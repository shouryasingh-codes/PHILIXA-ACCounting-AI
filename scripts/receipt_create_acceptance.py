"""One additional dummy receipt to prove automatic creation. Read-only by default."""
import argparse,asyncio,copy,json,os,uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from unittest.mock import patch
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyConnector,name,stock_quantity,company_identity,TallyError
from app.services import tally_goods_receipt as receipt

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute-approved-test',action='store_true');args=parser.parse_args()
    root=Path('data/receipt-native');source=json.loads((root/'plan.json').read_text())
    with patch.dict(os.environ,{'PHILIXA_TALLY_HOST':'127.0.0.1'}):c=TallyConnector()
    cat=await c.catalog(source['company'])
    if source['company']!='Philixa Test' or source['identity']!='bad1cd58-e5a3-43a7-8727-682b86b6f775' or len([v for v in cat['companies'] if name(v)==source['company'] and company_identity(v)==source['identity']])!=1:raise TallyError('Exact authorised test company not loaded.')
    path=root/'automatic-create-plan.json'
    if path.exists():plan=json.loads(path.read_text())
    else:
        p=copy.deepcopy(source['receipt']);p.update(guid=str(uuid.uuid4()),tracking='PH-GRN-AUTO-'+uuid.uuid4().hex)
        p['master_fingerprint']=receipt.fingerprint(cat,p)
        plan={'company':source['company'],'identity':source['identity'],'config':source['config'],'receipt':p,'stages':{}}
        path.write_text(json.dumps(plan,indent=2))
    p=plan['receipt'];receipt.validate(cat,p,plan['config'])
    if not args.execute_approved_test:
        print(json.dumps({'preflight':'passed','writes':False,'planned_vouchers':1,'voucher_type':'Receipt Note','date':p['date'],'items':p['items'],'valuation_total':'200.00','gst_credit':False},indent=2));return
    async def stocks():
        rows=await c.collection('StockItem',plan['company'],datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat())
        return {l['item']:str(stock_quantity(next(r for r in rows if name(r)==l['item']),l['unit'])) for l in p['items']}
    if 'before' not in plan['stages']:plan['stages']['before']=await stocks();path.write_text(json.dumps(plan,indent=2))
    with patch.object(receipt,'RECEIPT_CODEC_CERTIFIED',True):
        result=await receipt.execute('goods_receipt_post',c,plan['company'],plan['identity'],p,plan['config'],root/'journal.sqlite3')
    plan['stages']['receipt']=result;path.write_text(json.dumps(plan,indent=2));print('receipt',json.dumps(result),flush=True)
    if result.get('status')!='verified':raise TallyError('Native automatic receipt not verified. Stop; no new identity or blind resend.')
    after=await stocks();plan['stages']['after']=after
    if any(Decimal(after[l['item']])-Decimal(plan['stages']['before'][l['item']])!=Decimal(l['quantity']) for l in p['items']):raise TallyError('Native receipt stock delta mismatch.')
    again=await receipt.execute('goods_receipt_reconcile',c,plan['company'],plan['identity'],p,plan['config'],root/'journal.sqlite3')
    if again.get('status')!='verified' or await stocks()!=after:raise TallyError('Native reconciliation changed stock or failed.')
    vouchers=await c.collection('Voucher',plan['company'],p['date'],from_date=p['date']);found=[v for v in vouchers if receipt.identity_matches(v,p)]
    if len(found)!=1:raise TallyError('Native action count mismatch.')
    (root/'automatic-receipt-native.xml').write_text(ET.tostring(found[0],encoding='unicode'))
    plan['stages']['accepted']={'automatic_creation':True,'native_verified':True,'stock_delta_per_item':'1','duplicate_count':1};path.write_text(json.dumps(plan,indent=2));print(json.dumps(plan['stages']['accepted']))

if __name__=='__main__':asyncio.run(main())
