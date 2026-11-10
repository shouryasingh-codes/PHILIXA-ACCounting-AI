import asyncio,json
from pathlib import Path
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.bill_document import BillDocument
from app.services.bill_document_service import original_bytes
import pymupdf
async def main():
 async with AsyncSessionLocal() as db:
  row=await db.scalar(select(BillDocument).where(BillDocument.id=='989f76134da045e19d2b64e2ef6c64e9'))
  data=await original_bytes(row)
  with pymupdf.open(stream=data,filetype='pdf') as pdf:
   from app.services.embedded_invoice_layout import page_invoice,extract_document
   for i,page in enumerate(pdf):
    result=page_invoice(page,i+1)
    print(json.dumps({'page':i+1,'invoice':result[0] if result else None,'lines':len(result[1]) if result else 0},ensure_ascii=False))
asyncio.run(main())
