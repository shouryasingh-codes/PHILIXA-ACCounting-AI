"""Read-only extraction benchmark: no cloud requests, no database writes."""
import asyncio,json
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch,AsyncMock
from decimal import Decimal
from app.services import invoice_extraction as e
from fastapi import HTTPException

async def main():
 data=Path('/tmp/philixa-practice-check.pdf').read_bytes()
 settings=replace(e.get_settings(),gemini_api_key='',ai_api_key='')
 cloud=AsyncMock(side_effect=AssertionError('Paid API forbidden in free test'))
 with patch.object(e,'get_settings',return_value=settings),patch.object(e,'_post_invoice_json',cloud):
  try:
   raw=await e.extract_invoice_data(data,'application/pdf')
  except HTTPException as exc:
   raw=e.extract_from_pdf_text_local(data)
   raw['pipeline_error']=exc.detail
 cloud.assert_not_awaited()
 print(json.dumps(raw,indent=2,default=str))
 Path('/app/data/practice-free').mkdir(parents=True,exist_ok=True)
 Path('/app/data/practice-free/extracted.json').write_text(json.dumps(raw,indent=2,default=str))
asyncio.run(main())
