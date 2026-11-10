"""Source-only table evidence; no accounting authority or model-generated values."""
import hashlib
import json
import math
import re
from decimal import Decimal
from html.parser import HTMLParser
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Cell(Contract):
    id: str
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    rowspan: int = Field(default=1, ge=1, le=100)
    colspan: int = Field(default=1, ge=1, le=100)
    text: str = Field(max_length=2000)
    bbox: list[float] = Field(min_length=4, max_length=4)
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    structure_confidence: float | None = Field(default=None, ge=0, le=1)
    numeric_grounded: bool | None = None


class Table(Contract):
    id: str
    cells: list[Cell] = Field(max_length=1000)


class LayoutDocument(Contract):
    version: Literal['layout-v1'] = 'layout-v1'
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    reader: str
    config_sha256: str
    transforms: list = Field(default_factory=list)
    headers: list[Cell] = Field(max_length=300)
    tables: list[Table] = Field(max_length=10)
    raw_ocr: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def bounds(self):
        cells = self.headers + [c for t in self.tables for c in t.cells]
        if len({c.id for c in cells}) != len(cells): raise ValueError('Duplicate cell IDs')
        for cell in cells:
            x1,y1,x2,y2 = cell.bbox
            if not all(math.isfinite(v) for v in cell.bbox) or not (0 <= x1 < x2 <= self.image_width and 0 <= y1 < y2 <= self.image_height):
                raise ValueError('Cell outside source image')
        return self


class GridParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.cells=[]; self.row=-1; self.col=0; self.current=None; self.occupied=set()

    def handle_starttag(self, tag, attrs):
        if tag=='br' and self.current is not None:self.current['text']+=' '
        if tag == 'tr': self.row += 1; self.col=0
        if tag in ('td','th'):
            if self.row < 0 or self.current is not None: raise ValueError('Invalid table HTML')
            while (self.row,self.col) in self.occupied: self.col += 1
            a=dict(attrs); rs=int(a.get('rowspan',1)); cs=int(a.get('colspan',1))
            if not 1<=rs<=100 or not 1<=cs<=100: raise ValueError('Invalid cell span')
            self.current=dict(row=self.row,column=self.col,rowspan=rs,colspan=cs,text='')
            for r in range(self.row,self.row+rs):
                for c in range(self.col,self.col+cs):
                    if (r,c) in self.occupied: raise ValueError('Overlapping cells')
                    self.occupied.add((r,c))
            self.col += cs

    def handle_data(self,data):
        if self.current is not None: self.current['text'] += data

    def handle_endtag(self,tag):
        if tag in ('td','th') and self.current is not None:
            self.current['text']=' '.join(self.current['text'].split())
            self.cells.append(self.current); self.current=None


def box(value):
    if len(value)==4 and all(isinstance(v,(int,float)) for v in value): return list(map(float,value))
    if len(value)==8 and all(isinstance(v,(int,float)) for v in value):
        value=list(zip(value[::2],value[1::2]))
    return [float(min(p[0] for p in value)),float(min(p[1] for p in value)),
            float(max(p[0] for p in value)),float(max(p[1] for p in value))]


def normalize(result, image_bytes, width, height, manifest):
    res=result.get('res',result)
    tables=[]; table_boxes=[]
    for n,t in enumerate(res.get('table_res_list',[])):
        parser=GridParser(); parser.feed(t.get('pred_html',''))
        boxes=t.get('cell_box_list',[])
        if not boxes or len(boxes)!=len(parser.cells): raise ValueError('Table cells/HTML coverage mismatch')
        cells=[Cell(id=f't{n}c{i}',bbox=box(b),**c) for i,(b,c) in enumerate(zip(boxes,parser.cells))]
        # Cell order must agree with row/column geometry; never silently reorder HTML values.
        for a,b in zip(cells,cells[1:]):
            if a.row==b.row and a.bbox[0]>b.bbox[0]+3: raise ValueError('Table cell order ambiguous')
            if a.row<b.row and a.bbox[1]>b.bbox[1]+3: raise ValueError('Table row order ambiguous')
        tables.append(Table(id=f't{n}',cells=cells))
        if cells: table_boxes.append([min(c.bbox[0] for c in cells),min(c.bbox[1] for c in cells),max(c.bbox[2] for c in cells),max(c.bbox[3] for c in cells)])
    if not tables: raise ValueError('No table structure found')
    ocr=res.get('overall_ocr_res',{}); texts=ocr.get('rec_texts',[])
    boxes=ocr.get('rec_boxes',ocr.get('rec_polys',[])); scores=ocr.get('rec_scores',[])
    if len(texts)!=len(boxes): raise ValueError('OCR evidence shape mismatch')
    headers=[]
    for i,(text,b) in enumerate(zip(texts,boxes)):
        b=box(b); cx=(b[0]+b[2])/2;cy=(b[1]+b[3])/2
        if any(x1<=cx<=x2 and y1<=cy<=y2 for x1,y1,x2,y2 in table_boxes): continue
        headers.append(Cell(id=f'h{i}',row=i,column=0,text=text,bbox=b,
                            ocr_confidence=scores[i] if i<len(scores) else None))
    # A numeric HTML cell must also exist in independent OCR text at its source
    # location. Cell geometry alone is not proof of transcription correctness.
    numeric=r'(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s*[A-Za-z]+)?'
    def value(text):
        match=re.fullmatch(numeric,text.strip(),re.I)
        return Decimal(match[1].replace(',','')) if match else None
    all_cells=[c for t in tables for c in t.cells]
    owned={c.id:[] for c in all_cells}
    for text,token_box in zip(texts,boxes):
        number=value(text)
        if number is None:continue
        b=box(token_box);area=(b[2]-b[0])*(b[3]-b[1])
        if area<=0:continue
        candidates=[]
        for cell in all_cells:
            a=cell.bbox
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))/area
            if overlap:candidates.append((overlap,cell.id))
        candidates.sort(reverse=True)
        # Assignment uses geometry ONLY, never the expected/cell numeric value.
        # Overlapping detector boxes cannot claim the same source token twice.
        if candidates and candidates[0][0]>=.6 and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.1):
            owned[candidates[0][1]].append(number)
    for cell in all_cells:
        wanted=value(cell.text)
        if wanted is not None:cell.numeric_grounded=owned[cell.id]==[wanted]
    config_hash=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    return LayoutDocument(source_sha256=hashlib.sha256(image_bytes).hexdigest(),image_width=width,image_height=height,
        reader='ppstructure-v3',config_sha256=config_hash,headers=headers,tables=tables,raw_ocr=ocr)
