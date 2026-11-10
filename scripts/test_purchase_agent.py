import copy,json,tempfile,unittest,uuid
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from xml.etree.ElementTree import SubElement,Element
from sqlalchemy import select,func
from fastapi import HTTPException
from app.services import tally_purchase_history as history,purchase_message as message,purchase_agent as agent
from app.services import purchase_draft_service as drafts,purchase_native_context as native,tally_sync as sync
from app.models.purchase_agent import PurchaseGraphCheckpoint,PurchaseHistoryCache
from app.services.purchase_conversation import Reply
from app.services.tally_connector import TallyError
from app.services.purchase_identity import exact_master,master_identity
import scripts.test_gst_purchase as fixture


def query(catalog):
    party=exact_master(catalog,'supplier','Supplier');item=exact_master(catalog,'item','Cement')
    return dict(supplier='Supplier',supplier_id=master_identity(party),items=[dict(name='Cement',id=master_identity(item))],
                from_date='2026-05-01',to_date='2026-10-01')

def voucher(rate='350',**changes):
    v=Element('VOUCHER')
    for key,val in {'GUID':'manual-native-voucher','ALTERID':'12','DATE':'20260901','VOUCHERTYPENAME':'Purchase',
                    'PARTYLEDGERNAME':'Supplier','REFERENCE':'NATIVE-1',**changes}.items():SubElement(v,key).text=val
    line=SubElement(v,'ALLINVENTORYENTRIES.LIST')
    for key,val in dict(STOCKITEMNAME='Cement',BILLEDQTY='5 bags',RATE=rate+'/bags',AMOUNT=str(-5*int(rate))).items():SubElement(line,key).text=val
    return v


class NativeHistory(unittest.IsolatedAsyncioTestCase):
    async def test_manual_native_rows_and_pages_are_bound_to_query(self):
        cat=fixture.catalog();q=query(cat)
        connector=SimpleNamespace(catalog=AsyncMock(return_value=cat),collection=AsyncMock(return_value=[voucher()]))
        with tempfile.TemporaryDirectory() as tmp:
            result=await history.execute(connector,'Pilot Test','identity',q,None,None,tmp+'/journal')
            self.assertTrue(result['complete']);self.assertEqual(result['count'],1)
            page=await history.execute(connector,'Pilot Test','identity',q,result['generation'],0,tmp+'/journal')
            self.assertEqual(page['records'][0]['rate'],'350')
            self.assertEqual(page['records'][0]['voucher_id'],'manual-native-voucher')
            other={**q,'to_date':'2026-09-30'}
            with self.assertRaises(TallyError):await history.execute(connector,'Pilot Test','identity',other,result['generation'],0,tmp+'/journal')
            self.assertEqual(connector.collection.await_count,1)

    async def test_invalid_conflicting_source_does_not_become_complete(self):
        cat=fixture.catalog();q=query(cat)
        rows=[voucher(ISCANCELLED='Yes'),voucher(ISOPTIONAL='Yes'),voucher(DATE='bad'),voucher(GUID='')]
        records,issues=history.normalise_vouchers(rows,cat,q)
        self.assertEqual(records,[]);self.assertTrue(issues)
        v=voucher();line=v.find('ALLINVENTORYENTRIES.LIST');v.append(copy.deepcopy(line))
        self.assertEqual(history.normalise_vouchers([v],cat,q)[0],[])
        line.find('RATE').text='350/kg';v.remove(v.findall('ALLINVENTORYENTRIES.LIST')[1])
        self.assertEqual(history.normalise_vouchers([v],cat,q)[0],[])
        line.find('RATE').text='350/bags';SubElement(line,'DISCOUNT').text='5%'
        self.assertEqual(history.normalise_vouchers([v],cat,q)[0],[])
        q['supplier_id']='changed'
        with self.assertRaises(TallyError):history.normalise_vouchers([voucher()],cat,q)

    async def test_limit_is_incomplete_and_page_size_is_bounded(self):
        cat=fixture.catalog();q=query(cat)
        rows=[voucher(GUID=str(i)) for i in range(5001)]
        records,issues=history.normalise_vouchers(rows,cat,q)
        self.assertEqual(len(records),5000);self.assertIn('History record limit exceeded.',issues)


class Grounding(unittest.TestCase):
    def test_date_phrase_normalises_but_conflicting_dates_reject(self):
        field=dict(path='entry_date',value='02-10-2026',quote='date 02-10-2026')
        output=message.grounded('bill date 02-10-2026',message.MessageFields(updates=[field],unsupported_reason=None))
        self.assertEqual(output[0]['value'],'2026-10-02')
        field['quote']='02-10-2026 or 03-10-2026'
        with self.assertRaises(ValueError):message.grounded(field['quote'],message.MessageFields(updates=[field],unsupported_reason=None))

    def test_tool_budget_and_repeated_arguments_stop(self):
        calls=agent.step({},'history',{'company':'a'})
        with self.assertRaises(HTTPException):agent.step({'calls':calls},'history',{'company':'a'})
        with self.assertRaises(HTTPException):agent.step({'calls':['a']*6},'history',{'company':'b'})

    def test_multifield_and_multiline_explicit_values(self):
        text='Supplier se 5 Cement bags rate 350, aur 2 Sand kg rate 40'
        updates=[dict(path='party_name',value='Supplier',quote='Supplier'),dict(path='lines.0.item_name',value='Cement',quote='Cement'),
                 dict(path='lines.0.quantity',value='5',quote='5 Cement'),dict(path='lines.0.rate',value='350',quote='rate 350'),
                 dict(path='lines.1.item_name',value='Sand',quote='Sand'),dict(path='lines.1.quantity',value='2',quote='2 Sand')]
        grounded=message.grounded(text,message.MessageFields(updates=updates,unsupported_reason=None))
        result=agent.apply_updates({'lines':[{}]},grounded)
        self.assertEqual(len(result['lines']),2);self.assertEqual(result['lines'][0]['rate'],'350')

    def test_hallucinated_names_numbers_paths_and_source_rejected(self):
        for change in [dict(path='lines.0.rate',value='999',quote='350'),dict(path='party_name',value='Different',quote='Supplier'),
                       dict(path='organization_id',value='x',quote='Supplier'),dict(path='entry_date',value='2026-10-01',quote='Supplier'),
                       dict(path='invoice_number',value='INV-1',quote='not in message')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                message.grounded('Supplier rate 350',message.MessageFields(updates=[change],unsupported_reason=None))


class Durable(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.Durable.asyncSetUp
    asyncTearDown=fixture.Durable.asyncTearDown

    async def create(self):
        return await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,
            content={'party_name':'Supplier','lines':[{'item_name':'Cement','quantity':'5','unit':'bags'}]}))

    async def test_explicit_current_rate_does_not_require_historical_prices(self):
        row=await self.create()
        draft=await drafts.scoped_draft(self.db,self.principal,row['id'])
        draft.content={**draft.content,'lines':[{**draft.content['lines'][0],'rate':'350'}]}
        draft.extraction_metadata={'agent_provenance':{'lines.0.rate':{'status':'explicit','source_type':'user_message','value':'350'}}}
        await self.db.commit()
        with patch.object(native,'enqueue',new=AsyncMock()) as queued:
            context=await native.context(self.db,self.principal,draft)
        self.assertEqual(context['status'],'ready')
        self.assertEqual(context['history_status'],'not_required')
        self.assertIsNone(context['history_complete'])
        self.assertEqual(context['suggestions'],[])
        self.assertIn('rate_context',context)
        queued.assert_not_awaited()
        action=SimpleNamespace(company_id=self.company.id,organization_id=self.org,
            preconditions={'purchase_agent':{'draft_id':draft.id,'revision':draft.revision,
                'cache_id':None,'rate_context':context['rate_context']}})
        await native.guard_action(self.db,action)
        action.preconditions['purchase_agent']['rate_context']['binding']['supplier']='changed-master'
        with self.assertRaises(TallyError):await native.guard_action(self.db,action)
        draft.extraction_metadata={}
        await self.db.commit()
        context=await native.context(self.db,self.principal,draft)
        self.assertNotEqual(context.get('history_status'),'not_required')

    async def test_old_revision_and_missing_context_cannot_authorise_action(self):
        row=await self.create()
        action=SimpleNamespace(company_id=self.company.id,organization_id=self.org,
            preconditions={'purchase_agent':dict(draft_id=row['id'],revision=99,cache_id=None,generation=None)})
        with self.assertRaises(TallyError):await native.guard_action(self.db,action)
        action.preconditions['purchase_agent'].update(revision=row['revision'],cache_id='missing')
        with self.assertRaises(TallyError):await native.guard_action(self.db,action)

    async def test_checkpoints_grouped_issues_atomic_idempotent_corrections(self):
        row=await self.create();before=row['revision']
        with patch.object(native,'context',AsyncMock(return_value={'status':'ready','suggestions':[],'evidence_version':'native-v1'})):
            result=await agent.state(self.db,self.principal,row['id'])
            self.assertIn('proposal',result)
            self.assertGreater(len(result['issues']),1)
            count=await self.db.scalar(select(func.count()).select_from(PurchaseGraphCheckpoint))
            self.assertGreater(count,1)
            updates=[dict(path='lines.0.rate',value='350',quote='350'),dict(path='invoice_number',value='CHAT-1',quote='CHAT-1')]
            req=Reply(expected_revision=before,request_id=uuid.uuid4().hex,message='rate 350 bill CHAT-1')
            with patch.object(message,'extract',AsyncMock(return_value=updates)):
                saved=await agent.answer(self.db,self.principal,row['id'],req)
                again=await agent.answer(self.db,self.principal,row['id'],req)
            content=(await drafts.read_draft(self.db,self.principal,row['id']))['content']
            self.assertEqual(content['lines'][0]['rate'],'350');self.assertEqual(content['invoice_number'],'CHAT-1')
            self.assertEqual(saved['proposal']['revision'],again['proposal']['revision'])
            with self.assertRaises(HTTPException):await agent.answer(self.db,self.principal,row['id'],req.model_copy(update={'message':'different'}))

    async def test_scope_and_no_guess_without_source(self):
        row=await self.create()
        other=SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'})
        with self.assertRaises(HTTPException):await agent.state(self.db,other,row['id'])
        with patch.object(native,'context',AsyncMock(return_value={'status':'error','suggestions':[],'reason':'offline'})):
            result=await agent.state(self.db,self.principal,row['id'])
        self.assertFalse(result['proposal']['can_prepare_preview'])
        self.assertIsNone(result['proposal']['content']['invoice_number'])
        self.assertIsNone(result['proposal']['content']['lines'][0]['rate'])

    async def test_native_worker_publishes_complete_capture_and_stale_cache_abstains(self):
        import hashlib
        from datetime import timedelta
        row=await self.create();draft=await drafts.scoped_draft(self.db,self.principal,row['id'])
        context=await native.context(self.db,self.principal,draft)
        self.assertEqual(context['status'],'queued')
        cache=await self.db.get(PurchaseHistoryCache,context['cache_id'],populate_existing=True)
        cat=fixture.catalog();records,issues=history.normalise_vouchers([voucher()],cat,cache.query)
        self.assertFalse(issues)
        binding={'company':self.company.name,'identity':self.company.identity,'query':history.digest_query(cache.query)}
        manifest={**binding,'generation':'a'*32,'hashes':[hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()],
                  'complete':True,'count':len(records),'collected_at':sync.now().isoformat()}
        async def operation(db,company,kind,**kwargs):
            return {**binding,'generation':'a'*32,'page':0,'records':records} if 'page' in kwargs else manifest
        with patch.object(sync,'refresh_company',AsyncMock(return_value=True)),patch.object(sync,'operation',side_effect=operation):
            await native.refresh_purchase_history({},cache.id)
        await self.db.refresh(cache)
        self.assertEqual(cache.status,'ready',cache.error)
        context=await native.context(self.db,self.principal,draft)
        self.assertEqual(context['suggestions'][0]['value'],'350')
        self.assertIsNone(draft.content['lines'][0]['rate'])
        cache.collected_at=sync.now()-timedelta(minutes=16);await self.db.commit()
        context=await native.context(self.db,self.principal,draft)
        self.assertEqual(context['suggestions'],[])
        self.assertEqual(context['status'],'queued')

    async def test_native_worker_retries_transient_once_and_permission_change_stops_reads(self):
        from app.models.organization_membership import OrganizationMembership
        row=await self.create();draft=await drafts.scoped_draft(self.db,self.principal,row['id'])
        context=await native.context(self.db,self.principal,draft);key=context['cache_id']
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('Helper offline'))):
            await native.refresh_purchase_history({},key)
            cache=await self.db.get(PurchaseHistoryCache,key,populate_existing=True)
            self.assertEqual(cache.status,'queued');self.assertEqual(cache.attempts,1)
            await native.refresh_purchase_history({},key)
            await self.db.refresh(cache);self.assertEqual(cache.status,'error');self.assertEqual(cache.attempts,2)
        cache.status='queued';cache.attempts=0;await self.db.commit()
        member=await self.db.get(OrganizationMembership,(self.user,self.org));member.status='inactive';await self.db.commit()
        with patch.object(sync,'operation',AsyncMock()) as operation:
            await native.refresh_purchase_history({},key)
            self.assertEqual(operation.await_count,0)
        await self.db.refresh(cache);self.assertEqual(cache.status,'error')

    async def test_checkpoint_restart_resumes_pending_node(self):
        from langgraph.graph import StateGraph,END
        from typing import TypedDict
        from app.services.purchase_checkpoint import PurchaseSaver
        from app.database.session import AsyncSessionLocal
        class S(TypedDict):
            value:str
        calls=[];fail=[True]
        async def first(s):calls.append('first');return {'value':'prepared'}
        async def second(s):
            calls.append('second')
            if fail[0]:raise TallyError('Synthetic interrupted read')
            return {'value':'finished'}
        def build():
            g=StateGraph(S);g.add_node('first',first);g.add_node('second',second)
            g.set_entry_point('first');g.add_edge('first','second');g.add_edge('second',END)
            return g.compile(checkpointer=PurchaseSaver(AsyncSessionLocal))
        config={'configurable':{'thread_id':'test-resume-'+uuid.uuid4().hex}}
        with self.assertRaises(TallyError):await build().ainvoke({'value':'start'},config=config,durability='sync')
        fail[0]=False
        resumed=await build().ainvoke(None,config=config,durability='sync')
        self.assertEqual(resumed['value'],'finished');self.assertEqual(calls.count('first'),1)


if __name__=='__main__':unittest.main()
