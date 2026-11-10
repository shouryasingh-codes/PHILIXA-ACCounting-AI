"""Scoped server linkage tests with synthetic native-verification results."""
import asyncio,copy,secrets,unittest
from unittest.mock import patch,AsyncMock
from sqlalchemy import select
from fastapi import HTTPException
from app.models.tally import TallyAction
from app.models.purchase_draft import PurchaseDraft
from app.services import purchase_draft_service as drafts,goods_receipt_service as receipts,goods_receipt_link_service as links,tally_sync as sync,purchase_tax_service as tax
import scripts.test_gst_purchase as fixture

class Linkage(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.Durable.asyncSetUp
    asyncTearDown=fixture.Durable.asyncTearDown
    async def prepare(self):
        c=fixture.content()
        source=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':c['party_name'],'lines':c['lines']}))
        row=await self.db.get(PurchaseDraft,source['id'])
        await receipts.begin(self.db,self.principal,row)
        data=copy.deepcopy(receipts.receipt(row));data.update(received_on=c['entry_date'],rate_basis='tax_exclusive')
        await receipts.persist(self.db,self.principal,row,data,'receipt_updated')
        from app.services.purchase_memory_service import catalog_for
        preview=await receipts.preview(self.db,self.principal,row,await catalog_for(self.db,self.company))
        self.assertFalse(preview['preview']['can_confirm'])
        action=await self.db.get(TallyAction,preview['preview']['token'])
        # This fabricated result is isolated test data, not native acceptance.
        action.status='verified';action.result={'voucher_number':'synthetic-only'};await self.db.commit()
        invoice=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content=c))
        return row,action,invoice
    async def test_explicit_link_required_and_preview_retains_guard(self):
        original,native,invoice=await self.prepare()
        with self.assertRaises(HTTPException) as e:
            await drafts.preview_draft(self.db,self.principal,invoice['id'],drafts.DraftPreview(revision=0))
        self.assertEqual(e.exception.status_code,409)
        result=await links.link(self.db,self.principal,invoice['id'],links.LinkRequest(revision=0,receipt_draft_id=original.id,receipt_revision=original.revision))
        await tax.save_profile(self.db,self.principal,self.company.id,tax.TaxProfileSave(revision=0,**fixture.profile()))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=fixture.TallyError('offline'))):
            preview=await drafts.preview_draft(self.db,self.principal,invoice['id'],drafts.DraftPreview(revision=result['revision']))
        self.assertFalse(preview['preview']['can_confirm'])
        action=await self.db.get(TallyAction,preview['preview']['token'])
        await links.guard(self.db,action)
        self.assertEqual(action.preconditions['receipt_link']['tracking'],native.payload['tracking'])
        self.assertIn('TRACKINGNUMBER',action.xml_payload)
        from app.services import tally_goods_receipt as codec
        with patch.object(codec,'RECEIPT_CODEC_CERTIFIED',False):
            with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(action.status,'preview')
    async def test_stale_receipt_and_partial_quantities_rejected(self):
        original,native,invoice=await self.prepare()
        with self.assertRaises(HTTPException):
            await links.link(self.db,self.principal,invoice['id'],links.LinkRequest(revision=0,receipt_draft_id=original.id,receipt_revision=original.revision-1))
        row=await self.db.get(PurchaseDraft,invoice['id']);c=copy.deepcopy(row.content);c['lines'][0]['quantity']='1';row.content=c;await self.db.commit()
        with self.assertRaises(HTTPException) as e:
            await links.link(self.db,self.principal,invoice['id'],links.LinkRequest(revision=0,receipt_draft_id=original.id,receipt_revision=original.revision))
        self.assertEqual(e.exception.status_code,422)
    async def test_old_helper_cannot_receive_new_receipt_operations(self):
        from app.models.tally import TallyDevice
        from app.services import tally_bridge as bridge,tally_goods_receipt as codec
        from app.api.v1 import routes_tally_bridge as routes
        from scripts.test_purchase_memory_bridge import redis_client
        original,action,_=await self.prepare()
        device=TallyDevice(id=secrets.token_hex(16),organization_id=self.org,credential_hash='synthetic-v11',revoked=False)
        self.db.add(device);self.company.device_id=device.id
        action.device_version=device.credential_hash;action.approved_arguments=copy.deepcopy(action.payload)
        await self.db.commit()
        for _ in range(20):
            worker_lock=sync.company_lock(self.company.id)
            if await worker_lock.__aenter__():break
            await worker_lock.__aexit__(None,None,None);await asyncio.sleep(.1)
        else:self.fail('Disposable test device still being read by background worker')
        self.addAsyncCleanup(worker_lock.__aexit__,None,None,None)
        action.status='queued';await self.db.commit()
        redis=await redis_client();pending=None
        with patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client),patch.object(codec,'RECEIPT_CODEC_CERTIFIED',True):
            try:
                await routes.jobs(10,device,self.db)
                with self.assertRaises(fixture.TallyError):
                    await bridge.request_job(device,'goods_receipt_validate',company=self.company.name,identity=self.company.identity,payload=action.payload,config=sync.config_data(self.cfg),action_id=action.token)
                await routes.jobs(11,device,self.db)
                pending=asyncio.create_task(bridge.request_job(device,'goods_receipt_validate',company=self.company.name,identity=self.company.identity,payload=action.payload,config=sync.config_data(self.cfg),action_id=action.token))
                wire=await redis.blpop('tally:queue:v11:'+device.id,timeout=2);self.assertIsNotNone(wire)
                await redis.lpush('tally:queue:v11:'+device.id,wire[1])
                old=(await routes.jobs(10,device,self.db))['job']
                self.assertNotEqual((old or {}).get('operation'),'goods_receipt_validate')
                if old:await bridge.consume_result(redis,device,old['id'],{'error':'Synthetic test only'})
                for _ in range(8):
                    job=(await routes.jobs(11,device,self.db))['job']
                    if job and job['operation']=='goods_receipt_validate':break
                    if job:await bridge.consume_result(redis,device,job['id'],{'error':'Synthetic test only'})
                else:self.fail('Receipt job not delivered to v11 helper')
                await bridge.consume_result(redis,device,job['id'],{'data':{'status':'ready'}})
                self.assertEqual((await pending)['status'],'ready')
            finally:
                if pending and not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                await redis.delete(*['tally:'+key+':'+device.id for key in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','v8online','v9online','v10online','v11online','queue:v11')]);await redis.aclose()

if __name__=='__main__':unittest.main()
