import asyncio,json,os,uuid
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value,matches_action
from app.services.tally_gst_purchase import compile_purchase,execute,verify
from scripts.day5_native_setup import ROOT,COMPANY
async def main():
 c=TallyConnector();obj=json.loads((ROOT/'final-intra-proof.json').read_text());src=obj['payload']['source'];src['invoice_number']='D5-CODEC-FINAL'
 f=ROOT/'codec-final-proof.json'
 if f.exists():p=json.loads(f.read_text())['payload']
 else:p=compile_purchase(await c.catalog(COMPANY),src,obj['payload']['tax_profile'],obj['config'],str(uuid.uuid4()));f.write_text(json.dumps({'payload':p,'config':obj['config']},indent=2))
 os.environ['PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED']='1';result=await execute('purchase_gst_post',c,COMPANY,'day5-final-codec',p,obj['config'],str(ROOT/'acceptance-journal.sqlite'));assert result['status']=='verified',result
 rows=[v for v in await c.collection('Voucher',COMPANY,p['date']) if matches_action(v,p)];assert len(rows)==1 and verify(rows[0],p);(ROOT/'codec-final-voucher.xml').write_text(E.tostring(rows[0],encoding='unicode'))
 print('FINAL_CODEC_VERIFIED',result['voucher_number'],'duplicates',len(rows))
asyncio.run(main())
