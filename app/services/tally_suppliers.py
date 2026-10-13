"""Scoped supplier master reads. No model answers, writes, RAG or generated SQL."""
from app.services.tally_connector import TallyError, name, value
from app.services.tally_stock import resolve_scope
from app.services.tally_sync import refresh_company, saved_snapshot
from app.services.tally_sync_protocol import deserialize_catalog
from app.services.tally_supplier_codec import supplier_rows


def choice(parsed, company, ledger):
    return {'name': company.name + ' / ' + name(ledger), 'command': {
        'intent': 'supplier_read', 'fields': {'company_id': company.id, 'party_name': name(ledger)}}}


async def read_suppliers(db, principal, parsed):
    if parsed.unsupported_reason:
        return {'response': parsed.unsupported_reason}
    scope = await resolve_scope(db, principal, parsed)
    if not scope:
        return {'response': 'Permitted Tally company nahi mili. Owner/admin se company access approve karwayein.', 'connect_tally': True}
    if parsed.company_scope == 'named' and not parsed.company_query and not parsed.company_id:
        return {'response': 'Kaunsi Tally company? Company ka naam bataiye.'}
    if parsed.company_query and not parsed.company_id and len(scope) > 1:
        return {'response': 'Company naam ambiguous hai; company select karein.', 'tally_choices': [
            {'name': c.name, 'command': {'intent': parsed.intent, 'fields': {'company_id': c.id, 'party_name': parsed.party_name}}} for c in scope]}
    if parsed.intent == 'supplier_read' and not parsed.party_name:
        return {'response': 'Kis supplier ki details? Naam bataiye.'}
    lines, choices, results = [], [], []
    for company in scope:
        live = False
        try:
            live = await refresh_company(db, company)
        except (TallyError, TimeoutError):
            pass
        try:
            snapshot = await saved_snapshot(db, company)
            if not snapshot:
                raise TallyError('No saved supplier data')
            catalog = deserialize_catalog(snapshot.catalog)
            suppliers = supplier_rows(catalog)
            query = (parsed.party_name or '').strip().casefold()
            matches = suppliers
            if parsed.intent == 'supplier_read':
                exact = [l for l in suppliers if name(l).casefold() == query]
                matches = exact or [l for l in suppliers if query in name(l).casefold()]
            # Re-check grants after transport before releasing ledger data.
            if company.id not in {c.id for c in await resolve_scope(db, principal, parsed)}:
                raise TallyError('Company access changed')
            if await saved_snapshot(db, company) is None:
                raise TallyError('Device access changed')
            source = 'live' if live else 'saved'
            lines.append(f'{company.name} — {"Tally live suppliers" if live else "Saved Tally suppliers (live unavailable)"}; read time: {snapshot.collected_at.isoformat()}')
            complete = 'groups' in snapshot.catalog
            if not complete:
                lines.append('Older connector: direct Sundry Creditors ledgers only; subgroup coverage unverified. Connector update required for complete list.')
            if not matches:
                if query:
                    others = [l for l in catalog['ledgers'] if name(l).casefold() == query]
                    lines.append(f'{parsed.party_name}: ledger exists under {value(others[0], "PARENT")}; supplier classification not verified.' if len(others) == 1 else 'Matching supplier nahi mila.')
                else:
                    lines.append('Is company mein matching supplier nahi mila.')
            elif parsed.intent == 'supplier_read' and len(matches) == 1:
                ledger = matches[0]
                lines.extend([name(ledger), 'Tally group: ' + value(ledger, 'PARENT')])
                for label, tag in [('Phone', 'LEDGERPHONE'), ('Mobile', 'LEDGERMOBILE'), ('Email', 'EMAIL'), ('Opening balance (Tally raw)', 'OPENINGBALANCE'), ('Closing balance (Tally raw)', 'CLOSINGBALANCE')]:
                    field = value(ledger, tag)
                    if field:
                        lines.append(label + ': ' + field)
                results.append({'company_id': company.id, 'company': company.name, 'name': name(ledger), 'group': value(ledger, 'PARENT'), 'data_source': source})
            else:
                lines.append(f'{len(matches)} suppliers match. Details ke liye naam select karein.')
                choices.extend(choice(parsed, company, l) for l in matches[:100])
                if len(matches) > 100:
                    lines.append('First 100 shown; supplier ka naam search karein.')
        except TallyError:
            lines.append(company.name + ': supplier data unavailable; connection/company access check karein.')
    return {'response': '\n'.join(lines), 'tally_choices': choices, 'supplier_results': results}
