"""Per-user connector lifecycle. No credentials or accounting data in logs."""
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

VERSION = '3.5.1'
HOME = Path(os.environ.get('LOCALAPPDATA', '.')) / 'PhilixaConnect'
TASK = 'PhilixaTallyConnector-' + hashlib.sha256(getpass.getuser().encode()).hexdigest()[:12]
EXE = HOME / 'PhilixaConnect.exe'
SHORTCUT = Path(os.environ.get('APPDATA', '.')) / 'Microsoft/Windows/Start Menu/Programs/Philixa Tally Connector.lnk'

def milestone(event, error=None):
    # Fixed labels/type names only, never exception messages or payloads.
    HOME.mkdir(parents=True, exist_ok=True)
    path = HOME / 'startup.log'
    if path.exists() and path.stat().st_size > 100_000:
        path.write_text('', encoding='utf-8')
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'time': int(time.time()), 'event': event, 'error': error}) + '\n')

def read_settings():
    try:
        value = json.loads((HOME / 'settings.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        milestone('settings_invalid')
        raise RuntimeError('Saved settings unreadable. Reinstall preserves credentials; contact support before replacing pairing.')

def write_settings(settings):
    HOME.mkdir(parents=True, exist_ok=True)
    staged = HOME / 'settings.tmp'
    staged.write_text(json.dumps(settings), encoding='utf-8')
    staged.replace(HOME / 'settings.json')

def task_xml(user, executable):
    ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
    ET.register_namespace('', ns)
    def tag(parent, name, text=None, **attrs):
        node = ET.SubElement(parent, '{'+ns+'}'+name, attrs)
        if text is not None: node.text = text
        return node
    root = ET.Element('{'+ns+'}Task', {'version': '1.2'})
    triggers = tag(root, 'Triggers'); trigger = tag(triggers, 'LogonTrigger')
    tag(trigger, 'Enabled', 'true'); tag(trigger, 'UserId', user)
    principals = tag(root, 'Principals'); principal = tag(principals, 'Principal', id='User')
    tag(principal, 'UserId', user); tag(principal, 'LogonType', 'InteractiveToken'); tag(principal, 'RunLevel', 'LeastPrivilege')
    settings = tag(root, 'Settings')
    for name, value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                        ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),
                        ('StartWhenAvailable','true'),('Enabled','true'),('ExecutionTimeLimit','PT0S')]:
        tag(settings, name, value)
    restart = tag(settings, 'RestartOnFailure'); tag(restart,'Interval','PT1M'); tag(restart,'Count','999')
    actions = tag(root,'Actions', Context='User'); action = tag(actions,'Exec')
    tag(action,'Command',str(executable)); tag(action,'Arguments','--tray --managed')
    return ET.tostring(root, encoding='unicode', xml_declaration=False)

def powershell(script):
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    result = subprocess.run(['powershell.exe','-NoProfile','-WindowStyle','Hidden','-EncodedCommand',encoded],
                            creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, timeout=30)
    if result.returncode: raise RuntimeError('Windows setup failed')

def register_startup():
    user = subprocess.run(['whoami.exe'], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    path = HOME / 'startup-task.xml'
    path.write_text(task_xml(user, EXE), encoding='utf-16')
    result = subprocess.run(['schtasks.exe','/Create','/TN',TASK,'/XML',str(path),'/F'],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    if result.returncode: raise RuntimeError('Automatic startup could not be configured. Retry installation.')
    # Check registration before retiring the legacy Run entry.
    result = subprocess.run(['schtasks.exe','/Query','/TN',TASK,'/XML'], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    if result.returncode: raise RuntimeError('Automatic startup verification failed')
    SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    powershell("$ErrorActionPreference='Stop'; $w=New-Object -ComObject WScript.Shell; "
               + '$s=$w.CreateShortcut('+quote(SHORTCUT)+'); $s.TargetPath='+quote(EXE)
               + '; $s.WorkingDirectory='+quote(HOME)+'; $s.Save()')
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        try: winreg.DeleteValue(key, 'PhilixaConnect')
        except FileNotFoundError: pass
    write_settings({**read_settings(), 'startup_configured': True, 'connector_version': VERSION})
    milestone('startup_registered')

def remove_startup():
    subprocess.run(['schtasks.exe','/Delete','/TN',TASK,'/F'], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    if SHORTCUT.exists(): SHORTCUT.unlink()

def backoff(failures):
    return min(60, 2 ** min(failures, 6))
