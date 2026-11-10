"""Stable synthetic master identities for invoice-protection tests."""
import hashlib
from app.models.tally import TallySnapshot
from app.services.tally_sync_protocol import deserialize_catalog,serialize_catalog
from app.services.tally_connector import tag,name,value

async def master_ids(db,company_id):
    snapshot=await db.get(TallySnapshot,company_id)
    catalog=deserialize_catalog(snapshot.catalog)
    for kind in ('ledgers','items'):
        for row in catalog[kind]:
            if not value(row,'GUID'):tag(row,'GUID',hashlib.sha256((kind+name(row)).encode()).hexdigest())
    snapshot.catalog=serialize_catalog(catalog)
    await db.commit()
