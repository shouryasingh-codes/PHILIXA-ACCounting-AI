import asyncio,io,json
from pathlib import Path
from types import SimpleNamespace
import fitz
from fastapi import UploadFile
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyAction,TallyConnection
from app.models.organization_membership import OrganizationMembership
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.services import bill_document_service as docs,invoice_extraction as extraction,purchase_draft_service as drafts,tally_sync as sync
from app.jobs.document_jobs import validate_bill_document
from app.services.tally_connector import TallyConnector,name
ROOT=Path('data/day5-native');PDF=ROOT/'philixa-matching-test-bill.pdf';PROOF=ROOT/'matching-upload-proof.json'
def make_pdf():
 if PDF.exists():return
 d=fitz.open();p=d.new_page(width=842,height=595)
 def text(y,s,size=11):p.insert_text((30,y),s,fontsize=size)
 for y,s in [(30,'DUMMY PRACTICE BILL - NOT A REAL BUSINESS INVOICE'),(55,'TAX INVOICE'),(75,'Philixa GST TEST Supplier Local'),(95,'GSTIN: 06ABCPF1234G1ZC'),(115,'Invoice No: PHILIXA-UPLOAD-TEST-01'),(135,'Invoice Date: 02-Oct-2026'),(155,'Place of Supply: Haryana (06)'),(175,'Bill To / Buyer Details'),(195,'Philixa Test'),(215,'GSTIN: 06ABCPE1234F1ZF')]:text(y,s)
 xs=[30,285,350,400,450,515,570,650,710];ys=[240,265,290,315]
 for x in xs:p.draw_line((x,ys[0]),(x,ys[-1]),color=(0,0,0))
 for y in ys:p.draw_line((xs[0],y),(xs[-1],y),color=(0,0,0))
 rows=[['Description','HSN','Unit','Qty','Rate','Disc %','Taxable Amt','GST %'],['Philixa GST TEST Goods18','2523','bags','10','100.00','10%','900.00','18%'],['Philixa GST TEST Goods5','2523','bags','1','100.00','0%','100.00','5%']]
 for i,row in enumerate(rows):
  for j,v in enumerate(row):p.insert_text((xs[j]+4,ys[i]+16),v,fontsize=9)
 for y,s in [(345,'CGST'),(365,'83.50'),(390,'SGST'),(410,'83.50'),(435,'Round Off'),(455,'0.00'),(480,'Grand Total: 1167.00'),(520,'Test date is 02-Oct-2026 for Tally EDU. Original invoice date must never be silently changed.')]:text(y,s)
 d.save(PDF);d.close()
async def main():
 make_pdf()
 async with AsyncSessionLocal() as db:
  co=await db.scalar(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True)))
  cfg=await db.get(TallyConnection,co.organization_id);assert cfg.test_company and cfg.company=='Philixa Test'
  cat=await TallyConnector().catalog('Philixa Test')
  assert all(x in [name(i) for i in cat['items']] for x in ['Philixa GST TEST Goods18','Philixa GST TEST Goods5'])
  m=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==co.organization_id,OrganizationMembership.role=='owner',OrganizationMembership.status=='active'))
  principal=SimpleNamespace(organization_id=co.organization_id,user_id=m.user_id,role=m.role,session_id='authorized-matching-dummy-bill-test')
  row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.company_id==co.id,PurchaseDraft.content['invoice_number'].as_string()=='PHILIXA-UPLOAD-TEST-01'))
  if row is None:
   batch=await docs.create_batch(db,principal,docs.BatchCreate(company_id=co.id))
   upload=await docs.upload_document(db,principal,batch['id'],UploadFile(filename=PDF.name,file=io.BytesIO(PDF.read_bytes())))
   document_id=upload['document']['id'];await validate_bill_document({},document_id)
   raw=extraction.extract_from_pdf_text_local(PDF.read_bytes())
   assert raw['buyer_name']=='Philixa Test' and len(raw['lines'])==2 and raw['invoice_total']=='1167.0',raw
   result=await extraction.process_document_extraction(db,principal,document_id,raw_result=raw)
   row=await db.get(PurchaseDraft,result['draft']['id'])
  action=await db.get(TallyAction,row.action_id) if row.action_id else None
  if action is None:
   result=await drafts.preview_draft(db,principal,row.id,drafts.DraftPreview(revision=row.revision));action=await db.get(TallyAction,result['preview']['token'])
  if action.status=='preview':await sync.confirm_queued(db,principal,action)
  for _ in range(12):
   await db.refresh(action)
   if action.status in ('verified','failed','needs_review'):break
   async with sync.company_lock(co.id) as locked:
    if locked:await sync.process_action(db,action,co)
   await asyncio.sleep(2)
  await db.refresh(action)
  proof={'draft_id':row.id,'document_id':row.document_id,'status':action.status,'result':action.result,'workflow':'private PDF upload -> local structured extraction -> saved draft -> company check -> preview -> authorized dummy approval -> helper/native readback'}
  PROOF.write_text(json.dumps(proof,indent=2));print(json.dumps(proof),flush=True)
  assert action.status=='verified',proof
asyncio.run(main())
