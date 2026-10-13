"""Philixa Tally Connector unsigned Windows pilot. Only outbound HTTPS and local reads."""
import asyncio
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlsplit
import winreg
import httpx
import psutil
import pystray
from PIL import Image, ImageDraw
from helper.runtime import VERSION, EXE, register_startup, remove_startup, read_settings, write_settings, milestone, backoff, TASK
from app.services.tally_connector import local_operation, TallyError
from app.services.tally_sync_protocol import execute_sync, OPERATIONS, PROTOCOL_VERSION

HOME = Path(os.environ['LOCALAPPDATA']) / 'PhilixaConnect'
CONFIG = HOME / 'settings.json'
TARGET = 'PhilixaConnect/device'
os.environ['PHILIXA_TALLY_HOST'] = '127.0.0.1'

class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]

advapi = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
advapi.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
advapi.CredFree.argtypes = [ctypes.c_void_p]
kernel = ctypes.WinDLL('Kernel32.dll', use_last_error=True)
kernel.CreateEventW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.SetEvent.argtypes = kernel.ResetEvent.argtypes = [wintypes.HANDLE]
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
STOP_EVENT = 'Local\\PhilixaConnectStop'
SHOW_EVENT = 'Local\\PhilixaTallyConnectorShow'
kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
INSTANCE_HANDLE = None

def claim_instance(installer=False):
    global INSTANCE_HANDLE
    import getpass, hashlib
    name='Local\\PhilixaTallyConnector-'+hashlib.sha256(getpass.getuser().encode()).hexdigest()[:12]+('-setup' if installer else '')
    INSTANCE_HANDLE=kernel.CreateMutexW(None,False,name)
    if ctypes.get_last_error()==183:
        kernel.SetEvent(kernel.CreateEventW(None,True,False,SHOW_EVENT+('-setup' if installer else '')))
        kernel.CloseHandle(INSTANCE_HANDLE);INSTANCE_HANDLE=None
        return False
    return True

def start_managed():
    result=subprocess.run(['schtasks.exe','/Run','/TN',TASK],capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
    if result.returncode:raise RuntimeError('Automatic startup unavailable. Reinstall Tally Connector from Philixa.')
    kernel.SetEvent(kernel.CreateEventW(None,True,False,SHOW_EVENT))


def save_secret(secret):
    raw = secret.encode()
    buf = (ctypes.c_byte * len(raw)).from_buffer_copy(raw)
    cred = Credential(Type=1, TargetName=TARGET, CredentialBlobSize=len(raw), CredentialBlob=buf, Persist=2, UserName='Philixa')
    if not advapi.CredWriteW(ctypes.byref(cred), 0): raise ctypes.WinError(ctypes.get_last_error())

def load_secret():
    cred = ctypes.POINTER(Credential)()
    if not advapi.CredReadW(TARGET, 1, 0, ctypes.byref(cred)): return ''
    try: return ctypes.string_at(cred.contents.CredentialBlob, cred.contents.CredentialBlobSize).decode()
    finally: advapi.CredFree(cred)

def install():
    if not getattr(sys, 'frozen', False): raise RuntimeError('Install packaged executable only')
    HOME.mkdir(parents=True, exist_ok=True)
    destination = EXE
    staged, backup = HOME / 'connector-update.tmp', HOME / 'connector-previous.tmp'
    replacing = Path(sys.executable).resolve() != destination.resolve()
    if replacing:
        # Ask the old helper to drain an active operation. Never terminate a writer.
        kernel.SetEvent(kernel.CreateEventW(None,True,False,STOP_EVENT))
        deadline=time.monotonic()+30
        while any((p.info.get('exe') or '').casefold()==str(destination).casefold()
                  for p in psutil.process_iter(['exe'])):
            if time.monotonic()>deadline:
                kernel.ResetEvent(kernel.CreateEventW(None,True,False,STOP_EVENT))
                raise RuntimeError('Connector busy. Update deferred; existing connector remains active. Retry after current entry finishes.')
            time.sleep(.25)
        shutil.copy2(sys.executable,staged)
        if destination.exists(): shutil.copy2(destination,backup)
        staged.replace(destination)
    try:
        register_startup()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PhilixaConnect') as key:
            for name,value in {'DisplayName':'Philixa Tally Connector (unsigned pilot)',
                               'UninstallString':f'"{destination}" --uninstall','InstallLocation':str(HOME)}.items():
                winreg.SetValueEx(key,name,0,winreg.REG_SZ,value)
    except Exception:
        if replacing and backup.exists(): backup.replace(destination)
        write_settings({**read_settings(),'startup_configured':False})
        raise
    finally:
        if staged.exists(): staged.unlink()
    if backup.exists(): backup.unlink()
    milestone('install_complete')

def uninstall():
    remove_startup()
    kernel.SetEvent(kernel.CreateEventW(None,True,False,STOP_EVENT))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        try: winreg.DeleteValue(key, 'PhilixaConnect')
        except FileNotFoundError: pass
    try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PhilixaConnect')
    except FileNotFoundError: pass
    advapi.CredDeleteW(TARGET, 1, 0)
    # Explicit per-user directory; no shell or recursive deletion.
    if CONFIG.exists(): CONFIG.unlink()
    executable = HOME / 'PhilixaConnect.exe'
    if executable.exists():
        # Running Windows executables cannot be removed until exit.
        try: executable.unlink()
        except PermissionError:
            # Fixed, verified per-user target; one PowerShell process owns cleanup.
            literal = str(executable).replace("'", "''")
            cleanup = f"$target = '{literal}'\n$processId = {os.getpid()}\n" + r'''
$expected = Join-Path $env:LOCALAPPDATA 'PhilixaConnect\PhilixaConnect.exe'
if ([IO.Path]::GetFullPath($target) -ne [IO.Path]::GetFullPath($expected)) { exit 1 }
Wait-Process -Id $processId -ErrorAction SilentlyContinue
$running = Get-Process | Where-Object { $_.Path -eq $target }
foreach ($item in $running) { Wait-Process -Id $item.Id -ErrorAction SilentlyContinue }
Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
'''
            encoded = base64.b64encode(cleanup.encode('utf-16le')).decode()
            subprocess.Popen(['powershell.exe','-NoProfile','-WindowStyle','Hidden','-EncodedCommand',encoded],creationflags=subprocess.CREATE_NO_WINDOW)
    return True

def endpoint(base, local_test=False):
    url = urlsplit(base)
    local = (local_test or os.getenv('PHILIXA_HELPER_DEV_HTTP') == '1') and url.scheme == 'http' and url.hostname in ('127.0.0.1','localhost')
    if (url.scheme != 'https' and not local) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('Hosted Philixa HTTPS address required')
    return base.rstrip('/') + '/api/v1/integrations/tally'

def candidates():
    ports, running = [9000], False
    for process in psutil.process_iter(['name','exe']):
        if (process.info['name'] or '').lower() not in ('tally.exe','tallyprime.exe'): continue
        running = True
        try:
            ini = Path(process.info['exe']).parent / 'tally.ini'
            for match in re.finditer(r'^\s*(?:ServerPort|Port)\s*=\s*(\d+)\s*$', ini.read_text(errors='ignore'), re.M | re.I):
                port = int(match.group(1))
                if 1 <= port <= 65535 and port not in ports: ports.append(port)
        except (OSError, TypeError): pass
    return ports, running

def execute(job, port):
    if not isinstance(job,dict):raise ValueError('Unexpected job')
    # Cross-process mutex: two installed helper copies must not submit concurrently.
    import msvcrt
    import hashlib
    lock=HOME/('endpoint-'+hashlib.sha256(str(port or 9000).encode()).hexdigest()+'.lock')
    if isinstance(job,dict) and job.get('operation','') not in ('discover','stock'):
        HOME.mkdir(parents=True,exist_ok=True)
        with lock.open('a+b') as handle:
            if handle.tell()==0:handle.write(b'0');handle.flush()
            handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise TallyError('Company operation busy; retry safely.')
            try:return execute_unlocked(job,port)
            finally:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    return execute_unlocked(job,port)

def execute_unlocked(job, port):
    allowed = {'id','device_id','organization_id','operation','company','identity','as_of','item_query','generation','page','payload','config','action_id','tool','arguments'}
    if not isinstance(job, dict) or set(job) - allowed or not re.fullmatch('[a-f0-9]{32}', job.get('id','')):
        raise ValueError('Unexpected job')
    operation = job.get('operation')
    if operation not in OPERATIONS: raise ValueError('Unexpected operation')
    parameters = {}
    if operation == 'stock':
        for key, limit in [('company',200),('identity',250),('as_of',10),('item_query',200)]:
            value = job.get(key)
            if not isinstance(value,str) or not value or len(value)>limit: raise ValueError('Invalid job')
            parameters[key] = value
        from datetime import date
        date.fromisoformat(parameters['as_of'])
    if operation in ('discover','stock'):
        return asyncio.run(local_operation(operation, port=port, **parameters))
    for key,limit in [('company',200),('identity',250)]:
        if not isinstance(job.get(key),str) or not job[key] or len(job[key])>limit:raise ValueError('Invalid company')
        parameters[key]=job[key]
    if operation in ('mcp_read','mcp_compile'):
        if operation=='mcp_compile' and not re.fullmatch('[a-f0-9]{32}',job.get('action_id','')):raise ValueError('Invalid draft action')
        from helper.mcp_runtime import execute_read,execute_compile
        bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'mcp_bundle'
        return (execute_read if operation=='mcp_read' else execute_compile)(bundle,port or 9000,parameters['company'],parameters['identity'],job.get('tool'),job.get('arguments'))
    if operation=='snapshot_start':
        from datetime import date
        date.fromisoformat(job['as_of']);parameters['as_of']=job['as_of']
    elif operation=='snapshot_page':
        if not re.fullmatch('[a-f0-9]{32}',job.get('generation','')) or type(job.get('page'))!=int:raise ValueError('Invalid page')
        parameters.update(generation=job['generation'],page=job['page'])
    else:
        if not re.fullmatch('[a-f0-9]{32}',job.get('action_id','')) or not isinstance(job.get('payload'),dict):raise ValueError('Invalid action')
        parameters.update(payload=job['payload'],config=job.get('config'))
    return asyncio.run(execute_sync(operation,port=port,journal_path=HOME/'sync.sqlite3',**parameters))

def optional_port(raw):
    text = '' if raw is None else str(raw).strip()
    if text.lower() in ('', 'none', 'null'): return None
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ValueError('Port khaali chhodein (automatic), ya 1–65535 ka number dalein.')
    return int(text)


class Connect:
    def __init__(self):
        self.root = tk.Tk(); self.root.title('Philixa Tally Connector — unsigned pilot')
        milestone('window_created')
        self.root.geometry('540x460'); self.stop = threading.Event(); self.connected = False; self.busy=False
        self.lifecycle_lock=threading.RLock()
        self.closing=False; self.pending_until=0; self.last_health=0; self.health={}
        self.settings = read_settings()
        self.pending_until=time.monotonic()+max(0,self.settings.get('pair_expires_at',0)-time.time())
        self.installer=getattr(sys,'frozen',False) and Path(sys.executable).resolve()!=EXE.resolve()
        saved = load_secret()
        try: credential = json.loads(saved) if saved else {}
        except ValueError: credential = {}
        self.secret = credential.get('secret',''); self.secret_origin = credential.get('origin','')
        self.base = tk.StringVar(value=self.settings.get('base',''))
        self.local_test = tk.BooleanVar(value=self.settings.get('local_test',False))
        saved_port = self.settings.get('port')
        self.port = tk.StringVar(value='' if saved_port is None or str(saved_port).strip().lower() in ('none','null') else str(saved_port))
        self.status = tk.StringVar(value='Install once. Pair once. Connection stays automatic.')
        tk.Label(self.root,text='Philixa Tally Connector',font=('Segoe UI',16,'bold')).pack(pady=14)
        if self.installer:
            tk.Label(self.root,text='1. Install on this Tally PC\nExisting pairing and saved entries stay safe.',justify='left').pack(pady=12)
            self.install_button=tk.Button(self.root,text='Install & continue',command=self.install)
            self.install_button.pack(pady=14)
        else:
            tk.Label(self.root,text='2. Pair this PC with Philixa',font=('Segoe UI',11,'bold')).pack(pady=5)
            tk.Label(self.root,text='Philixa website address').pack()
            tk.Entry(self.root,textvariable=self.base,width=60).pack(pady=5)
            tk.Button(self.root,text='Generate connection code',command=self.pair).pack(pady=8)
            tk.Button(self.root,text='Pause / resume automatic connection',command=self.toggle_pause).pack(pady=5)
            self.advanced=tk.Frame(self.root)
            tk.Button(self.root,text='Advanced settings',command=lambda: self.advanced.pack(pady=5) if not self.advanced.winfo_ismapped() else self.advanced.pack_forget()).pack()
            tk.Checkbutton(self.advanced,text='Local development: Philixa on this PC',variable=self.local_test,command=self.select_local).pack()
            tk.Label(self.advanced,text='Tally port (blank = automatic)').pack()
            tk.Entry(self.advanced,textvariable=self.port).pack()
        self.pair_code=tk.StringVar(value=self.settings.get('pair_code','') if self.pending_until>time.monotonic() else '')
        if not self.installer:
            tk.Label(self.root,text='Connection code (paste into Philixa website)').pack(pady=5)
            tk.Entry(self.root,textvariable=self.pair_code,state='readonly',justify='center',font=('Segoe UI',14,'bold')).pack()
            tk.Button(self.root,text='Copy code',command=self.copy_code).pack(pady=4)
        tk.Label(self.root,textvariable=self.status,wraplength=510,justify='left').pack(pady=12)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_to_tray)
        self.stop_handle=kernel.CreateEventW(None,True,False,STOP_EVENT)
        if not self.installer:kernel.ResetEvent(self.stop_handle)
        image = Image.new('RGB',(64,64),'#236548'); ImageDraw.Draw(image).text((23,20),'P',fill='white')
        self.icon = pystray.Icon('Philixa',image,'Philixa Tally Connector',pystray.Menu(
            pystray.MenuItem('Show status',lambda: self.root.after(0,self.root.deiconify)),
            pystray.MenuItem('Pause / resume automatic connection',lambda: self.root.after(0,self.toggle_pause)),
            pystray.MenuItem('Exit',lambda: self.close())))
        threading.Thread(target=self.icon.run,daemon=True).start()
        self.show_handle=kernel.CreateEventW(None,True,False,SHOW_EVENT+('-setup' if self.installer else ''))
        if self.secret and self.base.get() and not self.installer:
            if self.settings.get('paused'): self.notify('Automatic connection paused. Click Resume to reconnect.')
            else: self.connect()
        if '--tray' in sys.argv and self.secret and self.pending_until<=time.monotonic() and not self.settings.get('paused'): self.root.withdraw()
        self.root.after(300,self.check_uninstall)

    def copy_code(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.pair_code.get())

    def hide_to_tray(self):
        self.status.set('Connection paused.' if self.settings.get('paused') else 'Background reconnect active. Use tray Show status to reopen.')
        self.root.withdraw()

    def notify(self, text): self.root.after(0,self.status.set,text)
    def select_local(self):
        if self.connected:
            self.local_test.set(self.settings.get('local_test',False))
            self.notify('Disconnect before changing connection.'); return
        self.base.set('http://127.0.0.1:8001' if self.local_test.get() else '')
        self.notify('Local test: isi PC ka Philixa app use hoga.' if self.local_test.get() else 'Hosted Philixa ka HTTPS address dalein.')
    def check_uninstall(self):
        if kernel.WaitForSingleObject(self.show_handle,0)==0:
            kernel.ResetEvent(self.show_handle)
            self.root.deiconify();self.root.lift();self.root.focus_force()
        if not self.installer and kernel.WaitForSingleObject(self.stop_handle,0)==0 and not self.busy: self.close()
        elif self.closing and not self.busy: self.close()
        else: self.root.after(300,self.check_uninstall)
    def install(self):
        self.install_button.config(state='disabled');self.notify('Installing and configuring automatic startup…')
        def run():
            try:
                install()
                result=subprocess.run(['schtasks.exe','/Run','/TN',TASK],capture_output=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
                if result.returncode: raise RuntimeError('Installed, but startup failed. Open Philixa Tally Connector from Windows Start.')
                self.root.after(0,self.close)
            except Exception as exc:
                milestone('installation_failed',type(exc).__name__)
                self.notify(str(exc) if isinstance(exc,RuntimeError) else 'Installation failed. Retry Install & continue. Existing pairing is preserved.')
                self.root.after(0,lambda:self.install_button.config(state='normal'))
        threading.Thread(target=run,daemon=True).start()
    def toggle_pause(self):
        paused=not self.settings.get('paused',False)
        self.settings['paused']=paused;write_settings(self.settings)
        if paused:self.disconnect()
        elif self.connected:self.notify('Finishing current operation; automatic connection will resume.');self.root.after(500,self.resume_when_idle)
        else:self.connect()
    def resume_when_idle(self):
        if self.settings.get('paused'):return
        if self.connected:self.root.after(500,self.resume_when_idle)
        else:self.connect()
    def config(self, pairing=False):
        url = endpoint(self.base.get().strip(),self.local_test.get()); port = optional_port(self.port.get())
        if self.secret and not pairing and self.secret_origin != self.base.get().strip().rstrip('/'):
            raise ValueError('Address changed. Pair with this Philixa address before reconnecting.')
        self.settings = {**self.settings,'base':self.base.get().strip(), 'port':port, 'local_test':self.local_test.get()}
        write_settings(self.settings)
        return url
    def pair(self):
        if self.connected: self.notify('Already paired. Use Change connected PC on the website only when replacing this connection.'); return
        try: url = self.config(pairing=True)
        except ValueError as exc: self.notify(str(exc)); return
        def run():
            try:
                with httpx.Client(timeout=15,follow_redirects=False,trust_env=False) as client:
                    response = client.post(url+'/pairing/begin'); response.raise_for_status(); data = response.json()
                origin=self.settings['base'].rstrip('/')
                save_secret(json.dumps({'secret':data['credential'],'origin':origin})); self.secret = data['credential'];self.secret_origin=origin
                self.pending_until=time.monotonic()+data.get('expires_in',600)
                self.settings.update(paused=False,pair_code=data['code'],pair_expires_at=time.time()+data.get('expires_in',600));write_settings(self.settings)
                self.root.after(0,self.code_ready,data['code'])
            except Exception: self.notify('Pairing unavailable. Check hosted address/network and retry.')
        threading.Thread(target=run,daemon=True).start()
    def code_ready(self, code):
        self.pair_code.set(code)
        self.status.set('Connection code: '+code+' (10 minutes). Philixa page par ye code dalein aur Connect dabayein.')
        self.connect()
    def connect(self):
        if self.connected or self.settings.get('paused'): return
        try: url = self.config()
        except ValueError as exc: self.notify(str(exc)); return
        if not self.secret: self.notify('Generate pairing code first.'); return
        self.stop.clear(); self.connected = True
        threading.Thread(target=self.poll,args=(url,self.secret),daemon=True).start()
    def disconnect(self): self.stop.set(); self.notify('Automatic connection paused. Resume when ready.')
    def close(self):
        with self.lifecycle_lock:
            self.closing=True
            if self.busy:
                self.notify('Finishing current entry before closing.');return
            self.stop.set()
        self.icon.stop(); self.root.after(0,self.root.destroy)
    def check_health(self, approved):
        ports,running=candidates()
        if self.settings.get('port'):ports=[self.settings['port']]
        state='closed' if not running else 'unreachable'
        companies=[]
        deadline=time.monotonic()+10
        for port in ports:
            if time.monotonic()>=deadline:break
            try:
                companies=asyncio.run(asyncio.wait_for(local_operation('discover',port=port),timeout=min(4,max(.1,deadline-time.monotonic()))))['companies']
                state='available';break
            except (TallyError,OSError,TimeoutError):continue
        present={(c['identity'],c['name']) for c in companies}
        bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'mcp_bundle'
        manifest=bundle/'manifest.json'
        mcp_build=None
        try:
            mcp_build=json.loads(manifest.read_text(encoding='utf-8')).get('commit')
        except (OSError,ValueError):pass
        return {'connector_version':VERSION,'startup_configured':bool(self.settings.get('startup_configured')),
                'mcp_build':mcp_build,'mcp_state':'disabled' if mcp_build else 'missing',
                'tally_state':state,'error_code':None if state=='available' else 'tally_closed' if state=='closed' else 'http_unreachable',
                'companies':[{'identity':c['identity'],'reachable':(c['identity'],c['name']) in present} for c in approved]}

    def poll(self,url,secret):
        try:
            failures=0
            with httpx.Client(timeout=15,headers={'Authorization':'Bearer '+secret},follow_redirects=False,trust_env=False) as client:
                while not self.stop.is_set():
                    try:
                        response = client.get(url+'/helper/jobs',params={'protocol_version':PROTOCOL_VERSION})
                        if response.status_code == 401:
                            if time.monotonic()<self.pending_until:
                                self.stop.wait(3);continue
                            self.notify('Pairing expired or revoked. Generate a new code and explicitly replace the PC on Philixa.');milestone('pairing_required');break
                        response.raise_for_status(); failures=0;self.pending_until=0;envelope=response.json();job = envelope['job']
                        if not job and time.monotonic()-self.last_health>20:
                            self.health=self.check_health(envelope.get('approved_companies',[]))
                            client.post(url+'/helper/heartbeat',json=self.health).raise_for_status()
                            self.last_health=time.monotonic()
                        if not job:
                            if not self.settings.get('startup_configured'):self.notify('Connector online; automatic startup not configured. Run the installer to complete setup.')
                            else:self.notify('Connector online. '+{'closed':'Tally closed; waiting automatically.','available':'Tally reachable.','unreachable':'Enable Tally HTTP server; retry is automatic.'}.get(self.health.get('tally_state'),'Checking Tally…'))
                            self.stop.wait(2);continue
                        if job.get('device_id') != envelope['device_id']: raise ValueError('Wrong device job')
                        ports, running = candidates(); ports = [self.settings['port']] if self.settings.get('port') else ports
                        result = None
                        with self.lifecycle_lock:
                            if self.stop.is_set() or self.closing:break
                            self.busy=True
                        for port in ports:
                            try: result = execute(job,port); break
                            except TallyError: continue
                        if result is None:
                            error = 'Setup needed: enable Tally HTTP server' if running else 'Tally closed'
                            # A successful discovery but unavailable selected identity is distinct.
                            if running:
                                try:
                                    discovery = execute({**job,'operation':'discover'},ports[0])
                                    selected=[c for c in discovery['companies'] if c['identity']==job.get('identity') and c['name']==job.get('company')]
                                    error = 'Company unavailable' if job['operation']=='stock' and len(selected)!=1 else 'Read failed'
                                except TallyError: pass
                            payload = {'id':job['id'],'error':error}
                            self.notify(error+'. Tally Exchange → Configure / Data Synchronisation: Server/Both aur local port set karein; company load karein. Menu version ke hisaab se badal sakta hai.')
                        else:
                            payload = {'id':job['id'],'data':result}
                            if len(json.dumps(payload).encode()) > 2_000_000: payload = {'id':job['id'],'error':'Response too large'}
                        published = client.post(url+'/helper/results',json=payload)
                        if published.status_code not in (200,410): published.raise_for_status()
                    except Exception as exc:
                        failures+=1;milestone('retry',type(exc).__name__)
                        self.notify('Philixa unavailable; reconnecting automatically.'); self.stop.wait(backoff(failures))
                    finally:self.busy=False
        finally: self.connected = False

if __name__ == '__main__':
    if '--install-only' in sys.argv:
        # Deployment acceptance entry: same installer implementation; no pairing
        # replacement or accounting calls. Existing active operations must drain.
        result={}
        try:
            install()
            started=subprocess.run(['schtasks.exe','/Run','/TN',TASK],capture_output=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
            if started.returncode:raise RuntimeError('Installed startup task did not start.')
            result={'installed':True,'version':VERSION,'startup_registered':True}
        except Exception as exc:
            milestone('installation_failed',type(exc).__name__)
            result={'installed':False,'error_type':type(exc).__name__}
        Path(sys.argv[sys.argv.index('--install-only')+1]).write_text(json.dumps(result))
        sys.exit(0 if result.get('installed') else 1)
    elif '--gst-self-test' in sys.argv:
        result={}
        try:
            from app.services.tally_gst_purchase import compile_purchase,validate,gst_xml,verify
            from app.services.tally_sync_protocol import deserialize_catalog
            import xml.etree.ElementTree as ET
            position=sys.argv.index('--gst-self-test')
            fixture=json.loads(Path(sys.argv[position+1]).read_text(encoding='utf-8'))
            catalog=deserialize_catalog(fixture['catalog'])
            payload=compile_purchase(catalog,fixture['content'],fixture['profile'],fixture['config'],fixture['guid'])
            validate(catalog,payload,fixture['config'])
            from app.services.tally_connector import parse_xml
            voucher=parse_xml(gst_xml(payload).encode()).find('.//VOUCHER')
            assert verify(voucher,payload)
            voucher.find('LEDGERENTRIES.LIST[2]/AMOUNT').text='-999'
            assert not verify(voucher,payload)
            assert PROTOCOL_VERSION>=8
            result={'synthetic_gst_math_and_verifier':True,'protocol_version':PROTOCOL_VERSION,'native_tally_acceptance':False}
        except Exception as exc:result={'error':type(exc).__name__}
        Path(sys.argv[sys.argv.index('--gst-self-test')+2]).write_text(json.dumps(result))
    elif '--mcp-self-test' in sys.argv:
        # Packaging smoke test: no GUI, pairing changes, company reads, or imports.
        result={}
        try:
            from helper.mcp_runtime import ReadGateway,StdioClient
            from app.services.tally_mcp import CONTRACTS,PIN
            bundle=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'mcp_bundle'
            with ReadGateway('__packaging_probe__',9000) as gateway,StdioClient(bundle,gateway.url) as child:
                inventory=child.request('tools/list',{})['tools']
                assert {t['name'] for t in inventory}==set(CONTRACTS)
                blocked=child.request('tools/call',{'name':'confirm_write','arguments':{}})
                assert blocked.get('isError')
                result={'stdio':True,'tools':len(inventory),'direct_writes_blocked':True,'commit':PIN}
        except Exception as exc:result={'error':type(exc).__name__}
        Path(sys.argv[sys.argv.index('--mcp-self-test')+1]).write_text(json.dumps(result))
    elif '--self-test' in sys.argv:
        TARGET = 'PhilixaConnect/temporary-build-test'
        result={}
        try:
            root=tk.Tk();root.withdraw();root.update();root.destroy();result['gui']=True
            save_secret('temporary-test');result['credential_store']=load_secret()=='temporary-test'
            for payload in ({'id':'a'*32,'operation':'shell'}, {'id':'a'*32,'operation':'discover','xml':'x'}):
                try:execute(payload,9000);raise AssertionError('Unexpected operation accepted')
                except ValueError:pass
            result['allowlist']=True
            assert endpoint('http://127.0.0.1:8001',True).startswith('http://127.0.0.1:8001/')
            for address in ('http://example.com','ftp://127.0.0.1','http://127.0.0.1:8001/path','http://127.0.0.1:8001?x=1'):
                try:endpoint(address,True);raise AssertionError('Invalid address accepted')
                except ValueError:pass
            try:endpoint('http://127.0.0.1:8001');raise AssertionError('Implicit HTTP accepted')
            except ValueError:pass
            result['local_http_scope']=True
            result['companies']=len(execute({'id':'a'*32,'operation':'discover'},9000)['companies'])
        except Exception as exc:result['error']=type(exc).__name__
        finally:advapi.CredDeleteW(TARGET,1,0)
        Path(sys.argv[sys.argv.index('--self-test')+1]).write_text(json.dumps(result))
    elif '--uninstall' in sys.argv:
        root=tk.Tk(); root.withdraw()
        if messagebox.askyesno('Uninstall Philixa Tally Connector','Remove startup, pairing credential and helper settings?'):
            complete=uninstall()
            messagebox.showinfo('Uninstalled', 'Startup and credential removed.' + ('' if complete else f' Close helper, then delete {HOME / "PhilixaConnect.exe"}.'))
    else:
        installer=getattr(sys,'frozen',False) and Path(sys.executable).resolve()!=EXE.resolve()
        if getattr(sys,'frozen',False) and not installer and '--managed' not in sys.argv:
            try:start_managed()
            except Exception as exc:
                milestone('managed_launch_failed',type(exc).__name__)
                ctypes.windll.user32.MessageBoxW(None,'Automatic startup unavailable. Reinstall from Philixa → Download Tally Connector. Existing pairing will be preserved.','Philixa Tally Connector',16)
                sys.exit(1)
        elif claim_instance(installer):
            try:
                milestone('launch');Connect().root.mainloop()
            except Exception as exc:
                milestone('startup_failed',type(exc).__name__)
                ctypes.windll.user32.MessageBoxW(None,'Connector could not start. Open Windows Start → Philixa Tally Connector. If it fails again, reinstall. Diagnostic log: '+str(HOME/'startup.log'),'Philixa Tally Connector',16)
                sys.exit(1)
