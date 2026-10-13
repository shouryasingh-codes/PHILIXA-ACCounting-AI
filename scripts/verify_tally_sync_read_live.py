"""Disposable workspace: actual helper snapshot -> saved graph read. No Tally writes."""
import asyncio
import json
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from sqlalchemy import delete
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.tally import TallyReadCompany, TallyDevice, TallySnapshot, TallyConnection, TallyAction
from app.api.v1.routes_tally_bridge import claim, PairClaim, approve, CompanyApproval, Permission, discover, revoke
from app.services import tally_sync as sync, tally_bridge as bridge
from app.services.business_command_service import CommandRequest, ParsedCommand
from app.services.portfolio_copilot_service import run_business_graph
from app.services.tally_connector import TallyError

async def main():
    code=json.loads(sys.stdin.readline())['code'];org=uuid.uuid4().hex
    principal=SimpleNamespace(organization_id=org,user_id='read_acceptance',role='owner',session_id='test')
    async with AsyncSessionLocal() as db:
        db.add(Organization(id=org,name='Temporary snapshot acceptance',slug=org));await db.commit()
        try:
            await claim(PairClaim(code=code),principal,db)
            await asyncio.sleep(2)
            available=await discover(principal,'helper',db)
            target=next(c for c in available['companies'] if c['name']=='Philixa Test')
            await approve(CompanyApproval(companies=[Permission(**target)]),principal,db)
            company=await db.scalar(__import__('sqlalchemy').select(TallyReadCompany).where(TallyReadCompany.organization_id==org))
            await sync.refresh_company(db,company)
            for _ in range(10):
                snapshot=await sync.saved_snapshot(db,company)
                if snapshot:break
                await asyncio.sleep(1)
            assert snapshot,'Snapshot unavailable'
            request=CommandRequest(intent='stock_read',fields={'item_name':'Cement'})
            live=await run_business_graph(request,principal,db)
            assert live['stock_results'][0]['status']=='ok'
            with patch.object(bridge,'request_job',AsyncMock(side_effect=TallyError('Tally closed'))):
                saved=await run_business_graph(request,principal,db)
            assert saved['data_source']=='saved'
            assert saved['stock']['quantity']==live['stock']['quantity']
            db.add(TallyConnection(organization_id=org,company='Philixa Test',godown='Main Location',
                purchase_ledger='Purchases',sales_ledger='Sales',test_company=True,version=1))
            await db.commit()
            with patch.object(sync,'refresh_company',AsyncMock(side_effect=TallyError('Tally closed'))):
                preview=await sync.preview_purchase(db,principal,ParsedCommand(intent='purchase_create',item_name='Cement',
                    party_name='Sharma Traders',quantity='5',unit='bags',rate='350'))
            assert 'preview' in preview,preview.get('response')
            print(json.dumps({'live_snapshot':True,'saved_graph_read':True,'offline_transport_simulated':True,
                              'offline_preview_from_actual_masters':True,'preview_not_confirmed':True,
                              'quantity_matches_live':True,'company':target['name'],'unit':saved['stock']['unit'],
                              'quantity':saved['stock']['quantity'],'real_tally_writes':0}))
        finally:
            await db.rollback();await revoke(principal,db)
            await db.execute(delete(TallyAction).where(TallyAction.organization_id==org))
            await db.execute(delete(TallyConnection).where(TallyConnection.organization_id==org))
            await db.execute(delete(TallySnapshot).where(TallySnapshot.company_id.in_(__import__('sqlalchemy').select(TallyReadCompany.id).where(TallyReadCompany.organization_id==org))))
            await db.execute(delete(TallyReadCompany).where(TallyReadCompany.organization_id==org))
            await db.execute(delete(TallyDevice).where(TallyDevice.organization_id==org))
            await db.execute(delete(Organization).where(Organization.id==org));await db.commit()
if __name__=='__main__':asyncio.run(main())
