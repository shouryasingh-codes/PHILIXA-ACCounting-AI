"""Read-only acceptance of the existing installation; never pair or import.

Run inside the local app container. Resolves one approved Philixa Test workspace
and its actual active owner/admin. Requests stock through its installed helper,
then compares stored verified purchases with native Tally exports. Does not
confirm a preview, replace credentials, change grants or cancel pending actions.
"""
import asyncio
import json
from types import SimpleNamespace
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany, TallyAction
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.organization import Organization
from app.api.v1.routes_tally_bridge import helper_status
from app.services.business_command_service import CommandRequest
from app.services.portfolio_copilot_service import run_business_graph
from app.services.tally_connector import TallyConnector, verify_voucher, matches_action


async def main():
    async with AsyncSessionLocal() as db:
        companies=list((await db.scalars(select(TallyReadCompany).where(
            TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True),
            TallyReadCompany.device_id.is_not(None)))).all())
        if len(companies)!=1:raise RuntimeError('Exactly one approved paired test company required.')
        company=companies[0]
        members=list((await db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.organization_id==company.organization_id,
            OrganizationMembership.status=='active',OrganizationMembership.role.in_(('owner','admin'))))).all())
        eligible=[]
        for member in members:
            user=await db.get(User,member.user_id)
            if user and user.is_active:eligible.append(member)
        organization=await db.get(Organization,company.organization_id)
        if not eligible or not organization or not organization.is_active:
            raise RuntimeError('Active test workspace owner required.')
        member=sorted(eligible,key=lambda m:(m.role!='owner',m.user_id))[0]
        principal=SimpleNamespace(organization_id=company.organization_id,user_id=member.user_id,
            role=member.role,session_id='read-only-installed-acceptance')
        status=await helper_status(principal,db)
        request=CommandRequest(intent='stock_read',fields={'company_id':company.id,'item_name':'Cement'})
        read=await run_business_graph(request,principal,db)
        rows=read.get('stock_results',[])
        live=len(rows)==1 and rows[0].get('status')=='ok' and rows[0].get('data_source')=='live'
        actions=list((await db.scalars(select(TallyAction).where(
            TallyAction.company_id==company.id,TallyAction.status=='verified',
            TallyAction.backend=='python').order_by(TallyAction.created_at.desc()).limit(5))).all())
        checked=[]
        connector=TallyConnector()
        active=list((await db.scalars(select(TallyAction).where(
            TallyAction.company_id==company.id,TallyAction.status.in_(('queued','submitting','verification_pending'))))).all())
        for action in actions if live else []:
            if action.payload.get('operation')=='stock_count_set' or not action.payload.get('date'):continue
            exports=await connector.collection('Voucher',company.name,action.payload['date'])
            found=[v for v in exports if matches_action(v,action.payload)]
            checked.append(len(found)==1 and verify_voucher(found[0],action.payload))
        # The stock read establishes a fresh identity-bound live proof.
        status=await helper_status(principal,db)
        output={'installed_helper_live_read':live,'connection_state':status.get('connection_state'),
            'active_accounting_actions':len(active),
            'existing_verified_purchases_checked':len(checked),'existing_purchase_native_match':bool(checked) and all(checked),
            'stock_source':rows[0].get('data_source') if rows else 'unavailable',
            'stock_read_reason':rows[0].get('reason') if rows else None,'accounting_writes':0,
            'pairing_or_grant_changes':0}
        print(json.dumps(output))
        return output

if __name__=='__main__':asyncio.run(main())
