"""Update the existing paired helper; never creates pairing or posts vouchers."""
import hashlib,json,os,sqlite3,subprocess
from pathlib import Path

def main():
    from helper.connect import load_secret
    root=Path(__file__).resolve().parents[1]
    home=Path(os.environ['LOCALAPPDATA'])/'PhilixaConnect'
    candidate=root/'data/downloads/PhilixaTallyConnectorSetup-3.7.0.exe'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    expected='302A89169A8F101A39A9626A970B87A101CA69EF25B07AFA4853F65D2C2399A9'
    if sha(candidate).upper()!=expected:raise RuntimeError('Installer integrity mismatch')
    secret=load_secret()
    if not secret:raise RuntimeError('Existing pairing unavailable; update stopped')
    settings=json.loads((home/'settings.json').read_text())
    result=root/'output/purchase-agent-helper-install.json'
    process=subprocess.run([str(candidate),'--install-only',str(result)],timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
    installed=json.loads(result.read_text())
    after=json.loads((home/'settings.json').read_text())
    with sqlite3.connect((home/'sync.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    proof=dict(installer=installed,exit_code=process.returncode,installed_matches_candidate=sha(home/'PhilixaConnect.exe')==sha(candidate),
        pairing_preserved=load_secret()==secret,journal_integrity=integrity,
        changed_setting_keys=[k for k,v in settings.items() if after.get(k)!=v],
        connection_settings_preserved=all(after.get(k)==v for k,v in settings.items() if k not in ('startup_configured','connector_version')),
        connector_version=after.get('connector_version'),posting=False)
    (root/'output/purchase-agent-helper-update.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof))
    if process.returncode or not all(proof[k] for k in ('installed_matches_candidate','pairing_preserved','connection_settings_preserved')) or integrity!='ok':raise SystemExit(1)

if __name__=='__main__':main()
