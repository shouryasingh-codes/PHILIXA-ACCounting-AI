"""Customer ledger safety and durable workflow checks. No real accounting writes."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree as ET
from sqlalchemy import select, delete
from fastapi import HTTPException
from app.services import tally_customer_codec as codec, tally_customer as service, tally_sync as sync, tally_sync_protocol as protocol
from app.services import business_command_service as commands, portfolio_copilot_service as graph
from app.services.tally_connector import TallyError, TallyRejected, value, name
from app.models.tally import TallyAction, TallyCustomerLink
from app.models.client import Client
from scripts.test_tally import node
import scripts.test_tally_sync as fixtures

class CustomerProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'journal.sqlite3';self.addCleanup(self.tmp.cleanup)
        self.p={'operation':'customer_ledger_create','company':'Pilot Test','name':'Rahul','parent':codec.GROUP,'guid':str(uuid.uuid4()),
            'mode':'create','target_guid':'','fingerprint':'','email':None,'phone':None,'client_id':None,'client_version':''}
        self.cfg={'company':'Pilot Test','test_company':True};self.rows=[];self.posts=0
        async def collection(kind,*args,**kwargs):
            if kind=='Company':return [node('COMPANY','Pilot Test',GUID='identity',ISGSTON='No')]
            return self.rows
        async def post(xml):
            self.posts+=1;self.rows.append(ET.fromstring(xml).find('.//LEDGER'));return ET.Element('REPLY')
        self.connector=SimpleNamespace(collection=collection,post=post)
    async def run_op(self,operation):
        return await codec.execute_customer(operation,self.connector,'Pilot Test','identity',self.p,self.cfg,self.path)
    async def test_create_verify_duplicate_delivery(self):
        self.assertEqual((await self.run_op('customer_ledger_validate'))['status'],'ready');self.assertEqual(self.posts,0)
        first=await self.run_op('customer_ledger_post');self.assertEqual(first['status'],'verified')
        self.assertEqual(first['ledger_name'],'Rahul');self.assertEqual(first['ledger_parent'],'Sundry Debtors')
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'verified');self.assertEqual(self.posts,1)
    async def test_no_reimport_when_timeout_before_import(self):
        async def lost(xml):self.posts+=1;raise TallyError('timeout')
        self.connector.post=lost
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'verification_pending')
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'verification_pending');self.assertEqual(self.posts,1)
    async def test_timeout_after_import_reconciles_without_resend(self):
        original=self.connector.post
        async def lost(xml):await original(xml);raise TallyError('timeout')
        self.connector.post=lost;await self.run_op('customer_ledger_post')
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'verified');self.assertEqual(self.posts,1)
    async def test_tally_assigned_guid_requires_preserved_marker(self):
        await self.run_op('customer_ledger_post');self.rows[0].find('GUID').text='native-guid'
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['ledger_guid'],'native-guid')
        self.rows[0].find('NOTES').text='unrelated'
        self.rows[0].remove(self.rows[0].find('LANGUAGENAME.LIST'))
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'needs_review')
    async def test_native_guid_assignment_uses_durable_import_receipt(self):
        async def native(xml):
            self.posts+=1;row=ET.fromstring(xml).find('.//LEDGER')
            row.find('GUID').text='tally-native';row.remove(row.find('NOTES'));ET.SubElement(row,'PHILIXAMASTERID').text='210'
            row.remove(row.find('LANGUAGENAME.LIST'))
            self.rows.append(row);return ET.fromstring('<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><LASTMID>210</LASTMID></RESPONSE>')
        self.connector.post=native
        reply=await self.run_op('customer_ledger_post');self.assertEqual(reply['status'],'verified');self.assertEqual(reply['verification_source'],'import_receipt')
        self.assertEqual(reply['ledger_guid'],'tally-native')
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'verified');self.assertEqual(self.posts,1)
        self.rows[0].find('PHILIXAMASTERID').text='211'
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'needs_review')
    async def test_same_name_external_ledger_blocks_import(self):
        self.rows=[node('LEDGER','Rahul',GUID='foreign',PARENT=codec.GROUP)]
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'needs_review');self.assertEqual(self.posts,0)
    async def test_changed_group_or_contact_not_verified(self):
        self.p['email']='rahul@example.invalid';await self.run_op('customer_ledger_post')
        self.rows[0].find('EMAIL').text='changed@example.invalid'
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'needs_review')
        self.rows[0].find('PARENT').text='Sundry Creditors'
        self.assertEqual((await self.run_op('customer_ledger_reconcile'))['status'],'needs_review');self.assertEqual(self.posts,1)
    async def test_link_only_no_import_and_stale_fingerprint(self):
        row=node('LEDGER','Rahul',GUID='native',PARENT=codec.GROUP,EMAIL='existing@example.invalid');self.rows=[row]
        self.p.update(mode='link',target_guid='native',fingerprint=codec.ledger_fingerprint(row))
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'verified');self.assertEqual(self.posts,0)
        row.find('EMAIL').text='changed@example.invalid'
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'needs_review')
    async def test_xml_escaping_and_company_envelope(self):
        self.p['name']='Rahul & Sons <Delhi>';xml=ET.fromstring(codec.ledger_xml(self.p))
        self.assertEqual(xml.findtext('.//SVCURRENTCOMPANY'),'Pilot Test');self.assertEqual(xml.find('.//LEDGER').get('ACTION'),'Create')
        self.assertEqual(xml.findtext('.//LEDGER/NAME'),self.p['name']);self.assertNotIn('VOUCHER',ET.tostring(xml,encoding='unicode'))
    async def test_invalid_payload_extra_fields_and_wrong_company(self):
        self.p['xml']='injected'
        with self.assertRaises(TallyError):await self.run_op('customer_ledger_post')
        self.p.pop('xml');self.p['company']='Other'
        with self.assertRaises(TallyError):await self.run_op('customer_ledger_post')
        self.assertEqual(self.posts,0)
    async def test_protocol_checks_gst_and_company_identity(self):
        with patch.object(protocol,'TallyConnector',return_value=self.connector):
            reply=await protocol.execute_sync('customer_ledger_validate',company='Pilot Test',identity='identity',payload=self.p,config=self.cfg,journal_path=self.path)
            self.assertEqual(reply['status'],'ready')
            with self.assertRaises(TallyError):await protocol.execute_sync('customer_ledger_post',company='Pilot Test',identity='wrong',payload=self.p,config=self.cfg,journal_path=self.path)
    async def test_explicit_rejection_and_unknown_outcome_no_resend(self):
        async def reject(xml):self.posts+=1;raise TallyRejected('Create rejected')
        self.connector.post=reject
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'failed')
        self.assertEqual((await self.run_op('customer_ledger_post'))['status'],'verification_pending');self.assertEqual(self.posts,1)

class CustomerDurable(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DurableTests.asyncSetUp
    async def asyncTearDown(self):
        await self.db.rollback()
        await self.db.execute(delete(TallyCustomerLink).where(TallyCustomerLink.organization_id==self.org))
        await self.db.commit()
        await fixtures.DurableTests.asyncTearDown(self)
    async def preview(self,**fields):
        parsed=commands.ParsedCommand(intent='customer_create',client_name='Rahul',**fields)
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            result=await service.preview_customer(self.db,self.principal,parsed)
        self.assertIn('preview',result,result);return await self.db.get(TallyAction,result['preview']['token'])
    def verified_snapshot(self,a):
        snapshot=copy.deepcopy(self.snapshot)
        row=ET.fromstring(codec.ledger_xml(a.payload)).find('.//LEDGER')
        row.find('GUID').text='native'
        snapshot['catalog']['ledgers'].append(ET.tostring(row,encoding='unicode'))
        return snapshot
    async def test_graph_customer_uses_tally_preview_no_early_client(self):
        parsed=commands.ParsedCommand(intent='customer_create',client_name='Rahul')
        with patch.object(commands,'plan_command',AsyncMock(return_value=parsed)),patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            reply=await graph.run_business_graph(commands.CommandRequest(text='Rahul customer add karo'),self.principal,self.db)
        self.assertEqual(reply['preview']['title'],'Customer + Tally ledger')
        self.assertIsNone(await self.db.scalar(select(Client.id).where(Client.organization_id==self.org)))
    async def test_confirmation_and_duplicate_preview_preserve_one_action(self):
        a=await self.preview();b=await self.preview();self.assertEqual(a.token,b.token)
        await sync.confirm_queued(self.db,self.principal,a);self.assertEqual(a.status,'queued');self.assertEqual(a.approved_arguments,a.payload)
        await sync.confirm_queued(self.db,self.principal,a);self.assertEqual(a.status,'queued')
        self.assertIsNone(await self.db.scalar(select(Client.id).where(Client.organization_id==self.org)))
        await sync.confirm_queued(self.db,self.principal,a,approve=False);self.assertEqual(a.status,'cancelled')
    async def test_verified_ledger_creates_client_and_link_atomically(self):
        a=await self.preview();await sync.confirm_queued(self.db,self.principal,a)
        replies=[{'status':'ready'},{'status':'verified','ledger_guid':'native','ledger_name':'Rahul','ledger_parent':codec.GROUP}]
        with patch.object(sync,'operation',AsyncMock(side_effect=replies)),patch.object(sync,'capture_snapshot',AsyncMock(return_value=self.verified_snapshot(a))):
            await sync.process_action(self.db,a,self.company)
        self.assertEqual(a.status,'verified');self.assertIn('linked',sync.action_result(a)['response'])
        link=await self.db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.company_id==self.company.id))
        self.assertEqual(link.ledger_guid,'native');self.assertEqual((await self.db.get(Client,link.client_id)).name,'Rahul')
    async def test_existing_rahul_reused_not_duplicated(self):
        from app.repositories.client_repository import ClientRepository
        client=await ClientRepository().create(self.db,self.principal,{'name':'Rahul'});await self.db.commit()
        a=await self.preview();self.assertEqual(a.payload['client_id'],client.id)
        await sync.confirm_queued(self.db,self.principal,a)
        with patch.object(sync,'operation',AsyncMock(return_value={'status':'verified','ledger_guid':'native','ledger_name':'Rahul','ledger_parent':codec.GROUP})),patch.object(sync,'capture_snapshot',AsyncMock(return_value=self.verified_snapshot(a))):
            await sync.process_action(self.db,a,self.company)
        clients=list((await self.db.scalars(select(Client).where(Client.organization_id==self.org))).all());self.assertEqual(len(clients),1)
    async def test_changed_existing_customer_blocks_post(self):
        from app.repositories.client_repository import ClientRepository
        c=await ClientRepository().create(self.db,self.principal,{'name':'Rahul'});await self.db.commit()
        a=await self.preview();await sync.confirm_queued(self.db,self.principal,a)
        c.email='changed@example.invalid';await self.db.commit()
        with patch.object(sync,'operation',AsyncMock()) as op:await sync.process_action(self.db,a,self.company)
        op.assert_not_awaited();self.assertEqual(a.status,'needs_review')
    async def test_snapshot_failure_keeps_unverified_without_crm_save(self):
        a=await self.preview();await sync.confirm_queued(self.db,self.principal,a)
        reply={'status':'verified','ledger_guid':'native','ledger_name':'Rahul','ledger_parent':codec.GROUP}
        with patch.object(sync,'operation',AsyncMock(side_effect=[{'status':'ready'},reply])),patch.object(sync,'capture_snapshot',AsyncMock(side_effect=TallyError('snapshot unavailable'))):
            with self.assertRaises(TallyError):await sync.process_action(self.db,a,self.company)
        self.assertEqual(a.status,'submitting');self.assertIsNone(await self.db.scalar(select(Client.id).where(Client.organization_id==self.org)))
        with patch.object(sync,'operation',AsyncMock(return_value=reply)) as op,patch.object(sync,'capture_snapshot',AsyncMock(return_value=self.verified_snapshot(a))):
            await sync.process_action(self.db,a,self.company)
        self.assertEqual(op.call_args.args[2],'customer_ledger_reconcile');self.assertEqual(a.status,'verified')
    async def test_wrong_session_revoked_member_and_forged_payload(self):
        a=await self.preview();other=SimpleNamespace(**vars(self.principal));other.session_id='other'
        with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,other,a)
        await sync.confirm_queued(self.db,self.principal,a);a.payload={**a.payload,'name':'Forged'};await self.db.commit()
        with patch.object(sync,'operation',AsyncMock()) as op:await sync.process_action(self.db,a,self.company)
        op.assert_not_awaited();self.assertEqual(a.status,'needs_review')
    async def test_wrong_group_is_not_converted_to_customer(self):
        from app.models.tally import TallySnapshot
        snapshot=await self.db.get(TallySnapshot,self.company.id);data=copy.deepcopy(snapshot.catalog)
        data['ledgers'].append(ET.tostring(node('LEDGER','Rahul',GUID='native',PARENT='Sundry Creditors'),encoding='unicode'))
        snapshot.catalog=data;await self.db.commit()
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            reply=await service.preview_customer(self.db,self.principal,commands.ParsedCommand(intent='customer_create',client_name='Rahul'))
        self.assertNotIn('preview',reply);self.assertIn('silently',reply['response'])
    async def test_old_helper_cannot_consume_customer_jobs_and_v6_checks_approval(self):
        import json
        from app.models.tally import TallyDevice,TallySnapshot
        from app.core.redis import get_redis_client,close_redis_pool
        from app.api.v1.routes_tally_bridge import jobs,helper_status
        device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='customer-test-secret',revoked=False)
        self.db.add(device);self.company.device_id=device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version=device.credential_hash;await self.db.commit()
        a=await self.preview();await sync.confirm_queued(self.db,self.principal,a)
        redis=await get_redis_client();job_id=uuid.uuid4().hex
        keys=['tally:online:','tally:protocol:','tally:v2online:','tally:v3online:','tally:v4online:','tally:v5online:','tally:v6online:','tally:queue:v6:']
        try:
            job={'id':job_id,'device_id':device.id,'organization_id':self.org,'credential_version':device.credential_hash,
                'operation':'customer_ledger_validate','company':self.company.name,'identity':self.company.identity,
                'payload':a.payload,'config':sync.config_data(self.cfg),'action_id':a.token}
            await redis.set('tally:job:'+job_id,json.dumps(job),ex=30);await redis.rpush('tally:queue:v6:'+device.id,json.dumps(job))
            self.assertIsNone((await jobs(5,device,self.db))['job'])
            self.assertEqual((await jobs(6,device,self.db))['job']['operation'],'customer_ledger_validate')
            status=await helper_status(self.principal,self.db);self.assertTrue(status['customer_ledger_capable']);self.assertFalse(status['helper_update_required'])
            job['payload']={**a.payload,'name':'Forged'};await redis.set('tally:job:'+job_id,json.dumps(job),ex=30);await redis.rpush('tally:queue:v6:'+device.id,json.dumps(job))
            with self.assertRaises(HTTPException):await jobs(6,device,self.db)
        finally:
            await redis.delete(*[k+device.id for k in keys],'tally:job:'+job_id);await redis.aclose();await close_redis_pool()


if __name__=='__main__':unittest.main()
