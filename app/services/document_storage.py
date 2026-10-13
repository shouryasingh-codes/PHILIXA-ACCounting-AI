"""Dedicated private bucket. Originals are served through authenticated APIs only."""
import io
import os
from functools import lru_cache
from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager,Timeout
from app.core.config import get_settings

MAX_BYTES=10*1024*1024


@lru_cache
def client():
    settings=get_settings()
    return Minio(settings.minio_url,access_key=settings.minio_access_key,secret_key=settings.minio_secret_key,
        secure=os.getenv('PHILIXA_MINIO_SECURE','0')=='1',http_client=PoolManager(num_pools=4,maxsize=8,timeout=Timeout(connect=3,read=15),retries=False))


def bucket():
    name=os.getenv('PHILIXA_DOCUMENTS_BUCKET','philixa-bill-originals')
    if name==get_settings().minio_bucket_name:raise RuntimeError('Documents require a separate private bucket')
    c=client()
    if not c.bucket_exists(name):
        try:c.make_bucket(name)
        except S3Error as exc:
            if exc.code not in ('BucketAlreadyExists','BucketAlreadyOwnedByYou'):raise
    try:
        policy=c.get_bucket_policy(name)
        if policy:raise RuntimeError('Documents bucket must have no public access policy')
    except S3Error as exc:
        if exc.code!='NoSuchBucketPolicy':raise
    return name


def put(key,data,media_type):
    client().put_object(bucket(),key,io.BytesIO(data),len(data),content_type=media_type)


def read(key):
    response=client().get_object(bucket(),key)
    try:
        data=response.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise RuntimeError('Stored document exceeds limit')
        return data
    finally:response.close();response.release_conn()


def remove(key):
    client().remove_object(bucket(),key)
