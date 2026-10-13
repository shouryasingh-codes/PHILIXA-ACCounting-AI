"""Read only, exclusively synthetic acceptance ledgers."""
import asyncio,json
from app.services.tally_connector import TallyConnector,name,value
from sqlalchemy import select,func
from app.database.session import AsyncSessionLocal
from app.models.client import Client
from app.models.tally import TallyAction,TallyCustomerLink
async def main():
    rows=await TallyConnector().collection('Ledger','Philixa Test')
    print(json.dumps([{'name':name(r), **{k:value(r,k) for k in ('GUID','MASTERID','PHILIXAMASTERID','NOTES','PARENT','ISBILLWISEON','ISCOSTCENTRESON','OPENINGBALANCE','CLOSINGBALANCE')}} for r in rows if name(r).startswith('Philixa QA Customer ')]))
    async with AsyncSessionLocal() as db:
        print(json.dumps({'qa_clients':await db.scalar(select(func.count()).select_from(Client).where(Client.name.like('Philixa QA Customer %'))),'qa_links':await db.scalar(select(func.count()).select_from(TallyCustomerLink).where(TallyCustomerLink.ledger_name.like('Philixa QA Customer %'))),'qa_actions':await db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.payload['name'].as_string().like('Philixa QA Customer %')))}))
asyncio.run(main())
