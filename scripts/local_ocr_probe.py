import json,time,sys
from pathlib import Path
from rapidocr import RapidOCR
from PIL import Image
import pymupdf,numpy as np
root=Path('data/day5-native')
engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':2})
pdf=pymupdf.open(root/'philixa-matching-test-bill.pdf');pix=pdf[0].get_pixmap(matrix=pymupdf.Matrix(2,2))
reports=[]
for fmt in ['png','jpeg']:
 image=root/('local-ocr-input.'+fmt);image.write_bytes(pix.tobytes(fmt))
 started=time.monotonic();result=engine(str(image));texts=list(result.txts or []);scores=[float(x) for x in (result.scores if result.scores is not None else [])];boxes=result.boxes.tolist() if result.boxes is not None else []
 checks={key:any(key in t for t in texts) for key in ['06ABCPF1234G1ZC','06ABCPE1234F1ZF','PHILIXA-UPLOAD-TEST-01','Goods18','Goods5','10%','18%','5%','1167.00']}
 report={'format':fmt,'seconds':round(time.monotonic()-started,2),'text_checks':checks,'texts':texts,'scores':scores,'boxes':boxes}
 reports.append(report);print(json.dumps({k:v for k,v in report.items() if k!='boxes'}),flush=True)
(root/'local-ocr-probe.json').write_text(json.dumps(reports,indent=2))
