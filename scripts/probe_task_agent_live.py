"""One free-tier model proposal; never runs a domain tool or posts to Tally."""
import asyncio
import json
from app.jobs.task_agent_jobs import billing_limits
from app.services.task_agent_model import choose
from app.services.task_agent_tools import MasterQuery, NewPurchase
from app.services.purchase_message import MessageFields, grounded


async def main():
    if billing_limits()[0]!='free':
        raise RuntimeError('This probe requires confirmed free-tier mode')
    tools=[dict(name='company_masters',description='Search permitted saved supplier/item masters; no write.',
        effect='read',schema=MasterQuery.model_json_schema()),
        dict(name='create_purchase_draft',description='Save explicit user facts as a draft; never post.',
        effect='draft',schema=NewPurchase.model_json_schema())]
    state=dict(messages=['Sharma Traders se 5 Cement bags kharide, rate 350 GST se pehle. Draft taiyar karo.'],
        outcome='draft',observations=[],executions=[])
    try:
        decision,usage=await choose(state,tools)
        permitted={t['name'] for t in tools}
        if decision.kind=='tool' and decision.tool not in permitted:
            raise ValueError('Unregistered model tool')
        if decision.kind=='tool':
            schema=MasterQuery if decision.tool=='company_masters' else NewPurchase
            schema.model_validate(decision.arguments)
            if decision.tool=='create_purchase_draft':
                fields=MessageFields(updates=decision.arguments['updates'],unsupported_reason=None)
                grounded(state['messages'][decision.arguments['message_index']],fields)
        print(json.dumps({'live_provider':True,'model':'openai/gpt-oss-20b',
            'decision':decision.model_dump(),'usage':usage,'domain_tools_executed':0,
            'tally_writes':0,'calls':1},ensure_ascii=False))
    except Exception as exc:
        # Provider errors may contain request payloads; print no raw exception.
        cause=exc.__cause__
        status=getattr(exc,'status',None) or getattr(cause,'code',None)
        markers=[m for m in ('rate_limit','invalid_api_key','json_schema','schema','Cloudflare','Access denied','timed out') if m.lower() in str(exc).lower()]
        validation=[{'field':list(e['loc']),'type':e['type']} for e in exc.errors()[:6]] if hasattr(exc,'errors') else []
        print(json.dumps({'live_provider_pass':False,'error_type':type(exc).__name__,
            'http_status':status,'diagnostic_markers':markers,
            'validation':validation,
            'domain_tools_executed':0,'tally_writes':0,'calls_max':1}))
        raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
