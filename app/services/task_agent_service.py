"""Authenticated durable task lifecycle. Feature remains opt-in during acceptance."""
import copy
import hashlib
import json
import os
import secrets
import re
from typing import Literal
from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.agent_task import AgentTask, AgentRun
from app.services import purchase_draft_service as drafts


def now():
    return datetime.now(timezone.utc)

def stock_read_question(message):
    subject=re.search(r'\b(stock|inventory)\b|स्टॉक|स्टाक',message,re.I)
    question=re.search(r'\b(kitna|kitne|dikhao|batao|available|how much|show|check|quantities|left)\b|कितना|कितने|बताओ|दिखाओ',message,re.I)
    mutation=re.search(r'\b(kharid\w*|purchase|sale|sell|add|set|adjust|delete|entry)\b|खरीद|बेच|जोड़|घटा|बदलो|एंट्री',message,re.I)
    return bool(subject and question and not mutation)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=16, max_length=64)
    company_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    draft_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    outcome: Literal['answer','draft','verified_entry'] = 'verified_entry'


class TaskSelection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reference:str=Field(pattern=r'^[a-f0-9]{64}$')
    draft_revision:int=Field(ge=0)
    evidence_version:str=Field(min_length=1,max_length=128)

class TaskResume(BaseModel):
    retry_documents:bool=False
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    request_id: str = Field(min_length=16, max_length=64)
    message: str = Field(default='', max_length=4000)
    company_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')
    selection:TaskSelection|None=None
    context_refresh:bool=False


class TaskApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    token: str = Field(pattern=r'^[a-f0-9]{32}$')
    approve: bool


def enabled():
    if os.getenv('PHILIXA_TASK_AGENT_ENABLED', '0') != '1':
        raise HTTPException(503, 'Task agent acceptance pending; existing chat remains available.')


async def scoped(db, principal, ident, lock=False):
    from app.services.tally_business import admin
    admin(principal)
    query = select(AgentTask).where(AgentTask.id == ident,
        AgentTask.organization_id == principal.organization_id, AgentTask.user_id == principal.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if not row:
        raise HTTPException(404, 'Task unavailable.')
    if row.company_id:
        await drafts.company_for(db, principal, row.company_id)
    if row.state.get('attachment_document_ids'):
        from app.services.bill_document_service import document_for
        for ident in row.state['attachment_document_ids']:
            doc=await document_for(db,principal,ident)
            if doc.company_id!=row.company_id:raise HTTPException(404,'Task source unavailable.')
    return row


def view(row):
    state = row.state
    observations = state.get('observations', [])
    latest = observations[-1].get('data', {}) if observations else {}
    # Only server-produced presentation fields, never model-authored controls.
    presentation = {key:latest[key] for key in ('preview','proposal','evidence_version',
        'gst_purchase_draft','tally_action','sync_status','tally_status','mcp_report','mcp_form',
        'mcp_catalog','stock','stock_results','coverage','data_source','purchase_assistant',
        'purchase_context','purchase_details','suggestions','goods_receipt','receipt_ready','situation_choices','purchase_situation','repeat_purchase') if key in latest}
    if state.get('details_unknown'):
        presentation_summary=state['summary']
    elif (presentation.get('purchase_assistant') or presentation.get('stock_results')) and latest.get('response') and not state.get('wait_reason') and not any(
        issue.get('code','').startswith('provider_') or issue.get('code')=='quota_wait' for issue in state.get('issues',[])):
        # Identity-first domain questions outrank a model's generic missing-field list.
        presentation_summary=latest['response']
    else:presentation_summary=state.get('summary','Task saved.')
    if presentation.get('preview') and row.status != 'needs_approval':
        presentation['preview'] = {**presentation['preview'],'can_confirm':False}
    if not row.company_id and isinstance(latest.get('companies'),list):
        presentation['company_choices'] = latest['companies']
    from app.services.task_agent_selection import public_offers
    active_execution=bool(row.status=='running' and row.lease_until and row.lease_until>now())
    stage=('running' if active_execution else 'waiting_worker' if row.status=='queued' else
           'waiting_context' if row.status=='waiting_context' else 'recovering' if row.status=='running' else row.status)
    return dict(execution_stage=stage,progress_active=active_execution,**presentation, document_task=bool(state.get('attachment_document_ids')), attachment_sources=state.get('attachment_sources',[]), selections=public_offers(row),
        details_unknown=bool(state.get('details_unknown')),
        wait_reason=state.get('wait_reason'),retry_at=state.get('provider_retry_at'),auto_resume_until=state.get('auto_resume_until'),
        can_resume=row.status=='needs_input',task_id=row.id, task_revision=row.revision, revision=row.revision, status=row.status,
        response='Task saved hai. Worker ki queue mein hai; processing abhi shuru nahi hui.' if row.status=='queued' and not state.get('action_id') else presentation_summary if row.status=='needs_input' or (state.get('outcome')=='answer' and presentation.get('stock_results') and row.status=='completed') else state.get('summary','Task saved.'),
        draft_id=state.get('draft_id'), action_id=state.get('action_id'),
        issues=[*latest.get('issues',[]),*state.get('issues',[])], updated_at=row.updated_at.isoformat())


async def read(db, principal, ident):
    row = await scoped(db, principal, ident, True)
    from app.services.business_help import help_answer
    answer = help_answer((row.state.get('messages') or [''])[-1])
    if (answer and row.status in ('queued','waiting_context','needs_input')
            and not row.state.get('executions') and not row.state.get('draft_id')
            and not row.state.get('action_id')
            and (not row.lease_until or row.lease_until <= now())):
        # Recover old, unstarted help turns through the authenticated status read.
        state=copy.deepcopy(row.state)
        state.update(summary=answer,outcome='answer',issues=[])
        for key in ('wait_reason','provider_retry_at','auto_resume_until'):state.pop(key,None)
        row.state=state;row.status='completed';row.revision+=1;row.updated_at=now()
        await db.commit()
    from app.services.task_agent_runtime import settled_stock_answer
    answer=settled_stock_answer(row.state)
    if answer and row.status in ('needs_input','waiting_context'):
        state=copy.deepcopy(row.state)
        state.update(summary=answer['data']['response'],issues=[])
        for key in ('wait_reason','provider_retry_at','auto_resume_until'):state.pop(key,None)
        row.state=state;row.status='completed' if answer.get('verified') else 'needs_input'
        await db.commit()
    if row.status=='waiting_context' and row.state.get('auto_resume_until') and datetime.fromisoformat(row.state['auto_resume_until'])<=now():
        row.state={**row.state,'summary':'Task saved hai—Resume karein.','provider_retry_at':None}
        row.status='needs_input';row.updated_at=now();await db.commit()
    token = row.state.get('action_id')
    if not token and row.status=='verification_pending':
        pending=[e for e in row.state.get('executions',[]) if e.get('status')=='pending']
        # An invalid source is rejected before the draft adapter reaches any
        # mutation. Reconcile only that provable pre-mutation case.
        if len(pending)==1 and pending[0].get('tool')=='apply_user_message':
            from app.services.purchase_message import grounded, MessageFields
            args=pending[0].get('arguments',{})
            messages=row.state.get('messages',[])
            index=args.get('message_index',-1)
            invalid=index<0 or index>=len(messages)
            if not invalid:
                try:grounded(messages[index],MessageFields(updates=args.get('updates',[]),unsupported_reason=None))
                except ValueError:invalid=True
            draft=await drafts.scoped_draft(db,principal,args['draft_id'])
            if invalid and draft.company_id==row.company_id and not draft.action_id and draft.revision==args.get('revision'):
                state=copy.deepcopy(row.state)
                next(e for e in state['executions'] if e.get('status')=='pending')['status']='not_started'
                state['summary']='Source evidence rejected before draft change. Resume with exact message facts; no entry posted.'
                row.state=state;row.status='needs_input';await db.commit()
            elif not invalid and draft.company_id==row.company_id and not draft.action_id and draft.revision>args.get('revision',draft.revision):
                from app.services.bill_evaluation_service import flatten, equivalent
                current=flatten(draft.content)
                matches=bool(args.get('updates')) and all(equivalent(u['path'],current.get(u['path']),u['value']) for u in args['updates'])
                if matches:
                    state=copy.deepcopy(row.state)
                    next(e for e in state['executions'] if e.get('status')=='pending')['status']='draft_reconciled'
                    state['draft_revision']=draft.revision
                    state['summary']='Saved draft values reconciled after interruption. Evidence/review must resume; no Tally entry posted.'
                    row.state=state;row.status='needs_input';await db.commit()
    if not token and row.status=='verification_pending':
        pending=[e for e in row.state.get('executions',[]) if e.get('status')=='pending']
        if pending and all(e.get('tool')=='purchase_preview' for e in pending):
            draft=await drafts.scoped_draft(db,principal,pending[-1]['arguments']['draft_id'])
            if draft.company_id==row.company_id and not draft.action_id:
                state=copy.deepcopy(row.state)
                for event in state['executions']:
                    if event.get('status')=='pending':event['status']='validation_review'
                state['summary']='Draft saved; missing invoice/tax details need review. No entry posted.'
                row.state=state;row.status='needs_input';await db.commit()
    if not token and row.status=='verification_pending':
        pending=[e for e in row.state.get('executions',[]) if e.get('status')=='pending' and e.get('tool')=='evaluate_automation']
        if len(pending)==1 and pending[0].get('arguments',{}).get('draft_id'):
            draft=await drafts.scoped_draft(db,principal,pending[0]['arguments']['draft_id'])
            if draft.company_id==row.company_id and draft.action_id:
                token=draft.action_id
                row.state={**row.state,'action_id':token,'draft_id':draft.id}
    if token:
        from app.models.tally import TallyAction
        action = await db.get(TallyAction, token, populate_existing=True)
        if not action or action.organization_id != principal.organization_id or action.user_id != principal.user_id or action.company_id != row.company_id:
            raise HTTPException(409,'Task action binding changed.')
        status = {'queued':'queued','submitting':'verification_pending','verification_pending':'verification_pending',
            'verified':'completed','failed':'failed','needs_review':'needs_input','cancelled':'cancelled','expired':'needs_input'}.get(action.status)
        if status and row.status != status:
            from app.services.tally_sync import action_result
            row.status = status
            row.state = {**row.state,'summary':action_result(action)['response']}
            row.updated_at = now()
            await db.commit()
        else:
            await db.commit()
    from app.services.task_queue_health import annotate
    return await annotate(view(row))


async def approve(db, principal, ident, request):
    enabled()
    row = await scoped(db, principal, ident, True)
    if row.revision != request.expected_revision or row.state.get('action_id') != request.token:
        raise HTTPException(409,'Task approval changed; reload exact review.')
    if row.status not in ('needs_approval','queued','verification_pending','completed'):
        raise HTTPException(409,'Task has no approvable action.')
    if row.state.get('draft_id'):
        draft = await drafts.scoped_draft(db,principal,row.state['draft_id'])
        if draft.action_id != request.token:
            raise HTTPException(409,'Draft preview changed.')
    await db.commit()  # Existing action service owns posting lock and guards.
    from app.services.tally_business import confirm_action
    await confirm_action(db,principal,request.token,approve=request.approve,
        status_only=row.status in ('queued','verification_pending','completed'))
    return await read(db,principal,ident)


async def metrics(db,principal,ident):
    row=await scoped(db,principal,ident)
    runs=(await db.scalars(select(AgentRun).where(AgentRun.task_id==ident))).all()
    usage=[r.state['usage'] for r in runs if isinstance(r.state.get('usage'),dict)]
    prompt=sum(int(u.get('prompt_tokens',0)) for u in usage)
    output=sum(int(u.get('completion_tokens',0)) for u in usage)
    estimated=Decimal(prompt)*Decimal('0.075')/1000000+Decimal(output)*Decimal('0.30')/1000000
    reserved=sum((Decimal(r.state.get('reserved_usd','0')) for r in runs),Decimal(0))
    from app.models.groq_quota import GroqQuotaRequest
    requests=(await db.scalars(select(GroqQuotaRequest).where(GroqQuotaRequest.task_id==ident))).all()
    quota_events=[r.state['quota_wait'] for r in runs if 'quota_wait' in r.state]
    return {'task_id':ident,'status':row.status,'user_messages':len(row.state.get('messages',[])),
        'model_responses_with_usage':len(usage),'prompt_tokens':prompt,'completion_tokens':output,
        'estimated_model_cost_usd':str(estimated),'reserved_usd':str(reserved),
        'cost_basis':'GPT-OSS 20B list-price estimate, 2026-11-02; not an invoice or actual free-tier charge',
        'coverage':'Agent-decision usage only; extraction has separate telemetry. Uncertain calls retain their reservation.',
        'gateway_requests':len(requests),'gateway_estimated_tokens':sum(r.reserved_tokens for r in requests),
        'gateway_charged_tokens':sum(r.charged_tokens for r in requests),
        'gateway_latency_ms':sum(r.metadata_json.get('latency_ms',0) for r in requests),
        'gateway_cached_tokens':sum((r.metadata_json.get('usage',{}).get('prompt_tokens_details') or {}).get('cached_tokens',0) for r in requests),
        'quota_wait_events':quota_events,'time_savings_verified':False}


async def create(db, principal, request, *, routing_seed=None):
    enabled()
    from app.services.tally_business import admin
    admin(principal)
    if request.company_id:
        await drafts.company_for(db, principal, request.company_id)
    if request.draft_id:
        draft = await drafts.scoped_draft(db, principal, request.draft_id)
        if draft.company_id != request.company_id:
            raise HTTPException(422, 'Task and draft company must match.')
    data = request.model_dump(mode='json')
    # A bounded read intent cannot inherit purchase-posting completion rules.
    if stock_read_question(request.message):
        request=request.model_copy(update={'outcome':'answer'})
        data=request.model_dump(mode='json')
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    company_id = request.company_id
    if not company_id:
        permitted = (await drafts.list_companies(db,principal))['companies']
        if len(permitted) == 1:
            company_id = permitted[0]['id']
    stamp = now()
    company_identity=(await drafts.company_for(db,principal,company_id)).identity if company_id else None
    await db.execute(insert(AgentTask).values(id=secrets.token_hex(16),
        organization_id=principal.organization_id, user_id=principal.user_id,
        company_id=company_id, request_id=request.request_id, request_hash=digest,
        revision=0, status='queued', state=dict(messages=[request.message],
        draft_id=request.draft_id,company_identity=company_identity, outcome=request.outcome, session_id=principal.session_id, executions=[], observations=[], summary='Task queued.',routing_first_step=routing_seed),
        created_at=stamp, updated_at=stamp).on_conflict_do_nothing())
    row = await db.scalar(select(AgentTask).where(AgentTask.organization_id == principal.organization_id,
        AgentTask.user_id == principal.user_id, AgentTask.request_id == request.request_id))
    if row.request_hash != digest:
        raise HTTPException(409, 'Request ID reused with changed task.')
    await db.commit()
    await enqueue(row.id)
    return view(row)


async def resume(db, principal, ident, request, *, routing_seed=None):
    enabled()
    row = await scoped(db, principal, ident, True)
    if row.state.get('draft_id') and request.message.strip().casefold() in ('context status','tally context refresh'):
        request=request.model_copy(update={'context_refresh':True})
    previous = row.state.get('resume_requests', {})
    digest = hashlib.sha256(json.dumps([request.message,request.company_id,request.selection.model_dump() if request.selection else None]).encode()).hexdigest()
    if request.retry_documents:digest=hashlib.sha256((digest+':retry_documents').encode()).hexdigest()
    if request.context_refresh:digest=hashlib.sha256((digest+':context_refresh').encode()).hexdigest()
    if request.request_id in previous:
        if previous[request.request_id] != [request.expected_revision, digest]:
            raise HTTPException(409, 'Request ID reused with changed answer.')
        return view(row)
    if row.revision != request.expected_revision:
        raise HTTPException(409, 'Task changed; reload current task.')
    if row.status in ('running', 'verification_pending', 'completed', 'cancelled'):
        raise HTTPException(409, 'Task cannot accept a new answer in this state.')
    unknown=request.message.strip().casefold().rstrip('.!?।') in ('pata nahi','pata nhi','nahi pata','nhi pata','malum nahi','maloom nahi','i don\'t know','dont know','पता नहीं','पता नही')
    if unknown and row.state.get('draft_id') and not request.selection and not request.context_refresh and not request.company_id:
        state=copy.deepcopy(row.state)
        state.setdefault('resume_requests',{})[request.request_id]=[row.revision,digest]
        state.setdefault('messages',[]).append(request.message)
        state.update(details_unknown=True,summary='Theek hai, draft saved hai. Jo details pata nahi hain unhe abhi blank rakha hai. Bill ya sahi details milne par yahin se continue karenge; abhi Tally entry nahi hui.',issues=[])
        for key in ('selection_refresh','provider_retry_at','auto_resume_until','context_auto_until','wait_reason'):state.pop(key,None)
        db.add(AgentRun(id=secrets.token_hex(16),task_id=row.id,revision=row.revision,state=copy.deepcopy(row.state),created_at=now()))
        row.state=state;row.revision+=1;row.status='needs_input';row.updated_at=now()
        await db.commit()
        return view(row)
    if request.company_id:
        await drafts.company_for(db,principal,request.company_id)
        if row.company_id and row.company_id != request.company_id:
            raise HTTPException(409,'Start a separate task to change company.')
        row.company_id=request.company_id
    import os
    if not request.context_refresh and os.getenv('PHILIXA_TASK_SELECTIONS_ENABLED','0')=='1':
        from app.services.task_agent_selection import apply
        selected=await apply(db,principal,row,request)
        if selected:
            await enqueue(row.id)
            return view(row)
    if request.retry_documents and (not row.state.get('attachment_document_ids') or request.message or request.selection or request.company_id or request.context_refresh):
        raise HTTPException(422,'Retry needs an exact attachment task without other changes.')
    state = copy.deepcopy(row.state)
    if request.retry_documents:
        state.update(attachment_initial=True,attachment_retry=True)
        state.pop('attachment_generations',None)
    if routing_seed and routing_seed.get('tool')=='purchase_context':
        state['outcome']='draft'
        state['tool_groups']=list(dict.fromkeys([*state.get('tool_groups',[]),'documents','purchase']))
    state.pop('details_unknown',None)
    state.pop('context_auto_until',None)
    if request.company_id and not state.get('company_identity'):
        state['company_identity']=(await drafts.company_for(db,principal,request.company_id)).identity
    state.setdefault('resume_requests', {})[request.request_id] = [row.revision, digest]
    if request.message:
        state.setdefault('messages', []).append(request.message)
    # Prior evidence remains in the audit; a new segment gets a fresh call budget.
    db.add(AgentRun(id=secrets.token_hex(16), task_id=row.id, revision=row.revision,
        state=copy.deepcopy(row.state), created_at=now()))
    state.update(executions=[], observations=[], model_rounds=0, provider_retries=0,
        summary='Task queued.',session_id=principal.session_id,routing_first_step=routing_seed)
    if request.context_refresh:
        if not state.get('draft_id'):raise HTTPException(409,'No saved purchase draft to refresh.')
        state['selection_refresh']=True
    state.pop('provider_retry_at',None)
    for key in ('auto_resume_until','wait_reason'):state.pop(key,None)
    row.state = state
    row.revision += 1
    row.status = 'queued'
    row.updated_at = now()
    await db.commit()
    await enqueue(row.id)
    return view(row)


def wake_job_id(ident,revision):
    return f'agent-task:{ident}:{revision}'


async def enqueue(ident):
    # Redis is only a wake-up mechanism. The committed queued task is recovered
    # by the worker cron if Redis is temporarily unavailable.
    from arq.connections import create_pool, RedisSettings
    from app.core.config import get_settings
    from app.services.bill_document_service import QUEUE
    pool = None
    try:
        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        from app.database.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            task=await db.get(AgentTask,ident)
            if not task:return
            revision=task.revision
        await pool.enqueue_job('execute_agent_task',ident,revision,_queue_name=QUEUE,_job_id=wake_job_id(ident,revision))
    except Exception:
        pass
    finally:
        if pool:
            await pool.aclose()


async def cancel(db, principal, ident, revision):
    row = await scoped(db, principal, ident, True)
    if row.revision != revision:
        raise HTTPException(409, 'Task changed; reload current task.')
    if row.status == 'running' or row.state.get('action_id') or any(
        e.get('status') == 'pending' for e in row.state.get('executions', [])):
        raise HTTPException(409, 'Operation may be submitted; check its result before cancelling.')
    row.status = 'cancelled'
    row.state = {**row.state, 'summary': 'Unsent task cancelled; no Tally voucher deleted.'}
    row.revision += 1
    row.updated_at = now()
    await db.commit()
    return view(row)
