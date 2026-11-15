"""Explicit, read-only test-company acceptance; no mocked provider/native data.

Uses an existing authorized task/session and conversation. The dispatch guard
rejects any model-selected mutation before it reaches a domain service.
"""
import argparse
import asyncio
import copy
import json
import secrets
import time
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, func
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.business_route import BusinessRoute
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction
from app.jobs.task_agent_jobs import principal_for
from app.services import business_router as router, intent_router_model as model
from app.services.ai_engine_manager import provider_scope,transport_lifespan
from app.services.business_command_service import CommandRequest
from app.services.business_conversation_service import scoped_conversation
from app.services.purchase_draft_service import company_for


async def main(args):
    await model.warm()
    async with transport_lifespan(),AsyncSessionLocal() as db:
        anchor=await db.get(AgentTask,args.task)
        if not anchor:raise ValueError('Authorized anchor task not found')
        principal=await principal_for(db,anchor)
        company=await company_for(db,principal,anchor.company_id)
        if company.name!='Philixa Test':raise ValueError('Only Philixa Test accepted')
        old=await db.get(BusinessRoute,args.route)
        if not old or (old.user_id,old.organization_id)!=(principal.user_id,principal.organization_id):
            raise ValueError('Route access denied')
        conversation=await scoped_conversation(db,principal,old.conversation_id)
        snapshot=(copy.deepcopy(anchor.state),anchor.revision,anchor.status)
        async def counts():
            return {cls.__name__:await db.scalar(select(func.count()).select_from(cls).where(
                cls.organization_id==principal.organization_id)) for cls in (AgentTask,PurchaseDraft,TallyAction)}
        before=await counts()
        request=CommandRequest(text=args.message,request_id=secrets.token_hex(16),
            conversation_id=conversation.id,conversation_revision=conversation.revision,
            candidate_task_id=anchor.id,fields={'company_id':company.id})
        dispatch=router.dispatch
        async def read_only_dispatch(db,principal,request,row,decision,context):
            if decision.handler!='domain_read' or decision.intent not in ('purchase_history_read','supplier_read'):
                raise ValueError('Live acceptance prohibits non-supplier-read dispatch')
            return await dispatch(db,principal,request,row,decision,context)
        start=time.monotonic()
        with provider_scope(args.provider),patch.object(router,'dispatch',read_only_dispatch):
            result=await router.route(db,principal,request)
            elapsed=round(time.monotonic()-start,3)
            replay=await router.route(db,principal,request)
        row=await db.get(BusinessRoute,result.get('route_id')) if result.get('route_id') else None
        await db.refresh(anchor)
        after=await counts()
        report={'test_type':'live provider + existing native connector, read-only backend',
            'non_read_dispatch_guard':True,'message':args.message,'requested_provider':args.provider,
            'router_version':model.VERSION,'seconds':elapsed,
            'route_id':row.id if row else None,'decision':row.decision if row else None,
            'telemetry':row.telemetry if row else None,'result':result,
            'idempotent_replay':result==replay,'counts_before':before,'counts_after':after,
            'existing_task_unchanged':snapshot==(anchor.state,anchor.revision,anchor.status),
            'browser_acceptance':'not performed by this script'}
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:report[k] for k in ('requested_provider','seconds','route_id','decision',
            'idempotent_replay','counts_before','counts_after','existing_task_unchanged')},ensure_ascii=False))
        print(json.dumps({'response':result.get('response'),'history_complete':result.get('history_complete'),
            'response_kind':result.get('response_kind')},ensure_ascii=False))
        if before!=after or not report['existing_task_unchanged']:raise AssertionError('Read acceptance mutated business state')


async def run(args):
    async with transport_lifespan():
        for number in range(1,args.runs+1):
            current=copy.copy(args)
            if args.runs>1:
                target=Path(args.output)
                current.output=str(target.with_name(target.stem+f'-run-{number}'+target.suffix))
            await main(current)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',required=True)
    parser.add_argument('--route',required=True)
    parser.add_argument('--provider',choices=['groq','gemini'],required=True)
    parser.add_argument('--message',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--runs',type=int,choices=[1,2,3],default=1,help='Bounded fresh requests; not replays. Same owned transport pool.')
    asyncio.run(run(parser.parse_args()))
