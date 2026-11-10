"""Retire legacy startup only after authenticated heartbeat AND native discovery.

No executable deletion, credential mutation, installation or scheduled-task creation.
Keep the exported startup XML and original files for recovery.
"""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def retire_after_verified_read(home, task_name, packaged_startup_enabled):
    if not packaged_startup_enabled:
        return False
    marker = Path(home) / 'migration-v1.json'
    if not marker.exists():
        return False
    state = json.loads(marker.read_text(encoding='utf-8'))
    if state.get('legacy_startup_retired'):
        return True
    expected = Path(os.environ['LOCALAPPDATA']) / 'PhilixaConnect' / 'PhilixaConnect.exe'
    result = subprocess.run(['schtasks.exe','/Query','/TN',task_name,'/XML'],
                            capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode == 0:
        root = ET.fromstring(result.stdout)
        commands = root.findall('.//{*}Exec/{*}Command')
        if len(commands) != 1 or Path(commands[0].text or '').resolve() != expected.resolve():
            raise RuntimeError('Legacy startup identity changed; retirement withheld')
        backup = Path(home) / 'legacy-backup-v1' / 'startup-task.xml'
        backup.write_bytes(result.stdout)
        deleted = subprocess.run(['schtasks.exe','/Delete','/TN',task_name,'/F'],
                                 capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if deleted.returncode:
            raise RuntimeError('Legacy startup retirement incomplete')
    else:
        # A query error is not evidence that no task exists. Preserve recovery state.
        raise RuntimeError('Legacy startup could not be inspected')
    state['legacy_startup_retired'] = True
    staged = marker.with_suffix('.tmp')
    staged.write_text(json.dumps(state), encoding='utf-8'); staged.replace(marker)
    return True
