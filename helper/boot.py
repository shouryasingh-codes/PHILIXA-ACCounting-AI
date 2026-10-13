"""PyInstaller runtime hook: diagnose failures before application imports."""
import ctypes
import json
import os
from pathlib import Path
import sys
import time

def record(event, error=None):
    try:
        folder=Path(os.environ['LOCALAPPDATA'])/'PhilixaConnect'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'startup.log'
        if path.exists() and path.stat().st_size>100_000:path.write_text('',encoding='utf-8')
        with path.open('a',encoding='utf-8') as log:
            log.write(json.dumps({'time':int(time.time()),'event':event,'error':error})+'\n')
    except OSError:pass

def failure(kind,value,traceback):
    record('unhandled_startup_failure',kind.__name__)
    ctypes.windll.user32.MessageBoxW(None,
        'Philixa Tally Connector could not start. Reinstall from Philixa → Download Tally Connector. '
        'If Windows blocked the app, contact support. Diagnostic log: %LOCALAPPDATA%\\PhilixaConnect\\startup.log',
        'Philixa Tally Connector',16)

sys.excepthook=failure
record('python_boot')
