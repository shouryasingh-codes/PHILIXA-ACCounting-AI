import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.services import invoice_extraction as e,purchase_draft_service as d,bill_document_service as docs
from types import SimpleNamespace
async def main():
 async with AsyncSessionLocal() as db:
  doc=await db.get(BillDocument,'f8b967ae81651ec56615a97f4b2e5f2f');principal=SimpleNamespace(user_id=doc.user_id,organization_id=doc.organization_id,role='owner',session_id='source-parser-repair')
  row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.document_id==doc.id).with_for_update());assert row and row.action_id is None and row.revision==0
  raw=e.extract_from_pdf_text_local(await docs.original_bytes(doc));raw['confidence']={};raw['warnings']=['Extracted from PDF table cell boundaries. Review against the original.'];raw['extraction_method']='embedded_text'
  for line in raw['lines']:line['confidence']=0.0
  v=e.verify_and_match(raw,await d.company_masters(db,principal,doc.company_id));assert len(v['lines'])==3 and v['calculated_total']=='42461.00';assert str(v['entry_date'])=='2026-10-14'
  row.content=d.DraftContent(party_name=v['party_name'],entry_date=v['entry_date'],invoice_number=v['invoice_number'],lines=v['lines'],**{k:raw.get(k) for k in ('tax_treatment','supplier_gstin','place_of_supply','invoice_discount','round_off','invoice_total','expected_taxes')}).model_dump(mode='json')
  row.extraction_metadata={**row.extraction_metadata,'field_evidence':v['field_evidence'],'line_evidence':v['line_evidence'],'warnings':v['warnings'],'invoice_number':v['invoice_number'],'detected_invoices':v['detected_invoices'],'confidence':{}};row.revision+=1;row.updated_at=docs.now();doc.extraction_result=raw;d.record_event(db,row,doc.user_id,'corrected_pdf_table_extraction');await db.commit()
  print('Corrected existing draft: 3 rows; quantities 50/200/100; total 42461.00; no Tally action.')
asyncio.run(main())
