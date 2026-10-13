"""Real PostgreSQL + private MinIO fixtures; no real bills, AI or Tally writes."""
import asyncio
import io
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from fastapi import HTTPException,UploadFile
from sqlalchemy import select,func
from PIL import Image
import pymupdf
from app.models.bill_document import BillDocument,DocumentBatchItem
from app.database.session import AsyncSessionLocal
from app.services import bill_document_service as docs,document_storage as storage
from app.services.document_validation import inspect,RejectedDocument
from app.jobs import document_jobs as jobs
from app.api.v1 import routes_bill_documents as routes
import scripts.test_tally_sync as fixtures


def picture(format='PNG',colour='green'):
    out=io.BytesIO();Image.new('RGB',(40,40),colour).save(out,format=format);return out.getvalue()


def pdf(pages=1,password=False):
    with pymupdf.open() as doc:
        for i in range(pages):doc.new_page().insert_text((30,50),'Synthetic bill page '+str(i+1))
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,user_pw='synthetic',owner_pw='owner') if password else doc.tobytes()


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.DurableTests.asyncSetUp(self)
        self.real_enqueue=docs.enqueue
        self.enqueue=patch.object(docs,'enqueue',AsyncMock());self.enqueue.start()
        self.batch=await docs.create_batch(self.db,self.principal,docs.BatchCreate(company_id=self.company.id))
    async def asyncTearDown(self):
        self.enqueue.stop()
        rows=list((await self.db.scalars(select(BillDocument).where(BillDocument.organization_id==self.org))).all())
        for row in rows:await asyncio.to_thread(storage.remove,row.object_key)
        await fixtures.DurableTests.asyncTearDown(self)

    async def upload(self,data=None,filename='bill.png',batch=None):
        return await docs.upload_document(self.db,self.principal,batch or self.batch['id'],UploadFile(io.BytesIO(data or picture()),filename=filename))

    async def test_pdf_jpg_png_worker_ready_original_and_page_preview(self):
        for data,filename,media in ((picture(),'bill.png','image/png'),(picture('JPEG'),'bill.jpg','image/jpeg'),(pdf(2),'bill.pdf','application/pdf')):
            result=await self.upload(data,filename);docid=result['document']['id']
            self.assertEqual(result['document']['status'],'queued')
            await jobs.validate_bill_document({},docid)
            async with AsyncSessionLocal() as fresh:
                row=await docs.document_for(fresh,self.principal,docid)
                self.assertEqual(row.status,'ready');self.assertEqual(row.media_type,media)
                response=await routes.original(docid,self.principal,fresh)
                self.assertEqual(response.body,data);self.assertEqual(response.headers['cache-control'],'private, no-store')
                if media=='application/pdf':
                    page=await routes.page_preview(docid,2,self.principal,fresh)
                    self.assertTrue(page.body.startswith(b'\x89PNG'))
        self.assertEqual(len((await docs.read_batch(self.db,self.principal,self.batch['id']))['documents']),3)

    async def test_duplicate_within_and_across_batches_reuses_original(self):
        first=await self.upload();second=await self.upload(filename='renamed.png')
        other_batch=await docs.create_batch(self.db,self.principal,docs.BatchCreate(company_id=self.company.id))
        third=await self.upload(batch=other_batch['id'])
        self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate']);self.assertTrue(third['duplicate'])
        self.assertEqual(first['document']['id'],third['document']['id'])
        self.assertEqual(len((await docs.read_batch(self.db,self.principal,self.batch['id']))['documents']),1)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(BillDocument).where(BillDocument.organization_id==self.org)),1)

    async def test_private_scope_disabled_company_and_no_object_key_in_response(self):
        result=await self.upload();docid=result['document']['id']
        self.assertNotIn('object_key',result['document']);self.assertNotIn('sha256',result['document'])
        for change in ({'user_id':'other'},{'organization_id':'other'}):
            other=SimpleNamespace(**{**self.principal.__dict__,**change})
            for operation in (docs.read_batch(self.db,other,self.batch['id']),docs.document_for(self.db,other,docid),
                routes.original(docid,other,self.db),routes.page_preview(docid,1,other,self.db),docs.retry_document(self.db,other,docid)):
                with self.assertRaises(HTTPException) as error:await operation
                self.assertEqual(error.exception.status_code,404)
        self.company.enabled=False;await self.db.commit()
        with self.assertRaises(HTTPException):await docs.document_for(self.db,self.principal,docid)

    async def test_corrupt_password_and_page_limits_have_clear_terminal_errors(self):
        for data,code in ((b'%PDF-not a PDF','corrupt_document'),(pdf(password=True),'password_protected'),(pdf(21),'page_limit')):
            result=await self.upload(data,'test.pdf');docid=result['document']['id'];await jobs.validate_bill_document({},docid)
            row=await self.db.get(BillDocument,docid,populate_existing=True)
            self.assertEqual(row.status,'rejected');self.assertEqual(row.error_code,code)
            with self.assertRaises(HTTPException):await routes.original(docid,self.principal,self.db)
            with self.assertRaises(HTTPException):await docs.retry_document(self.db,self.principal,docid)
        self.assertEqual(inspect(pdf(20))['page_count'],20)

    async def test_size_type_and_batch_limit_with_duplicate_at_capacity(self):
        for data,expected in ((b'%PDF-'+b'0'*storage.MAX_BYTES,413),(b'<html>not a bill</html>',415)):
            with self.assertRaises(HTTPException) as error:await self.upload(data)
            self.assertEqual(error.exception.status_code,expected)
        for i in range(50):await self.upload(picture(colour=(i,40,70)))
        with self.assertRaises(HTTPException) as error:await self.upload(picture(colour='red'))
        self.assertEqual(error.exception.status_code,409)
        self.assertTrue((await self.upload(picture(colour=(0,40,70))))['duplicate'])

    async def test_pending_work_and_expired_lease_survive_restart(self):
        result=await self.upload();docid=result['document']['id']
        row=await self.db.get(BillDocument,docid);row.status='processing';row.attempts=1
        row.lease_token='old-worker';row.lease_until=docs.now()-timedelta(seconds=1);await self.db.commit()
        pool=SimpleNamespace(enqueue_job=AsyncMock())
        self.enqueue.stop()
        try:await jobs.recover_bill_documents({'redis':pool})
        finally:self.enqueue.start()
        self.assertIn(docid,[call.args[1] for call in pool.enqueue_job.await_args_list])
        await jobs.validate_bill_document({},docid)
        async with AsyncSessionLocal() as fresh:
            recovered=await docs.document_for(fresh,self.principal,docid)
            self.assertEqual(recovered.status,'ready');self.assertEqual(recovered.attempts,2)
        self.assertEqual((await docs.read_batch(self.db,self.principal,self.batch['id']))['documents'][0]['status'],'ready')

    async def test_redis_failure_does_not_lose_upload_and_processing_retry_is_bounded(self):
        result=await self.upload();docid=result['document']['id']
        row=await self.db.get(BillDocument,docid)
        broken=SimpleNamespace(enqueue_job=AsyncMock(side_effect=ConnectionError('synthetic Redis outage')))
        await self.real_enqueue(row,broken)
        self.assertEqual((await docs.read_batch(self.db,self.principal,self.batch['id']))['documents'][0]['status'],'queued')
        with patch.object(docs,'original_bytes',AsyncMock(side_effect=HTTPException(503,'offline'))):
            for attempt in range(3):
                row=await self.db.get(BillDocument,docid,populate_existing=True);row.next_attempt_at=None;await self.db.commit()
                await jobs.validate_bill_document({},docid)
        row=await self.db.get(BillDocument,docid,populate_existing=True)
        self.assertEqual(row.status,'error');self.assertEqual(row.attempts,3)
        retried=await docs.retry_document(self.db,self.principal,docid);self.assertEqual(retried['status'],'queued')
        await jobs.validate_bill_document({},docid)
        self.assertEqual((await docs.document_for(self.db,self.principal,docid)).status,'ready')

    async def test_stale_worker_cannot_overwrite_new_lease(self):
        result=await self.upload();docid=result['document']['id']
        async def superseded(data,mode='inspect',page=None):
            async with AsyncSessionLocal() as other:
                row=await other.get(BillDocument,docid);row.lease_token='new-worker';row.status='processing';await other.commit()
            return {'media_type':'image/png','page_count':1}
        with patch.object(docs,'parse',side_effect=superseded):await jobs.validate_bill_document({},docid)
        row=await self.db.get(BillDocument,docid,populate_existing=True)
        self.assertEqual(row.status,'processing');self.assertEqual(row.lease_token,'new-worker')

    async def test_bucket_is_private_to_anonymous_requests(self):
        import httpx
        result=await self.upload();row=await self.db.get(BillDocument,result['document']['id'])
        async with httpx.AsyncClient(trust_env=False) as client:
            reply=await client.get('http://minio:9000/'+storage.bucket()+'/'+row.object_key)
        self.assertEqual(reply.status_code,403)

    async def test_concurrent_duplicates_in_different_batches_create_one_original(self):
        other=await docs.create_batch(self.db,self.principal,docs.BatchCreate(company_id=self.company.id))
        async def send(batch_id):
            async with AsyncSessionLocal() as db:
                return await docs.upload_document(db,self.principal,batch_id,UploadFile(io.BytesIO(picture()),filename='same.png'))
        first,second=await asyncio.gather(send(self.batch['id']),send(other['id']))
        self.assertEqual(first['document']['id'],second['document']['id'])
        self.assertEqual(sorted([first['duplicate'],second['duplicate']]),[False,True])

    async def test_http_upload_boundary_viewer_auth_and_download_headers(self):
        import httpx
        from app.main import app
        from app.core.auth import get_current_principal
        from app.database.session import get_db
        async def db_dependency():yield self.db
        app.dependency_overrides[get_db]=db_dependency
        app.dependency_overrides[get_current_principal]=lambda:self.principal
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer synthetic'}) as client:
                exact=picture();exact+=b'\x00'*(storage.MAX_BYTES-len(exact))
                response=await client.post('/api/v1/business/document-batches/'+self.batch['id']+'/documents',files={'file':('exact.png',exact,'image/png')})
                self.assertEqual(response.status_code,202,response.text)
                async def chunked_body():
                    yield b'--day3\r\nContent-Disposition: form-data; name="file"; filename="huge.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
                    for _ in range(11):yield b'x'*(1024*1024)
                    yield b'\r\n--day3--\r\n'
                oversized=await client.post('/api/v1/business/document-batches/'+self.batch['id']+'/documents',content=chunked_body(),headers={'Content-Type':'multipart/form-data; boundary=day3'})
                self.assertEqual(oversized.status_code,413,oversized.text)
                docid=response.json()['document']['id'];await jobs.validate_bill_document({},docid)
                original=await client.get('/api/v1/business/documents/'+docid+'/original')
                self.assertEqual(original.status_code,200);self.assertEqual(original.content,exact)
                self.assertIn('attachment',original.headers['content-disposition']);self.assertEqual(original.headers['x-content-type-options'],'nosniff')
                app.dependency_overrides.pop(get_current_principal)
                unauth=await client.get('/api/v1/business/documents/'+docid+'/original',headers={'Authorization':''})
                self.assertEqual(unauth.status_code,401)
        finally:app.dependency_overrides.clear()


if __name__=='__main__':unittest.main()
