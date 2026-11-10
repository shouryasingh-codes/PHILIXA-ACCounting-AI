import copy,json,unittest
from pathlib import Path
from app.services.local_invoice_ocr import parse_tokens
from app.services.invoice_extraction import verify_and_match
class LocalInvoice(unittest.TestCase):
 def test_wrapped_header_does_not_steal_gst_or_serial_column(self):
  for name,qty,rate,total in [('clean','7','80.00','660.80'),('tilted','6','100.00','708.00')]:
   with self.subTest(name=name):
    source=json.loads(Path(f'scripts/fixtures/release/accountant-{name}-tokens.json').read_text())
    raw=parse_tokens(**source);line=raw['lines'][0]
    self.assertEqual(len(raw['lines']),1);self.assertEqual(line['item_name'],'Philixa GST TEST Goods18')
    self.assertEqual((line['quantity'],line['rate'],line['gst_rate']),(qty,rate,'18'))
    self.assertEqual(raw['invoice_total'],total)
    self.assertEqual(line['source_evidence']['gst_rate']['raw'],'18')
 def test_wrapped_headers_do_not_hide_incomplete_actual_rows(self):
  source=json.loads(Path('scripts/fixtures/release/accountant-clean-tokens.json').read_text())
  source['tokens']=[t for t in source['tokens'] if t['text']!='7 bags']
  with self.assertRaises(ValueError):parse_tokens(**source)
 def setUp(self):
  self.raw=json.loads(Path('data/day5-native/local-structured-proof.json').read_text());self.tokens=self.raw['source_tokens']
 def test_geometry_and_reread_do_not_silently_change_unit(self):
  raw=parse_tokens(self.tokens,1684,1190);self.assertEqual([x['quantity'] for x in raw['lines']],['10','1']);self.assertEqual(raw['lines'][0]['unit'],'qags');self.assertEqual(raw['lines'][0]['source_evidence']['unit']['reread']['text'],'bags')
  result=verify_and_match(raw,{'suppliers':[raw['supplier_name']],'items':[{'name':'Philixa GST TEST Goods18','unit':'bags'},{'name':'Philixa GST TEST Goods5','unit':'bags'}]})
  self.assertEqual(result['calculated_total'],'1167.00');self.assertEqual(result['lines'][0]['unit'],'qags');self.assertEqual(result['line_evidence'][0]['unit']['suggested_value'],'bags');self.assertLess(result['line_evidence'][0]['unit']['confidence'],.8);self.assertGreater(result['line_evidence'][0]['quantity']['confidence'],.8)
 def test_missing_column_rejected(self):
  with self.assertRaises(ValueError):parse_tokens([x for x in self.tokens if x['text']!='Qty'],1684,1190)
 def test_incomplete_row_rejected(self):
  tokens=copy.deepcopy(self.tokens)
  for x in tokens:
   if x['text']=='10' and x['box'][1]>500:x['text']='unknown'
  with self.assertRaises(ValueError):parse_tokens(tokens,1684,1190)
 def test_gstin_checksum_and_total_mismatch_are_visible(self):
  tokens=copy.deepcopy(self.tokens)
  for x in tokens:
   if '06ABCPF1234G1ZC' in x['text']:x['text']=x['text'].replace('1ZC','1ZZ')
   if 'Grand Total:' in x['text']:x['text']='Grand Total: 999.00'
  raw=parse_tokens(tokens,1684,1190);self.assertTrue(any('GSTIN invalid' in w for w in raw['warnings']));result=verify_and_match(raw,{'suppliers':[],'items':[]});self.assertTrue(any('Invoice total mismatch' in w for w in result['warnings']))

 def test_second_layout_keeps_tax_columns_separate(self):
  x=json.loads(Path('data/day5-native/alternate-local-tokens.json').read_text());raw=parse_tokens(x['tokens'],x['width'],x['height']);result=verify_and_match(raw,{'suppliers':[],'items':[]});self.assertEqual(result['calculated_total'],'42461.00');self.assertEqual([r['quantity'] for r in raw['lines']],['50','200','100']);self.assertEqual(raw['buyer_name'],'M/s Sharma Construction Pvt. Ltd.')
 def test_tilted_missing_hsn_column_rejected_not_shifted(self):
  x=json.loads(Path('data/day5-native/tilted-local-proof.json').read_text())
  with self.assertRaises(ValueError):parse_tokens(x['source_tokens'],1744,1278)
