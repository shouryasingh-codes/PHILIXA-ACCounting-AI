"""Connection diagnostics are advisory; authorization stays in existing services."""
import hashlib

def live_key(device, identity):
    suffix = hashlib.sha256((device.credential_hash + ':' + identity).encode()).hexdigest()
    return 'tally:live-proof:' + device.id + ':' + suffix

def connection_state(paired, online, diagnostics, companies):
    if not paired: return 'setup_needed'
    if not online: return 'connector_offline'
    if not diagnostics or diagnostics.get('connector_version') not in ('3.1.0','3.1.1','3.2.0','3.2.1','3.3.0','3.3.1','3.4.0','3.5.0','3.5.1'): return 'update_required'
    if not diagnostics.get('startup_configured'): return 'setup_needed'
    if diagnostics.get('tally_state') == 'closed': return 'tally_closed'
    if diagnostics.get('tally_state') != 'available': return 'tally_unreachable'
    if not companies: return 'company_approval_needed'
    if any(not c.get('reachable') for c in companies): return 'company_unavailable'
    if not all(c.get('stock_read_verified') for c in companies): return 'checking'
    return 'live_available'
