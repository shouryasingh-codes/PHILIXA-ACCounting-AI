"""Explicitly authorized local practice setup; no portals or real registrations."""
import asyncio,json
from pathlib import Path
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,name,value,tag
from scripts.test_gst_purchase import gstin
ROOT=Path('data/day5-native');COMPANY='Philixa Test';PREFIX='Philixa GST TEST '
def node(kind,label,**fields):
 r=E.Element(kind,NAME=PREFIX+label,ACTION='Create')
 tag(r,'NAME',PREFIX+label)
 tag(tag(tag(r,'LANGUAGENAME.LIST'),'NAME.LIST',TYPE='String'),'NAME',PREFIX+label)
 for k,v in fields.items():tag(r,k,v)
 return r

def tax_detail(r,rate):
 d=tag(r,'GSTDETAILS.LIST');tag(d,'APPLICABLEFROM','20260401');tag(d,'TAXABILITY','Taxable');tag(d,'SUPPLYTYPE','Goods');tag(d,'ISREVERSECHARGEAPPLICABLE','No');tag(d,'GSTINELIGIBLEITC','No');tag(d,'HSNCODE','2523')
 st=tag(d,'STATEWISEDETAILS.LIST');tag(st,'STATENAME','Any')
 for h,v in [('CGST',rate/2),('SGST',rate/2),('IGST',rate)]:
  t=tag(st,'RATEDETAILS.LIST');tag(t,'GSTRATEDUTYHEAD',h);tag(t,'GSTRATE',v);tag(t,'GSTRATEVALUATIONTYPE','Based on Value')
 hs=tag(r,'HSNDETAILS.LIST');tag(hs,'APPLICABLEFROM','20260401');tag(hs,'HSNCODE','2523')
 return r
async def main():
 c=TallyConnector();companies=await c.collection('Company');co=[r for r in companies if name(r)==COMPANY]
 if len(co)!=1 or value(co[0],'ISGSTON')!='Yes':raise RuntimeError('Authorized GST practice company unavailable')
 nodes=[]
 for label,state,code in [('Supplier Local','Haryana','06'),('Supplier Interstate','Delhi','07')]:
  r=node('LEDGER',label,PARENT='Sundry Creditors',ISBILLWISEON='Yes',ISCOSTCENTRESON='No',COUNTRYNAME='India',STATENAME=state,GSTREGISTRATIONTYPE='Regular',PARTYGSTIN=gstin(code),GSTAPPLICABLE='Applicable')
  d=tag(r,'LEDGSTREGDETAILS.LIST');tag(d,'APPLICABLEFROM','20260401');tag(d,'GSTREGISTRATIONTYPE','Regular');tag(d,'GSTIN',gstin(code));tag(d,'STATE',state);tag(d,'COUNTRY','India');nodes.append(r)
 nodes.append(node('LEDGER','Purchase',PARENT='Purchase Accounts',ISCOSTCENTRESON='No',GSTAPPLICABLE='Applicable',GSTTYPEOFSUPPLY='Goods'))
 for h in ('CGST','SGST','IGST'):
  nodes.append(node('LEDGER','Input '+h,PARENT='Duties & Taxes',TAXTYPE='GST',GSTDUTYHEAD=h,ISCOSTCENTRESON='No',RATEOFINVOICETAX='0'))
 nodes.append(node('LEDGER','Round Off',PARENT='Indirect Expenses',GSTAPPLICABLE='Not Applicable',ISCOSTCENTRESON='No',ROUNDTYPE='Normal Rounding',ROUNDINGLIMIT='1'))
 for label,rate in [('Goods18',18),('Goods5',5)]:
  nodes.append(tax_detail(node('STOCKITEM',label,PARENT='&#4; Primary',BASEUNITS='bags',ISBATCHWISEON='No',GSTAPPLICABLE='Applicable',GSTTYPEOFSUPPLY='Goods'),rate))
 for kind in ('LEDGER','STOCKITEM'):
  existing={name(r) for r in await c.collection('Ledger' if kind=='LEDGER' else 'StockItem',COMPANY)}
  missing=[r for r in nodes if r.tag==kind and name(r) not in existing]
  if missing:
   env=E.Element('ENVELOPE');tag(tag(env,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(env,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',COMPANY);rd=tag(body,'REQUESTDATA')
   for r in missing:tag(rd,'TALLYMESSAGE').append(r)
   xml=E.tostring(env,encoding='unicode').replace('&amp;#4;','&#4;');(ROOT/('setup-'+kind+'.xml')).write_text(xml)
   reply=await c.post(xml);(ROOT/('setup-response-'+kind+'.xml')).write_text(E.tostring(reply,encoding='unicode'))
   print('CREATED',kind,reply.findtext('.//CREATED'),'ERRORS',reply.findtext('.//ERRORS'))
 for kind in ('Company','TaxUnit','Ledger','StockItem','StockGroup','Group','Godown','Unit'):
  rows=await c.collection(kind,COMPANY)
  if kind=='Company':rows=[r for r in rows if name(r)==COMPANY]
  out=E.Element('FIXTURE');out.extend(rows);(ROOT/('native-'+kind+'.xml')).write_text(E.tostring(out,encoding='unicode'))
 print('TEST_MASTERS',len(nodes),'portal_calls',0)
if __name__=='__main__':asyncio.run(main())
