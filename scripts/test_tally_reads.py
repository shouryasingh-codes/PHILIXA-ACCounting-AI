"""Real PostgreSQL/Redis isolation checks. Accounting transports mocked; no writes."""
import asyncio
import json
import uuid
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from sqlalchemy import delete
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.tally import TallyReadCompany, TallyDevice
from app.services import tally_stock as stock, tally_bridge as bridge
from app.services import business_command_service as commands, portfolio_copilot_service as graph
from app.api.v1 import routes_tally_bridge as routes
from app.core.redis import get_redis_client, close_redis_pool

class Reads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.org=uuid.uuid4().hex; self.db=AsyncSessionLocal()
        self.owner=SimpleNamespace(organization_id=self.org,user_id='owner',role='owner')
        self.member=SimpleNamespace(organization_id=self.org,user_id='member',role='member')
        self.db.add(Organization(id=self.org,name='Read test',slug=self.org))
        await self.db.flush()
        self.rows=[]
        for index in range(2):
            row=TallyReadCompany(id=uuid.uuid4().hex,organization_id=self.org,device_id=None,identity=f'guid{index}',name=f'Company {index}',enabled=True,aliases=['शर्मा'] if index==0 else [],member_ids=['member'] if index==0 else [])
            self.db.add(row);self.rows.append(row)
        await self.db.commit()
    async def asyncTearDown(self):
        await self.db.rollback()
        await self.db.execute(delete(TallyReadCompany).where(TallyReadCompany.organization_id==self.org))
        await self.db.execute(delete(TallyDevice).where(TallyDevice.organization_id==self.org))
        await self.db.execute(delete(Organization).where(Organization.id==self.org));await self.db.commit();await self.db.close()
        await close_redis_pool()
    async def data(self,operation,**kw):
        return {'company':kw['company'],'identity':kw['identity'],'as_of':kw['as_of'],'items':[{'item':'Cement','unit':'bags' if kw['identity']=='guid0' else 'kg','quantity':'0' if kw['identity']=='guid0' else '-1.25','raw_quantity':'','limitation':None}]}
    async def test_graph_multi_company_no_rag_or_synthesis(self):
        request=commands.CommandRequest(intent='stock_read',fields={'item_name':'Cement'})
        with patch.object(stock,'local_operation',side_effect=self.data), patch.object(commands,'get_ai_provider',side_effect=AssertionError('No synthesis')), patch('app.services.ask_client_service.AskClientService.business_history',side_effect=AssertionError('No RAG')):
            events=[e async for e in graph.business_graph.astream({'request':request.model_dump(mode='json'),'operation':'command'},{'configurable':{'business_runtime':(self.owner,self.db)}},stream_mode='updates')]
        self.assertEqual([next(iter(e)) for e in events],['start','business_planner','stock_scope','tally_tool'])
        result=events[-1]['tally_tool']['result'];self.assertEqual(result['coverage'],{'requested':2,'checked':2,'partial':False,'live_checked':2,'saved_checked':0})
        self.assertEqual([r['items'][0]['quantity'] for r in result['stock_results']],['0','-1.25'])
        self.assertNotIn('total',result)
    async def test_scope_permissions_alias_and_forged_id(self):
        p=commands.ParsedCommand(intent='stock_read',item_name='Cement')
        self.assertEqual(len(await stock.resolve_scope(self.db,self.member,p)),1)
        p.company_id=self.rows[1].id
        self.assertEqual(await stock.resolve_scope(self.db,self.member,p),[])
        other=SimpleNamespace(organization_id='wrong',user_id='owner',role='owner')
        self.assertEqual(await stock.resolve_scope(self.db,other,p),[])
        p.company_id=None;p.company_query='शर्मा'
        self.assertEqual((await stock.resolve_scope(self.db,self.owner,p))[0].id,self.rows[0].id)
    async def test_partial_timeout_not_zero_and_ambiguity_preserves_scope(self):
        async def read(operation,**kw):
            if kw['identity']=='guid1':raise TimeoutError()
            data=await self.data(operation,**kw); data['items'].append({**data['items'][0],'item':'Cement Premium'});data['items'][0]['item']='Cement Regular';return data
        p=commands.ParsedCommand(intent='stock_read',item_name='Cement')
        with patch.object(stock,'local_operation',side_effect=read):result=await stock.read_stock(self.db,self.owner,p)
        self.assertTrue(result['coverage']['partial']);self.assertEqual(result['stock_results'][1]['items'],[])
        self.assertEqual(len(result['tally_choices']),2)
        choice=result['tally_choices'][0]['command'];self.assertEqual(choice['fields']['company_id'],self.rows[0].id)
    async def test_company_ambiguity_and_not_found(self):
        p=commands.ParsedCommand(intent='stock_read',company_query='Company',item_name='Cement')
        result=await stock.read_stock(self.db,self.owner,p);self.assertEqual(len(result['tally_choices']),2)
        p.company_query='Company 0'
        with patch.object(stock,'local_operation',AsyncMock(return_value={'company':'Company 0','identity':'guid0','as_of':stock.datetime.now(stock.ZoneInfo('Asia/Kolkata')).date().isoformat(),'items':[]})):
            result=await stock.read_stock(self.db,self.owner,p)
        self.assertEqual(result['stock_results'][0]['status'],'item_not_found')
    async def test_more_than_100_companies_no_truncation(self):
        for index in range(2,103):self.db.add(TallyReadCompany(id=uuid.uuid4().hex,organization_id=self.org,identity=f'guid{index}',name=f'Company {index}',enabled=True,aliases=[],member_ids=[]))
        await self.db.commit()
        with patch.object(stock,'local_operation',side_effect=self.data):
            result=await stock.read_stock(self.db,self.owner,commands.ParsedCommand(intent='stock_read',item_name='Cement'))
        self.assertEqual(result['coverage']['requested'],103)
    async def test_bridge_duplicate_wrong_device_expiry_and_oversize(self):
        redis=await get_redis_client(); jobid=uuid.uuid4().hex
        device=SimpleNamespace(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='version')
        key='tally:job:'+jobid
        job={'device_id':device.id,'organization_id':self.org,'credential_version':'version'}
        try:
            await redis.set(key,json.dumps(job),ex=30)
            wrong=SimpleNamespace(id='wrong',organization_id=self.org,credential_hash='version')
            with self.assertRaises(HTTPException) as e:await bridge.consume_result(redis,wrong,jobid,{'data':{}})
            self.assertEqual(e.exception.status_code,403)
            with self.assertRaises(HTTPException) as e:await bridge.consume_result(redis,device,jobid,{'data':{'payload':'x'*2_000_001}})
            self.assertEqual(e.exception.status_code,413)
            await bridge.consume_result(redis,device,jobid,{'data':{'items':[]}})
            with self.assertRaises(HTTPException) as e:await bridge.consume_result(redis,device,jobid,{'data':{}})
            self.assertEqual(e.exception.status_code,410)
        finally:await redis.delete(key,'tally:result:'+jobid);await redis.aclose()
    async def test_pair_single_use_replace_and_revoked(self):
        redis=await get_redis_client();code=uuid.uuid4().hex[:12].upper()
        try:await redis.set('tally:pair:'+code,bridge.digest('secret'),ex=600)
        finally:await redis.aclose()
        await routes.claim(routes.PairClaim(code=code),self.owner,self.db)
        with self.assertRaises(HTTPException) as e:await routes.claim(routes.PairClaim(code=code,replace=True),self.owner,self.db)
        self.assertEqual(e.exception.status_code,410);await self.db.rollback()
        await routes.revoke(self.owner,self.db)
        with self.assertRaises(HTTPException):await routes.device_auth('Bearer secret',self.db)
    async def test_revocation_during_live_read(self):
        async def read(operation,**kw):
            async with AsyncSessionLocal() as other:
                row=await other.get(TallyReadCompany,self.rows[0].id);row.enabled=False;await other.commit()
            return await self.data(operation,**kw)
        with patch.object(stock,'local_operation',side_effect=read):
            result=await stock.read_stock(self.db,self.owner,commands.ParsedCommand(intent='stock_read',company_query='Company 0',item_name='Cement'))
        self.assertEqual(result['stock_results'][0]['status'],'unavailable')
    async def test_bridge_roundtrip_and_offline(self):
        device=SimpleNamespace(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='version')
        with self.assertRaises(stock.TallyError):await bridge.request_job(device,'shell')
        with self.assertRaises(stock.TallyError):await bridge.request_job(device,'discover')
        redis=await get_redis_client()
        try:
            await redis.set('tally:online:'+device.id,'1',ex=45)
            pending=asyncio.create_task(bridge.request_job(device,'discover'))
            queued=await redis.blpop('tally:queue:'+device.id,timeout=2)
            self.assertIsNotNone(queued)
            job=json.loads(queued[1]);await bridge.consume_result(redis,device,job['id'],{'data':{'companies':[]}})
            self.assertEqual(await pending,{'companies':[]})
        finally:await redis.delete('tally:online:'+device.id,'tally:queue:'+device.id);await redis.aclose()
    async def test_new_unapproved_company_not_authorized(self):
        descriptors=[{'identity':r.identity,'name':r.name} for r in self.rows]+[{'identity':'new','name':'New GST company'}]
        with patch.object(routes,'discover',AsyncMock(return_value={'companies':descriptors})):
            await routes.approve(routes.CompanyApproval(mode='local',companies=[routes.Permission(identity=self.rows[0].identity,name=self.rows[0].name)]),self.owner,self.db)
        scope=await stock.resolve_scope(self.db,self.owner,commands.ParsedCommand(intent='stock_read'))
        self.assertEqual([c.identity for c in scope],['guid0'])
    async def test_malformed_wrong_identity_compound_and_many_items(self):
        p=commands.ParsedCommand(intent='stock_read',company_query='Company 0',item_name='Cement')
        async def read(operation,**kw):
            data=await self.data(operation,**kw)
            data['items']=[{**data['items'][0],'item':f'Other {i}'} for i in range(110)]+[{**data['items'][0],'quantity':None,'raw_quantity':'1 box = 12 pcs','limitation':'Compound/alternate unit: raw Tally quantity; no conversion or total.'}]
            return data
        with patch.object(stock,'local_operation',side_effect=read):result=await stock.read_stock(self.db,self.owner,p)
        self.assertEqual(result['stock_results'][0]['status'],'ok');self.assertIsNone(result['stock']['quantity'])
        async def malformed(operation,**kw):
            data=await self.data(operation,**kw);data['items'][0]['quantity']='NaN';return data
        with patch.object(stock,'local_operation',side_effect=malformed):result=await stock.read_stock(self.db,self.owner,p)
        self.assertEqual(result['stock_results'][0]['status'],'unavailable')
    async def test_expired_pairing_and_member_setup_denied(self):
        with self.assertRaises(HTTPException) as error:await routes.claim(routes.PairClaim(code='FFFFFFFFFFFF'),self.owner,self.db)
        self.assertEqual(error.exception.status_code,410);await self.db.rollback()
        with self.assertRaises(HTTPException) as error:await routes.claim(routes.PairClaim(code='FFFFFFFFFFFF'),self.member,self.db)
        self.assertEqual(error.exception.status_code,403)
    async def test_duplicate_names_with_different_guids_block_approval(self):
        descriptors=[{'identity':'one','name':'Same name'},{'identity':'two','name':'Same name'}]
        with patch.object(routes,'discover',AsyncMock(return_value={'companies':descriptors})):
            with self.assertRaises(HTTPException) as error:
                await routes.approve(routes.CompanyApproval(mode='local',companies=[routes.Permission(**descriptors[0])]),self.owner,self.db)
        self.assertEqual(error.exception.status_code,422)

if __name__=='__main__':unittest.main()
