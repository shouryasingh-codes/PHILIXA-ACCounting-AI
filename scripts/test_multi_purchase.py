"""Protocol v7 and database tests with synthetic Tally transport only."""
import copy
import json
import unittest
from decimal import Decimal
from unittest.mock import patch,AsyncMock
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from pydantic import ValidationError
from app.services import tally_sync as sync,tally_sync_protocol as protocol,purchase_draft_service as drafts
from app.services import tally_multi_purchase as multi
from app.services.tally_connector import TallyError,TallyRejected
from app.models.tally import TallyAction
import scripts.test_tally_sync as fixtures


def payload(single,count=2):
    result={k:single[k] for k in ('company','godown','party','voucher_type','ledger','date','guid')}
    result.update(operation='purchase_multi',items=[],total='0.00',master_fingerprint='')
    for i in range(count):
        rate=Decimal('350.00')+i
        result['items'].append({'item':single['item'],'quantity':'1','unit':single['unit'],
            'rate':str(rate),'total':str(rate),'stock_before':single['stock_before']})
    result['total']=str(sum((Decimal(l['total']) for l in result['items']),Decimal('0.00')))
    return result


class MultiProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ProtocolTests.asyncSetUp(self)
        self.p=payload(self.p)
        self.p['master_fingerprint']=multi.fingerprint_multi(self.data,self.p)

    asyncTearDown=fixtures.ProtocolTests.asyncTearDown

    async def execute(self,op):
        return await protocol.execute_sync('purchase_multi_'+op,company='Pilot Test',identity='identity',
            payload=self.p,config=self.cfg,journal_path=self.path)

    async def test_one_twenty_fifty_lines_verify_without_duplicate_delivery(self):
        import uuid
        for count in (1,20,50):
            self.p=payload(multi.legacy_line(self.p,self.p['items'][0]),count)
            self.p['guid']=str(uuid.uuid4());self.p['master_fingerprint']=multi.fingerprint_multi(self.data,self.p)
            before=self.posts
            reply=await self.execute('post');self.assertEqual(reply['status'],'verified')
            self.assertEqual(len(self.vouchers[-1].findall('ALLINVENTORYENTRIES.LIST')),count)
            self.assertEqual((await self.execute('post'))['status'],'verified')
            self.assertEqual(self.posts,before+1)

    async def test_every_line_and_bill_total_are_checked(self):
        await self.execute('post');original=copy.deepcopy(self.vouchers[0])
        for path,text in (('ALLINVENTORYENTRIES.LIST[2]/ACTUALQTY','2 bags'),
            ('ALLINVENTORYENTRIES.LIST[2]/RATE','999/bags'),('LEDGERENTRIES.LIST/AMOUNT','1'),
            ('LEDGERENTRIES.LIST/BILLALLOCATIONS.LIST/AMOUNT','1'),('DATE','20260402')):
            damaged=copy.deepcopy(original);damaged.find(path).text=text
            self.assertFalse(multi.verify_multi(damaged,self.p),path)
        missing=copy.deepcopy(original);missing.remove(missing.findall('ALLINVENTORYENTRIES.LIST')[1])
        self.assertFalse(multi.verify_multi(missing,self.p))
        reordered=copy.deepcopy(original);first=reordered.findall('ALLINVENTORYENTRIES.LIST')[0];reordered.remove(first);reordered.append(first)
        self.assertTrue(multi.verify_multi(reordered,self.p))

    async def test_native_guid_full_ledger_and_master_change(self):
        await self.execute('post');v=self.vouchers[0];v.find('GUID').text='tally-native-guid'
        party=v.find('LEDGERENTRIES.LIST');full=copy.deepcopy(party);full.tag='ALLLEDGERENTRIES.LIST';v.append(full)
        party.remove(party.find('BILLALLOCATIONS.LIST'));ET.SubElement(party,'BILLALLOCATIONS.LIST')
        self.assertEqual((await self.execute('reconcile'))['status'],'verified')
        self.data['units'][0].find('DECIMALPLACES').text='2'
        self.assertEqual((await self.execute('validate'))['status'],'needs_review')

    async def test_uncertain_submission_is_never_reimported(self):
        async def timeout(xml):self.posts+=1;raise TallyError('lost response')
        self.connector.post=timeout
        self.assertEqual((await self.execute('post'))['status'],'verification_pending')
        self.assertEqual((await self.execute('post'))['status'],'verification_pending')
        self.assertEqual(self.posts,1)

    async def test_changed_total_unknown_unit_and_payload_rejected(self):
        for mutate in (lambda p:p.update(total='1'),lambda p:p['items'][1].update(unit='kg'),
            lambda p:p['items'][1].update(item='unknown'),lambda p:p['items'][1].update(quantity='NaN')):
            p=copy.deepcopy(self.p);mutate(p)
            with self.assertRaises((TallyError,ValueError)):multi.validate_multi(self.data,p,self.cfg)
        self.p['items']=[]
        self.assertEqual((await self.execute('validate'))['status'],'needs_review')


class MultiDrafts(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DurableTests.asyncSetUp
    asyncTearDown=fixtures.DurableTests.asyncTearDown

    async def stage(self):
        row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','entry_date':'2026-10-01','lines':[
                {'item_name':'Cement','quantity':'8','unit':'bags','rate':'350'},
                {'item_name':'Cement','quantity':'2','unit':'bags','rate':'400'}]}))
        self.assertEqual(row['total'],'3600.00')
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))):
            result=await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        return row['id'],await self.db.get(TallyAction,result['preview']['token'])

    async def test_saved_lines_preview_projection_and_dispatch(self):
        draft_id,action=await self.stage()
        self.assertEqual(action.schema_version,2);self.assertEqual(action.status,'preview')
        self.assertEqual(len((await drafts.read_draft(self.db,self.principal,draft_id))['content']['lines']),2)
        await sync.confirm_queued(self.db,self.principal,action)
        projected=await sync.stock_projection(self.db,self.company,'Cement','20','bags')
        self.assertEqual(projected['expected_quantity'],'30')
        with (patch.object(sync,'operation',AsyncMock(side_effect=[{'status':'ready'},{'status':'verified','voucher_number':'7'}])) as execute,
            patch.object(sync,'capture_snapshot',AsyncMock(return_value=self.snapshot))):
            await sync.process_action(self.db,action,self.company)
        self.assertEqual([call.args[2] for call in execute.await_args_list],['purchase_multi_validate','purchase_multi_post'])
        self.assertEqual(action.status,'verified')

    async def test_edit_invalidates_entire_preview_and_pending_is_read_only(self):
        draft_id,action=await self.stage()
        row=await drafts.read_draft(self.db,self.principal,draft_id);content=row['content'];content['lines'][1]['quantity']='3'
        await drafts.save_draft(self.db,self.principal,draft_id,drafts.DraftSave(revision=1,content=content))
        self.assertEqual(action.status,'expired')
        self.assertEqual((await drafts.read_draft(self.db,self.principal,draft_id))['total'],'4000.00')

    async def test_incomplete_ambiguous_and_excess_lines_never_queue(self):
        with self.assertRaises(ValidationError):drafts.DraftContent(lines=[{}]*101)
        with self.assertRaises(ValidationError):drafts.DraftContent(lines=[{}],item_name='Cement')
        row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','entry_date':'2026-10-01','lines':[{}]}))
        with self.assertRaises(HTTPException) as exc:
            await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        self.assertEqual(exc.exception.status_code,422)

    async def test_company_master_suggestions_are_scoped_and_preserve_base_unit(self):
        from types import SimpleNamespace
        data=await drafts.company_masters(self.db,self.principal,self.company.id)
        self.assertIn('Supplier',data['suppliers'])
        self.assertEqual(data['items'],[{'name':'Cement','unit':'bags'}])
        other=SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'})
        with self.assertRaises(HTTPException):await drafts.company_masters(self.db,other,self.company.id)

    async def test_concurrent_edit_during_snapshot_refresh_cannot_preview_stale_lines(self):
        from app.database.session import AsyncSessionLocal
        row=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','entry_date':'2026-10-01','lines':[
                {'item_name':'Cement','quantity':'1','unit':'bags','rate':'350'}]}))
        async def refresh(db,company):
            await db.commit()
            async with AsyncSessionLocal() as other:
                content=copy.deepcopy(row['content']);content['lines'][0]['quantity']='9'
                await drafts.save_draft(other,self.principal,row['id'],drafts.DraftSave(revision=0,content=content))
        with patch.object(sync,'refresh_company',side_effect=refresh):
            with self.assertRaises(HTTPException) as exc:
                await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        self.assertEqual(exc.exception.status_code,409)
        saved=await drafts.read_draft(self.db,self.principal,row['id'])
        self.assertEqual(saved['content']['lines'][0]['quantity'],'9')
        self.assertIsNone(saved['action_id'])


if __name__=='__main__':unittest.main()
