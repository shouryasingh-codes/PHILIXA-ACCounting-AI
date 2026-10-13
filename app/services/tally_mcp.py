"""Strict pinned contracts. No model-generated XML, URL, shell or direct write calls."""
from decimal import Decimal
import json
import math
from pathlib import Path
from jsonschema import Draft202012Validator
from app.services.tally_connector import TallyError

PIN = '6619585a351000dd979b046ff63408771435644a'
REGISTRY = json.loads(Path(__file__).with_name('tally_mcp_registry.json').read_text(encoding='utf-8'))
if REGISTRY['commit'] != PIN:
    raise RuntimeError('MCP registry pin mismatch')
CONTRACTS = {t['name']: t for t in REGISTRY['tools']}

def validate_arguments(tool, arguments, *, read_only=True):
    contract = CONTRACTS.get(tool)
    if not contract:
        raise TallyError('Unknown MCP tool.')
    if read_only and (contract['category'] != 'read' or contract['state'] != 'read_candidate'):
        raise TallyError('MCP capability prerequisite blocked.')
    if not isinstance(arguments, dict):
        raise TallyError('Invalid MCP arguments.')
    try: size=len(json.dumps(arguments, allow_nan=False))
    except (ValueError,TypeError,OverflowError):raise TallyError('Invalid MCP arguments.') from None
    if size>64000:raise TallyError('Invalid MCP arguments.')
    if next(Draft202012Validator(contract['inputSchema']).iter_errors(arguments), None):
        raise TallyError('MCP arguments do not match the pinned schema.')
    def safe(value, depth=0):
        if depth > 12: raise TallyError('MCP argument nesting exceeds limit.')
        if isinstance(value, str):
            # Upstream embeds names in TDL expressions. Reject expression/string escapes.
            if len(value) > 2000 or any(c in value for c in ('"','\\','\x00','\r','\n')):
                raise TallyError('Unsupported MCP field characters.')
        elif isinstance(value, (float, int)) and not isinstance(value, bool):
            if not math.isfinite(value) or abs(value) > 9007199254740991 or len(Decimal(str(value)).as_tuple().digits) > 15:
                raise TallyError('MCP numeric precision unsafe.')
        elif isinstance(value, dict):
            for v in value.values(): safe(v, depth+1)
        elif isinstance(value, list):
            if len(value)>1000: raise TallyError('MCP argument list exceeds limit.')
            for v in value: safe(v, depth+1)
    safe(arguments)
    return contract

def capability_view():
    return [{'tool': t['name'], 'category': t['category'], 'state': t['state'],
             'blocked_reason': t['blockedReason'], 'builder_available': t['builderAvailable']}
            for t in CONTRACTS.values()]
