"""Verify an existing pinned MCP payload before reusing it in a repair build."""
import hashlib
import json
from pathlib import Path
import re
import ssl

PIN = '6619585a351000dd979b046ff63408771435644a'


def validate_mcp(folder):
    root = Path(folder).resolve()
    data = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    files = data.get('runtimeFiles', {})
    if data.get('commit') != PIN or not data.get('nodeVersion','').startswith('v24.'):
        raise RuntimeError('Pinned MCP/Node identity mismatch')
    if not all(name in files for name in ('node.exe','LICENSE','NODE-LICENSE')):
        raise RuntimeError('Required runtime/licences missing')
    actual = {str(p.relative_to(root)).replace('\\','/') for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    if set(files) != actual:
        raise RuntimeError('MCP payload file list changed')
    for name, expected in files.items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('MCP payload integrity mismatch')
    return True


def validate_dependencies():
    from importlib.metadata import version
    expected = {'httpx':'0.28.1','psutil':'7.0.0','pystray':'0.19.5','Pillow':'11.3.0',
                'pyinstaller':'6.16.0','tzdata':'2025.2','jsonschema':'4.25.1'}
    if not all(version(name) == pinned for name, pinned in expected.items()):
        raise RuntimeError('Pinned build dependencies unavailable')


def runtime_ssl_data():
    """Preserve data required by this runtime's SSL constructor, including distrust.

    A vendor-patched stdlib may reference an additional PEM next to ssl.py.
    PyInstaller's ordinary certifi hook does not collect that runtime-specific file.
    Never remove/patch the SSL policy; collect the exact required resource instead.
    """
    code = getattr(ssl.SSLContext.__new__, '__code__', None)
    filenames = {v for v in (code.co_consts if code else ())
                 if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_.-]+\.pem',v)}
    records=[]
    for name in sorted(filenames):
        path=Path(ssl.__file__).resolve().with_name(name)
        if not path.is_file():
            raise RuntimeError('Required SSL runtime policy resource missing; build withheld')
        records.append({'source':str(path),'destination':'.','name':name,
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return records


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--dependencies']:
        validate_dependencies()
    elif sys.argv[1:] == ['--runtime-data']:
        print(json.dumps(runtime_ssl_data()))
    else:
        raise SystemExit('Only --dependencies is supported')
