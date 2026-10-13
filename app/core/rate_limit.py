"""
Rate limiting configuration for Philixa API.
Uses SlowAPI (wrapper around the `limits` library) with in-memory storage.
Key func = client IP address via get_remote_address.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Global limiter instance - imported by main.py and individual route modules.
# Default: 60 requests/minute per IP (applies to all non-decorated endpoints).
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
