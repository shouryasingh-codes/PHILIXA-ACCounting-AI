"""Day 8 DB boundaries and real digital-PDF evidence. Native writes are mocked."""
import copy
import secrets
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from sqlalchemy import select
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.models.tally import TallyAction,TallySnapshot
from app.models.organization_membership import OrganizationMembership
from app.models.purchase_automation import PurchaseAutomationReservation as Reservation,PurchaseAutomationDecision as Decision
from app.services import purchase_automation_service as auto,purchase_draft_service as drafts,purchase_memory_service as memory,tally_sync as sync
from app.services import bill_document_service as docs,invoice_extraction as extraction
from app.services.tally_connector import TallyError
import scripts.test_tally_sync as fixtures
from scripts.purchase_fixture_support import master_ids

CONTENT=dict(party_name='Supplier',invoice_number='D8-1',entry_date='2026-10-02',invoice_total='200',lines=[dict(item_name='Cement',quantity='2',unit='bags',rate='100')])

class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        await master_ids(self.db,self.company.id)
        self.cid=self.company.id
        for target,name,value in ((memory,'live_check',AsyncMock()),(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),(auto,'source_gate',AsyncMock(side_effect=self.proof))):
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def proof(self,db,row,company):return dict(source_sha256='verified-dummy-sha',content_hash=auto.digest(row.content),amount=row.content['invoice_total'])
    async def policy(self,mode='auto',**changes):
        current=await auto.policy_view(self.db,self.principal,self.cid)
        return await auto.save_policy(self.db,self.principal,self.cid,auto.PolicySave(revision=current['revision'],**{**dict(mode=mode,suppliers=['Supplier'],items=['Cement'],per_invoice='500',daily_amount='500',daily_count=2),**changes}))
    async def create(self,ref='D8-1'):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.cid,content={**CONTENT,'invoice_number':ref}))
    async def queued(self):
        await self.policy();row=await self.create();decision=await auto.evaluate(self.db,self.principal,row['id'])
        self.assertEqual(decision['decision'],'auto_post',decision)
        return await self.db.get(TallyAction,decision['action_id'])
    async def test_default_disabled_and_shadow_never_queues(self):
        row=await self.create()
        result=await auto.evaluate(self.db,self.principal,row['id']);self.assertEqual(result['decision'],'blocked')
        await self.policy('shadow');result=await auto.evaluate(self.db,self.principal,row['id'])
        self.assertEqual(result['decision'],'auto_post',result)
        action=await self.db.get(TallyAction,result['action_id']);self.assertEqual(action.status,'preview')
        self.assertEqual((await auto.usage(self.db,self.cid))['count'],0)
        again=await auto.evaluate(self.db,self.principal,row['id']);self.assertEqual(again['id'],result['id'])
    async def test_auto_reserves_and_verifies_without_human_confirmation(self):
        action=await self.queued();self.assertEqual(action.status,'queued')
        self.assertEqual((await auto.usage(self.db,self.cid))['count'],1)
        await auto.dispatch_guard(self.db,action)
        calls=[]
        async def operation(db,company,kind,**kwargs):
            calls.append(kind);return dict(status='ready') if kind.endswith('_validate') else dict(status='verified',voucher_number='D8-fake')
        with patch.object(sync,'operation',operation),patch.object(sync,'capture_snapshot',AsyncMock(return_value=self.snapshot)),patch.object(sync,'publish_snapshot',AsyncMock()):
            await sync.process_action(self.db,action,self.company)
        self.assertEqual(action.status,'verified');self.assertEqual(len([c for c in calls if c.endswith('_post')]),1)
        self.assertEqual((await self.db.scalars(select(Decision).where(Decision.company_id==self.cid))).all()[0].action_id,action.token)
    async def test_pause_stops_queued_before_send_and_keeps_budget(self):
        action=await self.queued();await self.policy('paused')
        with patch.object(sync,'operation',AsyncMock()) as operation:
            await sync.process_action(self.db,action,self.company);operation.assert_not_awaited()
        self.assertEqual(action.status,'needs_review');self.assertFalse(action.result['uncertain'])
        self.assertEqual((await auto.usage(self.db,self.cid))['count'],1)
    async def test_permission_revocation_blocks_dispatch(self):
        action=await self.queued();member=await self.db.get(OrganizationMembership,(self.user,self.org));member.role='member';await self.db.commit()
        with self.assertRaisesRegex(TallyError,'permission'):await auto.dispatch_guard(self.db,action)
    async def test_current_master_change_blocks_dispatch(self):
        action=await self.queued();snapshot=await self.db.get(TallySnapshot,self.cid)
        from app.services.tally_sync_protocol import deserialize_catalog,serialize_catalog
        catalog=deserialize_catalog(snapshot.catalog);catalog['items'][0].find('BASEUNITS').text='pcs';snapshot.catalog=serialize_catalog(catalog);await self.db.commit()
        with self.assertRaisesRegex(TallyError,'master changed'):await auto.dispatch_guard(self.db,action)
    async def test_daily_count_amount_and_per_invoice_limits(self):
        await self.policy();first=await self.create('A');await auto.evaluate(self.db,self.principal,first['id'])
        second=await self.create('B');await auto.evaluate(self.db,self.principal,second['id'])
        third=await self.create('C');result=await auto.evaluate(self.db,self.principal,third['id']);self.assertEqual(result['decision'],'blocked',result)
        self.assertIn('Daily',result['reasons'][0]);self.assertEqual((await auto.usage(self.db,self.cid))['count'],2)
        # Editing a policy does not reset the amount already reserved.
        current=await auto.policy_view(self.db,self.principal,self.cid)
        await auto.save_policy(self.db,self.principal,self.cid,auto.PolicySave(revision=current['revision'],mode='auto',suppliers=['Supplier'],items=['Cement'],per_invoice='100',daily_amount='1000',daily_count=50))
        result=await auto.evaluate(self.db,self.principal,third['id']);self.assertIn('Per-invoice',result['reasons'][0])
    async def test_missing_limit_disables_and_stale_cross_scope_policy_denied(self):
        await auto.save_policy(self.db,self.principal,self.cid,auto.PolicySave(revision=0,mode='auto',suppliers=['Supplier'],items=['Cement'],per_invoice='500',daily_count=2))
        result=await auto.evaluate(self.db,self.principal,(await self.create())['id']);self.assertEqual(result['decision'],'blocked')
        with self.assertRaises(HTTPException):await auto.save_policy(self.db,self.principal,self.cid,auto.PolicySave(revision=0))
        other=SimpleNamespace(**{**vars(self.principal),'organization_id':'other'})
        with self.assertRaises(HTTPException):await auto.policy_view(self.db,other,self.cid)
    async def test_ambiguous_source_and_duplicate_never_queue(self):
        await self.policy();row=await self.create()
        with patch.object(auto,'source_gate',AsyncMock(side_effect=TallyError('Ambiguous source unit'))):
            result=await auto.evaluate(self.db,self.principal,row['id']);self.assertEqual(result['decision'],'review')
        await self.policy();row=await self.create('DUP')
        with patch.object(memory,'live_check',AsyncMock(side_effect=TallyError('Existing Tally duplicate'))):
            result=await auto.evaluate(self.db,self.principal,row['id']);self.assertEqual(result['decision'],'blocked')
        self.assertEqual((await auto.usage(self.db,self.cid))['count'],0)
    async def test_pause_during_native_validation_blocks_write(self):
        action=await self.queued();calls=[]
        async def operation(db,company,kind,**kwargs):
            calls.append(kind)
            from app.models.purchase_automation import PurchaseAutomationPolicy
            policy=await db.get(PurchaseAutomationPolicy,company.id);policy.data={**policy.data,'mode':'paused'};policy.revision+=1;await db.commit()
            return {'status':'ready'}
        with patch.object(sync,'operation',operation):await sync.process_action(self.db,action,self.company)
        self.assertEqual(len(calls),1);self.assertEqual(action.status,'needs_review')
    async def test_old_day_reservation_cannot_post_and_uncertain_only_reconciles(self):
        action=await self.queued();reservation=await self.db.get(Reservation,action.token)
        from datetime import timedelta
        reservation.day-=timedelta(days=1);await self.db.commit()
        with self.assertRaisesRegex(TallyError,'expired'):await auto.dispatch_guard(self.db,action)
        action.status='verification_pending';await self.db.commit();await self.policy('paused')
        with patch.object(sync,'operation',AsyncMock(return_value={'status':'verification_pending'})) as operation:
            await sync.process_action(self.db,action,self.company)
            self.assertTrue(operation.call_args.args[2].endswith('_reconcile'))
    async def test_pause_works_without_masters_and_policy_history_persists(self):
        await self.policy()
        with patch.object(memory,'catalog_for',AsyncMock(side_effect=TallyError('offline'))):
            result=await auto.pause_policy(self.db,self.principal,self.cid)
        self.assertEqual(result['policy']['mode'],'paused')
        from app.models.purchase_automation import PurchaseAutomationPolicyEvent
        events=list(await self.db.scalars(select(PurchaseAutomationPolicyEvent).where(PurchaseAutomationPolicyEvent.company_id==self.cid)))
        self.assertEqual(len(events),2);self.assertEqual(events[0].data['mode'],'auto')
    async def test_concurrent_evaluations_cannot_overbook_daily_amount(self):
        import asyncio
        from app.database.session import AsyncSessionLocal
        await self.policy(daily_count=100,daily_amount='300')
        first=await self.create('CONCURRENT-A');second=await self.create('CONCURRENT-B')
        async def run(draft_id):
            async with AsyncSessionLocal() as session:return await auto.evaluate(session,self.principal,draft_id)
        results=await asyncio.gather(run(first['id']),run(second['id']))
        self.assertEqual(sorted(r['decision'] for r in results),['auto_post','blocked'],results)
        self.assertEqual((await auto.usage(self.db,self.cid))['count'],1)
        self.assertEqual(Decimal((await auto.usage(self.db,self.cid))['amount']),Decimal('200'))
    async def test_worker_evaluates_new_documents_once_without_starvation(self):
        await self.policy('shadow');row=await self.create('WORKER')
        doc=BillDocument(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.cid,filename='worker.pdf',media_type='application/pdf',size=1,sha256=secrets.token_hex(32),object_key='synthetic',status='ready',page_count=1,attempts=0,generation=0,created_at=sync.now(),updated_at=sync.now())
        self.db.add(doc);await self.db.flush()
        draft=await self.db.get(PurchaseDraft,row['id']);draft.document_id=doc.id;doc.extraction_result={'buyer_name':'Pilot Test'};await self.db.commit()
        await auto.automation_tick({});await auto.automation_tick({})
        await self.db.refresh(draft)
        self.assertIsNotNone(draft.action_id)
        self.assertEqual((await self.db.get(TallyAction,draft.action_id)).status,'preview')
        self.assertEqual(len(list(await self.db.scalars(select(Decision).where(Decision.draft_id==draft.id)))),1)
    async def test_helper_result_does_not_deadlock_uncommitted_preview(self):
        import asyncio,json
        from app.database.session import AsyncSessionLocal
        from app.models.tally import TallyDevice
        from app.api.v1 import routes_tally_bridge as routes
        device_id=secrets.token_hex(16)
        self.db.add(TallyDevice(id=device_id,organization_id=self.org,credential_hash=secrets.token_hex(32),revoked=False));await self.db.commit()
        # Inserting an action holds FK KEY SHARE on its organization until commit.
        self.db.add(TallyAction(token=secrets.token_hex(16),organization_id=self.org,user_id=self.user,session_id='fixture',company_id=self.cid,connection_version=1,created_at=sync.now(),expires_at=sync.now(),payload={},xml_payload='',status='preview',attempts=0))
        await self.db.flush()
        class Request:
            async def stream(self):yield json.dumps({'id':'a'*32,'data':{'status':'clear'}}).encode()
        async with AsyncSessionLocal() as receiver:
            device=await receiver.get(TallyDevice,device_id)
            redis=SimpleNamespace(aclose=AsyncMock())
            with patch.object(routes,'get_redis_client',AsyncMock(return_value=redis)),patch.object(routes,'consume_result',AsyncMock()) as consume:
                result=await asyncio.wait_for(routes.results(Request(),device,receiver),timeout=2)
                self.assertTrue(result['accepted']);consume.assert_awaited_once()
                await receiver.rollback()
    async def test_helper_claim_rechecks_paused_policy_before_post(self):
        import json
        from app.models.tally import TallyDevice
        from app.api.v1 import routes_tally_bridge as routes
        from app.core.config import get_settings
        from redis.asyncio import Redis
        action=await self.queued()
        device=TallyDevice(id=secrets.token_hex(16),organization_id=self.org,credential_hash=secrets.token_hex(32),revoked=False)
        self.db.add(device);self.company.device_id=device.id;action.device_version=device.credential_hash;action.status='submitting'
        snapshot=await self.db.get(TallySnapshot,self.cid);snapshot.device_version=device.credential_hash;await self.db.commit()
        await auto.pause_policy(self.db,self.principal,self.cid)
        async def redis_client():return Redis.from_url(get_settings().redis_url,decode_responses=True)
        redis=await redis_client();job_id=secrets.token_hex(16)
        job=dict(id=job_id,device_id=device.id,organization_id=self.org,credential_version=device.credential_hash,operation='purchase_multi_post',company=self.company.name,identity=self.company.identity,payload=action.payload,config={**sync.config_data(self.cfg),'invoice_guard':action.preconditions['invoice_guard']},action_id=action.token)
        try:
            await redis.set('tally:job:'+job_id,json.dumps(job),ex=30);await redis.rpush('tally:queue:v9:'+device.id,json.dumps(job))
            with patch.object(routes,'get_redis_client',redis_client):
                with self.assertRaises(HTTPException) as exc:await routes.jobs(9,device,self.db)
                self.assertEqual(exc.exception.status_code,403);self.assertIn('Automation policy',exc.exception.detail)
        finally:
            await redis.delete('tally:job:'+job_id,*['tally:'+k+':'+device.id for k in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','v8online','v9online','queue:v9')]);await redis.aclose()

class SourceEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.cid=self.company.id
        self.pdf=Path('data/day5-native/philixa-matching-test-bill.pdf').read_bytes()
        raw=extraction.extract_from_pdf_text_local(self.pdf)
        content=dict(party_name=raw['supplier_name'],invoice_number=raw['invoice_number'],entry_date='2026-10-02',invoice_total=raw['invoice_total'],tax_treatment=raw['tax_treatment'],supplier_gstin=raw['supplier_gstin'],place_of_supply=raw['place_of_supply'],round_off=raw['round_off'],expected_taxes=raw['expected_taxes'],lines=[{k:v for k,v in line.items() if k in drafts.DraftLine.model_fields} for line in raw['lines']])
        self.company.name='Philixa Test'
        self.doc=BillDocument(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.cid,filename='dummy.pdf',media_type='application/pdf',size=len(self.pdf),sha256=__import__('hashlib').sha256(self.pdf).hexdigest(),object_key='synthetic',status='ready',page_count=1,attempts=0,generation=0,created_at=sync.now(),updated_at=sync.now())
        self.db.add(self.doc);await self.db.flush()
        self.row=PurchaseDraft(id=secrets.token_hex(16),organization_id=self.org,user_id=self.user,company_id=self.cid,document_id=self.doc.id,content=drafts.DraftContent.model_validate(content).model_dump(mode='json'),revision=0,created_at=sync.now(),updated_at=sync.now())
        self.db.add(self.row);await self.db.commit()
        p=patch.object(docs.storage,'read',return_value=self.pdf);p.start();self.addCleanup(p.stop)
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def test_original_digital_pdf_and_changed_value(self):
        proof=await auto.source_gate(self.db,self.row,self.company);self.assertEqual(Decimal(proof['amount']),Decimal('1167'))
        changed=copy.deepcopy(self.row.content);changed['lines'][0]['quantity']='11';self.row.content=changed
        with self.assertRaisesRegex(TallyError,'quantity'):await auto.source_gate(self.db,self.row,self.company)
    async def test_photo_missing_source_checksum_and_wrong_buyer_block(self):
        self.doc.media_type='image/png'
        with self.assertRaisesRegex(TallyError,'photos/scans'):await auto.source_gate(self.db,self.row,self.company)
        self.doc.media_type='application/pdf';self.company.name='Wrong company'
        with self.assertRaises(HTTPException):await auto.source_gate(self.db,self.row,self.company)
        self.company.name='Philixa Test';self.doc.sha256='0'*64
        with self.assertRaises(HTTPException):await auto.source_gate(self.db,self.row,self.company)
    async def test_scanned_page_with_ocr_text_still_requires_review(self):
        import pymupdf
        original=pymupdf.open(stream=self.pdf,filetype='pdf');image=original[0].get_pixmap().tobytes('png')
        scanned=pymupdf.open();page=scanned.new_page(width=842,height=595);page.insert_image(page.rect,stream=image)
        page.insert_text((30,30),'OCR text layer must not authorize automation for this scanned invoice',render_mode=3)
        result=__import__('json').loads((await docs.parse(scanned.tobytes(),'automation')).decode())
        self.assertFalse(result['_digital_only']);scanned.close();original.close()

if __name__=='__main__':unittest.main()
