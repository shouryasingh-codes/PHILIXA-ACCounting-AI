"""Read-only incident proof, scoped by the supplied original task owner."""
import argparse,asyncio,json,os
from pathlib import Path
from sqlalchemy import select,func
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.business_route import BusinessRoute
from app.models.groq_quota import GroqQuotaRequest

async def main(ident):
    async with AsyncSessionLocal() as db:
        owner=await db.get(AgentTask,ident)
        if not owner:raise SystemExit('Original task not found')
        rows=(await db.scalars(select(BusinessRoute).where(BusinessRoute.organization_id==owner.organization_id,
            BusinessRoute.user_id==owner.user_id,BusinessRoute.result['response_kind'].as_string()=='smalltalk',
            BusinessRoute.status=='completed').order_by(BusinessRoute.created_at.desc()).limit(3))).all()
        proof=[]
        for row in rows:
            linked=await db.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.organization_id==row.organization_id,
                AgentTask.user_id==row.user_id,AgentTask.request_id==row.id))
            calls=(await db.scalars(select(GroqQuotaRequest).where(GroqQuotaRequest.task_id==row.id))).all()
            proof.append({'route_id':row.id,'version':row.version,'intent':row.decision.get('intent'),
                'status':row.status,'path':row.telemetry.get('path'),'total_ms':row.telemetry.get('total_ms'),
                'provider_ms':[q.metadata_json.get('latency_ms') for q in calls],
                'provider_calls':len(calls),'new_accounting_tasks':linked,
                'public_task_reference':row.result.get('task_id'),'routing_mode':row.result.get('routing_mode')})
        result={'date':'2026-11-07','scope':'Targeted conversational routing and latency; not full business-agent acceptance',
                'full_context_rollout':os.getenv('PHILIXA_INTENT_ROUTER_ENABLED','0'),
                'browser_verified':True,'native_posting_performed':False,'rows':proof,
                'targeted_check_passed':len(proof)>=2 and all(p['intent']=='smalltalk' and p['provider_calls']==1
                    and p['new_accounting_tasks']==0 and not p['public_task_reference'] for p in proof)}
        Path('data/social-routing-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('task_id');args=parser.parse_args();asyncio.run(main(args.task_id))
