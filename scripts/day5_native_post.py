import asyncio,json,os
from pathlib import Path
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value,matches_action
from app.services.tally_gst_purchase import execute,gst_xml,verify
async def main():
 root=Path('data/day5-native');obj=json.loads((root/'native-payload.json').read_text());p=obj['payload'];cfg=obj['config'];c=TallyConnector()
 os.environ['PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED']='1'
 (root/'local-request.xml').write_text(gst_xml(p))
 print(await execute('purchase_gst_post',c,p['company'],'day5-native',p,cfg,str(root/'journal.sqlite')))
 rows=[v for v in await c.collection('Voucher',p['company'],p['date']) if matches_action(v,p)]
 for v in rows:
  (root/'local-voucher.xml').write_text(E.tostring(v,encoding='unicode'))
  print('RESULT',verify(v,p),'top',[(k,value(v,k)) for k in ('DATE','REFERENCE','REFERENCEDATE','CMPGSTIN','PARTYGSTIN','VOUCHERNUMBER')]);print('LEDGERS',[(value(r,'LEDGERNAME'),value(r,'AMOUNT')) for r in v.findall('ALLLEDGERENTRIES.LIST')])
asyncio.run(main())
