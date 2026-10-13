import asyncio
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value,tag
from scripts.day5_native_setup import ROOT,COMPANY
async def main():
 c=TallyConnector();rows=[v for v in await c.collection('Voucher',COMPANY,'2026-10-02') if value(v,'MASTERID')=='16'];assert len(rows)==1;v=rows[0];assert value(v,'REFERENCE')=='D5-FINAL-intra' and value(v,'NARRATION').startswith('Philixa action ')
 (ROOT/'duplicate-16-before-cancel.xml').write_text(E.tostring(v,encoding='unicode'))
 if value(v,'ISCANCELLED')=='Yes':return
 env=E.Element('ENVELOPE');tag(tag(env,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(env,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','Vouchers');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',COMPANY);data=tag(body,'REQUESTDATA');dest=tag(tag(data,'TALLYMESSAGE'),'VOUCHER',DATE='20261002',TAGNAME='Master ID',TAGVALUE='16',ACTION='Cancel',VCHTYPE='Purchase');tag(dest,'NARRATION','Cancelled duplicate created during Day 5 controlled acceptance repair.')
 reply=await c.post(E.tostring(env,encoding='unicode'));(ROOT/'duplicate-16-cancel-result.xml').write_text(E.tostring(reply,encoding='unicode'));print(E.tostring(reply,encoding='unicode'))
asyncio.run(main())
