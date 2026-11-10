import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.services.bill_document_service import original_bytes
import pymupdf
async def main():
 async with AsyncSessionLocal() as db:
  row=await db.scalar(select(BillDocument).where(BillDocument.filename=='itemInvoiceDownload-2.pdf').order_by(BillDocument.created_at.desc()).limit(1))
  if not row:print('Not found');return
  data=await original_bytes(row)
  with pymupdf.open(stream=data,filetype='pdf') as pdf:
   print(json.dumps(dict(id=row.id,pages=len(pdf),status=row.extraction_status,split=row.extraction_split,error=row.extraction_error)))
   for i,page in enumerate(pdf):print('PAGE',i+1, page.get_text()[:6500])
asyncio.run(main())
