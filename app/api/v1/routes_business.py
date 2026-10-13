"""Authenticated compatibility API; graph nodes execute reusable business services."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.services.business_command_service import (
    CommandFields, ParsedCommand, CommandRequest, ApprovalRequest, guard_tally_scope,
    interpret, today, delivery_blockers, preview,
)
from app.services.portfolio_copilot_service import run_business_graph
router = APIRouter(prefix="/business", tags=["Business chat"])

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

@router.get('/purchase-drafts/{draft_id}')
async def read_bill_draft(draft_id: str, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)):
    return await drafts.read_draft(db,principal,draft_id)

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

@router.post("/command")
async def command(request: CommandRequest, principal: CurrentPrincipal, db: AsyncSession = Depends(get_db)) -> dict:
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
