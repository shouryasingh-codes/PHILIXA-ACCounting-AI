"""Shared accounting validation; safe to package in the Windows helper."""
from app.services.tally_connector import TallyError, name, value

def match(rows, query):
    query = (query or "").strip().casefold()
    exact = [row for row in rows if name(row).casefold() == query]
    return exact or [row for row in rows if query and query in name(row).casefold()]

def uses_cost_centres(catalog, ledger):
    # Purchase/sales masters retain Yes by default even when the company
    # feature is explicitly disabled. Unknown company state stays conservative.
    return catalog.get('cost_centres_enabled', True) and value(ledger,'ISCOSTCENTRESON').casefold() == 'yes'


def safe_catalog(catalog, cfg):
    if not cfg.test_company or not catalog['non_gst']:
        raise TallyError('Writes sirf explicitly selected non-GST test company mein supported hain.')
    if len(catalog['godowns']) != 1 or name(catalog['godowns'][0]) != cfg.godown:
        raise TallyError('Pilot ke liye exactly ek configured godown chahiye.')
    for ledger, group in ((cfg.purchase_ledger,'Purchase Accounts'),(cfg.sales_ledger,'Sales Accounts')):
        rows = match(catalog['ledgers'],ledger)
        if len(rows) != 1 or name(rows[0]) != ledger or value(rows[0],'PARENT') != group:
            raise TallyError('Configured purchase/sales ledger ya group badal gaya. Connection setup dobara karein.')
        if uses_cost_centres(catalog, rows[0]):
            raise TallyError('Cost-centre purchase/sales ledger supported nahi hai.')


def validate_item(catalog, item, unit):
    if value(item,'ISBATCHWISEON').casefold() != 'no':
        raise TallyError('Batch-enabled ya unknown batch configuration supported nahi hai.')
    if any(value(item,flag).casefold() == 'yes' for flag in ('ISPERISHABLEON','HASMFGDATE','ISADDLCOSTTRACKINGON','ISSERIALNUMBERON')):
        raise TallyError('Is item ka advanced inventory setup supported nahi hai.')
    if value(item,'BASEUNITS') != unit or value(item,'ADDITIONALUNITS') not in ('','Not Applicable'):
        raise TallyError('Item ki base unit use karein; alternate units supported nahi hain.')
    rows = match(catalog['units'],unit)
    if len(rows) != 1 or name(rows[0]) != unit or value(rows[0],'ISSIMPLEUNIT').casefold() != 'yes':
        raise TallyError('Sirf existing simple unit supported hai.')
    return rows[0]


