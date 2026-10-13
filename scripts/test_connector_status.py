"""Status truthfulness and authenticated heartbeat regression checks."""
import json
import unittest
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from app.services.tally_diagnostics import connection_state,live_key
from app.api.v1 import routes_tally_bridge as routes
from scripts import test_tally_reads as fixtures
from app.models.tally import TallyDevice
from app.services.tally_bridge import digest
from app.core.redis import get_redis_client

class StateTests(unittest.TestCase):
    def test_current_packaged_connector_is_accepted(self):
        d={'connector_version':'3.5.1','startup_configured':True,'tally_state':'available'}
        self.assertEqual(connection_state(True,True,d,[{'reachable':True,'stock_read_verified':True}]),'live_available')

    def test_online_is_not_live(self):
        self.assertEqual(connection_state(True,True,None,[]),'update_required')
        d={'connector_version':'3.1.0','startup_configured':True,'tally_state':'closed'}
        self.assertEqual(connection_state(True,True,d,[]),'tally_closed')
        d['tally_state']='available'
        self.assertEqual(connection_state(True,True,d,[]),'company_approval_needed')
        c=[{'reachable':True,'stock_read_verified':False}]
        self.assertEqual(connection_state(True,True,d,c),'checking')
        c[0]['stock_read_verified']=True
        self.assertEqual(connection_state(True,True,d,c),'live_available')
        c.append({'reachable':False,'stock_read_verified':True})
        self.assertEqual(connection_state(True,True,d,c),'company_unavailable')
    def test_offline_or_startup_failed_cannot_claim_success(self):
        self.assertEqual(connection_state(True,False,{},[]),'connector_offline')
        self.assertEqual(connection_state(False,False,None,[]),'setup_needed')
        self.assertEqual(connection_state(True,True,{'connector_version':'3.1.0','startup_configured':False},[]),'setup_needed')

class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture=fixtures.Reads();await self.fixture.asyncSetUp()
        self.db=self.fixture.db;self.owner=self.fixture.owner;self.rows=self.fixture.rows
        self.device=TallyDevice(id=self.fixture.org,organization_id=self.fixture.org,credential_hash=digest('synthetic-'+self.fixture.org),revoked=False)
        self.db.add(self.device)
        for row in self.rows:row.device_id=self.device.id
        await self.db.commit()
    async def asyncTearDown(self):
        redis=await get_redis_client()
        try:
            await redis.delete('tally:online:'+self.device.id,'tally:diagnostics:'+self.device.id,'tally:protocol:'+self.device.id,
                               *(live_key(self.device,r.identity) for r in self.rows))
        finally:await redis.aclose()
        await self.fixture.asyncTearDown()
    def body(self,state='available'):
        return routes.ConnectorHealth(connector_version='3.1.0',startup_configured=True,tally_state=state,
            companies=[routes.CompanyHealth(identity=r.identity,reachable=state=='available') for r in self.rows])
    async def online(self):
        redis=await get_redis_client()
        try:await redis.set('tally:online:'+self.device.id,'1',ex=45)
        finally:await redis.aclose()
    async def test_heartbeat_then_real_read_required_and_closed_invalidates(self):
        await self.online();await routes.heartbeat(self.body(),self.device,self.db)
        self.assertEqual((await routes.helper_status(self.owner,self.db))['connection_state'],'checking')
        async def stock(*args,**kwargs):return {'company':kwargs['company'],'identity':kwargs['identity'],'items':[]}
        with patch.object(routes,'transport',side_effect=stock):
            status=await routes.check_setup(self.owner,self.db)
        self.assertTrue(status['setup_complete'])
        await routes.heartbeat(self.body('closed'),self.device,self.db)
        status=await routes.helper_status(self.owner,self.db)
        self.assertEqual(status['connection_state'],'tally_closed');self.assertFalse(status['setup_complete'])
        self.assertTrue(all(not c['stock_read_verified'] for c in status['company_health']))
    async def test_unknown_company_rejected_and_member_scope_private(self):
        body=self.body();body.companies.append(routes.CompanyHealth(identity='forged',reachable=True))
        with self.assertRaises(HTTPException) as error:await routes.heartbeat(body,self.device,self.db)
        self.assertEqual(error.exception.status_code,403)
        await self.online();await routes.heartbeat(self.body(),self.device,self.db)
        status=await routes.helper_status(self.fixture.member,self.db)
        self.assertEqual(len(status['companies']),1);self.assertEqual(len(status['company_health']),1)
        self.assertNotIn('_credential_version',status['diagnostics'])
    async def test_credential_change_ignores_old_heartbeat(self):
        await self.online();await routes.heartbeat(self.body(),self.device,self.db)
        self.device.credential_hash=digest('replaced');await self.db.commit()
        self.assertEqual((await routes.helper_status(self.owner,self.db))['connection_state'],'update_required')
    async def test_failed_stock_read_never_marks_setup_complete(self):
        from app.services.tally_connector import TallyError
        await self.online();await routes.heartbeat(self.body(),self.device,self.db)
        with patch.object(routes,'transport',new=AsyncMock(side_effect=TallyError('unavailable'))):
            with self.assertRaises(HTTPException):await routes.check_setup(self.owner,self.db)
        self.assertFalse((await routes.helper_status(self.owner,self.db))['setup_complete'])

if __name__=='__main__':unittest.main()
