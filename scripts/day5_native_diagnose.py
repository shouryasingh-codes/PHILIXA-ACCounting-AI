import asyncio,json
from app.services.tally_connector import TallyConnector,value
async def main():
 rows=await TallyConnector().collection('Voucher','Philixa Test','2026-10-02')
 print([{'no':value(v,'VOUCHERNUMBER'),'ref':value(v,'REFERENCE'),'guid':value(v,'GUID'),'master':value(v,'MASTERID'),'key':value(v,'VOUCHERKEY')} for v in rows if value(v,'REFERENCE').startswith('D5-FINAL')])
asyncio.run(main())
