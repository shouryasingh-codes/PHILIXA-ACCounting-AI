"""Local development acceptance update. Never pairs a device or posts a voucher."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='bbb98016466a86e202b2137d822bb8b6195a392d7244f639d752dc87460f7d9d'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from helper.connect import load_secret
    home=Path(os.environ['LOCALAPPDATA'])/'PhilixaConnect'
    candidate=ROOT/'data/connector-candidates/PhilixaTallyConnectorSetup-3.7.1-mcp-candidate.exe'
    proof=json.loads(candidate.with_name(candidate.stem+'-acceptance.json').read_text(encoding='utf-8-sig'))
    if sha(candidate)!=EXPECTED or proof['sha256'].lower()!=EXPECTED:
        raise RuntimeError('Validated candidate identity mismatch')
    checks=proof['checks']
    if not all((checks['transport'].get('client_ready'),checks['transport'].get('async_client_ready'),
                checks['transport'].get('certificate_validation'),checks['history'].get('history_read'),
                checks['invoice'].get('duplicate_blocked'),checks['mcp'].get('stdio'))):
        raise RuntimeError('Packaged acceptance incomplete')
    # The connector will resume automatically. Do not start it over pending writes.
    query='''import asyncio
from sqlalchemy import select,func
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyAction
async def main():
 async with AsyncSessionLocal() as db:
  n=await db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.status.in_(['queued','submitting','verification_pending'])))
  print(n)
asyncio.run(main())
'''
    pending=subprocess.run(['docker','compose','-p','accounts-dev','exec','-T','app','python','-'],
                           cwd=ROOT,input=query,text=True,capture_output=True,check=True,timeout=20)
    if pending.stdout.strip()!='0': raise RuntimeError('Pending actions require review before update')
    credential=load_secret()
    if not credential: raise RuntimeError('Saved pairing unavailable; no update attempted')
    settings=json.loads((home/'settings.json').read_text(encoding='utf-8'))
    backup=ROOT/'.helper-build'/('repair-recovery-'+uuid.uuid4().hex)
    backup.mkdir()
    shutil.copyfile(home/'settings.json',backup/'settings.json')
    shutil.copyfile(home/'PhilixaConnect.exe',backup/'PhilixaConnect-previous.exe')
    with closing(sqlite3.connect((home/'sync.sqlite3').as_uri()+'?mode=ro',uri=True)) as old:
        with closing(sqlite3.connect(backup/'sync.sqlite3')) as saved:
            old.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()!=('ok',):
                raise RuntimeError('Backup journal integrity failed')
    result=ROOT/'output/connector-371-install-20261101.json'
    process=subprocess.run([str(candidate),'--install-only',str(result)],timeout=120,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    installed=json.loads(result.read_text(encoding='utf-8')) if result.exists() else {}
    after=json.loads((home/'settings.json').read_text(encoding='utf-8'))
    with closing(sqlite3.connect((home/'sync.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    report={'installed':installed.get('installed',False),'exit_code':process.returncode,
            'version':after.get('connector_version'),'installed_hash_matches':sha(home/'PhilixaConnect.exe')==EXPECTED,
            'pairing_preserved':load_secret()==credential,'journal_integrity':integrity,
            'connection_settings_preserved':all(after.get(k)==v for k,v in settings.items() if k not in ('connector_version','startup_configured')),
            'backup_directory':str(backup),'posting':False,'public_release':False}
    (ROOT/'output/connector-371-update-proof-20261101.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if not all((report['installed'],report['installed_hash_matches'],report['pairing_preserved'],
                report['connection_settings_preserved'],integrity=='ok',process.returncode==0)):
        raise RuntimeError('Update acceptance incomplete; recovery backup preserved')


if __name__=='__main__': main()
