import asyncio,copy
from xml.etree import ElementTree as E
from scripts.day5_native_setup import ROOT,COMPANY,PREFIX,node
from app.services.tally_connector import TallyConnector,tag,name,value
async def main():
 c=TallyConnector();rows=await c.collection('StockItem',COMPANY)
 template=next(r for r in rows if name(r)==PREFIX+'Goods18')
 detail=next(r for r in template.findall('GSTDETAILS.LIST') if value(r,'APPLICABLEFROM')=='20261002')
 nodes=[]
 for label,rate in [('Goods5',5)]:
  r=node('STOCKITEM',label);r.set('ACTION','Alter')
  d=copy.deepcopy(detail)
  for t in d.findall('.//RATEDETAILS.LIST'):
   head=value(t,'GSTRATEDUTYHEAD');t.find('GSTRATE').text=str(rate if head=='IGST' else rate/2 if head in ('CGST','SGST/UTGST') else 0)
  r.append(d)
  for h in template.findall('HSNDETAILS.LIST'):r.append(copy.deepcopy(h))
  nodes.append(r)
 r=node('LEDGER','Input SGST',GSTDUTYHEAD='SGST/UTGST');r.set('ACTION','Alter');nodes.append(r)
 env=E.Element('ENVELOPE');tag(tag(env,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(env,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',COMPANY);data=tag(body,'REQUESTDATA')
 for r in nodes:tag(data,'TALLYMESSAGE').append(r)
 xml=E.tostring(env,encoding='unicode').replace('<STATENAME> Any</STATENAME>','<STATENAME>&#4; Any</STATENAME>')
 reply=await c.post(xml);(ROOT/'native-master-adjustments-response.xml').write_text(E.tostring(reply,encoding='unicode'));print(E.tostring(reply,encoding='unicode'))
asyncio.run(main())
