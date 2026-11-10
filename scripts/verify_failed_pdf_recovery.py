import asyncio,json
from sqlalchemy import select,func
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction
from app.jobs.task_agent_jobs import principal_for
from app.services import purchase_draft_service as drafts
async def main():
 async with AsyncSessionLocal() as db:
  task=await db.get(AgentTask,'13a077663b3267f8f49a35e2f38e82d4')
  principal=await principal_for(db,task)
  rows=(await db.scalars(select(PurchaseDraft).where(PurchaseDraft.document_id=='989f76134da045e19d2b64e2ef6c64e9').order_by(PurchaseDraft.created_at,PurchaseDraft.id))).all()
  before=await db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==task.organization_id))
  result=[]
  for row in rows:
   ident,revision=row.id,row.revision
   info={'draft_id':ident,'invoice':row.content.get('invoice_number'),'total':row.content.get('invoice_total'),'pages':row.extraction_metadata.get('source_pages'),'lines':len(row.content.get('lines') or []),'action_id':row.action_id}
   try:await drafts.preview_draft(db,principal,ident,drafts.DraftPreview(revision=revision));raise AssertionError('Expected source company block')
   except HTTPException as error:info['blocked']=error.status_code==422 and 'Company mismatch' in str(error.detail)
   result.append(info)
  after=await db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==principal.organization_id))
  assert len(result)==2 and all(row['blocked'] and row['action_id'] is None for row in result) and before==after
  print(json.dumps({'drafts':result,'new_tally_actions':after-before}))
asyncio.run(main())
