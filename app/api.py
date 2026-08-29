from __future__ import annotations

"""
FastAPI routes for the AI analyst backend.

Defines endpoints for health checking and company analysis. The
analysis endpoint uses the service layer to orchestrate agent
execution and returns a structured response.

Enterprise lifecycle:
    The /analyze endpoint extracts X-Request-ID, X-Session-ID, X-User-ID,
    and X-Tenant-ID headers and builds a ScopeContext that is propagated
    through the full analysis lifecycle (evidence, agents, monitoring,
    alerts).
"""

import logging
from typing import Optional

import requests as _requests
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .schemas import (
    AnalysisRequest,
    AnalysisResponse,
    QuestionRequest,
    AgentAnswerResponse,
    WatchlistEntry,
    ThesisSnapshot,
    ThesisDiff,
    MaterialChangeEvent,
)
from .services.analysis_service import analyze_company
from .services.router_service import route_question
from .services.watchlist_service import watchlist_service

logger = logging.getLogger(__name__)

# Enterprise scope extraction
try:
    from .enterprise.tenant import ScopeContext, TenantScope, UserScope, register_scope
    _API_ENTERPRISE = True
except Exception:
    _API_ENTERPRISE = False


router = APIRouter()

# Phase 10C · Slice 7 — delivery preferences sub-router
try:
    from .routers.delivery_preferences import router as _delivery_prefs_router
    router.include_router(_delivery_prefs_router)
except Exception as _dp_err:
    logger.warning("[api] delivery_preferences router unavailable: %r", _dp_err)

# Phase 10C · Slice 8 — delivery inbox / digest read API
try:
    from .routers.delivery_inbox import router as _delivery_inbox_router
    router.include_router(_delivery_inbox_router)
except Exception as _di_err:
    logger.warning("[api] delivery_inbox router unavailable: %r", _di_err)

# Phase 16 · Slice 4 — auth routes (/auth/me, /auth/session, /auth/logout)
try:
    from .routers.auth import router as _auth_router
    router.include_router(_auth_router)
except Exception as _auth_err:
    logger.warning("[api] auth router unavailable: %r", _auth_err)

# Phase 16 · Slice 8 — admin auth observability (GET /admin/auth-status)
try:
    from .routers.admin_auth import router as _admin_auth_router
    router.include_router(_admin_auth_router)
except Exception as _aa_err:
    logger.warning("[api] admin_auth router unavailable: %r", _aa_err)

# Phase 17 · Slice 3 — billing routes (POST /billing/checkout)
try:
    from .routers.billing import router as _billing_router
    router.include_router(_billing_router)
except Exception as _billing_err:
    logger.warning("[api] billing router unavailable: %r", _billing_err)

# Beta milestone 2 — portfolio routes (positions CRUD, health, exposure, insights)
try:
    from .routers.portfolio import router as _portfolio_router
    router.include_router(_portfolio_router)
except Exception as _pf_err:
    logger.warning("[api] portfolio router unavailable: %r", _pf_err)

# Beta milestone 3 — scenario read routes (scenarios, ticker facet, portfolio impact)
try:
    from .routers.scenario import router as _scenario_router
    router.include_router(_scenario_router)
except Exception as _sc_err:
    logger.warning("[api] scenario router unavailable: %r", _sc_err)

# Beta milestone 4 — notification routes (inbox, unread, mark-read, preferences)
try:
    from .routers.notifications import router as _notifications_router
    router.include_router(_notifications_router)
except Exception as _nt_err:
    logger.warning("[api] notifications router unavailable: %r", _nt_err)


def _extract_scope(request: Request) -> "ScopeContext | None":
    """Extract tenant/user scope from standard enterprise HTTP headers.

    Headers consumed:
        X-Request-ID  : client-assigned request identifier
        X-Session-ID  : session identifier for correlation
        X-User-ID     : authenticated user identifier
        X-Tenant-ID   : tenant/organization identifier
    """
    if not _API_ENTERPRISE:
        return None
    try:
        headers    = request.headers
        user_id    = headers.get("X-User-ID",   "")
        tenant_id  = headers.get("X-Tenant-ID", "")
        session_id = headers.get("X-Session-ID", headers.get("X-Request-ID", ""))
        if not (user_id or tenant_id or session_id):
            return None
        scope = ScopeContext(
            user_id    = user_id,
            tenant_id  = tenant_id,
            session_id = session_id,
        )
        if session_id:
            register_scope(scope)
        return scope
    except Exception:
        return None


async def health() -> dict:
    """Return service health and identity.

    Registered on GET + HEAD for:  /  /health  /healthz
    Suitable for UptimeRobot (HEAD), Render health checks, and frontend warmup pings.
    HEAD requests return 200 with an empty body; GET requests return the full JSON.

    Response fields:
      status      — always "ok" when the process is up
      service     — stable service identifier
      version     — conviction schema version loaded at startup
      timestamp   — current UTC ISO-8601 timestamp
      environment — "production" / "development" / "unknown"
      build_commit — short git SHA from RENDER_GIT_COMMIT env var
    """
    import time as _t
    import os as _o

    git_commit = (
        _o.environ.get("RENDER_GIT_COMMIT", "")[:12]
        or _o.environ.get("GIT_COMMIT", "")[:12]
        or "unknown"
    )
    environment = (
        "production"  if _o.environ.get("RENDER_SERVICE_ID") else
        "development" if _o.environ.get("NODE_ENV") != "production" else
        "unknown"
    )

    try:
        from .services.conviction_modeler import CONVICTION_SCHEMA_VERSION
        version = CONVICTION_SCHEMA_VERSION
    except Exception:
        version = "unknown"

    from .config import settings as _s

    # Phase 9B: DB health gate — exposed for production validation
    db_enabled = False
    db_table_count = 0
    try:
        from .db.connection import _db_enabled as _dbe, _engine as _eng
        db_enabled = bool(_dbe)
        if _eng is not None:
            from sqlalchemy import inspect as _inspect, text as _text
            async with _eng.connect() as _conn:
                # Count tables visible in the default schema
                _result = await _conn.execute(
                    _text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                    if not str(_eng.url).startswith("sqlite")
                    else _text(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    )
                )
                row = _result.fetchone()
                db_table_count = int(row[0]) if row else 0
    except Exception:
        pass

    return {
        "status":       "ok",
        "service":      "clearsignal-backend",
        "version":      version,
        "timestamp":    _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
        "environment":  environment,
        "build_commit": git_commit,
        # Phase 9B: DB health gate
        "db_enabled":    db_enabled,
        "db_table_count": db_table_count,
        # Config telemetry — verify timeout/retry values are actually live on Render
        "cfg_agent_timeout":        getattr(_s, "agent_timeout", "MISSING"),
        "cfg_agent_max_retries":    getattr(_s, "agent_max_retries", "MISSING"),
        "cfg_synthesis_timeout":    getattr(_s, "synthesis_timeout", "MISSING"),
        "cfg_synthesis_max_tokens": getattr(_s, "synthesis_max_tokens", "MISSING"),
        "cfg_synthesis_max_retries":getattr(_s, "synthesis_max_retries", "MISSING"),
        "cfg_agent_model":          getattr(_s, "agent_model", "MISSING"),
    }


# Register GET + HEAD on all three health paths.
# FastAPI/Starlette 0.49+ does NOT auto-add HEAD for GET routes — must be explicit.
# UptimeRobot free plan uses HEAD; Render uses GET; frontend warmup uses GET.
for _health_path in ("/", "/health", "/healthz"):
    # Register GET and HEAD as SEPARATE routes with unique names so each gets a
    # unique OpenAPI operationId (a single GET+HEAD route shares one operationId
    # across both methods, which FastAPI flags as a duplicate and which breaks
    # client generators). HEAD is for uptime monitors, not API consumers, so it
    # is kept out of the schema.
    _health_name = "root" if _health_path == "/" else _health_path.strip("/")
    router.add_api_route(
        _health_path,
        health,
        methods=["GET"],
        summary="Health check" if _health_path != "/" else "Root — service identity",
        tags=["health"],
        name=f"health_get_{_health_name}",
        include_in_schema=True,
    )
    router.add_api_route(
        _health_path,
        health,
        methods=["HEAD"],
        tags=["health"],
        name=f"health_head_{_health_name}",
        include_in_schema=False,
    )
del _health_path, _health_name  # avoid leaking loop variables into module scope


async def readiness():
    """Readiness probe — distinct from /health (liveness).

    Returns 503 (not 200) when a *required* dependency is unavailable, so an
    orchestrator (Render / k8s) can gate traffic to this instance:

      * DB configured + reachable   -> 200 {"ready": true,  "db": "connected"}
      * DB configured + unreachable -> 503 {"ready": false, "db": "unreachable"}
      * DB not configured (dev)     -> 200 {"ready": true,  "db": "disabled"}
        (persistence is optional by design — the API serves without it)

    Read-only.  Never mutates state.  Never touches the conviction engine.
    """
    from fastapi.responses import JSONResponse
    try:
        from .db.connection import _db_enabled as _dbe, _engine as _eng
    except Exception:
        return JSONResponse(status_code=200, content={"ready": True, "db": "disabled"})

    if not _dbe or _eng is None:
        return JSONResponse(status_code=200, content={"ready": True, "db": "disabled"})
    try:
        from sqlalchemy import text as _text
        async with _eng.connect() as _conn:
            await _conn.execute(_text("SELECT 1"))
        return JSONResponse(status_code=200, content={"ready": True, "db": "connected"})
    except Exception as _exc:
        logger.warning("[readyz] db not reachable: %r", _exc)
        return JSONResponse(status_code=503, content={"ready": False, "db": "unreachable"})


router.add_api_route(
    "/readyz",
    readiness,
    methods=["GET"],
    summary="Readiness probe (503 when a required dependency is down)",
    tags=["health"],
    name="readiness_get",
    include_in_schema=True,
)
router.add_api_route(
    "/readyz",
    readiness,
    methods=["HEAD"],
    tags=["health"],
    name="readiness_head",
    include_in_schema=False,
)


@router.get(
    "/version",
    summary="Runtime version — conviction schema + deployment identity",
    tags=["health"],
)
async def api_version() -> dict:
    """Public endpoint returning the live conviction schema version and build commit.

    Lighter-weight alternative to /debug/version — suitable for frontend polling
    and uptime monitors.  Does NOT run a full smoke test; just reads constants
    from the loaded module.

    Key fields:
      schema_version          — "6-matrix" when Phase 6 matrix code is active
      conviction_runtime      — human-readable build label
      durability_matrix_enabled — True when matrix architecture is active
      build_commit            — short git SHA from RENDER_GIT_COMMIT env var
      conviction_modeler_md5  — first 16 chars of MD5 of conviction_modeler.py on disk
    """
    import time as _t
    import os as _o
    from .startup import _PROCESS_START_EPOCH, _conviction_modeler_checksum

    try:
        from .services.conviction_modeler import (
            CONVICTION_SCHEMA_VERSION,
            ARCHETYPE_MATRIX_ENABLED,
        )
        schema_version  = CONVICTION_SCHEMA_VERSION
        matrix_enabled  = ARCHETYPE_MATRIX_ENABLED
    except Exception as exc:
        schema_version  = f"IMPORT_ERROR:{exc}"
        matrix_enabled  = False

    git_commit = (
        _o.environ.get("RENDER_GIT_COMMIT", "")[:12]
        or _o.environ.get("GIT_COMMIT", "")[:12]
        or "unknown"
    )
    return {
        "schema_version":           schema_version,
        "conviction_runtime":       f"phase-6-matrix/{schema_version}",
        "durability_matrix_enabled": matrix_enabled,
        "build_commit":             git_commit,
        "conviction_modeler_md5":   _conviction_modeler_checksum(),
        "process_start_utc":        _t.strftime(
                                        "%Y-%m-%dT%H:%M:%SZ",
                                        _t.gmtime(_PROCESS_START_EPOCH),
                                    ),
    }


@router.get(
    "/debug/version",
    summary="Live process version — matrix system proof",
    tags=["debug"],
)
async def debug_version() -> dict:
    """Return live process identity and conviction system version.

    This endpoint proves the deployed process loaded the Phase 6 matrix
    architecture.  Call GET /debug/version on the live Render URL and confirm:

      - conviction_schema_version == "6-matrix"
      - archetype_matrix_enabled  == true
      - matrix_smoke_label        == "actionable thesis"   (durable compounder test)

    If conviction_schema_version is absent or wrong, the live process is running
    stale pre-matrix code — trigger a Render manual restart.

    Also includes:
      - git_commit_hash   : short SHA of the running commit (RENDER_GIT_COMMIT env var
                            or the VERCEL_GIT_COMMIT_SHA — set this in Render settings)
      - process_start_utc : when this gunicorn worker spawned
      - deployment_id     : RENDER_SERVICE_ID env var if set

    Never exposes secret key values — only presence booleans.
    """
    import time as _time
    import os as _os

    # ── Conviction system fingerprint ─────────────────────────────────────────
    try:
        from .services.conviction_modeler import (
            CONVICTION_SCHEMA_VERSION,
            ARCHETYPE_MATRIX_ENABLED,
            _DURABILITY_MATRIX_HIGH,
            _DURABILITY_MATRIX_MID,
            _durability_matrix_label,
        )
        _exp_risk_smoke = round(0.70 * 0.42 + 0.30 * 0.28, 4)
        _smoke_label    = _durability_matrix_label(0.71, _exp_risk_smoke)
        _matrix_ok      = ARCHETYPE_MATRIX_ENABLED and _smoke_label not in (
            "speculative setup", "insufficient conviction"
        )
        matrix_info = {
            "conviction_schema_version": CONVICTION_SCHEMA_VERSION,
            "archetype_matrix_enabled":  ARCHETYPE_MATRIX_ENABLED,
            "durability_matrix_high":    _DURABILITY_MATRIX_HIGH,
            "durability_matrix_mid":     _DURABILITY_MATRIX_MID,
            "matrix_smoke_label":        _smoke_label,
            "matrix_ok":                 _matrix_ok,
        }
    except Exception as exc:
        matrix_info = {
            "conviction_schema_version": "IMPORT_ERROR",
            "archetype_matrix_enabled":  False,
            "matrix_ok":                 False,
            "import_error":              str(exc),
        }

    # ── Deployment identity ───────────────────────────────────────────────────
    from .startup import _PROCESS_START_EPOCH
    git_hash   = (
        _os.environ.get("RENDER_GIT_COMMIT", "")[:12]
        or _os.environ.get("GIT_COMMIT", "")[:12]
        or "unknown"
    )
    process_start_utc = _time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_PROCESS_START_EPOCH)
    )

    return {
        # ── Proof fields — check these on Render ──────────────────────────────
        "matrix": matrix_info,
        # ── Deployment identity ───────────────────────────────────────────────
        "deployment": {
            "git_commit_hash":    git_hash,
            "process_start_utc":  process_start_utc,
            "render_service_id":  _os.environ.get("RENDER_SERVICE_ID", "local"),
            "render_instance_id": _os.environ.get("RENDER_INSTANCE_ID", "local"),
            "python_version":     __import__("sys").version.split()[0],
        },
        # ── Key presence (never expose values) ───────────────────────────────
        "env": {
            "openai_key_present": bool(_os.environ.get("OPENAI_API_KEY", "")),
            "fred_key_present":   bool(_os.environ.get("FRED_API_KEY", "")),
            "backend_url_set":    bool(_os.environ.get("BACKEND_URL", "")),
        },
    }


@router.get(
    "/debug/matrix-test",
    summary="Live matrix smoke test — runs compute_conviction() production path",
    tags=["debug"],
)
async def debug_matrix_test() -> dict:
    """Run compute_conviction() through the actual production path for 5 archetypes.

    Tests:
      COST  — durable compounder:   must NOT be 'speculative setup'
      MSFT  — durable compounder:   must NOT be 'speculative setup'
      TSLA  — narrative/speculative: CAN be 'speculative setup'
      PLTR  — narrative/speculative: CAN be 'speculative setup'
      NVDA  — quality cyclical:      check expectation-sensitive range

    Returns the setup_label and confidence_score for each, plus a PASS/FAIL verdict.
    """
    import traceback as _tb
    from .services.conviction_modeler import (
        compute_conviction,
        CONVICTION_SCHEMA_VERSION,
        ARCHETYPE_MATRIX_ENABLED,
    )
    from .schemas import (
        CompanyContext,
        CompanyKnowledgeProfile,
        ValuationView,
        MacroSensitivity,
        RiskProfile,
        MarketContext,
        QualityAssessment,
    )

    _ARCHETYPES = [
        # (ticker, company_name, sector, archetype_expect)
        ("COST",  "Costco Wholesale",      "Consumer Staples",  "durable"),
        ("MSFT",  "Microsoft",             "Technology",        "durable"),
        ("NVDA",  "Nvidia",                "Technology",        "cyclical"),
        ("TSLA",  "Tesla",                 "Consumer Disc.",    "narrative"),
        ("PLTR",  "Palantir Technologies", "Technology",        "narrative"),
    ]

    results = []
    all_pass = True

    for ticker, name, sector, archetype_expect in _ARCHETYPES:
        try:
            # CompanyContext = minimal company identity (required by compute_conviction)
            company = CompanyContext(ticker=ticker, company_name=name, sector=sector)

            # CompanyKnowledgeProfile = optional structured facts (enriches durability score)
            profile = CompanyKnowledgeProfile(
                ticker=ticker,
                company_name=name,
                business_model=(
                    "membership-fee-driven retailer with recurring subscription economics"
                    if ticker == "COST" else
                    "enterprise software and cloud platform with subscription revenue"
                    if ticker == "MSFT" else
                    "semiconductor IP designer with cyclical data-center demand"
                    if ticker == "NVDA" else
                    "automotive EV manufacturer with narrative-driven valuation"
                    if ticker == "TSLA" else
                    "data-analytics software with government and enterprise contracts"
                ),
                recurring_revenue_sources=(
                    ["membership fees", "renewal subscriptions"] if archetype_expect == "durable" else []
                ),
            )
            val  = ValuationView()
            mac  = MacroSensitivity()
            risk = RiskProfile()
            mkt  = MarketContext()
            qual = QualityAssessment()

            result = compute_conviction(
                evidence=[],
                valuation=val,
                macro=mac,
                risk=risk,
                market=mkt,
                quality=qual,
                company=company,
                ranked=None,
                governance_warnings=[],
                profile=profile,
            )

            label = result.setup_label
            score = result.final_score

            # Validation rule: durable compounders must NEVER get speculative labels
            _FORBIDDEN_FOR_DURABLE = {"speculative setup", "insufficient conviction"}
            if archetype_expect == "durable" and label in _FORBIDDEN_FOR_DURABLE:
                verdict = "FAIL — durable compounder got speculative label"
                all_pass = False
            else:
                verdict = "PASS"

            results.append({
                "ticker":             ticker,
                "archetype_expected": archetype_expect,
                "setup_label":        label,
                "confidence_score":   round(score, 4),
                "confidence_pct":     round(score * 100),
                "verdict":            verdict,
            })

        except Exception as exc:
            all_pass = False
            results.append({
                "ticker":  ticker,
                "verdict": f"ERROR — {type(exc).__name__}: {exc}",
                "traceback": _tb.format_exc()[-500:],
            })

    return {
        "overall": "PASS" if all_pass else "FAIL",
        "matrix_version": CONVICTION_SCHEMA_VERSION,
        "matrix_enabled": ARCHETYPE_MATRIX_ENABLED,
        "results": results,
    }


@router.get(
    "/admin/evidence-status",
    summary="Phase 9F — Historical Evidence Engine production status",
    tags=["admin"],
)
async def admin_evidence_status() -> dict:
    """Return seeding status, row counts, and acceptance-test retrieval result.

    Used for production validation after Phase 9F deploy.
    Idempotent read — safe to call at any time.
    """
    from .db import get_session as _gs_ev
    from .db.repositories.evidence_repo import get_all_analogs as _ga_ev, seed_analogs as _seed_ev
    from .evidence_engine import build_fingerprint as _bfp, retrieve_historical_analogs as _ret

    analog_count = 0
    table_exists = False
    seed_result = None
    acceptance_top = None
    acceptance_pass = False
    all_labels: list = []
    error = None

    try:
        async with _gs_ev() as _sess:
            if _sess is None:
                return {"status": "disabled", "reason": "DATABASE_URL not set"}

            # Attempt seed (idempotent — inserts only missing rows)
            inserted = await _seed_ev(_sess)
            seed_result = {"inserted_this_call": inserted}

            rows = await _ga_ev(_sess)
            analog_count = len(rows)
            table_exists = True
            all_labels = [r.label for r in rows]

            # Acceptance test: Cisco 2000 must rank before NVDA 2018
            _thesis = {
                "concern_tags": ["capex_cycle", "valuation_risk"],
                "bull_thesis": "AI infrastructure spending drives GPU demand at peak multiples.",
                "bear_thesis": "Hyperscaler capex cycle risk is the primary bear case.",
                "conclusion": "Bullish. Priced at peak multiple.",
                "confidence_score": 0.78,
                "company_name": "NVIDIA",
            }
            _fp = _bfp("What would break the Nvidia bull case?", _thesis, ticker="NVDA")
            _results = _ret(rows, _fp)

            if _results:
                acceptance_top = {
                    "label":            _results[0]["label"],
                    "mechanism":        _results[0]["mechanism"],
                    "relevance_score":  _results[0]["relevance_score"],
                    "drawdown_pct":     _results[0]["drawdown_pct"],
                }
                acceptance_pass = "Cisco" in _results[0]["label"]
            else:
                acceptance_top = None
                acceptance_pass = False

    except Exception as exc:
        import traceback as _tb
        error = f"{type(exc).__name__}: {exc}"

    return {
        "status":           "ok" if not error else "error",
        "error":            error,
        "table_exists":     table_exists,
        "analog_count":     analog_count,
        "expected_count":   22,
        "seed_result":      seed_result,
        "acceptance_test":  {
            "query":        "What would break the Nvidia bull case?",
            "pass":         acceptance_pass,
            "top_analog":   acceptance_top,
            "requirement":  "Cisco 2000 (infrastructure_overbuild) must rank first",
        },
        "all_labels":       all_labels,
    }


@router.get(
    "/admin/dossier-status",
    summary="Phase 9G — Company Dossier extraction status",
    tags=["admin"],
)
async def admin_dossier_status() -> dict:
    """Return dossier feature-flag state and row counts.

    Safe to call at any time — read-only queries.

    Key fields:
      dossier_extraction_enabled — True when the extraction flag is active.
      head_count                 — rows in company_dossier (one per ticker).
      debate_count               — rows in dossier_core_debate.
      dimension_count            — rows in dossier_moat_dimension.
      catalyst_count             — rows in dossier_catalyst.
      variant_count              — rows in dossier_variant.
      durability_count           — rows in dossier_durability.
      failure_mode_count         — rows in dossier_failure_mode.
      revision_count             — rows in dossier_revision.
      evidence_ref_count         — rows in dossier_evidence_ref.
    """
    from .config import settings as _9g_s
    from .db.connection import get_session as _gs_d

    enabled   = bool(_9g_s.dossier_extraction_enabled)
    counts    = {}
    error     = None
    db_active = False

    _TABLE_NAMES = [
        ("head_count",          "company_dossier"),
        ("debate_count",        "dossier_core_debate"),
        ("dimension_count",     "dossier_moat_dimension"),
        ("catalyst_count",      "dossier_catalyst"),
        ("variant_count",       "dossier_variant"),
        ("durability_count",    "dossier_durability"),
        ("failure_mode_count",  "dossier_failure_mode"),
        ("revision_count",      "dossier_revision"),
        ("evidence_ref_count",  "dossier_evidence_ref"),
    ]

    try:
        from sqlalchemy import text as _text
        async with _gs_d() as _sess:
            if _sess is None:
                return {
                    "status":  "disabled",
                    "reason":  "DATABASE_URL not set",
                    "dossier_extraction_enabled": enabled,
                }
            db_active = True
            for key, table in _TABLE_NAMES:
                try:
                    _r = await _sess.execute(_text(f"SELECT COUNT(*) FROM {table}"))
                    counts[key] = int((_r.fetchone() or (0,))[0])
                except Exception:
                    counts[key] = None   # table may not yet exist (pre-migration env)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    return {
        "status":                    "ok" if not error else "error",
        "error":                     error,
        "db_active":                 db_active,
        "dossier_extraction_enabled": enabled,
        **counts,
    }


@router.get(
    "/admin/dossier-injection-status",
    summary="Phase 9G · Slice 5C — Dossier injection status (shadow + canary)",
    tags=["admin"],
)
async def admin_dossier_injection_status() -> dict:
    """Return injection flag state, shadow telemetry, and canary cohort metrics.

    Read-only.  Combines:
      * Slice 5A shadow telemetry (block build stats, token sizes)
      * Slice 5C canary telemetry (cohort counts, conviction/echo/override metrics)
      * Kill-switch runtime override state
      * Persisted audit_log counts (survive process restarts)
    """
    from .config import settings as _inj_s
    from .services import dossier_injection_telemetry as _inj_tel
    from .services import dossier_canary_telemetry as _can_tel
    from .services import dossier_canary_metrics as _can_met
    from .services.canary_audit import build_persisted_snapshot as _build_pers
    from .db import get_session as _gs_adm

    shadow_snap  = _inj_tel.snapshot()
    canary_snap  = _can_tel.snapshot()
    outcomes     = _can_tel.snapshot_outcomes()
    metrics      = _can_met.compute_all(outcomes)
    eff_enabled  = _can_tel.get_enabled(bool(_inj_s.dossier_injection_enabled))

    persisted: dict = {}
    try:
        async with _gs_adm() as _adm_s:
            persisted = await _build_pers(_adm_s)
    except Exception as _adm_exc:
        import logging as _adm_log
        _adm_log.getLogger(__name__).debug(
            "[ask] dossier status persisted snapshot failed (non-fatal): %r", _adm_exc
        )
        from .services.canary_audit import _empty_snapshot as _es
        persisted = _es()

    return {
        "status":               "ok",
        "shadow":               bool(_inj_s.dossier_injection_shadow),
        "config_enabled":       bool(_inj_s.dossier_injection_enabled),
        "effective_enabled":    eff_enabled,
        "canary_pct":           int(_inj_s.dossier_injection_canary_pct),
        "include_prior_state":  bool(_inj_s.dossier_injection_include_prior_state),
        "token_cap":            350,
        "shadow_telemetry":     shadow_snap,
        "canary":               canary_snap,
        "metrics":              metrics,
        "persisted": {
            **persisted,
            "telemetry_source": "memory + audit_log",
        },
    }


@router.post(
    "/admin/dossier-injection/disable",
    summary="Phase 9G · Slice 5C — Tier-0 kill switch: disable injection immediately",
    tags=["admin"],
)
async def admin_dossier_injection_disable() -> dict:
    """Disable dossier injection in-process without a redeploy.

    Sets a runtime override that takes effect immediately for all subsequent
    requests.  The override survives until /enable is called or the process
    restarts (at which point the config setting governs again).
    """
    from .services import dossier_canary_telemetry as _can_tel
    _can_tel.force_disable()
    return {"status": "ok", "effective_enabled": False, "override": "force_disabled"}


@router.post(
    "/admin/dossier-injection/enable",
    summary="Phase 9G · Slice 5C — Re-enable injection (clears force-disable override)",
    tags=["admin"],
)
async def admin_dossier_injection_enable() -> dict:
    """Re-enable dossier injection by setting a force-enable runtime override.

    This clears a prior force_disable.  Injection only flows to sessions that
    fall in the canary bucket (canary_pct > 0) AND pass the cohort gate.
    """
    from .config import settings as _inj_s
    from .services import dossier_canary_telemetry as _can_tel
    _can_tel.force_enable()
    return {
        "status":         "ok",
        "effective_enabled": True,
        "override":       "cleared",
        "canary_pct":     int(_inj_s.dossier_injection_canary_pct),
    }


# ── Phase 10A · Slice 9 — Loop canary + kill-switch admin endpoints ───────────

@router.get(
    "/admin/loop-status",
    summary="Phase 10A · Slice 10 — Loop observability snapshot",
    tags=["admin"],
)
async def admin_loop_status() -> dict:
    """Return a complete, null-safe loop observability snapshot.

    Delegates to loop_observability.build_snapshot(), which covers:
    config flags, kill-switch state, canary cohort metrics, in-process
    telemetry counters, job/run/delivery DB counts, lock state, and
    all guardrail settings.

    Read-only.  Safe to call at any time regardless of loop_enabled.
    DB-down-safe: DB sections degrade to zeros rather than 500.
    """
    from .services.loop_observability import build_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_snapshot(_sess)
    except Exception:
        # DB session itself unavailable — return in-process snapshot
        return await build_snapshot(None)


@router.post(
    "/admin/loop/disable",
    summary="Phase 10A · Slice 9 — Kill switch: disable loop immediately",
    tags=["admin"],
)
async def admin_loop_disable() -> dict:
    """Disable the loop in-process without a redeploy.

    Sets a runtime override that takes effect immediately for all subsequent
    tick() calls.  The override survives until /admin/loop/enable is called
    or the process restarts (config governance resumes).
    """
    from .services import loop_canary_telemetry as _tel
    _tel.force_disable()
    return {
        "status":            "ok",
        "effective_enabled": False,
        "override":          "force_disabled",
    }


@router.post(
    "/admin/loop/enable",
    summary="Phase 10A · Slice 9 — Clear kill-switch override (restore config governance)",
    tags=["admin"],
)
async def admin_loop_enable() -> dict:
    """Re-enable the loop by clearing the force-disable override.

    Clears the kill-switch; config (loop_enabled) governs again.
    Does NOT force-enable when loop_enabled=False in config.
    """
    from .config import settings as _s
    from .services import loop_canary_telemetry as _tel
    _tel.force_enable()
    eff = _tel.get_enabled(bool(_s.loop_enabled))
    return {
        "status":             "ok",
        "effective_enabled":  eff,
        "override":           "cleared",
        "config_loop_enabled": bool(_s.loop_enabled),
        "canary_pct":         int(_s.loop_canary_pct),
    }


@router.get(
    "/admin/delivery-status",
    summary="Phase 10C · Slice 10 — Delivery observability snapshot",
    tags=["admin"],
)
async def admin_delivery_status() -> dict:
    """Return a complete, null-safe Phase 10C delivery observability snapshot.

    Delegates to delivery_observability_service.build_delivery_snapshot(), which covers:
    delivery feature flags, ledger counts by status and severity, notification counts,
    digest counts, user preference coverage, recent delivery decisions, guardrail
    settings, and duplicate count.

    Read-only.  Safe to call at any time regardless of delivery flags.
    DB-down-safe: DB sections degrade to zeros rather than 500.

    Key validation fields:
      safe_state             — True when delivery_in_app_enabled=False OR delivery_shadow=True
      delivery_flags         — all 4 Phase 10C flags
      ledger.shadow_count    — rows marked delivered_shadow (validates shadow flow)
      notifications.delivery_notifications — real Notification rows (0 in safe state)
      duplicate_count        — in-process dedup counter (should be 0 in clean runs)
    """
    from .services.delivery_observability_service import build_delivery_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_delivery_snapshot(_sess)
    except Exception:
        return await build_delivery_snapshot(None)


@router.get(
    "/admin/portfolio-status",
    summary="Phase 10D · Slice 8 — Portfolio intelligence observability snapshot",
    tags=["admin"],
)
async def admin_portfolio_status() -> dict:
    """Return a complete, null-safe Phase 10D portfolio observability snapshot.

    Delegates to portfolio_observability_service.build_portfolio_snapshot(), which covers:
    portfolio feature flags, portfolio/position/insight counts, insight breakdown by type,
    severity, and rank_band, delivery_ledger portfolio_alert counts, notification counts,
    digest counts, regulatory guard metadata, and safe_state flag.

    Read-only.  Safe to call at any time regardless of portfolio flags.
    DB-down-safe: DB sections degrade to zeros rather than 500.

    Key validation fields:
      safe_state                        — True when delivery disabled OR shadow=True
      portfolio_flags                   — all 4 Phase 10D flags
      insights.total                    — number of generated insights
      insights.by_severity              — distribution across severity ladder
      insights.stale_count              — insights backed by stale cross-exposure
      notifications.portfolio_alert_count — live Notification rows (0 in safe state)
      regulatory.disclaimer_present     — True always (regulatory guard active)
    """
    from .services.portfolio_observability_service import build_portfolio_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_portfolio_snapshot(_sess)
    except Exception:
        return await build_portfolio_snapshot(None)


@router.get(
    "/admin/billing-status",
    summary="Phase 17 · Slice 7 — Billing observability snapshot",
    tags=["admin"],
)
async def admin_billing_status() -> dict:
    """Return a complete, null-safe Phase 17 billing observability snapshot.

    Delegates to billing_observability_service.build_billing_snapshot(), which covers:
    billing feature flags, subscription counts by status, stripe event counts,
    entitlement cache population, registered billing routes, and safe_state.

    Read-only.  Safe to call at any time regardless of Stripe flags.
    DB-down-safe: DB sections degrade to zeros rather than 500.

    Key validation fields:
      billing_live_ready        — True only when the paid-production gate passes
      stripe_config_ready       — True when every required Stripe value is set
      billing_routes_present    — True when all 5 billing routes are registered
      unresolved_webhook_errors — must be 0 before paid beta access
      pending_webhooks          — must be 0 after the processing window
      safe_state                — True only in the disabled shadow configuration
    """
    from .services.billing_observability_service import build_billing_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_billing_snapshot(_sess)
    except Exception:
        return await build_billing_snapshot(None)


@router.get(
    "/admin/similarity-status",
    summary="Phase 11 · Slice 8 — Similarity engine observability snapshot",
    tags=["admin"],
)
async def admin_similarity_status() -> dict:
    """Return a read-only Phase 11 similarity observability snapshot.

    Delegates to similarity_observability_service.build_similarity_observability_snapshot(),
    which covers: similarity feature flags, db_available, per-target feature-vector
    counts, edge counts (total/floor_passed/expired) and by target_type, the
    shadow delivery ledger count (channel="similarity_shadow") and how many of
    those rows ever escalated to "delivered", any live Notification rows
    mistakenly tagged kind="similarity", the latest vector/edge build
    timestamps, and safe_state.

    Read-only. Safe to call at any time regardless of similarity flags.
    Never builds, scores, or rebuilds anything. DB-down-safe: degrades to
    zeros rather than 500.

    Key validation fields:
      safe_state              — True when similarity_shadow=True AND shadow_escalated_count=0
                                 AND live_notification_count=0
      flags                   — all 4 Phase 11 similarity flags
      vector_counts           — failure_mode/company/thesis feature-vector row counts
      edge_counts.floor_passed — edges that cleared the relevance floor
      shadow_delivery_count   — similarity transition events journaled in shadow
      shadow_escalated_count  — must stay 0; any nonzero value means a similarity
                                 event reached "delivered" status, which should
                                 never happen until a future live-delivery slice
    """
    from .services.similarity_observability_service import build_similarity_observability_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_similarity_observability_snapshot(_sess)
    except Exception:
        return await build_similarity_observability_snapshot(None)


@router.get(
    "/admin/similarity/{ticker}",
    summary="Phase 11 · Slice 6 — Resembles facet for a ticker (internal)",
    tags=["admin"],
)
async def admin_similarity_for_ticker(ticker: str) -> dict:
    """Return the read-only "Resembles" facet payload for *ticker*.

    Internal/admin inspection only — not wired into any public route, the
    dossier UI, or delivery. Never builds or rebuilds anything; if no
    similarity data has been built/scored for this ticker yet, returns the
    safe empty state (has_similarity=False, matches=[]).
    """
    from .services.similarity_read_service import get_resembles_facet_for_ticker
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await get_resembles_facet_for_ticker(_sess, ticker.upper())
    except Exception:
        return await get_resembles_facet_for_ticker(None, ticker.upper())


@router.get(
    "/admin/forecast-status",
    summary="Phase 12 · Slice 9 — Forecast engine observability snapshot",
    tags=["admin"],
)
async def admin_forecast_status() -> dict:
    """Return a read-only Phase 12 forecast engine observability snapshot.

    Delegates to forecast_observability_service.build_forecast_observability_snapshot.

    Reports:
      - All 6 forecast_* config flags
      - Vector counts (total, by type, by horizon, expired)
      - Evidence count
      - Calibration log count
      - Shadow delivery count (channel="forecast_shadow")
      - Live notification count (kind="forecast", always 0 in Phase 12)
      - Latest forecast and calibration timestamps
      - safe_state: True when shadow-only, no escalated rows, no live notifications

    Read-only. Never builds, scores, or rebuilds anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.
    """
    from .services.forecast_observability_service import build_forecast_observability_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as sess:
            return await build_forecast_observability_snapshot(sess)
    except Exception:
        return await build_forecast_observability_snapshot(None)


@router.get(
    "/admin/forecast/{ticker}",
    summary="Phase 12 · Slice 6 — Forecast facet for a ticker (internal)",
    tags=["admin"],
)
async def admin_forecast_for_ticker(ticker: str) -> dict:
    """Return the read-only forecast facet payload for *ticker*.

    Internal/admin inspection only — not wired into any public route, the
    dossier UI, or delivery.  Never builds or rebuilds anything; if no
    forecast data has been built for this ticker yet, returns the safe empty
    state (has_forecasts=False, forecasts=[]).

    All forecasts returned are:
      - non-expired
      - have non-empty why and invalidators
      - include the mandatory disclaimer verbatim

    Descriptive only.  No conviction, stance, buy/sell/hold, or price target
    fields are present anywhere in the response.
    """
    from .services.forecast_read_service import get_forecast_facet_for_ticker
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await get_forecast_facet_for_ticker(_sess, ticker.upper())
    except Exception:
        return await get_forecast_facet_for_ticker(None, ticker.upper())


@router.get(
    "/admin/decision-status",
    summary="Phase 13 · Slice 10 — Decision Intelligence full observability snapshot",
    tags=["admin"],
)
async def admin_decision_status() -> dict:
    """Return a read-only Phase 13 Decision Intelligence observability snapshot.

    Delegates to decision_observability_service.build_decision_observability_snapshot().

    Reports:
      - All 6 decision_* config flags
      - Row counts: priority, evidence, ranking_log, calibration_outcome, expired
      - Priority counts by bucket (critical/high/medium/low/informational)
      - Priority counts by candidate_type
      - Shadow delivery count and escalation count (must be 0)
      - Live notification count (must be 0)
      - Latest priority_at and calibration_at timestamps
      - safe_state: True when decision_shadow=True, delivery_enabled=False,
        shadow_escalated_count=0, live_notification_count=0

    Read-only.  Never builds, scores, ranks, or writes anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.

    No buy/sell/hold, target price, or investment recommendation language
    is present anywhere in the response.
    """
    from .services.decision_observability_service import build_decision_observability_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as sess:
            return await build_decision_observability_snapshot(sess)
    except Exception:
        return await build_decision_observability_snapshot(None)


@router.get(
    "/admin/decision/{ticker}",
    summary="Phase 13 · Slice 6 — Decision facet for a ticker (internal)",
    tags=["admin"],
)
async def admin_decision_for_ticker(ticker: str) -> dict:
    """Return the read-only decision facet payload for *ticker*.

    Internal/admin inspection only — not wired into any public route or
    delivery path. Never builds or rebuilds anything; if no decision data
    has been stored for this ticker yet, returns the safe empty state.

    Returns the top-3 valid (non-expired, explanation-present, scored)
    decision priorities for the ticker, plus a facet-level summary
    (top_bucket, top_score, type_counts).

    Descriptive only. No conviction, stance, buy/sell/hold, or price
    target fields are present anywhere in the response.
    """
    from .services.decision_read_service import get_decision_facet_for_ticker
    from .db.connection import get_session

    try:
        async with get_session() as sess:
            return await get_decision_facet_for_ticker(sess, ticker.upper())
    except Exception:
        return await get_decision_facet_for_ticker(None, ticker.upper())


@router.get(
    "/admin/scenario-status",
    summary="Phase 14 · Slice 10 — Scenario engine observability snapshot",
    tags=["admin"],
)
async def admin_scenario_status() -> dict:
    """Return a read-only Phase 14 scenario engine observability snapshot.

    Delegates to scenario_observability_service.build_scenario_observability_snapshot().

    Reports:
      - All 6 scenario_* config flags
      - Row counts: scenario_snapshot, scenario_evidence, scenario_run_log
      - Breakdown by scenario type and impact band
      - Shadow delivery ledger count (channel=scenario_shadow)
      - Live notification count (must be 0 in shadow mode)
      - Latest scenario and calibration timestamps
      - Structured safe_state with six sub-checks
      - db_available, schema_version, disclaimer

    Read-only.  Never builds, propagates, explains, or writes anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.

    No buy/sell/hold, target price, or investment recommendation language
    is present anywhere in the response.
    """
    from .services.scenario_observability_service import build_scenario_observability_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as sess:
            return await build_scenario_observability_snapshot(sess)
    except Exception:
        return await build_scenario_observability_snapshot(None)


@router.get(
    "/admin/scenario/{ticker}",
    summary="Phase 14 · Slice 6 — Scenario facet for a ticker (internal)",
    tags=["admin"],
)
async def admin_scenario_for_ticker(ticker: str) -> dict:
    """Return the read-only scenario facet payload for *ticker*.

    Internal/admin inspection only — not wired into any public route or
    delivery path.  Never builds or rebuilds anything; if no scenario data
    has been stored for this ticker yet, returns the safe empty state.

    Returns the top-3 valid (non-expired, explanation-present,
    transmission-path-present) scenario snapshots for the ticker, plus a
    facet-level summary (top_plausibility, top_confidence, type_counts).

    Descriptive only.  No conviction, stance, buy/sell/hold, or price
    target fields are present anywhere in the response.
    """
    from .services.scenario_read_service import get_scenario_facet_for_ticker
    from .db.connection import get_session

    try:
        async with get_session() as sess:
            return await get_scenario_facet_for_ticker(sess, ticker.upper())
    except Exception:
        return await get_scenario_facet_for_ticker(None, ticker.upper())


@router.post(
    "/admin/loop/seed-jobs",
    summary="Phase 10B · Slice 10 — Seed watchlist_scan jobs for active tickers",
    tags=["admin"],
)
async def admin_loop_seed_jobs() -> dict:
    """Seed one watchlist_scan ScheduledJob per active watched ticker.

    Idempotent — safe to call multiple times.  Uses the UNIQUE constraint
    on (job_type, target_key, period_bucket) to skip tickers that already
    have a job for today's bucket.

    Returns a SeedResult summary:
      tickers_seen:  number of active tickers found
      jobs_created:  new rows inserted
      jobs_existing: rows already existed (idempotent skip)
      errors:        per-ticker failure count
      period_bucket: YYYY-MM-DD bucket used
      tickers_seeded: list of ticker symbols that got new jobs
    """
    from .services.watchlist_job_seeder import seed_watchlist_jobs
    from .db.connection import get_session
    from dataclasses import asdict

    try:
        async with get_session() as sess:
            result = await seed_watchlist_jobs(sess)
        return {"status": "ok", **asdict(result)}
    except Exception as exc:
        logger.warning("admin_loop_seed_jobs failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@router.get(
    "/admin/user-learning-status",
    summary="Phase 15 · Slice 11 — User Learning observability snapshot",
    tags=["admin"],
)
async def admin_user_learning_status() -> dict:
    """Return a read-only Phase 15 user learning observability snapshot.

    Delegates to user_learning_observability_service.build_user_learning_snapshot().

    Reports:
      - All 6 learning_* config flags
      - Row counts: user_signal_event, learned_preference, preference_evidence,
        relevance_adjustment_log (total / shadow / calibration sub-counts)
      - Preference breakdowns by dimension and strength label
      - Latest signal, preference, and adjustment timestamps
      - Structured safe_state with five sub-checks
      - db_available, schema_version, disclaimer

    Read-only.  Never captures signals, infers preferences, or writes anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.

    No buy/sell/hold, target price, or investment guidance language is present
    anywhere in the response.
    """
    from .services.user_learning_observability_service import build_user_learning_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_user_learning_snapshot(_sess)
    except Exception:
        return await build_user_learning_snapshot(None)


@router.get(
    "/admin/personal-experience-status",
    summary="Phase 18 · Slice 10 — Personal Experience observability snapshot",
    tags=["admin"],
)
async def admin_personal_experience_status() -> dict:
    """Return a read-only Phase 18 Personal Experience observability snapshot.

    Reports:
      - All 6 experience_* config flags
      - Row counts: personal_experience_cursor, personal_experience_event,
        personal_brief_snapshot (total / shadow / calibration sub-counts)
      - Structured safe_state with six sub-checks
      - db_available, schema_version, disclaimer

    Read-only.  Never composes, scores, or writes anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.
    """
    from .services.personal_experience_observability_service import (
        build_personal_experience_snapshot,
    )
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_personal_experience_snapshot(_sess)
    except Exception:
        return await build_personal_experience_snapshot(None)


@router.get(
    "/admin/visual-intelligence-status",
    summary="Phase 19 · Slice 12 — Visual Intelligence observability snapshot",
    tags=["admin"],
)
async def admin_visual_intelligence_status() -> dict:
    """Return a read-only Phase 19 Visual Intelligence observability snapshot.

    Reports:
      - All 6 visual_* config flags
      - Row counts: visual_spec_cache, visual_experience_event,
        ai_visual_generation_log (total / shadow / calibration sub-counts)
      - Structured safe_state with six sub-checks
      - db_available, schema_version, disclaimer

    Read-only.  Never renders, generates, or writes anything.
    DB-down-safe: degrades gracefully to zeros rather than 500.
    """
    from .services.visual_observability_service import build_visual_snapshot
    from .db.connection import get_session

    try:
        async with get_session() as _sess:
            return await build_visual_snapshot(_sess)
    except Exception:
        return await build_visual_snapshot(None)


@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    summary="Analyze a company",
    tags=["analysis"],
)
async def analyze(request: AnalysisRequest, http_request: Request) -> AnalysisResponse:
    """Perform an AI analysis of the requested company.

    Enterprise lifecycle:
        - Scope is extracted from HTTP headers and passed into analyze_company
        - The full analysis flow (evidence, agents, synthesis, monitoring, alerts)
          runs under enterprise governance with the resolved scope.
    """
    try:
        scope = _extract_scope(http_request)
        return analyze_company(request, scope=scope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Analysis failed to complete") from exc


@router.post(
    "/ask",
    summary="Ask a question to a specialist agent",
    tags=["questions"],
)
async def ask_question(request: QuestionRequest, http_request: Request):
    """Route a user question to the appropriate agent and return its answer.

    Uses StreamingResponse with periodic keepalive newlines to prevent
    Render Nginx proxy_read_timeout (hard-coded 60 s, not user-configurable
    at any tier) from dropping the connection on long synthesis calls.

    Protocol:
      - While route_question() is running, emit b"\\r\\n" every 25 s.
        Each byte resets Nginx's proxy_read_timeout clock.
      - When synthesis completes, emit the full JSON body and close.
      - The response is application/json with optional leading whitespace,
        which is valid per RFC 8259.  browser fetch().json() and all
        compliant JSON parsers accept leading whitespace.

    Phase 9A persistence:
      After the JSON body is yielded, a fire-and-forget asyncio task
      writes the analysis result to the persistence layer.  This never
      blocks the response and degrades gracefully when DATABASE_URL is unset.

    Pipeline budget (unchanged):
      evidence(≤10 s) + agents(≤16 s) + synthesis(≤55 s httpx / ≤56 s wall)
      = ≤82 s total.  Keepalive at t≈25 s resets Nginx; response arrives
      well before the second Nginx window expires at t≈85 s.
    """
    import asyncio as _asyncio
    import json as _json
    import time as _time
    from fastapi.responses import StreamingResponse

    # ── Sprint 0 pre-flight gate ──────────────────────────────────────────────
    # Runs BEFORE any LLM work / streaming so it can return a clean status code
    # (401/403/413/429).  Enforces auth (when AUTH_ENABLED), question-length cap,
    # entitlements (when enforced), per-IP + per-user rate limits, and the per-
    # user daily quota.  Fails closed on misconfiguration.  Never logs the prompt.
    from .security.ask_guard import enforce_ask_preflight as _enforce_ask_preflight
    await _enforce_ask_preflight(http_request, getattr(request, "question", "") or "")

    _KEEPALIVE_INTERVAL_S: float = 25.0  # < 60 s Nginx limit; resets the clock

    # ── Sprint 3C.1A: progressive protocol negotiation ────────────────────────
    # Opt-in ONLY. Both current consumers require exactly one JSON document —
    # the validation runner calls resp.json(), the frontend slices from the
    # first "{" to the end — so emitting NDJSON by default would break them.
    # A caller sending */* (browser and requests default) is not a match and
    # receives the legacy bytes unchanged.
    from .progress import (
        LEGACY_MEDIA_TYPE as _LEGACY_MEDIA,
        PROGRESS_MEDIA_TYPE as _PROGRESS_MEDIA,
        ProgressProjector as _ProgressProjector,
        encode_frame as _encode_frame,
        error_frame as _error_frame,
        final_frame as _final_frame,
        progressive_requested as _progressive_requested,
    )
    _progressive: bool = _progressive_requested(http_request.headers.get("accept"))
    # Poll cadence while the pipeline runs in the executor. 100 ms keeps the
    # first real transition (routing completes at ~18 ms, retrieval at ~101 ms)
    # well inside the 250 ms target while costing ~210 brief lock acquisitions
    # across a median request.
    _PROGRESS_POLL_S: float = 0.1
    # Longest silent gap on the wire before a keepalive is needed. Synthesis is
    # the only genuinely quiet stretch (~11.8 s median, ~16.7 s p95), so 15 s
    # keeps every request under Nginx's 60 s window without emitting heartbeats
    # that duplicate real progress frames.
    _PROGRESS_HEARTBEAT_S: float = 15.0

    # Extract session ID for persistence correlation — prefer X-Session-ID,
    # fall back to X-Request-ID injected by the timing middleware.
    _session_id: str = (
        http_request.headers.get("X-Session-ID", "")
        or http_request.headers.get("X-Request-ID", "")
        or getattr(getattr(http_request, "state", None), "request_id", "")
        or ""
    )

    # ── Sprint 3A: request-scoped observability ──────────────────────────────
    # Reuse the request_id the timing middleware already generated (or an
    # inbound X-Request-ID) so logs, response headers and the _observability
    # block all correlate to one identifier. Only mint a new one if neither
    # exists, so a single request never has two ids.
    from .observability import (
        start_trace as _start_trace, bind as _obs_bind, stage as _obs_stage,
    )
    _obs_request_id: str = (
        http_request.headers.get("X-Request-ID", "")
        or getattr(getattr(http_request, "state", None), "request_id", "")
        or ""
    )
    _trace = _start_trace(
        _obs_request_id or None,
        ticker=str(getattr(request, "company_name", "") or ""),
        route="/ask",
    )

    # ── Sprint 3B.1: synthesis-prompt A/B variant ────────────────────────────
    # Selecting an experimental prompt requires the SAME authorization as
    # profiling detail, so an ordinary user always gets the production prompt.
    # Resolved once here and carried on a contextvar into the executor.
    try:
        from .observability import (
            DETAIL_TOKEN_HEADER as _TOK_HDR,
            PROMPT_VARIANT_HEADER as _VARIANT_HDR,
            profiling_authorized as _prof_auth,
            set_prompt_variant as _set_variant,
        )
        from .observability import (
            MODEL_VARIANT_HEADER as _MODEL_HDR,
            set_model_variant as _set_model_variant,
        )
        from .observability import (
            RISK_VARIANT_HEADER as _RISK_HDR,
            set_risk_variant as _set_risk_variant,
        )
        from .services.synthesis_prompt_variants import resolve_variant as _resolve_variant
        from .services.synthesis_model_variants import (
            resolve_model_variant as _resolve_model_variant,
        )
        from .investment_agents.risk_variants import (
            resolve_risk_variant as _resolve_risk_variant,
        )
        _is_authorized = _prof_auth("1", http_request.headers.get(_TOK_HDR))
        _set_variant(_resolve_variant(
            http_request.headers.get(_VARIANT_HDR), authorized=_is_authorized,
        ))
        # Sprint 3B.2 — model variant is resolved independently of the prompt
        # variant, so a model experiment can never change the prompt.
        _set_model_variant(_resolve_model_variant(
            http_request.headers.get(_MODEL_HDR), authorized=_is_authorized,
        ))
        # Sprint 3B.3 — risk variant is likewise independent: it changes the
        # risk agent's output shape only, never the synthesis prompt or model.
        _set_risk_variant(_resolve_risk_variant(
            http_request.headers.get(_RISK_HDR), authorized=_is_authorized,
        ))
    except Exception as _var_exc:
        logger.debug("[ask] prompt-variant resolution failed (non-fatal): %r", _var_exc)

    async def _generate():
        loop = _asyncio.get_running_loop()          # always the active loop

        # ── Phase 9C: Investment Memory (pre-dispatch read) ───────────────────
        # Read prior-analysis history BEFORE dispatching to the thread executor
        # so the memory block can be injected into the synthesis LLM prompt.
        # Must happen here (async context) — the thread cannot await DB calls.
        #
        # Root-cause fix: the frontend sends company_name="" for natural-language
        # queries like "Has the Nvidia thesis improved...". normalize_ticker("")
        # returns "UNKNOWN", which has no DB row.  We therefore try two sources:
        #   1. company_name field (fast path for explicit ticker/company entry)
        #   2. detect_company(question) — same entity detection the router uses
        _request = request  # default: no memory enrichment
        _pre_dispatch_ticker: str | None = None
        try:
            from .db import get_session as _get_session
            from .db.repositories.memory_retrieval import get_memory_context as _get_mem
            from .db.ticker_normalizer import normalize_ticker as _norm_ticker
            from .memory_context import (
                format_memory_for_prompt as _fmt_mem,
                memory_context_for_response as _mem_for_resp,
            )

            # Resolve ticker: explicit company_name → question text fallback
            _raw_company = (request.company_name or "").strip()
            if _raw_company:
                _pre_dispatch_ticker = _norm_ticker(_raw_company)
            else:
                # Explicit general-answer intents must not inherit investment
                # memory from a fuzzy company match in ordinary prose.
                from .services.company_detection import (
                    detect_company as _detect_co,
                    intent_allows_company_detection as _allows_company_detection,
                )
                if _allows_company_detection(getattr(request, "intent", None)):
                    try:
                        _co = _detect_co(request.question)
                        _pre_dispatch_ticker = _co.ticker if _co else None
                    except Exception:
                        _pre_dispatch_ticker = None
                else:
                    _pre_dispatch_ticker = None

            if _pre_dispatch_ticker:
                async with _get_session() as _mem_session:
                    _mem_ctx = await _get_mem(_mem_session, _pre_dispatch_ticker)

                if _mem_ctx:
                    _mem_block = _fmt_mem(_mem_ctx)
                    _mem_data = _mem_for_resp(_mem_ctx)
                    _request = request.model_copy(update={
                        "memory_context_block": _mem_block,
                        "memory_context_data": _mem_data,
                    })
                    logger.debug(
                        "[ask] 9C pre-dispatch memory loaded for %s (%d prior queries)",
                        _pre_dispatch_ticker,
                        _mem_ctx.get("total_queries", 0),
                    )
        except Exception as _mem_exc:
            logger.debug("[ask] 9C pre-dispatch memory read failed (non-fatal): %r", _mem_exc)
            # _request remains as original request — no memory, no problem

        # ── Slice 5A + 5C/5D: Dossier injection (shadow + canary) ─────────────
        # One dossier fetch shared between the 5A shadow telemetry path and the
        # 5C canary live-injection path.  Three invariants enforced:
        #   1. _request is modified (dossier_context_block set) ONLY when the
        #      session is in the injected cohort AND all gates pass.
        #   2. Any exception leaves _request and _5c_* variables unchanged.
        #   3. The canary path is permanently inert at the default settings
        #      (DOSSIER_INJECTION_ENABLED=false, DOSSIER_INJECTION_CANARY_PCT=0).
        import time as _time_5c
        _5c_cohort: Optional[str] = None      # INELIGIBLE | CONTROL | INJECTED
        _5c_injected: bool = False             # True only when block attached
        _5c_ticker: Optional[str] = _pre_dispatch_ticker
        _5c_pre_t: float = _time_5c.monotonic()

        try:
            from .config import settings as _5c_cfg
            from .services import dossier_canary_telemetry as _can_tel
            from .services.dossier_canary_cohort import (
                decide_cohort as _decide_cohort,
                COHORT_INELIGIBLE as _INELIGIBLE,
                COHORT_INJECTED as _COHORT_INJ,
            )

            _5c_eff_enabled = _can_tel.get_enabled(bool(_5c_cfg.dossier_injection_enabled))
            _5c_canary_pct  = int(_5c_cfg.dossier_injection_canary_pct)
            _5c_session     = _session_id or "anon"

            _need_dossier = (
                _pre_dispatch_ticker
                and (
                    _5c_cfg.dossier_injection_shadow
                    or (_5c_eff_enabled and _5c_canary_pct > 0)
                )
            )

            _inj_res_shared = None  # InjectionResult or None
            if _need_dossier:
                from .db import get_session as _gs_5c
                from .db.repositories.dossier_repo import get_full_dossier as _get_doss_5c
                from .services.dossier_injection_service import build_injection_block as _build_inj_5c

                _5c_intent = getattr(request, "question_intent", None) or "general"
                async with _gs_5c() as _doss_sess_5c:
                    _doss_5c = (
                        await _get_doss_5c(_doss_sess_5c, _pre_dispatch_ticker)
                        if _doss_sess_5c else None
                    )
                _inj_res_shared = (
                    _build_inj_5c(_doss_5c, question_intent=_5c_intent)
                    if _doss_5c else None
                )

            # 5A shadow telemetry (log-only, never attached to prompt).
            if _5c_cfg.dossier_injection_shadow and _pre_dispatch_ticker:
                from .services import dossier_injection_telemetry as _inj_tel_5a
                if _inj_res_shared is None:
                    _inj_tel_5a.record_null(_pre_dispatch_ticker)
                else:
                    _inj_tel_5a.record_build(
                        ticker=_pre_dispatch_ticker,
                        token_count=_inj_res_shared.token_count,
                        staleness_state=_inj_res_shared.staleness_state,
                        intent=_inj_res_shared.intent,
                        included_facets=_inj_res_shared.included_facets,
                        dropped_facets=_inj_res_shared.dropped_facets,
                        token_cap=350,
                    )
                    logger.info(
                        "[ask] 5A shadow dossier block for %s: %d tok (%s) facets=%s dropped=%s",
                        _pre_dispatch_ticker, _inj_res_shared.token_count,
                        _inj_res_shared.staleness_state,
                        _inj_res_shared.included_facets, _inj_res_shared.dropped_facets,
                    )

            # 5C canary: cohort decision + decision-event recording.
            if _pre_dispatch_ticker:
                _5c_cohort = _decide_cohort(_5c_session, _5c_canary_pct, _5c_eff_enabled)

                # Extract prior stance from dossier when available (for metrics).
                _5c_prior_stance = None
                if _doss_5c if _need_dossier else False:
                    try:
                        _5c_prior_stance = getattr(_doss_5c, "prior_state_label", None)
                    except Exception:
                        pass

                _can_tel.record_decision(
                    session_id=_5c_session,
                    cohort=_5c_cohort,
                    ticker=_pre_dispatch_ticker,
                    canary_pct=_5c_canary_pct,
                    token_count=(_inj_res_shared.token_count if _inj_res_shared else 0),
                    facets=(_inj_res_shared.included_facets if _inj_res_shared else []),
                    staleness=(_inj_res_shared.staleness_state if _inj_res_shared else "unknown"),
                    dossier_age_days=None,
                    prior_stance=_5c_prior_stance,
                )

                # Persist decision event to audit_log (fire-and-forget).
                # Queued before synthesis starts so it survives process teardown.
                try:
                    from .services.canary_audit import schedule_decision_persist as _sched_dec
                    _5c_blk_tok = _inj_res_shared.token_count if _inj_res_shared else 0
                    _sched_dec(
                        _asyncio.create_task,
                        session_id=_5c_session,
                        cohort=_5c_cohort,
                        ticker=_pre_dispatch_ticker,
                        token_count=_5c_blk_tok,
                        block_tokens=_5c_blk_tok,
                    )
                except Exception as _dec_pers_exc:
                    logger.debug("[ask] canary decision persist schedule failed (non-fatal): %r", _dec_pers_exc)
            else:
                _5c_cohort = _INELIGIBLE

            # Attach block to request — ONLY when all gates pass.
            if (
                _5c_cohort == _COHORT_INJ
                and _inj_res_shared is not None
                and _5c_eff_enabled
                and _5c_canary_pct > 0
            ):
                _request = _request.model_copy(update={
                    "dossier_context_block": _inj_res_shared.block_str,
                })
                _5c_injected = True
                logger.info(
                    "[ask] 5C dossier block attached for %s (session=%.8s cohort=%s tok=%d)",
                    _pre_dispatch_ticker, _5c_session, _5c_cohort,
                    _inj_res_shared.token_count,
                )

        except Exception as _5c_exc:
            logger.debug("[ask] 5C dossier injection block failed (non-fatal): %r", _5c_exc)
            # _request and _5c_* stay at their defaults — prompt is unchanged.

        # Phase 20A: attach session_id to request for session-context tracking.
        _request._session_id = _session_id  # type: ignore[attr-defined]

        # run_in_executor does not carry contextvars into the worker thread, so
        # the trace is bound explicitly. This only sets a contextvar — the
        # callable, its argument and its return value are unchanged.
        fut = loop.run_in_executor(None, _obs_bind(route_question, _trace), _request)

        # Emit keepalive bytes every 25 s while pipeline runs.
        # asyncio.wait_for + asyncio.shield: times out without cancelling fut.
        # Each yielded byte resets Nginx's proxy_read_timeout clock.
        #
        # Sprint 3C.1A — in progressive mode the same shield/wait_for pattern
        # runs on a shorter cadence and emits real trace transitions instead of
        # bare keepalives. The legacy branch below is untouched, so a
        # non-negotiating caller receives exactly the bytes it does today.
        if _progressive:
            _projector = _ProgressProjector()
            _last_emit = _time.monotonic()
            for _f in _projector.initial(_trace.total_duration_ms()):
                yield _encode_frame(_f)
                _last_emit = _time.monotonic()
            while not fut.done():
                try:
                    await _asyncio.wait_for(
                        _asyncio.shield(fut), timeout=_PROGRESS_POLL_S
                    )
                    break
                except _asyncio.TimeoutError:
                    try:
                        _frames = _projector.project(_trace.progress_snapshot())
                    except Exception as _pg_exc:  # pragma: no cover - defensive
                        # Progress projection must never be able to fail the
                        # request it is only observing.
                        logger.debug("[ask] progress projection failed: %r", _pg_exc)
                        _frames = []
                    for _f in _frames:
                        yield _encode_frame(_f)
                        _last_emit = _time.monotonic()
                    if _time.monotonic() - _last_emit >= _PROGRESS_HEARTBEAT_S:
                        # Blank line: valid NDJSON no-op that parsers skip, so a
                        # heartbeat cannot be mistaken for an event.
                        yield b"\n"
                        _last_emit = _time.monotonic()
                except Exception:
                    # route_question raised inside the wait window. Break so the
                    # `await fut` below re-raises it into the terminal handler;
                    # without this the exception escapes the generator entirely
                    # and the caller gets a broken stream with no error frame.
                    break
        else:
            while not fut.done():
                try:
                    await _asyncio.wait_for(
                        _asyncio.shield(fut), timeout=_KEEPALIVE_INTERVAL_S
                    )
                    # Future completed within the window — exit the loop.
                    break
                except _asyncio.TimeoutError:
                    yield b"\r\n"  # keepalive: reset Nginx proxy_read_timeout
                except Exception:
                    # Pre-existing gap: the loop sits outside the try below, so
                    # a route_question exception raised during a keepalive
                    # window escaped uncaught and produced a broken stream
                    # instead of the documented error body. Break and let
                    # `await fut` re-raise it into that handler.
                    break

        # Retrieve result and emit JSON body.
        try:
            result = await fut

            # Phase 9A: fire-and-forget persistence (never blocks response).
            try:
                from .db.persistence import persist_analysis_result as _persist
                _asyncio.create_task(
                    _persist(
                        question=request.question,
                        company_name=request.company_name,
                        session_id=_session_id,
                        result=result,
                    ),
                    name=f"persist-{_session_id[:8]}",
                )
            except Exception as _p_exc:
                logger.debug("[ask] persistence task creation failed (non-fatal): %r", _p_exc)

            # ── Phase 9C: Post-dispatch memory stamp ──────────────────────────
            # After the thread returns we know the *confirmed* resolved ticker
            # from routing metadata.  If the pre-dispatch read didn't produce
            # memory data (e.g. company_name was blank and entity detection
            # missed), retry here using the authoritative ticker and stamp the
            # result dict directly so the banner always has data.
            try:
                _result_dict = result.model_dump()
                _thesis_in_answer = (
                    _result_dict.get("answer", {}).get("investment_thesis")
                    if isinstance(_result_dict.get("answer"), dict)
                    else None
                )
                if isinstance(_thesis_in_answer, dict) and _thesis_in_answer.get("memory_context") is None:
                    # Pre-dispatch didn't produce memory — try with confirmed ticker.
                    _confirmed_ticker = (
                        result.routing.get("detected_ticker")
                        or result.company
                        or _pre_dispatch_ticker
                    )
                    if _confirmed_ticker:
                        from .db import get_session as _gs2
                        from .db.repositories.memory_retrieval import get_memory_context as _gm2
                        from .memory_context import memory_context_for_response as _mfr2
                        async with _gs2() as _s2:
                            _post_ctx = await _gm2(_s2, _confirmed_ticker)
                        if _post_ctx:
                            _thesis_in_answer["memory_context"] = _mfr2(_post_ctx)
                            logger.debug(
                                "[ask] 9C post-dispatch memory stamped for %s (%d queries)",
                                _confirmed_ticker,
                                _post_ctx.get("total_queries", 0),
                            )
            except Exception as _post_exc:
                logger.debug("[ask] 9C post-dispatch memory stamp failed (non-fatal): %r", _post_exc)
                _result_dict = result.model_dump()

            # ── Phase 9F: Post-dispatch historical evidence stamp ─────────────
            # Runs after Phase 9C memory stamp.  Uses _result_dict already built
            # above.  Fails silently — never blocks or modifies the response
            # unless analogs are found.
            try:
                _9f_thesis = (
                    _result_dict.get("answer", {}).get("investment_thesis")
                    if isinstance(_result_dict.get("answer"), dict)
                    else None
                )
                if isinstance(_9f_thesis, dict) and _9f_thesis.get("historical_evidence") is None:
                    _9f_ticker = (
                        result.routing.get("detected_ticker")
                        or result.company
                        or _pre_dispatch_ticker
                    )
                    from .evidence_engine import build_fingerprint as _build_fp, retrieve_historical_analogs as _retrieve_analogs
                    from .db import get_session as _gs9f
                    from .db.repositories.evidence_repo import get_all_analogs as _get_analogs
                    # Phase 7: pass company profile for deterministic business_model in fingerprint
                    _9f_profile = None
                    try:
                        from .services.company_knowledge import get_knowledge_profile as _gkp9f
                        _9f_profile = _gkp9f(_9f_ticker) if _9f_ticker else None
                    except Exception:
                        pass
                    _9f_fp = _build_fp(
                        question=request.question,
                        thesis_dict=_9f_thesis,
                        ticker=_9f_ticker,
                        profile=_9f_profile,
                    )
                    async with _gs9f() as _s9f:
                        _9f_all = await _get_analogs(_s9f)
                    _9f_results = _retrieve_analogs(_9f_all, _9f_fp)
                    if _9f_results:
                        _9f_thesis["historical_evidence"] = {
                            "analogs": _9f_results,
                            "retrieval_note": None,
                        }
                        logger.debug(
                            "[ask] 9F evidence stamped: %d analogs for %s (top mechanism: %s)",
                            len(_9f_results),
                            _9f_ticker,
                            _9f_results[0].get("mechanism") if _9f_results else "n/a",
                        )
                    else:
                        _9f_thesis["historical_evidence"] = {
                            "analogs": [],
                            "retrieval_note": "No strong historical analog found for this setup.",
                        }
            except Exception as _9f_exc:
                logger.debug("[ask] 9F post-dispatch evidence stamp failed (non-fatal): %r", _9f_exc)

            # ── Phase 9G · Phase 0: Post-dispatch dossier extraction ──────────
            # Fire-and-forget task: harvest signals from the thesis and write
            # to dossier facet tables.  Behind dossier_extraction_enabled flag.
            # Never blocks or fails the response.
            try:
                from .config import settings as _9g_cfg
                if _9g_cfg.dossier_extraction_enabled:
                    import uuid as _9g_uuid
                    from .db.dossier_extraction_task import (
                        run_dossier_extraction_task as _run_dossier,
                    )
                    _9g_thesis = (
                        _result_dict.get("answer", {}).get("investment_thesis")
                        if isinstance(_result_dict.get("answer"), dict)
                        else None
                    )
                    if isinstance(_9g_thesis, dict):
                        _9g_ticker = (
                            _9g_thesis.get("ticker")
                            or result.routing.get("detected_ticker")
                            or result.company
                            or _pre_dispatch_ticker
                            or ""
                        )
                        _9g_company = (
                            _9g_thesis.get("company_name")
                            or request.company_name
                            or ""
                        )
                        _9g_user_id = (
                            http_request.headers.get("X-User-ID") or None
                        )
                        _9g_version_id = str(_9g_uuid.uuid4())
                        _asyncio.create_task(
                            _run_dossier(
                                ticker       = _9g_ticker,
                                company_name = _9g_company,
                                thesis_dict  = _9g_thesis,
                                version_id   = _9g_version_id,
                                session_id   = _session_id,
                                user_id      = _9g_user_id,
                            ),
                            name=f"dossier-{_session_id[:8]}",
                        )
                        logger.debug(
                            "[ask] 9G dossier extraction task queued for %s (version=%s)",
                            _9g_ticker, _9g_version_id[:8],
                        )
            except Exception as _9g_exc:
                logger.debug(
                    "[ask] 9G dossier extraction task creation failed (non-fatal): %r",
                    _9g_exc,
                )

            # ── Slice 5C/5D: Post-synthesis outcome recording ─────────────────
            # Records conviction, stance, change-vector engagement, and drift
            # metrics for both injected and control cohorts.  Never raises.
            #
            # Fallback detection covers two shapes:
            #   "unavailable"     — generic synthesis failure / httpx timeout
            #   "wall cap exceeded" — Python-side 56s wall-cap fallback
            # Both set confidence_score=0.0 and produce recognisable conclusions.
            try:
                if _5c_cohort is not None:
                    import re as _re_5c
                    from .services import dossier_canary_telemetry as _can_tel_out
                    from .services.canary_audit import schedule_outcome_persist as _sched_out

                    _5c_thesis_out = (
                        _result_dict.get("answer", {}).get("investment_thesis")
                        if isinstance(_result_dict.get("answer"), dict)
                        else None
                    )
                    if isinstance(_5c_thesis_out, dict):
                        _5c_stance       = _5c_thesis_out.get("directional_stance") or _5c_thesis_out.get("stance")
                        _5c_conviction   = _5c_thesis_out.get("confidence_score")
                        _5c_conclusion   = str(_5c_thesis_out.get("conclusion") or "")
                        _5c_cv           = _5c_thesis_out.get("change_vector") or {}
                        _5c_cv_text      = str(_5c_cv) if _5c_cv else ""

                        # Fallback: either generic "unavailable" OR wall-cap "wall cap exceeded".
                        _5c_score_zero   = (
                            isinstance(_5c_thesis_out.get("confidence_score"), float)
                            and _5c_thesis_out.get("confidence_score") == 0.0
                        )
                        _5c_conc_lower   = _5c_conclusion.lower()
                        _5c_wall_cap     = _5c_score_zero and "wall cap exceeded" in _5c_conc_lower
                        _5c_fallback     = _5c_score_zero and (
                            "unavailable" in _5c_conc_lower
                            or _5c_wall_cap
                        )

                        # Specificity: count numeric tokens in conclusion + direct_answer.
                        _5c_text_for_spec = (
                            _5c_conclusion
                            + " " + str(_5c_thesis_out.get("direct_answer") or "")
                        )
                        _5c_specificity = float(
                            len(_re_5c.findall(r"\d+\.?\d*", _5c_text_for_spec))
                        )
                        _5c_latency = round(_time_5c.monotonic() - _5c_pre_t, 2)
                        _5c_latency_ms = int(_5c_latency * 1000)

                        # Update in-memory wall-cap counter when applicable.
                        if _5c_wall_cap:
                            _can_tel_out.record_wall_cap_fallback()

                        _can_tel_out.record_outcome(
                            session_id=_session_id or "anon",
                            cohort=_5c_cohort,
                            ticker=_5c_ticker or "",
                            stance=str(_5c_stance) if _5c_stance else None,
                            conviction=float(_5c_conviction) if _5c_conviction is not None else None,
                            change_vector_len=len(_5c_cv_text),
                            conclusion_len=len(_5c_conclusion),
                            specificity=_5c_specificity,
                            fallback_used=bool(_5c_fallback),
                            latency_s=_5c_latency,
                            prior_challenged=_5c_thesis_out.get("prior_challenged"),
                        )

                        # Persist outcome to audit_log immediately (fire-and-forget).
                        # Enqueued here — before the yield — so it survives teardown.
                        _5c_cve_out = (
                            len(_5c_cv_text) / len(_5c_conclusion)
                            if len(_5c_conclusion) > 0 and len(_5c_cv_text) >= 0
                            else None
                        )
                        _sched_out(
                            _asyncio.create_task,
                            session_id=_session_id or "anon",
                            cohort=_5c_cohort,
                            ticker=_5c_ticker or "",
                            injected=bool(_5c_injected),
                            fallback=bool(_5c_fallback),
                            wall_cap_fallback=bool(_5c_wall_cap),
                            conviction=float(_5c_conviction) if _5c_conviction is not None else None,
                            specificity=_5c_specificity,
                            cve=_5c_cve_out,
                            latency_ms=_5c_latency_ms,
                        )
            except Exception as _5c_out_exc:
                logger.debug("[ask] 5C outcome recording failed (non-fatal): %r", _5c_out_exc)

            # ── Sprint 1B: content-integrity check (fail-closed, dict-level) ──────
            # Reconcile the valuation fields and flag cross-field contradictions
            # BEFORE the response reaches the frontend.  Operates on the emitted
            # dict (post-model), applies a qualified fallback for the price label on
            # a hard cheap/rich contradiction, and attaches a compact _integrity
            # block.  Fails OPEN on any error so it can never break the response.
            try:
                from .config import settings as _ci_cfg
                if getattr(_ci_cfg, "content_integrity_enabled", True):
                    with _obs_stage("integrity_validation"):
                        from .integrity.consistency import validate_thesis_integrity as _vti
                        _thesis = (
                            _result_dict.get("answer", {}).get("investment_thesis")
                            if isinstance(_result_dict.get("answer"), dict) else None
                        )
                        if isinstance(_thesis, dict):
                            _ir = _vti(_thesis, question=getattr(request, "question", None))
                            # Sprint 2C — the reconciled valuation state is authoritative.
                            # Apply its regime correction whenever the validator asks for
                            # one, not only on a hard failure: a soft cheap-vs-fully-priced
                            # disagreement still has to stop the response calling the stock
                            # cheap. "fair" remains the frontend-safe value for an
                            # undetermined state (the frontend has no such enum member).
                            _regime_fix = _ir.qualifications.get("expectation_regime")
                            if _regime_fix:
                                _thesis["expectation_regime"] = (
                                    "fair" if _regime_fix == "undetermined" else _regime_fix
                                )
                            if not _ir.ok:
                                logger.warning(
                                    "[ask] content-integrity: %d violation(s) for %s: %s",
                                    len(_ir.violations),
                                    _thesis.get("ticker") or _thesis.get("company") or "?",
                                    "; ".join(f"{v.code}({v.severity})" for v in _ir.violations),
                                )
                            _thesis["_integrity"] = {
                                "ok": _ir.ok,
                                # Sprint 2B — additive grade alongside `ok`:
                                # clean | qualified | degraded | blocked.
                                "status": _ir.status,
                                "severity_counts": _ir.severity_counts(),
                                "valuation_state": _ir.state,
                                "price_label": _ir.qualifications.get("price_label"),
                                "decision_threshold_coverage": _ir.qualifications.get(
                                    "decision_threshold_coverage"
                                ),
                                "violations": [
                                    {"code": v.code, "severity": v.severity, "field": v.field}
                                    for v in _ir.violations
                                ],
                                "caveats": [
                                    c for c in (
                                        _ir.qualifications.get("stale_precision_caveat"),
                                        _ir.qualifications.get("threshold_coverage_caveat"),
                                    )
                                    if c
                                ],
                            }
            except Exception as _ci_exc:
                logger.debug("[ask] content-integrity check failed (non-fatal): %r", _ci_exc)

            # ── Sprint 3A: additive _observability block ─────────────────────
            # Metadata only — request id, wall time, build identity and stage
            # timings. Never prompts, completions, evidence bodies or provider
            # credentials. Full stage detail is included only outside
            # production, where the extra payload is a debugging aid rather
            # than response weight on a metered endpoint.
            try:
                import os as _os_mod
                from .observability import (
                    DETAIL_REQUEST_HEADER as _DETAIL_HDR,
                    DETAIL_TOKEN_HEADER as _DETAIL_TOK_HDR,
                    should_include_detail as _should_detail,
                )
                # Sprint 3A.1 — in production, stage/model/provider detail is
                # released only to an explicitly authorized profiling request.
                # Ordinary users keep the compact block. Outside production the
                # Sprint 3A behavior (detail always on) is unchanged.
                _obs_detail = _should_detail(
                    is_production=_os_mod.environ.get("RENDER_SERVICE_ID") is not None,
                    detail_requested=http_request.headers.get(_DETAIL_HDR),
                    supplied_token=http_request.headers.get(_DETAIL_TOK_HDR),
                )
                _obs_block = _trace.to_dict(include_stages=_obs_detail)
                # Sprint 3B.1 — record WHICH synthesis prompt served this
                # request, so an A/B artifact can never be misattributed.
                from .observability import (
                    current_prompt_variant as _cur_variant,
                    current_model_variant as _cur_model_variant,
                    current_risk_variant as _cur_risk_variant,
                )
                from .services.synthesis_model_variants import describe_variant as _desc
                _obs_block["synthesis_variant"] = _cur_variant()
                _obs_block.update(_desc(_cur_model_variant()))
                # Sprint 3B.3 — record WHICH risk-agent shape served this
                # request, for the same anti-misattribution reason.
                _obs_block["risk_variant"] = _cur_risk_variant()
                _result_dict["_observability"] = _obs_block
            except Exception as _obs_exc:
                logger.debug("[ask] observability block failed (non-fatal): %r", _obs_exc)

            # Sprint 3C.1A — the SAME _result_dict is serialized on both paths.
            # Progressive only wraps it in a terminal frame, so the payload a
            # caller ends up with cannot diverge between the two modes.
            if _progressive:
                yield _encode_frame(_final_frame(_result_dict))
            else:
                yield _json.dumps(_result_dict).encode()
        except Exception as exc:
            logger.warning("[ask] route_question raised: %r", exc)
            # Correlation must survive the failure path — without the id the
            # error log and the client's response cannot be tied together.
            _err_body = {"error": "Question routing failed"}
            try:
                _err_body["_observability"] = _trace.to_dict(include_stages=False)
            except Exception:
                pass
            if _progressive:
                # Terminal error frame. The exception message is deliberately
                # not forwarded — it can carry a prompt fragment or an upstream
                # response body — only its class name.
                yield _encode_frame(_error_frame(
                    "Question routing failed",
                    error_class=type(exc).__name__,
                    stage="pipeline",
                ))
            else:
                yield _json.dumps(_err_body).encode()

    # X-Accel-Buffering: no — instructs Render/Nginx to disable response
    # buffering and forward each chunk immediately.  Without this, Nginx
    # accumulates all chunks before forwarding; keepalive bytes reach Nginx
    # (resetting the timer) but are never flushed to the client until the
    # full response is ready, making them invisible to monitoring and
    # causing intermittent failures when the buffer flush races with the
    # 60-second proxy_read_timeout window.
    return StreamingResponse(
        _generate(),
        # Sprint 3C.1A — the content type reflects what is actually on the wire,
        # so a proxy or client that does not understand NDJSON is never handed
        # a body labelled application/json that it cannot parse as one object.
        media_type=_PROGRESS_MEDIA if _progressive else _LEGACY_MEDIA,
        headers={"X-Accel-Buffering": "no"},
    )


# ── Phase 9B: Thesis Evolution endpoints ─────────────────────────────────────

@router.get(
    "/ticker/{ticker}/evolution",
    summary="Thesis evolution timeline for a ticker",
    tags=["evolution"],
)
async def get_ticker_evolution(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100),
    min_magnitude: str = Query(default="minor", pattern="^(minor|moderate|material)$"),
    since: Optional[str] = Query(default=None, description="ISO datetime cursor for pagination"),
) -> dict:
    """Return the full thesis evolution timeline for a ticker.

    Each delta entry contains summary versions (no full bull/bear text).
    Use GET /ticker/{ticker}/evolution/{delta_id} to expand a specific delta.

    Returns 404 when the ticker has no history.
    Returns 200 with empty deltas list when there is only one version.
    """
    from .db.connection import get_session
    from .db.repositories.evolution_repo import get_evolution_with_versions
    from datetime import datetime as _dt

    since_dt = None
    if since:
        try:
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")

    async with get_session() as session:
        ticker_upper = ticker.upper()
        result = await get_evolution_with_versions(
            session=session,
            ticker=ticker_upper,
            limit=limit,
            min_magnitude=min_magnitude,
            since=since_dt,
        )

    if result is None:
        raise HTTPException(status_code=404, detail=f"No history for ticker: {ticker.upper()}")
    return result


@router.get(
    "/ticker/{ticker}/evolution/{delta_id}",
    summary="Full diff for a single thesis delta",
    tags=["evolution"],
)
async def get_delta_detail(ticker: str, delta_id: str) -> dict:
    """Return full thesis text for both versions of a specific delta.

    Includes inline_diff word-count stats for each changed field.
    Used by the DiffCard component when the user expands a timeline item.

    Returns 404 when delta_id does not exist for this ticker.
    """
    from .db.connection import get_session
    from .db.repositories.evolution_repo import get_delta_full

    async with get_session() as session:
        result = await get_delta_full(
            session=session,
            ticker=ticker.upper(),
            delta_id=delta_id,
        )

    if result is None:
        raise HTTPException(status_code=404, detail=f"Delta {delta_id} not found for {ticker.upper()}")
    return result


@router.get(
    "/ticker/{ticker}/latest",
    summary="Latest thesis version and most recent change summary",
    tags=["evolution"],
)
async def get_ticker_latest(ticker: str) -> dict:
    """Return the most recent ThesisVersion for a ticker plus last delta metadata.

    Used by the LatestChangeCard UI component.
    last_delta is null when there is only one version (nothing to diff against).

    Returns 404 when the ticker has no recorded history.
    """
    from .db.connection import get_session
    from .db.repositories.evolution_repo import get_latest_change_card

    async with get_session() as session:
        result = await get_latest_change_card(
            session=session,
            ticker=ticker.upper(),
        )

    if result is None:
        raise HTTPException(status_code=404, detail=f"No history for ticker: {ticker.upper()}")
    return result


@router.get(
    "/material-changes",
    summary="Cross-ticker material change feed",
    tags=["evolution"],
)
async def get_material_changes(
    limit: int = Query(default=20, ge=1, le=100),
    since: Optional[str] = Query(default=None, description="ISO datetime pagination cursor"),
    tickers: Optional[str] = Query(default=None, description="Comma-separated ticker filter"),
) -> dict:
    """Return the cross-ticker material change feed.

    Shows only material-magnitude deltas that are debounce_visible=True
    (one per ticker per UTC calendar day — the largest |conviction_delta|).

    Paginate using the next_cursor value from the previous response.
    """
    from .db.connection import get_session
    from .db.repositories.evolution_repo import get_material_changes_feed
    from datetime import datetime as _dt

    since_dt = None
    if since:
        try:
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")

    ticker_list = None
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    async with get_session() as session:
        result = await get_material_changes_feed(
            session=session,
            limit=limit,
            since=since_dt,
            tickers=ticker_list,
        )

    return result


# ── Exchange short-name normalisation ─────────────────────────────────────────
_EXCHANGE_MAP = {
    "NASDAQ Global Select":    "NASDAQ",
    "NASDAQ Global Market":    "NASDAQ",
    "NASDAQ Capital Market":   "NASDAQ",
    "New York Stock Exchange": "NYSE",
    "NYSE American":           "AMEX",
    "NYSE Arca":               "AMEX",
    "Tokyo Stock Exchange":    "TSE",
    "London Stock Exchange":   "LSE",
    "Euronext Amsterdam":      "EURONEXT",
    "Euronext Paris":          "EURONEXT",
}


def _normalise_exchange(raw: Optional[str]) -> str:
    if not raw:
        return "NYSE"
    return _EXCHANGE_MAP.get(raw, raw)


def _fmp_get(url: str) -> Optional[list | dict]:
    """Minimal HTTP helper — returns None on any failure."""
    try:
        r = _requests.get(url, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.warning("FMP request failed: %s", exc)
        return None


@router.get(
    "/market/resolve",
    summary="Resolve company name/ticker to exchange symbol and market data",
    tags=["market"],
)
async def market_resolve(
    query: str = Query(..., description="Company name or ticker to resolve"),
) -> dict:
    """Resolve a company name or ticker to its exchange symbol.

    Returns resolved symbol information and optional real-time market data
    when FMP_API_KEY is configured.  Fields that cannot be populated are
    omitted from the response — the frontend must handle missing fields
    gracefully and must not display placeholder values.
    """
    from .config import settings

    api_key = settings.fmp_api_key
    base    = "https://financialmodelingprep.com/api/v3"

    ticker: Optional[str]   = None
    name:   Optional[str]   = None
    exchange: Optional[str] = None

    # ── Step 1: FMP symbol search ──────────────────────────────────────────
    search_url = f"{base}/search?query={_requests.utils.quote(query)}&limit=5"
    if api_key:
        search_url += f"&apikey={api_key}"
    search_data = _fmp_get(search_url)
    if search_data and isinstance(search_data, list) and search_data:
        top        = search_data[0]
        ticker     = top.get("symbol")
        name       = top.get("name")
        exchange   = _normalise_exchange(
            top.get("stockExchange") or top.get("exchangeShortName")
        )

    if not ticker:
        return {"query": query, "error": "Symbol could not be resolved"}

    tv_symbol = f"{exchange}:{ticker}" if exchange else ticker

    result: dict = {
        "query":             query,
        "name":              name,
        "ticker":            ticker,
        "exchange":          exchange,
        "tradingViewSymbol": tv_symbol,
    }

    # ── Step 2: real-time quote (only when API key present) ────────────────
    if api_key:
        quote_url  = f"{base}/quote/{ticker}?apikey={api_key}"
        quote_data = _fmp_get(quote_url)
        if quote_data and isinstance(quote_data, list) and quote_data:
            q_rec = quote_data[0]
            def _safe_float(val) -> Optional[float]:
                try:
                    return float(val) if val is not None else None
                except (TypeError, ValueError):
                    return None

            price           = _safe_float(q_rec.get("price"))
            change_pct      = _safe_float(q_rec.get("changesPercentage"))
            market_cap      = _safe_float(q_rec.get("marketCap"))
            volume          = q_rec.get("volume")
            high_52         = _safe_float(q_rec.get("yearHigh"))
            low_52          = _safe_float(q_rec.get("yearLow"))
            pe              = _safe_float(q_rec.get("pe"))

            if price           is not None: result["price"]            = price
            if change_pct      is not None: result["changePercent"]    = change_pct
            if market_cap      is not None: result["marketCap"]        = market_cap
            if volume          is not None: result["volume"]           = volume
            if high_52         is not None: result["fiftyTwoWeekHigh"] = high_52
            if low_52          is not None: result["fiftyTwoWeekLow"]  = low_52
            if pe              is not None: result["peRatio"]          = pe

        # ── Step 3: forward P/E from analyst consensus EPS estimate ───────
        # FMP /analyst-estimates returns annual estimates sorted desc; we
        # take the earliest *future* fiscal year to get next-12m forward EPS.
        if price is not None:
            est_url  = f"{base}/analyst-estimates/{ticker}?limit=4&apikey={api_key}"
            est_data = _fmp_get(est_url)
            if est_data and isinstance(est_data, list):
                import datetime as _dt
                current_year = _dt.date.today().year
                fwd_eps: Optional[float] = None
                for est in sorted(est_data, key=lambda r: r.get("date", ""), reverse=False):
                    try:
                        est_year = int(str(est.get("date", ""))[:4])
                    except (ValueError, TypeError):
                        continue
                    if est_year >= current_year:
                        raw_eps = est.get("estimatedEpsAvg") or est.get("estimatedEps")
                        fwd_eps = _safe_float(raw_eps)
                        if fwd_eps and fwd_eps > 0:
                            break
                if fwd_eps and fwd_eps > 0:
                    result["forwardPe"] = round(price / fwd_eps, 1)

    return result


# =============================================================================
# WATCHLIST ENDPOINTS
# =============================================================================


@router.get(
    "/watchlist",
    response_model=list,
    summary="List all watchlisted tickers",
    tags=["watchlist"],
)
async def get_watchlist(request: Request = None) -> list:
    """Return all watchlist entries sorted by most-recently-added.

    Authenticated accounts always use durable, user-scoped membership. Legacy
    local/system operation may still use the file-backed index.
    """
    from .config import settings as _wl_s
    from .dependencies.auth import require_user_id as _require_uid
    from .services.watchlist_scope_service import (
        is_authenticated_watchlist_request,
        should_use_db_watchlist,
    )
    _uid = _require_uid(request)   # 401 when unauthenticated under enforcement mode
    if should_use_db_watchlist(
        request,
        feature_enabled=getattr(_wl_s, "watchlist_db_backed", False),
    ):
        try:
            from .db import get_session as _get_session
            async with _get_session() as _db:
                entries = await watchlist_service.get_watchlist_async(_db, user_id=_uid)
            return [e.model_dump() for e in entries]
        except Exception as _exc:
            logger.warning("[watchlist] DB-backed read failed: %r", _exc)
            if is_authenticated_watchlist_request(request):
                raise HTTPException(
                    status_code=503,
                    detail="Watchlist persistence is temporarily unavailable.",
                ) from _exc
    return [e.model_dump() for e in watchlist_service.get_watchlist()]


@router.post(
    "/watchlist/{ticker}",
    response_model=dict,
    summary="Add a ticker to the watchlist",
    tags=["watchlist"],
)
async def add_to_watchlist(
    ticker:       str,
    company_name: str = Query(default="", description="Optional canonical company name"),
    request:      Request = None,
) -> dict:
    """Add *ticker* to the watchlist.  Idempotent — safe to call multiple times."""
    from .dependencies.auth import require_user_id as _require_uid
    _uid = _require_uid(request)   # 401 when unauthenticated under enforcement mode
    # Phase 17 · Slice 6 — entitlement enforcement (no-op when ENTITLEMENTS_ENFORCED=false)
    try:
        from .services.entitlement_enforcement import (
            check_watchlist_limit,
            EntitlementViolation,
        )
        from .services.entitlement_service import resolve_entitlements
        from .db import get_session as _get_session

        _user_id = getattr(getattr(request, "state", None), "user_id", "") or ""
        async with _get_session() as _db:
            _ent = await resolve_entitlements(_db, _user_id)
            _already_tracked = await watchlist_service.is_tracked_async(
                _db, ticker, user_id=_uid,
            )
            _current = len(
                await watchlist_service.get_watchlist_async(_db, user_id=_uid)
            )

        # Count only the acting account's membership. Idempotent adds do not
        # consume an additional entitlement slot.
        if not _already_tracked:
            check_watchlist_limit(_ent, _current)
    except EntitlementViolation as _exc:
        raise HTTPException(status_code=402, detail=_exc.as_dict())
    except HTTPException:
        raise
    except Exception:
        pass  # enforcement is failure-open

    # Phase 10B · Slice 2 — DB-backed membership when enabled (dual-writes file).
    from .config import settings as _wl_s
    from .services.watchlist_scope_service import (
        is_authenticated_watchlist_request,
        should_use_db_watchlist,
    )
    if should_use_db_watchlist(
        request,
        feature_enabled=getattr(_wl_s, "watchlist_db_backed", False),
    ):
        try:
            from .db import get_session as _get_session
            async with _get_session() as _db:
                entry = await watchlist_service.add_ticker_async(
                    _db, ticker, company_name, user_id=_uid)
            return entry.model_dump()
        except Exception as _exc:
            logger.warning("[watchlist] DB-backed add failed: %r", _exc)
            if is_authenticated_watchlist_request(request):
                raise HTTPException(
                    status_code=503,
                    detail="Watchlist persistence is temporarily unavailable.",
                ) from _exc

    entry = watchlist_service.add_ticker(ticker, company_name)
    return entry.model_dump()


@router.delete(
    "/watchlist/{ticker}",
    response_model=dict,
    summary="Remove a ticker from the watchlist",
    tags=["watchlist"],
)
async def remove_from_watchlist(ticker: str, request: Request = None) -> dict:
    """Remove *ticker* from the watchlist.  Returns {removed: bool}.

    Phase 10B · Slice 2: routes through the DB-backed async path when
    ``watchlist_db_backed`` is enabled (still removes the file entry too).
    """
    from .config import settings as _wl_s
    from .dependencies.auth import require_user_id as _require_uid
    from .services.watchlist_scope_service import (
        is_authenticated_watchlist_request,
        should_use_db_watchlist,
    )
    _uid = _require_uid(request)   # 401 when unauthenticated under enforcement mode
    if should_use_db_watchlist(
        request,
        feature_enabled=getattr(_wl_s, "watchlist_db_backed", False),
    ):
        try:
            from .db import get_session as _get_session
            async with _get_session() as _db:
                removed = await watchlist_service.remove_ticker_async(
                    _db, ticker, user_id=_uid)
            return {"ticker": ticker.upper(), "removed": removed}
        except Exception as _exc:
            logger.warning("[watchlist] DB-backed remove failed: %r", _exc)
            if is_authenticated_watchlist_request(request):
                raise HTTPException(
                    status_code=503,
                    detail="Watchlist persistence is temporarily unavailable.",
                ) from _exc

    removed = watchlist_service.remove_ticker(ticker)
    return {"ticker": ticker.upper(), "removed": removed}


@router.get(
    "/watchlist/{ticker}/snapshots",
    response_model=list,
    summary="Get thesis snapshot history for a ticker",
    tags=["watchlist"],
)
async def get_snapshots(
    ticker: str,
    limit:  int = Query(default=20, ge=1, le=200, description="Max snapshots to return"),
) -> list:
    """Return the thesis snapshot history for *ticker*, newest-first."""
    snaps = watchlist_service.get_snapshots(ticker, limit=limit)
    return [s.model_dump() for s in snaps]


@router.get(
    "/watchlist/{ticker}/diff",
    response_model=dict,
    summary="Get the latest thesis diff for a ticker",
    tags=["watchlist"],
)
async def get_latest_diff(ticker: str) -> dict:
    """Return the diff between the two most recent snapshots for *ticker*.

    Returns {available: false} when fewer than two snapshots exist.
    """
    diff = watchlist_service.get_latest_diff(ticker)
    if diff is None:
        return {"available": False, "ticker": ticker.upper()}
    return {"available": True, "ticker": ticker.upper(), **diff.model_dump()}


@router.get(
    "/watchlist/changes/material",
    response_model=list,
    summary="Get material change events across all watchlisted tickers",
    tags=["watchlist"],
)
async def get_material_changes(
    limit: int = Query(default=50, ge=1, le=500, description="Max events to return"),
) -> list:
    """Return the most recent material change events across the entire watchlist."""
    events = watchlist_service.get_material_changes(limit=limit)
    return [e.model_dump() for e in events]


@router.get(
    "/watchlist/{ticker}/changes",
    response_model=list,
    summary="Get material change events for a specific ticker",
    tags=["watchlist"],
)
async def get_ticker_changes(
    ticker: str,
    limit:  int = Query(default=20, ge=1, le=200),
) -> list:
    """Return material change events for *ticker*, newest-first."""
    events = watchlist_service.get_material_changes(ticker=ticker, limit=limit)
    return [e.model_dump() for e in events]


@router.post(
    "/watchlist/{ticker}/acknowledge",
    response_model=dict,
    summary="Clear the material-change flag for a ticker",
    tags=["watchlist"],
)
async def acknowledge_change(ticker: str) -> dict:
    """Mark the material-change alert as reviewed for *ticker*."""
    watchlist_service.clear_material_change_flag(ticker)
    return {"ticker": ticker.upper(), "acknowledged": True}


@router.get(
    "/alerts",
    response_model=list,
    summary="Get real-time thesis alerts from material change events",
    tags=["watchlist"],
)
async def get_alerts(
    limit: int = Query(default=30, ge=1, le=200, description="Max alerts to return"),
) -> list:
    """Return material change events formatted as analyst alerts, newest-first.

    Each alert includes: ticker, headline, summary, severity, timestamp, change_type.
    Backed by the persistent MaterialChangeEvent store — only returns real events
    from actual thesis analyses. Returns empty list when no events exist.
    """
    events = watchlist_service.get_material_changes(limit=limit)
    alerts = []
    for ev in events:
        # Format timestamp for display
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
            ts_display = dt.strftime("%b %d · %H:%M")
        except Exception:
            ts_display = ev.timestamp[:16] if ev.timestamp else "—"

        alerts.append({
            "id":          ev.event_id,
            "ticker":      ev.ticker,
            "headline":    ev.summary,
            "summary":     _build_alert_body(ev),
            "severity":    ev.severity,
            "timestamp":   ts_display,
            "change_type": ev.change_type,
        })
    return alerts


def _build_alert_body(ev) -> str:
    """Build a contextual alert body from a MaterialChangeEvent."""
    parts = []
    if ev.drivers:
        # First driver as context
        parts.append(ev.drivers[0])
    if ev.confidence_change and abs(ev.confidence_change) >= 0.04:
        direction = "improved" if ev.confidence_change > 0 else "weakened"
        parts.append(f"Conviction {direction} since the prior analysis.")
    if not parts:
        parts.append("Review the updated thesis for full context.")
    return " ".join(parts)


# =============================================================================
# PHASE I ENDPOINTS
# =============================================================================


@router.get(
    "/morning-brief",
    response_model=dict,
    summary="[Deprecated] Morning brief v1 — redirects to /morning-brief/v2",
    tags=["intelligence"],
)
async def get_morning_brief() -> dict:
    """Deprecated v1 morning-brief endpoint.

    Returns a machine-readable deprecation notice pointing callers to the
    canonical v2 endpoint.  The v1 implementation (generate_morning_brief)
    is no longer called from production code; use GET /morning-brief/v2.
    """
    return {
        "deprecated": True,
        "redirect": "/morning-brief/v2",
        "message": (
            "This endpoint is deprecated. "
            "Use GET /morning-brief/v2 for the current 5-section institutional brief."
        ),
    }


@router.get(
    "/timeline-events/{ticker}",
    response_model=list,
    summary="Get structured timeline events for a ticker",
    tags=["intelligence"],
)
async def get_timeline_events(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list:
    """Return structured TimelineEvent objects for *ticker*, newest-first.

    Converts stored material change events and thesis diffs into
    frontend-ready timeline entries.
    """
    from .services.timeline_event_service import get_ticker_timeline

    events = get_ticker_timeline(ticker, limit=limit)
    return [e.model_dump() for e in events]


@router.get(
    "/alert-priority/{ticker}",
    response_model=dict,
    summary="Get the priority level of the most recent alert for a ticker",
    tags=["intelligence"],
)
async def get_alert_priority(ticker: str) -> dict:
    """Return the AlertPriority for the most recent thesis diff for *ticker*.

    Returns {available: false} when no diff exists.
    """
    from .services.alert_prioritizer import alert_priority_score

    diff         = watchlist_service.get_latest_diff(ticker)
    latest_event = watchlist_service.get_material_changes(ticker=ticker, limit=1)
    event        = latest_event[0] if latest_event else None

    if diff is None:
        return {"available": False, "ticker": ticker.upper()}

    ap = alert_priority_score(diff, event)
    return {"available": True, "ticker": ticker.upper(), **ap.model_dump()}


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/history", tags=["history"])
async def get_history(
    ticker: Optional[str] = None,
    limit: int = 50,
) -> list:
    """Return analysis history, optionally filtered by ticker."""
    from .services.history_service import get_analysis_history
    try:
        entries = get_analysis_history(ticker=ticker, limit=limit)
        return [e.model_dump() for e in entries]
    except Exception as exc:
        logger.warning("get_history failed: %s", exc)
        return []

@router.get("/history/summary", tags=["history"])
async def get_history_summary_endpoint() -> dict:
    """Return a summary of tracked history."""
    from .services.history_service import get_history_summary
    try:
        return get_history_summary()
    except Exception as exc:
        logger.warning("get_history_summary failed: %s", exc)
        return {"total_tickers": 0, "total_entries": 0}

@router.get("/watchlist/themes", tags=["watchlist"])
async def get_watchlist_themes() -> list:
    """Return watchlist entries grouped by macro theme."""
    from .services.watchlist_themes import group_watchlist_by_theme
    try:
        entries = watchlist_service.get_watchlist()
        raw = [e.model_dump() for e in entries]
        groups = group_watchlist_by_theme(raw)
        return [g.model_dump() for g in groups]
    except Exception as exc:
        logger.warning("get_watchlist_themes failed: %s", exc)
        return []

@router.get("/usage/stats", tags=["usage"])
async def get_usage_stats(http_request: Request) -> dict:
    """Return aggregate usage statistics.

    Internal aggregate — admin-only by default (USAGE_STATS_ADMIN_ONLY).  The
    system/bypass user is admin in single-tenant mode; when AUTH_ENABLED, only
    ADMIN_USER_IDS may read it.  Never exposes per-user or cross-user rows.
    """
    from .config import settings as _s
    if _s.usage_stats_admin_only:
        from .security.authz import require_admin
        require_admin(http_request)   # 401 unauth / 403 non-admin
    from .services.usage_tracking import usage_tracker
    return usage_tracker.get_totals()


# ── Live Market Intelligence (Phase L) ───────────────────────────────────────

@router.post("/events/ingest", tags=["events"])
async def ingest_event(event_data: dict, http_request: Request) -> dict:
    """
    Ingest a normalized event and return impact assessments for all relevant tickers.
    Accepts NormalizedEvent-compatible dict.

    Internal ingestion hook — OFF by default (EVENTS_INGEST_ENABLED).  When
    enabled it requires admin authorization and enforces a payload-size cap
    (MAX_EVENT_PAYLOAD_BYTES); unknown fields are dropped (schema restriction).
    """
    from .config import settings as _s
    # Disabled by default → do not expose an arbitrary-payload sink.
    if not _s.events_ingest_enabled:
        raise HTTPException(status_code=403, detail="Event ingestion is disabled.")
    # Admin-only (system/bypass user in single-tenant; ADMIN_USER_IDS otherwise).
    from .security.authz import require_admin
    require_admin(http_request)
    # Payload-size cap (schema restriction to known fields happens below).
    import json as _json_ev
    try:
        _payload_bytes = len(_json_ev.dumps(event_data).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Malformed event payload.")
    if _payload_bytes > _s.max_event_payload_bytes:
        raise HTTPException(status_code=413, detail="Event payload too large.")

    from .services.ingestion.normalized_event import NormalizedEvent, EventCategory, SourceReliability
    from .services.event_processor import process_event_for_watchlist, save_impact_assessment
    from .services.market_regime_tracker import update_regime
    try:
        # Normalize event_data
        event = NormalizedEvent(**{
            k: v for k, v in event_data.items()
            if k in NormalizedEvent.model_fields
        })
        impacts = process_event_for_watchlist(event)
        # Save all non-noise impacts
        for impact in impacts:
            save_impact_assessment(impact)
        # Update regime if this is a macro event
        if event.category == EventCategory.MACRO:
            update_regime([event])
        return {
            "event_id": event.event_id,
            "ticker": event.ticker,
            "impact_count": len(impacts),
            "impacts": [i.model_dump() for i in impacts],
        }
    except Exception as exc:
        logger.warning("ingest_event failed: %s", exc)
        return {"error": str(exc), "impact_count": 0, "impacts": []}


@router.get("/events/impact/{ticker}", tags=["events"])
async def get_event_impacts(ticker: str, limit: int = 20) -> list:
    """Get recent event impact assessments for a specific ticker."""
    try:
        from .services.timeline_store import default_store
        entries = default_store.load(ticker.upper(), entry_type="event_impact")
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return [e.data for e in entries[:limit]]
    except Exception as exc:
        logger.warning("get_event_impacts failed: %s", exc)
        return []


@router.get("/regime", tags=["market"])
async def get_market_regime() -> dict:
    """Get the current market regime classification."""
    from .services.market_regime_tracker import get_current_regime
    try:
        regime = get_current_regime()
        return regime.model_dump()
    except Exception as exc:
        logger.warning("get_market_regime failed: %s", exc)
        return {"rate_environment": "uncertain", "risk_appetite": "selective"}


# ---------------------------------------------------------------------------
# Phase M — Real Market Infrastructure endpoints
# ---------------------------------------------------------------------------


@router.get("/pipeline/health", tags=["pipeline"])
async def get_pipeline_health() -> dict:
    """
    Return health status of all ingestion adapters.

    Reports per-adapter reachability, last run timestamp, dedup stats.
    """
    try:
        from .services.ingestion.event_ingestion_pipeline import get_default_pipeline
        pipeline = get_default_pipeline(auto_register=True)
        health = await pipeline.health_check()
        return health
    except Exception as exc:
        logger.warning("pipeline_health failed: %s", exc)
        return {"pipeline_healthy": False, "error": str(exc)}


class _PipelineRunRequest(BaseModel):
    tickers: Optional[list] = None
    since: Optional[str] = None


@router.post("/pipeline/run", tags=["pipeline"])
async def run_ingestion_pipeline(body: _PipelineRunRequest = None) -> dict:
    """
    Trigger a full ingestion pipeline run.

    Fetches from all registered adapters (SEC EDGAR, Treasury/Macro,
    Earnings, News), deduplicates, scores freshness, assesses thesis impact.

    Returns PipelineRunResult summary with impact assessments.
    """
    try:
        from .services.ingestion.event_ingestion_pipeline import get_default_pipeline
        pipeline = get_default_pipeline(auto_register=True)
        tickers = body.tickers if body else None
        since = body.since if body else None
        result = await pipeline.run(tickers=tickers, since=since)
        return {
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "duration_ms": result.duration_ms,
            "adapters_called": result.adapters_called,
            "events_fetched": result.events_fetched,
            "events_after_dedup": result.events_after_dedup,
            "events_after_freshness": result.events_after_freshness,
            "impact_assessments": [a.model_dump() for a in result.impact_assessments],
            "skipped_stale": result.skipped_stale,
            "adapter_errors": result.adapter_errors,
        }
    except Exception as exc:
        logger.warning("pipeline_run failed: %s", exc)
        return {"error": str(exc), "impact_assessments": []}


@router.post("/events/process", tags=["events"])
async def process_single_event(payload: dict) -> dict:
    """
    Process a single event through the LiveThesisUpdateService.

    Accepts a NormalizedEvent payload, runs through the full pipeline:
    normalize → thesis impact → regime update → watchlist drift.

    Returns UpdateSummary with per-ticker impact assessments.
    """
    try:
        from .services.ingestion.normalized_event import EventCategory, NormalizedEvent, SourceReliability
        from .services.live_thesis_update_service import get_live_thesis_service
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()

        # Build NormalizedEvent from payload with safe defaults
        event = NormalizedEvent(
            ticker=payload.get("ticker"),
            category=EventCategory(payload.get("category", "news")),
            headline=payload.get("headline", ""),
            body=payload.get("body", ""),
            source=payload.get("source", "api"),
            source_reliability=SourceReliability(
                payload.get("source_reliability", "medium")
            ),
            event_timestamp=payload.get("event_timestamp") or now_iso,
            ingestion_timestamp=now_iso,
            is_market_moving=payload.get("is_market_moving", False),
            tags=payload.get("tags", []),
            magnitude=payload.get("magnitude"),
        )

        service = get_live_thesis_service()
        summary = service.process_event(event)
        return summary.to_dict()
    except Exception as exc:
        logger.warning("process_single_event failed: %s", exc)
        return {"error": str(exc), "impact_count": 0}


@router.get("/events/freshness/{ticker}", tags=["events"])
async def get_event_freshness(ticker: str, limit: int = 20) -> list:
    """
    Return recent EventImpactAssessments with freshness scores for a ticker.

    Adds freshness metadata (age_hours, label, is_stale) to each assessment.
    Used by the frontend to display "Live / Today / This Week / Stale" labels.
    """
    try:
        from .services.timeline_store import default_store
        from .services.ingestion.freshness_scorer import freshness_label
        from datetime import datetime, timezone

        entries = default_store.load(ticker.upper(), entry_type="event_impact")
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        now = datetime.now(timezone.utc)
        result = []
        for entry in entries[:limit]:
            data = dict(entry.data)
            # Add freshness metadata based on assessment timestamp
            ts_str = data.get("timestamp", "") or entry.timestamp or ""
            age_hours = 999.0
            if ts_str:
                try:
                    ts_str_clean = ts_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(ts_str_clean)
                    if dt.tzinfo is None:
                        from datetime import timezone as tz
                        dt = dt.replace(tzinfo=tz.utc)
                    age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
                except Exception:
                    pass
            data["freshness_label"] = freshness_label(age_hours)
            data["age_hours"] = round(age_hours, 1)
            result.append(data)
        return result
    except Exception as exc:
        logger.warning("get_event_freshness failed: %s", exc)
        return []


@router.get("/morning-brief/v2", tags=["brief"])
async def get_morning_brief_v2(
    reference_date: Optional[str] = None,
    tickers: Optional[str] = Query(
        default=None,
        description="Comma-separated browser fallback used only when the signed-in account has no persisted watchlist",
    ),
    request: Request = None,
) -> dict:
    """
    Generate the Phase M 5-section institutional morning brief.

    Sections:
      1. Market Regime (rate_environment, risk_appetite, regime_headline)
      2. What Changed (narrative_shifts — 2-4 PM sentences)
      3. Debate Shifts (debate_shifts — 2-3 sentences)
      4. Priority Alerts (priority_alerts + attention_required tickers)
      5. Watchlist Drift (per-ticker direction/driver/materiality)

    Query params:
      tickers: comma-separated browser fallback for migrated accounts that do not
               yet have a persisted account watchlist.
      reference_date: ISO date string for the brief header (defaults to today UTC).
    """
    # Phase 17 · Slice 6 — entitlement enforcement (no-op when ENTITLEMENTS_ENFORCED=false)
    try:
        from .services.entitlement_enforcement import (
            check_briefing_limit,
            EntitlementViolation,
        )
        from .services.entitlement_service import resolve_entitlements
        from .db import get_session as _get_session

        _user_id = getattr(getattr(request, "state", None), "user_id", "") or ""
        async with _get_session() as _db:
            _ent = await resolve_entitlements(_db, _user_id)
        # No weekly usage counter yet — pass 0 (fail-open); blocks at limit=0 only.
        check_briefing_limit(_ent, 0)
    except EntitlementViolation as _exc:
        raise HTTPException(status_code=402, detail=_exc.as_dict())
    except HTTPException:
        raise
    except Exception:
        pass  # enforcement is failure-open

    try:
        from .services.watchlist_service import watchlist_service
        from .services.market_regime_tracker import get_current_regime
        from .services.thesis_impact_evaluator import get_default_evaluator
        from .services.morning_brief_service import generate_morning_brief_v2
        from .services.timeline_store import default_store
        from .schemas import EventImpactAssessment, WatchlistEntry as WLEntry
        from .services.brief_scope_service import parse_ticker_csv, resolve_brief_entries
        from .services.brief_material_change_service import (
            load_recent_material_changes,
            load_recent_material_changes_from_db,
            merge_material_changes,
        )

        # Resolve the brief universe without allowing a signed-in user to inherit
        # the process-wide legacy watchlist. Account rows are authoritative; the
        # browser list is a migration fallback only when the account is empty.
        legacy_entries = watchlist_service.get_watchlist()
        requested_tickers = parse_ticker_csv(tickers)
        user_id = getattr(getattr(request, "state", None), "user_id", "") or ""
        account_entries = []
        if user_id:
            try:
                from .db import get_session as _get_session
                from .db.repositories.watchlist_repo import ticker_list_active

                async with _get_session() as _db:
                    rows = await ticker_list_active(_db, user_id=user_id) if _db else []
                metadata = {entry.ticker.upper(): entry for entry in legacy_entries}
                account_entries = [
                    metadata.get(row.ticker.upper())
                    or WLEntry(
                        ticker=row.ticker,
                        company_name=row.company_name or row.ticker,
                        added_at=row.added_at.isoformat() if row.added_at else "",
                    )
                    for row in rows
                ]
            except Exception as scope_exc:
                logger.warning("morning_brief_v2 account scope lookup failed: %s", scope_exc)

        watchlist_entries, brief_scope = resolve_brief_entries(
            account_entries=account_entries,
            requested_tickers=requested_tickers,
            legacy_entries=legacy_entries,
            authenticated=bool(user_id),
        )

        # Fetch current regime
        try:
            regime = get_current_regime()
        except Exception:
            regime = None

        # Fetch recent event impacts across all watched tickers
        all_impacts = []
        for entry in watchlist_entries:
            try:
                ticker_entries = default_store.load(entry.ticker, entry_type="event_impact")
                ticker_entries.sort(key=lambda e: e.timestamp, reverse=True)
                for te in ticker_entries[:5]:
                    try:
                        all_impacts.append(EventImpactAssessment.model_validate(te.data))
                    except Exception:
                        pass
            except Exception:
                pass

        # Compute watchlist drift
        evaluator = get_default_evaluator()
        ticker_list = [e.ticker for e in watchlist_entries]
        drift = evaluator.get_watchlist_drift(ticker_list) if ticker_list else []

        # Postgres is authoritative for material thesis deltas because Render's
        # local timeline directory is ephemeral across deploys. Keep the local
        # store as a fallback for in-flight events and local development.
        durable_material_changes = []
        if ticker_list:
            try:
                from .db import get_session as _get_session

                async with _get_session() as _db:
                    durable_material_changes = (
                        await load_recent_material_changes_from_db(
                            _db,
                            ticker_list,
                        )
                        if _db
                        else []
                    )
            except Exception as material_exc:
                logger.warning(
                    "morning_brief_v2 durable material-change lookup failed: %s",
                    material_exc,
                )

        timeline_material_changes = load_recent_material_changes(
            default_store,
            ticker_list,
        )
        recent_material_changes = merge_material_changes(
            durable_material_changes,
            timeline_material_changes,
        )

        brief = generate_morning_brief_v2(
            watchlist_entries=watchlist_entries,
            recent_material_changes=recent_material_changes,
            event_impacts=all_impacts,
            watchlist_drift=drift,
            regime=regime,
            reference_date=reference_date,
        )
        payload = brief.model_dump()
        payload["brief_scope"] = brief_scope
        payload["tracked_tickers"] = ticker_list
        return payload
    except Exception as exc:
        logger.warning("morning_brief_v2 failed: %s", exc)
        # Return a valid empty-state brief rather than an error object
        return {
            "generated_at": "",
            "reference_date": reference_date or "",
            "ticker_count": 0,
            "regime_headline": "",
            "regime_factors": [],
            "rate_environment": "uncertain",
            "risk_appetite": "selective",
            "narrative_shifts": [],
            "debate_shifts": [],
            "priority_alerts": [],
            "attention_required": [],
            "watchlist_drift": [],
            "top_movers": [],
            "brief_text": "",
            "market_regime_note": "",
            "_error": str(exc),
        }


@router.get("/watchlist/drift", tags=["watchlist"])
async def get_watchlist_drift() -> list:
    """
    Return current thesis drift summaries for all watched tickers.

    Sorted by materiality descending. Direction: broke > weakened > strengthened > unchanged.
    Used by the watchlist page to show thesis evolution without running a full analysis.
    """
    try:
        from .services.watchlist_service import watchlist_service
        from .services.thesis_impact_evaluator import get_default_evaluator

        entries = watchlist_service.get_watchlist()
        tickers = [e.ticker for e in entries]
        evaluator = get_default_evaluator()
        drift = evaluator.get_watchlist_drift(tickers)
        return [d.model_dump() for d in drift]
    except Exception as exc:
        logger.warning("watchlist_drift failed: %s", exc)
        return []


@router.get("/watchlist/status", tags=["watchlist"])
async def get_watchlist_status() -> dict:
    """
    Diagnostic endpoint — returns the full state of the watchlist + analysis coverage.

    Returns:
      - registered_tickers: list of tickers in the backend registry
      - tickers_with_snapshots: tickers that have at least one thesis snapshot
      - tickers_with_analyses: same as snapshots (one analysis = one snapshot)
      - tickers_pending_analysis: registered but no snapshot yet
      - ticker_count: total registered
      - ready_count: registered + analyzed
      - pending_count: registered but not yet analyzed
      - guidance: human-readable next-step instruction

    Use this for frontend diagnostics and empty-state UX decisions.
    """
    try:
        from .services.watchlist_service import watchlist_service
        from .services.timeline_store import default_store

        entries = watchlist_service.get_watchlist()
        tickers_registered = [e.ticker for e in entries]

        # Check which tickers have snapshots (= have been analyzed)
        tickers_with_snapshots = []
        tickers_pending = []
        for ticker in tickers_registered:
            snaps = default_store.load(ticker, entry_type="thesis_snapshot")
            if snaps:
                tickers_with_snapshots.append(ticker)
            else:
                tickers_pending.append(ticker)

        ready_count = len(tickers_with_snapshots)
        pending_count = len(tickers_pending)
        total_count = len(tickers_registered)

        if total_count == 0:
            guidance = "Add companies to your watchlist by clicking 'Watch' on the analyze page."
        elif pending_count > 0 and ready_count == 0:
            guidance = (
                f"{pending_count} ticker{'s' if pending_count > 1 else ''} registered. "
                f"Run an analysis on each to populate the morning brief, timeline, and alerts."
            )
        elif pending_count > 0:
            guidance = (
                f"{ready_count} analyzed, {pending_count} pending analysis. "
                f"Analyze remaining tickers to complete your watchlist intelligence."
            )
        else:
            guidance = f"{ready_count} ticker{'s' if ready_count > 1 else ''} active with thesis memory."

        return {
            "registered_tickers": tickers_registered,
            "tickers_with_snapshots": tickers_with_snapshots,
            "tickers_pending_analysis": tickers_pending,
            "ticker_count": total_count,
            "ready_count": ready_count,
            "pending_count": pending_count,
            "guidance": guidance,
        }
    except Exception as exc:
        logger.warning("watchlist_status failed: %s", exc)
        return {
            "registered_tickers": [],
            "tickers_with_snapshots": [],
            "tickers_pending_analysis": [],
            "ticker_count": 0,
            "ready_count": 0,
            "pending_count": 0,
            "guidance": "Status unavailable.",
        }
