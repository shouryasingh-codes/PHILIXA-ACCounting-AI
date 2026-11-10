"""Regression against the unchanged realistic specimen that originally failed."""
import unittest
from pathlib import Path
from decimal import Decimal as D
from unittest.mock import patch,AsyncMock
from app.services import invoice_extraction as e
from app.services.invoice_ai_budget import BudgetPaused

class PracticeLayout(unittest.IsolatedAsyncioTestCase):
 async def test_free_pipeline_with_configured_key_and_disabled_budget(self):
  data=Path('scripts/fixtures/release/practice-layout.pdf').read_bytes()
  settings=type('S',(),{'gemini_api_key':'never-send','ai_api_key':''})()
  with patch.object(e,'get_settings',return_value=settings),patch('app.services.invoice_ai_budget.limits',side_effect=BudgetPaused()),patch.object(e,'_post_invoice_json',AsyncMock(side_effect=AssertionError('cloud forbidden'))) as cloud:
   raw=await e.extract_invoice_data(data,'application/pdf')
  cloud.assert_not_awaited()
  self.assertEqual(raw['buyer_name'],'Philixa Test')
  self.assertEqual(raw['supplier_name'],'Philixa GST TEST Supplier Local')
  self.assertEqual(raw['invoice_number'],'PX/26-27/1023')
  self.assertEqual(raw['invoice_date'],'02-Oct-2026')
  self.assertEqual(len(raw['lines']),2)
  for line,name,qty,rate,discount,gst,taxable in zip(raw['lines'],['Goods18','Goods5'],['12','8'],['125','87.5'],['5','0'],['18','5'],['1425','700']):
   self.assertEqual(line['item_name'],'Philixa GST TEST '+name)
   self.assertEqual(line['unit'],'bags');self.assertEqual(line['hsn'],'2523')
   for key,value in [('quantity',qty),('rate',rate),('discount_percent',discount),('gst_rate',gst),('taxable_amount',taxable)]:self.assertEqual(D(line[key]),D(value))
  for key,value in [('invoice_discount','0'),('round_off','.50'),('invoice_total','2417'),('subtotal','2125'),('tax_amount','291.50')]:self.assertEqual(D(str(raw[key])),D(value))
  self.assertEqual(raw['expected_taxes'],{'CGST':'145.75','SGST':'145.75'})
  self.assertEqual(raw['extraction_method'],'embedded_text')
  self.assertTrue(raw['warnings'])

 def test_combined_unit_missing_is_not_invented(self):
  page=type('Page',(),{'find_tables':lambda s:type('Tables',(),{'tables':[type('T',(),{'extract':lambda s:[['Description','Qty / Unit','Rate Rs.','Taxable Rs.'],['Item','12','100','1200']]})()]})()})()
  self.assertEqual(e.extract_ruled_invoice_tables(page,1),[])
