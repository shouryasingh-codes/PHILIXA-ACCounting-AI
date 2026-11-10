"""Full tracked-receipt invoice linkage; partial/combined receipts abstain."""
import copy
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError,value,tag,decimal,matches_action
from app.services import tally_goods_receipt as receipts

def validate_link(p,receipt):
    if p.get('operation') not in ('purchase_gst','purchase_multi'):raise TallyError('Unsupported linked invoice codec.')
    if p.get('company')!=receipt.get('company') or p.get('party')!=receipt.get('party') or p.get('godown')!=receipt.get('godown') or p.get('date','')<receipt.get('date',''):
        raise TallyError('Invoice/receipt company, supplier, godown or dates differ.')
    original=receipt.get('items',[]);lines=p.get('items',[])
    if not original or len(original)!=len(lines) or len({l['item'] for l in lines})!=len(lines):raise TallyError('Full receipt only; partial/combined/repeated lines require review.')
    for r in original:
        found=[l for l in lines if l['item']==r['item'] and l['unit']==r['unit']]
        if len(found)!=1 or decimal(found[0]['quantity'])!=decimal(r['quantity']):raise TallyError('Invoice quantity differs; partial receipt linkage unsupported.')

def linked_xml(xml,p,receipt):
    validate_link(p,receipt)
    # Preserve Tally's Not Applicable sentinel used by the GST compiler.
    root=ET.fromstring(xml.replace('&#4;','&amp;#4;'));v=root.find('.//VOUCHER')
    if v is None:raise TallyError('Linked invoice XML missing.')
    lines=v.findall('ALLINVENTORYENTRIES.LIST')
    if len(lines)!=len(p['items']):raise TallyError('Linked invoice lines incomplete.')
    for line in lines:
        batches=line.findall('BATCHALLOCATIONS.LIST')
        if len(batches)!=1:raise TallyError('Single batch allocation required.')
        batch=batches[0]
        for key,val in [('TRACKINGNUMBER',receipt['tracking']),('ORDERNO','Not Applicable')]:
            nodes=batch.findall(key)
            if len(nodes)>1:raise TallyError('Ambiguous tracking XML.')
            if nodes:nodes[0].text=val
            else:tag(batch,key,val)
    return ET.tostring(root,encoding='unicode').replace('&amp;#4;','&#4;')

def verify_tracking(v,p,receipt):
    try:validate_link(p,receipt)
    except (TallyError,KeyError,TypeError):return False
    rows=v.findall('ALLINVENTORYENTRIES.LIST')
    return len(rows)==len(p['items']) and all(len(r.findall('BATCHALLOCATIONS.LIST'))==1 and value(r.find('BATCHALLOCATIONS.LIST'),'TRACKINGNUMBER')==receipt['tracking'] for r in rows)

async def check_outstanding(connector,company,p,receipt):
    validate_link(p,receipt)
    vouchers=await connector.collection('Voucher',company,p['date'],from_date=receipt['date'])
    if len(vouchers)>5000:raise TallyError('Receipt link coverage incomplete.')
    found=[v for v in vouchers if receipts.identity_matches(v,receipt)]
    if len(found)!=1 or not receipts.verify(found[0],receipt):raise TallyError('Original native receipt/tracking could not be verified.')
    for v in vouchers:
        if value(v,'ISCANCELLED').casefold()=='yes' or value(v,'ISOPTIONAL').casefold()=='yes':continue
        if receipts.identity_matches(v,receipt) or matches_action(v,p):continue
        if any(value(b,'TRACKINGNUMBER')==receipt['tracking'] for b in v.findall('.//BATCHALLOCATIONS.LIST')):
            raise TallyError('Receipt already linked, partly billed or returned. Review required; no resend.')

class LinkedConnector:
    def __init__(self,connector,p,receipt):self.connector=connector;self.p=p;self.receipt=receipt
    def __getattr__(self,key):return getattr(self.connector,key)
    async def post(self,xml):
        # Recheck immediately before the existing action-specific journaled post.
        await check_outstanding(self.connector,self.p['company'],self.p,self.receipt)
        return await self.connector.post(linked_xml(xml,self.p,self.receipt))

async def execute(operation,connector,company,identity,p,config,journal_path):
    receipt=copy.deepcopy(config.get('receipt_link'))
    if not isinstance(receipt,dict):raise TallyError('Receipt link proof missing.')
    validate_link(p,receipt)
    reconcile=operation.endswith('_reconcile')
    if not reconcile:
        if not receipts.RECEIPT_CODEC_CERTIFIED:return {'status':'needs_review','uncertain':False,'reason':'Native receipt/invoice linkage acceptance pending.'}
        await check_outstanding(connector,company,p,receipt)
    clean={k:v for k,v in config.items() if k!='receipt_link'}
    wrapped=LinkedConnector(connector,p,receipt)
    if p['operation']=='purchase_gst':
        from app.services.tally_gst_purchase import execute as original
    else:
        from app.services.tally_multi_purchase import execute_multi as original
    result=await original(operation,wrapped,company,identity,p,clean,journal_path)
    if result.get('status')=='verified':
        vouchers=await connector.collection('Voucher',company,p['date'],from_date=p['date'])
        found=[v for v in vouchers if matches_action(v,p)]
        if len(found)!=1 or not verify_tracking(found[0],p,receipt):
            return {'status':'needs_review','uncertain':True,'reason':'Posted invoice receipt-tracking verification failed. Do not resend.'}
    return result
