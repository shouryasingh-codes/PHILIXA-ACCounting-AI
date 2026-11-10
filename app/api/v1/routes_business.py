"""Authenticated compatibility API; graph nodes execute reusable business services."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.services.business_command_service import (
    CommandFields, ParsedCommand, CommandRequest, ApprovalRequest, guard_tally_scope,
    interpret, today, delivery_blockers, preview,
)
from app.services.portfolio_copilot_service import run_business_graph
router = APIRouter(prefix="/business", tags=["Business chat"])

from app.services import task_agent_service as task_agent

@router.get('/task-capabilities')
async def agent_task_capabilities(principal: CurrentPrincipal):
    import os
    from app.services.business_router import enabled, frontdoor_enabled
    from app.services.intent_router_model import ready
    from app.services.chat_attachments import enabled as attachment_enabled
    return {'enabled':os.getenv('PHILIXA_TASK_AGENT_ENABLED','0') == '1','router_enabled':frontdoor_enabled(),'domain_routing_enabled':enabled(),'router_model_ready':ready(),'chat_attachments_enabled':attachment_enabled() and os.getenv('PHILIXA_TASK_AGENT_ENABLED','0')=='1'}

@router.post('/tasks')
async def create_agent_task(request: task_agent.TaskCreate, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.create(db, principal, request)

@router.get('/routing/{route_id}')
async def routing_status(route_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    from app.services.business_router import status
    return await status(db,principal,route_id)

from pydantic import BaseModel, Field

class RoutingRetry(BaseModel):
    request_id: str = Field(min_length=16,max_length=64)

@router.post('/routing/{route_id}/retry')
async def retry_routing(route_id: str, request: RoutingRetry, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    from app.services.business_router import retry
    return await retry(db,principal,route_id,request.request_id)

@router.get('/tasks/{task_id}')
async def get_agent_task(task_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.read(db, principal, task_id)

@router.get('/tasks/{task_id}/metrics')
async def agent_task_metrics(task_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.metrics(db,principal,task_id)

@router.post('/tasks/{task_id}/approve')
async def approve_agent_task(task_id: str, request: task_agent.TaskApproval, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.approve(db,principal,task_id,request)

@router.post('/tasks/{task_id}/resume')
async def resume_agent_task(task_id: str, request: task_agent.TaskResume, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.resume(db, principal, task_id, request)

@router.post('/tasks/{task_id}/cancel')
async def cancel_agent_task(task_id: str, request: task_agent.TaskResume, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await task_agent.cancel(db, principal, task_id, request.expected_revision)

from app.services import business_conversation_service as conversations
from app.services import purchase_draft_service as drafts

@router.get('/purchase-drafts/companies')
async def draft_companies(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.list_companies(db,principal)

@router.get('/purchase-drafts')
async def list_bill_drafts(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.list_drafts(db,principal)

@router.get('/purchase-drafts/companies/{company_id}/masters')
async def bill_company_masters(company_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.company_masters(db,principal,company_id)

@router.post('/purchase-drafts')
async def create_bill_draft(request: drafts.DraftCreate, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.create_draft(db,principal,request)

from app.services import purchase_review_service as review_queue

@router.get('/purchase-drafts/review-queue')
async def bill_review_queue(principal: CurrentPrincipal, view: str = 'all', offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    return await review_queue.queue(db,principal,view,offset,limit)

@router.post('/purchase-drafts/bulk-approve')
async def approve_bill_selection(request: review_queue.BulkApproval, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await review_queue.bulk_approve(db,principal,request)

from app.services import purchase_memory_service as bill_memory
from app.services import purchase_automation_service as automation
from app.services import bill_evaluation_service as evaluation

@router.get('/purchase-drafts/{draft_id}/evaluation-metrics')
async def bill_evaluation_metrics(draft_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await evaluation.metrics(db,principal,draft_id)

@router.post('/purchase-drafts/{draft_id}/review-time')
async def bill_review_time(draft_id:str,request:evaluation.ReviewSample,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await evaluation.record_review(db,principal,draft_id,request)

@router.get('/purchase-drafts/companies/{company_id}/automation')
async def automation_policy(company_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await automation.policy_view(db,principal,company_id)

@router.put('/purchase-drafts/companies/{company_id}/automation')
async def save_automation_policy(company_id:str,request:automation.PolicySave,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await automation.save_policy(db,principal,company_id,request)

@router.post('/purchase-drafts/companies/{company_id}/automation/pause')
async def pause_automation_policy(company_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await automation.pause_policy(db,principal,company_id)

@router.post('/purchase-drafts/{draft_id}/automation-evaluate')
async def evaluate_automation(draft_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await automation.evaluate(db,principal,draft_id,force=True)

@router.get('/purchase-drafts/{draft_id}/automation-decisions')
async def automation_decisions(draft_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await automation.history(db,principal,draft_id)

@router.get('/purchase-drafts/companies/{company_id}/aliases')
async def bill_aliases(company_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await bill_memory.alias_list(db,principal,company_id)

@router.post('/purchase-drafts/{draft_id}/aliases')
async def remember_bill_correction(draft_id: str, request: bill_memory.AliasApproval, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await bill_memory.approve_alias(db,principal,draft_id,request)

@router.get('/purchase-drafts/{draft_id}')
async def read_bill_draft(draft_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.read_draft(db,principal,draft_id)


from app.services import purchase_conversation
from app.services import goods_receipt_link_service as receipt_links

@router.post('/purchase-drafts/{draft_id}/receipt-link')
async def link_receipt(draft_id:str,request:receipt_links.LinkRequest,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await receipt_links.link(db,principal,draft_id,request)

@router.get('/purchase-drafts/companies/{company_id}/receipts')
async def receipt_choices(company_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await receipt_links.available(db,principal,company_id)

@router.post('/purchase-drafts/{draft_id}/chat')
async def purchase_chat(draft_id:str,request:purchase_conversation.Reply,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services.tally_connector import TallyError
    from fastapi import HTTPException
    try:return await purchase_conversation.answer(db,principal,draft_id,request)
    except TallyError as exc:raise HTTPException(409,str(exc))

@router.post('/purchase-drafts/{draft_id}/context-refresh')
async def purchase_context_refresh(draft_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services import purchase_native_context as context
    if not context.enabled():raise HTTPException(409,'Purchase agent rollout disabled.')
    row=await drafts.scoped_draft(db,principal,draft_id,lock=True)
    await drafts.editable_action(db,row,row.revision)
    result=await context.context(db,principal,row,force=True)
    await db.commit()
    return result

@router.put('/purchase-drafts/{draft_id}')
async def save_bill_draft(draft_id: str, request: drafts.DraftSave, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.save_draft(db,principal,draft_id,request)

@router.get('/purchase-drafts/{draft_id}/audit')
async def bill_audit(draft_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.audit_draft(db,principal,draft_id)

@router.post('/purchase-drafts/{draft_id}/preview')
async def preview_bill_draft(draft_id: str, request: drafts.DraftPreview, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.preview_draft(db,principal,draft_id,request)

@router.get('/conversations')
async def list_chats(principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await conversations.list_conversations(db,principal)

@router.post('/conversations')
async def create_chat(request: conversations.ConversationCreate, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await conversations.create_conversation(db,principal,request)

@router.get('/conversations/{conversation_id}')
async def read_chat(conversation_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await conversations.read_conversation(db,principal,conversation_id)

@router.put('/conversations/{conversation_id}')
async def save_chat(conversation_id: str, request: conversations.ConversationSave, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await conversations.save_conversation(db,principal,conversation_id,request)


@router.delete('/conversations/{conversation_id}')
async def delete_chat(conversation_id: str, principal: CurrentPrincipal, revision: int = Query(ge=0), db: AsyncSession = Depends(get_db)):
    return await conversations.delete_conversation(db,principal,conversation_id,revision)


@router.post('/conversations/{conversation_id}/restore')
async def restore_chat(conversation_id: str, request: conversations.ConversationRevision, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await conversations.restore_conversation(db,principal,conversation_id,request.revision)

@router.post("/command")
async def command(request: CommandRequest, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)) -> dict:
    if request.attachments:
        from app.services.chat_attachments import accept
        return await accept(db,principal,request)
    import os
    from app.services import business_router
    if business_router.frontdoor_enabled():
        return await business_router.route(db,principal,request)
    from app.services.business_help import help_answer, reply
    answer = help_answer(request.text) if not request.selection and not request.context_refresh else None
    if answer:
        # Standalone help must not resume or mutate the previous accounting task.
        return reply(answer)
    if request.task_id and request.request_id and task_agent.stock_read_question(request.text):
        previous=await task_agent.scoped(db,principal,request.task_id)
        return await task_agent.create(db,principal,task_agent.TaskCreate(message=request.text,
            request_id=request.request_id,company_id=request.fields.company_id or previous.company_id,outcome='answer'))
    if request.task_id:
        if request.expected_revision is None or not request.request_id:
            raise HTTPException(422,'Task resume requires revision and request ID.')
        return await task_agent.resume(db, principal, request.task_id, task_agent.TaskResume(
            expected_revision=request.expected_revision,request_id=request.request_id,message=request.text,company_id=request.fields.company_id,selection=request.selection,context_refresh=request.context_refresh))
    if os.getenv('PHILIXA_TASK_AGENT_ENABLED','0') == '1' and request.request_id:
        return await task_agent.create(db,principal,task_agent.TaskCreate(message=request.text,
            request_id=request.request_id,company_id=request.fields.company_id,
            outcome='answer' if request.intent in ('stock_read','mcp_read','supplier_list','supplier_read','customer_list','customer_read') else 'verified_entry'))
    return await run_business_graph(request, principal, db)

@router.post("/confirm")
async def confirm(request: ApprovalRequest, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)) -> dict:
    return await run_business_graph(request, principal, db, approval=True)

@router.get('/tally-capabilities')
async def tally_capabilities(principal: CurrentPrincipal):
    from app.services.tally_mcp import capability_view, PIN
    import os
    return {'backend':'mcp','commit':PIN,'read_rollout_enabled':os.getenv('PHILIXA_MCP_READ_ENABLED')=='1',
            'tools':capability_view()}


from app.services import purchase_tax_service as purchase_tax

@router.get('/purchase-drafts/companies/{company_id}/tax-profile')
async def tax_profile(company_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await purchase_tax.profile_view(db,principal,company_id)

@router.put('/purchase-drafts/companies/{company_id}/tax-profile')
async def tax_profile_save(company_id:str,request:purchase_tax.TaxProfileSave,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await purchase_tax.save_profile(db,principal,company_id,request)

@router.get('/purchase-drafts/{draft_id}/tax-check')
async def tax_check(draft_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await purchase_tax.tax_check(db,principal,draft_id)
