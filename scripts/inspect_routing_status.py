"""Content-free routing/provider diagnostics; no keys, prompts or documents."""
import asyncio,json,sys
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.business_route import BusinessRoute
from app.models.groq_quota import GroqQuotaRequest


async def main():
    async with AsyncSessionLocal() as db:
        query=select(BusinessRoute)
        if '--user-only' in sys.argv:query=query.where(BusinessRoute.organization_id!='routing-synthetic-evaluation')
        rows=(await db.scalars(query.order_by(BusinessRoute.created_at.desc()).limit(5))).all()
        for row in rows:
            requests=(await db.scalars(select(GroqQuotaRequest).where(GroqQuotaRequest.task_id==row.id))).all()
            print(json.dumps({'route_id':row.id,'status':row.status,'version':row.version,
                'path':row.telemetry.get('path'),'failure':row.telemetry.get('failure_type') or row.result.get('failure'),
                'total_ms':row.telemetry.get('total_ms'),'classification_ms':row.telemetry.get('classification_ms'),
                'providers':[{'status':r.status,'tokens':r.charged_tokens,'http_status':r.metadata_json.get('http_status'),
                    'latency_ms':r.metadata_json.get('latency_ms'),'usage':r.metadata_json.get('usage')} for r in requests]}))


if __name__=='__main__':asyncio.run(main())
