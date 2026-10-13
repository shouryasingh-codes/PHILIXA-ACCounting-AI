"""Acceptance through the installed paired connector; only a unique QA ledger.

Requires an existing active owner session and configured non-GST test company.
Creates/links a temporary customer through the graph and durable queue, verifies
native Tally independently, then removes only that exact zero-balance QA record.
Pairing, grants, user sessions and existing customers are never changed.
"""
import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from sqlalchemy import select, delete
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyConnection,TallyAction,TallyCustomerLink
from app.models.organization_membership import OrganizationMembership
from app.models.user_session import UserSession
from app.models.client import Client
from app.services import tally_sync as sync
from app.services.tally_connector import TallyConnector,name,value,decimal,tag
from app.services.tally_customer_codec import matches_created,verify_created
from app.services.portfolio_copilot_service import run_business_graph
from app.services.business_command_service import CommandRequest,CommandFields
from app.api.v1.routes_tally_bridge import helper_status

async def main():
    report={'installed_connector_acceptance':False,'native_voucher_writes':0,'pairing_or_grant_changes':0}
    async with AsyncSessionLocal() as db:
        companies=list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True),TallyReadCompany.device_id.is_not(None)))).all())
        if len(companies)!=1:raise RuntimeError('Exactly one approved paired test company required.')
        company=companies[0];company_name=company.name;company_id=company.id
        cfg=await db.get(TallyConnection,company.organization_id)
        if not cfg or not cfg.test_company or cfg.company!=company.name:raise RuntimeError('Configured test company required.')
        session=await db.scalar(select(UserSession).join(OrganizationMembership,(OrganizationMembership.user_id==UserSession.user_id)&(OrganizationMembership.organization_id==UserSession.organization_id)).where(UserSession.organization_id==company.organization_id,UserSession.revoked_at.is_(None),UserSession.expires_at>sync.now(),OrganizationMembership.status=='active',OrganizationMembership.role.in_(('owner','admin'))))
        if not session:raise RuntimeError('Existing active owner/admin session required.')
        member=await db.get(OrganizationMembership,(session.user_id,session.organization_id))
        principal=SimpleNamespace(organization_id=company.organization_id,user_id=session.user_id,session_id=session.id,role=member.role)
        status=await helper_status(principal,db)
        if not status.get('customer_ledger_capable'):raise RuntimeError('Installed protocol 6 connector not ready.')
        if await db.scalar(select(TallyAction.token).where(TallyAction.company_id==company.id,TallyAction.status.in_(sync.ACTIVE))):raise RuntimeError('Existing accounting actions must settle first.')
        test_name='Philixa QA Customer '+uuid.uuid4().hex[:12]
        connector=TallyConnector();token=None;payload=None;client_id=None
        try:
            preview=await run_business_graph(CommandRequest(intent='customer_create',fields=CommandFields(client_name=test_name,company_id=company.id)),principal,db)
            if not preview.get('preview'):raise RuntimeError('Customer preview unavailable.')
            token=preview['preview']['token'];action=await db.get(TallyAction,token);payload=dict(action.payload)
            async with sync.company_lock(company.id) as locked:
                if not locked:raise RuntimeError('Company busy.')
                await sync.confirm_queued(db,principal,action)
                await sync.process_action(db,action,company)
            await db.refresh(action)
            report['action_status']=action.status
            if action.status!='verified':raise RuntimeError('Installed customer dispatch not verified: '+str(action.status))
            link=await db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.action_id==token))
            if not link:raise RuntimeError('Verified ledger link missing.')
            client_id=link.client_id
            actual=[l for l in await connector.collection('Ledger',company_name) if name(l)==test_name]
            client=await db.get(Client,client_id)
            if len(actual)!=1 or value(actual[0],'GUID')!=link.ledger_guid or not verify_created(actual[0],payload) or not client or client.name!=test_name:raise RuntimeError('Independent Tally/customer link mismatch.')
            await sync.confirm_queued(db,principal,action)
            if len([l for l in await connector.collection('Ledger',company_name) if name(l)==test_name])!=1:raise RuntimeError('Duplicate ledger.')
            report.update(installed_connector_acceptance=True,ledger_parent='Sundry Debtors',duplicate_ledgers=1,philixa_link_verified=True,duplicate_confirmation='one ledger')
        finally:
            await db.rollback()
            if payload:
                rows=[l for l in await connector.collection('Ledger',company_name) if name(l)==test_name and matches_created(l,payload)]
                if len(rows)>1:raise RuntimeError('Ambiguous test ledger cleanup refused.')
                if rows:
                    row=rows[0]
                    if value(row,'PARENT')!='Sundry Debtors' or decimal(value(row,'OPENINGBALANCE') or '0')!=0 or decimal(value(row,'CLOSINGBALANCE') or '0')!=0:raise RuntimeError('Test ledger changed; cleanup refused.')
                    root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC')
                    tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY',company_name)
                    ledger=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE',**{'xmlns:UDF':'TallyUDF'}),'LEDGER',NAME=test_name,ACTION='Delete')
                    tag(ledger,'GUID',value(row,'GUID'));tag(ledger,'NAME',test_name)
                    await connector.post(ET.tostring(root,encoding='unicode'))
                    if any(name(l)==test_name for l in await connector.collection('Ledger',company_name)):raise RuntimeError('Test cleanup not verified.')
                    report['native_test_ledger_cleanup']='verified'
            if token:
                link=await db.scalar(select(TallyCustomerLink).where(TallyCustomerLink.action_id==token))
                if link:client_id=link.client_id
                await db.execute(delete(TallyCustomerLink).where(TallyCustomerLink.action_id==token))
                await db.execute(delete(TallyAction).where(TallyAction.token==token))
                if client_id:await db.execute(delete(Client).where(Client.id==client_id,Client.name==test_name))
                await db.commit()
                company=await db.get(TallyReadCompany,company_id)
                await sync.refresh_company(db,company)
            Path('data/customer-installed-acceptance.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))

if __name__=='__main__':asyncio.run(main())
