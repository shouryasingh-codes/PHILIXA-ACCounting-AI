"""Remove only orphan cron wakeups, never jobs with payloads or accounting actions."""
import asyncio,time
from app.core.redis import get_redis_client

async def main():
    redis=await get_redis_client();removed=0
    try:
        queue='philixa:tally:worker'
        entries=await redis.zrangebyscore(queue,'-inf',int(time.time()*1000),start=0,num=20000)
        for raw in entries:
            job=raw.decode() if isinstance(raw,bytes) else raw
            if not job.startswith(('cron:sync_tick:','cron:automation_tick:')):continue
            # An absent ARQ payload is already expired and cannot run.
            # Atomic recheck prevents racing a newly populated job.
            removed+=await redis.eval("if redis.call('EXISTS', KEYS[2]) == 0 then return redis.call('ZREM', KEYS[1], ARGV[1]) else return 0 end",2,queue,'arq:job:'+job,raw)
        print('Expired orphan cron wakeups removed:',removed)
    finally:await redis.aclose()
if __name__=='__main__':asyncio.run(main())
