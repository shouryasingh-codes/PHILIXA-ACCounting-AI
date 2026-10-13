import asyncio,json,secrets
from xml.etree import ElementTree as E
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyConnection,TallyDevice,PurchaseTaxProfile
from app.services.tally_connector import TallyConnector,value,name,stock_row,company_identity
from app.services.tally_sync_protocol import serialize_catalog
from app.services import tally_sync as sync
from scripts.day5_native_setup import ROOT,COMPANY,PREFIX
async def main():
 cat=await TallyConnector().catalog(COMPANY)
 async with AsyncSessionLocal() as db:
  rows=list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name==COMPANY,TallyReadCompany.enabled.is_(True)))).all());assert len(rows)==1;co=rows[0];assert co.identity==company_identity(cat['companies'][0]);cfg=await db.get(TallyConnection,co.organization_id);assert cfg.test_company and cfg.company==COMPANY
  backup=ROOT/'workspace-config-before.json'
  if not backup.exists():backup.write_text(json.dumps(sync.config_data(cfg),indent=2))
  cfg.purchase_ledger=PREFIX+'Purchase';cfg.version+=1
  data={'ledgers':{h:PREFIX+'Input '+h for h in ('CGST','SGST','IGST')},'rounding_ledger':PREFIX+'Round Off'};profile=await db.get(PurchaseTaxProfile,co.id)
  if profile:profile.data=data;profile.revision+=1
  else:db.add(PurchaseTaxProfile(company_id=co.id,data=data,revision=1))
  dev=await db.get(TallyDevice,co.device_id)
  await sync.publish_snapshot(db,co,dict(generation=secrets.token_hex(16),identity=co.identity,device_version=dev.credential_hash,as_of='2026-10-14',collected_at=sync.now(),catalog=serialize_catalog(cat),items=[stock_row(r,cat['units']) for r in cat['items']]))
  await db.commit();print('GST practice profile configured; native snapshot saved; existing credentials preserved.')
asyncio.run(main())
