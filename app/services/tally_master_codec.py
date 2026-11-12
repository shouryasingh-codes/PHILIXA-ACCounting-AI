"""Deterministic Tally master creation codecs (Supplier Ledgers, Stock Items, Units).

Generates standard, schema-valid Tally XML for All Masters import without model hallucinations.
Safe to import without DB or AI dependencies.
"""
import re
from xml.etree import ElementTree as ET
from app.services.tally_connector import tag, name, value, TallyError

CREDITOR_GROUP = 'Sundry Creditors'
DEFAULT_UNIT = 'Nos'


def clean_stock_name(raw: str) -> str:
    """Clean common OCR artifacts and extract standardized stock item name."""
    if not raw:
        return "Item"
    cleaned = raw.strip()
    # Fix OCR typos like 13-10100 -> i3-10100
    cleaned = re.sub(r'\b13-(\d{4,5})\b', r'i3-\1', cleaned, flags=re.IGNORECASE)
    # Remove verbose core/cache specs that don't belong in standard item master
    cleaned = re.sub(r'\s*\(\d+-Core.*?\)', '', cleaned, flags=re.IGNORECASE)
    # Standardize generation
    cleaned = re.sub(r'\(10th Generation\)', '(10th Gen)', cleaned, flags=re.IGNORECASE)
    # Collapse duplicate whitespace
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned


def normalize_unit(unit: str | None) -> str:
    """Normalize unit string to canonical Tally unit name."""
    u = (unit or '').strip()
    if not u or u.lower() in ('no', 'nos', 'no.', 'nos.'):
        return 'Nos'
    if u.lower() in ('pc', 'pcs', 'piece', 'pieces', 'pc.'):
        return 'Pcs'
    if u.lower() in ('box', 'boxes', 'bx'):
        return 'Box'
    if u.lower() in ('kg', 'kgs', 'kilogram', 'kilograms'):
        return 'Kgs'
    if u.lower() in ('bag', 'bags'):
        return 'bags'
    return u


def validate_master_identity(name_str: str, max_len: int = 120) -> str:
    if not isinstance(name_str, str):
        raise TallyError('Master name must be a string.')
    cleaned = name_str.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(c) < 32 for c in cleaned):
        raise TallyError(f'Invalid master name: {cleaned[:30]}')
    return cleaned


UQC_MAP = {
    'nos': ('NOS', 'NOS-NUMBERS', 'Numbers'),
    'pcs': ('PCS', 'PCS-PIECES', 'Pieces'),
    'box': ('BOX', 'BOX-BOX', 'Boxes'),
    'bags': ('BAG', 'BAG-BAGS', 'Bags'),
    'bag': ('BAG', 'BAG-BAGS', 'Bags'),
}


def build_unit_message(parent_req: ET.Element, unit_name: str) -> ET.Element:
    """Append a simple unit creation message to REQUESTDATA."""
    u_clean = validate_master_identity(unit_name, 50)
    msg = tag(parent_req, 'TALLYMESSAGE', **{'xmlns:UDF': 'TallyUDF'})
    unit_el = tag(msg, 'UNIT', NAME=u_clean, ACTION='Create')
    tag(unit_el, 'NAME', u_clean)
    tag(unit_el, 'ISSIMPLEUNIT', 'Yes')
    tag(unit_el, 'DECIMALPLACES', '0')
    gst_uom, uqc_name, orig = UQC_MAP.get(u_clean.lower(), ('OTH', 'OTH-OTHERS', u_clean))
    tag(unit_el, 'ORIGINALNAME', orig)
    tag(unit_el, 'GSTREPUOM', gst_uom)
    uqc_list = tag(unit_el, 'REPORTINGUQCDETAILS.LIST')
    tag(uqc_list, 'APPLICABLEFROM', '20200401')
    tag(uqc_list, 'REPORTINGUQCNAME', uqc_name)
    return msg


def build_ledger_message(parent_req: ET.Element, ledger_name: str, gstin: str | None = None,
                         state: str | None = None, parent: str = CREDITOR_GROUP) -> ET.Element:
    """Append a Sundry Creditor ledger creation message to REQUESTDATA."""
    l_clean = validate_master_identity(ledger_name, 120)
    msg = tag(parent_req, 'TALLYMESSAGE', **{'xmlns:UDF': 'TallyUDF'})
    ledger_el = tag(msg, 'LEDGER', NAME=l_clean, ACTION='Create')
    tag(ledger_el, 'NAME', l_clean)
    tag(ledger_el, 'PARENT', parent)
    tag(ledger_el, 'ISBILLWISEON', 'Yes')
    tag(ledger_el, 'ISCOSTCENTRESON', 'No')
    tag(ledger_el, 'OPENINGBALANCE', '0')
    if gstin and re.fullmatch(r'\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}', gstin.strip().upper()):
        tag(ledger_el, 'PARTYGSTIN', gstin.strip().upper())
    if state and isinstance(state, str) and len(state.strip()) <= 50:
        tag(ledger_el, 'LEDGERSTATENAME', state.strip())
    return msg


def build_stock_item_message(parent_req: ET.Element, item_name: str, unit: str = DEFAULT_UNIT) -> ET.Element:
    """Append a stock item creation message to REQUESTDATA."""
    i_clean = validate_master_identity(item_name, 200)
    u_clean = validate_master_identity(normalize_unit(unit), 50)
    msg = tag(parent_req, 'TALLYMESSAGE', **{'xmlns:UDF': 'TallyUDF'})
    item_el = tag(msg, 'STOCKITEM', NAME=i_clean, ACTION='Create')
    tag(item_el, 'NAME', i_clean)
    tag(item_el, 'BASEUNITS', u_clean)
    tag(item_el, 'ADDITIONALUNITS', 'Not Applicable')
    tag(item_el, 'OPENINGBALANCE', '0')
    tag(item_el, 'ISBATCHWISEON', 'No')
    tag(item_el, 'ISPERISHABLEON', 'No')
    tag(item_el, 'HASMFGDATE', 'No')
    tag(item_el, 'ISADDLCOSTTRACKINGON', 'No')
    tag(item_el, 'ISSERIALNUMBERON', 'No')
    return msg


def batch_masters_xml(company: str, *, ledgers: list[dict] | None = None,
                      units: list[str] | None = None,
                      items: list[dict] | None = None) -> str:
    """Construct an All Masters Import Data envelope for creating units, ledgers and stock items."""
    if not company or not company.strip():
        raise TallyError('Company name required for master creation.')

    root = ET.Element('ENVELOPE')
    tag(tag(root, 'HEADER'), 'TALLYREQUEST', 'Import Data')
    body = tag(root, 'BODY')
    import_data = tag(body, 'IMPORTDATA')
    desc = tag(import_data, 'REQUESTDESC')
    tag(desc, 'REPORTNAME', 'All Masters')
    tag(tag(desc, 'STATICVARIABLES'), 'SVCURRENTCOMPANY', company.strip())
    req_data = tag(import_data, 'REQUESTDATA')

    # 1. Units first so Stock Items can bind their BASEUNITS
    for u in (units or []):
        build_unit_message(req_data, u)

    # 2. Ledgers (Sundry Creditors)
    for l in (ledgers or []):
        build_ledger_message(req_data, l['name'], gstin=l.get('gstin'), state=l.get('state'), parent=l.get('parent', CREDITOR_GROUP))

    # 3. Stock Items
    for itm in (items or []):
        build_stock_item_message(req_data, itm['name'], unit=itm.get('unit', DEFAULT_UNIT))

    return ET.tostring(root, encoding='unicode')
