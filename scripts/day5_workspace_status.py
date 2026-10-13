import asyncio
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyConnection
async def main():
 async with AsyncSessionLocal() as db:
  rows=await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test'))
  for row in rows:
   cfg=await db.get(TallyConnection,row.organization_id);print({'company_id':row.id,'org_id':row.organization_id,'identity':row.identity,'device':row.device_id,'config':{'company':cfg.company,'godown':cfg.godown,'purchase_ledger':cfg.purchase_ledger,'sales_ledger':cfg.sales_ledger,'test_company':cfg.test_company} if cfg else None})
asyncio.run(main())
