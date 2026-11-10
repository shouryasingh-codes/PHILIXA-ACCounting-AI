"""Hash-pinned local update; preserve pairing/settings/journal. No vouchers."""
import hashlib,json,os,shutil,sqlite3,subprocess,uuid
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='5473307b93b3123e05d8e2e8d3ca820c45e7f4781f244e939e9c346799f0800b'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    from helper.connect import load_secret
    from helper.runtime import HOME
    home=HOME.resolve()
    if home!=Path('C:/Users/admin/AppData/Local/PhilixaConnect').resolve():raise RuntimeError('Wrong Windows user/data directory; update stopped')
    candidate=ROOT/'data/connector-candidates/PhilixaTallyConnectorSetup-3.8.0-mcp-candidate.exe'
    proof=json.loads(candidate.with_name(candidate.stem+'-acceptance.json').read_text(encoding='utf-8-sig'))
    if sha(candidate)!=EXPECTED or proof['sha256'].lower()!=EXPECTED:raise RuntimeError('Artifact hash mismatch')
    checks=proof['checks']
    if not all([checks['transport'].get('client_ready'),checks['transport'].get('async_client_ready'),
        checks['transport'].get('certificate_validation'),checks['receipt'].get('receipt_codecs'),
        checks['receipt'].get('protocol_version')==11,checks['history'].get('history_read'),
        checks['invoice'].get('duplicate_blocked'),checks['mcp'].get('direct_writes_blocked')]):raise RuntimeError('Packaged acceptance incomplete')
    preflight=subprocess.run(['docker','compose','exec','-T','app','python','-m','scripts.task_agent_preflight'],
        cwd=ROOT,capture_output=True,text=True,check=True,timeout=30)
    if any(json.loads(preflight.stdout).values()):raise RuntimeError('Active operations; update deferred')
    credential=load_secret()
    if not credential:raise RuntimeError('Existing pairing unavailable; no re-pair attempted')
    settings=json.loads((home/'settings.json').read_text(encoding='utf-8'))
    backup=ROOT/'.helper-build'/('connector-380-recovery-'+uuid.uuid4().hex);backup.mkdir()
    shutil.copy2(home/'settings.json',backup/'settings.json')
    shutil.copy2(home/'PhilixaConnect.exe',backup/'PhilixaConnect-previous.exe')
    with closing(sqlite3.connect((home/'sync.sqlite3').as_uri()+'?mode=ro',uri=True)) as source:
        with closing(sqlite3.connect(backup/'sync.sqlite3')) as saved:
            source.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity failed')
    result=ROOT/'output/connector-380-install.json'
    process=subprocess.run([str(candidate),'--install-only',str(result)],timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    installed=json.loads(result.read_text()) if result.exists() else {}
    after=json.loads((home/'settings.json').read_text(encoding='utf-8'))
    with closing(sqlite3.connect((home/'sync.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    report={'installed':installed.get('installed',False),'exit_code':process.returncode,
        'version':after.get('connector_version'),'installed_hash_matches':sha(home/'PhilixaConnect.exe')==EXPECTED,
        'pairing_preserved':load_secret()==credential,'journal_integrity':integrity,
        'settings_preserved':all(after.get(k)==v for k,v in settings.items() if k not in ('connector_version','startup_configured')),
        'backup_directory':str(backup),'posting':False,'public_release':False}
    (ROOT/'output/connector-380-update-proof.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    if not all([report['installed'],report['installed_hash_matches'],report['pairing_preserved'],report['settings_preserved'],integrity=='ok',process.returncode==0]):raise RuntimeError('Update acceptance incomplete; backup preserved')

if __name__=='__main__':main()
