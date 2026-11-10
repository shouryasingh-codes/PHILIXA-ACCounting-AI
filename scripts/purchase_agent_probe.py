"""Bounded read-only acceptance probes. Never creates or posts Tally vouchers."""
import asyncio,json,sys
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

async def main():
    if '--provider' in sys.argv:
        from app.services.purchase_message import extract
        updates=await extract('Sharma Traders se 50 Cement bags liye, rate 350 tha, bill INV-AGENT-TEST date 02-10-2026')
        fields={v['path']:v['value'] for v in updates}
        expected={'party_name':'Sharma Traders','lines.0.item_name':'Cement','lines.0.quantity':'50','lines.0.rate':'350',
                  'invoice_number':'INV-AGENT-TEST','entry_date':'2026-10-02'}
        assert all(fields.get(k)==v for k,v in expected.items()),fields
        print(json.dumps({'provider_probe':'passed','explicit_fields':len(updates),'test_data':'synthetic only','posting':False}))
        return
    from app.services.tally_connector import TallyConnector,name
    from app.services.tally_purchase_history import normalise_vouchers
    from app.services.purchase_identity import exact_master,master_identity
    connector=TallyConnector()
    companies=await connector.collection('Company')
    target=[v for v in companies if name(v)=='Philixa Test']
    if len(target)!=1:
        print(json.dumps({'native_probe':'unavailable','reason':'Philixa Test company not loaded','posting':False}));return
    cat=await connector.catalog('Philixa Test')
    supplier=exact_master(cat,'supplier','Sharma Traders');item=exact_master(cat,'item','Cement')
    ceiling=datetime.now(ZoneInfo('Asia/Kolkata')).date()
    query=dict(supplier='Sharma Traders',supplier_id=master_identity(supplier),items=[{'name':'Cement','id':master_identity(item)}],
               from_date=(ceiling-timedelta(days=179)).isoformat(),to_date=ceiling.isoformat())
    vouchers=await connector.collection('Voucher','Philixa Test',query['to_date'],from_date=query['from_date'],supplier_query=query['supplier'])
    records,issues=normalise_vouchers(vouchers,cat,query)
    print(json.dumps({'native_probe':'passed' if not issues else 'needs_review','matching_vouchers':len(vouchers),
        'evidenced_lines':len(records),'issues':issues,'latest_rate':records[0]['rate'] if records else None,
        'posting':False},indent=2))

if __name__=='__main__':asyncio.run(main())
