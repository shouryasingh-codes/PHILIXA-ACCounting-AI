"""One-time, resumable migration. Caller must hold the shared instance mutex.

SQLite backup API captures WAL consistently. Source files are never removed.
The caller must drain the legacy helper before calling this function.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def migrate(legacy, destination):
    legacy, destination = Path(legacy), Path(destination)
    if legacy.resolve() == destination.resolve():
        return False
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / 'migration-v1.json'
    if marker.exists():
        state = json.loads(marker.read_text(encoding='utf-8'))
        if not isinstance(state, dict) or state.get('version') != 1:
            raise RuntimeError('Migration marker invalid; recovery review required')
        if (destination / 'sync.sqlite3').exists():
            with closing(sqlite3.connect((destination / 'sync.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                    raise RuntimeError('Saved journal integrity check failed')
        return False
    tracked = ('settings.json', 'sync.sqlite3')
    # Never overwrite data created by a previous packaged session without a marker.
    # A partial migration uses staging files only, so existing final files are unsafe.
    pending = destination / 'migration-pending.json'
    if pending.exists():
        evidence = json.loads(pending.read_text(encoding='utf-8'))
        if not isinstance(evidence, dict) or not set(evidence).issubset(tracked):
            raise RuntimeError('Invalid interrupted migration record')
        for name, expected in evidence.items():
            content = (destination / 'legacy-backup-v1' / (name + '.staged')).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError('Interrupted migration backup changed')
            (destination / name).write_bytes(content)
        _finish(destination, evidence)
        return True
    if any((destination / name).exists() for name in tracked):
        raise RuntimeError('Migration destination already contains data; recovery review required')
    evidence = {}
    backup = destination / 'legacy-backup-v1'
    backup.mkdir(exist_ok=True)
    for name in tracked:
        source = legacy / name
        if not source.exists():
            continue
        target = backup / (name + '.staged')
        if name.endswith('.sqlite3'):
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
                with closing(sqlite3.connect(target)) as new:
                    old.backup(new)
                    if new.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                        raise RuntimeError('Legacy journal integrity check failed')
        else:
            value = json.loads(source.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise RuntimeError('Legacy settings invalid')
            target.write_text(json.dumps(value), encoding='utf-8')
        evidence[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    # Staging survives interruption; final promotion is tracked by a recovery record.
    pending.write_text(json.dumps(evidence), encoding='utf-8')
    for name in evidence:
        content = (backup / (name + '.staged')).read_bytes()
        (destination / name).write_bytes(content)
    _finish(destination, evidence)
    return True


def _finish(destination, evidence):
    if 'settings.json' in evidence:
        if not isinstance(json.loads((destination / 'settings.json').read_text(encoding='utf-8')), dict):
            raise RuntimeError('Migrated settings invalid')
    if 'sync.sqlite3' in evidence:
        with closing(sqlite3.connect(destination / 'sync.sqlite3')) as db:
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise RuntimeError('Migrated journal integrity check failed')
    temporary = destination / 'migration-marker.tmp'
    temporary.write_text(json.dumps({'version': 1, 'files': evidence,
                                     'legacy_startup_retired': False}), encoding='utf-8')
    temporary.replace(destination / 'migration-v1.json')
    (destination / 'migration-pending.json').unlink()
