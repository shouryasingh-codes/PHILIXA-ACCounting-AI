import asyncio,json
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,tag,value,matches_action,parse_xml
from app.services.tally_gst_purchase import gst_xml,verify,compile_purchase
from scripts.day5_native_setup import ROOT,COMPANY
async def main():
 c=TallyConnector()
 for label in ('intra','inter','mixed-discount-round','inter-round-up'):
  obj=json.loads((ROOT/('final-'+label+'-proof.json')).read_text());p=compile_purchase(await c.catalog(COMPANY),obj['payload']['source'],obj['payload']['tax_profile'],obj['config'],obj['payload']['guid']);obj['payload']=p;(ROOT/('final-'+label+'-proof.json')).write_text(json.dumps(obj,indent=2))
  rows=[v for v in await c.collection('Voucher',COMPANY,p['date']) if matches_action(v,p) and value(v,'ISCANCELLED')!='Yes'];assert len(rows)==1
  # Exact same dummy voucher/financial amounts; fix only the native cess enum.
  v=rows[0];env=parse_xml(gst_xml(p).encode());dest=env.find('.//VOUCHER');dest.attrib.clear();dest.attrib.update(DATE=p['date'].replace('-',''),TAGNAME='Master ID',TAGVALUE=value(v,'MASTERID'),ACTION='Alter',VCHTYPE='Purchase',OBJVIEW='Invoice Voucher View');tag(dest,'VOUCHERNUMBER',value(v,'VOUCHERNUMBER'));dest.find('GUID').text=value(v,'GUID');tag(dest,'MASTERID',value(v,'MASTERID'))
  xml=E.tostring(env,encoding='unicode').replace('<GSTRATEVALUATIONTYPE> Not Applicable</GSTRATEVALUATIONTYPE>','<GSTRATEVALUATIONTYPE>&#4; Not Applicable</GSTRATEVALUATIONTYPE>')
  reply=await c.post(xml);(ROOT/('cess-fix-'+label+'-response.xml')).write_text(E.tostring(reply,encoding='unicode'));print(E.tostring(reply,encoding='unicode'),flush=True);assert reply.findtext('.//ALTERED')=='1';assert reply.findtext('.//CREATED')=='0';assert reply.findtext('.//EXCEPTIONS')=='0'
  rows=[v for v in await c.collection('Voucher',COMPANY,p['date']) if matches_action(v,p) and value(v,'ISCANCELLED')!='Yes'];assert len(rows)==1 and verify(rows[0],p)
  (ROOT/('final-'+label+'-voucher.xml')).write_text(E.tostring(rows[0],encoding='unicode'));print(label,'same voucher corrected',flush=True)
asyncio.run(main())
