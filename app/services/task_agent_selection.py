"""Server-owned offers. Exact selections update a draft without model calls."""
import copy,hashlib,json,os
from fastapi import HTTPException
from app.services import purchase_draft_service as drafts

def offers(task):
    latest=(task.state.get('observations') or [{}])[-1].get('data',{})
    proposal=latest.get('proposal') or {};proof=latest.get('selection_context') or {}
    result=[]
    for master in proof.get('masters',[]):
        body={'kind':'identity',**master}
        result.append(body)
    hint=latest.get('purchase_context',{}).get('supplier_suggestion')
    if hint:result.append({'kind':'history','value':hint['supplier'],'label':'Haan, wahi supplier/rate','hint':hint})
    for rate in latest.get('suggestions',[]):
        result.append({'kind':'rate','field':rate['field'],'value':rate['value'],'label':'Rate ₹'+rate['value'],'rate':rate})
    for offer in result:
        offer.update(draft_id=task.state.get('draft_id'),draft_revision=proposal.get('revision'),
            evidence_version=latest.get('evidence_version'),generation=proof.get('generation'))
        offer['reference']=hashlib.sha256(json.dumps([task.id,task.revision,offer],sort_keys=True).encode()).hexdigest()
        offer.setdefault('label',offer['value'])
    return result

def public_offers(task):
    if os.getenv('PHILIXA_TASK_SELECTIONS_ENABLED','0')!='1':return []
    return [{k:o.get(k) for k in ('reference','label','kind','field','value','draft_revision','evidence_version')} for o in offers(task)]

def confirmation_offer(available,message):
    if message.strip().casefold().rstrip('.!') not in {'done','haan','han','yes','haan wahi','haan wahi hain','haan, wahi hain','haan, wahi supplier/rate hain'}:return None
    histories=[o for o in available if o['kind']=='history']
    if len(histories)==1:return histories[0]
    rates=[o for o in available if o['kind']=='rate']
    return rates[0] if len(rates)==1 and len(available)==1 else None

async def apply(db,principal,task,request):
    if not task.state.get('draft_id'):return None
    available=offers(task);selection=request.selection
    if selection:
        matches=[o for o in available if o['reference']==selection.reference]
        if len(matches)!=1:raise HTTPException(409,'Selection changed; reload current review.')
        offer=matches[0]
        if selection.draft_revision!=offer['draft_revision'] or selection.evidence_version!=offer['evidence_version']:
            raise HTTPException(409,'Selection evidence changed; reload.')
    else:
        matches=[o for o in available if o['kind']=='identity' and request.message.strip().casefold()==o['value'].casefold()]
        offer=matches[0] if len(matches)==1 else confirmation_offer(available,request.message)
        if not offer:return None
    row=await drafts.scoped_draft(db,principal,offer['draft_id'],lock=True)
    if row.company_id!=task.company_id or row.revision!=offer['draft_revision']:
        raise HTTPException(409,'Draft changed; reload selection.')
    await drafts.editable_action(db,row,row.revision)
    from app.services import tally_sync as sync
    from app.services.purchase_identity import exact_master,master_identity,master_fingerprint
    from app.services.tally_sync_protocol import deserialize_catalog
    from app.services.purchase_native_context import fresh,conversation_history,context,suggestion_version
    company=await drafts.company_for(db,principal,task.company_id)
    if task.state.get('company_identity') and task.state['company_identity']!=company.identity:
        raise HTTPException(409,'Native company identity changed; start a fresh task.')
    snapshot=await sync.saved_snapshot(db,company)
    if (not snapshot or not fresh(snapshot.collected_at)) and offer['kind']=='identity':
        # A read-only refresh may commit; re-lock task/draft below before edit.
        await db.commit()
        from app.services.tally_connector import TallyError
        try:await sync.refresh_company(db,company)
        except TallyError:pass
        snapshot=await sync.saved_snapshot(db,company)
    if not snapshot or not fresh(snapshot.collected_at) or (snapshot.generation!=offer['generation'] and offer['kind']!='identity'):
        raise HTTPException(409,'Tally masters changed/stale. Refresh context before selecting.')
    catalog=deserialize_catalog(snapshot.catalog);content=copy.deepcopy(row.content);changed={}
    if offer['kind']=='identity':
        kind='supplier' if offer['field']=='party_name' else 'item'
        master=exact_master(catalog,kind,offer['value'])
        if master_identity(master)!=offer['native_id'] or master_fingerprint(master)!=offer['fingerprint']:
            raise HTTPException(409,'Native identity changed; refresh context.')
        if kind=='supplier':content['party_name']=offer['value'];changed['party_name']=offer['value']
        else:
            index=int(offer['field'].split(':')[0]);content['lines'][index]['item_name']=offer['value'];changed[f'lines.{index}.item_name']=offer['value']
    else:
        current=await conversation_history(db,principal,row,catalog) if offer['kind']=='history' else await context(db,principal,row)
        if offer['kind']=='history':
            hint=current.get('supplier_suggestion')
            if not hint or suggestion_version(hint)!=suggestion_version(offer['hint']):raise HTTPException(409,'History changed; review new suggestion.')
            content['party_name']=hint['supplier'];changed['party_name']=hint['supplier'];rates=hint['rates']
        else:
            rates=[r for r in current.get('suggestions',[]) if r==offer['rate']]
            if not rates:raise HTTPException(409,'Rate evidence changed.')
        for rate in rates:
            index=int(rate['field'].split(':')[0])
            if content['lines'][index].get('rate') is not None:continue
            content['lines'][index]['rate']=rate['value'];changed[f'lines.{index}.rate']=rate['value']
    # No committing domain helper between task request dedup and draft edit.
    if not changed:raise HTTPException(409,'Value already explicit. Use a correction message to change it.')
    from sqlalchemy import select
    from app.models.agent_task import AgentTask
    task=await db.scalar(select(AgentTask).where(AgentTask.id==task.id).with_for_update().execution_options(populate_existing=True))
    if task.revision!=request.expected_revision:raise HTTPException(409,'Task changed during selection.')
    row=await drafts.scoped_draft(db,principal,offer['draft_id'],lock=True)
    if row.revision!=offer['draft_revision']:raise HTTPException(409,'Draft changed during selection.')
    provenance=dict((row.extraction_metadata or {}).get('agent_provenance',{}))
    for field,value in changed.items():
        provenance[field]={'value':value,'status':'explicit','source_type':'user_selection',
            'source_id':offer['reference'],'draft_revision':row.revision+1,'observed_at':sync.now().isoformat()}
    row.extraction_metadata={**(row.extraction_metadata or {}),'agent_provenance':provenance}
    await db.flush()
    await drafts.save_draft(db,principal,row.id,drafts.DraftSave(revision=row.revision,content=drafts.DraftContent.model_validate(content)),commit=False,
        event_details={'selection_reference':offer['reference'],'evidence_version':offer['evidence_version'],
            'task_id':task.id,'fields':list(changed),'provenance':{k:provenance[k] for k in changed}})
    state=copy.deepcopy(task.state)
    state.pop('details_unknown',None)
    state.pop('context_auto_until',None)
    digest=hashlib.sha256(json.dumps([request.message,request.company_id,request.selection.model_dump() if request.selection else None]).encode()).hexdigest()
    state.setdefault('resume_requests',{})[request.request_id]=[task.revision,digest]
    if request.message:state.setdefault('messages',[]).append(request.message)
    state.update(draft_revision=row.revision,summary='Selection saved. Tally context check ho raha hai.',
        session_id=principal.session_id,executions=[],observations=[],model_rounds=0,provider_retries=0,issues=[],selection_refresh=True)
    state.pop('action_id',None)
    for key in ('provider_retry_at','auto_resume_until','wait_reason'):state.pop(key,None)
    task.state=state;task.revision+=1;task.status='queued';task.updated_at=sync.now()
    await db.commit()
    return task
