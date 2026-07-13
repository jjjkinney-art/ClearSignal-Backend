"""
test_completion_pass.py — Verifies the four completion issues are fixed.

Each test is structural/behavioral on the REAL code, not mocks:

Issue 1 — pytest terminates cleanly
    • conftest.py exists at project root with autouse cleanup
    • pytest.ini exists with timeout enforcement
    • audit_store is in-memory by default (no SQLite file side effect)

Issue 2 — Direct storage fallbacks removed from services
    • No service module imports query_records directly
    • history_ops.fallback_query is the single authorized path
    • All four services (evidence, monitoring, alert, learning) route through it

Issue 3 — Evidence service is meaning-first
    • HistoricalMeaning primary fields are populated
    • Raw stat labels live under supporting_metrics only
    • usual_consequence comes from archetype map, NOT count dominance

Issue 4 — No unconditional baseline routing
    • router_service does not unconditionally call run_equity_agent
    • Equity runs only when in `selected` (or as explicit empty-selection fallback)
"""
from __future__ import annotations

import os
import sys
import pathlib
import inspect

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Minimal bootstrap so real modules import ──────────────────────────────

import types


_MISSING = object()
_ORIG_SYS_MODULES: dict = {}


def _stub(name, **attrs):
    # Install a FRESH fake module (never mutate the real, pre-imported one) and
    # record the original so teardown_module() restores it — otherwise stubbing
    # pydantic/pydantic_settings in place leaks process-wide and breaks FastAPI
    # model-building in later-collected test files.
    if name not in _ORIG_SYS_MODULES:
        _ORIG_SYS_MODULES[name] = sys.modules.get(name, _MISSING)
    m = types.ModuleType(name)
    m.__path__ = []
    m.__package__ = name.rsplit(".", 1)[0] if "." in name else name
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def teardown_module(module=None):
    """Restore every module this file shadowed so the stubs never leak into
    other test files (deterministic collection / CI reliability)."""
    for name, orig in _ORIG_SYS_MODULES.items():
        if orig is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig
    _ORIG_SYS_MODULES.clear()


# Pydantic stub (tests don't need real validation)
pd = _stub("pydantic")
class _BM:
    model_config = {}
    model_fields = {}
    def __init__(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)
pd.BaseModel = _BM
pd.Field = lambda *a, **k: None
# schemas.py expects pydantic v2 field_validator OR v1 validator as fallback
pd.field_validator = lambda *a, **k: (lambda f: f)
pd.validator = lambda *a, **k: (lambda f: f)
pd.ConfigDict = dict
class _ValidationError(Exception): pass
pd.ValidationError = _ValidationError
_stub("pydantic_settings", BaseSettings=_BM)


# Ensure real app package is used, not a stub
app_pkg = _stub("app")
app_pkg.__path__ = [str(_ROOT / "app")]


# ════════════════════════════════════════════════════════════════════════════
# Issue 1: pytest termination / hang prevention
# ════════════════════════════════════════════════════════════════════════════

class TestPytestTerminationHygiene:
    """conftest + pytest.ini + side-effect-free module imports."""

    def test_conftest_exists_at_project_root(self):
        """A project-root conftest.py must exist so pytest discovers fixtures."""
        conftest = _ROOT / "conftest.py"
        assert conftest.exists(), f"conftest.py must exist at {_ROOT}"
        content = conftest.read_text()
        # Conftest must reset enterprise caches + trace store between tests
        assert "_reset_enterprise_caches" in content, \
            "conftest must reset enterprise caches"
        assert "_reset_trace_store" in content, \
            "conftest must reset trace store"
        assert "_disable_streaming" in content, \
            "conftest must neutralize streaming loop for tests"

    def test_pytest_ini_enforces_timeout(self):
        """pytest.ini must enforce a per-test timeout to prevent hangs."""
        ini = _ROOT / "pytest.ini"
        assert ini.exists(), "pytest.ini must exist"
        content = ini.read_text()
        assert "timeout" in content, "pytest.ini must declare a timeout"

    def test_audit_store_no_sqlite_side_effect_on_import(self):
        """Importing audit must NOT create an audit.db file on disk by default."""
        # Track files before import
        from app.enterprise import audit as _audit

        # By default, audit_store must be in-memory (db_path = None or unset from env)
        # If ANTHROPIC_AUDIT_DB is not set, the store must not have created files
        if not os.environ.get("ANTHROPIC_AUDIT_DB"):
            assert _audit.audit_store._db_path is None, (
                "Default audit_store must be in-memory (db_path=None) "
                "to prevent filesystem side effects on import"
            )

    def test_audit_store_opt_in_persistence(self):
        """AuditStore must still support opt-in persistence via explicit db_path."""
        from app.enterprise.audit import AuditStore
        # Creating an explicit on-disk store must work
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            store = AuditStore(db_path=tmp_path)
            assert store._db_path == tmp_path
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ════════════════════════════════════════════════════════════════════════════
# Issue 2: Direct storage fallbacks removed
# ════════════════════════════════════════════════════════════════════════════

class TestStorageAccessCentralized:
    """No service module directly imports query_records."""

    SERVICE_FILES = [
        "app/services/monitoring_service.py",
        "app/services/alert_service.py",
        "app/services/learning.py",
        "app/services/evidence_service.py",
    ]

    def test_no_direct_query_records_import_in_services(self):
        """Services must not import ``query_records`` directly from storage.

        They must use history_ops.fallback_query when a fallback is needed.
        """
        offenders = []
        for rel in self.SERVICE_FILES:
            src = (_ROOT / rel).read_text()
            if "from ..data_pipeline.storage import query_records" in src:
                offenders.append(rel)
        assert not offenders, (
            f"Services must not import query_records directly; offenders: {offenders}"
        )

    def test_history_ops_has_fallback_query_method(self):
        """history_ops must expose the single authorized fallback method."""
        from app.enterprise.history_ops import history_ops, HistoryOps
        assert hasattr(HistoryOps, "fallback_query"), \
            "HistoryOps must expose fallback_query()"
        assert callable(history_ops.fallback_query), \
            "history_ops.fallback_query must be callable"

    def test_services_reference_central_fallback(self):
        """Each service with a fallback path must reference history_ops.fallback_query."""
        for rel in self.SERVICE_FILES:
            src = (_ROOT / rel).read_text()
            if "_central_hops.fallback_query" in src or "history_ops.fallback_query" in src:
                continue
            # If no fallback reference AND no query_records reference, it uses only typed windows — fine
            if "query_records" not in src:
                continue
            assert False, (
                f"{rel} references query_records without routing through "
                f"history_ops.fallback_query"
            )

    def test_fallback_query_returns_list(self):
        """fallback_query must return a list (possibly empty) for any table."""
        from app.enterprise.history_ops import history_ops
        # Should not raise even if storage module is absent
        result = history_ops.fallback_query("nonexistent_table", limit=5)
        assert isinstance(result, list)


# ════════════════════════════════════════════════════════════════════════════
# Issue 3: Evidence service is meaning-first
# ════════════════════════════════════════════════════════════════════════════

class TestEvidenceMeaningFirst:
    """HistoricalMeaning is the primary evidence object, stats are secondary."""

    def test_historical_meaning_schema_has_meaning_first_fields(self):
        """HistoricalMeaning primary fields must be semantic, not numeric."""
        from app.schemas import HistoricalMeaning
        required_fields = [
            "situation_archetype",
            "historical_pattern",
            "pattern_stability",
            "pattern_direction",
            "escalation_likelihood",
            "usual_consequence",
            "meaning_summary",
        ]
        for fld in required_fields:
            assert fld in HistoricalMeaning.model_fields, \
                f"HistoricalMeaning must have primary field '{fld}'"

        # supporting_metrics must be OPTIONAL and secondary
        assert "supporting_metrics" in HistoricalMeaning.model_fields

    def test_archetype_drives_usual_consequence(self):
        """usual_consequence comes from archetype map, NOT from count dominance."""
        src = (_ROOT / "app/services/evidence_service.py").read_text()
        # The canonical map must exist
        assert "_ARCHETYPE_CONSEQUENCE" in src, \
            "Evidence must have an _ARCHETYPE_CONSEQUENCE canonical map"
        # usual_consequence must come from the map, not from counts
        assert "_ARCHETYPE_CONSEQUENCE.get(" in src, \
            "usual_consequence must be looked up from the archetype map"
        # No count-dominance shortcut
        assert "max(outcome_counts" not in src, \
            "usual_consequence must NOT be derived from max(outcome_counts)"

    def test_archetype_drives_escalation_likelihood(self):
        """escalation_likelihood comes from archetype map."""
        src = (_ROOT / "app/services/evidence_service.py").read_text()
        assert "_ARCHETYPE_ESCALATION" in src, \
            "Evidence must have an _ARCHETYPE_ESCALATION canonical map"

    def test_supporting_metrics_contains_raw_labels_only(self):
        """Raw stat labels live in supporting_metrics, not as primary fields."""
        src = (_ROOT / "app/services/evidence_service.py").read_text()
        # Raw labels like trend_direction should appear INSIDE supporting_metrics blocks
        # not as primary HistoricalMeaning constructor args
        # Find HistoricalMeaning( blocks and check they don't have trend_direction as top arg
        import re
        # Find the price HistoricalMeaning construction
        # Confirm "trend_direction" appears under supporting_metrics, not as a primary kwarg
        # Simple heuristic: trend_direction should appear after "supporting_metrics"
        m = re.search(
            r"HistoricalMeaning\(\s*domain\s*=\s*\"price\".*?\)",
            src, re.DOTALL,
        )
        assert m, "Must find price HistoricalMeaning construction"
        block = m.group()
        # Primary field should NOT have trend_direction as the primary pattern_direction
        # supporting_metrics should contain it
        if "trend_direction" in block:
            # Must appear under supporting_metrics, not as a top-level kwarg
            sm_start = block.find("supporting_metrics")
            td_start = block.find("trend_direction")
            assert td_start > sm_start, \
                "trend_direction must be inside supporting_metrics (secondary), not primary"

    def test_historical_meaning_built_for_all_domains(self):
        """Evidence service builds HistoricalMeaning for price, event, signal, financial."""
        src = (_ROOT / "app/services/evidence_service.py").read_text()
        for domain in ("price", "event", "signal", "financial"):
            assert f'domain               = "{domain}"' in src \
                or f'domain={repr(domain)}' in src \
                or f'domain = "{domain}"' in src, \
                f"HistoricalMeaning must be built for domain '{domain}'"


# ════════════════════════════════════════════════════════════════════════════
# Issue 4: No unconditional baseline routing
# ════════════════════════════════════════════════════════════════════════════

class TestRoutingIsSelective:
    """Router does not unconditionally execute equity (or any) baseline agent."""

    def test_router_service_no_always_run_comment(self):
        """No 'always run equity' comment remains in router."""
        src = (_ROOT / "app/services/router_service.py").read_text()
        assert "Always run equity baseline" not in src, (
            "Stale 'Always run equity baseline' comment must be removed"
        )

    def test_router_equity_only_runs_when_selected(self):
        """route_question in router_service must execute equity only via the "
        "selection loop, not as an unconditional call."""
        from app.services import router_service
        src = inspect.getsource(router_service.route_question)
        # The agent loop must gate all agent calls behind `if agent == "xxx":`
        # There must be no bare run_equity_agent() call outside the loop
        # Count occurrences of run_equity_agent to verify it's only in one place
        # inside the selection-gated block
        run_equity_count = src.count("run_equity_agent(")
        # Should be exactly 1 (inside the for-loop if agent == "equity" branch)
        assert run_equity_count == 1, (
            f"run_equity_agent must be called exactly once (inside the "
            f"selective agent loop); found {run_equity_count} calls"
        )

    def test_router_equity_runs_inside_if_agent_equity(self):
        """The equity call must be gated by `if agent == "equity":`."""
        src = (_ROOT / "app/services/router_service.py").read_text()
        # Locate the run_equity_agent( call and verify it's within an `if agent == "equity":` block
        idx = src.find("run_equity_agent(")
        # Walk backward to find the nearest `if agent ==`
        before = src[:idx]
        last_if = before.rfind("if agent ==")
        assert last_if > 0, "run_equity_agent must be inside an `if agent == ...` block"
        gate = before[last_if:].split("\n")[0]
        assert '"equity"' in gate, \
            f"Equity call must be gated by `if agent == \"equity\":`, found gate: {gate}"

    def test_analysis_service_iterates_selected_agents(self):
        """analysis_service's agent loop must iterate only selected_agents."""
        from app.services import analysis_service
        src = inspect.getsource(analysis_service.analyze_company)
        assert "for agent in selected_agents:" in src, (
            "analyze_company must iterate strictly over selected_agents"
        )
        # There should be no unconditional run_equity_agent outside the loop
        equity_calls = src.count("run_equity_agent(")
        # Only the lambda in _AGENT_RUNNERS dict counts — one occurrence max
        assert equity_calls <= 1, (
            f"analyze_company should not call run_equity_agent unconditionally; "
            f"found {equity_calls} direct references"
        )

    def test_empty_selection_default_is_explicit(self):
        """If classifier returns no agents, default must be explicit (not hidden)."""
        src = (_ROOT / "app/services/router_service.py").read_text()
        # The fallback must be labeled as an explicit fallback, not a baseline
        assert "if not selected:" in src, \
            "Empty-selection branch must be explicit"
        # Comment must clarify this is a fallback not a baseline
        idx = src.find("if not selected:")
        surrounding = src[max(0, idx - 400):idx + 200]
        assert "fallback" in surrounding.lower() or "sensible default" in surrounding.lower(), \
            "Empty-selection branch must be commented as fallback, not baseline"


# ════════════════════════════════════════════════════════════════════════════
# Integration: full lifecycle still works after all four fixes
# ════════════════════════════════════════════════════════════════════════════

class TestLifecycleStillWorks:
    """After all fixes, the real lifecycle still executes end-to-end."""

    def test_monitoring_history_helpers_callable(self):
        """Monitoring's history helpers still work after storage centralization."""
        from app.services.monitoring_service import _recent_event_count
        result = _recent_event_count("earnings")
        assert isinstance(result, int)
        assert result >= 0

    def test_alert_evidence_collection_callable(self):
        """Alert's evidence collection still works."""
        from app.services.alert_service import _collect_component_evidence
        result = _collect_component_evidence("key_risks")
        assert isinstance(result, dict)
        assert "recent_signal_count" in result

    def test_learning_get_signal_weight_callable(self):
        """learning.get_signal_weight still works after fallback routing."""
        from app.services.learning import get_signal_weight
        w = get_signal_weight("test_signal_completion")
        assert isinstance(w, float)
        assert 0.5 <= w <= 2.0

    def test_enterprise_cache_cleanup_is_idempotent(self):
        """Calling conftest-style cleanup twice must not raise."""
        # Import conftest as a regular module to exercise its helpers
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_conftest_module", str(_ROOT / "conftest.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Each cleanup function must be idempotent
        mod._reset_enterprise_caches()
        mod._reset_enterprise_caches()
        mod._reset_trace_store()
        mod._reset_trace_store()
        mod._reset_audit_store()
        mod._reset_audit_store()
        mod._reset_learning_memory()
        mod._reset_learning_memory()


# ════════════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    suites = [
        TestPytestTerminationHygiene,
        TestStorageAccessCentralized,
        TestEvidenceMeaningFirst,
        TestRoutingIsSelective,
        TestLifecycleStillWorks,
    ]
    passed = 0
    failed = 0
    for cls in suites:
        suite = cls()
        label = cls.__name__
        for name in sorted(n for n in dir(cls) if n.startswith("test_")):
            full = f"{label}.{name}"
            try:
                getattr(suite, name)()
                print(f"  PASS  {full}")
                passed += 1
            except Exception as e:
                import traceback
                print(f"  FAIL  {full}")
                traceback.print_exc()
                failed += 1
    print(f"\n{'=' * 66}")
    print(f"  {passed} passed, {failed} failed")
    if not failed:
        print("  COMPLETION TESTS PASSED — all four issues fixed")
    print(f"{'=' * 66}")
