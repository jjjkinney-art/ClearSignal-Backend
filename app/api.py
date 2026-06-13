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
    router.add_api_route(
        _health_path,
        health,
        methods=["GET", "HEAD"],
        summary="Health check" if _health_path != "/" else "Root — service identity",
        tags=["health"],
        include_in_schema=True,
    )
del _health_path  # avoid leaking the loop variable into module scope


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
    """
    from .config import settings as _inj_s
    from .services import dossier_injection_telemetry as _inj_tel
    from .services import dossier_canary_telemetry as _can_tel
    from .services import dossier_canary_metrics as _can_met

    shadow_snap  = _inj_tel.snapshot()
    canary_snap  = _can_tel.snapshot()
    outcomes     = _can_tel.snapshot_outcomes()
    metrics      = _can_met.compute_all(outcomes)
    eff_enabled  = _can_tel.get_enabled(bool(_inj_s.dossier_injection_enabled))

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
    from fastapi.responses import StreamingResponse

    _KEEPALIVE_INTERVAL_S: float = 25.0  # < 60 s Nginx limit; resets the clock

    # Extract session ID for persistence correlation — prefer X-Session-ID,
    # fall back to X-Request-ID injected by the timing middleware.
    _session_id: str = (
        http_request.headers.get("X-Session-ID", "")
        or http_request.headers.get("X-Request-ID", "")
        or getattr(getattr(http_request, "state", None), "request_id", "")
        or ""
    )

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
                # company_name is blank — extract from question using entity detection.
                # detect_company is fast (regex + alias lookup) and safe to call sync.
                try:
                    from .services.company_detection import detect_company as _detect_co
                    _co = _detect_co(request.question)
                    _pre_dispatch_ticker = _co.ticker if _co else None
                except Exception:
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

        fut = loop.run_in_executor(None, route_question, _request)

        # Emit keepalive bytes every 25 s while pipeline runs.
        # asyncio.wait_for + asyncio.shield: times out without cancelling fut.
        # Each yielded byte resets Nginx's proxy_read_timeout clock.
        while not fut.done():
            try:
                await _asyncio.wait_for(
                    _asyncio.shield(fut), timeout=_KEEPALIVE_INTERVAL_S
                )
                # Future completed within the window — exit the keepalive loop.
                break
            except _asyncio.TimeoutError:
                yield b"\r\n"  # keepalive: reset Nginx proxy_read_timeout

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
                    _9f_fp = _build_fp(
                        question=request.question,
                        thesis_dict=_9f_thesis,
                        ticker=_9f_ticker,
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
            try:
                if _5c_cohort is not None:
                    import re as _re_5c
                    from .services import dossier_canary_telemetry as _can_tel_out

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
                        _5c_fallback     = (
                            isinstance(_5c_thesis_out.get("confidence_score"), float)
                            and _5c_thesis_out.get("confidence_score") == 0.0
                            and "unavailable" in _5c_conclusion.lower()
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
            except Exception as _5c_out_exc:
                logger.debug("[ask] 5C outcome recording failed (non-fatal): %r", _5c_out_exc)

            yield _json.dumps(_result_dict).encode()
        except Exception as exc:
            logger.warning("[ask] route_question raised: %r", exc)
            yield _json.dumps({"error": "Question routing failed"}).encode()

    # X-Accel-Buffering: no — instructs Render/Nginx to disable response
    # buffering and forward each chunk immediately.  Without this, Nginx
    # accumulates all chunks before forwarding; keepalive bytes reach Nginx
    # (resetting the timer) but are never flushed to the client until the
    # full response is ready, making them invisible to monitoring and
    # causing intermittent failures when the buffer flush races with the
    # 60-second proxy_read_timeout window.
    return StreamingResponse(
        _generate(),
        media_type="application/json",
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
async def get_watchlist() -> list:
    """Return all watchlist entries sorted by most-recently-added."""
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
) -> dict:
    """Add *ticker* to the watchlist.  Idempotent — safe to call multiple times."""
    entry = watchlist_service.add_ticker(ticker, company_name)
    return entry.model_dump()


@router.delete(
    "/watchlist/{ticker}",
    response_model=dict,
    summary="Remove a ticker from the watchlist",
    tags=["watchlist"],
)
async def remove_from_watchlist(ticker: str) -> dict:
    """Remove *ticker* from the watchlist.  Returns {removed: bool}."""
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
async def get_usage_stats() -> dict:
    """Return aggregate usage statistics."""
    from .services.usage_tracking import usage_tracker
    return usage_tracker.get_totals()


# ── Live Market Intelligence (Phase L) ───────────────────────────────────────

@router.post("/events/ingest", tags=["events"])
async def ingest_event(event_data: dict) -> dict:
    """
    Ingest a normalized event and return impact assessments for all relevant tickers.
    Accepts NormalizedEvent-compatible dict.
    """
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
        description="Comma-separated ticker list from frontend localStorage (fallback when backend list is empty)",
    ),
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
      tickers: comma-separated list of tickers from the frontend watchlist store.
               Used as fallback when the backend has no registered entries (e.g., fresh
               server start). The backend will auto-register them and generate a brief.
      reference_date: ISO date string for the brief header (defaults to today UTC).
    """
    try:
        from .services.watchlist_service import watchlist_service
        from .services.market_regime_tracker import get_current_regime
        from .services.thesis_impact_evaluator import get_default_evaluator
        from .services.morning_brief_service import generate_morning_brief_v2
        from .services.timeline_store import default_store
        from .schemas import EventImpactAssessment, WatchlistEntry as WLEntry

        # Fetch watchlist state (sync method — get_watchlist returns List[WatchlistEntry])
        watchlist_entries = watchlist_service.get_watchlist()

        # Fallback: if backend has no entries but frontend sent tickers, register them
        if not watchlist_entries and tickers:
            frontend_tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            for ticker_sym in frontend_tickers[:20]:  # cap at 20
                try:
                    watchlist_service.add_ticker(ticker_sym, ticker_sym)
                except Exception:
                    pass
            watchlist_entries = watchlist_service.get_watchlist()

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

        brief = generate_morning_brief_v2(
            watchlist_entries=watchlist_entries,
            event_impacts=all_impacts,
            watchlist_drift=drift,
            regime=regime,
            reference_date=reference_date,
        )
        return brief.model_dump()
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
