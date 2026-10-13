import asyncio,copy
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value,name,tag
from scripts.day5_native_setup import ROOT,COMPANY,PREFIX,node
from scripts.test_gst_purchase import gstin
async def main():
 c=TallyConnector();nodes=[]
 tax=next(r for r in await c.collection('TaxUnit',COMPANY) if name(r)=='Haryana Registration')
 q=E.Element('TAXUNIT',**tax.attrib);q.set('ACTION','Alter');tag(q,'GUID',value(tax,'GUID'));tag(q,'NAME','Haryana Registration');tag(q,'GSTREGNUMBER',gstin('06'))
 for label,code,pan in [('Supplier Local','06','ABCPF1234G'),('Supplier Interstate','07','ABCPG1234H')]:
  old=next(r for r in await c.collection('Ledger',COMPANY) if name(r)==PREFIX+label);r=node('LEDGER',label,PARTYGSTIN=gstin(code,pan));r.set('ACTION','Alter');[r.append(copy.deepcopy(d)) for d in old.findall('LEDGSTREGDETAILS.LIST') if list(d)]
  for d in r.findall('LEDGSTREGDETAILS.LIST'):
   if d.find('GSTIN') is not None:d.find('GSTIN').text=gstin(code,pan)
  nodes.append(r)
 unit=E.Element('UNIT',NAME='bags',ACTION='Alter');tag(unit,'NAME','bags');tag(unit,'GSTREPUOM','BAG');nodes.append(unit)
 env=E.Element('ENVELOPE');tag(tag(env,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(env,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',COMPANY);data=tag(body,'REQUESTDATA')
 for r in nodes:tag(data,'TALLYMESSAGE').append(r)
 reply=await c.post(E.tostring(env,encoding='unicode'));print(E.tostring(reply,encoding='unicode'));(ROOT/'native-registration-adjustments.xml').write_text(E.tostring(reply,encoding='unicode'))
 print('dummyGSTIN',gstin('06'),gstin('06','ABCPF1234G'),gstin('07','ABCPG1234H'))
asyncio.run(main())
