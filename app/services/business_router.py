"""Authenticated server-owned dispatch, persistent decisions and task focus."""
import copy
import asyncio
import hashlib
import json
import os
import secrets
import time
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select,text
from sqlalchemy.dialects.postgresql import insert
from app.models.business_route import BusinessRoute
from app.models.agent_task import AgentTask,AgentRun
from app.services import task_agent_service as tasks
from app.services import purchase_draft_service as drafts
from app.services.intent_router import VERSION,RouteDecision,fast_route,validate_evidence,first_step

LEGACY_READS={'supplier_list','supplier_read','customer_list','customer_read','task_list',
              'customer_history','portfolio_history','mcp_read'}


def enabled():return os.getenv('PHILIXA_INTENT_ROUTER_ENABLED','0')=='1'


def frontdoor_enabled():
    # An enabled task agent must never treat unclassified conversation as a
    # verified-entry task. Full context/seed rollout remains a separate gate.
    return enabled() or os.getenv('PHILIXA_TASK_AGENT_ENABLED','0')=='1'



def clarification(message,code='clarification'):
    return {'response':message,'status':'needs_input','response_kind':'routing_clarification',
            'issues':[{'code':code,'message':message}],'can_resume':False}


async def context_for(db,principal,request):
    from app.services.business_conversation_service import scoped_conversation
    conversation=None
    if request.conversation_id:
        conversation=await scoped_conversation(db,principal,request.conversation_id)
        if request.conversation_revision is not None and conversation.revision!=request.conversation_revision:
            raise HTTPException(409,'Chat changed; reload before sending.')
    latest=None
    if conversation:
        latest=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
            BusinessRoute.user_id==principal.user_id,BusinessRoute.conversation_id==conversation.id,
            BusinessRoute.status=='completed').order_by(BusinessRoute.created_at.desc()).limit(1))
    prior=(latest.context_data if latest else {})
    # Authoritative attachment links, never transcript JSON task references.
    from app.models.chat_attachment import ChatBillMessage
    attachment_message=await db.scalar(select(ChatBillMessage).where(
        ChatBillMessage.conversation_id==conversation.id,
        ChatBillMessage.organization_id==principal.organization_id,
        ChatBillMessage.user_id==principal.user_id).order_by(ChatBillMessage.created_at.desc(),ChatBillMessage.id.desc()).limit(1)) if conversation else None
    attachment_task=await tasks.scoped(db,principal,attachment_message.task_id) if attachment_message else None
    task_id=request.task_id or (attachment_task.id if attachment_task and (not latest or attachment_message.created_at>latest.created_at)
        else prior.get('foreground_task_id')) or (attachment_task.id if attachment_task else None) or request.candidate_task_id
    task=await tasks.scoped(db,principal,task_id) if task_id else None
    explicit_control=bool(request.selection or request.context_refresh)
    if request.task_id and explicit_control and request.expected_revision is None:raise HTTPException(422,'Task revision required.')
    if request.task_id and request.expected_revision is not None and task.revision!=request.expected_revision:raise HTTPException(409,'Task changed; reload current task.')
    company_id=request.fields.company_id or (task.company_id if task else None)
    if not company_id:
        companies=(await drafts.list_companies(db,principal))['companies']
        if len(companies)==1:company_id=companies[0]['id']
    company=await drafts.company_for(db,principal,company_id) if company_id else None
    if task and task.company_id and company_id!=task.company_id and request.task_id and explicit_control:
        raise HTTPException(409,'Task company changed; start a separate task.')
    if task and task.company_id and company_id!=task.company_id:
        # Explicit new company without a task reference starts a separate context.
        task=None
    if task and task.state.get('company_identity') and company and task.state['company_identity']!=company.identity:
        raise HTTPException(409,'Task native company identity changed; start a fresh task.')
    if not attachment_task and task and task.state.get('attachment_document_ids'):attachment_task=task
    attachment_index=[];attachment_documents=[];attachment_complete=True
    if attachment_task and attachment_task.company_id==company_id:
        from app.services.chat_attachments import source_context
        ids=attachment_task.state.get('attachment_document_ids',[])
        attachment_documents=ids[:10];attachment_complete=len(ids)<=10
        sources=await source_context(db,principal,{'attachment_document_ids':attachment_documents},company_id)
        remaining=20
        for source in sources:
            if remaining<=0:
                attachment_complete=False
                break
            take=min(remaining,len(source['drafts']))
            attachment_index.append({'document_id':source['document_id'],'filename':source['filename'][:200],
                'status':source['extraction_status'],'generation':source['extraction_generation'],
                'drafts':[{'id':d['id'],'revision':d['revision'],'invoice_number':d.get('content',{}).get('invoice_number'),
                           'pages':(d.get('extraction_metadata') or {}).get('source_pages',[])} for d in source['drafts'][:take]]})
            remaining-=take
            attachment_complete=attachment_complete and len(source['drafts'])<=take
    state=task.state if task else {}
    draft=None;draft_unavailable=False
    if state.get('draft_id'):
        try:draft=await drafts.scoped_draft(db,principal,state['draft_id'])
        except HTTPException as exc:
            if exc.status_code!=404:raise
            draft_unavailable=True
    if draft and draft.company_id!=task.company_id:raise HTTPException(409,'Draft company changed.')
    from app.services.task_agent_selection import offers
    # Native offer labels are data only; selection service revalidates at dispatch.
    choices=[o['value'] for o in offers(task) if o['kind']=='identity'] if task else []
    focused=bool(task and (not latest or latest.result.get('task_id')==task.id))
    last_observation=(state.get('observations') or [{}])[-1].get('data',{})
    question=(last_observation.get('purchase_assistant') or {}).get('field')
    context={'conversation_id':conversation.id if conversation else None,
        'prior_route_id':latest.id if latest else None,
        'conversation_revision':conversation.revision if conversation else None,
        'task_id':task.id if task else None,'task_revision':task.revision if task else None,
        'task_status':task.status if task else None,'focused':focused,
        'foreground_task_id':task.id if task else None,
        'can_continue':bool(task and not draft_unavailable and task.status in ('needs_input','queued','waiting_context','needs_approval')),
        'draft_unavailable':draft_unavailable,
        'company_id':company_id,'company_identity':company.identity if company else None,
        'draft_id':draft.id if draft else None,'draft_revision':draft.revision if draft else None,
        'draft_lines':[{k:line.get(k) for k in ('item_name','quantity','unit','rate')} for line in (draft.content.get('lines') or [])[:20]] if draft else [],
        'choices':choices[:30],'pending_field':question,'message_count':len(state.get('messages',[])),
        'recent_messages':[{'role':m['role'],'text':m.get('text','')[:1000]} for m in conversation.messages[-6:]] if conversation else
            [{'role':'user','text':m[:1000]} for m in state.get('messages',[])[-3:]],
        'attachment_index':attachment_index,'attachment_index_complete':attachment_complete,
        'attachment_document_ids':attachment_documents}

    return context


async def reserve_model(db,row):
    """Shares the agent's daily cap and advisory lock; no HTTP while locked."""
    from app.jobs.task_agent_jobs import billing_limits
    from app.ai.groq_gateway import QuotaDeferred
    mode,cap,reserve=billing_limits()
    await db.execute(text('SELECT pg_advisory_xact_lock(73925,1)'))
    day_start=tasks.now().astimezone(ZoneInfo('Asia/Kolkata')).replace(hour=0,minute=0,second=0,microsecond=0)
    runs=(await db.scalars(select(AgentRun).where(AgentRun.created_at>=day_start))).all()
    routes=(await db.scalars(select(BusinessRoute).where(BusinessRoute.created_at>=day_start))).all()
    used=sum((Decimal(r.state.get('reserved_usd','0')) for r in runs),Decimal(0))
    used+=sum((Decimal(r.telemetry.get('reserved_usd','0')) for r in routes),Decimal(0))
    calls=sum(bool(r.state.get('free_call')) for r in runs)+sum(bool(r.telemetry.get('free_call')) for r in routes)
    from app.ai.groq_gateway import free_call_limit
    local_limit=free_call_limit()
    if mode=='free' and local_limit is not None and calls>=local_limit:raise QuotaDeferred('local_cap')
    if mode=='paid' and used+reserve>cap:raise QuotaDeferred('local_cap')
    row.telemetry={**row.telemetry,'reserved_usd':str(reserve),'free_call':mode=='free','model_attempts':1}
    row.status='classifying';await db.commit()


async def assert_fresh(db,principal,request,context,check_task=True):
    from types import SimpleNamespace
    from app.jobs.task_agent_jobs import principal_for
    await principal_for(db,SimpleNamespace(user_id=principal.user_id,organization_id=principal.organization_id,
        company_id=context.get('company_id'),state={'session_id':principal.session_id,
        'company_identity':context.get('company_identity')}))
    if context.get('conversation_id'):
        from app.services.business_conversation_service import scoped_conversation
        conv=await scoped_conversation(db,principal,context['conversation_id'],lock=True)
        if conv.revision!=context['conversation_revision']:raise HTTPException(409,'Chat changed during routing; reload.')
        latest=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
            BusinessRoute.user_id==principal.user_id,BusinessRoute.conversation_id==conv.id,
            BusinessRoute.status=='completed').order_by(BusinessRoute.created_at.desc()).limit(1))
        if (latest.id if latest else None)!=context.get('prior_route_id'):
            raise HTTPException(409,'Conversation focus changed; reload.')
    if check_task and context.get('task_id'):
        task=await tasks.scoped(db,principal,context['task_id'],True)
        if task.revision!=context['task_revision']:raise HTTPException(409,'Task changed during routing; reload.')
    if context.get('company_id'):
        company=await drafts.company_for(db,principal,context['company_id'])
        if company.identity!=context['company_identity']:raise HTTPException(409,'Native company identity changed.')
    if check_task and context.get('draft_id'):
        draft=await drafts.scoped_draft(db,principal,context['draft_id'],lock=True)
        if draft.revision!=context['draft_revision']:raise HTTPException(409,'Draft changed during routing; reload.')


async def dispatch(db,principal,request,row,decision,context):
    from app.services.business_help import reply
    if decision.handler=='direct_reply':
        answer=(decision.conversational_reply if decision.conversational_reply else
            'Namaste! Batao, kya kaam karna hai?')
        return {**reply(answer),'response_kind':'smalltalk' if decision.intent=='smalltalk' else 'product_help'}
    if decision.handler=='clarify':
        if decision.intent=='unsupported' and decision.conversational_reply:
            return {**reply(decision.conversational_reply),'response_kind':'capability_limitation'}
        return clarification(decision.clarification or 'Aap kya poochhna ya karwana chahte hain? Thoda clear bata dein.')
    if decision.handler=='domain_read':
        if decision.intent=='existing_read':
            if request.intent not in LEGACY_READS:raise HTTPException(422,'Typed read control required.')
            from app.services.portfolio_copilot_service import run_business_graph
            return await run_business_graph(request,principal,db)
        if not context.get('company_id'):
            return clarification('Kis connected company ka data dekhna hai? Company select karein.','company_required')
        from app.services.task_agent_tools import registry
        tool_name='read_stock' if decision.intent=='stock_read' else 'read_report'
        tool=next(t for t in registry(db,principal,context['company_id'],{}) if t.name==tool_name)
        arguments={'item_name':decision.item_name or '*'} if tool_name=='read_stock' else {
            'report':decision.report,**{d.field:d.value for d in decision.report_dates}}
        arguments=tool.arguments.model_validate(arguments).model_dump()
        await tool.authorize(arguments)
        await db.commit()
        result=await tool.execute(arguments)
        return {**result.data,'response':result.data.get('response','Current data nahi mil saka.'),
            'status':'completed' if result.verified else 'needs_input','response_kind':'domain_read',
            'can_resume':False}
    if decision.handler=='domain_document':
        from app.services.chat_attachments import source_context,referenced_bill_ids
        state={'attachment_document_ids':context.get('attachment_document_ids',[]),'messages':[request.text]}
        sources=await source_context(db,principal,state,context.get('company_id'))
        current_index={d['id']:(d['revision'],source['extraction_generation']) for source in sources for d in source['drafts']}
        for source in context.get('attachment_index',[]):
            for d in source['drafts']:
                if current_index.get(d['id'])!=(d['revision'],source['generation']):
                    raise HTTPException(409,'Bill changed during routing; ask again using current bill.')
        choices=[(source,draft) for source in sources for draft in source['drafts']]
        matching=referenced_bill_ids(request.text,choices)
        target=decision.target_draft_id
        if len(choices)==1 and not matching:matching=[choices[0][1]['id']]
        if len(matching)!=1 or (target and target!=matching[0]):
            return {**clarification('Kaunsa bill check karun? Invoice number ya pehla/doosra bill batayein.','document_reference_required'),
                'bill_choices':[{'filename':source['filename'],'invoice_number':draft.get('content',{}).get('invoice_number')} for source,draft in choices]}
        from app.services.task_agent_tools import registry
        tool=next(t for t in registry(db,principal,context['company_id'],state) if t.name=='read_bill_fields')
        args=tool.arguments.model_validate({'draft_id':matching[0],'fields':decision.document_fields}).model_dump()
        await tool.authorize(args);await db.commit()
        result=await tool.execute(args)
        return {**result.data,'status':'completed' if result.verified else 'needs_input',
            'response_kind':'document_answer','can_resume':False}
    # Compatibility rollout: existing domain agent still owns the business
    # workflow. New grounded seeds stay OFF until the full evaluation gate passes.
    # Social/help/read turns have already returned and cannot create such tasks.
    seed=first_step(decision,context) if enabled() or decision.intent=='bill_processing' else None
    if decision.handler=='domain_continuation':
        if request.fields.company_id and request.fields.company_id!=context.get('company_id'):
            raise HTTPException(409,'Correction company mismatch.')
        # If the last turn changed topic, typed choices or explicit corrections are
        # required; a generic acknowledgement cannot implicitly approve anything.
        return await tasks.resume(db,principal,context['task_id'],tasks.TaskResume(
            expected_revision=context['task_revision'],request_id=row.id,message=request.text,
            company_id=context.get('company_id'),selection=request.selection,context_refresh=request.context_refresh),routing_seed=seed)
    request_create=tasks.TaskCreate(message=request.text,request_id=row.id,company_id=context.get('company_id'),
        outcome='answer' if decision.intent in ('stock_read','report_read') else 'verified_entry')
    return await tasks.create(db,principal,request_create,routing_seed=seed)


async def route(db,principal,request):
    from app.services.tally_business import admin
    admin(principal)
    if not request.request_id:raise HTTPException(422,'Routing request ID required.')
    if request.selection:
        try:tasks.TaskSelection.model_validate(request.selection)
        except ValueError:raise HTTPException(422,'Invalid selection reference.') from None
    started=time.monotonic()
    data=request.model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    # Replays are looked up before current revision validation: their own edit may
    # have advanced the task. Recheck ownership/permissions before returning data.
    existing=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
        BusinessRoute.user_id==principal.user_id,BusinessRoute.request_id==request.request_id))
    if existing:
        if existing.input_hash!=digest:raise HTTPException(409,'Request ID reused with changed message.')
        return await replay(db,principal,existing)
    if request.conversation_id:
        from app.services.business_conversation_service import scoped_conversation
        await scoped_conversation(db,principal,request.conversation_id,lock=True)
        active=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
            BusinessRoute.user_id==principal.user_id,BusinessRoute.conversation_id==request.conversation_id,
            BusinessRoute.status.in_(['routing','classifying','dispatching'])).order_by(BusinessRoute.created_at.desc()).limit(1))
        if active:
            if tasks.now()-active.updated_at<timedelta(seconds=30):
                raise HTTPException(409,'Previous message is still routing; wait for its result.')
            # Never let another request overtake an uncertain domain dispatch.
            if active.status=='dispatching':raise HTTPException(409,'Previous dispatch needs status reconciliation.')
            active.status='failed';active.result=clarification('Pichhli routing interrupt hui. Koi task success assume nahi ki.','routing_interrupted')
    context=await context_for(db,principal,request)
    if (request.selection or request.context_refresh) and not context.get('can_continue'):
        raise HTTPException(409,'Open the saved task before selecting or refreshing.')
    stamp=tasks.now();ident=secrets.token_hex(16)
    await db.execute(insert(BusinessRoute).values(id=ident,organization_id=principal.organization_id,
        user_id=principal.user_id,conversation_id=request.conversation_id,request_id=request.request_id,
        input_hash=digest,status='routing',version=VERSION,context_revision=context.get('conversation_revision'),
        context_data={**{k:v for k,v in context.items() if k not in ('recent_messages','draft_lines','choices')},'request':data},
        decision={},result={},telemetry={},created_at=stamp,updated_at=stamp).on_conflict_do_nothing())
    await db.commit()
    row=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
        BusinessRoute.user_id==principal.user_id,BusinessRoute.request_id==request.request_id))
    if row.id!=ident:
        if row.input_hash!=digest:raise HTTPException(409,'Request ID conflict.')
        return await replay(db,principal,row)
    decision=fast_route(request.text,context,selection=bool(request.selection),refresh=request.context_refresh)
    if request.intent in LEGACY_READS:
        decision=RouteDecision(intent='existing_read',relation='standalone',handler='domain_read',reason='typed_legacy_read')
    elif request.intent=='stock_read' and not request.selection:
        item=request.fields.item_name or '*'
        # Explicit typed UI read is still a read request, never write authority.
        decision=RouteDecision(intent='stock_read',relation='standalone',handler='domain_read',item_name=item,reason='typed_stock_read')
    try:
        if not decision:
            # No database lock/transaction remains held during provider I/O.
            from app.services.intent_router_model import classify
            async with asyncio.timeout(8):
                await reserve_model(db,row)
                decision,usage=await classify(request.text,context,row.id)
            row.telemetry={**row.telemetry,'usage':usage}
        row.telemetry={**row.telemetry,'path':'model' if row.telemetry.get('model_attempts') else 'deterministic',
                       'classification_ms':round((time.monotonic()-started)*1000)}
        if decision.intent=='existing_read' and request.intent not in LEGACY_READS:
            raise ValueError('Model cannot request a legacy control')
        if decision.reason=='typed_stock_read' and request.intent=='stock_read':
            validate_evidence(decision.model_copy(update={'item_name':'*'}),request.text,context)
        else:validate_evidence(decision,request.text,context)
        await assert_fresh(db,principal,request,context,decision.handler=='domain_continuation')
        current_status=await db.scalar(select(BusinessRoute.status).where(BusinessRoute.id==row.id))
        if current_status not in ('routing','classifying'):raise HTTPException(409,'Routing request no longer current.')
        row.decision=decision.model_dump(mode='json');row.status='dispatching';await db.commit()
        # Recheck after the commit boundary. Domain services own any mutation.
        await assert_fresh(db,principal,request,context,decision.handler=='domain_continuation')
        await db.commit()
        result=await dispatch(db,principal,request,row,decision,context)
        row.context_data={**row.context_data,'foreground_task_id':result.get('task_id') or context.get('task_id')}
        row.status='completed';row.result={**result,'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'}
    except HTTPException as exc:
        await db.rollback()
        row=await db.get(BusinessRoute,ident,populate_existing=True)
        row.status='failed';row.result={'http_status':exc.status_code,'detail':exc.detail}
        await db.commit()
        raise
    except Exception as exc:
        # Provider failures never silently enter a write workflow or wait loop.
        await db.rollback()
        row=await db.get(BusinessRoute,ident,populate_existing=True)
        if row.status=='dispatching':
            # Keep uncertain dispatch distinguishable from classifier failure.
            # Stable route ID lets replay reconcile committed task creation/resume.
            row.result=clarification('Task ka result confirm nahi hua. Status dobara check karein; naya task repeat nahi kiya.','dispatch_uncertain')
            row.telemetry={**row.telemetry,'failure_type':type(exc).__name__}
            row.updated_at=tasks.now();await db.commit()
            return row.result
        reason=getattr(exc,'reason','routing_unavailable')
        from app.ai.groq_gateway import QuotaDeferred
        from app.services.intent_router_model import RoutingNotSent,RoutingOutputError
        if (isinstance(exc,QuotaDeferred) and not exc.sent) or isinstance(exc,RoutingNotSent):
            row.telemetry={**row.telemetry,'reserved_usd':'0','free_call':False,'model_attempts':0}
        message='Message samajhne wali service abhi available nahi hai. Kaam start hua nahi maana gaya; dobara try karein.'
        if isinstance(exc,RoutingOutputError):
            reason='routing_unclear'
            row.telemetry={**row.telemetry,'routing_diagnostic':exc.diagnostic}
            message='Is message ka jawab reliably taiyar nahi hua. Retry karein; koi accounting action nahi hua.'
        elif isinstance(exc,QuotaDeferred):
            source='Groq ne request limit ki wajah se roki hai.' if exc.sent else 'Philixa ne available AI quota bachane ke liye request abhi nahi bheji.'
            detail={'minute_quota':'Minute ki capacity busy hai; thodi der baad Retry karein.',
                'daily_quota':'Daily capacity khatam hai; provider reset ke baad Retry karein.',
                'local_cap':'Configured local budget/call cap poora ho gaya hai.',
                'request_too_large':'Message aur context available token capacity se bade hain.',
                'quota_ledger_unavailable':'Quota tracking service abhi available nahi hai.'}.get(reason,'AI service abhi available nahi hai; baad mein Retry karein.')
            message=source+' '+detail+' Koi naya accounting kaam start nahi hua.'
            row.telemetry={**row.telemetry,'quota_source':'provider' if exc.sent else 'local_admission',
                'retry_at':exc.retry_at.isoformat() if exc.retry_at else None}
        elif getattr(exc.__cause__,'code',None) in (401,403):
            status=exc.__cause__.code
            reason='provider_access_denied' if status==403 else 'provider_authentication_failed'
            message=('Groq access reject hua (403). Network/VPN ya provider access check karein; details badalne ki zaroorat nahi. Koi accounting action nahi hua.' if status==403 else
                'Groq authentication fail hui (401). Server ki API configuration check karni hogi; koi accounting action nahi hua.')
            row.telemetry={**row.telemetry,'provider_http_status':status}
        elif isinstance(exc,TimeoutError):
            reason='routing_timeout'
            message='Message samajhne mein time limit lag gayi. Koi naya kaam start nahi kiya; dobara try kar sakte hain.'
        elif isinstance(exc,RoutingNotSent):
            reason='routing_initializing'
            message='AI routing setup abhi ready nahi hai. Clear help/stock options available hain; naya kaam start nahi kiya.'
        row.status='failed';row.result={**clarification(message,reason),'can_retry_routing':True}
        row.telemetry={**row.telemetry,'failure_type':type(exc).__name__}
    row.updated_at=tasks.now()
    row.telemetry={**row.telemetry,'total_ms':round((time.monotonic()-started)*1000)}
    await db.commit()
    return {**row.result,'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'}


async def replay(db,principal,row):
    from app.services.business_conversation_service import scoped_conversation
    if row.conversation_id:await scoped_conversation(db,principal,row.conversation_id)
    if row.context_data.get('company_id'):
        company=await drafts.company_for(db,principal,row.context_data['company_id'])
        if company.identity!=row.context_data.get('company_identity'):raise HTTPException(409,'Native company identity changed.')
    task_id=row.result.get('task_id')
    if task_id:await tasks.scoped(db,principal,task_id)
    if row.status in ('completed','failed'):
        if row.result.get('http_status'):raise HTTPException(row.result['http_status'],row.result['detail'])
        return {**row.result,'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'}
    # Recover committed task creation by the stable internal route identity.
    task=await db.scalar(select(AgentTask).where(AgentTask.organization_id==principal.organization_id,
        AgentTask.user_id==principal.user_id,AgentTask.request_id==row.id))
    if not task and row.context_data.get('task_id'):
        candidate=await tasks.scoped(db,principal,row.context_data['task_id'])
        if row.id in candidate.state.get('resume_requests',{}):task=candidate
    if task:
        result=tasks.view(task)
        row.result={**result,'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'};row.status='completed'
        row.context_data={**row.context_data,'foreground_task_id':task.id}
        await db.commit();return row.result
    if row.status!='dispatching' and tasks.now()-row.updated_at>timedelta(seconds=20):
        row.status='failed';row.result=clarification('Pichhli routing complete nahi hui. Koi success assume nahi ki. Naya message bhejein.','routing_interrupted')
        await db.commit();return {**row.result,'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'}
    return {**clarification('Ye message process ho raha hai. Is request ko dobara execute nahi kiya.','routing_in_progress'),
            'route_id':row.id,'router_version':VERSION,'routing_mode':'full' if enabled() else 'conversation_guard'}


async def status(db,principal,ident):
    from app.services.tally_business import admin
    admin(principal)
    row=await db.scalar(select(BusinessRoute).where(BusinessRoute.id==ident,
        BusinessRoute.organization_id==principal.organization_id,BusinessRoute.user_id==principal.user_id))
    if not row:raise HTTPException(404,'Routing request unavailable.')
    return await replay(db,principal,row)


async def retry(db,principal,ident,request_id):
    """Explicit retry of classifier failure only. Dispatch is never replayed blindly."""
    from app.services.tally_business import admin
    from app.services.business_command_service import CommandRequest
    admin(principal)
    if not frontdoor_enabled():raise HTTPException(409,'Conversation routing is disabled; send a new message through the current flow.')
    row=await db.scalar(select(BusinessRoute).where(BusinessRoute.id==ident,
        BusinessRoute.organization_id==principal.organization_id,BusinessRoute.user_id==principal.user_id))
    if not row:raise HTTPException(404,'Routing request unavailable.')
    if row.status!='failed' or not row.result.get('can_retry_routing'):
        raise HTTPException(409,'Use status for this request; automatic execution retry is not allowed.')
    original=copy.deepcopy(row.context_data.get('request'))
    if not original:raise HTTPException(409,'Send the message again; legacy request has no retry snapshot.')
    if request_id==original['request_id']:raise HTTPException(422,'Retry needs its own stable request ID.')
    existing=await db.scalar(select(BusinessRoute).where(BusinessRoute.organization_id==principal.organization_id,
        BusinessRoute.user_id==principal.user_id,BusinessRoute.request_id==request_id))
    if existing:
        if existing.context_data.get('request',{}).get('routing_retry_of')!=ident:
            raise HTTPException(409,'Retry ID belongs to another message.')
        return await replay(db,principal,existing)
    original['request_id']=request_id
    original['routing_retry_of']=ident
    if original.get('conversation_id'):
        from app.services.business_conversation_service import scoped_conversation
        conv=await scoped_conversation(db,principal,original['conversation_id'])
        original['conversation_revision']=conv.revision
    # Replay lookup happens inside route before checking current revisions.
    return await route(db,principal,CommandRequest.model_validate(original))
