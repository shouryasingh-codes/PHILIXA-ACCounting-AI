"""PyInstaller runtime hook: diagnose failures before application imports."""
import ctypes
import json
import os
from pathlib import Path
import sys
import time

def record(event, error=None):
    try:
        from helper.package_runtime import data_home
        folder=data_home()
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'startup.log'
        if path.exists() and path.stat().st_size>100_000:path.write_text('',encoding='utf-8')
        with path.open('a',encoding='utf-8') as log:
            log.write(json.dumps({'time':int(time.time()),'event':event,'error':error})+'\n')
    except OSError:pass

def failure(kind,value,traceback):
    record('unhandled_startup_failure',kind.__name__)
    try:
        from helper.network_diagnostics import record_failure
        from helper.package_runtime import data_home
        record_failure(value, data_home())
    except Exception: pass
    ctypes.windll.user32.MessageBoxW(None,
        'Philixa Tally Connector could not start. Reinstall from Philixa → Download Tally Connector. '
        'If Windows blocked the app, contact support. Diagnostic log: %LOCALAPPDATA%\\PhilixaConnect\\startup.log',
        'Philixa Tally Connector',16)

sys.excepthook=failure
record('python_boot')

# importlib.resources can resolve a frozen certifi module inside PYZ rather
# than its separately collected data. Use the packaged CA file explicitly;
# certificate verification stays enabled for every HTTPX client.
if getattr(sys,'frozen',False):
    from helper.tls import configure_bundled_ca
    try:
        configure_bundled_ca(sys._MEIPASS)
        record('bundled_ca_ready')
    except RuntimeError:
        record('bundled_ca_missing')
        raise
