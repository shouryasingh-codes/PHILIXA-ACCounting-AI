"""Authorized, bounded test-company auto-post; never post the prior Day 5 bill.

One stable dummy invoice, maximum INR 211.20, one reservation. Always pauses
the test policy afterwards. Re-runs reconcile the same action, never resend.
"""
import asyncio,io,json
from pathlib import Path
from types import SimpleNamespace
import pymupdf as fitz
from fastapi import UploadFile
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyAction,TallyConnection
from app.models.organization_membership import OrganizationMembership
from app.models.purchase_draft import PurchaseDraft
from app.models.purchase_automation import PurchaseAutomationPolicy as Policy
from app.services import purchase_automation_service as auto,bill_document_service as docs,invoice_extraction as extraction,tally_sync as sync
from app.jobs.document_jobs import validate_bill_document
from app.services.tally_connector import TallyConnector,name,company_identity

ROOT=Path('data/day8');REFERENCE='PHILIXA-D8-AUTO-20261016';PDF=ROOT/'day8-dummy-digital.pdf'
def make_pdf():
    ROOT.mkdir(parents=True,exist_ok=True)
    if PDF.exists():return
    doc=fitz.open();page=doc.new_page(width=842,height=595)
    def text(y,s,size=11):page.insert_text((30,y),s,fontsize=size)
    for y,s in [(30,'DUMMY PRACTICE BILL - DAY 8 AUTOMATION TEST - NOT A REAL INVOICE'),(55,'TAX INVOICE'),(75,'Philixa GST TEST Supplier Local'),(95,'GSTIN: 06ABCPF1234G1ZC'),(115,'Invoice No: '+REFERENCE),(135,'Invoice Date: 02-Oct-2026'),(155,'Place of Supply: Haryana (06)'),(175,'Bill To / Buyer Details'),(195,'Philixa Test'),(215,'GSTIN: 06ABCPE1234F1ZF')]:text(y,s)
    xs=[30,285,350,400,450,515,570,650,710];ys=[240,265,290,315]
    for x in xs:page.draw_line((x,ys[0]),(x,ys[-1]),color=(0,0,0))
    for y in ys:page.draw_line((xs[0],y),(xs[-1],y),color=(0,0,0))
    rows=[['Description','HSN','Unit','Qty','Rate','Disc %','Taxable Amt','GST %'],['Philixa GST TEST Goods18','2523','bags','1','100.00','10%','90.00','18%'],['Philixa GST TEST Goods5','2523','bags','1','100.00','0%','100.00','5%']]
    for i,row in enumerate(rows):
        for j,v in enumerate(row):page.insert_text((xs[j]+4,ys[i]+16),v,fontsize=9)
    for y,s in [(345,'CGST'),(365,'10.60'),(390,'SGST'),(410,'10.60'),(435,'Round Off'),(455,'0.00'),(480,'Grand Total: 211.20'),(520,'Original dummy date deliberately set to 02-Oct-2026 for Tally EDU.')]:text(y,s)
    doc.save(PDF);doc.close()

async def main():
    make_pdf();proof={'invoice':REFERENCE,'maximum_amount':'211.20','human_bill_confirmation':False}
    original_operation=sync.operation
    async def traced_operation(db,company,kind,**params):
        print('Day 8 connector operation: '+kind,flush=True)
        result=await original_operation(db,company,kind,**params)
        print('Day 8 connector completed: '+kind,flush=True)
        return result
    sync.operation=traced_operation
    async with AsyncSessionLocal() as db:
        companies=list(await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True))))
        assert len(companies)==1,'One approved Philixa Test company required.'
        co=companies[0];cid=co.id
        assert co.identity=='bad1cd58-e5a3-43a7-8727-682b86b6f775','Company identity differs.'
        cfg=await db.get(TallyConnection,co.organization_id)
        assert cfg.test_company and cfg.company==co.name,'Test-company write configuration required.'
        native=await TallyConnector().collection('Company')
        assert any(name(c)==co.name and company_identity(c)==co.identity for c in native),'Approved native company must be open.'
        member=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==co.organization_id,OrganizationMembership.role=='owner',OrganizationMembership.status=='active'))
        assert member
        principal=SimpleNamespace(organization_id=co.organization_id,user_id=member.user_id,role=member.role,session_id='authorized-day8-acceptance')
        await auto.authority(db,co,member.user_id)
        row=await db.scalar(select(PurchaseDraft).where(PurchaseDraft.company_id==cid,PurchaseDraft.content['invoice_number'].as_string()==REFERENCE))
        current=await db.get(Policy,cid,populate_existing=True)
        assert not current or current.data['mode']=='paused','Refusing to overwrite an active user policy.'
        policy_enabled=False
        try:
            if not row:
                batch=await docs.create_batch(db,principal,docs.BatchCreate(company_id=cid))
                uploaded=await docs.upload_document(db,principal,batch['id'],UploadFile(filename=PDF.name,file=io.BytesIO(PDF.read_bytes())))
                document_id=uploaded['document']['id'];await validate_bill_document({},document_id)
                raw=extraction.extract_from_pdf_text_local(PDF.read_bytes())
                assert raw['invoice_number']==REFERENCE and raw['buyer_name']=='Philixa Test' and len(raw['lines'])==2 and auto.same_amount(raw['invoice_total'],'211.20'),raw
                result=await extraction.process_document_extraction(db,principal,document_id,raw_result=raw)
                row=await db.get(PurchaseDraft,result['draft']['id'])
            draft_id=row.id
            action=await db.get(TallyAction,row.action_id) if row.action_id else None
            if action is None:
                view=await auto.policy_view(db,principal,cid)
                await auto.save_policy(db,principal,cid,auto.PolicySave(revision=view['revision'],mode='auto',suppliers=['Philixa GST TEST Supplier Local'],items=['Philixa GST TEST Goods18','Philixa GST TEST Goods5'],per_invoice='211.20',daily_amount='211.20',daily_count=1))
                policy_enabled=True
                decision=await auto.evaluate(db,principal,draft_id)
                proof['decision']=decision
                assert decision['decision']=='auto_post',decision
                action=await db.get(TallyAction,decision['action_id'])
            assert action and (action.preconditions or {}).get('automation'),'A Day 8 automatic action is required; no manual approval fallback.'
            for _ in range(8):
                await db.refresh(action)
                if action.status in ('verified','failed','needs_review'):break
                async with sync.company_lock(cid) as locked:
                    if locked:await sync.process_action(db,action,co)
                await asyncio.sleep(1)
            await db.refresh(action)
            proof.update(draft_id=draft_id,action_id=action.token,status=action.status,result=action.result,usage=await auto.usage(db,cid),workflow='private digital PDF -> deterministic source read -> policy decision -> reserved automatic approval -> installed helper -> native voucher readback')
            assert action.status=='verified',proof
        finally:
            await db.rollback()
            if policy_enabled:
                paused=await auto.pause_policy(db,principal,cid);proof['policy_after_test']=paused['policy']['mode']
            else:
                p=await db.get(Policy,cid,populate_existing=True);proof['policy_after_test']=p.data['mode'] if p else 'unset'
            ROOT.joinpath('live-auto-post-proof.json').write_text(json.dumps(proof,indent=2,default=str))
            print(json.dumps(proof,default=str),flush=True)

if __name__=='__main__':asyncio.run(main())
