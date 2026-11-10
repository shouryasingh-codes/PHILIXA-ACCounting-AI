import asyncio,io,json,sys
from pathlib import Path
from decimal import Decimal as D
from types import SimpleNamespace
import pymupdf
from fastapi import UploadFile
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyReadCompany
from app.models.organization_membership import OrganizationMembership
from app.services import bill_document_service as docs,invoice_extraction_jobs as jobs
async def run():
 from app.core.arq import init_arq_pool
 await init_arq_pool()
 fmt=sys.argv[1];assert fmt in ('png','jpeg')
 pdf=pymupdf.open('data/day5-native/philixa-matching-test-bill.pdf');data=pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes(fmt)
 path=Path('data/day5-native/matching-ocr.'+fmt);path.write_bytes(data)
 async with AsyncSessionLocal() as db:
  co=await db.scalar(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True)))
  member=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==co.organization_id,OrganizationMembership.role=='owner',OrganizationMembership.status=='active'))
  p=SimpleNamespace(organization_id=co.organization_id,user_id=member.user_id,role=member.role)
  batch=await docs.create_batch(db,p,docs.BatchCreate(company_id=co.id))
  result=await docs.upload_document(db,p,batch['id'],UploadFile(filename=path.name,file=io.BytesIO(data)))
  doc_id=result['document']['id']
 for _ in range(60):
  async with AsyncSessionLocal() as db:
   doc=await db.get(BillDocument,doc_id)
   if doc.status=='ready':break
   assert doc.status not in ('error','rejected'),doc.error_code
  await asyncio.sleep(1)
 async with AsyncSessionLocal() as db:await jobs.request_extraction(db,p,doc_id)
 print('QUEUED '+fmt+' document '+doc_id,flush=True)
 for _ in range(110):
  async with AsyncSessionLocal() as db:
   doc=await db.get(BillDocument,doc_id)
   if doc.extraction_status=='error':raise AssertionError(doc.extraction_error)
   row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.document_id==doc_id))
   if row:
    c=row.content;raw=doc.extraction_result;lines=c['lines']
    assert row.action_id is None,'Unexpected posting action'
    assert c['party_name']=='Philixa GST TEST Supplier Local' and raw['buyer_name']=='Philixa Test'
    assert c['invoice_number']=='PHILIXA-UPLOAD-TEST-01' and c['entry_date']=='2026-10-02'
    assert len(lines)==2
    for line,item,q,discount,gst,taxable in zip(lines,['Goods18','Goods5'],['10','1'],['10','0'],['18','5'],['900','100']):
     assert line['item_name']=='Philixa GST TEST '+item
     assert D(line['quantity'])==D(q) and D(line['rate'])==100
     assert D(line.get('discount_percent') or 0)==D(discount) and D(line['gst_rate'])==D(gst)
     assert D(line['taxable_amount'])==D(taxable) and line['hsn']=='2523'
     assert line['unit']==('qags' if item=='Goods18' else 'bags')
    assert D(c['invoice_total'])==1167 and D(c['expected_taxes']['CGST'])==D('83.50') and D(c['expected_taxes']['SGST'])==D('83.50')
    assert raw.get('extraction_method')=='local_ocr'
    evidence=row.extraction_metadata['line_evidence'][0]['unit']
    assert evidence['reread']['text']=='bags' and evidence['suggested_value']=='bags'
    result={'format':fmt,'document_id':doc_id,'draft_id':row.id,'method':raw.get('extraction_method'),'content':c,'status':doc.extraction_status,'action_id':row.action_id,'passed':True}
    Path('data/day5-native/'+fmt+'-local-workflow-proof.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True);return
  await asyncio.sleep(2)
 raise AssertionError('Processing exceeded test wait budget')
asyncio.run(run())
