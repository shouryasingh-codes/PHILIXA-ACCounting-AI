"""Read-only Day 7 acceptance against the already-authorized test company."""
import asyncio,json
from pathlib import Path
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany,TallyAction
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.services.tally_connector import TallyConnector,TallyError,name,company_identity
from app.services import purchase_identity as identity,purchase_memory_service as memory

async def main():
    report={'real_vouchers_posted':False}
    async with AsyncSessionLocal() as db:
        companies=list((await db.scalars(select(TallyReadCompany).where(TallyReadCompany.name=='Philixa Test',TallyReadCompany.enabled.is_(True)))).all())
        if len(companies)!=1:raise RuntimeError('One authorized Philixa Test company required.')
        company=companies[0];catalog=await memory.catalog_for(db,company)
        active=list((await db.scalars(select(TallyAction).where(TallyAction.company_id==company.id,TallyAction.status.in_(('queued','submitting','verification_pending'))))).all())
        report['active_actions']=len(active)
        row=await db.scalar(select(PurchaseDraft).join(BillDocument).where(PurchaseDraft.company_id==company.id,BillDocument.filename=='matching-ocr.jpeg'))
        if row:
            guard=identity.invoice_guard(company.id+':'+company.identity,catalog,row.content)
            try:await memory.check_local(db,row,guard);report['cross_format_duplicate_blocked']=False
            except TallyError as exc:report.update(cross_format_duplicate_blocked='Duplicate' in str(exc),app_reason=str(exc))
        else:
            guard=identity.invoice_guard(company.id+':'+company.identity,catalog,{'party_name':'Philixa GST TEST Supplier Local','invoice_number':'PHILIXA-UPLOAD-TEST-01','entry_date':'2026-10-02'})
        connector=TallyConnector()
        companies=await connector.collection('Company')
        if len([c for c in companies if name(c)==company.name and company_identity(c)==company.identity])!=1:raise TallyError('Authorized native company identity not loaded.')
        report['native_result']=await identity.check_native(connector,company.name,guard)
        report['native_duplicate_blocked']=report['native_result']['status']=='duplicate'
        from app.services import tally_sync as sync
        from app.core.redis import get_redis_client
        redis=await get_redis_client()
        try:report['installed_helper_protocol']=await redis.get('tally:protocol:'+company.device_id)
        finally:await redis.aclose()
        report['installed_helper_result']=await sync.operation(db,company,'invoice_reference_check',payload=guard)
        report['installed_helper_duplicate_blocked']=report['installed_helper_result']['status']=='duplicate'
        if row:report['review_draft']={'revision':row.revision,'action_id':row.action_id}

    Path('data/day7/live-native-duplicate-proof.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
if __name__=='__main__':asyncio.run(main())
