"""Read-only purchase evidence. History is a suggestion, never invoice evidence."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from app.models.purchase_draft import PurchaseDraft
from app.models.tally import TallyAction


def rate_evidence(content, rows, today):
    """Use only exact supplier/item/unit matches within a bounded date window."""
    output = []
    try:
        ceiling = min(date.fromisoformat(content.get('entry_date') or str(today)), today)
    except ValueError:
        return output
    for index, line in enumerate(content.get('lines') or []):
        if line.get('rate') is not None or not content.get('party_name'):
            continue
        candidates = []
        for row in rows:
            old = row.content
            if old.get('party_name') != content['party_name']:
                continue
            try:
                stamp = date.fromisoformat(old.get('entry_date') or '')
            except ValueError:
                continue
            if not ceiling - timedelta(days=180) <= stamp <= ceiling:
                continue
            matches = [v for v in old.get('lines') or [] if
                       v.get('item_name') == line.get('item_name') and v.get('unit') == line.get('unit')]
            # Repeated items may have different pack/rate treatments: abstain.
            if len(matches) != 1 or not line.get('item_name') or not line.get('unit'):
                continue
            try:
                rate = Decimal(str(matches[0].get('rate')))
            except InvalidOperation:
                continue
            if not rate.is_finite() or rate <= 0:
                continue
            candidates.append((stamp, row.id, rate, old.get('invoice_number')))
        if not candidates:
            continue
        latest = max(v[0] for v in candidates)
        matches = [v for v in candidates if v[0] == latest]
        # Conflicting rates on the latest day require review, not an arbitrary pick.
        if len({v[2] for v in matches}) != 1:
            continue
        stamp, source, rate, invoice = sorted(matches, key=lambda v: v[1])[0]
        output.append(dict(field=f'{index}:rate', value=str(rate), source='verified_purchase',
                           draft_id=source, invoice_number=invoice, entry_date=str(stamp),
                           requires_confirmation=True))
    return output


async def collect(db, principal, row, today):
    # Only verified, still-active sources in the permitted company/workspace.
    from app.services.purchase_draft_service import active_source_filter
    history = (await db.scalars(select(PurchaseDraft).join(TallyAction, PurchaseDraft.action_id == TallyAction.token)
        .where(PurchaseDraft.organization_id == principal.organization_id,
               PurchaseDraft.company_id == row.company_id, PurchaseDraft.id != row.id,
               TallyAction.organization_id == principal.organization_id,
               TallyAction.company_id == row.company_id, TallyAction.status == 'verified',
               active_source_filter())
        .order_by(PurchaseDraft.updated_at.desc(), PurchaseDraft.id).limit(100))).all()
    return rate_evidence(row.content, history, today)


def pending_fields(content):
    required = ['party_name', 'invoice_number', 'entry_date', 'invoice_total']
    if content.get('tax_treatment'):
        required += ['supplier_gstin', 'place_of_supply', 'expected_taxes']
    missing = [key for key in required if content.get(key) in (None, '', {})]
    keys = ['item_name', 'quantity', 'unit', 'rate']
    if content.get('tax_treatment'):
        keys += ['gst_rate', 'hsn', 'taxable_amount']
    for index, line in enumerate(content.get('lines') or []):
        missing += [f'{index}:{key}' for key in keys if line.get(key) in (None, '')]
    return missing


def pending_labels(content):
    labels = dict(party_name='supplier', invoice_number='invoice number', entry_date='bill date',
                  invoice_total='final total', supplier_gstin='supplier GSTIN', place_of_supply='supply state',
                  expected_taxes='tax breakup', item_name='item', quantity='quantity', unit='unit', rate='rate',
                  gst_rate='GST rate', hsn='HSN', taxable_amount='taxable amount')
    result = []
    for field in pending_fields(content):
        index, key = field.split(':') if ':' in field else (None, field)
        result.append((f'item {int(index)+1} ' if index is not None else '')+labels[key])
    return result
