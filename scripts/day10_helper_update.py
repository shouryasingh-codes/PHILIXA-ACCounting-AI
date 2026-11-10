"""Authorized per-user pilot update; compare pairing/journal without exposing secrets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    from helper.connect import load_secret
    from helper.runtime import TASK
    root=Path(__file__).resolve().parents[1]
    output=root/'data/day10'
    home=Path(os.environ['LOCALAPPDATA'])/'PhilixaConnect'
    candidate=output/'installer/PhilixaTallyConnectorSetup-3.6.0.exe'
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    secret=load_secret()
    if not secret:
        raise RuntimeError('Existing pilot pairing required; no new pairing will be created')
    settings=json.loads((home/'settings.json').read_text())
    journal=digest(home/'sync.sqlite3')
    previous=digest(home/'PhilixaConnect.exe')
    result=output/'helper-install.json'
    process=subprocess.run([str(candidate),'--install-only',str(result)],timeout=120,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    installed=json.loads(result.read_text())
    task=subprocess.run(['schtasks.exe','/Query','/TN',TASK,'/XML'],capture_output=True,timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW)
    after=json.loads((home/'settings.json').read_text())
    proof={'installer':installed,'exit_code':process.returncode,
           'candidate_sha256':digest(candidate),'previous_sha256':previous,
           'installed_matches_candidate':digest(home/'PhilixaConnect.exe')==digest(candidate),
           'pairing_preserved':load_secret()==secret,
           'journal_preserved':digest(home/'sync.sqlite3')==journal,
           'connection_settings_preserved':all(after.get(k)==v for k,v in settings.items() if k!='startup_configured'),
           'startup_task_registered':task.returncode==0,'real_vouchers_posted':False}
    (output/'helper-update-proof.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof))
    if process.returncode or not all(proof[k] for k in ('installed_matches_candidate','pairing_preserved','journal_preserved','connection_settings_preserved','startup_task_registered')):
        raise SystemExit(1)


if __name__=='__main__':main()
