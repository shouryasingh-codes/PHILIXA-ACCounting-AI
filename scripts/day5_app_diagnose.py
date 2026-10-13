import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction,TallyConnection,TallyReadCompany,TallySnapshot
from app.services.tally_connector import TallyConnector,TallyError
from app.services import tally_gst_purchase as gst,tally_sync as sync
async def main():
 async with AsyncSessionLocal() as db:
  d=await db.get(PurchaseDraft,'8b3e59204f6143b2c5be7dcecd182eba');a=await db.get(TallyAction,d.action_id);c=await db.get(TallyConnection,d.organization_id);co=await db.get(TallyReadCompany,d.company_id)
  try:
   live=await TallyConnector().catalog(co.name);snap=await db.get(TallySnapshot,co.id);from app.services.tally_sync_protocol import deserialize_catalog
   saved=deserialize_catalog(snap.catalog)
   for kind in ('companies','items','ledgers','units','tax_units','groups','stock_groups','godowns'):
    names={gst.name(x):x for x in live.get(kind,[])}
    for old in saved.get(kind,[]):
     new=names.get(gst.name(old))
     if new is not None:
      def flat(row):return {(x.tag,i):(x.text or '').strip() for i,x in enumerate(row.iter())}
      one,two=flat(old),flat(new);diff=[k[0] for k in set(one)|set(two) if one.get(k)!=two.get(k)]
      if diff:print(kind,gst.name(old),sorted(set(diff)))
   expected=gst.compile_purchase(live,a.payload['source'],a.payload['tax_profile'],sync.config_data(c),a.payload['guid'])
   for old,new in zip(a.payload['items'],expected['items']):new['stock_before']=old['stock_before']
   print('DIFFERING',[(k,'changed') for k in expected if expected[k]!=a.payload.get(k)])
  except TallyError as e:print('VALIDATION',str(e))
asyncio.run(main())
