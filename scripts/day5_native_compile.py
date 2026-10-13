import asyncio,json,uuid
from pathlib import Path
from app.services.tally_connector import TallyConnector,name,value
from app.services.tally_gst_purchase import compile_purchase,gst_xml
from scripts.test_gst_purchase import content,gstin
from scripts.day5_native_setup import ROOT,COMPANY,PREFIX
from xml.etree import ElementTree as E
async def main():
 cat=await TallyConnector().catalog(COMPANY)
 cfg={'company':COMPANY,'test_company':True,'godown':'Main Location','purchase_ledger':PREFIX+'Purchase','sales_ledger':'Sales'}
 pr={'ledgers':{h:PREFIX+'Input '+h for h in ('CGST','SGST','IGST')},'rounding_ledger':PREFIX+'Round Off'}
 src=content(header='100',roundoff='-.30');src.update(party_name=PREFIX+'Supplier Local',entry_date='2026-10-02',invoice_number='D5-NATIVE-LOCAL-1')
 for row,label in zip(src['lines'],['Goods18','Goods5']):row['item_name']=PREFIX+label
 p=compile_purchase(cat,src,pr,cfg,str(uuid.uuid4()))
 (ROOT/'native-payload.json').write_text(json.dumps({'payload':p,'config':cfg},indent=2))
 for key,kind in [('companies','Company'),('tax_units','TaxUnit'),('items','StockItem'),('ledgers','Ledger')]:
  e=E.Element('FIXTURE');e.extend(cat[key]);(ROOT/('native-'+kind+'.xml')).write_text(E.tostring(e,encoding='unicode'))
 print('COMPILED',p['total'],p['tax_ledgers'])
asyncio.run(main())
