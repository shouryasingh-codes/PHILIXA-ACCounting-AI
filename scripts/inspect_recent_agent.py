"""Read-only recent task diagnosis; no credentials or model requests."""
import asyncio,json
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.agent_task import AgentTask

async def main():
    async with AsyncSessionLocal() as db:
        rows=(await db.scalars(select(AgentTask).order_by(AgentTask.updated_at.desc()).limit(5))).all()
        for row in rows:
            state=row.state
            print(json.dumps(dict(id=row.id,status=row.status,messages=state.get('messages'),draft_id=state.get('draft_id'),summary=state.get('summary'),observations=state.get('observations',[])[-2:]),default=str,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
