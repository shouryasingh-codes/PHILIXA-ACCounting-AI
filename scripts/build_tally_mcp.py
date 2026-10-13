"""Build an isolated adapter. Never edit the pinned upstream source tree."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'third_party' / 'tally_mcp'
BUILD = ROOT / 'integration' / 'tally_mcp'
PIN = '6619585a351000dd979b046ff63408771435644a'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build():
    BUILD.mkdir(parents=True, exist_ok=True)
    provenance=json.loads((BUILD/'upstream.json').read_text(encoding='utf-8'))
    if provenance.get('commit')!=PIN:raise RuntimeError('Pinned source provenance mismatch')
    for relative,expected in provenance['files'].items():
        original=(SOURCE/relative).resolve()
        if not original.is_relative_to(SOURCE.resolve()) or digest(original)!=expected:
            raise RuntimeError('Pinned source changed; review patches instead of overwriting upstream')
    for directory in ('src', 'templates'):
        shutil.copytree(SOURCE / directory, BUILD / directory, dirs_exist_ok=True)
    for filename in ('tsconfig.json', 'LICENSE'):
        shutil.copy2(SOURCE / filename, BUILD / filename)
    path = BUILD / 'src' / 'tools.ts'
    code = path.read_text(encoding='utf-8')
    old = 'async function buildWriteXml(toolName: string, args: Record<string, unknown>): Promise<string>'
    if code.count(old) != 1:
        raise RuntimeError('Pinned builder patch no longer matches')
    patched=code.replace(old, 'export ' + old)
    anchor='  const a = args as any;\n  switch (toolName) {'
    batch='''  const a = args as any;
  if (toolName === "create_vouchers_batch") {
    if (!Array.isArray(a.vouchers) || a.vouchers.length === 0 || a.vouchers.length > 50) throw new Error("batch_size_invalid");
    const keys = a.vouchers.map((v: any) => `${v.voucherType}:${v.narration}`);
    if (new Set(keys).size !== keys.length) throw new Error("batch_identity_ambiguous");
    return createVouchersBatchXml(a.vouchers.map(buildVoucherBatchEntry));
  }
  switch (toolName) {'''
    if patched.count(anchor)!=1:raise RuntimeError('Pinned batch adapter patch no longer matches')
    path.write_text(patched.replace(anchor,batch), encoding='utf-8')
    shutil.copy2(BUILD / 'entry.ts', BUILD / 'src' / 'philixa.ts')
    npm = shutil.which('npm.cmd') or shutil.which('npm')
    subprocess.run([npm, 'run', 'build'], cwd=BUILD, check=True)
    node = shutil.which('node')
    exported = subprocess.check_output([node, '--input-type=module', '-e',
        "import {tools} from './dist/tools.js'; process.stdout.write(JSON.stringify(tools));"], cwd=BUILD)
    tools = json.loads(exported)
    builder = code[code.index(old):code.index('export async function handleTool')]
    builder_names = set(re.findall(r'case "([a-z_]+)":', builder))
    builder_names.add('create_vouchers_batch')
    registry = []
    for tool in tools:
        n = tool['name']
        category = ('write' if n.startswith(('create_', 'update_', 'delete_')) or n == 'set_bill_of_materials'
                    else 'context' if n in ('set_company','set_period')
                    else 'approval' if n in ('preview_write','confirm_write')
                    else 'audit' if n == 'get_audit_log' else 'cache' if n.startswith('sync_') or n == 'query_sql' else 'read')
        schema = tool['inputSchema']
        def close_objects(s):
            if not isinstance(s, dict): return
            if s.get('type') == 'object' or 'properties' in s:
                s['additionalProperties'] = False
            for v in s.values():
                if isinstance(v, dict): close_objects(v)
                elif isinstance(v, list):
                    for item in v: close_objects(item)
        close_objects(schema)
        registry.append({**tool, 'category': category, 'builderAvailable': n in builder_names,
            'state': 'read_candidate' if category == 'read' else 'prerequisite_blocked',
            'permission': 'company_read' if category == 'read' else 'owner_admin_explicit_operation',
            'preview': 'typed_fields' if category == 'write' else 'none',
            'verification': 'voucher_guid_and_report' if category == 'write' and any(k in n for k in ('invoice','voucher','note','order','stock','material','rejection','quotation')) else 'master_guid_and_fields' if category == 'write' else 'scoped_read',
            'blockedReason': None if category == 'read' else {
                'write':'durable_dispatch_and_live_acceptance_required',
                'context':'session_context_adapter_required','cache':'session_scoped_cache_adapter_required',
                'approval':'replaced_by_philixa_durable_approval','audit':'workspace_scoped_audit_adapter_required'}[category]})
    (BUILD / 'registry.json').write_text(json.dumps({'commit': PIN, 'tools': registry}, indent=2), encoding='utf-8')
    # Registry travels with the server and the server-side policy package.
    target = ROOT / 'app' / 'services' / 'tally_mcp_registry.json'
    shutil.copy2(BUILD / 'registry.json', target)
    original = provenance['files']
    files = {str(p.relative_to(BUILD)).replace('\\','/'): digest(p) for folder in ('dist','templates')
             for p in (BUILD / folder).rglob('*') if p.is_file()}
    for f in ('package.json','package-lock.json','LICENSE','registry.json'): files[f] = digest(BUILD / f)
    (BUILD / 'manifest.json').write_text(json.dumps({'commit': PIN, 'adapter': '0.1.0',
        'originalFiles': original, 'runtimeFiles': files, 'tools': len(registry)}, indent=2), encoding='utf-8')
    print(f'Built {len(registry)} contracts. Writes remain prerequisite-blocked.')

if __name__ == '__main__': build()
