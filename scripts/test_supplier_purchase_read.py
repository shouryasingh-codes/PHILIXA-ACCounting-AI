import copy
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree.ElementTree import fromstring
from fastapi import HTTPException
from app.services import supplier_purchase_read as service
from app.services.purchase_identity import master_identity, master_fingerprint
from app.services.tally_sync_protocol import serialize_catalog
from app.services.tally_purchase_history import digest_query


class ReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.party=fromstring('<LEDGER NAME="Sharma Traders"><PARENT>Sundry Creditors</PARENT><GUID>party-1</GUID></LEDGER>')
        self.item=fromstring('<STOCKITEM NAME="Cement"><GUID>item-1</GUID><BASEUNITS>bags</BASEUNITS></STOCKITEM>')
        self.company=SimpleNamespace(id='company',name='Test',identity='native-company',device_id='device')
        self.catalog={'non_gst':True,'cost_centres_enabled':False,'ledgers':[self.party],'items':[self.item],'units':[],'godowns':[]}
        self.snapshot=SimpleNamespace(collected_at=service.sync.now(),catalog=serialize_catalog(self.catalog))
        self.db=SimpleNamespace(commit=AsyncMock(),refresh=AsyncMock())
        self.rows=[{'voucher_id':'voucher-1','alteration_id':'1','invoice_number':'INV-1','entry_date':'2026-10-02',
            'supplier':'Sharma Traders','supplier_id':master_identity(self.party),'supplier_fingerprint':master_fingerprint(self.party),
            'item':'Cement','item_id':master_identity(self.item),'item_fingerprint':master_fingerprint(self.item),
            'quantity':'5','unit':'bags','rate':'350','amount':'1750','discount':'0'}]
        self.complete=True;self.corrupt=False;self.operations=[]
        async def operation(db,company,kind,**kw):
            self.assertEqual(kind,'purchase_history_read');self.operations.append(kind)
            binding={'company':'Test','identity':'native-company','query':digest_query(kw['payload'])}
            digest=hashlib.sha256(json.dumps(self.rows,sort_keys=True).encode()).hexdigest()
            if 'page' in kw:
                return {**binding,'generation':'a'*32,'page':0,'records':[] if self.corrupt else self.rows}
            return {**binding,'generation':'a'*32,'complete':self.complete,'collected_at':service.sync.now().isoformat(),
                    'count':len(self.rows),'hashes':[digest] if self.rows else []}
        self.patches=[patch.object(service.drafts,'company_for',AsyncMock(return_value=self.company)),
            patch.object(service.sync,'saved_snapshot',AsyncMock(return_value=self.snapshot)),
            patch.object(service.sync,'bound_device',AsyncMock()),patch.object(service.sync,'operation',operation)]
        for p in self.patches:p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):p.stop()

    async def read(self):return await service.read(self.db,None,'company','Sharma Traders','2026-09-01','2026-11-01')

    async def test_reads_native_lines_without_draft_or_write(self):
        result=await self.read()
        self.assertTrue(result['history_complete']);self.assertIn('Cement',result['response'])
        self.assertIn('1750',result['response']);self.assertEqual(len(self.operations),2)
        self.assertNotIn('task_id',result);self.assertNotIn('draft_id',result)

    async def test_empty_complete_read_is_period_scoped(self):
        self.rows=[];result=await self.read()
        self.assertEqual(result['history_count'],0);self.assertIn('verified period',result['response'])

    async def test_incomplete_read_never_claims_no_purchases(self):
        self.complete=False;result=await self.read()
        self.assertFalse(result['history_complete']);self.assertNotIn('history_records',result)
        self.assertEqual(len(self.operations),1)

    async def test_changed_or_missing_pages_do_not_become_answers(self):
        self.corrupt=True;result=await self.read()
        self.assertFalse(result['history_complete']);self.assertNotIn('Cement',result['response'])

    async def test_wrong_identity_or_amount_rejected(self):
        for field,value in [('supplier_id','foreign'),('amount','1700'),('rate','NaN'),('unit','BOX')]:
            with self.subTest(field=field):
                original=self.rows[0][field];self.rows[0][field]=value
                self.assertFalse((await self.read())['history_complete']);self.rows[0][field]=original

    async def test_ambiguous_supplier_is_not_guessed(self):
        self.catalog['ledgers'].append(copy.deepcopy(self.party));self.snapshot.catalog=serialize_catalog(self.catalog)
        self.assertFalse((await self.read())['history_complete']);self.assertFalse(self.operations)

    async def test_current_permissions_are_rechecked(self):
        with patch.object(service.drafts,'company_for',AsyncMock(side_effect=[self.company,HTTPException(403,'revoked')])):
            with self.assertRaises(HTTPException):await self.read()

    async def test_provider_is_not_required_for_native_history(self):
        with patch('app.services.ai_engine_manager.call_gemini_json',AsyncMock(side_effect=AssertionError('No model'))):
            self.assertTrue((await self.read())['history_complete'])

    async def test_window_larger_than_supported_is_actionable(self):
        result=await service.read(self.db,None,'company','Sharma Traders','2020-01-01','2026-11-01')
        self.assertFalse(result['history_complete']);self.assertFalse(self.operations)

    async def test_offline_tally_falls_back_to_verified_cache_and_actions(self):
        from datetime import datetime, timezone
        cache_row=SimpleNamespace(
            query={'supplier':'Sharma Traders'},
            data={'records':[self.rows[0]]},
            collected_at=datetime(2026,10,3,tzinfo=timezone.utc),
        )
        action_row=SimpleNamespace(
            created_at=datetime(2026,10,4,tzinfo=timezone.utc),
            payload={'operation':'goods_receipt','party':'Sharma Traders','date':'2026-10-04',
                     'guid':'grn-1','tracking':'PH-GRN-1',
                     'items':[{'item':'Cement','quantity':'3','unit':'bags','rate':'350.00'}]},
        )
        class _ScalarResult:
            def __init__(self,items):self._items=items
            def all(self):return self._items
        scalars=AsyncMock(side_effect=[_ScalarResult([cache_row]),_ScalarResult([action_row])])
        db=SimpleNamespace(commit=AsyncMock(),refresh=AsyncMock(),scalars=scalars)
        with patch.object(service.sync,'operation',AsyncMock(side_effect=service.TallyError('http_unreachable'))):
            result=await service.read(db,None,'company','Sharma Traders','2026-09-01','2026-11-01')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['data_source'],'cached')
        self.assertFalse(result['history_complete'])
        self.assertEqual(result['history_count'],2)
        self.assertIn('Receipt Note',result['response'])
        self.assertIn('Cement',result['response'])

    async def test_live_history_reconciles_verified_receipt_note_without_duplicate_purchase(self):
        from datetime import datetime, timezone
        dup_purchase=SimpleNamespace(
            created_at=datetime(2026,10,2,tzinfo=timezone.utc),
            payload={'operation':'purchase_multi','party':'Sharma Traders','date':'2026-10-02',
                     'guid':'tally-guid-different-format','invoice_number':'INV-1',
                     'items':[{'item':'Cement','quantity':'5','unit':'bags','rate':'350'}]},
        )
        receipt=SimpleNamespace(
            created_at=datetime(2026,10,5,tzinfo=timezone.utc),
            payload={'operation':'goods_receipt','party':'Sharma Traders','date':'2026-10-05',
                     'guid':'grn-2','tracking':'PH-GRN-2',
                     'items':[{'item':'Cement','quantity':'2','unit':'bags','rate':'350'}]},
        )
        class _ScalarResult:
            def __init__(self,items):self._items=items
            def all(self):return self._items
        db=SimpleNamespace(commit=AsyncMock(),refresh=AsyncMock(),scalars=AsyncMock(return_value=_ScalarResult([receipt,dup_purchase])))
        result=await service.read(db,None,'company','Sharma Traders','2026-09-01','2026-11-01')
        self.assertTrue(result['history_complete'])
        self.assertEqual(result['history_count'],2)
        self.assertIn('Receipt Note',result['response'])

if __name__=='__main__':unittest.main()
