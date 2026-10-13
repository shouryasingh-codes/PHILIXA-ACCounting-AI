from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import limiter

from app.api.v1.routes_audio import router as audio_router
from app.api.v1.routes_auth import router as auth_router, ws_ticket_router
from app.api.v1.routes_clients import router as clients_router
from app.api.v1.routes_commitments import router as commitments_router
from app.api.v1.routes_dashboard import router as dashboard_router
from app.api.v1.routes_health import router as health_router
from app.api.v1.routes_jobs import router as jobs_router
from app.api.v1.routes_live import router as live_router
from app.api.v1.routes_meeting_notes import router as meeting_notes_router
from app.api.v1.routes_preferences import router as preferences_router
from app.api.v1.routes_vapi import router as vapi_router
from app.api.v1.routes_voice import router as voice_router
from app.api.v1.routes_business import router as business_router
from app.api.v1.routes_bill_documents import router as bill_documents_router
from app.api.v1.routes_tally import router as tally_router
from app.api.v1.routes_tally_bridge import router as tally_bridge_router
from app.api.v1.routes_webhooks import router as webhooks_router
from app.api.v1.routes_workspace import router as workspace_router
from app.core.config import get_settings
from app.core.csrf import CSRFProtectionMiddleware
from app.core.lifespan import lifespan as core_lifespan
from app.core.logging import configure_logging
from app.database.session import init_db

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if not settings.skip_startup_checks:
        await init_db()
    async with core_lifespan(app):
        yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="PHILIXA 6.0 Multi-Tenant SaaS Authentication & Copilot System.",
    lifespan=lifespan,
)

# Register SlowAPI limiter and 429 handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB


@app.middleware("http")
async def enforce_payload_size_limit(request: Request, call_next):
    # Exact file limit is enforced while reading UploadFile; permit multipart overhead.
    is_document_upload=request.method=='POST' and request.url.path.startswith('/api/v1/business/document-batches/') and request.url.path.endswith('/documents')
    request_limit=MAX_CONTENT_LENGTH+65536 if is_document_upload else MAX_CONTENT_LENGTH
    if is_document_upload:
        received=0
        original_receive=request._receive
        async def bounded_receive():
            nonlocal received
            message=await original_receive()
            if message['type']=='http.request':
                received+=len(message.get('body',b''))
                if received>request_limit:raise HTTPException(413,'Maximum document request size exceeded.')
            return message
        request._receive=bounded_receive
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > request_limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload Too Large: Maximum allowed request size is 10MB."},
                )
        except ValueError:
            pass
    response=await call_next(request)
    # Multipart parsers may translate a receive-limit exception into HTTP 400.
    if is_document_upload and received>request_limit:
        return JSONResponse(status_code=413,content={'detail':'Maximum document request size exceeded.'})
    return response

# 1. Strict CORS Middleware
raw_origins = settings.allowed_origins
if isinstance(raw_origins, list):
    origins = [o.strip() for o in raw_origins if o.strip()]
elif isinstance(raw_origins, str) and raw_origins.strip():
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    origins = ["http://localhost:8000", "http://localhost:3000", "http://127.0.0.1:8000"]

if "*" in origins:
    origins = [o for o in origins if o != "*"]

if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-CSRF-Token",
            "X-Requested-With",
            "Accept",
            "Origin",
        ],
        expose_headers=["Content-Length", "X-CSRF-Token"],
        max_age=600,
    )

# 2. CSRF Protection Middleware
app.add_middleware(CSRFProtectionMiddleware)

WEB_DIR = Path(__file__).resolve().parent / "web"


@app.get("/", include_in_schema=False)
def dashboard() -> HTMLResponse:
    # Explicitly read as UTF-8 to prevent browser charset misdetection
    content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        content=content, 
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


# 3. Public Health Router
app.include_router(health_router)

# 4. Auth & Workspace Routers (Dual-mounted at root and /api/v1 for test & API compatibility)
app.include_router(auth_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(workspace_router)
app.include_router(workspace_router, prefix="/api/v1")

# 5. Core API Routers (/api/v1)
app.include_router(meeting_notes_router, prefix="/api/v1")
app.include_router(clients_router, prefix="/api/v1")
app.include_router(commitments_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(audio_router)
app.include_router(audio_router, prefix="/api/v1")
app.include_router(live_router)
app.include_router(live_router, prefix="/api/v1")
app.include_router(voice_router, prefix="/api/v1")
app.include_router(business_router, prefix="/api/v1")
app.include_router(bill_documents_router,prefix='/api/v1')
app.include_router(tally_router, prefix="/api/v1")
app.include_router(tally_bridge_router, prefix="/api/v1")
app.include_router(vapi_router, prefix="/api/v1")
app.include_router(vapi_router)
app.include_router(ws_ticket_router)
app.include_router(ws_ticket_router, prefix="/api/v1")

# 6. Static Files
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
