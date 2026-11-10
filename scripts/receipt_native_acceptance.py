"""Read-only by default. --execute-approved-test creates two labelled test vouchers.

Never use for real books. Never changes periods, dates, masters or protections.
Persisted identities and journals ensure rerunning never blindly resends a voucher.
"""
import argparse,asyncio,json,uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyConnector,TallyError,name,stock_quantity,company_identity
from app.services import tally_goods_receipt as receipt,tally_receipt_link as linked,tally_gst_purchase as gst
from app.services.purchase_identity import exact_master,invoice_guard

COMPANY='Philixa Test'
IDENTITY='bad1cd58-e5a3-43a7-8727-682b86b6f775'
PREFIX='Philixa GST TEST '
ROOT=Path('data/receipt-native')

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute-approved-test',action='store_true');args=parser.parse_args()
    # This acceptance runner is local Windows only, never the Docker hostname.
    with patch.dict('os.environ',{'PHILIXA_TALLY_HOST':'127.0.0.1'}):c=TallyConnector()
    cat=await c.catalog(COMPANY)
    companies=[r for r in cat['companies'] if name(r)==COMPANY]
    if len(companies)!=1 or company_identity(companies[0])!=IDENTITY:raise TallyError('Exact authorised test company identity unavailable; no writes.')
    cfg={'company':COMPANY,'godown':'Main Location','purchase_ledger':PREFIX+'Purchase','sales_ledger':'Sales','test_company':True}
    ROOT.mkdir(parents=True,exist_ok=True);planfile=ROOT/'plan.json'
    if planfile.exists():plan=json.loads(planfile.read_text())
    else:
        token=uuid.uuid4().hex
        source={'tax_treatment':'regular_domestic_goods','party_name':PREFIX+'Supplier Local',
            'place_of_supply':'06','entry_date':'2026-10-02','invoice_number':'PH-GRN-ACCEPT-'+token[:10],
            'invoice_discount':'0','round_off':'0','invoice_total':'223.00','expected_taxes':{'CGST':'11.50','SGST':'11.50'},
            'lines':[{'item_name':PREFIX+label,'quantity':'1','unit':'bags','rate':'100.00','gst_rate':rate,'hsn':'2523','taxable_amount':'100.00'} for label,rate in [('Goods18','18'),('Goods5','5')]]}
        from app.services.tally_connector import value
        party=exact_master(cat,'supplier',source['party_name'])
        source['supplier_gstin']=value(party,'PARTYGSTIN')
        profile={'ledgers':{h:PREFIX+'Input '+h for h in ('CGST','SGST','IGST')},'rounding_ledger':PREFIX+'Round Off'}
        invoice=gst.compile_purchase(cat,source,profile,cfg,str(uuid.uuid4()))
        p={'operation':'goods_receipt','company':COMPANY,'party':source['party_name'],'godown':cfg['godown'],'ledger':cfg['purchase_ledger'],
            'date':'2026-10-02','guid':str(uuid.uuid4()),'tracking':'PH-GRN-'+token,
            'items':[{'item':l['item_name'],'quantity':'1','unit':'bags','rate':'100.00'} for l in source['lines']],'master_fingerprint':''}
        p['master_fingerprint']=receipt.fingerprint(cat,p);receipt.validate(cat,p,cfg)
        plan={'company':COMPANY,'identity':IDENTITY,'receipt':p,'invoice':invoice,'config':cfg,'stages':{}}
        planfile.write_text(json.dumps(plan,indent=2))
    if plan['company']!=COMPANY or plan['identity']!=IDENTITY:raise TallyError('Saved acceptance scope mismatch.')
    p=plan['receipt'];invoice=plan['invoice']
    existing=await c.collection('Voucher',COMPANY,p['date'],from_date=p['date'])
    native=[v for v in existing if receipt.identity_matches(v,p)]
    if not native:receipt.validate(cat,p,cfg)
    elif len(native)!=1 or not receipt.verify(native[0],p):raise TallyError('Existing receipt requires review; no writes.')
    gst.validate(cat,invoice,cfg);linked.validate_link(invoice,p)
    if not args.execute_approved_test:
        print(json.dumps({'preflight':'passed','writes':False,'company':COMPANY,'date':p['date'],
            'test_items':[{'item':l['item'],'quantity':l['quantity']} for l in p['items']],
            'invoice_total':invoice['total'],'planned_vouchers':['Receipt Note','linked GST Purchase'],'plan':str(planfile)},indent=2));return
    async def stocks():
        rows=await c.collection('StockItem',COMPANY,datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat())
        return {l['item']:str(stock_quantity(next(r for r in rows if name(r)==l['item']),l['unit'])) for l in p['items']}
    async def save(stage,result):
        plan['stages'][stage]=result;planfile.write_text(json.dumps(plan,indent=2));print(stage,json.dumps(result),flush=True)
    if 'before' not in plan['stages']:await save('before',await stocks())
    with patch.object(receipt,'RECEIPT_CODEC_CERTIFIED',True):
        result=await receipt.execute('goods_receipt_post',c,COMPANY,IDENTITY,p,cfg,ROOT/'journal.sqlite3')
        await save('receipt',result)
        if result.get('status')!='verified':raise TallyError('Receipt not verified. Stop; reconcile same action, do not create a new one.')
        if 'after_receipt' not in plan['stages']:await save('after_receipt',await stocks())
        for l in p['items']:
            if Decimal(plan['stages']['after_receipt'][l['item']])-Decimal(plan['stages']['before'][l['item']])!=Decimal(l['quantity']):raise TallyError('Receipt stock delta mismatch. No invoice posted.')
        config={**cfg,'receipt_link':p,'invoice_guard':invoice_guard(COMPANY+':'+IDENTITY,cat,invoice['source'])}
        result=await linked.execute('purchase_gst_post',c,COMPANY,IDENTITY,invoice,config,ROOT/'journal.sqlite3')
        await save('invoice',result)
        if result.get('status')!='verified':raise TallyError('Invoice/tracking not verified. Do not resend with a new action.')
    after=await stocks();await save('after_invoice',after)
    if after!=plan['stages']['after_receipt']:raise TallyError('Linked invoice changed stock again; acceptance FAILED.')
    vouchers=await c.collection('Voucher',COMPANY,invoice['date'],from_date=p['date'])
    for label,payload,matcher in [('receipt',p,receipt.identity_matches),('invoice',invoice,__import__('app.services.tally_connector',fromlist=['matches_action']).matches_action)]:
        found=[v for v in vouchers if matcher(v,payload)]
        if len(found)!=1:raise TallyError('Duplicate/missing native action during final proof.')
        (ROOT/(label+'-native.xml')).write_text(ET.tostring(found[0],encoding='unicode'))
    await save('accepted',{'receipt_stock_delta':'one bag per test item','invoice_stock_delta':'0','duplicate_count_per_action':1,'native_verified':True})

if __name__=='__main__':asyncio.run(main())
