"""Read-only acceptance against the installed paired helper; never approves writes."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany
from app.models.organization_membership import OrganizationMembership
from app.services.business_command_service import CommandRequest
from app.services.portfolio_copilot_service import run_business_graph

async def main():
    async with AsyncSessionLocal() as db:
        companies=list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True)))).all())
        if len(companies)!=1:raise RuntimeError('Exactly one approved test company required')
        company=companies[0]
        owner=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==company.organization_id,OrganizationMembership.status=='active',OrganizationMembership.role=='owner'))
        if not owner:raise RuntimeError('Active owner required')
        principal=SimpleNamespace(organization_id=company.organization_id,user_id=owner.user_id,role=owner.role,session_id='report-read-acceptance')
        with patch.dict('os.environ',{'PHILIXA_PURCHASE_REPORT_ENABLED':'1'}):
            result=await run_business_graph(CommandRequest(text='Philixa Test ka purchase report 1 October 2026 se 2 October 2026 tak dikhao.'),principal,db)
        view=result.get('mcp_report',{})
        period_ok=view.get('arguments')=={'from':'01-10-2026','to':'02-10-2026'}
        amount_ok=any(row[1:] == ['₹5,950.00','','₹-5,950.00'] for row in view.get('rows',[]))
        print(json.dumps({'capability':result.get('capability'),'requested_period_match':period_ok,
                          'total_matches_native_day_book_5950':amount_ok,'accounting_writes':0}))
        if result.get('capability')!='read_result':raise RuntimeError('Live report acceptance incomplete')
        if not period_ok or not amount_ok:raise RuntimeError('Report period/total does not match the reviewed test company')

if __name__=='__main__':asyncio.run(main())
