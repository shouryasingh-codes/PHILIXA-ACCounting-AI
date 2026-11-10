"""Protocol 10 read-only isolation using synthetic companies and real Redis."""
import asyncio,secrets,unittest
from unittest.mock import patch
from app.models.tally import TallyDevice,TallySnapshot
from app.services import tally_bridge as bridge,tally_sync as sync
from app.services.tally_connector import TallyError
from app.services.tally_purchase_history import validate_query
from app.services.purchase_identity import exact_master,master_identity
from app.services.tally_sync_protocol import deserialize_catalog
from app.api.v1 import routes_tally_bridge as routes
from scripts.test_purchase_memory_bridge import redis_client
from scripts.test_purchase_memory import MemoryTests

class HistoryBridge(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=MemoryTests.asyncSetUp
    asyncTearDown=MemoryTests.asyncTearDown

    async def test_history_read_needs_no_posting_action_and_old_helper_cannot_consume(self):
        device=TallyDevice(id=secrets.token_hex(16),organization_id=self.org,credential_hash='synthetic-v10',revoked=False)
        self.db.add(device);self.company.device_id=device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id)
        snapshot.device_version=device.credential_hash
        cat=deserialize_catalog(snapshot.catalog)
        query=validate_query(dict(supplier='Supplier',supplier_id=master_identity(exact_master(cat,'supplier','Supplier')),
            items=[dict(name='Cement',id=master_identity(exact_master(cat,'item','Cement')))],from_date='2026-09-01',to_date='2026-10-02'))
        await self.db.commit()
        redis=await redis_client();pending=None
        with patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client):
            try:
                await routes.jobs(9,device,self.db)
                with self.assertRaises(TallyError):
                    await bridge.request_job(device,'purchase_history_read',company=self.company.name,identity=self.company.identity,payload=query)
                await routes.jobs(10,device,self.db)
                pending=asyncio.create_task(bridge.request_job(device,'purchase_history_read',company=self.company.name,identity=self.company.identity,payload=query))
                wire=await redis.blpop('tally:queue:v10:'+device.id,timeout=2)
                self.assertIsNotNone(wire)
                await redis.lpush('tally:queue:v10:'+device.id,wire[1])
                old_job=(await routes.jobs(9,device,self.db))['job']
                self.assertNotEqual((old_job or {}).get('operation'),'purchase_history_read')
                # A running stock worker may legitimately enqueue a legacy read for
                # this disposable company. Complete that read without live Tally.
                if old_job:await bridge.consume_result(redis,device,old_job['id'],{'error':'Synthetic test connector offline'})
                for _ in range(8):
                    job=(await routes.jobs(10,device,self.db))['job']
                    if job and job['operation']=='purchase_history_read':break
                    if job:await bridge.consume_result(redis,device,job['id'],{'error':'Synthetic test connector offline'})
                else:self.fail('Protocol 10 history request was not delivered')
                self.assertEqual(job['operation'],'purchase_history_read');self.assertNotIn('action_id',job)
                await bridge.consume_result(redis,device,job['id'],{'data':{'complete':True,'count':0}})
                self.assertTrue((await pending)['complete'])
            finally:
                if pending and not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                await redis.delete(*['tally:'+key+':'+device.id for key in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','v8online','v9online','v10online','queue:v10')])
                await redis.aclose()

if __name__=='__main__':unittest.main()
