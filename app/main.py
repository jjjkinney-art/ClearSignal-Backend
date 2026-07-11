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

    # Phase 10C — apply delivery_ledger column additions (idempotent ALTER TABLE)
    # create_all() does not add columns to existing tables.  These two nullable
    # columns are added by 007_briefing_delivery.sql but must be re-applied here
    # for deployments where delivery_ledger already existed pre-10C.
    try:
        from .db import get_session as _get_session_10c
        from sqlalchemy import text as _text_10c
        _ALTERS = [
            "ALTER TABLE delivery_ledger ADD COLUMN IF NOT EXISTS canonical_severity VARCHAR(20)",
            "ALTER TABLE delivery_ledger ADD COLUMN IF NOT EXISTS severity_rank INTEGER",
            "CREATE INDEX IF NOT EXISTS ix_delivery_ledger_canonical_severity ON delivery_ledger (canonical_severity)",
        ]
        async with _get_session_10c() as _alt_sess:
            if _alt_sess is not None:
                for _stmt in _ALTERS:
                    try:
                        await _alt_sess.execute(_text_10c(_stmt))
                    except Exception:
                        pass   # column/index already exists — no-op
                await _alt_sess.commit()
                logger.info("[startup] 10C delivery_ledger column migration applied (idempotent)")
    except Exception as _alt_exc:
        logger.warning("[startup] 10C delivery_ledger migration failed (non-fatal): %r", _alt_exc)

    # Phase 10B — backfill watched_tickers from flat-file index.json (idempotent)
    try:
        from .db import get_session as _get_session
        from .db.repositories.watchlist_repo import ticker_add as _ticker_add
        from .services.watchlist_service import watchlist_service as _wl_service
        async with _get_session() as _wl_session:
            if _wl_session is not None:
                _entries = _wl_service.get_watchlist()
                _bf_added = 0
                for _e in _entries:
                    if _e.ticker:
                        _row = await _ticker_add(
                            _wl_session,
                            _e.ticker,
                            company_name=getattr(_e, "company_name", "") or "",
                        )
                        if _row is not None:
                            _bf_added += 1
                logger.info("[startup] 10B watched_tickers backfill: %d rows upserted", _bf_added)
    except Exception as _bf_exc:
        logger.warning("[startup] 10B watched_tickers backfill failed (non-fatal): %r", _bf_exc)

    # Phase 16 · Slice 2 — System user seed + NULL ownership claim (idempotent)
    # Ensures the well-known SYSTEM_DEFAULT_USER row exists and claims every
    # NULL user_id row across all user-scoped tables.  Runs at every boot;
    # second and subsequent runs claim 0 rows (idempotent).
    try:
        from .db import get_session as _get_session_16
        from .services.system_user_service import (
            ensure_system_user as _ensure_system_user,
            claim_null_ownership as _claim_null,
        )
        async with _get_session_16() as _identity_sess:
            if _identity_sess is not None:
                await _ensure_system_user(_identity_sess)
                _claim_result = await _claim_null(_identity_sess)
                await _identity_sess.commit()
                logger.info(
                    "[startup] 16.2 identity: system user seeded, %d orphan rows claimed",
                    _claim_result.total,
                )
    except Exception as _identity_exc:
        logger.warning("[startup] 16.2 identity seed failed (non-fatal): %r", _identity_exc)

    yield

    # Phase 9A — dispose DB engine on shutdown
    try:
        from .db import close_db
        await close_db()
    except Exception as _exc:
        logger.warning("[shutdown] persistence layer close failed (non-fatal): %r", _exc)


_API_DESCRIPTION = """\
Backend for **ClearSignal** — an AI-powered equity analysis platform.

The conviction engine (frozen, institutionally validated) produces structured
theses, dossiers, and scenarios. This API exposes the user-facing beta surfaces
built on top of it.

### Identity & rollout

Most product surfaces are scoped to the acting user:

* **`AUTH_ENABLED=false` (default):** every request resolves to a single system
  *bypass* user — the API behaves single-tenant. No JWT is inspected.
* **`AUTH_ENABLED=true`:** identity is the verified Supabase JWT `sub`; requests
  without a valid token receive **401** on user-scoped routes.

Several capabilities are dark-launched behind flags and are inert until enabled
by an operator (never in code): `STRIPE_ENABLED` (billing), `DELIVERY_SHADOW` /
`DELIVERY_IN_APP_ENABLED` (real notification delivery), `WATCHLIST_DB_BACKED`
(persistent multi-instance watchlists), and the scenario build/scoring flags.

### Conventions

* `request.state.user_id` is stamped by the auth middleware before every handler.
* Read endpoints degrade gracefully when persistence is disabled (empty payloads,
  never 5xx). `/readyz` is the dependency-aware readiness probe.
* No endpoint returns buy/sell/hold or price-target language — the engine is a
  describer, not a recommender.
"""

_OPENAPI_TAGS = [
    {"name": "health",
     "description": "Liveness (`/`, `/health`, `/healthz`) and readiness (`/readyz`) "
                    "probes. `/readyz` returns **503** when a required dependency (DB) "
                    "is configured but unreachable, so orchestrators can gate traffic."},
    {"name": "watchlist",
     "description": "Track tickers and their thesis-snapshot history. Membership is "
                    "DB-backed when `WATCHLIST_DB_BACKED=true` (persistent, multi-instance) "
                    "and scoped to the authenticated user; otherwise a local JSON index."},
    {"name": "portfolio",
     "description": "Position CRUD plus portfolio-level intelligence — concentration / "
                    "diversification **health**, shared-risk **exposure** clusters, and "
                    "**insights**. All reads are scoped to the caller's default portfolio."},
    {"name": "scenarios",
     "description": "Read-only Scenario Engine — *“what changes if X happens?”*. Returns "
                    "descriptive scenario facets per ticker (transmission path, plausibility, "
                    "confidence). Purely descriptive; no conviction, stance, or price fields."},
    {"name": "notifications",
     "description": "In-app notification inbox, unread counts, idempotent read receipts, and "
                    "delivery preferences. Surfaces the delivery ledger read-only while "
                    "delivery stays in shadow mode (no real sends)."},
    {"name": "auth",
     "description": "Supabase JWT session endpoints (`/auth/me`, `/auth/session`, "
                    "`/auth/logout`). Enforced only when `AUTH_ENABLED=true`; a system bypass "
                    "user is used otherwise."},
    {"name": "billing",
     "description": "Stripe checkout, webhook receiver, subscription **status**, billing "
                    "portal, and cancel. Mutating routes return **503** and the webhook is a "
                    "no-op until `STRIPE_ENABLED=true`. The system user cannot check out."},
    {"name": "admin",
     "description": "Internal observability / status snapshots for each subsystem. Not part "
                    "of the public product surface."},
]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ClearSignal API",
        version="0.1.0",
        description=_API_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        lifespan=lifespan,
        contact={"name": "ClearSignal"},
    )

    # Phase 16 · Slice 3 — Identity middleware (runs innermost; added first so
    # CORSMiddleware wraps it and preflight requests are handled before auth).
    # In bypass mode (AUTH_ENABLED=false) this is a pure no-op: stamps
    # request.state.user_id = SYSTEM_DEFAULT_USER_ID on every request and
    # returns immediately without inspecting headers or verifying JWTs.
    from .middleware.auth_middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware)

    # CORS — environment-driven explicit allowlist (Sprint 0).
    # Never serve a wildcard origin together with credentials, and never allow
    # a wildcard origin at all in production.  Localhost dev origins are the
    # default so local development keeps working out of the box.
    from .config import settings as _cors_settings
    _cors_origins = _cors_settings.cors_allow_origins_list
    _cors_credentials = _cors_settings.cors_allow_credentials
    if _cors_settings.is_production and "*" in _cors_origins:
        logger.error(
            "[cors] wildcard '*' origin is not permitted in production; ignoring it. "
            "Set CORS_ALLOW_ORIGINS to an explicit frontend allowlist."
        )
        _cors_origins = [o for o in _cors_origins if o != "*"]
    if "*" in _cors_origins and _cors_credentials:
        # '*' with credentials is invalid per the Fetch spec and browsers reject
        # it; disable credentials so a real (non-credentialed) wildcard still works.
        logger.warning(
            "[cors] '*' origin with credentials is invalid; disabling allow_credentials."
        )
        _cors_credentials = False
    logger.info(
        "[cors] origins=%s credentials=%s production=%s",
        _cors_origins or "(none)", _cors_credentials, _cors_settings.is_production,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_cors_credentials,
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
