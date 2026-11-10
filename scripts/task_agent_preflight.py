"""Sanitized local worker-reload preflight; no native calls."""
import asyncio,json
from sqlalchemy import select,func
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyAction
from app.models.bill_document import BillDocument
from app.models.agent_task import AgentTask


async def main():
    async with AsyncSessionLocal() as db:
        actions=await db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.status.in_(['queued','submitting','verification_pending'])))
        documents=await db.scalar(select(func.count()).select_from(BillDocument).where(BillDocument.extraction_status=='processing'))
        tasks=await db.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.status=='running'))
        print(json.dumps({'active_actions':actions,'processing_documents':documents,'running_agent_tasks':tasks}))


if __name__=='__main__':asyncio.run(main())
