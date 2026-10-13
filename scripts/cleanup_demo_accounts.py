import asyncio
from datetime import datetime, timedelta, timezone
import logging
import sys
import os

# Add the parent directory to sys.path so we can import 'app'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.user import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from typing import Any, Dict

async def cleanup_demo_accounts(ctx: Dict[str, Any] | None = None) -> None:
    logger.info("Starting demo account cleanup...")
    
    session_factory = (ctx.get("db_session_factory") if ctx else None) or AsyncSessionLocal
    async with session_factory() as db:
        stmt = select(User).where(User.email.like("demo_guest_%"))
        result = await db.execute(stmt)
        users = result.scalars().all()
        
        deleted_count = 0
        for user in users:
            await db.delete(user)
            deleted_count += 1
            
        await db.commit()
        logger.info(f"Cleanup complete. Deleted {deleted_count} old demo accounts.")

if __name__ == "__main__":
    asyncio.run(cleanup_demo_accounts())
