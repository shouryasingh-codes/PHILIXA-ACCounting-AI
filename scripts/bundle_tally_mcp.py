"""Stage pinned MCP + portable Node for PyInstaller's private payload."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from build_tally_mcp import build, BUILD, ROOT, PIN

def stage():
    build()
    node=Path(shutil.which('node') or '')
    if not node.is_file():raise RuntimeError('Node LTS runtime missing')
    version=subprocess.check_output([str(node),'--version'],text=True).strip()
    # Build deliberately pins a supported major; it does not fetch moving latest.
    if not version.startswith('v24.'):raise RuntimeError('Node 24 runtime required for this build')
    payload=Path(tempfile.mkdtemp(prefix='mcp-',dir=ROOT/'.helper-build'))
    for directory in ('dist','templates'):shutil.copytree(BUILD/directory,payload/directory)
    for filename in ('package.json','package-lock.json','LICENSE','registry.json','manifest.json'):
        shutil.copy2(BUILD/filename,payload/filename)
    shutil.copy2(node,payload/'node.exe')
    license_path=BUILD/'NODE-LICENSE'
    if not license_path.is_file():raise RuntimeError('Node redistribution license missing')
    shutil.copy2(license_path,payload/'NODE-LICENSE')
    npm=shutil.which('npm.cmd') or shutil.which('npm')
    subprocess.run([npm,'ci','--omit=dev','--ignore-scripts','--no-audit','--no-fund'],cwd=payload,check=True)
    files={str(p.relative_to(payload)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in payload.rglob('*') if p.is_file() and p.name!='manifest.json'}
    (payload/'manifest.json').write_text(json.dumps({'commit':PIN,'adapter':'0.1.0',
        'nodeVersion':version,'runtimeFiles':files},indent=2),encoding='utf-8')
    print('MCP_BUNDLE='+str(payload))
    return payload

if __name__=='__main__':stage()
