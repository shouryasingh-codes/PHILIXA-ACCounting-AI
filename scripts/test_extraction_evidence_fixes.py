"""Evidence regressions: explicit amounts, ambiguous labels, crop agreement."""
import copy
import json
from pathlib import Path
import unittest
from app.services.invoice_extraction import invoice_discount_from_text, extract_from_pdf_text_local, verify_and_match
from app.services.local_invoice_ocr import parse_tokens


class EvidenceFixes(unittest.TestCase):
    def test_invoice_discount_requires_unique_explicit_money_evidence(self):
        for text,value in [('Invoice Discount: 0','0'),('Bill Discount INR:\n100.00','100.00'),('Overall Discount: 1,250.50','1250.50')]:
            self.assertEqual(invoice_discount_from_text(text),value)
        for text in ('Discount: 100','Invoice Discount: 10%','Invoice Discount: -5','Invoice Discount: 5\nInvoice Discount: 6','Grand Total: 1050'):
            self.assertIsNone(invoice_discount_from_text(text),text)

    def test_pdf_literal_supplier_and_invoice_discount_independent_of_master(self):
        import pymupdf
        for supplier in ('Supplier','Supplier Engineering Ltd','Acme Materials'):
            doc=pymupdf.open();page=doc.new_page()
            page.insert_text((30,30),'TAX INVOICE\n'+supplier+'\nGSTIN: 06ABCPF1234G1ZC\nInvoice No: EVID-1\nInvoice Date: 02-Oct-2026\nBill To\nBuyer Ltd\nInvoice Discount: 100.00\nGrand Total: 900.00')
            data=doc.tobytes();doc.close()
            raw=extract_from_pdf_text_local(data)
            self.assertEqual(raw['supplier_name'],supplier)
            self.assertEqual(raw['invoice_discount'],'100.00')

    def test_two_crop_reads_correct_unit_but_preserve_original_and_review_gate(self):
        raw=json.loads(Path('data/day5-native/local-structured-proof.json').read_text())
        tokens=copy.deepcopy(raw['source_tokens'])
        token=next(t for t in tokens if t['text']=='qags')
        token['unit_rereads']=[{'text':'bags','confidence':.999},{'text':'bags','confidence':.998}]
        result=parse_tokens(tokens,1684,1190)
        self.assertEqual(result['lines'][0]['unit'],'bags')
        evidence=result['lines'][0]['source_evidence']['unit']
        self.assertEqual(evidence['raw'],'qags')
        self.assertEqual(evidence['corrected_from'],'qags')
        self.assertLess(evidence['confidence'],.8)
        verified=verify_and_match(result,{'suppliers':[],'items':[]})
        self.assertTrue(any('source review' in w for w in verified['warnings']))
        token['unit_rereads'][1]['text']='kgs'
        self.assertEqual(parse_tokens(tokens,1684,1190)['lines'][0]['unit'],'qags')
        token['unit_rereads'][1]={'text':'bags','confidence':.7}
        self.assertEqual(parse_tokens(tokens,1684,1190)['lines'][0]['unit'],'qags')


if __name__=='__main__':unittest.main()
