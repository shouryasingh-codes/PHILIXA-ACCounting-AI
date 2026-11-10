"""Scoped heartbeat/native read and receipt validation only; never posts."""
import asyncio,json
from pathlib import Path
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask
from app.models.tally import TallyAction,TallyConnection
from app.jobs.task_agent_jobs import principal_for
from app.api.v1.routes_tally_bridge import helper_status
from app.services import tally_sync as sync,purchase_draft_service as drafts

async def main():
    report=json.loads(Path('data/live-situation-acceptance.json').read_text())
    async with AsyncSessionLocal() as db:
        task=await db.get(AgentTask,report['task_id']);principal=await principal_for(db,task)
        company=await drafts.company_for(db,principal,task.company_id)
        status=await helper_status(principal,db)
        proof={'online':status['online'],'protocol_version':status['protocol_version'],
            'goods_receipt_capable':status.get('goods_receipt_capable'),
            'purchase_history_capable':status.get('purchase_history_capable'),'posting':False}
        if not proof['online'] or proof['protocol_version']!=11:raise RuntimeError('Updated connector heartbeat not verified')
        await sync.refresh_company(db,company)
        snapshot=await sync.saved_snapshot(db,company)
        proof['native_snapshot_read']=bool(snapshot)
        # Receipt validation is action-authorised and expects queued state;
        # never promote a preview merely to test connectivity.
        proof['receipt_native_validation']='not_run_requires_separately_authorised_action'
        Path('data/connector-380-live-proof.json').write_text(json.dumps(proof,indent=2))
        print(json.dumps(proof))

if __name__=='__main__':asyncio.run(main())
