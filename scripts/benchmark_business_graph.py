"""Compare extracted direct dispatch with graph for real read-only tools, no model calls."""
import asyncio
import statistics
import time
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyConnection
from app.models.client import Client
from app.models.organization_membership import OrganizationMembership
from app.repositories.client_repository import ClientRepository
from app.services import business_command_service as commands
from app.services.portfolio_copilot_service import run_business_graph


async def main():
    async with AsyncSessionLocal() as db:
        cfg=await db.scalar(select(TallyConnection).where(TallyConnection.company=='Philixa Test'))
        assert cfg,'Configure the test company first'
        membership=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==cfg.organization_id).limit(1))
        assert membership
        principal=SimpleNamespace(organization_id=cfg.organization_id,user_id=membership.user_id,role='owner',session_id='benchmark-read-only')
        client=await ClientRepository().create(db,principal,{'name':'Temporary benchmark customer'})
        await db.flush()
        cases={
            'stock_read':commands.CommandRequest(intent='stock_read',fields={'item_name':'Cement'}),
            'customer_read':commands.CommandRequest(intent='customer_read',client_id=client.id),
        }
        with patch.object(commands,'get_ai_provider',side_effect=AssertionError('Simple reads must not add model calls')) as provider:
            for label,request in cases.items():
                principal.organization_id = cfg.organization_id if label=='stock_read' else client.organization_id
                durations={'direct':[],'graph':[]}
                responses={}
                for _ in range(5):
                    for mode in durations:
                        started=time.perf_counter()
                        if mode=='direct':
                            parsed=await commands.plan_command(request,principal,db)
                            response=await commands.execute_command(request,principal,db,parsed)
                        else:
                            response=await run_business_graph(request,principal,db)
                        durations[mode].append((time.perf_counter()-started)*1000)
                        responses[mode]=response
                # Ignore the changing read timestamp when comparing real stock output.
                assert responses['direct']['response'].split('\n')[0]==responses['graph']['response'].split('\n')[0]
                print(label,{mode:round(statistics.median(samples),2) for mode,samples in durations.items()},'median_ms; model_calls=0')
            provider.assert_not_called()


if __name__=='__main__':
    asyncio.run(main())
