import unittest
from pathlib import Path
from app.services.invoice_extraction import extract_from_pdf_text_local,verify_and_match
class UploadedBill(unittest.TestCase):
 def test_cells_keep_hsn_separate_from_quantity_and_supplier_from_buyer(self):
  raw=extract_from_pdf_text_local(Path('data/day5-native/test-bill-source.pdf').read_bytes())
  self.assertEqual(raw['supplier_name'],'Radha Krishna Building Materials');self.assertEqual(raw['invoice_number'],'RK/2026-27/0842')
  self.assertEqual([r['quantity'] for r in raw['lines']],['50','200','100']);self.assertEqual([r['rate'] for r in raw['lines']],['380.00','62.00','45.00']);self.assertEqual([r['hsn'] for r in raw['lines']],['2523','7214','2505'])
  self.assertEqual(raw['buyer_name'],'M/s Sharma Construction Pvt. Ltd.')
  from app.services.purchase_draft_service import validate_document_company
  from fastapi import HTTPException
  with self.assertRaises(HTTPException):validate_document_company(raw,'Philixa Test')
  with self.assertRaises(HTTPException):validate_document_company({},'Philixa Test')
  validate_document_company(raw,'Sharma Construction Pvt. Ltd.')
  result=verify_and_match(raw,{'suppliers':[],'items':[]});self.assertEqual(str(result['entry_date']),'2026-10-14');self.assertEqual(result['calculated_total'],'42461.00');self.assertFalse(any('Calculation mismatch' in w or 'Invoice total mismatch' in w for w in result['warnings']))
if __name__=='__main__':unittest.main()
