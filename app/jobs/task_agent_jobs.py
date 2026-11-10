"""Recoverable bounded agent segments on the existing document queue."""
import copy
import os
import secrets
from datetime import datetime,timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from sqlalchemy import select, text, or_
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask, AgentRun, AgentExecution
from app.services.task_agent_service import now,wake_job_id


def billing_limits():
    mode=os.getenv('PHILIXA_TASK_AGENT_BILLING_MODE','paid')
    if mode == 'free':
        if os.getenv('PHILIXA_GROQ_FREE_TIER_CONFIRMED','0') != '1':
            raise ValueError('Verify Groq account Free tier before enabling free calls')
        return mode,Decimal(0),Decimal(0)
    if mode != 'paid':
        raise ValueError('Unknown agent billing mode')
    cap=Decimal(os.getenv('PHILIXA_TASK_AGENT_DAILY_USD','0'))
    reserve=Decimal('0.02')
    if not cap.is_finite() or cap < reserve:
        raise ValueError('Agent daily budget is unset or exhausted')
    return mode,cap,reserve


async def principal_for(db, row):
    from app.models.user import User
    from app.models.organization import Organization
    from app.models.organization_membership import OrganizationMembership
    from app.models.user_session import UserSession
    from fastapi import HTTPException
    member = await db.get(OrganizationMembership, (row.user_id, row.organization_id), populate_existing=True)
    user = await db.get(User, row.user_id, populate_existing=True)
    org = await db.get(Organization, row.organization_id, populate_existing=True)
    session = await db.get(UserSession, row.state.get('session_id'), populate_existing=True)
    if not member or member.status != 'active' or member.role not in ('owner','admin') or not user or not user.is_active or not org or not org.is_active:
        raise HTTPException(403, 'Task permissions changed.')
    if not session or session.user_id != row.user_id or session.organization_id != row.organization_id or session.revoked_at or session.expires_at <= now():
        raise HTTPException(403, 'Task session expired; sign in again.')
    if row.company_id and row.state.get('company_identity'):
        from app.models.tally import TallyReadCompany
        company=await db.get(TallyReadCompany,row.company_id,populate_existing=True)
        if not company or not company.enabled or company.organization_id!=row.organization_id or company.identity!=row.state['company_identity']:
            raise HTTPException(403,'Task native company identity changed.')
    return SimpleNamespace(user_id=row.user_id, organization_id=row.organization_id,
        role=member.role, session_id=session.id)


def quota_wait(state,exc,stamp):
    """Persisted deadline, independent from worker/process lifetime."""
    result=copy.deepcopy(state)
    result['wait_reason']=exc.reason
    deadline=datetime.fromisoformat(result['auto_resume_until']) if result.get('auto_resume_until') else stamp+timedelta(seconds=120)
    result['auto_resume_until']=deadline.isoformat()
    eligible=exc.reason in ('minute_quota','provider_unavailable') and exc.retry_at and exc.retry_at<=deadline and stamp<deadline
    if exc.sent and result.get('provider_retries',0)>=1:eligible=False
    if eligible:
        if exc.sent:result['provider_retries']=result.get('provider_retries',0)+1
        result.update(status='waiting_context',provider_retry_at=exc.retry_at.isoformat(),
            summary='Details saved hain. Thodi der mein automatically continue hoga.')
    else:
        result.pop('provider_retry_at',None)
        result.update(status='needs_input',summary='Task saved hai—Resume karein.' if exc.reason!='request_too_large' else 'Task saved hai. Context bahut bada hai; narrower details se resume karein.')
    return result

async def execute_agent_task(ctx, task_id, expected_revision=None):
    if os.getenv('PHILIXA_TASK_AGENT_ENABLED','0') != '1':
        return
    from app.services.task_agent_runtime import run
    from app.services.task_agent_tools import registry
    from app.services.task_agent_model import choose
    from app.services.purchase_checkpoint import PurchaseSaver
    from langgraph.graph import StateGraph, END
    from typing import TypedDict
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(AgentTask).where(AgentTask.id == task_id).with_for_update())
        if row and expected_revision is not None and row.revision!=expected_revision:return
        if row and row.state.get('auto_resume_until') and datetime.fromisoformat(row.state['auto_resume_until'])<=now() and row.status in ('waiting_context','queued'):
            row.status='needs_input';row.state={**row.state,'summary':'Task saved hai—Resume karein.','provider_retry_at':None};await db.commit();return
        if row and row.status=='waiting_context' and row.state.get('provider_retry_at'):
            if datetime.fromisoformat(row.state['provider_retry_at']) <= now():row.status='queued'
        if not row or row.status not in ('queued','running'):
            return
        if row.lease_until and row.lease_until > now():
            return
        token = secrets.token_hex(16)
        row.lease_token = token
        row.lease_until = now()+timedelta(minutes=10)
        row.status = 'running'
        revision = row.revision
        state = copy.deepcopy(row.state)
        state['task_id']=row.id
        state['company_id']=row.company_id
        state.pop('provider_retry_at',None)
        await db.commit()
        reservation_id=None

        async def persist(current):
            current = copy.deepcopy(current)
            latest=(current.get('observations') or [{}])[-1].get('data',{})
            context_status=latest.get('purchase_context',{}).get('native_history_status')
            if current.get('status')=='needs_input' and context_status in ('pending','queued','processing','stale') and not current.get('details_unknown'):
                deadline=current.setdefault('context_auto_until',(now()+timedelta(seconds=120)).isoformat())
                if now()+timedelta(seconds=5)<datetime.fromisoformat(deadline):
                    current.update(status='waiting_context',selection_refresh=True,
                        provider_retry_at=(now()+timedelta(seconds=5)).isoformat(),
                        summary='Tally se supplier/rate check ho rahe hain. Draft saved hai; result khud aa jayega.')
            elif context_status in ('ready','error','unavailable','needs_identity'):
                current.pop('context_auto_until',None)
            locked = await db.scalar(select(AgentTask).where(AgentTask.id == task_id).with_for_update().execution_options(populate_existing=True))
            if locked.lease_token != token or locked.revision != revision or locked.status == 'cancelled':
                raise ValueError('Task lease changed')
            locked.state = current
            locked.status = current.get('status','running')
            locked.updated_at = now()
            locked.lease_until = now()+timedelta(minutes=10)
            from sqlalchemy.dialects.postgresql import insert
            for event in current.get('executions',[]):
                await db.execute(insert(AgentExecution).values(id=secrets.token_hex(16), task_id=task_id,
                    revision=revision, call_key=event['key'], data=event, created_at=now()).on_conflict_do_update(
                    index_elements=['task_id','revision','call_key'], set_={'data':event}))
            await db.commit()
            if current.get('status')=='waiting_context' and current.get('selection_refresh') and ctx.get('redis'):
                from app.services.bill_document_service import QUEUE
                try:
                    await ctx['redis'].enqueue_job('execute_agent_task',task_id,revision,_queue_name=QUEUE,
                        _defer_until=datetime.fromisoformat(current['provider_retry_at']),
                        _job_id=f'agent-context:{task_id}:{revision}:{current["provider_retry_at"]}')
                except Exception:
                    pass # Committed waiting state is recovered by the cron.

        async def budget():
            nonlocal reservation_id
            reservation_id=None
            # Reserve a conservative amount before every paid call. Never refund
            # an uncertain call. Default zero keeps new paid work disabled.
            mode,cap,reserve=billing_limits()
            await db.execute(text('SELECT pg_advisory_xact_lock(73925,1)'))
            day_start = now().astimezone(ZoneInfo('Asia/Kolkata')).replace(hour=0,minute=0,second=0,microsecond=0)
            runs = (await db.scalars(select(AgentRun).where(AgentRun.created_at >= day_start))).all()
            from app.models.business_route import BusinessRoute
            routes=(await db.scalars(select(BusinessRoute).where(BusinessRoute.created_at>=day_start))).all()
            used = sum((Decimal(r.state.get('reserved_usd','0')) for r in runs), Decimal(0))
            used += sum((Decimal(r.telemetry.get('reserved_usd','0')) for r in routes),Decimal(0))
            from app.ai.groq_gateway import free_call_limit
            local_limit=free_call_limit()
            if mode == 'free' and local_limit is not None and sum(bool(r.state.get('free_call')) for r in runs)+sum(bool(r.telemetry.get('free_call')) for r in routes) >= local_limit:
                from app.ai.groq_gateway import QuotaDeferred
                raise QuotaDeferred('local_cap')
            if mode == 'paid' and used+reserve > cap:
                raise ValueError('Agent daily budget exhausted')
            reservation_id=secrets.token_hex(16)
            db.add(AgentRun(id=reservation_id,task_id=task_id,revision=revision,
                state={'reserved_usd':str(reserve),'free_call':mode=='free'},created_at=now()))
            await db.commit()

        async def model(current, schemas):
            from app.ai.groq_gateway import context
            with context(task_id=task_id,revision=revision):decision, usage = await choose(current, schemas)
            current['issues']=[i for i in current.get('issues',[]) if i.get('code') != 'quota_wait' and not str(i.get('code','')).startswith('provider_')]
            current.pop('wait_reason', None)
            current.pop('provider_retry_at', None)
            db.add(AgentRun(id=secrets.token_hex(16),task_id=task_id,revision=revision,
                state={'usage':usage},created_at=now()))
            await db.commit()
            return decision

        async def completed(current):
            # Only the task's current purchase action can prove its write done.
            # A historical observation, a draft, or an unrelated read cannot.
            if current.get('outcome') == 'answer':
                return bool(current.get('observations') and current['observations'][-1].get('verified') and
                    all(e.get('effect')=='read' and e.get('status')=='settled' for e in current.get('executions',[])))
            if current.get('outcome') == 'draft' and current.get('draft_id'):
                from app.services.purchase_draft_service import scoped_draft
                await scoped_draft(db,await principal_for(db,row),current['draft_id'])
                return True
            if not current.get('draft_id'):
                return False
            from app.services.purchase_draft_service import scoped_draft
            from app.models.tally import TallyAction
            principal = await principal_for(db,row)
            draft = await scoped_draft(db,principal,current['draft_id'])
            action = await db.get(TallyAction,draft.action_id,populate_existing=True) if draft.action_id else None
            return bool(action and action.status == 'verified' and action.company_id == row.company_id)

        try:
            principal = await principal_for(db, row)
            if state.get('attachment_initial'):
                from app.services.chat_attachments import advance
                state=await advance(db,principal,state,row.company_id,queue=ctx.get('redis'))
                if state.get('attachment_initial') or state.get('issues') or not any(message.strip() for message in state.get('messages',[])):
                    await persist(state)
                    return
                state['status']='running'
            from app.services.intent_router import is_bill_entry_intent
            has_entry = state.get('outcome') == 'verified_entry' or any(is_bill_entry_intent(m) for m in state.get('messages', []))
            if state.get('draft_id') and has_entry:
                state['outcome'] = 'verified_entry'
                state['tool_groups'] = list(dict.fromkeys([*state.get('tool_groups', []), 'documents', 'purchase']))
                if not state.get('routing_first_step') and not state.get('executions'):
                    state['routing_first_step'] = {'kind': 'tool', 'tool': 'purchase_context', 'arguments': {'draft_id': state['draft_id']}, 'summary': 'Saved bill ki purchase validation check kar rahi hoon.'}
            if state.get('attachment_document_ids'):
                state['tool_groups']=list(dict.fromkeys([*state.get('tool_groups',[]),'documents',*(['purchase'] if state.get('draft_id') and state.get('outcome')!='answer' else [])]))
                from app.services.chat_attachments import source_context
                state['attachment_sources']=await source_context(db,principal,state,row.company_id)
                if any(state.get('attachment_generations',{}).get(source['document_id'],source['extraction_generation'])!=source['extraction_generation'] for source in state['attachment_sources']):
                    state.update(status='needs_input',summary='Bill extraction changed. Original aur latest draft review karke dobara continue karein.',issues=[{'code':'source_generation_changed'}])
                    await persist(state)
                    return
                state['observations']=[{'status':'ok','verified':True,'data':{'attachment_sources':state['attachment_sources']}}]
            from app.services.purchase_situation import extract as situation_facts
            if state.get('draft_id') and state.get('messages') and situation_facts(state['messages'][-1]):
                from app.services.purchase_draft_service import scoped_draft
                from app.services.purchase_situation import capture
                draft=await scoped_draft(db,principal,state['draft_id'])
                if draft.company_id!=row.company_id:raise ValueError('Draft company changed')
                await capture(db,principal,draft,state['messages'][-1])
            if state.pop('selection_refresh',False):
                # The user's exact choice is already committed. Refresh scoped
                # context and ask the domain question without a planner call.
                from app.services.purchase_situation import state as proposal
                result=await proposal(db,principal,state['draft_id'])
                current_revision=(result.get('proposal') or {}).get('revision')
                if isinstance(current_revision,int) and current_revision!=state.get('draft_revision'):
                    state['draft_revision']=current_revision
                    state.pop('action_id',None)
                state.update(observations=[{'status':'ok','data':result,'verified':False}],
                    summary=result['response'],status='needs_input',issues=[])
                await persist(state)
                return
            if state.get('draft_id'):
                from app.services.purchase_draft_service import scoped_draft
                draft=await scoped_draft(db,principal,state['draft_id'])
                if draft.company_id!=row.company_id:raise ValueError('Draft company changed')
                # Resume starts a new planner segment, not a new purchase.
                # Rehydrate authoritative context before the planner can ask
                # questions; capture bounded situation evidence directly from
                # the original user answer, never from a model summary.
                if not state.get('attachment_document_ids'):
                    from app.services.purchase_situation import state as proposal
                    result=await proposal(db,principal,draft.id)
                    draft=await scoped_draft(db,principal,draft.id)
                    state['observations']=[{'status':'ok','data':result,'verified':False}]
                # Document Q&A needs source facts, not an unsolicited Tally-history sync.
                state['draft_revision']=draft.revision
                state['prefetched_draft']={'id':draft.id,'revision':draft.revision,
                    'content':copy.deepcopy(draft.content),'observed_at':now().isoformat()}
            tools = registry(db, principal, row.company_id, state)
            # Rehydrate live authority before each tool, not just at job startup.
            from dataclasses import replace
            guarded = []
            for tool in tools:
                async def auth(args, original=tool.authorize):
                    fresh = await principal_for(db, row)
                    principal.role = fresh.role
                    await original(args)
                async def execute(args, original=tool.execute, name=tool.name):
                    return await original(args)
                guarded.append(replace(tool, authorize=auth, execute=execute))
            class GraphState(TypedDict):
                task: dict
            async def segment(s):
                return {'task':await run(s['task'], guarded, model, persist, budget, completed)}
            graph = StateGraph(GraphState)
            graph.add_node('segment',segment)
            graph.set_entry_point('segment')
            graph.add_edge('segment',END)
            workflow = graph.compile(checkpointer=PurchaseSaver(AsyncSessionLocal))
            await workflow.ainvoke({'task':state}, {'configurable':{'thread_id':f'agent:{task_id}:{revision}'},'recursion_limit':3},durability='sync')
        except Exception as exc:
            await db.rollback()
            row = await db.get(AgentTask,task_id,populate_existing=True)
            if row and row.lease_token == token:
                pending = any(e.get('status')=='pending' and e.get('effect')!='read' for e in row.state.get('executions',[]))
                row.status = 'verification_pending' if pending else 'needs_input'
                row.state = {**row.state,'summary':'Task saved; execution needs review. No success assumed.',
                    'issues':[{'code':type(exc).__name__}]}
                from app.services.task_agent_model import AgentProviderUnavailable
                from app.ai.groq_gateway import QuotaDeferred
                if isinstance(exc,QuotaDeferred) and not pending:
                    if not exc.sent and reservation_id:
                        row.state={**row.state,'model_rounds':max(0,row.state.get('model_rounds',0)-1)}
                        reserved=await db.get(AgentRun,reservation_id) if reservation_id else None
                        if reserved:reserved.state={**reserved.state,'reserved_usd':'0','free_call':False,'not_sent':True}
                    row.state=quota_wait(row.state,exc,now());row.status=row.state['status']
                    row.state={**row.state,'issues':[{'code':'quota_wait','reason':exc.reason}]}
                    db.add(AgentRun(id=secrets.token_hex(16),task_id=task_id,revision=revision,
                        state={'quota_wait':{'reason':exc.reason,'at':now().isoformat(),
                            'retry_at':exc.retry_at.isoformat() if exc.retry_at else None,
                            'auto_resume_until':row.state['auto_resume_until'],'sent':exc.sent}},created_at=now()))
                if isinstance(exc,AgentProviderUnavailable) and not pending:
                    row.state={**row.state,'summary':exc.safe_message,'issues':[{'code':exc.code,'http_status':exc.status,'diagnostic':exc.diagnostic}]}
                    if exc.status in (429,503) and row.state.get('provider_retries',0)<1:
                        fallback=QuotaDeferred('minute_quota' if exc.status==429 else 'provider_unavailable',now()+timedelta(seconds=65),sent=True,status=exc.status)
                        row.state=quota_wait(row.state,fallback,now());row.status=row.state['status']
                await db.commit()
                if row.status=='waiting_context' and row.state.get('provider_retry_at') and ctx.get('redis'):
                    from app.services.bill_document_service import QUEUE
                    await ctx['redis'].enqueue_job('execute_agent_task',task_id,revision,_queue_name=QUEUE,
                        _defer_until=datetime.fromisoformat(row.state['provider_retry_at']),
                        _job_id=f'agent-provider-retry:{task_id}:{revision}')
        finally:
            row = await db.get(AgentTask,task_id,populate_existing=True)
            if row and row.lease_token == token:
                row.lease_token = None
                row.lease_until = None
                await db.commit()


async def recover_agent_tasks(ctx):
    if os.getenv('PHILIXA_TASK_AGENT_ENABLED','0') != '1':
        return
    from app.services.chat_attachments import wake
    await wake(ctx)
    async with AsyncSessionLocal() as db:
        from app.models.bill_document import BillDocument
        waiting=(await db.scalars(select(AgentTask).where(AgentTask.status=='waiting_context').limit(50))).all()
        for task in waiting:
            if task.state.get('auto_resume_until') and datetime.fromisoformat(task.state['auto_resume_until'])<=now():
                task.status='needs_input';task.state={**task.state,'provider_retry_at':None,'summary':'Task saved hai—Resume karein.'};continue
            retry_at=task.state.get('provider_retry_at')
            if retry_at:
                if datetime.fromisoformat(retry_at)<=now():task.status='queued'
                continue
            doc_id=task.state.get('waiting_document_id')
            if not doc_id:
                continue
            doc=await db.get(BillDocument,doc_id,populate_existing=True)
            if not doc or doc.organization_id!=task.organization_id or doc.user_id!=task.user_id or doc.company_id!=task.company_id or doc.trashed_at:
                task.status='needs_input'
                task.state={**task.state,'summary':'Source document unavailable; review task.'}
            elif doc.extraction_status not in (None,'queued','processing'):
                # Resume only after the external job changes terminal state;
                # preserve execution evidence to avoid another extraction call.
                task.status='queued'
                task.state={**task.state,'summary':'Document processing finished; reviewing result.'}
        await db.commit()
        pending = (await db.execute(select(AgentTask.id,AgentTask.revision).where(AgentTask.status.in_(['queued','running']),
            or_(AgentTask.lease_until.is_(None),AgentTask.lease_until <= now())).limit(50))).all()
    for ident,revision in pending:
        from app.services.bill_document_service import QUEUE
        await ctx['redis'].enqueue_job('execute_agent_task',ident,revision,_queue_name=QUEUE,_job_id=wake_job_id(ident,revision))
