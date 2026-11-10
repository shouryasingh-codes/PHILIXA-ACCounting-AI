"""Company-scoped adapters. Model output never supplies a principal or authority."""
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from typing import Literal
import os
from app.services.task_agent_runtime import Tool, ToolResult
from app.services import purchase_draft_service as drafts
from app.services.purchase_message import Mention, MessageFields, grounded


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')

class CapabilityGroup(Empty):
    group:Literal['purchase','reads','documents','receipts']


class DraftId(Empty):
    draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class DraftMessage(DraftId):
    revision: int = Field(ge=0)
    message_index: int = Field(ge=0,le=1000)
    updates: list[Mention] = Field(min_length=1,max_length=200)

class DraftSituation(DraftId):
    revision:int=Field(ge=0)
    message_index:int=Field(ge=0,le=1000)


class NewPurchase(Empty):
    message_index: int = Field(ge=0,le=1000)
    updates: list[Mention] = Field(min_length=1,max_length=200)


class DraftRevision(DraftId):
    revision: int = Field(ge=0)


class DocumentId(Empty):
    document_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class BillFields(DraftId):
    fields:list[Literal['party_name','invoice_number','entry_date','invoice_total','lines','expected_taxes']]=Field(min_length=1,max_length=6)


class StockQuery(Empty):
    item_name: str = Field(default='*',min_length=1, max_length=200,description='Exact item/query; * for all stock when no item specified.')


class MasterQuery(Empty):
    supplier_query: str | None = Field(default=None,max_length=200)
    item_query: str | None = Field(default=None,max_length=200)


class ReportQuery(Empty):
    report: Literal['get_purchase_register','get_sales_register','get_bills_receivable',
                    'get_bills_payable','get_receipts_and_payments','get_cash_flow']
    from_date: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
    to_date: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
    as_of: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')


class ReceiptLink(DraftRevision):
    receipt_draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    receipt_revision: int = Field(ge=0)


def registry(db, principal, company_id, state):
    async def expand(args):return ToolResult(status='ok',data={'capability_group':args['group']})
    async def annotate(draft_id,updates,message,message_index,previous_content=None):
        row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
        provenance=dict((row.extraction_metadata or {}).get('agent_provenance',{}))
        for update in updates:
            current=row.content
            for part in update['path'].split('.'):
                current=current[int(part)] if isinstance(current,list) else current.get(part) if isinstance(current,dict) else None
            quote=update['quote']
            if update['path'].endswith(('party_name','item_name')) and isinstance(current,str) and current in message:quote=current
            provenance[update['path']]={'value':current,'quote':quote,'status':'explicit',
                'source_type':'user_message','source_id':f"{state.get('task_id')}:{message_index}",
                'observed_at':row.updated_at.isoformat(),'draft_revision':row.revision}
        metadata={**(row.extraction_metadata or {}),'agent_provenance':provenance}
        if getattr(row,'document_id',None) and previous_content is not None:
            conflicts=list(metadata.get('chat_source_conflicts',[]))
            for update in updates:
                previous=previous_content
                for part in update['path'].split('.'):
                    previous=previous[int(part)] if isinstance(previous,list) else previous.get(part) if isinstance(previous,dict) else None
                current=provenance[update['path']]['value']
                if previous is not None and str(previous)!=str(current):
                    conflicts.append({'field':update['path'],'previous':previous,'corrected':current,
                        'quote':update['quote'],'source':'explicit user correction; original extraction retained','draft_revision':row.revision})
            metadata['chat_source_conflicts']=conflicts[-100:]
        row.extraction_metadata=metadata
        # Events are immutable and unique per draft revision. Evidence changes
        # therefore own a new revision instead of colliding with the edit event.
        row.revision+=1
        for evidence in provenance.values():
            if evidence.get('source_id')==f"{state.get('task_id')}:{message_index}":
                evidence['draft_revision']=row.revision
        row.extraction_metadata={**(row.extraction_metadata or {}),'agent_provenance':provenance}
        drafts.record_event(db,row,principal.user_id,'task_explicit_fields',{'fields':[u['path'] for u in updates]})
        await db.commit()
    async def complete_explicit_names(content,message):
        from app.services.task_agent_evidence import explicit_master_names
        from app.services.purchase_memory_service import catalog_for
        from app.services.tally_connector import name,value
        from app.services.tally_connector import TallyError
        company=await drafts.company_for(db,principal,company_id)
        try:catalog=await catalog_for(db,company)
        except TallyError:return content
        result=explicit_master_names(content,message,
            [name(r) for r in catalog['ledgers'] if value(r,'PARENT')=='Sundry Creditors'],
            [name(r) for r in catalog['items']])
        native=[r for r in catalog.get('companies',[]) if name(r)==company.name]
        if len(native)==1 and value(native[0],'ISGSTON').casefold()=='yes' and not result.get('unsupported_treatments'):
            # Same GST working-copy route as existing chat, not tax approval.
            # The compiler still requires supported treatment and invoice evidence.
            result['tax_treatment']=result.get('tax_treatment') or 'regular_domestic_goods'
        from app.models.tally import TallyConnection
        cfg=await db.get(TallyConnection,principal.organization_id)
        if cfg and cfg.company==company.name and not result.get('godown'):
            result['godown']=cfg.godown
        return result
    def source_message(args):
        index=args['message_index']
        messages=state.get('messages',[])
        if index>=len(messages):
            from fastapi import HTTPException
            raise HTTPException(422,'Original user message unavailable.')
        return messages[index]
    async def authorize(args):
        from fastapi import HTTPException
        if company_id:
            await drafts.company_for(db, principal, company_id)
        else:
            from app.services.tally_business import admin
            admin(principal)
        if args.get('draft_id'):
            row = await drafts.scoped_draft(db, principal, args['draft_id'])
            if state.get('attachment_document_ids') and row.document_id not in state['attachment_document_ids']:
                raise HTTPException(404, 'Draft is outside attached sources.')
            if row.company_id != company_id:
                from fastapi import HTTPException
                raise HTTPException(404, 'Draft unavailable for task company.')
        if args.get('document_id'):
            from app.services.bill_document_service import document_for
            doc = await document_for(db, principal, args['document_id'])
            if state.get('attachment_document_ids') and doc.id not in state['attachment_document_ids']:
                raise HTTPException(404, 'Document is outside attached sources.')
            if doc.company_id != company_id:
                from fastapi import HTTPException
                raise HTTPException(404, 'Document unavailable for task company.')

    async def companies(args):
        return ToolResult(status='ok', data=await drafts.list_companies(db, principal))

    async def masters(args):
        result=await drafts.company_masters(db, principal, company_id)
        suppliers=[s for s in result.get('suppliers',[]) if not args.get('supplier_query') or args['supplier_query'].casefold() in s.casefold()]
        items=[i for i in result.get('items',[]) if not args.get('item_query') or args['item_query'].casefold() in i['name'].casefold()]
        return ToolResult(status='ok',data={**result,'suppliers':suppliers[:20],'items':items[:20],
            'coverage':{'supplier_results_truncated':len(suppliers)>20,'item_results_truncated':len(items)>20,
                        'scope':'filtered saved masters, suggestions only; not proof of invoice identity'}})

    async def read(args):
        result=await drafts.read_draft(db, principal, args['draft_id'])
        return ToolResult(status='ok', data={**result, **({'draft_id':result['id']} if state.get('attachment_document_ids') else {})})

    async def context(args):
        from app.services.purchase_situation import state as proposal
        result = await proposal(db, principal, args['draft_id'])
        return ToolResult(status='needs_input' if result.get('issues') else 'ok', data=result)

    async def update(args):
        from app.services.purchase_agent import apply_updates
        from app.services.purchase_situation import state as proposal,capture
        # The model selects the operation, but extraction must be grounded in
        # an actual user message, never in tool/document text or a model rewrite.
        try:
            message=source_message(args)
            updates=grounded(message,MessageFields(updates=args['updates'],unsupported_reason=None))
        except (ValueError, HTTPException):
            return ToolResult(status='ok',data={'draft_id':args['draft_id'],
                'validation_error':'No draft change: message_index or exact source quotes are invalid. Select the indexed message containing the facts.'})
        row=await drafts.scoped_draft(db,principal,args['draft_id'])
        if row.revision!=args['revision']:
            return ToolResult(status='ok',data={'draft_id':row.id,'current_revision':row.revision,
                'validation_error':'Draft revision changed. Read current draft before applying correction.'})
        import copy
        previous_content=copy.deepcopy(row.content)
        canonical=await complete_explicit_names(apply_updates(row.content,updates),message)
        await drafts.save_draft(db,principal,row.id,drafts.DraftSave(
            revision=row.revision,content=drafts.DraftContent.model_validate(canonical)))
        await annotate(row.id,updates,message,args['message_index'],previous_content=previous_content)
        await capture(db,principal,await drafts.scoped_draft(db,principal,row.id,lock=True),message)
        result=await proposal(db,principal,row.id)
        return ToolResult(status='needs_input' if result.get('issues') else 'ok', data=result)

    async def create(args):
        if state.get('attachment_document_ids'):
            return ToolResult(status='needs_input', data={'response':'Use the existing attached document draft; creating a replacement is blocked.'})
        from app.services.purchase_agent import apply_updates
        if state.get('task_id'):
            from app.models.agent_task import AgentTask
            task=await db.get(AgentTask,state['task_id'],populate_existing=True)
            if task and task.organization_id==principal.organization_id and task.user_id==principal.user_id and task.state.get('draft_id'):
                existing=await drafts.read_draft(db,principal,task.state['draft_id'])
                return ToolResult(status='ok',data={**existing,'draft_id':existing['id'],'reused':True})
        try:
            updates=grounded(source_message(args),MessageFields(updates=args['updates'],unsupported_reason=None))
        except (ValueError,HTTPException):
            return ToolResult(status='ok',data={'validation_error':'No draft created: explicit message evidence is invalid. Correct the source quotes and fields before retrying.'})
        content = apply_updates({'lines':[{}]}, updates)
        content = await complete_explicit_names(content,source_message(args))
        result = await drafts.create_draft(db, principal, drafts.DraftCreate(
            company_id=company_id, content=drafts.DraftContent.model_validate(content)))
        await annotate(result['id'],updates,source_message(args),args['message_index'])
        from app.services.purchase_situation import state as proposal,capture
        await capture(db,principal,await drafts.scoped_draft(db,principal,result['id'],lock=True),source_message(args))
        proposed=await proposal(db,principal,result['id'])
        return ToolResult(status='needs_input' if proposed.get('issues') else 'ok', data={**proposed,'draft_id':result['id']})

    async def preview(args):
        from fastapi import HTTPException
        try:
            from app.services.purchase_situation import state as proposal
            current=await proposal(db,principal,args['draft_id'])
            if current.get('issues'):return ToolResult(status='needs_input',data=current)
            if current['proposal']['revision']!=args['revision']:
                return ToolResult(status='needs_input',data={**current,'response':'Draft changed; current review dobara dekhein.'})
            result = await drafts.preview_draft(db, principal, args['draft_id'], drafts.DraftPreview(revision=args['revision']))
            from app.models.tally import TallyAction
            action=await db.get(TallyAction,result['preview']['token'])
            evidence=current['purchase_context']
            action.preconditions={**(action.preconditions or {}),'purchase_agent':{
                'draft_id':args['draft_id'],'revision':args['revision'],'cache_id':evidence.get('cache_id'),
                'generation':evidence.get('generation'),'rate_context':evidence.get('rate_context')}}
            await db.commit()
        except HTTPException as exc:
            if exc.status_code not in (409,422):raise
            # Validation is an observation for the planner, not an unknown
            # financial write. This adapter never submits an action.
            return ToolResult(status='ok',data={'draft_id':args['draft_id'],
                'validation_error':str(exc.detail)[:1000],'preview_created':False})
        return ToolResult(status='needs_approval', data=result)

    async def taxes(args):
        from app.services.purchase_tax_service import tax_check
        return ToolResult(status='ok', data=await tax_check(db, principal, args['draft_id']))

    async def receipt(args):
        from app.services.goods_receipt_service import preview,receipt as receipt_data
        from app.services.purchase_memory_service import catalog_for
        row = await drafts.scoped_draft(db, principal, args['draft_id'])
        company = await drafts.company_for(db, principal, company_id)
        if row.revision != args['revision']:
            from fastapi import HTTPException
            raise HTTPException(409,'Draft changed.')
        if not receipt_data(row):
            from app.services.purchase_situation import state as intake
            return ToolResult(status='needs_input',data=await intake(db,principal,row.id))
        if receipt_data(row).get('rate_basis')=='tax_inclusive':
            from app.services.purchase_situation import state as intake
            return ToolResult(status='needs_input',data=await intake(db,principal,row.id))
        return ToolResult(status='needs_approval', data=await preview(db, principal, row, await catalog_for(db, company)))

    async def situation(args):
        from app.services.purchase_situation import capture,state as intake
        row=await drafts.scoped_draft(db,principal,args['draft_id'],lock=True)
        if row.revision!=args['revision']:raise HTTPException(409,'Draft changed; review current situation.')
        await capture(db,principal,row,source_message(args))
        result=await intake(db,principal,row.id)
        return ToolResult(status='needs_input' if result.get('issues') or result.get('situation_choices') else 'ok',data=result)

    async def bill_fields(args):
        row=await drafts.scoped_draft(db,principal,args['draft_id'])
        if not row.document_id or row.document_id not in state.get('attachment_document_ids',[]):
            raise HTTPException(404,'Choose one of the bills attached to this task.')
        from app.services.bill_document_service import document_for
        doc=await document_for(db,principal,row.document_id)
        from app.services.chat_attachments import source_context
        sources=await source_context(db,principal,state,company_id)
        choices=[(source,draft) for source in sources for draft in source['drafts']]
        if len(choices)>1:
            from app.services.chat_attachments import referenced_bill_ids
            matching=referenced_bill_ids((state.get('messages') or [''])[-1],choices)
            if matching!=[row.id]:
                return ToolResult(status='needs_input',data={'response':'Kaunsa bill? Filename ya invoice number batayein.',
                    'bill_choices':[{'filename':source['filename'],'invoice_number':draft.get('content',{}).get('invoice_number')} for source,draft in choices]})
        labels={'party_name':'Supplier','invoice_number':'Invoice','entry_date':'Date','invoice_total':'Bill total ₹','lines':'Items','expected_taxes':'Tax amounts'}
        values={key:row.content.get(key) for key in args['fields']}
        import json
        lines=[doc.filename]
        for key,value in values.items():
            rendered='Unclear; original review karein' if value is None else json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else str(value)
            lines.append(labels[key]+': '+rendered)
        return ToolResult(status='needs_input',verified=True,data={'draft_id':row.id,'revision':row.revision,
            'document_id':doc.id,'values':values,'source':'current saved draft; original extraction retained in audit',
            'response':'\n'.join(lines)+'\nYe bill/draft ka jawab hai; nayi Tally entry post nahi hui.'})

    async def documents(args):
        from app.services.bill_document_service import document_for
        from app.services.invoice_extraction import list_document_drafts
        doc = await document_for(db, principal, args['document_id'])
        return ToolResult(status='ok', data=dict(document_id=doc.id,status=doc.status,
            extraction_status=doc.extraction_status,
            drafts=(await list_document_drafts(db,principal,doc.id))['drafts']))

    async def list_documents(args):
        from sqlalchemy import select
        from app.models.bill_document import BillDocument
        from app.services.bill_document_service import view
        if state.get('attachment_document_ids'):
            from app.services.chat_attachments import source_context
            return ToolResult(status='ok',data={'documents':await source_context(db,principal,state,company_id)})
        rows=(await db.scalars(select(BillDocument).where(
            BillDocument.organization_id==principal.organization_id,
            BillDocument.user_id==principal.user_id,BillDocument.company_id==company_id,
            BillDocument.trashed_at.is_(None)).order_by(BillDocument.created_at.desc()).limit(50))).all()
        return ToolResult(status='ok',data={'documents':[view(r) for r in rows],
            'coverage':'latest 50 documents; not a complete archive'})

    async def extract_document(args):
        from app.services.invoice_extraction_jobs import request_extraction
        result=await request_extraction(db, principal, args['document_id'])
        return ToolResult(status='ok' if result.get('drafts') else 'waiting_context', data={
            **result, 'document_id':args['document_id']})

    async def stock(args):
        from app.services.business_command_service import ParsedCommand
        from app.services.tally_stock import read_stock
        result=await read_stock(db,principal,ParsedCommand(
            intent='stock_read',company_id=company_id,company_scope='named',item_name=args['item_name']))
        live=bool(result.get('stock_results') and result.get('data_source')=='live' and not result.get('coverage',{}).get('partial'))
        return ToolResult(status='ok',data=result,verified=live)

    async def link(args):
        from app.services.goods_receipt_link_service import link, LinkRequest
        result = await link(db,principal,args['draft_id'],LinkRequest(
            revision=args['revision'],receipt_draft_id=args['receipt_draft_id'],receipt_revision=args['receipt_revision']))
        return ToolResult(status='ok',data=result)

    async def auto(args):
        from app.services.purchase_automation_service import evaluate
        return ToolResult(status='needs_approval',data=await evaluate(db,principal,args['draft_id'],force=True))

    async def report(args):
        from app.services.tally_mcp_service import read_report
        from app.services.business_command_service import ParsedCommand
        from app.services.tally_mcp import CONTRACTS
        # Use exact pinned contract field names; never widen tool access.
        schema=CONTRACTS[args['report']]['inputSchema']
        from datetime import date
        from fastapi import HTTPException
        messages='\n'.join(state.get('messages',[]))
        params={}
        for source,target in (('from_date','from'),('to_date','to'),('as_of','asOf')):
            if args.get(source) is None:continue
            value=date.fromisoformat(args[source])
            if not any(token in messages for token in (value.isoformat(),value.strftime('%d-%m-%Y'),value.strftime('%d/%m/%Y'))):
                raise HTTPException(422,'Report dates need explicit user evidence; please state the period.')
            if target in schema.get('properties',{}):params[target]=value.strftime('%d-%m-%Y')
        result=await read_report(db,principal,ParsedCommand(intent='mcp_read',company_id=company_id,
            company_scope='named',mcp_tool=args['report'],mcp_arguments=params))
        verified=result.get('capability')=='read_result'
        return ToolResult(status='ok' if verified else 'needs_input',data=result,verified=verified)

    tools = [Tool('request_capability_group','Expose another permitted capability group when the task needs it.',CapabilityGroup,'read',authorize,expand),
        Tool('list_companies', 'List permitted companies; ask user when company is ambiguous.', Empty, 'read', authorize, companies)]
    if company_id:
        tools.extend([
            Tool('company_masters', 'Search saved supplier/item/unit masters with sync time; partial spelling is only a suggestion.', MasterQuery, 'read', authorize, masters),
            Tool('read_purchase_draft', 'Read existing scoped draft and action status.', DraftId, 'read', authorize, read),
            Tool('purchase_context', 'Resolve draft identities, relevant history, validation and proposal.', DraftId, 'draft', authorize, context),
            Tool('record_purchase_situation', 'Record explicit bill availability, goods receipt, received date and rate basis from an indexed user message. Choose receipt workflow only when bill pending AND goods received are explicit.', DraftSituation, 'draft', authorize, situation),
            Tool('apply_user_message', 'Apply explicit facts/corrections from an exact user message.', DraftMessage, 'draft', authorize, update),
            Tool('create_purchase_draft', 'Create a purchase draft from explicit user message; never posts.', NewPurchase, 'draft', authorize, create),
            Tool('check_purchase_tax', 'Check saved draft tax and totals using existing validators.', DraftId, 'read', authorize, taxes),
            Tool('purchase_preview', 'Prepare exact revision review; never confirms or posts.', DraftRevision, 'draft', authorize, preview),
            Tool('receipt_preview', 'Prepare goods-received-without-bill review using existing receipt gates.', DraftRevision, 'draft', authorize, receipt),
            Tool('read_bill_fields','Answer selected facts from an exact attached bill draft. Use invoice_total for bill total, not purchase_context/history. Does not post.',BillFields,'read',authorize,bill_fields),
            Tool('document_status', 'Read permitted source document processing status.', DocumentId, 'read', authorize, documents),
            Tool('list_documents', 'Find recent private documents in this exact company; never assumes all archive covered.', Empty, 'read', authorize, list_documents),
            Tool('extract_document', 'Queue existing extraction with its own budget and evidence checks.', DocumentId, 'draft', authorize, extract_document),
            Tool('read_stock', 'Read live stock in this exact company; preserve date and unavailable status.', StockQuery, 'read', authorize, stock),
            Tool('link_receipt', 'Link exact full goods receipt to actual invoice through existing guards.', ReceiptLink, 'draft', authorize, link),
            Tool('evaluate_automation', 'Use existing policy/release gates; model confidence cannot authorise posting.', DraftId, 'write', authorize, auto),
            Tool('read_report', 'Read an allowlisted company report using existing rollout gates; do not invent period dates.', ReportQuery, 'read', authorize, report),
        ])
    if state.get('outcome') == 'answer':
        return [tool for tool in tools if tool.effect == 'read']
    if state.get('outcome') == 'draft' or os.getenv('PHILIXA_TASK_AGENT_REVIEW_ONLY','1')=='1':
        return [tool for tool in tools if tool.effect != 'write']
    return tools
