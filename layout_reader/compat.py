"""Version-bound upstream fix: don't initialize a disabled chart model.

PaddleX 3.3.13 creates ChartRecognition unconditionally in PP-StructureV3.
Only the isolated reader distribution is patched; no extraction values change.
Fail the build if upstream source no longer matches. Keep hashes for review.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path


def main():
    dist=importlib.metadata.distribution('paddlex')
    if dist.version!='3.3.13':raise RuntimeError('Revalidate chart initialization fix for changed PaddleX')
    path=Path(dist.locate_file('paddlex/inference/pipelines/layout_parsing/pipeline_v2.py'))
    original=path.read_bytes();text=original.decode()
    before='''        self.chart_recognition_model = self.create_model(
            chart_recognition_config,
        )'''
    after='''        self.chart_recognition_model = None
        if config.get("use_chart_recognition", False):
            self.chart_recognition_model = self.create_model(
                chart_recognition_config,
            )'''
    if text.count(before)!=1:raise RuntimeError('Upstream chart initialization changed; review required')
    patched=text.replace(before,after).encode();path.write_bytes(patched)
    Path('/reader/compat-evidence.json').write_text(json.dumps({'package':'paddlex','version':dist.version,
        'file':str(path),'before_sha256':hashlib.sha256(original).hexdigest(),
        'after_sha256':hashlib.sha256(patched).hexdigest(),'change':'Honor disabled chart-recognition configuration'},indent=2))


if __name__=='__main__':main()
