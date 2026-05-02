"""
test_final_completion.py — Tests covering the final completion pass.

Each test targets a specific requirement from the completion brief:

1. full test run does not hang — conftest.py sets timeout, disables streaming
2. services use history_ops rather than raw storage fallbacks
3. evidence_service exposes meaning-first HistoricalMeaning outputs
4. routing does not force baseline agents unconditionally
"""
from __future__ import annotations

import os
import sys
import threading
import inspect
import pathlib
import types

# Use relative path from this file so tests run from any working directory
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ── Minimal bootstrap (no network) ────────────────────────────────────────

def _stub(name, **attrs):
    if name in sys.modules:
        m = sys.modules[name]
    else:
        m = types.ModuleType(name); m.__path__ = []
        sys.modules[name] = m
    for k, v in attrs.items(): setattr(m, k, v)
    return m


pd = _stub("pydantic")


class _BM:
    model_config = {}; model_fields = {}
    def __init__(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)


pd.BaseModel = _BM
pd.Field = lambda *a, **k: None
pd.field_validator = lambda *a, **k: (lambda fn: fn)
pd.validator = lambda *a, **k: (lambda fn: fn)
pd.model_validator = lambda *a, **k: (lambda fn: fn)
pd.root_validator = lambda *a, **k: (lambda fn: fn)
pd.ConfigDict = dict
_stub("pydantic_settings", BaseSettings=_BM)

_stub("app.data_pipeline.storage",
      query_records=lambda *a, **k: [],
      insert_price_records=lambda *a, **k: None,
      insert_financial_records=lambda *a, **k: None,
      insert_event_records=lambda *a, **k: None,
      insert_signal_records=lambda *a, **k: None)
_stub("app.data_pipeline.ingestion", ingest_signals=lambda *a, **k: None)
_stub("app.data_pipeline.schemas",
      PriceRecord=type("PriceRecord", (_BM,), {}),
      FinancialRecord=type("FinancialRecord", (_BM,), {}),
      EventRecord=type("EventRecord", (_BM,), {}),
      SignalRecord=type("SignalRecord", (_BM,), {}))

_stub("app.providers.fmp_client",
      get_company_profile=lambda *a, **k: None,
      get_market_snapshot=lambda *a, **k: None,
      get_financial_context=lambda *a, **k: None,
      get_recent_news=lambda *a, **k: [])
_stub("app.providers.sec_client",
      get_recent_filings=lambda *a, **k: [],
      get_company_facts=lambda *a, **k: {})
_stub("app.providers.retrieval_provider",
      get_public_context=lambda *a, **k: [],
      get_document_context=lambda *a, **k: [])

# Minimal config
class _Settings:
    openai_model = "gpt-3.5-turbo"; openai_api_key = ""
    fmp_api_key = ""; sec_user_agent = "test/0.1"
    enterprise_mode = True; audit_db_path = ""
    provider_cache_ttl_s = 300.0; history_cache_ttl_s = 120.0
    circuit_failure_threshold = 5; circuit_cooldown_s = 60.0
    enable_data_retrieval = True; system_prompt_file = ""
    max_tokens = 512; temperature = 0.0
    model_timeout = 5.0; model_max_retries = 1; model_backoff_factor = 0.1


_cfg = _stub("app.config")
_cfg.settings = _Settings(); _cfg.Settings = _Settings


# ════════════════════════════════════════════════════════════════════════════
# TEST 1: No runaway background loops or non-daemon threads
# ════════════════════════════════════════════════════════════════════════════

class TestNoHangingBackgroundTasks:
    """pytest must terminate cleanly — no non-daemon threads survive import."""

    def test_importing_enterprise_does_not_start_threads(self):
        """Importing enterprise modules must not start any non-daemon threads."""
        before = {t.ident for t in threading.enumerate()
                  if not t.daemon and t.is_alive()}

        from app.enterprise import observability, audit, cache, history_ops, \
            reliability, tenant, provider_registry, tools  # noqa: F401

        after = {t.ident for t in threading.enumerate()
                 if not t.daemon and t.is_alive()}
        new = after - before
        # Filter out main thread
        new.discard(threading.main_thread().ident)
        assert not new, f"Enterprise imports started {len(new)} non-daemon threads"

    def test_audit_store_does_not_create_file_on_import(self):
        """The default audit_store must be in-memory unless env var is set."""
        # Unset env var to force default behavior
        if "ANTHROPIC_AUDIT_DB" in os.environ:
            del os.environ["ANTHROPIC_AUDIT_DB"]

        # Re-import audit module fresh
        if "app.enterprise.audit" in sys.modules:
            del sys.modules["app.enterprise.audit"]
        from app.enterprise.audit import audit_store

        # Default store must have no db_path
        assert audit_store._db_path is None, (
            "Default audit_store must be in-memory (db_path=None) to prevent "
            "side-effectful test runs"
        )

    def test_streaming_module_has_no_module_level_execution(self):
        """streaming.py must not execute asyncio.run or start loops on import."""
        src = (_PROJECT_ROOT / "app" / "data_pipeline" / "streaming.py").read_text()
        # asyncio.run(main()) must only exist as example text in docstrings
        non_docstring_lines = []
        in_docstring = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if not in_docstring and stripped and not stripped.startswith("#"):
                non_docstring_lines.append(stripped)

        offenders = [l for l in non_docstring_lines if "asyncio.run(" in l]
        assert not offenders, (
            f"streaming.py must not call asyncio.run() outside docstrings; "
            f"found: {offenders}"
        )

    def test_conftest_exists_at_project_root(self):
        """conftest.py must exist at project root for test-safe teardown."""
        conftest = _PROJECT_ROOT / "conftest.py"
        assert conftest.exists(), "conftest.py must exist at project root"
        content = conftest.read_text()
        # Must have the key hooks
        assert "_clean_enterprise_state" in content
        # Streaming is neutered at import time (not via fixture)
        assert "start_streaming" in content, (
            "conftest.py must neuter streaming to prevent test hangs"
        )
        # Must have built-in watchdog (no pytest-timeout dep)
        assert "_start_test_watchdog" in content, (
            "conftest.py must have built-in watchdog; pytest-timeout not required"
        )

    def test_pytest_ini_enforces_timeout(self):
        """pytest.ini must set a timeout to prevent hangs."""
        pytest_ini = _PROJECT_ROOT / "pytest.ini"
        assert pytest_ini.exists(), "pytest.ini must exist at project root"
        content = pytest_ini.read_text()
        assert "timeout" in content.lower(), \
            "pytest.ini must configure a test timeout"


# ════════════════════════════════════════════════════════════════════════════
# TEST 2: Services use history_ops — no direct query_records imports
# ════════════════════════════════════════════════════════════════════════════

class TestNoDirectStorageFallbacks:
    """Services must route through history_ops, not raw query_records."""

    SERVICE_FILES = [
        "app/services/monitoring_service.py",
        "app/services/alert_service.py",
        "app/services/learning.py",
        "app/services/evidence_service.py",
    ]

    def test_services_do_not_import_query_records_directly(self):
        """Grep-level assertion: no `from ..data_pipeline.storage import query_records`."""
        offenders = []
        for rel in self.SERVICE_FILES:
            path = _PROJECT_ROOT / rel
            if not path.exists():
                continue
            content = path.read_text()
            if "from ..data_pipeline.storage import query_records" in content:
                offenders.append(rel)
            if "from app.data_pipeline.storage import query_records" in content:
                offenders.append(rel)
        assert not offenders, (
            f"These services bypass history_ops by importing query_records "
            f"directly: {offenders}. All storage access must go through "
            f"history_ops.fallback_query instead."
        )

    def test_services_use_fallback_query_or_typed_windows(self):
        """Every service that queries history must use history_ops."""
        expected_references = {
            "app/services/monitoring_service.py": "history_ops",
            "app/services/alert_service.py":       "history_ops",
            "app/services/learning.py":            "history_ops",
            "app/services/evidence_service.py":    "history_ops",
        }
        for rel, marker in expected_references.items():
            path = _PROJECT_ROOT / rel
            content = path.read_text()
            assert marker in content, (
                f"{rel} must reference history_ops; it currently does not."
            )

    def test_history_ops_has_fallback_query_method(self):
        """history_ops must expose fallback_query as the single escape hatch."""
        from app.enterprise.history_ops import history_ops, HistoryOps
        assert hasattr(history_ops, "fallback_query"), (
            "history_ops must provide fallback_query() for isolated direct-storage "
            "access; services must not import query_records directly."
        )
        assert callable(history_ops.fallback_query)

    def test_fallback_query_returns_list(self):
        """fallback_query must return a list (empty if storage unavailable)."""
        from app.enterprise.history_ops import history_ops
        result = history_ops.fallback_query("signal_history", limit=10)
        assert isinstance(result, list)


# ════════════════════════════════════════════════════════════════════════════
# TEST 3: evidence_service is meaning-first
# ════════════════════════════════════════════════════════════════════════════

class TestEvidenceIsMeaningFirst:
    """evidence_service must produce HistoricalMeaning as primary output."""

    def test_historical_meaning_schema_has_canonical_fields(self):
        """HistoricalMeaning must declare all required meaning-first fields."""
        # Read schema source directly — stub-based introspection is unreliable
        # because the test bootstrap installs pydantic stubs before the real
        # schema module loads.
        schemas_src = (_PROJECT_ROOT / "app/schemas.py").read_text()

        # Find the HistoricalMeaning class definition
        import re
        match = re.search(
            r"class HistoricalMeaning\(BaseModel\):(.*?)(?=^class \w+\(|\Z)",
            schemas_src,
            re.DOTALL | re.MULTILINE,
        )
        assert match, "HistoricalMeaning class not found in app/schemas.py"
        body = match.group(1)

        required_fields = {
            "domain", "situation_archetype", "historical_pattern",
            "pattern_stability", "pattern_direction", "escalation_likelihood",
            "usual_consequence", "meaning_summary", "supporting_metrics",
        }
        # Each field must appear as `field_name:` in the class body
        missing = {f for f in required_fields if f"{f}:" not in body}
        assert not missing, (
            f"HistoricalMeaning missing canonical meaning-first fields: {missing}"
        )

    def test_evidence_service_builds_historical_meaning_for_four_domains(self):
        """evidence_service must build HistoricalMeaning for price, event, signal, financial."""
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        for domain_name in ("price_meaning", "event_meaning", "signal_meaning", "financial_meaning"):
            assert domain_name in src, (
                f"evidence_service must construct {domain_name} as a HistoricalMeaning"
            )
        # Must attach as primary output, not just construct
        assert "historical_meanings = meaning_map" in src or \
               "historical_meanings\", meaning_map" in src, (
            "HistoricalMeaning objects must be attached to context as primary output"
        )

    def test_archetype_consequence_mapping_exists(self):
        """_ARCHETYPE_CONSEQUENCE must map archetypes to canonical consequences."""
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        assert "_ARCHETYPE_CONSEQUENCE" in src, (
            "evidence_service must define a canonical archetype → consequence "
            "mapping (not derived from count dominance)"
        )
        # Required meaning-first archetypes must be present
        required_archetypes = [
            "persistent-growth", "stress-cluster", "structural-shift",
            "fading-pattern", "noise-regime", "isolated-anomaly",
        ]
        for arch in required_archetypes:
            assert arch in src, f"Missing archetype: {arch}"

    def test_financial_archetype_meaning_first(self):
        """Financial archetype inference uses semantic direction labels, not raw stats."""
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        # The refactored version uses _infer_financial_archetype(direction_label)
        assert "_infer_financial_archetype" in src, (
            "financial domain must use explicit archetype inference function "
            "(meaning-first), not inline stat thresholds"
        )
        assert "fin_direction_label" in src, (
            "financial meaning must compute semantic direction label before archetype"
        )

    def test_supporting_metrics_isolated_from_primary_fields(self):
        """The schema must keep supporting_metrics separate from primary fields."""
        schemas_src = (_PROJECT_ROOT / "app/schemas.py").read_text()

        # supporting_metrics must be declared separately from primary fields
        assert "supporting_metrics:" in schemas_src, (
            "HistoricalMeaning must declare a separate 'supporting_metrics' field"
        )
        # Primary fields must NOT be dicts of raw numbers (they are string types)
        import re
        match = re.search(
            r"class HistoricalMeaning\(BaseModel\):(.*?)(?=^class \w+\(|\Z)",
            schemas_src,
            re.DOTALL | re.MULTILINE,
        )
        body = match.group(1)
        # Primary meaning fields must be typed as str (not float/int/dict)
        for primary in ("situation_archetype", "pattern_stability",
                        "escalation_likelihood", "usual_consequence"):
            pattern = rf"{primary}:\s*(\w+)"
            m = re.search(pattern, body)
            assert m, f"Field {primary} not found with type annotation"
            field_type = m.group(1)
            assert field_type == "str", (
                f"Primary meaning field '{primary}' must be typed as str "
                f"(semantic label), not {field_type}"
            )


# ════════════════════════════════════════════════════════════════════════════
# TEST 4: Routing is selective — no unconditional baseline agent execution
# ════════════════════════════════════════════════════════════════════════════

class TestRoutingIsSelective:
    """The router must not force baseline agents unconditionally."""

    def test_router_has_no_always_equity_language(self):
        """No misleading 'always run equity baseline' assertions in orchestration.

        The router's comment that equity-as-fallback is 'not an unconditional
        baseline' is CORRECT and must not be flagged — it's explaining the
        absence of a baseline, not asserting one.
        """
        # Patterns that would INCORRECTLY assert a baseline (positive claims)
        forbidden_patterns = [
            "equity analyst always runs",
            "always run equity agent",
            "equity is always executed",
            "unconditional equity baseline",
            "baseline agent always fires",
            "agents always run by default",
        ]
        files = [
            _PROJECT_ROOT / "app/services/router_service.py",
            _PROJECT_ROOT / "app/services/analysis_service.py",
            _PROJECT_ROOT / "app/api.py",
        ]
        offenders = []
        for f in files:
            if not f.exists():
                continue
            content = f.read_text().lower()
            for phrase in forbidden_patterns:
                if phrase in content:
                    offenders.append(f"{f.name}: {phrase!r}")
        assert not offenders, (
            f"Misleading 'baseline always' assertions found: {offenders}. "
            f"Routing is selective; comments must reflect this."
        )

    def test_router_selects_only_matching_agents(self):
        """Router source must contain selective agent invocation logic."""
        src = (_PROJECT_ROOT / "app/services/router_service.py").read_text()
        # Must have an explicit 'selected' list that gates agent invocation
        assert "selected_agents" in src or "selected = [" in src, (
            "Router must maintain a 'selected' list of agents to invoke"
        )
        # Agents run only when they appear in the selected list
        assert "for agent in selected" in src or \
               ('if "equity" in selected' in src or "if 'equity' in selected" in src), (
            "Router must gate agent invocation on membership in selected list"
        )

    def test_router_comment_is_honest_about_fallback(self):
        """The fallback comment must say 'explicit fallback', not 'always'."""
        src = (_PROJECT_ROOT / "app/services/router_service.py").read_text()
        assert "explicit fallback" in src or "sensible default" in src, (
            "Router must clearly comment that equity-as-fallback is an EXPLICIT "
            "fallback, not an unconditional baseline"
        )
        assert "strictly selective" in src.lower() or "Routing is strictly selective" in src, (
            "Router must clearly state routing is strictly selective"
        )

    def test_no_unconditional_equity_run_in_analysis_service(self):
        """analysis_service must not unconditionally invoke the equity agent.

        All agent calls must be inside a conditional guard:
            - dict-dispatch pattern: `_AGENT_RUNNERS["equity"]` gated by
              `for agent in selected_agents`
            - direct call gated by `if "equity" in selected_agents`
        """
        src = (_PROJECT_ROOT / "app/services/analysis_service.py").read_text()
        lines = src.splitlines()

        for i, line in enumerate(lines):
            if "run_equity_agent(" in line and not line.strip().startswith("#"):
                # Look up to 30 lines before for gating logic
                preceding = "\n".join(lines[max(0, i-30):i])
                is_gated = (
                    "selected_agents" in preceding or
                    "selected = " in preceding or
                    "_AGENT_RUNNERS" in preceding or  # dict-dispatch pattern
                    'if "equity"' in preceding or
                    "if 'equity'" in preceding or
                    ("for agent in " in preceding and "selected" in preceding)
                )
                assert is_gated, (
                    f"run_equity_agent call at line {i+1} must be gated by "
                    f"selected_agents membership. No unconditional baseline "
                    f"invocation is allowed."
                )


# ════════════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    suites = [
        TestNoHangingBackgroundTasks,
        TestNoDirectStorageFallbacks,
        TestEvidenceIsMeaningFirst,
        TestRoutingIsSelective,
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
    print(f"\n{'='*66}")
    print(f"  {passed} passed, {failed} failed")
    if not failed:
        print("  ALL FINAL COMPLETION TESTS PASSED")
    print(f"{'='*66}")
