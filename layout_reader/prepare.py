"""Build-time only artifact acquisition; inference never downloads models."""
import hashlib
import importlib.metadata
import json
import pathlib
import tarfile
import urllib.request

ROOT = pathlib.Path('/opt/philixa-models')
MODELS = {
    'layout_detection': 'PP-DocLayout_plus-L',
    'text_detection': 'PP-OCRv5_mobile_det',
    'text_recognition': 'en_PP-OCRv5_mobile_rec',
    'table_classification': 'PP-LCNet_x1_0_table_cls',
    'table_orientation_classify': 'PP-LCNet_x1_0_doc_ori',
    'wired_table_structure_recognition': 'SLANet_plus',
    'wireless_table_structure_recognition': 'SLANet_plus',
    'wired_table_cells_detection': 'RT-DETR-L_wired_table_cell_det',
    'wireless_table_cells_detection': 'RT-DETR-L_wireless_table_cell_det',
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name in sorted(set(MODELS.values())):
        url = f'https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/{name}_infer.tar'
        archive = ROOT / (name + '.tar')
        cached=pathlib.Path('/model-download-cache')/(name+'.tar')
        print('Acquiring '+name,flush=True)
        import shutil
        if not cached.is_file():
            with urllib.request.urlopen(url,timeout=120) as response, archive.open('wb') as output:
                shutil.copyfileobj(response,output)
            cached.parent.mkdir(exist_ok=True);shutil.copyfile(archive,cached)
        else:shutil.copyfile(cached,archive)
        print('Acquired '+name,flush=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with tarfile.open(archive) as tar:
            tar.extractall(ROOT / name, filter='data')
        archive.unlink()
        configs = list((ROOT / name).rglob('inference.yml'))
        if len(configs) != 1:
            raise RuntimeError('Ambiguous model artifact: ' + name)
        artifacts.append({'name': name, 'url': url, 'archive_sha256': digest,
                          'path': str(configs[0].parent), 'license': 'Apache-2.0; PaddleOCR distribution; inspect bundled notices',
                          'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (ROOT / name).rglob('*') if p.is_file()}})
    manifest = {'models': MODELS, 'artifacts': artifacts,
                'config': {'device':'cpu','threads':2,'doc_orientation':False,'unwarping':False,
                           'text_orientation':False,'table_orientation':False,'region_detection':False,
                           'formula':False,'chart':False,'seal':False,'layout_threshold':.4,'layout_merge':'large'},
                'packages': {n: importlib.metadata.version(n) for n in ('paddleocr', 'paddlepaddle', 'paddlex')}}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    # Construct pipeline now, catching incompatible names/configuration at build time.
    from runtime import pipeline
    pipeline()


if __name__ == '__main__':
    main()
