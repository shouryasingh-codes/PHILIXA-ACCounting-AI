"""Resolve frozen certificate data without disabling HTTPS verification."""
from pathlib import Path

def configure_bundled_ca(bundle_root):
    import certifi
    path=Path(bundle_root)/'certifi'/'cacert.pem'
    if not path.is_file():raise RuntimeError('Packaged certificate bundle missing')
    # Capture the path now, independently of runtime-hook globals/import state.
    certifi.where=lambda ca_path=str(path):ca_path
    return path
