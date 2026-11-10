"""Durable attachment intake; reuses document/extraction services, never posts."""
import copy
import hashlib
import json
import os
import secrets
import re
from sqlalchemy import select,text
from fastapi import HTTPException
from app.models.chat_attachment import ChatBillMessage,ChatBillAttachment
from app.models.agent_task import AgentTask
from app.services import task_agent_service as tasks, business_conversation_service as chats
from app.services import bill_document_service as documents,purchase_draft_service as drafts


def enabled():return os.getenv('PHILIXA_CHAT_ATTACHMENTS_ENABLED','0')=='1'


def referenced_bill_ids(message,choices):
    """Resolve explicit references against immutable message/page ordering only."""
    message=message.casefold()
    ordinals={'first':1,'pehla':1,'पहला':1,'second':2,'doosra':2,'dusra':2,'दूसरा':2,
              'third':3,'teesra':3,'तीसरा':3,'fourth':4,'fifth':5,'sixth':6,'seventh':7,
              'eighth':8,'ninth':9,'tenth':10}
    positions=[]
    for match in re.finditer(r'\b(\d+)(?:st|nd|rd|th)?\s+(?:bill|invoice)\b',message):positions.append(int(match[1]))
    for word,position in ordinals.items():
        if re.search(r'(?<!\w)'+re.escape(word)+r'\s+(?:bill|invoice|बिल)(?!\w)',message):positions.append(position)
    if positions:
        return list(dict.fromkeys(choices[position-1][1]['id'] for position in positions if 1<=position<=len(choices)))
    def mentioned(value):return bool(value and re.search(r'(?<![\w./-])'+re.escape(value.casefold())+r'(?![\w./-])',message))
    return [draft['id'] for source,draft in choices if mentioned(draft.get('content',{}).get('invoice_number'))
        or (mentioned(source['filename']) and len(source['drafts'])==1)]


async def accept(db,principal,request):
    if not enabled():raise HTTPException(409,'Chat attachments unavailable; use Manage bills.')
    tasks.enabled()
    if not request.request_id or not request.conversation_id or request.conversation_revision is None:
        raise HTTPException(422,'Attachments need conversation, revision and request ID.')
    ids=[ref.document_id for ref in request.attachments]
    if not ids:raise HTTPException(422,'At least one attachment required.')
    if len(set(ids))!=len(ids):raise HTTPException(422,'Duplicate attachment references.')
    canonical={'conversation_id':request.conversation_id,'text':request.text,
               'documents':ids,'company_id':request.fields.company_id,'task_id':request.task_id}
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    # Cross-conversation requests sharing an ID must serialize too.
    lock_key=int.from_bytes(hashlib.sha256((principal.organization_id+':'+principal.user_id+':'+request.request_id).encode()).digest()[:8], 'big', signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock_key})
    # Lock conversation before checking request identity: concurrent sends serialize.
    conversation=await chats.scoped_conversation(db,principal,request.conversation_id,lock=True)
    previous=await db.scalar(select(ChatBillMessage).where(
        ChatBillMessage.organization_id==principal.organization_id,ChatBillMessage.user_id==principal.user_id,
        ChatBillMessage.request_id==request.request_id))
    if previous:
        if previous.request_hash!=digest:raise HTTPException(409,'Request ID reused with changed attachments.')
        task=await tasks.scoped(db,principal,previous.task_id)
        result=tasks.view(task);result.update(conversation_id=conversation.id,conversation_revision=conversation.revision,message_id=previous.id)
        return result
    collision=await db.scalar(select(AgentTask.id).where(AgentTask.organization_id==principal.organization_id,AgentTask.user_id==principal.user_id,AgentTask.request_id==request.request_id))
    if collision:raise HTTPException(409,'Request ID belongs to a different task.')
    if conversation.revision!=request.conversation_revision:raise HTTPException(409,'Chat changed; reload before sending attachments.')
    rows=[await documents.document_for(db,principal,ident) for ident in ids]
    companies={row.company_id for row in rows}
    if len(companies)!=1:raise HTTPException(422,'All attachments must belong to one selected company.')
    company_id=next(iter(companies))
    if request.fields.company_id and request.fields.company_id!=company_id:raise HTTPException(422,'Attachment company mismatch.')
    company=await drafts.company_for(db,principal,company_id)
    if request.task_id:
        old=await tasks.scoped(db,principal,request.task_id)
        if old.company_id!=company_id:raise HTTPException(409,'Task company differs; start a new attachment task.')
        # A new source must not silently replace an approved/active draft.
        raise HTTPException(409,'Send new files as a new task; existing task remains saved.')
    stamp=tasks.now();message_id=secrets.token_hex(16);task_id=secrets.token_hex(16)
    from app.services.intent_router import is_bill_entry_intent
    has_entry = is_bill_entry_intent(request.text or '')
    outcome = 'verified_entry' if has_entry else 'answer'
    tool_groups = ['documents', 'purchase'] if has_entry else ['documents']
    task=AgentTask(id=task_id,organization_id=principal.organization_id,user_id=principal.user_id,
        company_id=company_id,request_id=request.request_id,request_hash=digest,revision=0,status='queued',
        created_at=stamp,updated_at=stamp,state=dict(messages=[request.text],
        session_id=principal.session_id,company_identity=company.identity,outcome=outcome,
        attachment_document_ids=ids,attachment_initial=True,attachment_message_id=message_id,
        tool_groups=tool_groups,executions=[],observations=[],
        summary='Bills saved hain. File aur details check ho rahi hain.'))
    db.add(task);await db.flush()
    db.add(ChatBillMessage(id=message_id,organization_id=principal.organization_id,user_id=principal.user_id,
        conversation_id=conversation.id,task_id=task_id,request_id=request.request_id,request_hash=digest,
        text=request.text,created_at=stamp))
    await db.flush()
    for index,row in enumerate(rows):db.add(ChatBillAttachment(id=secrets.token_hex(16),message_id=message_id,document_id=row.id,position=index))
    conversation.messages=[*conversation.messages,
        {'role':'user','text':request.text,'message_id':message_id},
        {'role':'assistant','text':task.state['summary'],'message_id':message_id+':result','data':tasks.view(task)}]
    conversation.title=conversation.title if conversation.title!='New chat' else (request.text or rows[0].filename)[:100]
    conversation.revision+=1;conversation.updated_at=stamp
    await db.commit()
    await tasks.enqueue(task.id)
    return {**tasks.view(task),'message_id':message_id,'conversation_id':conversation.id,'conversation_revision':conversation.revision}


async def source_context(db,principal,state,company_id):
    """Bounded exact-source evidence; never a latest-document search."""
    from app.services.invoice_extraction import list_document_drafts
    result=[]
    for ident in state.get('attachment_document_ids',[]):
        doc=await documents.document_for(db,principal,ident)
        if doc.company_id!=company_id:raise HTTPException(404,'Attachment unavailable for task company.')
        linked=(await list_document_drafts(db,principal,ident))['drafts']
        result.append({'document_id':doc.id,'filename':doc.filename,'status':doc.status,
            'extraction_status':doc.extraction_status,'extraction_generation':doc.extraction_generation,
            'page_count':doc.page_count,'message':documents.view(doc)['message'],
            'error':doc.extraction_error,'boundary_issue':bool((doc.page_count or 0)>1 and linked and any(not (d.get('extraction_metadata') or {}).get('is_split_draft') for d in linked)),'drafts':linked})
    return result


async def advance(db,principal,state,company_id,queue=None):
    """One non-blocking segment. OCR waiting consumes no planner budget."""
    from app.services.invoice_extraction_jobs import request_extraction
    sources=await source_context(db,principal,state,company_id)
    for source in sources:
        if source['status']=='ready' and not source['drafts'] and (source['extraction_status'] is None or state.get('attachment_retry')):
            await request_extraction(db,principal,source['document_id'],split=(source['page_count'] or 0)>1,pool=queue)
    state.pop('attachment_retry',None)
    sources=await source_context(db,principal,state,company_id)
    pending=any(s['status'] in ('queued','processing') or s['extraction_status'] in ('queued','processing') for s in sources)
    state['attachment_sources']=sources
    state['observations']=[{'status':'waiting_context' if pending else 'ok','verified':False,
        'data':{'attachment_sources':sources,'document_id':sources[0]['document_id'] if len(sources)==1 else None}}]
    if pending:
        state.update(status='waiting_context',summary='Bills ki details check ho rahi hain. Result isi chat mein aayega.')
        return state
    if any(source['boundary_issue'] for source in sources):
        state.update(attachment_initial=False,status='needs_input',issues=[{'code':'invoice_boundary_review','message':'Multi-page invoice boundaries are not verified. Review original; no merged purchase prepared.'}],summary='Multi-page bill ki invoice boundaries verify nahi hain. Original review karein; koi Tally entry nahi hui.')
        return state
    all_drafts=[draft for source in sources for draft in source['drafts']]
    lines=[]
    for source in sources:
        if not source['drafts']:
            lines.append(source['filename']+': '+(source['error'] or source['message'] or 'Details unavailable; original review karein.'))
        for draft in source['drafts']:
            content=draft.get('content',{})
            total=content.get('invoice_total')
            lines.append(source['filename']+': '+str(content.get('party_name') or 'Supplier review required')+
                ' · '+str(content.get('invoice_number') or 'Invoice reference unclear')+
                (' · Bill total ₹'+str(total) if total is not None else ' · Total review karein'))
    state['attachment_generations']={source['document_id']:source['extraction_generation'] for source in sources}
    from app.services.intent_router import is_bill_entry_intent
    has_entry = state.get('outcome') == 'verified_entry' or any(is_bill_entry_intent(m) for m in state.get('messages', []))
    if len(all_drafts)==1:
        target_draft=all_drafts[0]['id']
        target_outcome='verified_entry' if has_entry else 'draft'
        state.update(draft_id=target_draft,draft_revision=all_drafts[0]['revision'],outcome=target_outcome)
        if has_entry:
            state['tool_groups']=list(dict.fromkeys([*state.get('tool_groups',[]),'documents','purchase']))
            state['routing_first_step']={'kind':'tool','tool':'purchase_context','arguments':{'draft_id':target_draft},'summary':'Saved bill ki purchase validation check kar rahi hoon.'}
    if has_entry and all_drafts:
        draft_content = all_drafts[0].get('content', {})
        p_name = draft_content.get('party_name') or 'Supplier'
        inv = draft_content.get('invoice_number')
        inv_part = f", Invoice #{inv}" if inv else ""
        tot = draft_content.get('invoice_total')
        tot_part = f", Total ₹{tot}" if tot else ""
        ending = f"Maine {p_name} ka bill{inv_part}{tot_part} check kar liya hai. Tally me entry ke liye masters aur details verify ho rahi hain."
        state.update(attachment_initial=False,status='needs_input',issues=[],
            summary=ending)
    else:
        ending='Original ke saath Review bill karein.' if all_drafts else 'Bill ki details extract nahi hui; draft nahi bana. View original se file dekhein.'
        state.update(attachment_initial=False,status='needs_input',issues=[] if all_drafts else [{'code':'document_extraction_failed'}],
            summary='\n'.join(lines)+'\n'+ending+' Is upload se nayi Tally entry post nahi hui.')
    return state


async def wake(ctx,document_id=None):
    """Completion hint + recovery scanner; enqueue is not the source of truth."""
    if not enabled():return
    from app.database.session import AsyncSessionLocal
    from app.services.bill_document_service import QUEUE
    async with AsyncSessionLocal() as db:
        rows=(await db.scalars(select(AgentTask).where(AgentTask.status.in_(['queued','waiting_context']),AgentTask.state['attachment_initial'].as_boolean().is_(True)).order_by(AgentTask.updated_at).limit(100))).all()
        dispatch=[]
        for row in rows:
            if not row.state.get('attachment_initial'):continue
            if document_id and document_id not in row.state.get('attachment_document_ids',[]):continue
            row.status='queued'
            dispatch.append((row.id,row.revision))
        await db.commit()
    for ident,revision in dispatch:
        try:await ctx['redis'].enqueue_job('execute_agent_task',ident,revision,_queue_name=QUEUE,_job_id=tasks.wake_job_id(ident,revision))
        except Exception:pass


async def transcript(db,principal,conversation,messages):
    """Restore from authoritative links; forged/removed UI cards grant no access."""
    linked=(await db.scalars(select(ChatBillMessage).where(ChatBillMessage.conversation_id==conversation.id,
        ChatBillMessage.user_id==principal.user_id,ChatBillMessage.organization_id==principal.organization_id).order_by(ChatBillMessage.created_at))).all()
    replacements={}
    for link in linked:
        try:task=await tasks.scoped(db,principal,link.task_id)
        except HTTPException:
            replacements[link.id]={'role':'user','text':link.text,'message_id':link.id}
            replacements[link.id+':result']={'role':'assistant','text':'Bill access unavailable. Company permission check karein.','message_id':link.id+':result'}
            continue
        refs=(await db.scalars(select(ChatBillAttachment).where(ChatBillAttachment.message_id==link.id).order_by(ChatBillAttachment.position))).all()
        files=[]
        for ref in refs:
            try:
                doc=await documents.document_for(db,principal,ref.document_id)
                files.append({'document_id':doc.id,'filename':doc.filename,'media_type':doc.media_type})
            except HTTPException:files.append({'document_id':ref.document_id,'filename':'Document unavailable'})
        replacements[link.id]={'role':'user','text':link.text,'message_id':link.id,'data':{'chat_attachments':files}}
        replacements[link.id+':result']={'role':'assistant','text':task.state.get('summary','Bills saved.'),'message_id':link.id+':result','data':tasks.view(task)}
    output=[];seen=set()
    for message in copy.deepcopy(messages):
        ident=message.get('message_id')
        if ident in replacements:
            if ident not in seen:output.append(replacements[ident]);seen.add(ident)
        else:
            if message.get('data'):message['data'].pop('chat_attachments',None)
            output.append(message)
    output.extend(value for ident,value in replacements.items() if ident not in seen)
    return output
