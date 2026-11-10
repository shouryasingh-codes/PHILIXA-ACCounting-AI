"""Review-mode purchase agent. Models propose fields; existing compilers authorise writes."""
import copy,hashlib,json,re,secrets
from datetime import datetime
from typing import TypedDict
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select,text
from langgraph.graph import StateGraph,END
from app.models.purchase_agent import PurchaseChatReceipt
from app.models.tally import TallyAction
from app.services import purchase_draft_service as drafts,purchase_native_context as native,tally_sync as sync
from app.services import purchase_context
from app.services.tally_connector import TallyError,name,value
from app.services.purchase_identity import normalized,exact_master,master_identity,master_fingerprint

def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()

def apply_updates(content,updates):
    content=copy.deepcopy(content)
    for item in updates:
        path=item['path'];val=item['value']
        match=re.fullmatch(r'lines\.(\d{1,2})\.([a-z_]+)',path)
        if match:
            index=int(match[1])
            if index>len(content['lines']):raise HTTPException(422,'Line correction ambiguous; item names ke saath details dein.')
            if index==len(content['lines']):content['lines'].append({})
            content['lines'][index][match[2]]=val
        elif path.startswith('expected_taxes.'):
            content.setdefault('expected_taxes',None)
            if content['expected_taxes'] is None:content['expected_taxes']={}
            content['expected_taxes'][path.split('.')[1]]=val
        else:content[path]=val
    return drafts.DraftContent.model_validate(content).model_dump(mode='json')

async def resolve(db,principal,row,catalog):
    from app.services.purchase_memory_service import reusable_aliases
    aliases=await reusable_aliases(db,principal,row.company_id)
    c=copy.deepcopy(row.content);bindings=[];issues=[]
    targets=[('supplier','party_name',None,c.get('party_name'))]+[('item','item_name',i,v.get('item_name')) for i,v in enumerate(c['lines'])]
    for kind,key,index,label in targets:
        try:exact_master(catalog,kind,label);continue
        except TallyError:pass
        alias=aliases.get(kind+':'+normalized(label)) if label else None
        if alias:
            if index is None:c[key]=alias['target']
            else:c['lines'][index][key]=alias['target']
            bindings.append(dict(id=alias['id'],kind=kind,line_index=index,fingerprint=alias['fingerprint']))
        else:
            rows=catalog['ledgers' if kind=='supplier' else 'items']
            if kind=='supplier':rows=[v for v in rows if value(v,'PARENT')=='Sundry Creditors']
            exact_label=normalized(label)
            candidates=[name(v) for v in rows if exact_label and exact_label in normalized(name(v))] or [name(v) for v in rows]
            issues.append(dict(field='party_name' if index is None else f'{index}:item_name',kind='identity',
                message='Kis supplier se liya?' if kind=='supplier' else f'Item {index+1}: kaunsa Tally item?',choices=candidates[:8]))
    if c!=row.content:
        previous=await drafts.editable_action(db,row,row.revision)
        if previous and previous.status=='preview':previous.status='expired'
        row.content=c;row.action_id=None;row.revision+=1;row.updated_at=sync.now()
        replaced={(b['kind'],b.get('line_index')) for b in bindings}
        retained=[b for b in (row.extraction_metadata or {}).get('approved_aliases',[])
                  if (b['kind'],b.get('line_index')) not in replaced]
        row.extraction_metadata={**(row.extraction_metadata or {}),'approved_aliases':retained+bindings}
        drafts.record_event(db,row,'system:approved-memory','alias_reused',{'bindings':bindings})
        await db.commit()
        row=await drafts.scoped_draft(db,principal,row.id,lock=True)
    return row,issues

class AgentState(TypedDict,total=False):
    draft_id:str
    revision:int
    calls:list[str]
    context:dict
    issues:list[dict]
    proposal:dict

def step(state,tool,args):
    key=tool+':'+digest(args)
    if key in state.get('calls',[]) or len(state.get('calls',[]))>=6:raise HTTPException(409,'Task saved hai; tool limit reached. Refresh karke review karein.')
    return [*state.get('calls',[]),key]

async def identity_history(db,principal,row,catalog,identities):
    if identities and all(i['field']=='party_name' for i in identities):
        return await native.conversation_history(db,principal,row,catalog)
    if not identities:return await native.context(db,principal,row)
    return {'status':'needs_identity','suggestions':[]}

async def state(db,principal,draft_id,prefix=''):
    from app.services.purchase_conversation import frozen,prepare
    from app.services.purchase_memory_service import catalog_for
    from app.database.session import AsyncSessionLocal
    from app.services.purchase_checkpoint import PurchaseSaver
    principal=frozen(principal)
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    await drafts.editable_action(db,row,row.revision)
    company=await drafts.company_for(db,principal,row.company_id)
    try:catalog=await catalog_for(db,company)
    except TallyError:
        await db.commit()
        return {'response':'Purchase saved hai. Tally masters sync karein; koi entry post nahi hui.',
            'draft_id':row.id,'gst_purchase_draft':{'id':row.id},'issues':[{'field':'context','message':'Masters missing'}]}
    row,identities=await resolve(db,principal,row,catalog)
    row,catalog,master_notes=await prepare(db,principal,row)
    content=copy.deepcopy(row.content);revision=row.revision
    snapshot=await sync.saved_snapshot(db,company)
    snapshot_generation=snapshot.generation if snapshot else None
    await db.commit() # No draft row lock held while tools perform read-only network IO.
    # Only serializable domain evidence enters the checkpointer. db/principal stay in closures.
    async def masters_node(s):
        return {'calls':step(s,'resolve_masters',{'draft':draft_id,'revision':revision}),'issues':identities}
    async def history_node(s):
        result=await identity_history(db,principal,row,catalog,identities)
        return {'calls':step(s,'read_history',{'company':row.company_id,'content':content}),'context':result}
    async def validate_node(s):
        issues=list(s.get('issues',[]))
        identity_fields={v['field'] for v in issues}
        missing=purchase_context.pending_fields(content)
        for key in missing:
            if key in identity_fields:continue
            label=purchase_context.pending_labels(content)[missing.index(key)]
            issues.append({'field':key,'kind':'missing','message':label,'choices':[]})
        context=s['context']
        if not identities and context.get('status')!='ready':
            issues.append({'field':'context','kind':'context','message':context.get('reason') or 'Tally context sync pending','choices':[]})
        if not snapshot or not native.fresh(snapshot.collected_at):
            issues.append({'field':'masters','kind':'context','message':'Masters refresh pending','choices':[]})
        calls=step(s,'validate_draft',{'revision':revision,'context':context.get('evidence_version')})
        if not identities and content.get('invoice_number') and content.get('entry_date') and context.get('complete'):
            from app.services.purchase_identity import invoice_guard
            from app.services.purchase_memory_service import check_local,live_check
            calls=step({'calls':calls},'check_duplicate',{'company':company.id,'reference':content['invoice_number'],'date':content['entry_date']})
            try:
                guard=invoice_guard(company.id+':'+company.identity,catalog,content)
                await check_local(db,row,guard)
                await live_check(db,company,guard)
            except TallyError as exc:issues.append({'field':'duplicate','kind':'blocked','message':str(exc),'choices':[]})
        totals=drafts.draft_totals(content)
        if not content.get('tax_treatment') and totals['total'] and content.get('invoice_total') is not None:
            from decimal import Decimal
            if Decimal(totals['total'])!=Decimal(str(content['invoice_total'])):
                issues.append({'field':'invoice_total','kind':'blocked','message':'Final total line amounts se match nahi hai.','choices':[]})
        return {'calls':calls,'issues':issues}
    async def proposal_node(s):
        evidence=s['context'];provenance=copy.deepcopy((row.extraction_metadata or {}).get('agent_provenance',{}))
        for index,line in enumerate(content['lines']):
            for key,val in line.items():
                if val is not None:
                    path=f'lines.{index}.{key}'
                    provenance.setdefault(path,dict(value=val,status='master' if key=='unit' else 'unresolved',source_type='tally_master' if key=='unit' else 'saved_draft',observed_at=row.updated_at.isoformat(),draft_revision=revision))
        totals=drafts.draft_totals(content)
        for key,val in content.items():
            if key!='lines' and val is not None:
                provenance.setdefault(key,dict(value=val,status='master' if key=='supplier_gstin' else 'unresolved',
                    source_type='tally_master' if key=='supplier_gstin' else 'saved_draft',observed_at=row.updated_at.isoformat(),draft_revision=revision))
        return {'calls':step(s,'prepare_proposal',{'revision':revision,'content':content}),
            'proposal':dict(company=company.name,company_id=company.id,content=content,revision=revision,
                totals={**totals,'source':'calculated','invoice_total':content.get('invoice_total')},provenance=provenance,
                evidence_version=digest([revision,content,evidence.get('evidence_version'),snapshot_generation]),
                can_prepare_preview=not s['issues'])}
    graph=StateGraph(AgentState)
    for key,fn in [('masters',masters_node),('history',history_node),('validate',validate_node),('proposal',proposal_node)]:graph.add_node(key,fn)
    graph.set_entry_point('masters');graph.add_edge('masters','history');graph.add_edge('history','validate');graph.add_edge('validate','proposal');graph.add_edge('proposal',END)
    # Checkpoints are isolated per principal/draft and request run. A run never replays posting.
    thread='purchase:'+digest([principal.organization_id,principal.user_id,row.id,revision,snapshot_generation])
    workflow=graph.compile(checkpointer=PurchaseSaver(AsyncSessionLocal))
    config={'configurable':{'thread_id':thread},'recursion_limit':8}
    checkpoint=await workflow.aget_state(config)
    result=await workflow.ainvoke(None if checkpoint.next else {'draft_id':row.id,'revision':revision,'calls':[]},
        config=config,durability='sync')
    current=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    if current.revision!=revision:raise HTTPException(409,'Purchase details changed; current draft review karein.')
    issues=result['issues'];proposal=result['proposal'];context=result['context']
    if context.get('status')=='ready':
        fresh_context=await native.context(db,principal,current)
        if fresh_context.get('evidence_version')!=context.get('evidence_version'):
            raise HTTPException(409,'Tally context changed; current proposal dobara review karein.')
    identity=next((v for v in issues if v['kind']=='identity'),None)
    missing=[v['message'] for v in issues if v['kind']=='missing']
    blockers=[v['message'] for v in issues if v['kind']=='blocked']
    message=[prefix] if prefix else []
    message.extend(' · '.join(str(v) for v in [l.get('quantity'),l.get('unit'),l.get('item_name')] if v) for l in content['lines'])
    if identity:message.append(identity['message'])
    elif blockers:message.append(blockers[0])
    elif missing:
        fields={v['field'] for v in issues if v['kind']=='missing'}
        groups=[]
        if any(v.endswith(':quantity') for v in fields):groups.append('quantity')
        if any(v.endswith(':unit') for v in fields):groups.append('unit')
        if any(v.endswith(':rate') for v in fields):groups.append('rate')
        if fields & {'invoice_number','entry_date'}:groups.append('bill number/date')
        if 'invoice_total' in fields:groups.append('final total')
        if any(v in fields for v in ('supplier_gstin','place_of_supply','expected_taxes')) or any(v.endswith((':gst_rate',':hsn',':taxable_amount')) for v in fields):groups.append('bill ke tax details')
        message.append('Bas '+', '.join(groups)+' chahiye. Ek message mein bata sakte hain, ya bill bhej dein.')
    else:message.append('Purchase details review karein. Preview mein validation ke baad confirmation milega.')
    response={'response':'\n'.join(message),'draft_id':row.id,'gst_purchase_draft':{'id':row.id},
        'purchase_assistant':{'draft_id':row.id,'revision':revision,'field':identity['field'] if identity else 'message','choices':identity['choices'] if identity else []},
        'proposal':proposal,'issues':issues,'suggestions':context.get('suggestions',[]),'evidence_version':proposal['evidence_version'],
            'purchase_context':{**context,'native_history_status':context.get('history_status',context.get('status')),
            'native_history_reason':context.get('reason')},'purchase_details':master_notes}
    selection_masters=[]
    for label in identity['choices'] if identity else []:
        try:
            master=exact_master(catalog,'supplier' if identity['field']=='party_name' else 'item',label)
            selection_masters.append({'field':identity['field'],'value':label,'native_id':master_identity(master),'fingerprint':master_fingerprint(master)})
        except TallyError:continue # No stable identity means no model-free offer.
    response['selection_context']={'generation':snapshot_generation,'observed_at':snapshot.collected_at.isoformat() if snapshot else None,'masters':selection_masters}
    if identity and identity['field']=='party_name' and context.get('supplier_suggestion'):
        response['response']='\n'.join(message[:-1]+['Pichhli matching purchase mili. Is baar bhi wahi supplier/rate hain?'])
    from app.services.repeat_purchase import proposal as repeat_proposal
    repeat=repeat_proposal(content,context)
    if repeat:
        response['repeat_purchase']=repeat
        response['response']=f"Pichhli matching purchase se {repeat['supplier']} ka suggestion mila. Is baar bhi wahi supplier/rate? Quantity is nayi purchase ki rahegi; abhi entry nahi hui."
    await db.commit();return response

async def answer(db,principal,draft_id,request):
    from app.services.purchase_conversation import frozen
    from app.services import purchase_message
    principal=frozen(principal)
    if request.resume:return await state(db,principal,draft_id)
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    request_id=request.request_id
    if not request_id:raise HTTPException(422,'Request ID required; reload chat and retry.')
    key=digest([principal.organization_id,principal.user_id,draft_id,request_id])
    request_hash=digest(request.model_dump(mode='json'))
    receipt=await db.get(PurchaseChatReceipt,key)
    if receipt:
        if receipt.request_hash!=request_hash:raise HTTPException(409,'Request ID reused with different details.')
        await db.commit();return await state(db,principal,draft_id,prefix='Ye message pehle save ho chuka hai.')
    revision=request.expected_revision if request.expected_revision is not None else request.revision
    await drafts.editable_action(db,row,revision)
    if revision is None or row.revision!=revision:raise HTTPException(409,'Draft changed; review again.')
    content=copy.deepcopy(row.content);meta=copy.deepcopy(row.extraction_metadata or {})
    if request.accept_suggestions or request.prepare_preview:
        await db.commit();proposal=await state(db,principal,draft_id)
        if request.evidence_version!=proposal.get('evidence_version'):raise HTTPException(409,'Evidence changed; current proposal review karein.')
        row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
        await drafts.editable_action(db,row,revision)
        if request.prepare_preview:
            if proposal['issues']:raise HTTPException(422,'Required details/context pending; preview abhi ready nahi.')
            result=await drafts.preview_draft(db,principal,row.id,drafts.DraftPreview(revision=row.revision))
            action=await db.get(TallyAction,result['preview']['token'])
            context=proposal['purchase_context']
            action.preconditions={**(action.preconditions or {}),'purchase_agent':dict(draft_id=row.id,revision=row.revision,
                cache_id=context.get('cache_id'),generation=context.get('generation'),rate_context=context.get('rate_context'))}
            db.add(PurchaseChatReceipt(id=key,draft_id=row.id,user_id=principal.user_id,request_hash=request_hash,response={'preview':action.token},created_at=sync.now()))
            await db.commit();return result
        updates=[]
        for suggestion in proposal['suggestions']:
            index,field=suggestion['field'].split(':')
            updates.append(dict(path=f'lines.{index}.{field}',value=suggestion['value'],quote='user accepted proposal',source=suggestion))
        if not updates:raise HTTPException(422,'No current suggestions to accept.')
    else:
        text_value=(request.message or request.answer or '').strip()
        if text_value.casefold() in ('pause','stop','baad mein','ruk ja'):
            await db.commit();return {'response':'Purchase draft saved hai.','purchase_resume':row.id,'gst_purchase_draft':{'id':row.id}}
        # Exact identity selections do not need another provider call.
        from app.services.purchase_memory_service import catalog_for
        catalog=await catalog_for(db,await drafts.company_for(db,principal,row.company_id))
        if request.field=='party_name' and any(name(v)==text_value and value(v,'PARENT')=='Sundry Creditors' for v in catalog['ledgers']):
            updates=[dict(path='party_name',value=text_value,quote=text_value)]
        elif re.fullmatch(r'\d+:item_name',request.field or '') and any(name(v)==text_value for v in catalog['items']):
            updates=[dict(path='lines.'+request.field.replace(':','.'),value=text_value,quote=text_value)]
        else:
            # Release row lock during model IO; reacquire and recheck revision afterwards.
            await db.commit()
            updates=await purchase_message.extract(text_value,{'content':content,'current_field':request.field})
            row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
            await drafts.editable_action(db,row,revision)
            if row.revision!=revision:raise HTTPException(409,'Draft changed during understanding; message not replayed.')
            receipt=await db.get(PurchaseChatReceipt,key)
            if receipt:
                if receipt.request_hash!=request_hash:raise HTTPException(409,'Request ID conflict.')
                await db.commit();return await state(db,principal,draft_id)
    if not updates:raise HTTPException(422,'Koi clear purchase detail nahi mili; draft unchanged.')
    before=copy.deepcopy(content)
    try:content=apply_updates(content,updates)
    except Exception:raise HTTPException(422,'Details invalid/ambiguous; original draft retained.')
    previous=await drafts.editable_action(db,row,revision)
    if previous and previous.status=='preview':previous.status='expired'
    row.content=content;row.action_id=None;row.revision+=1;row.updated_at=sync.now()
    provenance=meta.get('agent_provenance',{})
    for update in updates:
        source=update.get('source')
        provenance[update['path']]=dict(value=update['value'],source_type='accepted_history' if source else 'user_message',
            source_id=source.get('source_id') if source else request_id,quote=update['quote'],status='explicit',
            observed_at=sync.now().isoformat(),draft_revision=row.revision,**({'historical_source':source} if source else {}))
    row.extraction_metadata={**meta,'agent_provenance':provenance}
    drafts.record_event(db,row,principal.user_id,'agent_message',{'request_id':request_id,'fields':[v['path'] for v in updates]})
    from app.services.bill_evaluation_service import record,changed_fields,flatten
    record(db,principal,'agent_message',{'request_id':request_id,'field_count':len(updates),'revision':row.revision},draft_id=row.id)
    changed=changed_fields(before,content);old_values=flatten(before)
    corrections=[path for path in changed if old_values.get(path) not in (None,'')]
    if corrections:record(db,principal,'correction',{'revision':row.revision,'count':len(corrections),'fields':corrections},draft_id=row.id)
    db.add(PurchaseChatReceipt(id=key,draft_id=row.id,user_id=principal.user_id,request_hash=request_hash,response={'revision':row.revision},created_at=sync.now()))
    await db.commit()
    return await state(db,principal,draft_id)
