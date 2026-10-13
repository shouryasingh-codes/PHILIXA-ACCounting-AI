"""Synthetic GST master/native-shaped voucher fixtures. Never real tax/Tally writes."""
import asyncio
import copy
import os
import tempfile
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from xml.etree import ElementTree as ET
from sqlalchemy import select
from fastapi import HTTPException
from app.services import tally_gst_purchase as gst,purchase_draft_service as drafts,purchase_tax_service as service,tally_sync as sync
from app.services.tally_connector import TallyError,TallyRejected,tag,name,parse_xml
from app.services.tally_sync_protocol import serialize_catalog,deserialize_catalog
from app.models.tally import TallySnapshot,TallyAction
import scripts.test_tally_sync as fixtures

def gstin(state,pan='ABCPE1234F'):
    raw=state+pan+'1Z';alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';factor=2;total=0
    for char in reversed(raw):
        n=alphabet.index(char)*factor;total+=n//36+n%36;factor=1 if factor==2 else 2
    return raw+alphabet[(36-total%36)%36]

def node(kind,label,**fields):
    row=ET.Element(kind,NAME=label)
    for key,text in fields.items():tag(row,key,text)
    return row

def details(row,rate,when='20260401'):
    d=tag(row,'GSTDETAILS.LIST');tag(d,'APPLICABLEFROM',when);tag(d,'TAXABILITY','Taxable');tag(d,'ISREVERSECHARGEAPPLICABLE','No');tag(d,'SUPPLYTYPE','Goods');tag(d,'HSNCODE','2523')
    state=tag(d,'STATEWISEDETAILS.LIST');tag(state,'STATENAME','Any')
    for head,amount in [('CGST',Decimal(rate)/2),('SGST',Decimal(rate)/2),('IGST',rate)]:
        r=tag(state,'RATEDETAILS.LIST');tag(r,'GSTRATEDUTYHEAD',head);tag(r,'GSTRATE',amount);tag(r,'GSTRATEVALUATIONTYPE','Based on Value')
    return d

def catalog(inter=False):
    company=node('COMPANY','Pilot Test',GUID='identity',ISGSTON='Yes',GSTREGISTRATIONTYPE='Regular',GSTIN=gstin('06'))
    party=node('LEDGER','Supplier',GUID='party',PARENT='Sundry Creditors',GSTREGISTRATIONTYPE='Regular',PARTYGSTIN=gstin('07' if inter else '06','ABCPF1234G'),ISCOSTCENTRESON='No')
    purchase=node('LEDGER','Purchase',GUID='purchase',PARENT='Purchase Accounts',ISCOSTCENTRESON='No')
    items=[]
    for label,rate in [('Cement','18'),('Other goods','5')]:
        item=node('STOCKITEM',label,GUID=label,PARENT='Primary',BASEUNITS='bags',ADDITIONALUNITS='',ISBATCHWISEON='No',CLOSINGBALANCE='20 bags',GSTTYPEOFSUPPLY='Goods');details(item,rate);items.append(item)
    ledgers=[party,purchase,node('LEDGER','Round Off',PARENT='Indirect Expenses',GSTAPPLICABLE='Not Applicable',ISCOSTCENTRESON='No')]
    ledgers.extend(node('LEDGER','Input '+h,GUID=h,PARENT='Duties & Taxes',TAXTYPE='GST',GSTDUTYHEAD=h,ISCOSTCENTRESON='No') for h in gst.HEADS)
    return {'non_gst':False,'cost_centres_enabled':False,'companies':[company],'stock_groups':[],
        'groups':[node('GROUP','Purchase Accounts',PARENT='Primary')],'items':items,'ledgers':ledgers,
        'godowns':[node('GODOWN','Main Location')],'units':[node('UNIT','bags',ISSIMPLEUNIT='Yes',DECIMALPLACES='0',GSTREPUOM='BAG-BAGS')]}

def config():return {'company':'Pilot Test','godown':'Main Location','purchase_ledger':'Purchase','sales_ledger':'Sales','test_company':True}
def profile():return {'ledgers':{h:'Input '+h for h in gst.HEADS},'rounding_ledger':'Round Off'}
def content(inter=False,header='0',roundoff='0'):
    header=Decimal(header);net=Decimal('1000')-header
    taxes=Decimal('167') if not header else Decimal('150.30')
    return {'tax_treatment':'regular_domestic_goods','party_name':'Supplier','supplier_gstin':gstin('07' if inter else '06','ABCPF1234G'),
        'place_of_supply':'06','entry_date':'2026-10-01','invoice_number':'GST-TEST-1','invoice_discount':str(header),'round_off':roundoff,
        'invoice_total':str(net+taxes+Decimal(roundoff)),
        'expected_taxes':{'IGST':str(taxes)} if inter else {'CGST':str(taxes/2),'SGST':str(taxes/2)},
        'lines':[{'item_name':'Cement','unit':'bags','quantity':'10','rate':'100','discount_percent':'10','gst_rate':'18','hsn':'2523','taxable_amount':'810' if header else '900'},
            {'item_name':'Other goods','unit':'bags','quantity':'1','rate':'100','gst_rate':'5','hsn':'2523','taxable_amount':'90' if header else '100'}]}

class Arithmetic(unittest.TestCase):
    def compile(self,inter=False,**kwargs):return gst.compile_purchase(catalog(inter),content(inter,**kwargs),profile(),config(),str(uuid.uuid4()))
    def test_intra_inter_mixed_rates_discount_and_disclosed_roundoff(self):
        for inter in (False,True):
            p=self.compile(inter,header='100',roundoff='-.30')
            self.assertEqual(p['total'],'1050.00');self.assertEqual(p['taxable_total'],'900.00')
            self.assertEqual([x['discount'] for x in p['items']],['190.00','10.00'])
            self.assertEqual([x['amount'] for x in p['tax_ledgers']],['150.30'] if inter else ['75.15','75.15'])
            gst.validate(catalog(inter),p,config())
    def test_roundoff_bounds_and_missing_ledger_no_auto_adjustment(self):
        for amount in ('1.01','-1.01'):
            with self.assertRaises(TallyError):self.compile(roundoff=amount)
        c=content(roundoff='1');pr=profile();pr['rounding_ledger']=None
        with self.assertRaises(TallyError):gst.compile_purchase(catalog(),c,pr,config(),str(uuid.uuid4()))
        c=content();c['invoice_total']='1168'
        with self.assertRaisesRegex(TallyError,'grand total'):gst.compile_purchase(catalog(),c,profile(),config(),str(uuid.uuid4()))
    def test_effective_rate_change_and_group_inheritance(self):
        cat=catalog();item=cat['items'][0]
        item.remove(item.find('GSTDETAILS.LIST'));item.find('PARENT').text='Goods group'
        group=node('STOCKGROUP','Goods group',PARENT='Primary');details(group,'18');details(group,'40','20261101');cat['stock_groups']=[group]
        p=gst.compile_purchase(cat,content(),profile(),config(),str(uuid.uuid4()));self.assertEqual(p['items'][0]['gst_source'],'Goods group')
        # Duplicate effective definitions are ambiguous rather than first-match wins.
        details(group,'5')
        with self.assertRaises(TallyError):gst.compile_purchase(cat,content(),profile(),config(),str(uuid.uuid4()))
    def test_missing_and_unsupported_masters_invoice_evidence_block(self):
        cases=[]
        for mutate in (
            lambda c,x:x.update(supplier_gstin=gstin('08')),
            lambda c,x:x.update(place_of_supply='07'),
            lambda c,x:x.update(unsupported_treatments=['reverse_charge']),
            lambda c,x:x.update(expected_taxes={'CGST':'99','SGST':'99'}),
            lambda c,x:x['lines'][0].update(gst_rate='5'),
            lambda c,x:x['lines'][0].update(hsn=None),
            lambda c,x:c['items'][0].find('GSTDETAILS.LIST/ISREVERSECHARGEAPPLICABLE').__setattr__('text','Yes'),
            lambda c,x:c['items'][0].find('GSTDETAILS.LIST/SUPPLYTYPE').__setattr__('text','Services'),
            lambda c,x:c['ledgers'][0].find('GSTREGISTRATIONTYPE').__setattr__('text','Composition'),
            lambda c,x:c.update(companies=[]),
        ):
            cat=catalog();doc=content();mutate(cat,doc)
            with self.assertRaises(TallyError):gst.compile_purchase(cat,doc,profile(),config(),str(uuid.uuid4()))
    def test_paisa_and_proportional_discount_determinism(self):
        self.assertEqual(gst.money('1.005'),Decimal('1.01'));self.assertEqual(gst.money('-1.005'),Decimal('-1.01'))
        p=self.compile();cat=catalog();cat['items'][0].find('CLOSINGBALANCE').text='99 bags'
        gst.validate(cat,p,config())
        cat['items'][0].find('GSTDETAILS.LIST/STATEWISEDETAILS.LIST/RATEDETAILS.LIST/GSTRATE').text='5'
        with self.assertRaises(TallyError):gst.validate(cat,p,config())

    def test_tax_unit_history_hsn_history_and_utgst(self):
        cat=catalog();unit=node('TAXUNIT','GST Registration',GSTREGNUMBER=gstin('06'))
        r=tag(unit,'GSTREGISTRATIONDETAILS.LIST');tag(r,'FROMDATE','20260401');tag(r,'REGISTRATIONTYPE','Regular')
        cat['tax_units']=[unit]
        item=cat['items'][0];item.find('GSTDETAILS.LIST/HSNCODE').text=''
        hsn=tag(item,'HSNDETAILS.LIST');tag(hsn,'APPLICABLEFROM','20260401');tag(hsn,'HSNCODE','2523')
        p=gst.compile_purchase(cat,content(),profile(),config(),str(uuid.uuid4()));self.assertEqual(p['company_gstin'],gstin('06'))
        cat=catalog();cat['companies'][0].find('GSTIN').text=gstin('04');cat['ledgers'][0].find('PARTYGSTIN').text=gstin('04','ABCPF1234G')
        c=content();c['supplier_gstin']=gstin('04','ABCPF1234G');c['place_of_supply']='04';c['expected_taxes']={'CGST':'83.50','UTGST':'83.50'}
        p=gst.compile_purchase(cat,c,profile(),config(),str(uuid.uuid4()));self.assertEqual([r['head'] for r in p['tax_ledgers']],['CGST','UTGST'])

class NativeShape(unittest.IsolatedAsyncioTestCase):
    async def test_tax_ledger_wise_verification_mutations_and_no_duplicate_write(self):
        cat=catalog();p=gst.compile_purchase(cat,content(),profile(),config(),str(uuid.uuid4()))
        vouchers=[];posts=[]
        async def post(xml):
            posts.append(xml);v=parse_xml(xml.encode()).find('.//VOUCHER');tag(v,'VOUCHERNUMBER','GST-1');vouchers.append(v)
        connector=SimpleNamespace(catalog=AsyncMock(return_value=cat),collection=AsyncMock(side_effect=lambda *args:vouchers),post=post)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'0'}):
                result=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',p,config(),tmp+'/journal');self.assertEqual(result['status'],'needs_review');self.assertEqual(posts,[])
            with patch.dict(os.environ,{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'1'}):
                first=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',p,config(),tmp+'/journal');self.assertEqual(first['status'],'verified')
                again=await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',p,config(),tmp+'/journal');self.assertEqual(again['status'],'verified');self.assertEqual(len(posts),1)
            original=vouchers[0]
            self.assertTrue(gst.verify(original,p))
            for path,new in [('LEDGERENTRIES.LIST[2]/AMOUNT','-99'),('REFERENCE','different'),('PARTYGSTIN',gstin('08')),('ALLINVENTORYENTRIES.LIST/AMOUNT','-999'),('ALLINVENTORYENTRIES.LIST/BATCHALLOCATIONS.LIST/ACTUALQTY','2 bags'),('ALLINVENTORYENTRIES.LIST/DISCOUNT','1'),('ALLINVENTORYENTRIES.LIST/RATEDETAILS.LIST/GSTRATE','1'),('CMPGSTIN',gstin('07'))]:
                altered=copy.deepcopy(original);altered.find(path).text=new;self.assertFalse(gst.verify(altered,p),path)

    async def test_unknown_delivery_is_reconciled_without_resend(self):
        cat=catalog();p=gst.compile_purchase(cat,content(),profile(),config(),str(uuid.uuid4()))
        connector=SimpleNamespace(catalog=AsyncMock(return_value=cat),collection=AsyncMock(return_value=[]),post=AsyncMock(side_effect=TallyError('timeout')))
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'1'}):
            for _ in range(2):self.assertEqual((await gst.execute('purchase_gst_post',connector,'Pilot Test','identity',p,config(),tmp+'/journal'))['status'],'verification_pending')
            self.assertEqual(connector.post.await_count,1)

class Durable(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.catalog=serialize_catalog(catalog());await self.db.commit()
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    async def test_scoped_profile_revision_preview_locked_and_tax_check(self):
        saved=await service.save_profile(self.db,self.principal,self.company.id,service.TaxProfileSave(revision=0,**profile()))
        self.assertEqual(saved['revision'],1)
        with self.assertRaises(HTTPException):await service.save_profile(self.db,self.principal,self.company.id,service.TaxProfileSave(revision=0,**profile()))
        other=SimpleNamespace(**{**self.principal.__dict__,'organization_id':'other'})
        with self.assertRaises(HTTPException):await service.profile_view(self.db,other,self.company.id)
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content=content()))
        check=await service.tax_check(self.db,self.principal,draft['id']);self.assertEqual(check['total'],'1167.00')
        with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),patch.dict(os.environ,{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'0'}):
            preview=await drafts.preview_draft(self.db,self.principal,draft['id'],drafts.DraftPreview(revision=0))
            self.assertFalse(preview['preview']['can_confirm'])
            action=await self.db.get(TallyAction,preview['preview']['token']);self.assertEqual(action.schema_version,3)
            with self.assertRaises(HTTPException):await sync.confirm_queued(self.db,self.principal,action)
            self.assertEqual(action.status,'preview')
        await service.save_profile(self.db,self.principal,self.company.id,service.TaxProfileSave(revision=1,**profile()))
        with self.assertRaises(TallyError):await service.ensure_approved_profile(self.db,action)

class BridgeV8(Durable):
    async def test_legacy_helper_cannot_consume_gst_job(self):
        from redis.asyncio import Redis
        from app.core.config import get_settings
        from app.models.tally import TallyDevice
        from app.services import tally_bridge as bridge
        from app.api.v1 import routes_tally_bridge as routes
        import json
        async def redis_client():return Redis.from_url(get_settings().redis_url,decode_responses=True)
        device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='synthetic-v8',revoked=False)
        self.db.add(device);self.company.device_id=device.id
        snapshot=await self.db.get(TallySnapshot,self.company.id);snapshot.device_version=device.credential_hash;await self.db.commit()
        await service.save_profile(self.db,self.principal,self.company.id,service.TaxProfileSave(revision=0,**profile()))
        draft=await drafts.create_draft(self.db,self.principal,drafts.DraftCreate(company_id=self.company.id,content=content()))
        redis=await redis_client();pending=None
        with patch.dict(os.environ,{'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED':'1'}),patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('offline'))),patch.object(bridge,'get_redis_client',redis_client),patch.object(routes,'get_redis_client',redis_client):
            try:
                preview=await drafts.preview_draft(self.db,self.principal,draft['id'],drafts.DraftPreview(revision=0))
                action=await self.db.get(TallyAction,preview['preview']['token']);await sync.confirm_queued(self.db,self.principal,action)
                await routes.jobs(7,device,self.db)
                with self.assertRaises(TallyError):await bridge.request_job(device,'purchase_gst_validate',company='Pilot Test',identity='identity',payload=action.payload,config=config(),action_id=action.token)
                await routes.jobs(8,device,self.db)
                pending=asyncio.create_task(bridge.request_job(device,'purchase_gst_validate',company='Pilot Test',identity='identity',payload=action.payload,config=config(),action_id=action.token))
                wire=await redis.blpop('tally:queue:v8:'+device.id,timeout=2);self.assertIsNotNone(wire)
                await redis.lpush('tally:queue:v8:'+device.id,wire[1])
                self.assertIsNone((await routes.jobs(7,device,self.db))['job'])
                job=(await routes.jobs(8,device,self.db))['job'];self.assertEqual(job['operation'],'purchase_gst_validate')
                await bridge.consume_result(redis,device,job['id'],{'data':{'status':'ready'}})
                self.assertEqual((await pending)['status'],'ready')
            finally:
                if pending and not pending.done():pending.cancel();await asyncio.gather(pending,return_exceptions=True)
                await redis.delete(*['tally:'+key+':'+device.id for key in ('online','protocol','v2online','v3online','v4online','v5online','v6online','v7online','v8online','queue:v8')]);await redis.aclose()

if __name__=='__main__':unittest.main()
