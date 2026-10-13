"""Outbound HTTPS long-poll bridge. Redis coordinates all server workers."""
import hashlib
import json
import secrets
import logging
from time import perf_counter
from fastapi import HTTPException
from app.core.redis import get_redis_client
from app.services.tally_connector import TallyError
logger = logging.getLogger(__name__)

def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()

async def request_job(device, operation, **parameters):
    from app.services.tally_sync_protocol import OPERATIONS
    if operation not in OPERATIONS:
        raise TallyError('Unsupported helper operation.')
    redis = await get_redis_client()
    job_id = secrets.token_hex(16)
    started, outcome = perf_counter(), 'error'
    job = {'id': job_id, 'device_id': device.id, 'organization_id': device.organization_id,
           'credential_version': device.credential_hash, 'operation': operation, **parameters}
    try:
        if not await redis.exists('tally:online:' + device.id):
            raise TallyError('Helper offline. Philixa Tally Connector kholkar reconnect karein.')
        if operation not in ('discover','stock') and not await redis.exists('tally:v2online:'+device.id):
            raise TallyError('Setup needed: update Philixa Tally Connector for saved data and purchase sync.')
        if operation.startswith('stock_count_') and not await redis.exists('tally:v3online:'+device.id):
            raise TallyError('Update Philixa Tally Connector for physical count review.')
        if operation.startswith('mcp_') and not await redis.exists('tally:v4online:'+device.id):
            raise TallyError('Updated bundled MCP Tally Connector required.')
        if operation=='mcp_compile' and not await redis.exists('tally:v5online:'+device.id):
            raise TallyError('Update Tally Connector for operation draft compilation.')
        if operation.startswith('customer_ledger_') and not await redis.exists('tally:v6online:'+device.id):
            raise TallyError('Tally Connector update required for customer ledger creation. Saved pairing remains valid.')
        if operation.startswith('purchase_gst_') and not await redis.exists('tally:v8online:'+device.id):
            raise TallyError('Update Philixa Tally Connector (v8) for GST/discount purchases.')
        if operation.startswith('purchase_multi_') and not await redis.exists('tally:v7online:'+device.id):
            raise TallyError('Update Tally Connector (v7) for multi-item purchase. Saved pairing remains valid.')
        await redis.set('tally:job:' + job_id, json.dumps(job), ex=30)
        queue = ('tally:queue:v8:' if operation.startswith('purchase_gst_') else 'tally:queue:v7:' if operation.startswith('purchase_multi_') else 'tally:queue:v6:' if operation.startswith('customer_ledger_') else 'tally:queue:v5:' if operation=='mcp_compile' else 'tally:queue:v4:' if operation.startswith('mcp_') else 'tally:queue:v3:' if operation.startswith('stock_count_') else 'tally:queue:' if operation in ('discover','stock') else 'tally:queue:v2:') + device.id
        async with redis.pipeline(transaction=True) as pipe:
            pipe.rpush(queue, json.dumps(job))
            pipe.expire(queue, 40)
            await pipe.execute()
        result = await redis.blpop('tally:result:' + job_id, timeout=23)
        if not result:
            raise TallyError('Helper read timeout; stock unknown.')
        data = json.loads(result[1])
        if data.get('error'):
            # Device diagnostics are fixed messages, never raw Tally error payloads.
            raise TallyError(data['error'][:200])
        outcome = 'ok'
        return data['data']
    finally:
        await redis.delete('tally:job:' + job_id, 'tally:result:' + job_id)
        await redis.aclose()
        logger.info('tally_bridge job=%s device=%s operation=%s outcome=%s duration_ms=%.1f',job_id,device.id,operation,outcome,(perf_counter()-started)*1000)


async def consume_result(redis, device, job_id, result):
    key = 'tally:job:' + job_id
    original = await redis.get(key)
    if not original:
        raise HTTPException(410, 'Expired/duplicate result')
    job = json.loads(original)
    if job['device_id'] != device.id or job['organization_id'] != device.organization_id or job['credential_version'] != device.credential_hash:
        raise HTTPException(403, 'Wrong device')
    if len(json.dumps(result).encode()) > 2_000_000:
        raise HTTPException(413, 'Result too large')
    # Compare-delete and result publication in one operation: no stolen/duplicate results.
    accepted = await redis.eval("""
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
        redis.call('DEL', KEYS[1])
        redis.call('RPUSH', KEYS[2], ARGV[2])
        redis.call('EXPIRE', KEYS[2], 30)
        return 1
    """, 2, key, 'tally:result:' + job_id, original, json.dumps(result))
    if not accepted:
        raise HTTPException(410, 'Expired/duplicate result')
