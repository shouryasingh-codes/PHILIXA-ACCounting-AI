import asyncio,json,os,uuid,copy
from pathlib import Path
from xml.etree import ElementTree as E
from app.services.tally_connector import TallyConnector,value,name,matches_action,TallyError
from app.services.tally_gst_purchase import compile_purchase,execute,gst_xml,verify
from scripts.test_gst_purchase import content,gstin
from scripts.day5_native_setup import ROOT,COMPANY,PREFIX
async def main():
 c=TallyConnector();cfg={'company':COMPANY,'test_company':True,'godown':'Main Location','purchase_ledger':PREFIX+'Purchase','sales_ledger':'Sales'};pr={'ledgers':{h:PREFIX+'Input '+h for h in ('CGST','SGST','IGST')},'rounding_ledger':PREFIX+'Round Off'}
 os.environ['PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED']='1';reports=[]
 for label,inter,header,roundoff in [('intra',False,'0','0'),('inter',True,'0','0'),('mixed-discount-round',False,'100','-.30'),('inter-round-up',True,'100','.70')]:
  file=ROOT/('final-'+label+'-proof.json')
  if file.exists():obj=json.loads(file.read_text());p=obj['payload']
  else:
   cat=await c.catalog(COMPANY);src=content(inter,header,roundoff);src.update(party_name=PREFIX+('Supplier Interstate' if inter else 'Supplier Local'),supplier_gstin=gstin('07','ABCPG1234H') if inter else gstin('06','ABCPF1234G'),entry_date='2026-10-02',invoice_number='D5-FINAL-'+label)
   for row,item in zip(src['lines'],['Goods18','Goods5']):row['item_name']=PREFIX+item
   p=compile_purchase(cat,src,pr,cfg,str(uuid.uuid4()));file.write_text(json.dumps({'payload':p,'config':cfg,'result':None},indent=2))
  result=await execute('purchase_gst_post',c,COMPANY,'day5-acceptance',p,cfg,str(ROOT/'acceptance-journal.sqlite'))
  rows=[v for v in await c.collection('Voucher',COMPANY,p['date']) if matches_action(v,p)]
  if len(rows)==1:(ROOT/('final-'+label+'-voucher.xml')).write_text(E.tostring(rows[0],encoding='unicode'))
  file.write_text(json.dumps({'payload':p,'config':cfg,'result':result},indent=2));print(label,result,flush=True)
  assert result['status']=='verified',result
  again=await execute('purchase_gst_post',c,COMPANY,'day5-acceptance',p,cfg,str(ROOT/'acceptance-journal.sqlite'));assert again['status']=='verified'
  rows2=[v for v in await c.collection('Voucher',COMPANY,p['date']) if matches_action(v,p)];assert len(rows2)==1
  for mutate in ('total','tax','quantity','reference'):
   v=copy.deepcopy(rows2[0])
   if mutate=='total':next(r for r in v.findall('ALLLEDGERENTRIES.LIST') if value(r,'LEDGERNAME')==p['party']).find('AMOUNT').text='1.00'
   elif mutate=='tax':next(r for r in v.findall('ALLLEDGERENTRIES.LIST') if value(r,'LEDGERNAME')==p['tax_ledgers'][0]['ledger']).find('AMOUNT').text='-1.00'
   elif mutate=='quantity':v.find('ALLINVENTORYENTRIES.LIST/BILLEDQTY').text='999 bags'
   else:v.find('REFERENCE').text='wrong'
   assert not verify(v,p),mutate
  reports.append({'case':label,'voucher':result['voucher_number'],'total':p['total'],'tax_ledgers':p['tax_ledgers'],'duplicate_count':len(rows2),'mutated_fields_rejected':4})
 cat=await c.catalog(COMPANY)
 for key,kind in [('companies','Company'),('tax_units','TaxUnit'),('items','StockItem'),('ledgers','Ledger'),('units','Unit'),('groups','Group'),('stock_groups','StockGroup'),('godowns','Godown')]:
  e=E.Element('FIXTURE');e.extend(cat[key]);(ROOT/('accepted-'+kind+'.xml')).write_text(E.tostring(e,encoding='unicode'))
 (ROOT/'acceptance-report.json').write_text(json.dumps(reports,indent=2));print('ACCEPTED',len(reports),'DUPLICATE_SAFE',flush=True)
asyncio.run(main())
