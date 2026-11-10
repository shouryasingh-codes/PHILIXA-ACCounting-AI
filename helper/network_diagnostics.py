"""Allowlisted diagnostic records: never serialize exception messages or locals."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def failure_record(exc, resources=()):
    frames = traceback.extract_tb(exc.__traceback__)
    keylog = os.environ.get('SSLKEYLOGFILE')
    return {
        'time': int(time.time()), 'event': 'network_client_failure',
        'exception_type': type(exc).__name__,
        'frames': [{'module': Path(f.filename).name, 'line': f.lineno,
                    'function': f.name} for f in frames[-12:]],
        # Known resource labels only. Paths/messages from the exception are private.
        'resources': [{'label': label, 'exists': Path(path).is_file(),
                       'resolved_path': _safe_path(path)}
                      for label, path in resources if label in ('certifi_ca', 'bundle_ca')],
        'frozen': bool(getattr(sys, 'frozen', False)),
        'ssl_keylog_configured': bool(keylog),
        'ssl_keylog_parent_exists': Path(keylog).parent.is_dir() if keylog else None,
    }


def _safe_path(path):
    import os
    value = str(Path(path).resolve())
    profile = os.environ.get('USERPROFILE')
    return value.replace(profile, '%USERPROFILE%') if profile else value


def record_failure(exc, home):
    import certifi
    resources = [('certifi_ca', certifi.where())]
    if hasattr(sys, '_MEIPASS'):
        resources.append(('bundle_ca', Path(sys._MEIPASS) / 'certifi' / 'cacert.pem'))
    value = failure_record(exc, resources)
    folder = Path(home)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'network-diagnostics.jsonl'
    if target.exists() and target.stat().st_size > 100_000:
        target.write_text('', encoding='utf-8')
    with target.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(value) + '\n')
    return value
