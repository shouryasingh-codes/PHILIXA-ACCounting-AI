import asyncio
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.services import invoice_extraction as e,purchase_draft_service as d,bill_document_service as docs
from types import SimpleNamespace
async def main():
 async with AsyncSessionLocal() as db:
  doc=await db.get(BillDocument,'f8b967ae81651ec56615a97f4b2e5f2f')
  row=await db.get(PurchaseDraft,'ae9c51b5a2d4e1b99e33a79de434c046',with_for_update=True)
  assert row.document_id==doc.id and row.action_id is None
  raw=e.extract_from_pdf_text_local(await docs.original_bytes(doc))
  assert raw['buyer_name']=='M/s Sharma Construction Pvt. Ltd.'
  principal=SimpleNamespace(user_id=doc.user_id,organization_id=doc.organization_id,role='owner')
  v=e.verify_and_match(raw,await d.company_masters(db,principal,doc.company_id))
  doc.extraction_result={**doc.extraction_result,'buyer_name':raw['buyer_name']}
  row.extraction_metadata={**row.extraction_metadata,'line_evidence':v['line_evidence'],'warnings':v['warnings']+['Company mismatch: bill buyer is '+raw['buyer_name']+'; selected company is Philixa Test. Posting blocked.']}
  row.revision+=1;row.updated_at=docs.now()
  d.record_event(db,row,doc.user_id,'source_buyer_identity_checked')
  await db.commit()
  print('Saved source buyer evidence; draft values unchanged; no Tally action.')
asyncio.run(main())
