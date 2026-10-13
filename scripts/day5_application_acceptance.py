import asyncio,json
from types import SimpleNamespace
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyAction
from app.models.organization_membership import OrganizationMembership
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts,tally_sync as sync
from scripts.day5_native_setup import ROOT,COMPANY
async def main():
 async with AsyncSessionLocal() as db:
  co=await db.scalar(select(TallyReadCompany).where(TallyReadCompany.name==COMPANY,TallyReadCompany.enabled.is_(True)));m=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==co.organization_id,OrganizationMembership.role=='owner',OrganizationMembership.status=='active'))
  principal=SimpleNamespace(organization_id=co.organization_id,user_id=m.user_id,role=m.role,session_id='day5-authorized-practice-acceptance')
  row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.company_id==co.id,PurchaseDraft.content['invoice_number'].as_string()=='D5-APP-E2E'))
  if row is None:
   src=json.loads((ROOT/'codec-final-proof.json').read_text())['payload']['source'];src['invoice_number']='D5-APP-E2E';d=await drafts.create_draft(db,principal,drafts.DraftCreate(company_id=co.id,content=src));row=await db.get(PurchaseDraft,d['id'])
  action=await db.get(TallyAction,row.action_id) if row.action_id else None
  if action is not None and action.status=='needs_review' and isinstance(action.result,dict) and action.result.get('uncertain') is False:action=None
  if action is None:
   preview=await drafts.preview_draft(db,principal,row.id,drafts.DraftPreview(revision=row.revision));action=await db.get(TallyAction,preview['preview']['token'])
  if action.status=='preview':await sync.confirm_queued(db,principal,action)
  # Respect the same company lock as the background worker.
  for _ in range(8):
   await db.refresh(action)
   if action.status in ('verified','failed','needs_review'):break
   async with sync.company_lock(co.id) as locked:
    if locked:await sync.process_action(db,action,co)
   await asyncio.sleep(1)
  await db.refresh(action);out={'draft_id':row.id,'action_status':action.status,'result':action.result,'helper_protocol':8,'workflow':'saved draft -> preview -> authorized approval -> installed helper -> native readback'};(ROOT/'application-e2e-proof.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True);assert action.status=='verified'
asyncio.run(main())
