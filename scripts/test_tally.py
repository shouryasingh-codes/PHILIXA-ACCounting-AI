"""Synthetic fixtures and real PostgreSQL approval tests; never contacts real Tally."""
import asyncio
import copy
import uuid
import unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete
from app.api.v1.routes_business import ParsedCommand,CommandFields,CommandRequest,guard_tally_scope
from app.models.organization import Organization
from app.models.tally import TallyConnection,TallyAction
from app.database.session import AsyncSessionLocal,async_engine
from app.services import tally_business as business
from app.services.tally_connector import TallyConnector,TallyError,TallyRejected,parse_xml,verify_voucher,voucher_xml,stock_quantity
from app.api.v1 import routes_tally


def node(kind,title,**fields):
    result=ET.Element(kind,NAME=title)
    for key,text in fields.items():
        ET.SubElement(result,key).text=str(text)
    return result


class FakeTally:
    def __init__(self):
        self.balance=20
        self.posts=0
        self.vouchers=[]
        self.mode='normal'
        self.entered=asyncio.Event()
    async def catalog(self,company):
        if company!='Pilot Test':raise TallyError('Wrong company')
        return {'non_gst':True,
            'items':[node('STOCKITEM','Cement',BASEUNITS='bags',ISBATCHWISEON='No',CLOSINGBALANCE=f'{self.balance} bags')],
            'units':[node('UNIT','bags',ISSIMPLEUNIT='Yes',DECIMALPLACES='0')],
            'godowns':[node('GODOWN','Main Location')],
            'ledgers':[node('LEDGER','Supplier',PARENT='Sundry Creditors'),node('LEDGER','Customer',PARENT='Sundry Debtors'),
                       node('LEDGER','Purchase',PARENT='Purchase Accounts'),node('LEDGER','Sales',PARENT='Sales Accounts')]}
    async def collection(self,kind,company=None,voucher_date=None):
        if kind=='Voucher':return self.vouchers
        if kind=='StockItem':return (await self.catalog(company))['items']
        return []
    async def post(self,xml):
        self.posts+=1
        self.entered.set()
        await asyncio.sleep(.15)
        if self.mode=='reject':raise TallyRejected('Voucher totals do not match')
        if self.mode=='pending':raise TallyError('Timeout')
        voucher=ET.fromstring(xml).find('.//VOUCHER')
        ET.SubElement(voucher,'VOUCHERNUMBER').text=str(self.posts)
        self.vouchers.append(voucher)
        qty=int(voucher.findtext('.//ACTUALQTY').split()[0])
        self.balance+=qty if voucher.findtext('VOUCHERTYPENAME')=='Purchase' else -qty
        if self.mode=='timeout_after_save':raise TallyError('Timeout after save')
        return ET.fromstring('<RESPONSE><CREATED>1</CREATED><ERRORS>0</ERRORS></RESPONSE>')


class XmlTests(unittest.TestCase):
    def test_explicit_numeric_stock_balance(self):
        for amount in ('0','10','-2','1.25'):
            item=node('STOCKITEM','Cement',BASEUNITS='bags',PHILIXACLOSINGQTY=amount)
            self.assertEqual(str(stock_quantity(item,'bags')),amount)
        with self.assertRaises(TallyError):stock_quantity(item,'kg')
        with self.assertRaises(TallyError):stock_quantity(node('STOCKITEM','Cement',BASEUNITS='bags'),'bags')
        with self.assertRaises(TallyError):stock_quantity(node('STOCKITEM','Cement',BASEUNITS='bags',PHILIXACLOSINGQTY='NaN'),'bags')
    def test_cost_centres_require_company_feature(self):
        ledger=node('LEDGER','Purchases',ISCOSTCENTRESON='Yes')
        self.assertFalse(business.uses_cost_centres({'cost_centres_enabled':False},ledger))
        self.assertTrue(business.uses_cost_centres({'cost_centres_enabled':True},ledger))
        self.assertTrue(business.uses_cost_centres({},ledger))
    def test_collection_ignores_unnamed_master_metadata(self):
        response=ET.fromstring('<ENVELOPE><DESC><GODOWN/></DESC><COLLECTION><GODOWN NAME="Main Location"/></COLLECTION></ENVELOPE>')
        with patch.object(TallyConnector,'post',new=AsyncMock(return_value=response)):
            rows=asyncio.run(TallyConnector().collection('Godown','Pilot Test'))
        self.assertEqual([row.get('NAME') for row in rows],['Main Location'])
        # Voucher exports need not have a NAME attribute.
        response=ET.fromstring('<ENVELOPE><COLLECTION><VOUCHER><GUID>test</GUID></VOUCHER></COLLECTION></ENVELOPE>')
        with patch.object(TallyConnector,'post',new=AsyncMock(return_value=response)):
            self.assertEqual(len(asyncio.run(TallyConnector().collection('Voucher','Pilot Test'))),1)
    def test_reject_unsafe_and_errors(self):
        for xml in (b'<!DOCTYPE X><X/>',b'<broken',b'<ENVELOPE><HEADER><STATUS>0</STATUS></HEADER></ENVELOPE>'):
            with self.assertRaises(TallyError):parse_xml(xml)
        with self.assertRaises(TallyError):parse_xml('<!DOCTYPE X><X/>'.encode('utf-16'))
        with self.assertRaises(TallyRejected):
            parse_xml(b'<RESPONSE><CREATED>0</CREATED><ALTERED>0</ALTERED><LINEERROR>bad</LINEERROR></RESPONSE>')
    def test_field_validation(self):
        for fields in ({'quantity':0},{'quantity':-1},{'rate':'NaN'},{'rate':'1.001'},{'quantity':'1e99'}):
            with self.assertRaises(ValidationError):CommandFields(**fields)
        with self.assertRaises(ValidationError):CommandFields(tax='18%')
    def test_scope_guard_does_not_trust_model(self):
        for text in ('GST ke saath entry karo','10 Cement bags aur 2 Steel rods kharide','serial number ke saath sale karo'):
            result=guard_tally_scope(CommandRequest(text=text),ParsedCommand(intent='purchase_create'))
            self.assertTrue(result.unsupported_reason)
        result=guard_tally_scope(CommandRequest(text='10 bags 350 per bag',conversation_history=[{'role':'user','content':'GST ke saath purchase entry karo'}]),ParsedCommand(intent='purchase_create'))
        self.assertTrue(result.unsupported_reason)
    def test_xml_escaping_and_mismatch(self):
        p={'company':'A & B','date':'2026-10-08','guid':str(uuid.uuid4()),'voucher_type':'Sales',
           'party':'Party <test>','item':'Cement','godown':'Main Location','quantity':'10','unit':'bags',
           'rate':'350','total':'3500.00','ledger':'Sales'}
        voucher=ET.fromstring(voucher_xml(p)).find('.//VOUCHER')
        self.assertTrue(verify_voucher(voucher,p))
        for path,text in (('DATE','20260101'),('.//RATE','351/bags'),('.//GODOWNNAME','Other'),('.//ACTUALQTY','11 bags'),('.//LEDGERNAME','Other')):
            modified=copy.deepcopy(voucher);modified.find(path).text=text
            self.assertFalse(verify_voucher(modified,p),path)
    def test_local_endpoint_only(self):
        with patch.dict('os.environ',{'PHILIXA_TALLY_HOST':'example.com'}):
            with self.assertRaises(TallyError):TallyConnector()


async def integration():
    org='tally-test-'+uuid.uuid4().hex
    principal=SimpleNamespace(organization_id=org,user_id='test-user',session_id='test-session',role='owner')
    fake=FakeTally()
    async with AsyncSessionLocal() as db:
        db.add(Organization(id=org,name='Tally isolated test',slug=org,workspace_type='company',plan='free',is_active=True))
        await db.commit()
        db.add(TallyConnection(organization_id=org,company='Pilot Test',godown='Main Location',purchase_ledger='Purchase',sales_ledger='Sales',test_company=True))
        await db.commit()
    async def preview(intent='purchase_create',**fields):
        command=ParsedCommand(intent=intent,item_name='Cement',party_name='Supplier' if intent=='purchase_create' else 'Customer',
                              quantity='10',rate='350',unit='bags',**fields)
        async with AsyncSessionLocal() as db:
            return await business.handle_command(db,principal,command)
    async def confirm(token,approve=True,who=principal,status_only=False):
        async with AsyncSessionLocal() as db:
            return await business.confirm_action(db,who,token,approve,status_only)
    try:
      with patch.object(business,'TallyConnector',return_value=fake):
        async with AsyncSessionLocal() as db:
            assert (await routes_tally.status(principal,db))['configured']
            outsider=SimpleNamespace(**{**vars(principal),'organization_id':'wrong'})
            assert not (await routes_tally.status(outsider,db))['configured']
            try:await routes_tally.test(routes_tally.ProbeRequest(),SimpleNamespace(**{**vars(principal),'role':'member'}))
            except HTTPException as exc:assert exc.status_code==403
            else:raise AssertionError('Member must not configure')
            missing=await business.handle_command(db,principal,ParsedCommand(intent='purchase_create',item_name='Cement'))
            assert missing['tally_form'] and fake.posts==0
            invalid=await business.handle_command(db,principal,ParsedCommand(intent='purchase_create',item_name='Cement',party_name='Supplier',quantity='1',rate='350',unit='kg'))
            assert 'preview' not in invalid
            fractional=await business.handle_command(db,principal,ParsedCommand(intent='purchase_create',item_name='Cement',party_name='Supplier',quantity='1.5',rate='350',unit='bags'))
            assert 'preview' not in fractional
            unsupported=await business.handle_command(db,principal,ParsedCommand(intent='purchase_create',unsupported_reason='GST invoice'))
            assert 'preview' not in unsupported
            for change in ('gst','batch','godown'):
                catalog=await fake.catalog('Pilot Test')
                if change=='gst':catalog['non_gst']=False
                if change=='batch':catalog['items'][0].find('ISBATCHWISEON').text='Yes'
                if change=='godown':catalog['godowns'].append(node('GODOWN','Other'))
                with patch.object(fake,'catalog',new=AsyncMock(return_value=catalog)):
                    blocked=await business.handle_command(db,principal,ParsedCommand(intent='purchase_create',item_name='Cement',party_name='Supplier',quantity='1',rate='350',unit='bags'))
                    assert 'preview' not in blocked,change
            catalog=await fake.catalog('Pilot Test');catalog['items'].append(node('STOCKITEM','Cement White'))
            with patch.object(fake,'catalog',new=AsyncMock(return_value=catalog)):
                choice=await business.handle_command(db,principal,ParsedCommand(intent='stock_read',item_name='Cem'))
                assert len(choice['tally_choices'])==2
        print('PASS: missing details, ambiguous names, invalid unit/precision, GST/batch/godown rejection and configuration permissions')
        first=await preview();token=first['preview']['token'];assert fake.posts==0
        for change in ({'organization_id':'wrong'},{'session_id':'wrong'},{'user_id':'wrong'}):
            who=SimpleNamespace(**{**vars(principal),**change})
            try:await confirm(token,who=who)
            except HTTPException as exc:assert exc.status_code==410
            else:raise AssertionError('Scope must reject')
        try:await confirm(token,who=SimpleNamespace(**{**vars(principal),'role':'member'}))
        except HTTPException as exc:assert exc.status_code==403
        else:raise AssertionError('Member must not write')
        task=asyncio.create_task(confirm(token));await fake.entered.wait()
        try:await confirm(token)
        except HTTPException as exc:assert exc.status_code==409
        else:raise AssertionError('Concurrent write must be blocked')
        result=await task;assert result['tally_status']=='verified' and fake.balance==30
        assert (await confirm(token))==result and fake.posts==1
        sale=await preview('sale_create');await confirm(sale['preview']['token']);assert fake.balance==20 and fake.posts==2
        cancelled=await preview();await confirm(cancelled['preview']['token'],False);assert fake.posts==2
        expired=await preview();token=expired['preview']['token']
        async with AsyncSessionLocal() as db:
            action=await db.get(TallyAction,token);action.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);await db.commit()
        try:await confirm(token)
        except HTTPException as exc:assert exc.status_code==410
        else:raise AssertionError('Expired preview must reject')
        fake.balance=2
        insufficient=await preview('sale_create');assert 'preview' not in insufficient and 'insufficient' in insufficient['response']
        fake.balance=20
        stale=await preview();token=stale['preview']['token']
        async with AsyncSessionLocal() as db:
            cfg=await db.get(TallyConnection,org);cfg.version+=1;await db.commit()
        assert (await confirm(token))['tally_status']=='failed' and fake.posts==2
        fake.mode='timeout_after_save';timed=await preview();token=timed['preview']['token']
        assert (await confirm(token))['tally_status']=='verified';assert fake.posts==3
        fake.mode='pending';pending=await preview();token=pending['preview']['token']
        assert (await confirm(token))['tally_status']=='verification_pending'
        assert (await confirm(token,status_only=True))['tally_status']=='verification_pending';assert fake.posts==4
        fake.mode='reject';rejected=await preview();token=rejected['preview']['token']
        assert (await confirm(token))['tally_status']=='failed';assert fake.posts==5
        # Master/stock revalidation between preview and confirmation.
        fake.mode='normal';stale_stock=await preview('sale_create');fake.balance=0
        assert (await confirm(stale_stock['preview']['token']))['tally_status']=='failed';assert fake.posts==5
        print('PASS: real PostgreSQL approvals, tenant/user/session/role scope, concurrent confirmation, purchase/sale stock effects, cancellation, expiry, stale config/stock, rejection and uncertain import without retries (synthetic Tally)')
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Organization).where(Organization.id==org));await db.commit()
        await async_engine.dispose()


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(XmlTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    asyncio.run(integration())
