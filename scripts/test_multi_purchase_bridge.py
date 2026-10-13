"""Actual Redis queues and scoped helper polling; no Tally transport or provider."""
import asyncio
import json
import uuid
import unittest
from unittest.mock import patch,AsyncMock
from redis.asyncio import Redis
from app.core.config import get_settings
from app.models.tally import TallyDevice
from app.services import tally_bridge as bridge,tally_sync as sync,purchase_draft_service as drafts
from app.services.tally_connector import TallyError
from app.api.v1 import routes_tally_bridge as routes
import scripts.test_tally_sync as fixtures


async def redis_client():return Redis.from_url(get_settings().redis_url,decode_responses=True)


class BridgeV7(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DurableTests.asyncSetUp
    asyncTearDown=fixtures.DurableTests.asyncTearDown

    async def test_v6_cannot_consume_v7_jobs_and_v7_requires_approved_action(self):
        self.device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='version',revoked=False)
        self.db.add(self.device);self.company.device_id=self.device.id;await self.db.commit()
        # Snapshot was captured by the former local endpoint; rebind a synthetic equivalent.
        from app.models.tally import TallySnapshot
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version='version';await self.db.commit()
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','entry_date':'2026-10-01','lines':[
                {'item_name':'Cement','quantity':'1','unit':'bags','rate':'350'}]}))
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            preview=await drafts.preview_draft(self.db,self.principal,draft['id'],drafts.DraftPreview(revision=0))
        from app.models.tally import TallyAction
        action=await self.db.get(TallyAction,preview['preview']['token']);await sync.confirm_queued(self.db,self.principal,action)
        redis=await redis_client();pending=None
        with patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client):
            try:
                await routes.jobs(6,self.device,self.db)
                with self.assertRaises(TallyError):
                    await bridge.request_job(self.device,'purchase_multi_validate',company=self.company.name,identity=self.company.identity,
                        payload=action.payload,config=sync.config_data(self.cfg),action_id=action.token)
                await routes.jobs(7,self.device,self.db)
                pending=asyncio.create_task(bridge.request_job(self.device,'purchase_multi_validate',company=self.company.name,
                    identity=self.company.identity,payload=action.payload,config=sync.config_data(self.cfg),action_id=action.token))
                wire=await redis.blpop('tally:queue:v7:'+self.device.id,timeout=2)
                self.assertIsNotNone(wire);await redis.lpush('tally:queue:v7:'+self.device.id,wire[1])
                self.assertIsNone((await routes.jobs(6,self.device,self.db))['job'])
                result=await routes.jobs(7,self.device,self.db)
                self.assertEqual(result['job']['operation'],'purchase_multi_validate')
                self.assertEqual(result['job']['payload'],action.payload)
                await bridge.consume_result(redis,self.device,result['job']['id'],{'data':{'status':'ready'}})
                self.assertEqual((await pending)['status'],'ready')
            finally:
                if pending and not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                await redis.delete(*['tally:'+key+':'+self.device.id for key in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','queue:v7')]);await redis.aclose()


if __name__=='__main__':unittest.main()
