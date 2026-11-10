"""Private CPU reader. No database, credentials, Groq or Tally access."""
import asyncio
import io
import json
import multiprocessing
import os
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
lock = asyncio.Lock()


def infer(data, connection):
    try:
        started=time.monotonic()
        import resource
        import numpy as np
        from runtime import pipeline
        image = Image.open(io.BytesIO(data)).convert('RGB')
        results = list(pipeline().predict(np.array(image),use_table_orientation_classify=False))
        if len(results) != 1:
            raise ValueError('single_page_required')
        value = results[0].json
        if callable(value): value = value()
        if isinstance(value, str): value = json.loads(value)
        encoded = json.dumps(value)
        if len(encoded.encode()) > 8 * 1024 * 1024: raise ValueError('layout_output_limit')
        connection.send({'status': 'ok', 'result': value,
                         'manifest': json.loads(Path('/opt/philixa-models/manifest.json').read_text()),
                         'telemetry':{'reader_latency_ms':round((time.monotonic()-started)*1000),
                                      'reader_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}})
    except Exception as exc:
        connection.send({'status': 'error', 'reason': 'layout_inference_failed', 'exception_type': type(exc).__name__})
    finally:
        connection.close()


@app.get('/health')
async def health():
    return {'reader': 'ppstructure-v3', 'candidate': True}


@app.post('/read')
async def read(request: Request):
    if lock.locked(): return JSONResponse({'status': 'error', 'reason': 'layout_busy'}, 409)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 10 * 1024 * 1024:
            return JSONResponse({'status': 'error', 'reason': 'file_size'}, 413)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 4_000_000:
                raise ValueError()
            if image.getexif().get(274,1)!=1:
                raise ValueError('Photo orientation needs normalization before source-grounded review')
            image.load()
    except Exception:
        return JSONResponse({'status': 'error', 'reason': 'layout_image_invalid_or_limit'}, 422)
    async with lock:
        ctx = multiprocessing.get_context('spawn')
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=infer, args=(bytes(data), child))
        process.start(); child.close(); start = time.monotonic()
        try:
            while time.monotonic() - start < 90:
                if parent.poll(): return parent.recv()
                if not process.is_alive():
                    return JSONResponse({'status': 'error', 'reason': 'layout_process_failed'}, 503)
                await asyncio.sleep(.1)
            return JSONResponse({'status': 'error', 'reason': 'layout_timeout'}, 504)
        finally:
            if process.is_alive(): process.terminate()
            await asyncio.to_thread(process.join, 3)
            if process.is_alive(): process.kill(); await asyncio.to_thread(process.join)
            parent.close()
