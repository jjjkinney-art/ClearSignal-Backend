"""
Application entry point for the AI analyst backend.

This module instantiates the FastAPI app and includes all API
routers. It also provides a root path description for the API.
"""

import logging
import time
import uuid as _uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api import router as api_router
from .startup import print_startup_diagnostics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """FastAPI lifespan handler: startup diagnostics + DB init, then DB shutdown."""
    print_startup_diagnostics()

    # Phase 9A — initialise persistence layer (no-op when DATABASE_URL is empty)
    try:
        from .config import settings as _settings
        from .db import init_db
        await init_db(_settings.database_url)
    except Exception as _exc:
        logger.warning("[startup] persistence layer init failed (non-fatal): %r", _exc)

    # Phase 9F — seed historical analogs (idempotent; skips rows that already exist)
    try:
        from .db import get_session as _get_session
        from .db.repositories.evidence_repo import seed_analogs as _seed_analogs
        async with _get_session() as _seed_session:
            if _seed_session is not None:
                _inserted = await _seed_analogs(_seed_session)
                logger.info("[startup] 9F analog seed: %d rows inserted", _inserted)
    except Exception as _seed_exc:
        logger.warning("[startup] 9F analog seed failed (non-fatal): %r", _seed_exc)

    yield

    # Phase 9A — dispose DB engine on shutdown
    try:
        from .db import close_db
        await close_db()
    except Exception as _exc:
        logger.warning("[shutdown] persistence layer close failed (non-fatal): %r", _exc)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AI Analyst Backend",
        version="0.1.0",
        description="Backend service for an AI‑powered company analysis platform",
        lifespan=lifespan,
    )

    # CORS (allow all origins for development — tighten in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request timing + request ID middleware
    @app.middleware("http")
    async def add_request_id_and_timing(request: Request, call_next):
        request_id = str(_uuid.uuid4())[:8]
        start = time.monotonic()
        request.state.request_id = request_id
        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        logger.info(
            "%s %s %s | %dms | req=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    app.include_router(api_router)
    return app


app = create_app()
