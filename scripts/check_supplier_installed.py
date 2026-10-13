"""Read-only graph/helper/native acceptance. Never confirms an action or edits grants."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.organization import Organization
from app.services.business_command_service import CommandRequest
from app.services.portfolio_copilot_service import run_business_graph
from app.services.tally_connector import TallyConnector, TallyError, name, value
from app.services.tally_supplier_codec import supplier_rows


async def main():
    async with AsyncSessionLocal() as db:
        companies=list((await db.scalars(select(TallyReadCompany).where(
            TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True),
            TallyReadCompany.device_id.is_not(None)))).all())
        if len(companies)!=1:
            raise RuntimeError('Exactly one approved paired test company required.')
        company=companies[0]
        members=list((await db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.organization_id==company.organization_id,
            OrganizationMembership.status=='active',OrganizationMembership.role.in_(('owner','admin'))))).all())
        eligible=[]
        for member in members:
            user=await db.get(User,member.user_id)
            if user and user.is_active:eligible.append(member)
        org=await db.get(Organization,company.organization_id)
        if not eligible or not org or not org.is_active:
            raise RuntimeError('Active workspace owner required.')
        member=sorted(eligible,key=lambda m:(m.role!='owner',m.user_id))[0]
        principal=SimpleNamespace(organization_id=company.organization_id,user_id=member.user_id,
            role=member.role,session_id='supplier-read-acceptance')
        result=await run_business_graph(CommandRequest(text='Hamara supplier kaun hai?'),principal,db)
        offered={c['command']['fields']['party_name'] for c in result.get('tally_choices',[])
            if c['command']['fields'].get('company_id')==company.id}
        catalog=await TallyConnector().catalog(company.name)
        native={name(l) for l in supplier_rows(catalog)}
        first=sorted(native)[0] if native else None
        detail={}
        if first:
            detail=await run_business_graph(CommandRequest(text=first+' ye kon hai?'),principal,db)
        rows=detail.get('supplier_results',[])
        ledger=next((l for l in supplier_rows(catalog) if name(l)==first),None)
        detail_match=bool(first) and any(r['company_id']==company.id and r['name']==first and r['group']==value(ledger,'PARENT') and r['data_source']=='live' for r in rows)
        fields_match=bool(ledger is not None) and all(not value(ledger,tag) or value(ledger,tag) in detail.get('response','')
            for tag in ('LEDGERPHONE','LEDGERMOBILE','EMAIL','OPENINGBALANCE','CLOSINGBALANCE'))
        # Exercise real scoped saved data without closing the user's Tally window.
        from app.services import tally_suppliers
        with patch.object(tally_suppliers,'refresh_company',AsyncMock(side_effect=TallyError('Tally closed'))):
            offline=await run_business_graph(CommandRequest(intent='supplier_list',fields={'company_id':company.id}),principal,db)
        saved={c['command']['fields']['party_name'] for c in offline.get('tally_choices',[])}
        report={'list_matches_native':offered==native,'list_source_live':'Tally live suppliers' in result['response'],
            'supplier_count':len(native),'named_detail_matches_native':detail_match,
            'detail_fields_match_native':fields_match,
            'simulated_offline_saved_data_match':saved==native and 'Saved Tally suppliers' in offline['response'] and 'Tally live suppliers' not in offline['response'],
            'installed_helper_group_coverage':'subgroup coverage unverified' not in result['response'],
            'accounting_writes':0,'pairing_or_grant_changes':0}
        print(json.dumps(report))
        if not all(report[k] for k in ('list_matches_native','list_source_live','named_detail_matches_native','detail_fields_match_native','simulated_offline_saved_data_match','installed_helper_group_coverage')):
            raise RuntimeError('Supplier acceptance incomplete.')

if __name__=='__main__':asyncio.run(main())
