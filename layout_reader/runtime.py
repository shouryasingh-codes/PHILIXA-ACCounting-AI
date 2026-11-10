import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path('/opt/philixa-models')


@lru_cache
def pipeline():
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    from paddleocr import PPStructureV3
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    # Verify bundled models rather than silently acquiring replacements.
    for artifact in manifest['artifacts']:
        for path, expected in artifact['files'].items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Model artifact integrity failure')
    paths = {a['name']: a['path'] for a in manifest['artifacts']}
    kwargs = {key + '_model_name': name for key, name in manifest['models'].items()}
    kwargs.update({key + '_model_dir': paths[name] for key, name in manifest['models'].items()})
    return PPStructureV3(**kwargs, device='cpu', cpu_threads=2,
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, use_formula_recognition=False,
        use_seal_recognition=False, use_chart_recognition=False,use_region_detection=False,
        layout_threshold=.4,layout_merge_bboxes_mode='large',
        use_table_recognition=True)
