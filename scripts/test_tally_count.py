"""Synthetic count safety tests. These do not certify real Tally XML."""
import copy
import unittest
import uuid
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch,AsyncMock
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from app.services import tally_count as count,tally_sync as sync,business_command_service as commands
from app.services.tally_connector import TallyError,value
from app.models.tally import TallyAction
import scripts.test_tally_sync as fixtures
from scripts.test_tally import node

class CountProtocol(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ProtocolTests.asyncSetUp
    asyncTearDown=fixtures.ProtocolTests.asyncTearDown
    async def prepare(self,target='8'):
        stamp=datetime.now(ZoneInfo('Asia/Kolkata'))
        self.p={'operation':'stock_count_set','company':'Pilot Test','godown':'Main Location','item':'Cement','unit':'bags',
                'target_quantity':target,'counted_at':stamp.isoformat(),'reason':'Physical recount','date':stamp.date().isoformat(),
                'guid':str(uuid.uuid4()),'baseline':'','revision':''}
        original=self.connector.collection
        async def collection(kind,*args,**kwargs):
            if kind=='Company':return [node('COMPANY','Pilot Test',GUID='identity',ISDELIVERYNOTE='No')]
            return await original(kind,*args,**kwargs)
        self.connector.collection=collection
        self.cert=patch.object(count,'COUNT_CODEC_CERTIFIED',True);self.cert.start();self.addCleanup(self.cert.stop)
        reply=await self.run_op('stock_count_validate');self.p.update(baseline=reply['baseline'],revision=reply['revision'])
        originalpost=self.connector.post
        async def post(xml):
            reply=await originalpost(xml)
            self.data['items'][0].find('CLOSINGBALANCE').text=target+' bags'
            return reply
        self.connector.post=post
    async def run_op(self,op):
        return await count.execute_count(op,self.connector,'Pilot Test','identity',self.p,self.cfg,self.path)
    async def test_verified_zero_and_duplicate(self):
        await self.prepare('0')
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'verified')
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'verified');self.assertEqual(self.posts,1)
    async def test_stale_same_quantity_transaction(self):
        await self.prepare();self.vouchers.append(node('VOUCHER','',GUID='manual',NARRATION='manual activity'))
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'needs_review');self.assertEqual(self.posts,0)
    async def test_transaction_without_guid_still_invalidates_baseline(self):
        await self.prepare()
        self.vouchers.append(node('VOUCHER','',VOUCHERTYPENAME='Purchase',NARRATION='manual activity'))
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'needs_review')
        self.assertEqual(self.posts,0)
    async def test_physical_difference_must_be_enabled_in_export(self):
        await self.prepare()
        voucher=ET.fromstring(count.count_xml(self.p)).find('.//VOUCHER')
        self.assertTrue(count.verify_count(voucher,self.p))
        voucher.find('DIFFACTUALQTY').text='No'
        self.assertFalse(count.verify_count(voucher,self.p))
        voucher.remove(voucher.find('DIFFACTUALQTY'))
        self.assertFalse(count.verify_count(voucher,self.p))
    async def test_timeout_no_reimport(self):
        await self.prepare()
        async def lost(xml):self.posts+=1;raise TallyError('timeout')
        self.connector.post=lost
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'verification_pending')
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'verification_pending');self.assertEqual(self.posts,1)
    async def test_unproven_codec_and_tracking_fail_closed(self):
        await self.prepare()
        with patch.object(count,'COUNT_CODEC_CERTIFIED',False):self.assertEqual((await self.run_op('stock_count_post'))['status'],'blocked')
        original=self.connector.collection
        async def unknown(kind,*args,**kwargs):
            if kind=='Company':return [node('COMPANY','Pilot Test',GUID='identity')]
            return await original(kind,*args,**kwargs)
        self.connector.collection=unknown
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'blocked');self.assertEqual(self.posts,0)
    async def test_bad_units_and_previous_day(self):
        await self.prepare();self.p['unit']='kg'
        with self.assertRaises(TallyError):await self.run_op('stock_count_validate')
        self.p['unit']='bags';self.p['counted_at']=(datetime.now(ZoneInfo('Asia/Kolkata'))-timedelta(days=1)).isoformat()
        with self.assertRaises(TallyError):await self.run_op('stock_count_validate')
    async def test_foreign_activity_after_submission(self):
        await self.prepare();original=self.connector.post
        async def changed(xml):
            reply=await original(xml);self.vouchers.append(node('VOUCHER','',GUID='foreign'));return reply
        self.connector.post=changed
        self.assertEqual((await self.run_op('stock_count_post'))['status'],'needs_review')

class CountDurable(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        cert=patch.object(count,'COUNT_CODEC_CERTIFIED',True)
        cert.start();self.addCleanup(cert.stop)
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def draft(self):
        p=commands.ParsedCommand(intent='stock_count_set',company_id=self.company.id,item_name='Cement',target_quantity='8',unit='bags',counted_at=datetime.now(ZoneInfo('Asia/Kolkata')),reason='Recount')
        result=await count.create_draft(self.db,self.principal,p)
        return await self.db.get(TallyAction,result['tally_action'])
    async def test_offline_draft_no_confirmation_no_expected_delta(self):
        a=await self.draft();self.assertEqual(a.status,'draft')
        await sync.confirm_queued(self.db,self.principal,a);self.assertEqual(a.status,'draft')
        self.assertEqual((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'],'20')
        await sync.confirm_queued(self.db,self.principal,a,approve=False);self.assertEqual(a.status,'cancelled')
    async def test_unavailable_count_no_form_or_new_draft(self):
        p=commands.ParsedCommand(intent='stock_count_set',company_id=self.company.id,item_name='Cement')
        with patch.object(count,'COUNT_CODEC_CERTIFIED',False):
            result=await count.create_draft(self.db,self.principal,p)
        self.assertFalse(result['count_capability']['available'])
        self.assertNotIn('tally_form',result)
        self.assertNotIn('tally_action',result)
    async def test_existing_draft_retained_without_retry_or_post(self):
        a=await self.draft()
        with patch.object(count,'COUNT_CODEC_CERTIFIED',False),patch.object(sync,'operation',AsyncMock(side_effect=AssertionError('No disabled dispatch'))):
            result=await count.review(self.db,self.principal,a)
            self.assertFalse(result['count_review_available'])
            self.assertEqual(result['sync_status'],'draft')
            self.assertIn('Saved draft retained',result['response'])
            a.status='preview';await self.db.commit()
            await sync.confirm_queued(self.db,self.principal,a)
            self.assertEqual(a.status,'preview')
        await self.db.refresh(a)
        self.assertEqual(a.payload['target_quantity'],'8')
    async def test_review_reconfirmation_same_action(self):
        a=await self.draft()
        with patch.object(sync,'operation',AsyncMock(return_value={'status':'ready','baseline':'20','revision':'rev'})):
            result=await count.review(self.db,self.principal,a);self.assertEqual(result['preview']['token'],a.token)
            result=await count.review(self.db,self.principal,a);self.assertEqual(result['preview']['token'],a.token)
        await sync.confirm_queued(self.db,self.principal,a);self.assertEqual(a.status,'queued')
        self.assertIsNone((await sync.stock_projection(self.db,self.company,'Cement','20','bags'))['expected_quantity'])
    async def test_wrong_session_and_pending_purchase(self):
        a=await self.draft();other=copy.copy(self.principal);other.session_id='forged'
        with self.assertRaises(HTTPException):await count.review(self.db,other,a)
        purchase=await fixtures.DurableTests.preview(self);await sync.confirm_queued(self.db,self.principal,purchase)
        with self.assertRaises(HTTPException):await count.review(self.db,self.principal,a)
    async def test_actual_graph_routes_count_without_history(self):
        from app.services import portfolio_copilot_service as graph
        p=commands.ParsedCommand(intent='stock_count_set',company_id=self.company.id,item_name='Cement',target_quantity='0',unit='bags',counted_at=datetime.now(ZoneInfo('Asia/Kolkata')),reason='Physical count')
        self.assertEqual(graph.business_route({'parsed':p.model_dump()}),'tally_tool')
        with patch.object(commands,'plan_command',AsyncMock(return_value=p)),patch('app.services.ask_client_service.AskClientService',side_effect=AssertionError('RAG forbidden')):
            result=await graph.run_business_graph(commands.CommandRequest(text='actual count zero'),self.principal,self.db)
        self.assertEqual(result['sync_status'],'draft')
    async def test_changed_config_and_member_cannot_review(self):
        a=await self.draft();member=copy.copy(self.principal);member.role='member'
        with self.assertRaises(HTTPException):await count.review(self.db,member,a)
        self.cfg.version+=1;await self.db.commit()
        with self.assertRaises(HTTPException):await count.review(self.db,self.principal,a)

class LanguageSafety(unittest.TestCase):
    def test_100_reviewed_template_variants_against_wrong_model_route(self):
        # Guard evaluation, not a measurement of production LLM accuracy.
        templates=[('add {n} bags of {i}','inventory_add'),('remove {n} bags {i}','inventory_change'),
                   ('{i} ke {n} bags kam karo','inventory_change'),('{i} actual {n} bags stock correct karo','stock_count_set'),
                   ('physical {i} count {n} bags','stock_count_set'),('{i} ginti {n} bags hai','stock_count_set'),
                   ('{i} ke {n} bags purchase karo','purchase_create'),('{i} ke {n} bags kharide','purchase_create'),
                   ('sell {n} bags {i}','blocked'),('{i} ke {n} bags return karo','blocked'),
                   ('{i} ka bill delete karo','blocked'),('{i} stock add mat karo','blocked'),
                   ('{i} stock {n} add nahi karo','blocked'),('{i} actual {n} bags nahi hain','blocked'),
                   ('{i} stock kitna hai','stock_read'),('kitna {i} hai','stock_read'),
                   ('{i} ke {n} bags aaye','inventory_add'),('{i} {n} bags ghata do','inventory_change'),
                   ('{i} {n} bags hata do','inventory_change'),('{i} counted {n} bags','stock_count_set')]
        checked=0
        for i in ('Cement','Steel','Rice','सीमेंट','atta'):
            for template,expected in templates:
                text=template.format(i=i,n=5);request=commands.CommandRequest(text=text)
                parsed=commands.ParsedCommand(intent='purchase_create',item_name=i,quantity='5')
                result=commands.guard_tally_scope(request,parsed)
                with self.subTest(text=text):self.assertEqual('blocked' if result.unsupported_reason else result.intent,expected)
                checked+=1
        self.assertEqual(checked,100)

if __name__=='__main__':unittest.main()
