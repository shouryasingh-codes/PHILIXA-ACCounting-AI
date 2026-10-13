"""Native customer acceptance in the configured test company, no real contacts.

Default: read-only preflight. --execute: create one uniquely named zero-balance
test customer via the real graph/queue/protocol, verify CRM link, then delete only
that exact test ledger and isolated DB fixtures. Never imports a voucher.
"""
import argparse
import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from sqlalchemy import select, delete
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany, TallyConnection, TallyAction, TallyCustomerLink
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.services.tally_connector import TallyConnector, company_identity, name, value, tag, decimal
from app.services.tally_customer_codec import matches_created
from app.services import tally_sync as sync
from app.services.portfolio_copilot_service import run_business_graph
from app.services.business_command_service import CommandRequest,CommandFields

async def main(execute=False):
    report={'native_customer_acceptance':False,'installed_connector_acceptance':False,'native_voucher_writes':0}
    async with AsyncSessionLocal() as db:
        configured=list((await db.scalars(select(TallyConnection).join(Organization,Organization.id==TallyConnection.organization_id).where(TallyConnection.company=='Philixa Test',TallyConnection.test_company.is_(True),Organization.name!='Customer acceptance test'))).all())
        if len(configured)!=1:raise RuntimeError('Exactly one explicitly configured Philixa Test company required.')
        cfg=configured[0]
        company_name=cfg.company
        approved=await db.scalar(select(TallyReadCompany).where(TallyReadCompany.organization_id==cfg.organization_id,TallyReadCompany.name==cfg.company,TallyReadCompany.enabled.is_(True)))
        if not approved:raise RuntimeError('Configured test company approval required.')
        active=await db.scalar(select(TallyAction.token).where(TallyAction.company_id==approved.id,TallyAction.status.in_(sync.ACTIVE)))
        if active:raise RuntimeError('Existing accounting actions must settle before native acceptance.')
        connector=TallyConnector();companies=await connector.collection('Company')
        rows=[c for c in companies if name(c)==cfg.company and company_identity(c)==approved.identity]
        if len(rows)!=1 or value(rows[0],'ISGSTON').casefold()!='no':raise RuntimeError('Approved non-GST native identity not available.')
        report['preflight']='approved configured non-GST test company reachable'
        if not execute:print(json.dumps(report));return
        org_id=uuid.uuid4().hex;user_id=uuid.uuid4().hex;test_name='Philixa QA Customer '+uuid.uuid4().hex[:12]
        principal=SimpleNamespace(organization_id=org_id,user_id=user_id,session_id='native-customer-acceptance',role='owner')
        native_guid=None;payload=None
        original_post=TallyConnector.post
        async def record_import(conn,xml):
            response=await original_post(conn,xml)
            ledger=ET.fromstring(xml).find('.//LEDGER')
            if ledger is not None and ledger.get('ACTION')=='Create' and ledger.get('NAME')==test_name:
                report['import_receipt']={k:response.findtext('.//'+k) for k in ('CREATED','ALTERED','LASTMID','ERRORS')}
            return response
        from unittest.mock import patch
        receipt_patch=patch.object(TallyConnector,'post',record_import);receipt_patch.start()
        try:
            db.add(Organization(id=org_id,name='Customer acceptance test',slug=org_id));db.add(User(id=user_id,email=user_id+'@example.invalid',hashed_password='synthetic'))
            await db.flush();db.add(OrganizationMembership(organization_id=org_id,user_id=user_id,role='owner',status='active'))
            company=TallyReadCompany(id=uuid.uuid4().hex,organization_id=org_id,name=cfg.company,identity=approved.identity,enabled=True,device_id=None,aliases=[],member_ids=[])
            db.add(company);db.add(TallyConnection(organization_id=org_id,company=cfg.company,godown=cfg.godown,purchase_ledger=cfg.purchase_ledger,sales_ledger=cfg.sales_ledger,test_company=True,version=1));await db.commit()
            preview=await run_business_graph(CommandRequest(intent='customer_create',fields=CommandFields(client_name=test_name,company_id=company.id)),principal,db)
            if not preview.get('preview'):raise RuntimeError('Customer preview unavailable: '+preview.get('response','unknown'))
            action=await db.get(TallyAction,preview['preview']['token']);payload=action.payload
            await sync.confirm_queued(db,principal,action)
            async with sync.company_lock(company.id) as locked:
                if not locked:raise RuntimeError('Tally endpoint busy.')
                await sync.process_action(db,action,company)
            report['action_status']=action.status
            observed=[l for l in await connector.collection('Ledger',cfg.company) if name(l)==test_name]
            if len(observed)==1 and report.get('import_receipt',{}).get('CREATED')=='1':native_guid=value(observed[0],'GUID')
            if action.status!='verified':raise RuntimeError('Native customer not verified: '+(action.result or {}).get('response',action.status))
            link=await db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.action_id==action.token))
            ledgers=await connector.collection('Ledger',cfg.company)
            actual=[l for l in ledgers if name(l)==test_name and link and value(l,'GUID')==link.ledger_guid]
            if len(actual)!=1 or not link or value(actual[0],'GUID')!=link.ledger_guid:raise RuntimeError('Independent native customer link mismatch.')
            native_guid=link.ledger_guid
            report.update(native_customer_acceptance=True,ledger_parent=value(actual[0],'PARENT'),duplicate_ledgers=len(actual),philixa_link_verified=True)
            # A repeated confirmed action reconciles instead of creating another ledger.
            await sync.confirm_queued(db,principal,action)
            actual=[l for l in await connector.collection('Ledger',cfg.company) if name(l)==test_name]
            if len(actual)!=1:raise RuntimeError('Duplicate ledger after repeated confirmation.')
            report['duplicate_confirmation']='one ledger'
        finally:
            receipt_patch.stop()
            await db.rollback()
            if payload:
                actual=[l for l in await connector.collection('Ledger',company_name) if name(l)==test_name and (matches_created(l,payload) or (native_guid and value(l,'GUID')==native_guid))]
                if len(actual)==1:
                    row=actual[0]
                    if value(row,'PARENT')!='Sundry Debtors' or decimal(value(row,'OPENINGBALANCE') or '0')!=0 or decimal(value(row,'CLOSINGBALANCE') or '0')!=0:
                        raise RuntimeError('Test ledger changed; automatic cleanup refused.')
                    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(root,'BODY'),'IMPORTDATA')
                    desc=tag(body,'REQUESTDESC');tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',company_name)
                    ledger=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE',**{'xmlns:UDF':'TallyUDF'}),'LEDGER',NAME=test_name,ACTION='Delete')
                    tag(ledger,'GUID',value(row,'GUID'));tag(ledger,'NAME',test_name)
                    await connector.post(ET.tostring(root,encoding='unicode'))
                    if any(name(l)==test_name for l in await connector.collection('Ledger',company_name)):raise RuntimeError('Test ledger cleanup not verified.')
                    report['native_test_ledger_cleanup']='verified'
            await db.execute(delete(TallyCustomerLink).where(TallyCustomerLink.organization_id==org_id))
            await db.execute(delete(TallyAction).where(TallyAction.organization_id==org_id))
            await db.execute(delete(Organization).where(Organization.id==org_id));await db.execute(delete(User).where(User.id==user_id));await db.commit()
            Path('data/customer-ledger-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    asyncio.run(main(args.execute))
