import copy
import json
import unittest
from pathlib import Path
from app.services.local_invoice_ocr import parse_tokens
from app.services.invoice_extraction import verify_and_match


class RetailInvoice(unittest.TestCase):
    def setUp(self):
        self.source=json.loads(Path('scripts/fixtures/release/retail-gst-tokens.json').read_text())

    def parse(self):
        return parse_tokens(**self.source)

    def change(self, old, new, after=0):
        hits=[t for t in self.source['tokens'] if t['text']==old and t['box'][1]>=after]
        self.assertEqual(len(hits),1)
        hits[0]['text']=new

    def test_actual_ocr_values_and_tax_inclusive_amounts(self):
        raw=self.parse()
        self.assertEqual((raw['supplier_name'],raw['buyer_name'],raw['invoice_number'],raw['invoice_date']),
                         ('Sharma Kirana Store','Gupta General Store','INV-4','2026-10-07'))
        self.assertEqual([(l['quantity'],l['rate'],l['taxable_amount']) for l in raw['lines']],
                         [('6','165.00','990.00'),('6','158.00','948.00'),('3','260.00','780.00'),('2','240.00','480.00')])
        self.assertEqual(raw['round_off'],'-0.30')
        self.assertEqual(raw['place_of_supply'],'08')
        self.assertEqual(raw['expected_taxes'],{'CGST':'111.15','SGST':'111.15'})
        self.assertTrue(any('GSTIN invalid' in w for w in raw['warnings']))
        line=raw['lines'][0]
        self.assertEqual(line['source_evidence']['inclusive_amount']['raw'],'1,039.50')
        self.assertEqual(line['source_evidence']['taxable_amount']['raw'],'990.00')
        checked=verify_and_match(raw,{'suppliers':[],'items':[]})
        self.assertEqual(checked['calculated_total'],'3420.00')
        self.assertFalse(any('total mismatch' in w.lower() for w in checked['warnings']))

    def test_other_supplier_and_date_not_hardcoded(self):
        self.change('Sharma Kirana Store','Independent Grocery Supplier')
        self.change('INV-4','TEST/ALT/17')
        self.change('07 Oct 2026','09 Nov 2026')
        raw=self.parse()
        self.assertEqual(raw['supplier_name'],'Independent Grocery Supplier')
        self.assertEqual(raw['invoice_number'],'TEST/ALT/17')
        self.assertEqual(raw['invoice_date'],'2026-11-09')

    def test_missing_or_changed_values_never_guessed(self):
        original=copy.deepcopy(self.source)
        for old,new,after in [('6PCS','unknown',318),('165.00','166.00',0),
                              ('1,039.50','1,040.50',0),('990.00','991.00',700),
                              ('24.75','25.75',0),('111.15','112.15',570),
                              ('-0.30','0.30',0),('\u20b93,420.00','\u20b93,421.00',0)]:
            with self.subTest(old=old,new=new):
                self.source=copy.deepcopy(original)
                # The first row and second row share quantity text; target first.
                candidates=[t for t in self.source['tokens'] if t['text']==old and t['box'][1]>=after]
                candidates[0]['text']=new
                with self.assertRaises(ValueError):self.parse()

    def test_missing_item_or_summary_row_blocks(self):
        original=copy.deepcopy(self.source)
        for removed in ['Assam Tea 500 g','(18%)','480.00']:
            with self.subTest(removed=removed):
                self.source=copy.deepcopy(original)
                self.source['tokens']=[t for t in self.source['tokens'] if t['text']!=removed]
                with self.assertRaises(ValueError):self.parse()

    def test_repeated_hsn_cannot_allocate_summary_silently(self):
        self.change('1512','0713',700)
        with self.assertRaises(ValueError):self.parse()


if __name__=='__main__':unittest.main()
