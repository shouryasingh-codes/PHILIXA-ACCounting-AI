"""Service for creating missing Tally masters (Suppliers, Stock Items, Units) on demand.

Safe, idempotent, and directly bound to the user's active purchase draft.
"""
import copy
import logging
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from app.services.tally_connector import TallyConnector, TallyError, name, value, parse_xml
from app.services.tally_master_codec import (
    CREDITOR_GROUP,
    clean_stock_name,
    normalize_unit,
    batch_masters_xml,
)
from app.services import purchase_draft_service as drafts

logger = logging.getLogger(__name__)


async def create_missing_masters_in_tally(
    db, principal, draft_id: str, create_supplier: bool = True, create_items: bool = True
) -> dict:
    """Create missing masters in Tally Prime, refresh company snapshot, and update the draft."""
    from app.services.tally_sync import refresh_company, saved_snapshot, now
    from app.services.tally_sync_protocol import deserialize_catalog
    from app.services.purchase_situation import state as situation_state

    row = await drafts.scoped_draft(db, principal, draft_id, lock=True)
    company = await drafts.company_for(db, principal, row.company_id)

    # 1. Fetch current catalog from snapshot or live connector
    snapshot = await saved_snapshot(db, company)
    catalog = deserialize_catalog(snapshot.catalog) if snapshot else None
    if not catalog:
        connector = TallyConnector()
        catalog = await connector.catalog(company.name)

    existing_creditors = {
        name(l).casefold()
        for l in catalog.get('ledgers', [])
        if value(l, 'PARENT').casefold() == CREDITOR_GROUP.casefold()
    }
    existing_units = {name(u).casefold() for u in catalog.get('units', [])}
    existing_items = {name(i).casefold() for i in catalog.get('items', [])}

    ledgers_to_create = []
    units_to_create = []
    items_to_create = []

    content = copy.deepcopy(row.content)
    meta = row.extraction_metadata or {}

    # 2. Check Supplier
    raw_supplier = (
        (meta.get('field_evidence', {}).get('party_name', {}).get('value'))
        or (meta.get('source_evidence', {}).get('supplier_name', {}).get('raw'))
        or content.get('party_name')
        or ''
    ).strip()

    supplier_target = raw_supplier or content.get('party_name') or 'Supplier'

    if create_supplier and supplier_target:
        if supplier_target.casefold() not in existing_creditors:
            gstin = content.get('supplier_gstin')
            state_val = content.get('place_of_supply')
            ledgers_to_create.append({
                'name': supplier_target,
                'gstin': gstin,
                'state': state_val,
                'parent': CREDITOR_GROUP
            })

    # 3. Check Stock Items & Units
    lines = content.get('lines', [])
    line_name_mapping = {}

    if create_items:
        for idx, line in enumerate(lines):
            raw_item = line.get('item_name') or f"Item {idx + 1}"
            cleaned_name = clean_stock_name(raw_item)
            unit_name = normalize_unit(line.get('unit'))

            # Check if cleaned_name matches an existing item in catalog
            matching_existing = next(
                (i for i in catalog.get('items', []) if name(i).casefold() == cleaned_name.casefold()),
                None
            )

            if matching_existing:
                line_name_mapping[idx] = (name(matching_existing), unit_name)
            else:
                if unit_name.casefold() not in existing_units and unit_name not in units_to_create:
                    units_to_create.append(unit_name)

                if not any(i['name'].casefold() == cleaned_name.casefold() for i in items_to_create):
                    items_to_create.append({'name': cleaned_name, 'unit': unit_name})

                line_name_mapping[idx] = (cleaned_name, unit_name)

    # 4. If nothing to create, but draft lines need standardizing against existing masters:
    if not ledgers_to_create and not units_to_create and not items_to_create:
        updated = False
        if line_name_mapping:
            for idx, (c_name, u_name) in line_name_mapping.items():
                if idx < len(content['lines']):
                    if content['lines'][idx].get('item_name') != c_name or content['lines'][idx].get('unit') != u_name:
                        content['lines'][idx]['item_name'] = c_name
                        content['lines'][idx]['unit'] = u_name
                        updated = True

        matching_creditor = next(
            (l for l in catalog.get('ledgers', []) if name(l).casefold() == supplier_target.casefold() and value(l, 'PARENT').casefold() == CREDITOR_GROUP.casefold()),
            None
        )
        if matching_creditor and content.get('party_name') != name(matching_creditor):
            content['party_name'] = name(matching_creditor)
            updated = True

        if updated:
            row.content = content
            row.action_id = None
            row.revision += 1
            row.updated_at = now()
            await db.commit()

        reloaded = await drafts.scoped_draft(db, principal, row.id, lock=True)
        current_situation = await situation_state(db, principal, reloaded.id)
        return {
            'status': 'ok',
            'supplier_created': None,
            'items_created': [],
            'units_created': [],
            'draft_id': row.id,
            'revision': row.revision,
            'response': 'Tally masters check kar liye gaye hain aur draft sync ho gaya hai.',
            **current_situation
        }

    # 5. Build XML & post to Tally
    xml = batch_masters_xml(
        company.name,
        ledgers=ledgers_to_create,
        units=units_to_create,
        items=items_to_create
    )

    connector = TallyConnector()
    try:
        reply_xml = await connector.post(xml)
        logger.info(
            'Created masters in Tally: ledgers=%d, units=%d, items=%d',
            len(ledgers_to_create), len(units_to_create), len(items_to_create)
        )
    except Exception as exc:
        logger.error('Failed to post masters XML to Tally: %s', exc)
        raise TallyError(f'Tally me masters create nahi ho sake: {exc}')

    # 6. Refresh Company Masters Snapshot in database
    await refresh_company(db, company)

    # 7. Update Draft Content to bind to the newly created masters
    if ledgers_to_create:
        content['party_name'] = ledgers_to_create[0]['name']

    if create_items:
        for idx, (cleaned_name, unit_name) in line_name_mapping.items():
            if idx < len(content['lines']):
                content['lines'][idx]['item_name'] = cleaned_name
                content['lines'][idx]['unit'] = unit_name

    row.content = content
    row.action_id = None
    row.revision += 1
    row.updated_at = now()

    drafts.record_event(
        db,
        row,
        principal.user_id,
        'system:masters_created',
        {
            'supplier_created': [l['name'] for l in ledgers_to_create],
            'units_created': units_to_create,
            'items_created': [i['name'] for i in items_to_create],
        }
    )
    await db.commit()

    # 8. Re-evaluate proposal state after masters creation
    reloaded_draft = await drafts.scoped_draft(db, principal, row.id, lock=True)
    post_situation = await situation_state(db, principal, reloaded_draft.id)

    parts = []
    if ledgers_to_create:
        parts.append(f"{ledgers_to_create[0]['name']} (Sundry Creditors)")
    if items_to_create:
        parts.append(f"{len(items_to_create)} stock items")

    summary_str = f"Maine Tally me {' aur '.join(parts)} create kar diye hain! Ab aap bill ki review entry check kar sakte hain."

    return {
        'status': 'ok',
        'supplier_created': ledgers_to_create[0]['name'] if ledgers_to_create else None,
        'items_created': [i['name'] for i in items_to_create],
        'units_created': units_to_create,
        'draft_id': row.id,
        'revision': row.revision,
        'response': summary_str,
        'proposal': post_situation.get('proposal'),
        'issues': post_situation.get('issues', []),
        'can_preview': post_situation.get('can_preview'),
        'purchase_assistant': post_situation.get('purchase_assistant'),
    }
