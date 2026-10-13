import asyncio
from app.database.session import AsyncSessionLocal
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction
from app.services.tally_connector import TallyConnector,matches_action
async def main():
 async with AsyncSessionLocal() as db:
  d=await db.get(PurchaseDraft,'8b3e59204f6143b2c5be7dcecd182eba');a=await db.get(TallyAction,d.action_id);assert a.status=='needs_review' and a.result is None and a.payload['invoice_number']=='D5-APP-E2E'
  rows=[r for r in await TallyConnector().collection('Voucher',a.payload['company'],a.payload['date']) if matches_action(r,a.payload)];assert not rows
  # This exact acceptance attempt stopped in read-only validation, before submitting.
  a.result={'uncertain':False,'response':'Read-only validation rejected XML whitespace fingerprint; no accounting write was sent. Fresh preview required.'};await db.commit()
asyncio.run(main())
