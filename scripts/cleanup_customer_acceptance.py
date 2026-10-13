"""Clean only the two known failed-test ledger identities and persisted QA fixtures."""
import asyncio
from xml.etree import ElementTree as ET
from sqlalchemy import select,delete
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyAction,TallyCustomerLink
from app.models.organization import Organization
from app.models.user import User
from app.services.tally_connector import TallyConnector,tag,name,value,decimal
from app.services.tally_customer_codec import matches_created

async def main():
    async with AsyncSessionLocal() as db:
        orgs=list((await db.scalars(select(Organization).where(Organization.name=='Customer acceptance test'))).all())
        proof={}
        for org in orgs:
            if org.slug!=org.id:raise RuntimeError('Not an isolated acceptance fixture')
            actions=list((await db.scalars(select(TallyAction).where(TallyAction.organization_id==org.id))).all())
            for a in actions:
                if a.payload.get('operation')=='customer_ledger_create' and a.payload['name'].startswith('Philixa QA Customer '):proof[a.payload['name']]=a.payload
        connector=TallyConnector();rows=await connector.collection('Ledger','Philixa Test')
        known_ids={'bad1cd58-e5a3-43a7-8727-682b86b6f775-000000d2','bad1cd58-e5a3-43a7-8727-682b86b6f775-000000d3'}
        cleaned=0
        for row in rows:
            n=name(row)
            if not n.startswith('Philixa QA Customer '):continue
            if value(row,'GUID') not in known_ids and not (n in proof and matches_created(row,proof[n])):continue
            if value(row,'PARENT')!='Sundry Debtors' or decimal(value(row,'OPENINGBALANCE') or '0')!=0 or decimal(value(row,'CLOSINGBALANCE') or '0')!=0:raise RuntimeError('QA ledger changed, cleanup refused')
            vouchers=await connector.collection('Voucher','Philixa Test')
            if any(v.findtext('.//LEDGERNAME')==n or any(x.text==n for x in v.findall('.//LEDGERNAME')) for v in vouchers):raise RuntimeError('QA ledger has transactions; cleanup refused')
            root=ET.Element('ENVELOPE');tag(tag(root,'HEADER'),'TALLYREQUEST','Import Data');body=tag(tag(root,'BODY'),'IMPORTDATA');desc=tag(body,'REQUESTDESC')
            tag(desc,'REPORTNAME','All Masters');tag(tag(desc,'STATICVARIABLES'),'SVCURRENTCOMPANY','Philixa Test')
            ledger=tag(tag(tag(body,'REQUESTDATA'),'TALLYMESSAGE',**{'xmlns:UDF':'TallyUDF'}),'LEDGER',NAME=n,ACTION='Delete');tag(ledger,'NAME',n);tag(ledger,'GUID',value(row,'GUID'))
            await connector.post(ET.tostring(root,encoding='unicode'))
            if any(name(l)==n for l in await connector.collection('Ledger','Philixa Test')):raise RuntimeError('Cleanup not verified')
            cleaned+=1
        for org in orgs:
            actor_ids=list((await db.scalars(select(TallyAction.user_id).where(TallyAction.organization_id==org.id))).all())
            await db.execute(delete(TallyCustomerLink).where(TallyCustomerLink.organization_id==org.id));await db.execute(delete(TallyAction).where(TallyAction.organization_id==org.id))
            await db.execute(delete(Organization).where(Organization.id==org.id))
            if actor_ids:await db.execute(delete(User).where(User.id.in_(actor_ids),User.email.endswith('@example.invalid')))
        await db.commit();print('Temporary acceptance ledgers cleaned:',cleaned)
asyncio.run(main())
