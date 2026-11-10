"""Synthetic safety checks only. These do not certify Tally XML acceptance."""
import copy,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from app.services import tally_goods_receipt as receipt,tally_receipt_link as link,tally_gst_purchase as gst
from app.services.tally_connector import TallyError,tag,parse_xml
import scripts.test_gst_purchase as fixture

def payload():
    p={'operation':'goods_receipt','company':'Pilot Test','party':'Supplier','godown':'Main Location','ledger':'Purchase',
        'date':'2026-10-02','guid':str(uuid.uuid4()),'tracking':'PH-GRN-'+uuid.uuid4().hex,
        'items':[{'item':'Cement','quantity':'5','unit':'bags','rate':'350.00'}],'master_fingerprint':''}
    p['master_fingerprint']=receipt.fingerprint(fixture.catalog(),p);return p

class Codec(unittest.TestCase):
    def test_exact_receipt_and_tampering(self):
        p=payload();receipt.validate(fixture.catalog(),p,fixture.config())
        v=ET.fromstring(receipt.receipt_xml(p)).find('.//VOUCHER')
        self.assertTrue(receipt.verify(v,p));self.assertEqual(v.findtext('ISINVOICE'),'No')
        self.assertEqual(v.findall('ALLLEDGERENTRIES.LIST'),[])
        for field,text in [('TRACKINGNUMBER','Other'),('GODOWNNAME','Other'),('ACTUALQTY','6 bags')]:
            changed=copy.deepcopy(v);changed.find('.//BATCHALLOCATIONS.LIST/'+field).text=text
            self.assertFalse(receipt.verify(changed,p))
        changed=copy.deepcopy(v);party=tag(changed,'ALLLEDGERENTRIES.LIST');tag(party,'LEDGERNAME','Input CGST');tag(party,'AMOUNT','1750')
        self.assertFalse(receipt.verify(changed,p),'unexpected tax rows must not be accepted in a receipt')
    def test_configuration_identity_and_precision(self):
        p=payload();cat=fixture.catalog();cat['items'][0].find('BASEUNITS').text='kg'
        with self.assertRaises(TallyError):receipt.validate(cat,p,fixture.config())
        p=payload();p['items'][0]['quantity']='5.5'
        with self.assertRaises(TallyError):receipt.validate(fixture.catalog(),p,fixture.config())
        p=payload();p['items']*=2
        with self.assertRaises(TallyError):receipt.validate(fixture.catalog(),p,fixture.config())
    def test_full_invoice_tracking_preserves_financial_fields(self):
        r=payload();content=fixture.content();p=gst.compile_purchase(fixture.catalog(),content,fixture.profile(),fixture.config(),str(uuid.uuid4()))
        # Receipt covers precisely the approved invoice's lines; rates can differ
        # on the later real invoice, quantities cannot silently change.
        r['items']=[{k:l[k] for k in ('item','quantity','unit','rate')} for l in p['items']]
        r['date']=p['date']
        original=gst.gst_xml(p);linked=link.linked_xml(original,p,r)
        v=parse_xml(linked.encode()).find('.//VOUCHER')
        self.assertTrue(link.verify_tracking(v,p,r));self.assertTrue(gst.verify(v,p))
        for b in v.findall('.//BATCHALLOCATIONS.LIST'):
            self.assertEqual(b.findtext('TRACKINGNUMBER'),r['tracking'])
        bad=copy.deepcopy(p);bad['items'][0]['quantity']='1'
        with self.assertRaises(TallyError):link.linked_xml(original,bad,r)
        bad=copy.deepcopy(p);bad['party']='Other'
        with self.assertRaises(TallyError):link.validate_link(bad,r)

class Protocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'journal.sqlite3';self.p=payload()
        self.rows=[];self.posts=0;self.timeout=False
        owner=self
        class Connector:
            async def catalog(self,*args):return fixture.catalog()
            async def collection(self,kind,*args,**kwargs):
                if kind=='VoucherType':return [fixture.node('VOUCHERTYPE','Receipt Note',ISACTIVE='Yes')]
                return owner.rows
            async def post(self,xml):
                owner.posts+=1
                if owner.timeout:raise TallyError('timeout after uncertain delivery')
                v=ET.fromstring(xml).find('.//VOUCHER');tag(v,'VOUCHERNUMBER','GRN-1');owner.rows.append(v)
        self.connector=Connector()
    async def asyncTearDown(self):self.tmp.cleanup()
    async def run_op(self,operation):return await receipt.execute(operation,self.connector,'Pilot Test','identity',self.p,fixture.config(),self.path)
    async def test_uncertified_never_posts(self):
        with patch.object(receipt,'RECEIPT_CODEC_CERTIFIED',False):
            self.assertEqual((await self.run_op('goods_receipt_post'))['status'],'needs_review');self.assertEqual(self.posts,0)
    async def test_journal_duplicate_and_native_verification(self):
        with patch.object(receipt,'RECEIPT_CODEC_CERTIFIED',True):
            self.assertEqual((await self.run_op('goods_receipt_validate'))['status'],'ready')
            self.assertEqual((await self.run_op('goods_receipt_post'))['status'],'verified')
            self.assertEqual((await self.run_op('goods_receipt_post'))['status'],'verified');self.assertEqual(self.posts,1)
            self.rows[0].find('.//TRACKINGNUMBER').text='wrong'
            self.assertEqual((await self.run_op('goods_receipt_reconcile'))['status'],'needs_review')
    async def test_timeout_never_resends(self):
        self.timeout=True
        with patch.object(receipt,'RECEIPT_CODEC_CERTIFIED',True):
            self.assertEqual((await self.run_op('goods_receipt_post'))['status'],'verification_pending')
            self.assertEqual((await self.run_op('goods_receipt_post'))['status'],'verification_pending')
            self.assertEqual((await self.run_op('goods_receipt_reconcile'))['status'],'verification_pending')
        self.assertEqual(self.posts,1)
    async def test_another_invoice_consuming_tracking_blocks_link(self):
        r=self.p;v=ET.fromstring(receipt.receipt_xml(r)).find('.//VOUCHER');self.rows=[v]
        p={'operation':'purchase_multi','company':r['company'],'party':r['party'],'godown':r['godown'],'date':r['date'],'guid':str(uuid.uuid4()),'items':copy.deepcopy(r['items'])}
        await link.check_outstanding(self.connector,r['company'],p,r)
        used=ET.Element('VOUCHER');tag(used,'GUID','foreign');tag(tag(tag(used,'ALLINVENTORYENTRIES.LIST'),'BATCHALLOCATIONS.LIST'),'TRACKINGNUMBER',r['tracking']);self.rows.append(used)
        with self.assertRaises(TallyError):await link.check_outstanding(self.connector,r['company'],p,r)

if __name__=='__main__':unittest.main()
