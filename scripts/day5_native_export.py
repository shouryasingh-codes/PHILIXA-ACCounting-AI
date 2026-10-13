import asyncio
from pathlib import Path
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value
async def main():
 rows=await TallyConnector().collection('Voucher','Philixa Test','2026-10-02')
 ui=[r for r in rows if value(r,'REFERENCE')=='D5-UI-REFERENCE']
 assert len(ui)==1
 Path('data/day5-native/ui-reference-voucher.xml').write_text(E.tostring(ui[0],encoding='unicode'))
 print('UI_NATIVE',[(r.tag,r.text) for r in ui[0] if r.tag in ('DATE','REFERENCE','REFERENCEDATE','CMPGSTIN','PARTYGSTIN','GSTREGISTRATION','VOUCHERNUMBER','PLACEOFSUPPLY','STATENAME')])
 print('LINES',*[E.tostring(r,encoding='unicode') for r in ui[0].findall('ALLINVENTORYENTRIES.LIST')])
 print('LEDGERS',*[E.tostring(r,encoding='unicode') for r in ui[0].findall('LEDGERENTRIES.LIST')+ui[0].findall('ALLLEDGERENTRIES.LIST')])
asyncio.run(main())
