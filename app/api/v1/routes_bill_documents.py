"""Owner-scoped originals; no public object URLs or accounting actions."""
from urllib.parse import quote
from fastapi import APIRouter,Depends,File,UploadFile,HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.services import bill_document_service as docs

router=APIRouter(prefix='/business',tags=['Private bill documents'])


@router.post('/document-batches')
async def create_batch(request:docs.BatchCreate,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await docs.create_batch(db,principal,request)


@router.get('/document-batches')
async def list_batches(principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await docs.list_batches(db,principal)


@router.get('/document-batches/{batch_id}')
async def read_batch(batch_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await docs.read_batch(db,principal,batch_id)


@router.post('/document-batches/{batch_id}/documents',status_code=202)
async def upload(batch_id:str,principal:CurrentPrincipal,file:UploadFile=File(...),db:AsyncSession=Depends(get_db)):
    try:return await docs.upload_document(db,principal,batch_id,file)
    finally:await file.close()


@router.get('/documents/{document_id}')
async def status(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return docs.view(await docs.document_for(db,principal,document_id))


@router.post('/documents/{document_id}/retry')
async def retry(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    return await docs.retry_document(db,principal,document_id)


def private_response(data,media_type,filename=None):
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'; sandbox"}
    if filename:headers['Content-Disposition']="attachment; filename*=UTF-8''"+quote(filename,safe='')
    return Response(content=data,media_type=media_type,headers=headers)


@router.get('/documents/{document_id}/original')
async def original(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    row=await docs.document_for(db,principal,document_id)
    if row.status!='ready':raise HTTPException(409,'File check complete hone par original available hoga.')
    return private_response(await docs.original_bytes(row),row.media_type,row.filename)


@router.get('/documents/{document_id}/pages/{page}')
async def page_preview(document_id:str,page:int,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    row=await docs.document_for(db,principal,document_id)
    if row.status!='ready' or row.media_type!='application/pdf' or not 1<=page<=(row.page_count or 0):
        raise HTTPException(409,'PDF page unavailable.')
    try:rendered=await docs.parse(await docs.original_bytes(row),'preview',page)
    except (ValueError,TimeoutError):raise HTTPException(422,'PDF page render nahi ho saka.') from None
    return private_response(rendered,'image/png')


@router.post('/documents/{document_id}/extract',status_code=202)
async def extract_document(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services import invoice_extraction as extractor
    from app.services.invoice_extraction_jobs import request_extraction
    return await request_extraction(db,principal,document_id,split=False)


@router.get('/documents/{document_id}/drafts')
async def document_drafts(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services import invoice_extraction as extractor
    return await extractor.list_document_drafts(db,principal,document_id)


@router.post('/documents/{document_id}/split',status_code=202)
async def split_document(document_id:str,principal:CurrentPrincipal,db:AsyncSession=Depends(get_db)):
    from app.services import invoice_extraction as extractor
    from app.services.invoice_extraction_jobs import request_extraction
    return await request_extraction(db,principal,document_id,split=True)

