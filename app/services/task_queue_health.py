"""Read-only queue heartbeat annotation; never resumes work or changes task state."""
import asyncio


async def annotate(result):
    if result.get('action_id') or result.get('status') not in ('queued','running','waiting_context'):return result
    from app.core.redis import get_redis_client
    from app.services.bill_document_service import QUEUE
    try:
        redis=await get_redis_client()
        heartbeat=await asyncio.wait_for(redis.exists(QUEUE+':health-check'),timeout=1)
        state='online' if heartbeat else 'unavailable'
    except Exception:state='unknown'
    result={**result,'worker_state':state}
    if state!='online':
        result.update(progress_active=False,response='Task saved hai. Background worker abhi available nahi hai; kaam start hua nahi maana gaya. Status automatically check ho raha hai.')
    else:
        # A heartbeat proves the worker is alive, not that this job is executing.
        result['progress_active']=result.get('execution_stage')=='running'
        if result.get('status')=='queued':
            result.update(execution_stage='waiting_worker',response='Task saved hai. Worker ki queue mein hai; processing abhi shuru nahi hui.')
    return result
