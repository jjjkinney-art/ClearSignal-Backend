"""
Startup diagnostics for the AI analyst backend.

This module contains only stdlib imports so it can be safely imported by
tests on Python 3.9 without pulling in api.py (which uses 3.10+ union-type
syntax ``list | dict`` in annotations).

Phase 6: Added hard matrix-system assertions.  If the matrix architecture is
not loaded, the server REFUSES to start with a RuntimeError rather than silently
serving stale speculative labels for durable compounders.

Phase 6.1: Added [MATRIX_RUNTIME_LOADED] fingerprint log + importlib.reload()
to force the live process to pick up the newest conviction_modeler.py bytes,
not a cached pre-matrix version held in sys.modules.

Phase 10A · Slice 1: Continuous Intelligence Loop schema registered.
Migration: app/db/migrations/005_continuous_loop.sql (5 new tables → db_table_count 19→24).
Tables: scheduled_jobs, job_locks, job_runs, delivery_ledger, notifications.
All loop flags default to off (loop_enabled=False); loop is inert until Slice 4.
Phase 10B · Slice 2: DB Watchlist Membership schema registered.
Migration: app/db/migrations/006_watchlist_membership.sql (1 new table → db_table_count 24→25).
Table: watched_tickers. Backfilled from .clearSignal_watchlist/index.json at startup.
Phase 10C · Slice 2: Delivery Preferences schema registered.
Migration: app/db/migrations/007_briefing_delivery.sql (3 new tables → db_table_count 25→28).
Tables: user_delivery_prefs, digest_batches, delivery_ledger_archive; plus two
additive nullable columns on delivery_ledger (canonical_severity, severity_rank).
Additive and inert — no delivery behavior changes until later 10C slices.
Phase 10D · Slice 1: Portfolio Intelligence schema registered.
Migration: app/db/migrations/008_portfolio_intelligence.sql (3 new tables → db_table_count 28→31).
Tables: portfolios, portfolio_positions, portfolio_insights.
Additive and inert — no analytical or delivery behavior changes until later 10D slices.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
import time


# ── Process start timestamp (module-level — set once on import) ───────────────
_PROCESS_START_EPOCH: float = time.time()


def _conviction_modeler_checksum() -> str:
    """Return the first 16 chars of the MD5 digest of conviction_modeler.py.

    Used to prove which *file bytes* the live process loaded.  If Render has
    deployed a new file but the Python runtime cached the old module, the
    checksum will still reflect the new file bytes on disk — so a mismatch
    between the disk checksum and the module constants is a clear cache-hit
    signal that importlib.reload() must fire.
    """
    cm_path = os.path.join(
        os.path.dirname(__file__), "services", "conviction_modeler.py"
    )
    try:
        with open(cm_path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:16]
    except OSError:
        return "FILE_NOT_FOUND"


def _force_reload_conviction_modeler() -> None:
    """Force a live reimport of conviction_modeler from disk.

    Render (and uvicorn with --reload=False) may cache the pre-matrix module
    in sys.modules after the first import.  Calling importlib.reload() forces
    Python to re-execute the module file from disk, picking up any changes
    that landed in a new deploy without a full worker restart.

    Safe to call multiple times — reload() is idempotent.
    Called once from print_startup_diagnostics() before _check_matrix_system().
    """
    mod_name = "app.services.conviction_modeler"
    if mod_name in sys.modules:
        try:
            importlib.reload(sys.modules[mod_name])
            print(f"[STARTUP] importlib.reload({mod_name}) — forced disk re-read  ✓")
        except Exception as exc:
            # Non-fatal: log and continue.  The hard matrix assertion below
            # will catch any resulting breakage.
            print(
                f"[STARTUP] WARNING: reload({mod_name}) raised {type(exc).__name__}: {exc} "
                "— proceeding with cached module",
                file=sys.stderr,
            )
    else:
        print(f"[STARTUP] {mod_name} not yet in sys.modules — first import will read from disk")


def _check_matrix_system() -> dict:
    """Import conviction modeler and verify matrix architecture is loaded.

    Returns a dict of version/status fields for use by /debug/version and
    /api/version.

    Raises RuntimeError if ARCHETYPE_MATRIX_ENABLED is False or absent —
    this indicates the live process loaded a stale pre-matrix conviction_modeler.
    """
    try:
        from app.services.conviction_modeler import (  # type: ignore[import]
            CONVICTION_SCHEMA_VERSION,
            ARCHETYPE_MATRIX_ENABLED,
            _DURABILITY_MATRIX_HIGH,
            _DURABILITY_MATRIX_MID,
            _durability_matrix_label,
            _compute_expectation_risk,
        )
    except ImportError as exc:
        raise RuntimeError(
            "[MATRIX_SYSTEM_MISSING] Failed to import matrix architecture from "
            "conviction_modeler.  The live process is running stale code that "
            "predates the Phase 6 matrix refactor.  "
            f"ImportError: {exc}"
        ) from exc

    if not ARCHETYPE_MATRIX_ENABLED:
        raise RuntimeError(
            "[MATRIX_SYSTEM_DISABLED] ARCHETYPE_MATRIX_ENABLED=False in "
            "conviction_modeler.  The matrix architecture must always be enabled "
            "in production.  Check that conviction_modeler.py was saved correctly."
        )

    # Smoke-test: a durable compounder must NEVER produce 'speculative setup'
    _smoke_exp_risk = round(0.70 * 0.42 + 0.30 * 0.28, 4)   # 0.378
    _smoke_label    = _durability_matrix_label(0.71, _smoke_exp_risk)
    if _smoke_label in ("speculative setup", "insufficient conviction"):
        raise RuntimeError(
            f"[MATRIX_SMOKE_FAIL] Durable compounder (durability=0.71) produced "
            f"label={_smoke_label!r}. Matrix logic is broken — "
            "refusing to start to prevent serving invalid classifications."
        )

    return {
        "conviction_schema_version": CONVICTION_SCHEMA_VERSION,
        "archetype_matrix_enabled":  ARCHETYPE_MATRIX_ENABLED,
        "durability_matrix_high":    _DURABILITY_MATRIX_HIGH,
        "durability_matrix_mid":     _DURABILITY_MATRIX_MID,
        "matrix_smoke_label":        _smoke_label,
        "conviction_modeler_checksum": _conviction_modeler_checksum(),
    }


def print_startup_diagnostics() -> None:
    """Print key-presence diagnostics to stdout at server startup.

    Phase 6: Also asserts the matrix conviction architecture is loaded.
    Phase 6.1: Forces importlib.reload() of conviction_modeler before the
               assertion, then emits [MATRIX_RUNTIME_LOADED] with file checksum.

    Raises RuntimeError (caught by uvicorn/gunicorn and surfaced as a crash)
    if the matrix system is not present — prevents silent stale-code deployments.
    """
    fred_key   = os.environ.get("FRED_API_KEY",   "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    git_commit = (
        os.environ.get("RENDER_GIT_COMMIT", "")[:12]
        or os.environ.get("GIT_COMMIT", "")[:12]
        or "unknown"
    )
    port           = os.environ.get("PORT", "8000")
    service_id     = os.environ.get("RENDER_SERVICE_ID", "local")
    service_name   = os.environ.get("RENDER_SERVICE_NAME", "local")
    environment    = "production" if os.environ.get("RENDER_SERVICE_ID") else "development"

    print("=" * 60)
    print("[STARTUP] ClearSignal AI Backend — boot sequence")
    print("[STARTUP] DB schema:              006_watchlist_membership (db_table_count 24→25)")
    print(f"[STARTUP] Service:                {service_name} ({service_id})")
    print(f"[STARTUP] Environment:            {environment}")
    print(f"[STARTUP] Port:                   {port}")
    print(f"[STARTUP] GIT_COMMIT:             {git_commit}")
    print(f"[STARTUP] Health endpoints:       GET /, GET /health, GET /healthz")
    print(f"[STARTUP] FRED_API_KEY present:   {bool(fred_key)}  (len={len(fred_key)})")
    print(f"[STARTUP] OPENAI_API_KEY present: {bool(openai_key)}  (len={len(openai_key)})")

    if not fred_key:
        print(
            "[STARTUP] WARNING: FRED_API_KEY not set — live macro evidence will be "
            "skipped and all answers will fall back to conceptual reasoning."
        )
    if not openai_key:
        print(
            "[STARTUP] CRITICAL: OPENAI_API_KEY not set — the ModelClient has no "
            "OpenAI connection.  Every call to /api/ask will raise RuntimeError "
            "until OPENAI_API_KEY is added to the environment."
        )

    # ── Phase 6.1: Force fresh module load from disk ───────────────────────────
    # This runs BEFORE the matrix assertion so the assertion sees the newest
    # bytes, not a cached pre-matrix module from sys.modules.
    print("[STARTUP] Forcing conviction_modeler reload from disk...")
    _force_reload_conviction_modeler()

    # ── Phase 6.1: File checksum (disk bytes — independent of sys.modules) ─────
    _disk_checksum = _conviction_modeler_checksum()
    print(f"[MATRIX_RUNTIME_LOADED] conviction_modeler.py disk_md5={_disk_checksum}")

    # ── Phase 6: Matrix system assertion ──────────────────────────────────────
    print("[STARTUP] Verifying matrix conviction architecture...")
    try:
        matrix_info = _check_matrix_system()
        print(f"[MATRIX_RUNTIME_LOADED] schema={matrix_info['conviction_schema_version']}  "
              f"matrix_enabled={matrix_info['archetype_matrix_enabled']}  "
              f"file_md5={matrix_info['conviction_modeler_checksum']}  "
              f"smoke_label={matrix_info['matrix_smoke_label']!r}")
        print(f"[MATRIX_SYSTEM_ACTIVE]   conviction_schema={matrix_info['conviction_schema_version']}")
        print(f"[MATRIX_VERSION]         schema={matrix_info['conviction_schema_version']}")
        print(f"[ARCHETYPE_MATRIX_ENABLED] enabled={matrix_info['archetype_matrix_enabled']}")
        print(f"[MATRIX_THRESHOLDS]      high={matrix_info['durability_matrix_high']} mid={matrix_info['durability_matrix_mid']}")
        print(f"[MATRIX_SMOKE_TEST]      durable_label={matrix_info['matrix_smoke_label']!r}  ✓")
        print(f"[MATRIX_FILE_CHECKSUM]   md5(conviction_modeler.py)={matrix_info['conviction_modeler_checksum']}")
    except RuntimeError as exc:
        print(f"[STARTUP] FATAL: {exc}", file=sys.stderr)
        # Re-raise — gunicorn/uvicorn will log this as a worker crash.
        # Render will mark the deploy as failed rather than serving stale code.
        raise

    print("=" * 60)
