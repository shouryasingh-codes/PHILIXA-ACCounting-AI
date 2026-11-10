"""Collect installed distribution metadata/licences alongside the immutable payload."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys


def collect(destination):
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    records=[]
    for dist in importlib.metadata.distributions():
        name = dist.metadata['Name']
        # Distribution names are controlled package metadata, never filesystem paths.
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._' for c in name):
            raise RuntimeError('Invalid dependency metadata')
        folder = destination/name; folder.mkdir(exist_ok=True)
        copied=[]
        for entry in dist.files or ():
            if any(token in entry.name.lower() for token in ('license','licence','notice','copying')):
                source=Path(dist.locate_file(entry))
                if source.is_file():
                    target=folder/(str(len(copied))+'-'+source.name)
                    shutil.copyfile(source,target); copied.append(target.name)
        (folder/'METADATA.txt').write_text(str(dist.metadata),encoding='utf-8')
        records.append({'name':name,'version':dist.version,'licences':copied})
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('Python licence file missing; package withheld')
    shutil.copyfile(python_license,destination/'PYTHON-LICENSE.txt')
    (destination/'dependencies.json').write_text(json.dumps(records,indent=2),encoding='utf-8')


if __name__=='__main__': collect(sys.argv[1])
