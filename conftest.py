"""
Project-wide pytest configuration — self-contained, no plugin deps required.

Key guarantees:
1. Streaming module is neutered at IMPORT time (not fixture), so any test
   that touches it cannot spawn an infinite loop
2. Autouse fixture resets enterprise caches/traces/audit between tests
3. A built-in thread-based per-test timeout kicks in even without pytest-timeout
4. Any non-daemon threads surviving a test are logged (warning only)
"""
from __future__ import annotations

import os
import sys
import threading
import warnings
from typing import Iterator, Optional

# ── Project root on sys.path ──────────────────────────────────────────────
_ROOT = os.path.abspath(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Neuter streaming AT IMPORT TIME ──────────────────────────────────────
# _disable_streaming: sentinel checked by test_completion_pass hygiene test.
_disable_streaming = True
try:
    from app.data_pipeline import streaming as _streaming_mod

    async def _noop_coro(*args, **kwargs):
        return None

    _streaming_mod.start_streaming    = _noop_coro
    _streaming_mod._stream_for_symbol = _noop_coro
except Exception:
    pass


# ── Neuter LLM model client AT IMPORT TIME ───────────────────────────────
# Prevents real OpenAI API calls (which time out after ~10s each) in tests
# that exercise analysis_service without fully stubbing app.model_client.
if not os.environ.get("ANTHROPIC_TEST_ALLOW_NETWORK"):
    try:
        from app.model_client import model_client as _model_client
        _model_client.call = lambda *a, **kw: '{"stub": true}'
    except Exception:
        pass


# ── Save real schema classes before test collection stubs corrupt them ────
# Multiple test files overwrite app.schemas classes at collection time.
# We save all real classes here (conftest imports before any test file) so
# the autouse fixture can restore them before each test that needs them.
_real_schema_attrs: dict = {}
try:
    import app.schemas as _app_schemas_mod
    _real_schema_attrs = {k: v for k, v in vars(_app_schemas_mod).items()
                          if isinstance(v, type)}
except Exception:
    pass
# Keep backwards-compat alias used by autouse fixture below
_real_HistoricalMeaning = _real_schema_attrs.get("HistoricalMeaning")


# ── Save real app.config Settings and settings before stubs replace them ─────
# test_enterprise.py, test_enterprise_integration.py, and test_final_lifecycle.py
# all replace app.config.Settings and app.config.settings at collection time with
# stub classes that have different attributes (e.g. enterprise_mode=True).
# We save the originals here and restore them in the autouse fixture.
_real_config_Settings = None
_real_config_settings = None
try:
    import app.config as _config_mod
    _real_config_Settings = getattr(_config_mod, "Settings", None)
    _real_config_settings = getattr(_config_mod, "settings", None)
except Exception:
    pass


# ── Neuter network-bound provider functions AT IMPORT TIME ───────────────
# Tests should never make real HTTP calls to FMP, SEC, or other providers.
# Each requests.get(timeout=10) call can hang pytest for up to 10s in
# environments without DNS or with stalled connections.  Replace these
# functions with empty-result stubs unless a test explicitly opts in by
# setting ANTHROPIC_TEST_ALLOW_NETWORK=1 in the environment.
if not os.environ.get("ANTHROPIC_TEST_ALLOW_NETWORK"):
    def _empty_dict(*a, **kw): return {}
    def _empty_list(*a, **kw): return []

    try:
        from app.providers import fmp_client as _fmp
        _fmp.get_company_profile   = _empty_dict
        _fmp.get_market_snapshot   = _empty_dict
        _fmp.get_financial_context = _empty_dict
        _fmp.get_recent_news       = _empty_list
    except Exception:
        pass

    try:
        from app.providers import sec_client as _sec
        _sec.get_recent_filings = _empty_list
        _sec.get_company_facts  = _empty_dict
    except Exception:
        pass

    try:
        from app.providers import retrieval_provider as _ret
        _ret.get_public_context   = _empty_list
        _ret.get_document_context = _empty_list
    except Exception:
        pass

    try:
        from app.services import data_providers as _dp
        _dp.fetch_fmp_financials = _empty_dict
        _dp.fetch_sec_filings    = _empty_dict
    except Exception:
        pass


# ── Preserve real ingestion functions before test collection stubs replace them ──
# test_runtime_behavior.py calls _stub("app.data_pipeline.ingestion", ...) at
# module import time which replaces ingest_signals on the real module object.
# We save the originals here (conftest runs before any test file is collected)
# and restore them in the autouse fixture so later tests get the real functions.
_real_ingestion_funcs: dict = {}
try:
    import app.data_pipeline.ingestion as _ingestion_mod
    for _fn_name in ("ingest_signals", "ingest_price_history"):
        _fn = getattr(_ingestion_mod, _fn_name, None)
        if callable(_fn):
            _real_ingestion_funcs[_fn_name] = _fn
except Exception:
    pass


# ── Preserve real service functions that stub files replace on the real module ──
# test_enterprise_integration.py does _stub("app.services.context_service") and then
# sets .enrich_grounding_context = _mock_enrich (a stub that ignores providers).
# We save the real function here and restore it in the autouse fixture.
_real_service_funcs: dict = {}  # maps (module_name, func_name) -> real_func
for _mod_name_fn, _fn_names in [
    ("app.services.context_service", ("enrich_grounding_context",)),
    ("app.services.prioritization_utils", ("rank_signals",)),
]:
    try:
        __import__(_mod_name_fn)
        _mf = sys.modules.get(_mod_name_fn)
        if _mf is not None:
            for _fn_name in _fn_names:
                _fn = getattr(_mf, _fn_name, None)
                if callable(_fn):
                    _real_service_funcs[(_mod_name_fn, _fn_name)] = _fn
    except Exception:
        pass


# ── Preserve real service modules before test collection _load() calls replace them ──
# test_history_inversion.py and test_meaning_native.py call _load("app.services.X", path)
# at module import time, which replaces the real module in sys.modules with a version
# loaded under a stub pydantic/schemas environment.  We save the originals here (conftest
# imports before any test file is collected) and restore them in the autouse fixture.
_real_service_modules: dict = {}
for _svc_name in (
    "app.services.monitoring_service",
    "app.services.alert_service",
    "app.services.learning",
):
    try:
        __import__(_svc_name)
        _svc_mod = sys.modules.get(_svc_name)
        if _svc_mod is not None:
            _real_service_modules[_svc_name] = _svc_mod
    except Exception:
        pass


# ── State-reset helpers ───────────────────────────────────────────────────

def _reset_enterprise_caches() -> None:
    try:
        from app.enterprise.cache import response_cache, history_cache
        response_cache.clear()
        history_cache.clear()
    except Exception:
        pass


def _reset_trace_store() -> None:
    try:
        from app.enterprise import observability
        with observability._store_lock:
            observability._trace_store.clear()
    except Exception:
        pass


def _reset_audit_store() -> None:
    try:
        from app.enterprise.audit import audit_store
        with audit_store._lock:
            audit_store._analyses.clear()
            audit_store._alerts.clear()
            audit_store._monitoring.clear()
    except Exception:
        pass


def _reset_learning_memory() -> None:
    try:
        from app.services import learning
        learning._signal_memory.clear()
        learning._signal_outcomes.clear()
        if hasattr(learning, "_signal_avg_scores"):
            learning._signal_avg_scores.clear()
    except Exception:
        pass


def _warn_non_daemon_threads() -> None:
    rogue = [
        t for t in threading.enumerate()
        if not t.daemon
        and t is not threading.main_thread()
        and t.is_alive()
    ]
    if rogue:
        warnings.warn(
            f"Test left non-daemon threads alive: {[t.name for t in rogue]}",
            RuntimeWarning,
        )


# ── Built-in watchdog (no plugin needed) ──────────────────────────────────

_PER_TEST_TIMEOUT_S = float(os.environ.get("PYTEST_TEST_TIMEOUT", "30"))
_watchdog_lock = threading.Lock()
_current_watchdog: Optional[threading.Timer] = None


def _start_test_watchdog(test_name: str = "") -> None:
    global _current_watchdog
    with _watchdog_lock:
        if _current_watchdog is not None:
            _current_watchdog.cancel()

        def _kill():
            sys.stderr.write(
                f"\n\nWATCHDOG: test '{test_name}' exceeded "
                f"{_PER_TEST_TIMEOUT_S}s — aborting process\n"
            )
            sys.stderr.flush()
            os._exit(124)

        _current_watchdog = threading.Timer(_PER_TEST_TIMEOUT_S, _kill)
        _current_watchdog.daemon = True
        _current_watchdog.start()


def _stop_test_watchdog() -> None:
    global _current_watchdog
    with _watchdog_lock:
        if _current_watchdog is not None:
            _current_watchdog.cancel()
            _current_watchdog = None


# ── pytest hooks ──────────────────────────────────────────────────────────

try:
    import pytest

    @pytest.fixture(autouse=True)
    def _clean_enterprise_state(request) -> Iterator[None]:
        _reset_enterprise_caches()
        _reset_trace_store()
        _reset_audit_store()
        _reset_learning_memory()

        # Restore real ingestion functions if test collection stubs replaced them.
        if _real_ingestion_funcs:
            try:
                import app.data_pipeline.ingestion as _ing
                for _fn_name, _fn in _real_ingestion_funcs.items():
                    if getattr(_ing, _fn_name, None) is not _fn:
                        setattr(_ing, _fn_name, _fn)
            except Exception:
                pass

        # Restore real service functions that test collection stubs replaced on the real module.
        # (e.g. test_enterprise_integration.py replaces context_service.enrich_grounding_context)
        if _real_service_funcs:
            for (_mod_name_fn, _fn_name), _fn in _real_service_funcs.items():
                try:
                    _mf = sys.modules.get(_mod_name_fn)
                    if _mf is not None and getattr(_mf, _fn_name, None) is not _fn:
                        setattr(_mf, _fn_name, _fn)
                except Exception:
                    pass

        # Restore real service modules if test collection _load() calls replaced them.
        # test_history_inversion.py and test_meaning_native.py call _load() which replaces
        # sys.modules entries for monitoring_service, alert_service, and learning with
        # stub-environment versions.  Restoring the real modules keeps later tests clean.
        #
        # IMPORTANT: Python's import machinery for `import a.b.c` reads the PARENT MODULE'S
        # ATTRIBUTE first (a.b.c attribute), not sys.modules["a.b.c"].  So we must update
        # BOTH sys.modules["a.b.c"] AND setattr(parent_mod, "c", real_mod) to ensure the
        # real module is found on the next `import app.services.X as _m` statement.
        if _real_service_modules:
            for _svc_name, _svc_mod in _real_service_modules.items():
                if sys.modules.get(_svc_name) is not _svc_mod:
                    sys.modules[_svc_name] = _svc_mod
                # Also fix parent module attribute
                _parts = _svc_name.rsplit(".", 1)
                if len(_parts) == 2:
                    _parent_name, _attr_name = _parts
                    _parent_mod = sys.modules.get(_parent_name)
                    if (_parent_mod is not None
                            and getattr(_parent_mod, _attr_name, None) is not _svc_mod):
                        try:
                            setattr(_parent_mod, _attr_name, _svc_mod)
                        except Exception:
                            pass

        # Re-clear learning memory NOW that the real service modules are restored.
        # The _reset_learning_memory() call at the top of this fixture runs before
        # service modules are restored, so it may clear the wrong (stub) module's
        # dicts.  Clearing again here ensures the real learning module is clean.
        _reset_learning_memory()

        # Restore real app.config.Settings and app.config.settings if stubs replaced them.
        # Multiple test files replace these at collection time, breaking later tests that
        # expect the real settings (e.g. test_backend.py tests that monkeypatch enable_data_retrieval).
        if _real_config_Settings is not None or _real_config_settings is not None:
            try:
                import app.config as _cfg
                if _real_config_Settings is not None:
                    if getattr(_cfg, "Settings", None) is not _real_config_Settings:
                        _cfg.Settings = _real_config_Settings
                if _real_config_settings is not None:
                    if getattr(_cfg, "settings", None) is not _real_config_settings:
                        _cfg.settings = _real_config_settings
                # Propagate to app.* modules that imported settings at module level
                for _mod_name, _mod in list(sys.modules.items()):
                    if not _mod_name.startswith("app.") or _mod is None:
                        continue
                    if _real_config_settings is not None:
                        existing = getattr(_mod, "settings", None)
                        if (existing is not None
                                and existing is not _real_config_settings
                                and not isinstance(existing, type)):
                            try:
                                setattr(_mod, "settings", _real_config_settings)
                            except Exception:
                                pass
            except Exception:
                pass

        # Restore all real schema classes if test collection stubs replaced them.
        # Propagate to app.* modules only — test files that deliberately use stub
        # schemas (test_enterprise_integration, test_final_lifecycle, etc.) must
        # not be touched or their own stubs break.
        if _real_schema_attrs:
            try:
                import app.schemas as _sm
                for _cls_name, _cls in _real_schema_attrs.items():
                    setattr(_sm, _cls_name, _cls)
                # Propagate restored classes to app.* service/provider modules
                for _mod_name, _mod in list(sys.modules.items()):
                    if not _mod_name.startswith("app."):
                        continue
                    if _mod is None or _mod is _sm:
                        continue
                    for _cls_name, _cls in _real_schema_attrs.items():
                        existing = getattr(_mod, _cls_name, None)
                        if (existing is not None
                                and existing is not _cls
                                and isinstance(existing, type)):
                            try:
                                setattr(_mod, _cls_name, _cls)
                            except Exception:
                                pass
            except Exception:
                pass

        test_name = getattr(request.node, "name", "<unknown>")
        _start_test_watchdog(test_name)
        try:
            yield
        finally:
            _stop_test_watchdog()
            _reset_enterprise_caches()
            _reset_trace_store()
            _reset_audit_store()
            _reset_learning_memory()
            _warn_non_daemon_threads()

    @pytest.fixture(autouse=True, scope="session")
    def _session_shutdown_hook() -> Iterator[None]:
        """Session-end hook: signal streaming stop and clean up any
        remaining background state.  Runs once after all tests complete."""
        yield
        # Signal any running streaming loops to exit
        try:
            from app.data_pipeline import streaming
            if hasattr(streaming, "stop_streaming"):
                streaming.stop_streaming()
        except Exception:
            pass
        # Cancel any leftover asyncio tasks if an event loop is running
        try:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
            except RuntimeError:
                # No running loop — nothing to clean
                pass
        except Exception:
            pass
        # Final thread audit
        _warn_non_daemon_threads()

except ImportError:
    pass
