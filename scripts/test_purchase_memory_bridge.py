"""Protocol 9 isolation with real Redis, synthetic authorized actions only."""
import asyncio
import secrets
import unittest
from unittest.mock import patch,AsyncMock
from redis.asyncio import Redis
from app.core.config import get_settings
from app.models.tally import TallyDevice,TallySnapshot,TallyAction
from app.services import tally_bridge as bridge,tally_sync as sync,purchase_draft_service as drafts
from app.services.tally_connector import TallyError
from app.api.v1 import routes_tally_bridge as routes
import scripts.test_purchase_memory as memory_fixtures
CONTENT=memory_fixtures.CONTENT

async def redis_client():return Redis.from_url(get_settings().redis_url,decode_responses=True)

class BridgeV9(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=memory_fixtures.MemoryTests.asyncSetUp
    asyncTearDown=memory_fixtures.MemoryTests.asyncTearDown
    async def test_old_helpers_cannot_receive_guarded_jobs_new_helper_can(self):
        device=TallyDevice(id=secrets.token_hex(16),organization_id=self.org,credential_hash='synthetic-v9',revoked=False)
        self.db.add(device);self.company.device_id=device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version=device.credential_hash;await self.db.commit()
        row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content=CONTENT))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('synthetic offline'))):
            result=await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        action=await self.db.get(TallyAction,result['preview']['token']);await sync.confirm_queued(self.db,self.principal,action)
        cfg={**sync.config_data(self.cfg),'invoice_guard':action.preconditions['invoice_guard']}
        redis=await redis_client();pending=None
        with patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client):
            try:
                await routes.jobs(8,device,self.db)
                with self.assertRaises(TallyError):await bridge.request_job(device,'purchase_multi_validate',company=self.company.name,identity=self.company.identity,payload=action.payload,config=cfg,action_id=action.token)
                await routes.jobs(9,device,self.db)
                pending=asyncio.create_task(bridge.request_job(device,'purchase_multi_validate',company=self.company.name,identity=self.company.identity,payload=action.payload,config=cfg,action_id=action.token))
                wire=await redis.blpop('tally:queue:v9:'+device.id,timeout=2);self.assertIsNotNone(wire)
                await redis.lpush('tally:queue:v9:'+device.id,wire[1])
                self.assertIsNone((await routes.jobs(8,device,self.db))['job'])
                job=(await routes.jobs(9,device,self.db))['job'];self.assertEqual(job['config']['invoice_guard'],cfg['invoice_guard'])
                await bridge.consume_result(redis,device,job['id'],{'data':{'status':'ready'}})
                self.assertEqual((await pending)['status'],'ready')
            finally:
                if pending and not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                await redis.delete(*['tally:'+key+':'+device.id for key in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','v8online','v9online','queue:v9')]);await redis.aclose()

if __name__=='__main__':unittest.main()
