import copy,json,unittest
from pathlib import Path
from xml.etree import ElementTree as E
from app.services import tally_gst_purchase as gst
from app.services.tally_connector import value,TallyError
ROOT=Path('data/day5-native')
class NativeExports(unittest.TestCase):
 def test_real_native_exports_and_mutations(self):
  for label in ('intra','inter','mixed-discount-round','inter-round-up','codec-final'):
   prefix='final-'+label if label!='codec-final' else label
   p=json.loads((ROOT/(prefix+'-proof.json')).read_text())['payload'];v=E.parse(ROOT/(prefix+'-voucher.xml')).getroot()
   self.assertTrue(gst.verify(v,p),label)
   for path,text in [('REFERENCE','wrong'),('PLACEOFSUPPLY','Delhi'),('ALLINVENTORYENTRIES.LIST/GSTITEMUQC','OTH-OTHERS'),('ALLINVENTORYENTRIES.LIST/RATEDETAILS.LIST/GSTRATE','99')]:
    bad=copy.deepcopy(v);bad.find(path).text=text;self.assertFalse(gst.verify(bad,p),(label,path))
 def test_snapshot_formatting_is_not_a_master_change(self):
  from app.services.tally_sync_protocol import serialize_catalog,deserialize_catalog
  obj=json.loads((ROOT/'final-intra-proof.json').read_text());p=obj['payload'];keys={'companies':'Company','tax_units':'TaxUnit','items':'StockItem','ledgers':'Ledger','units':'Unit','groups':'Group','stock_groups':'StockGroup','godowns':'Godown'}
  cat={k:list(E.parse(ROOT/('accepted-'+kind+'.xml')).getroot()) for k,kind in keys.items()};cat.update(non_gst=False,cost_centres_enabled=False)
  self.assertEqual(gst.fingerprint(cat,p),gst.fingerprint(deserialize_catalog(serialize_catalog(cat)),p))
  before=gst.fingerprint(cat,p);cat['companies'][0].find('ISGSTON').text='No';self.assertNotEqual(before,gst.fingerprint(cat,p))
 def test_native_master_calculation_and_missing_mapping_block(self):
  keys={'companies':'Company','tax_units':'TaxUnit','items':'StockItem','ledgers':'Ledger','units':'Unit','groups':'Group','stock_groups':'StockGroup','godowns':'Godown'}
  cat={k:list(E.parse(ROOT/('accepted-'+kind+'.xml')).getroot()) for k,kind in keys.items()};cat.update(non_gst=False,cost_centres_enabled=False)
  obj=json.loads((ROOT/'final-intra-proof.json').read_text());p=obj['payload'];result=gst.compile_purchase(cat,p['source'],p['tax_profile'],obj['config'],p['guid']);self.assertEqual(result['total'],p['total'])
  for unit in cat['units']:
   for child in list(unit.findall('REPORTINGUQCDETAILS.LIST')):unit.remove(child)
   unit.find('GSTREPUOM').text='BAG'
  with self.assertRaises(TallyError):gst.compile_purchase(cat,p['source'],p['tax_profile'],obj['config'],p['guid'])
if __name__=='__main__':unittest.main()
