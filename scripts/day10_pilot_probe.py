"""Read-only pilot recovery evidence. Never confirms or submits an action."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany, TallyAction
from app.models.purchase_draft import PurchaseDraft
from app.models.bill_document import BillDocument
from app.models.purchase_automation import PurchaseAutomationPolicy
from app.services.tally_connector import TallyConnector, name, company_identity
from app.services.tally_gst_purchase import verify


async def main(label):
    report = {'label': label, 'real_vouchers_posted': False}
    async with AsyncSessionLocal() as db:
        company = await db.scalar(select(TallyReadCompany).where(TallyReadCompany.name == 'Philixa Test', TallyReadCompany.enabled.is_(True)))
        if not company:
            raise RuntimeError('Approved test company unavailable')
        active = list((await db.scalars(select(TallyAction).where(TallyAction.company_id == company.id, TallyAction.status.in_(('queued','submitting','verification_pending'))))).all())
        policy = await db.get(PurchaseAutomationPolicy, company.id)
        report.update(active_actions=len(active), automation_mode=policy.data.get('mode') if policy else 'unset')
        rows = list((await db.scalars(select(PurchaseDraft).where(PurchaseDraft.company_id == company.id).order_by(PurchaseDraft.id))).all())
        documents = list((await db.scalars(select(BillDocument).where(BillDocument.company_id == company.id).order_by(BillDocument.id))).all())
        state = {'drafts':[(r.id,r.revision,r.content,r.action_id) for r in rows], 'documents':[(r.id,r.filename) for r in documents]}
        report.update(drafts=len(rows), documents=len(documents), durable_state_sha256=hashlib.sha256(json.dumps(state,sort_keys=True,default=str).encode()).hexdigest())
        from app.services.bill_document_service import original_bytes
        originals=[]
        for document in documents:
            try:
                originals.append(hashlib.sha256(await original_bytes(document)).hexdigest()==document.sha256)
            except Exception:
                originals.append(False)
        report['private_originals_checked']=len(originals)
        report['private_originals_intact']=bool(originals) and all(originals)
        if active or report['automation_mode'] not in ('paused','unset'):
            raise RuntimeError('Restart test requires no active accounting actions and paused automation')
        connector = TallyConnector()
        try:
            loaded = await connector.collection('Company')
            assert any(name(c)==company.name and company_identity(c)==company.identity for c in loaded), 'Approved company not loaded'
            action = await db.get(TallyAction, '22e86d253510d4528b17a5820c47de17')
            assert action and action.company_id==company.id and action.status=='verified', 'Prior verified dummy action unavailable'
            vouchers = await connector.collection('Voucher',company.name,action.payload['date'])
            matches = [v for v in vouchers if verify(v,action.payload)]
            report.update(native_readback_verified=len(matches)==1, approved_date=action.payload['date'], same_action=action.token)
        except Exception as exc:
            report.update(native_readback_verified=False,native_error=str(exc)[:250])
    root=Path('data/day10');root.mkdir(parents=True,exist_ok=True)
    (root/(label+'.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if not report.get('native_readback_verified') or not report.get('private_originals_intact'):
        raise SystemExit(1)


if __name__=='__main__':
    label=sys.argv[1] if len(sys.argv)>1 else 'probe'
    if label not in ('before-restart','after-restart','after-helper-update','probe'):
        raise SystemExit('Unsupported evidence label')
    asyncio.run(main(label))
