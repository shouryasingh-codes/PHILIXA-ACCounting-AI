"""Read-only local bridge acceptance in a disposable workspace. Never prints secrets."""
import asyncio
import json
import sys
import uuid
from types import SimpleNamespace
from sqlalchemy import delete
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.tally import TallyReadCompany, TallyDevice
from app.api.v1.routes_tally_bridge import claim, PairClaim, approve, CompanyApproval, Permission, discover, revoke
from app.services.business_command_service import CommandRequest
from app.services.portfolio_copilot_service import run_business_graph

async def main():
    code=json.loads(sys.stdin.readline())['code'];org=uuid.uuid4().hex
    principal=SimpleNamespace(organization_id=org,user_id='bridge_acceptance',role='owner')
    async with AsyncSessionLocal() as db:
        db.add(Organization(id=org,name='Temporary bridge acceptance',slug=org));await db.commit()
        try:
            await claim(PairClaim(code=code),principal,db)
            await asyncio.sleep(2)
            available=await discover(principal,'helper',db)
            target=next(c for c in available['companies'] if c['name']=='Philixa Test')
            await approve(CompanyApproval(companies=[Permission(**target)]),principal,db)
            result=await run_business_graph(CommandRequest(intent='stock_read',fields={'item_name':'Cement'}),principal,db)
            assert result['stock_results'][0]['status']=='ok',result['coverage']
            assert result['stock']['quantity']=='0' and result['stock']['unit']=='bags'
            print('PASS: paired Windows helper → Redis jobs → existing graph → local Tally; Cement 0 bags.')
        finally:
            await db.rollback();await revoke(principal,db)
            await db.execute(delete(TallyReadCompany).where(TallyReadCompany.organization_id==org))
            await db.execute(delete(TallyDevice).where(TallyDevice.organization_id==org))
            await db.execute(delete(Organization).where(Organization.id==org));await db.commit()

if __name__=='__main__':asyncio.run(main())
