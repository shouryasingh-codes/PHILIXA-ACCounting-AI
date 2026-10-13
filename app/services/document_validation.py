"""Bounded parser subprocess: no AI, database, external links or embedded scripts."""
import io
import json
import sys
import warnings
from PIL import Image

MAX_BYTES=10*1024*1024


class RejectedDocument(Exception):pass


def inspect(data):
    if not data or len(data)>MAX_BYTES:raise RejectedDocument('file_size')
    if data.startswith(b'%PDF-'):
        import pymupdf
        try:
            with pymupdf.open(stream=data,filetype='pdf') as doc:
                if doc.needs_pass:raise RejectedDocument('password_protected')
                if not 1<=doc.page_count<=20:raise RejectedDocument('page_limit')
                if doc.is_repaired:raise RejectedDocument('corrupt_document')
                for page in doc:
                    if page.rect.is_empty or page.rect.is_infinite:raise RejectedDocument('corrupt_document')
                return {'media_type':'application/pdf','page_count':doc.page_count}
        except RejectedDocument:raise
        except Exception:raise RejectedDocument('corrupt_document') from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('JPEG','PNG'):raise RejectedDocument('unsupported_type')
                if image.width*image.height>40000000 or getattr(image,'n_frames',1)!=1:raise RejectedDocument('image_limit')
                media='image/jpeg' if image.format=='JPEG' else 'image/png'
                image.verify()
            with Image.open(io.BytesIO(data)) as image:image.load()
            return {'media_type':media,'page_count':1}
    except RejectedDocument:raise
    except (Image.DecompressionBombWarning,Image.DecompressionBombError):raise RejectedDocument('image_limit') from None
    except Exception:raise RejectedDocument('corrupt_document') from None


def preview(data,page):
    import pymupdf
    with pymupdf.open(stream=data,filetype='pdf') as doc:
        if doc.needs_pass or not 1<=page<=min(doc.page_count,20):raise RejectedDocument('page_limit')
        p=doc[page-1];scale=min(2,1600/max(p.rect.width,p.rect.height))
        return p.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False,annots=False).tobytes('png')


if __name__=='__main__':
    data=sys.stdin.buffer.read(MAX_BYTES+1)
    try:
        if sys.argv[1]=='inspect':sys.stdout.write(json.dumps(inspect(data)))
        elif sys.argv[1]=='extract':
            import pymupdf
            from app.services.invoice_extraction import extract_from_pdf_text_local
            result=extract_from_pdf_text_local(data)
            with pymupdf.open(stream=data,filetype='pdf') as doc:
                result['_source_text']='\n'.join(page.get_text() for page in doc)[:60000]
                result['_page_count']=doc.page_count
            sys.stdout.write(json.dumps(result))
        elif sys.argv[1]=='preview':sys.stdout.buffer.write(preview(data,int(sys.argv[2])))
        else:raise RejectedDocument('unsupported_type')
    except Exception as exc:
        sys.stderr.write(str(exc) if isinstance(exc,RejectedDocument) else 'corrupt_document');sys.exit(2)
