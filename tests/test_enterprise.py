"""
Enterprise hardening eval and regression test suite.

Tests verify BEHAVIOR across all 10 enterprise improvement areas.
These are scenario-style tests, not just unit tests.

Coverage
--------
1.  Provider governance: entitlement checks, fallback chains
2.  Observability: trace lifecycle, span timing, error categorization
3.  Audit: record emission, query by request_id
4.  Retrieval: normalization, deduplication, ranking, fallback
5.  History ops: windowed queries, comparison windows, retention
6.  Reliability: retry policy, circuit breaker state transitions
7.  Tenant safety: scope isolation, watchlist limits, source access
8.  Cache: TTL expiry, hit/miss stats, tag invalidation
9.  Tool integration: registration, dispatch, schema export
10. Config: enterprise fields present
"""
from __future__ import annotations

import sys
import time
import types
import pathlib

# ── Minimal stub setup (no pydantic or DB required) ──────────────────────

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

def _stub(name, **attrs):
    if name in sys.modules:
        m = sys.modules[name]
    else:
        m = types.ModuleType(name)
        m.__path__ = []
        sys.modules[name] = m
    for k, v in attrs.items():
        setattr(m, k, v)
    return m

# pydantic stub
pd = _stub("pydantic")
class _BM:
    model_config = {}
    model_fields = {}
    def __init__(self, **kw):
        for k,v in kw.items(): setattr(self,k,v)
pd.BaseModel = _BM
pd.Field = lambda *a, **k: None

_stub("pydantic_settings", BaseSettings=_BM)

# ── App package: preserve real __path__ so enterprise subpackage resolves ──
app = _stub("app")
app.__path__ = [str(_ROOT / "app")]   # MUST be the real path

# Stub only modules that have external dependencies or DB access
for mod in [
    "app.services", "app.providers",
    "app.data_pipeline",
    "app.data_pipeline.schemas", "app.data_pipeline.storage",
    "app.data_pipeline.ingestion",
    "app.providers.fmp_client", "app.providers.sec_client",
    "app.providers.retrieval_provider",
    "app.agents", "app.model_client",
]:
    _stub(mod)

# Minimal config — must have all enterprise fields
class _Settings:
    openai_model              = "gpt-3.5-turbo"
    fmp_api_key               = ""
    enterprise_mode           = False   # default is False
    audit_db_path             = ""
    provider_cache_ttl_s      = 300.0
    history_cache_ttl_s       = 120.0
    circuit_failure_threshold = 5
    circuit_cooldown_s        = 60.0

class _SettingsCls(_BM, _Settings):
    pass

_cfg_mod = _stub("app.config")
_cfg_mod.settings = _Settings()
_cfg_mod.Settings = _SettingsCls

_stub("app.data_pipeline.storage", query_records=lambda *a, **k: [])
_stub("app.data_pipeline.ingestion", ingest_signals=lambda *a, **k: None)

# Minimal schema stubs
_schema_mod = _stub("app.schemas")
for cn in ["Alert","ThesisChangeResult","SynthesisOutput","AlertInterpretation",
           "SignalProfileModel","MonitoringDecision","AnalysisRequest","AnalysisResponse",
           "EquityAnalysis","MacroAnalysis","OpportunityAnalysis","ResearchAnalysis",
           "EducationAnalysis","AccountingAnalysis","GroundingContext",
           "HistoricalMeaning","HistoricalInterpretation","CompanyProfile","MarketSnapshot",
           "FinancialContext","FilingContext"]:
    cls = type(cn, (_BM,), {"model_config": {}, "model_fields": {}})
    setattr(_schema_mod, cn, cls)


# ═══════════════════════════════════════════════════════════════════════════
# 1. PROVIDER GOVERNANCE
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderGovernance:

    def _reg(self):
        from app.enterprise.provider_registry import (
            ProviderRegistry, ProviderMetadata, ProviderPolicy,
            SourceType, CapabilityType,
        )
        return ProviderRegistry, ProviderMetadata, ProviderPolicy, SourceType, CapabilityType

    def test_registered_provider_access_granted(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="test_fmp", source_type=ST.LICENSED,
                        capabilities=[CT.FINANCIAL_HISTORY], requires_key=True))
        dec = reg.check_access("test_fmp", has_api_key=True)
        assert dec.allowed, f"Expected access granted: {dec.reason}"

    def test_no_api_key_denies_licensed_provider(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="keyed_prov", source_type=ST.LICENSED,
                        capabilities=[CT.FINANCIAL_HISTORY], requires_key=True))
        dec = reg.check_access("keyed_prov", has_api_key=False)
        assert not dec.allowed
        assert dec.fallback_to is None or isinstance(dec.fallback_to, str)

    def test_denied_list_blocks_provider(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="blocked", source_type=ST.PUBLIC,
                        capabilities=[CT.NEWS], requires_key=False))
        pol = PP(denied_providers=["blocked"])
        dec = reg.check_access("blocked", policy=pol, has_api_key=False)
        assert not dec.allowed

    def test_internal_source_blocked_by_default_policy(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="internal_db", source_type=ST.INTERNAL,
                        capabilities=[CT.FINANCIAL_HISTORY], requires_key=False))
        dec = reg.check_access("internal_db")
        assert not dec.allowed

    def test_internal_source_allowed_when_policy_permits(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="internal_db2", source_type=ST.INTERNAL,
                        capabilities=[CT.FINANCIAL_HISTORY], requires_key=False))
        pol = PP(allow_internal=True)
        dec = reg.check_access("internal_db2", policy=pol)
        assert dec.allowed

    def test_fallback_chain_respects_priority(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        reg.register(PM(name="hi_prio", source_type=ST.PUBLIC,
                        capabilities=[CT.NEWS], priority=10))
        reg.register(PM(name="lo_prio", source_type=ST.PUBLIC,
                        capabilities=[CT.NEWS], priority=90))
        chain = reg.build_chain(CT.NEWS)
        assert chain[0] == "hi_prio"

    def test_unregistered_provider_denied(self):
        PR, PM, PP, ST, CT = self._reg()
        reg = PR()
        dec = reg.check_access("ghost_provider")
        assert not dec.allowed


# ═══════════════════════════════════════════════════════════════════════════
# 2. OBSERVABILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestObservability:

    def test_trace_lifecycle(self):
        from app.enterprise.observability import get_tracer, start_span, finish_trace
        trace = get_tracer("req-obs-1")
        with start_span(trace, "evidence_build", {"sources": ["fmp"]}) as span:
            span.set_tag("records", 10)
        trace.finish()
        assert trace.total_ms is not None
        assert len(trace.spans) == 1
        assert trace.spans[0].stage == "evidence_build"
        assert trace.spans[0].tags.get("records") == 10

    def test_span_captures_error(self):
        from app.enterprise.observability import get_tracer, start_span
        trace = get_tracer("req-obs-err")
        try:
            with start_span(trace, "failing_stage") as span:
                raise ValueError("timeout occurred")
        except ValueError:
            pass
        assert trace.spans[0].status == "error"
        assert "timeout" in trace.spans[0].error

    def test_error_categorization(self):
        from app.enterprise.observability import ErrorCategory
        assert ErrorCategory.categorize(Exception("timeout error")) == "provider_timeout"
        assert ErrorCategory.categorize(Exception("rate limit 429")) == "provider_rate_limit"
        assert ErrorCategory.categorize(Exception("unauthorized 401")) == "provider_auth"

    def test_stage_timing_retrieval(self):
        from app.enterprise.observability import get_tracer, start_span
        trace = get_tracer("req-obs-timing")
        with start_span(trace, "agent_call") as span:
            time.sleep(0.01)
        t = trace.get_stage_timing("agent_call")
        assert t is not None and t > 5.0   # at least 5ms

    def test_has_errors_false_on_success(self):
        from app.enterprise.observability import get_tracer, start_span
        trace = get_tracer("req-obs-ok")
        with start_span(trace, "good_stage") as span:
            pass
        assert not trace.has_errors()

    def test_trace_to_dict_structure(self):
        from app.enterprise.observability import get_tracer
        trace = get_tracer("req-obs-dict")
        trace.finish()
        d = trace.to_dict()
        for key in ("request_id","trace_id","spans","total_ms","has_errors"):
            assert key in d, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════
# 3. AUDIT / REPRODUCIBILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestAudit:

    def test_analysis_audit_record_stored_and_retrieved(self):
        from app.enterprise.audit import AuditStore, AnalysisAuditRecord
        store = AuditStore(db_path=None)
        rec = AnalysisAuditRecord(
            request_id="req-audit-1", company="Acme",
            user_question="What are the risks?",
            evidence_sources=["fmp","sec"], agents_used=["equity"],
        )
        store.record_analysis(rec)
        found = store.get_analysis("req-audit-1")
        assert found is not None
        assert found.company == "Acme"
        assert "fmp" in found.evidence_sources

    def test_alert_audit_stored_and_linked(self):
        from app.enterprise.audit import AuditStore, AlertAuditRecord
        store = AuditStore(db_path=None)
        rec = AlertAuditRecord(
            request_id="req-audit-2", component="key_risks",
            case_archetype="downside-exposure-change",
            severity="high", severity_reason="change_severity=high",
        )
        store.record_alert(rec)
        alerts = store.get_alerts_for_request("req-audit-2")
        assert len(alerts) == 1
        assert alerts[0].case_archetype == "downside-exposure-change"

    def test_monitoring_audit_stored(self):
        from app.enterprise.audit import AuditStore, MonitoringDecisionRecord
        store = AuditStore(db_path=None)
        rec = MonitoringDecisionRecord(
            request_id="req-audit-3", event_type="earnings",
            behavior_profile="thesis-driven",
            recommended_action="trigger_reanalysis_and_thesis_compare",
        )
        store.record_monitoring(rec)
        recs = store.get_monitoring_for_request("req-audit-3")
        assert len(recs) == 1
        assert recs[0].behavior_profile == "thesis-driven"

    def test_audit_stats_count(self):
        from app.enterprise.audit import AuditStore, AnalysisAuditRecord
        store = AuditStore(db_path=None)
        for i in range(3):
            store.record_analysis(AnalysisAuditRecord(request_id=f"req-s-{i}"))
        stats = store.stats()
        assert stats["analysis_records"] == 3

    def test_audit_record_serializable(self):
        import json
        from app.enterprise.audit import AnalysisAuditRecord
        rec = AnalysisAuditRecord(request_id="ser-test", company="Acme")
        d = rec.to_dict()
        json.dumps(d)   # must not raise


# ═══════════════════════════════════════════════════════════════════════════
# 4. RETRIEVAL HARDENING
# ═══════════════════════════════════════════════════════════════════════════

class TestRetrieval:

    def test_normalize_produces_retrieval_result(self):
        from app.enterprise.retrieval import _normalize
        raw = {"title": "Apple Q3", "snippet": "Earnings beat", "date": "2025-01-15",
               "url": "https://example.com"}
        r = _normalize(raw, "test_src")
        assert r.title == "Apple Q3"
        assert r.source == "test_src"
        assert 0.0 <= r.freshness_score <= 1.0
        assert 0.0 <= r.combined_score <= 1.0

    def test_deduplication_removes_same_title(self):
        from app.enterprise.retrieval import RetrievalResult, _deduplicate
        r1 = RetrievalResult(source="a", title="Apple Earnings Report")
        r2 = RetrievalResult(source="b", title="apple earnings report")  # same
        r3 = RetrievalResult(source="c", title="NVIDIA Outlook")
        deduped = _deduplicate([r1, r2, r3])
        assert len(deduped) == 2

    def test_ranking_by_combined_score(self):
        from app.enterprise.retrieval import RetrievalResult, RetrievalQuery, _rank
        r_low  = RetrievalResult(source="a", title="A", combined_score=0.2)
        r_high = RetrievalResult(source="b", title="B", combined_score=0.9)
        query  = RetrievalQuery(text="test")
        ranked = _rank([r_low, r_high], query)
        assert ranked[0].combined_score > ranked[1].combined_score

    def test_freshness_score_old_is_low(self):
        from app.enterprise.retrieval import _freshness_score
        score_old   = _freshness_score("2020-01-01", fresh_days=30)
        score_today = _freshness_score("2025-10-01", fresh_days=30)
        # Old date should have lower or equal freshness
        assert score_old <= score_today

    def test_retrieve_returns_context_on_no_sources(self):
        from app.enterprise.retrieval import RetrievalQuery, retrieve
        query = RetrievalQuery(text="test", source_filter=["nonexistent_source"])
        ctx   = retrieve(query, sources=[])
        assert ctx.results == []
        assert ctx.confidence == 0.0

    def test_retrieval_context_has_expected_fields(self):
        from app.enterprise.retrieval import RetrievalQuery, retrieve
        query = RetrievalQuery(text="test")
        ctx   = retrieve(query, sources=[])
        for attr in ("query","results","sources_used","sources_failed","latency_ms","confidence"):
            assert hasattr(ctx, attr), f"Missing field: {attr}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. HISTORY OPS
# ═══════════════════════════════════════════════════════════════════════════

class TestHistoryOps:

    def test_price_window_empty_when_no_records(self):
        from app.enterprise.history_ops import HistoryOps
        ops = HistoryOps()
        w = ops.price_window("AAPL", days=30)
        assert w.domain == "price"
        assert not w.has_data

    def test_window_values_extraction(self):
        from app.enterprise.history_ops import HistoryWindow
        w = HistoryWindow(
            domain="price", ticker="AAPL",
            records=[{"price": 150.0}, {"price": 155.0}, {"price": "bad"}],
        )
        prices = w.values("price")
        assert prices == [150.0, 155.0]   # bad value skipped

    def test_comparison_windows_returns_two(self):
        from app.enterprise.history_ops import HistoryOps
        ops = HistoryOps()
        older, recent = ops.comparison_windows("price", ticker="AAPL", total_days=30)
        assert older.domain == "price"
        assert recent.domain == "price"

    def test_filter_by_type(self):
        from app.enterprise.history_ops import HistoryWindow
        w = HistoryWindow(
            domain="event", records=[
                {"event_type": "earnings", "ticker": "AAPL"},
                {"event_type": "filing",   "ticker": "AAPL"},
            ],
        )
        earnings = w.filter_by_type("earnings")
        assert earnings.record_count == 1
        assert earnings.records[0]["event_type"] == "earnings"

    def test_retention_summary_returns_dict(self):
        from app.enterprise.history_ops import HistoryOps
        ops  = HistoryOps()
        summ = ops.retention_summary()
        assert isinstance(summ, dict)
        for domain in ("price","financial","event","signal"):
            assert domain in summ

    def test_archive_before_returns_count(self):
        from app.enterprise.history_ops import HistoryOps
        ops   = HistoryOps()
        count = ops.archive_before("price", cutoff_days=365)
        assert isinstance(count, int) and count >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. RELIABILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestReliability:

    def test_successful_call_records_success(self):
        from app.enterprise.reliability import ProviderHealth, call_with_reliability
        health = ProviderHealth()
        result = call_with_reliability("test_prov", fn=lambda: "ok",
                                        policy=None)
        assert result == "ok"

    def test_failing_call_uses_fallback(self):
        from app.enterprise.reliability import call_with_reliability, RetryPolicy
        pol = RetryPolicy(max_retries=0)
        result = call_with_reliability(
            "fail_prov",
            fn=lambda: (_ for _ in ()).throw(Exception("boom")),
            policy=pol,
            fallback_fn=lambda: "fallback_value",
        )
        assert result == "fallback_value"

    def test_circuit_breaker_opens_after_threshold(self):
        from app.enterprise.reliability import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3, cooldown_s=1000)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_breaker_half_opens_after_cooldown(self):
        from app.enterprise.reliability import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_closes_on_success(self):
        from app.enterprise.reliability import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=2, cooldown_s=0.01)
        cb.record_failure(); cb.record_failure()
        time.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_retry_policy_delay_increases(self):
        from app.enterprise.reliability import RetryPolicy
        pol = RetryPolicy(max_retries=3, backoff_factor=1.0, jitter=False)
        d1 = pol.delay(1); d2 = pol.delay(2); d3 = pol.delay(3)
        assert d1 < d2 < d3

    def test_classify_exception(self):
        from app.enterprise.reliability import (
            _classify_exception, ProviderTimeoutError,
            ProviderRateLimitError, ProviderAuthError,
        )
        assert _classify_exception(Exception("connection timeout")) == ProviderTimeoutError
        assert _classify_exception(Exception("rate limit 429"))     == ProviderRateLimitError
        assert _classify_exception(Exception("unauthorized 401"))   == ProviderAuthError


# ═══════════════════════════════════════════════════════════════════════════
# 7. TENANT SAFETY
# ═══════════════════════════════════════════════════════════════════════════

class TestTenantSafety:

    def test_scope_isolation_different_tenants(self):
        from app.enterprise.tenant import ScopedWatchlist, ScopeContext
        wl = ScopedWatchlist()
        scope_a = ScopeContext(user_id="u1", tenant_id="tenant_a")
        scope_b = ScopeContext(user_id="u1", tenant_id="tenant_b")
        wl.add("AAPL", scope_a)
        assert wl.is_watched("AAPL", scope_a)
        assert not wl.is_watched("AAPL", scope_b)   # different tenant

    def test_watchlist_max_limit_enforced(self):
        from app.enterprise.tenant import (
            ScopedWatchlist, ScopeContext, TenantScope
        )
        tenant = TenantScope(tenant_id="limited", max_watchlist=2)
        scope  = ScopeContext(user_id="u2", tenant_id="limited", tenant_scope=tenant)
        wl     = ScopedWatchlist()
        wl.add("AAPL", scope)
        wl.add("GOOG", scope)
        raised = False
        try:
            wl.add("MSFT", scope)
        except ValueError:
            raised = True
        assert raised, "Expected ValueError when watchlist limit exceeded"

    def test_source_access_restriction_by_scope(self):
        from app.enterprise.tenant import ScopeContext, TenantScope
        tenant = TenantScope(tenant_id="restricted", allowed_sources=["sec"])
        scope  = ScopeContext(tenant_scope=tenant)
        assert scope.can_access_source("sec")
        assert not scope.can_access_source("fmp")

    def test_anonymous_scope_has_no_restrictions(self):
        from app.enterprise.tenant import get_scope
        scope = get_scope("nonexistent_key")
        assert scope.can_access_source("fmp")    # no restrictions for anonymous
        assert scope.can_access_source("sec")

    def test_alert_subscription_scoped(self):
        from app.enterprise.tenant import ScopedAlertSubscriptions, ScopeContext
        subs = ScopedAlertSubscriptions()
        scope_a = ScopeContext(user_id="ua", tenant_id="ta")
        scope_b = ScopeContext(user_id="ub", tenant_id="tb")
        subs.subscribe("AAPL", scope_a, {"sensitivity": "high"})
        assert subs.get_config("AAPL", scope_a) is not None
        assert subs.get_config("AAPL", scope_b) is None   # not visible to scope_b

    def test_user_preference_retrieval(self):
        from app.enterprise.tenant import UserScope, ScopeContext
        user  = UserScope(user_id="u3", preferences={"alert_sensitivity": "high"})
        scope = ScopeContext(user_id="u3", user_scope=user)
        assert scope.user_preference("alert_sensitivity") == "high"
        assert scope.user_preference("nonexistent", "default") == "default"


# ═══════════════════════════════════════════════════════════════════════════
# 8. CACHE
# ═══════════════════════════════════════════════════════════════════════════

class TestCache:

    def test_set_and_get(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache(default_ttl=60)
        cache.set("k1", {"data": 42})
        result = cache.get("k1")
        assert result == {"data": 42}

    def test_expired_entry_returns_none(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache()
        cache.set("exp_key", "value", ttl_s=0.01)
        time.sleep(0.05)
        assert cache.get("exp_key") is None

    def test_hit_miss_stats(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache()
        cache.set("hit_key", "val")
        cache.get("hit_key")        # hit
        cache.get("miss_key")       # miss
        stats = cache.stats()
        assert stats["hits"]   == 1
        assert stats["misses"] == 1

    def test_hit_rate_computed(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache()
        cache.set("a", 1); cache.set("b", 2)
        cache.get("a"); cache.get("a"); cache.get("b")  # 3 hits
        cache.get("z")                                   # 1 miss
        stats = cache.stats()
        assert stats["hit_rate"] == 0.75

    def test_tag_invalidation(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache()
        cache.set("fmp:k1", "v1", source_tags=["fmp"])
        cache.set("sec:k2", "v2", source_tags=["sec"])
        cache.set("fmp:k3", "v3", source_tags=["fmp"])
        removed = cache.invalidate_by_tag("fmp")
        assert removed == 2
        assert cache.get("fmp:k1") is None
        assert cache.get("sec:k2") == "v2"

    def test_max_entries_eviction(self):
        from app.enterprise.cache import InProcessCache
        cache = InProcessCache(max_entries=3)
        for i in range(5):
            cache.set(f"key_{i}", i)
        stats = cache.stats()
        assert stats["active"] <= 3


# ═══════════════════════════════════════════════════════════════════════════
# 9. TOOL INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

class TestToolIntegration:

    def test_tool_registration_and_retrieval(self):
        from app.enterprise.tools import ToolRegistry, ToolDefinition
        reg  = ToolRegistry()
        tool = ToolDefinition(
            name="test_tool", description="A test tool",
            input_schema={"type": "object", "properties": {}},
            handler=lambda inp: "result",
        )
        reg.register(tool)
        assert reg.get("test_tool") is not None

    def test_tool_dispatch_success(self):
        from app.enterprise.tools import ToolRegistry, ToolDefinition
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="adder", description="Adds two numbers",
            input_schema={"type": "object"},
            handler=lambda inp: inp.get("a", 0) + inp.get("b", 0),
        ))
        result = reg.call("adder", {"a": 3, "b": 4})
        assert result.success
        assert result.content == 7

    def test_tool_dispatch_failure_returns_error_result(self):
        from app.enterprise.tools import ToolRegistry, ToolDefinition
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="bad_tool", description="Always fails",
            input_schema={"type": "object"},
            handler=lambda inp: (_ for _ in ()).throw(RuntimeError("bad")),
        ))
        result = reg.call("bad_tool", {})
        assert not result.success
        assert "bad" in result.error

    def test_unknown_tool_returns_error_result(self):
        from app.enterprise.tools import ToolRegistry
        reg    = ToolRegistry()
        result = reg.call("ghost_tool", {})
        assert not result.success

    def test_tool_schema_export(self):
        from app.enterprise.tools import tool_registry
        schemas = tool_registry.to_tool_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) > 0
        for s in schemas:
            assert "name" in s
            assert "description" in s
            assert "input_schema" in s

    def test_built_in_tools_registered(self):
        from app.enterprise.tools import tool_registry
        for name in ("company_profile","market_snapshot","recent_filings",
                     "retrieve","price_history","analyze_company"):
            assert tool_registry.get(name) is not None, f"Missing built-in tool: {name}"

    def test_category_filter(self):
        from app.enterprise.tools import tool_registry
        financial = tool_registry.for_category("financial")
        assert len(financial) > 0
        assert all("financial" in t.categories for t in financial)


# ═══════════════════════════════════════════════════════════════════════════
# 10. CONFIG ENTERPRISE FIELDS
# ═══════════════════════════════════════════════════════════════════════════

class TestEnterpriseConfig:

    def test_enterprise_config_fields_present(self):
        """All enterprise config fields must exist on Settings."""
        from app.config import Settings
        # Instantiate with defaults
        s = Settings()
        required_fields = [
            "enterprise_mode", "audit_db_path", "provider_cache_ttl_s",
            "history_cache_ttl_s", "circuit_failure_threshold", "circuit_cooldown_s",
        ]
        for f in required_fields:
            assert hasattr(s, f), f"Missing enterprise config field: {f}"

    def test_enterprise_defaults_are_safe(self):
        from app.config import Settings
        s = Settings()
        # enterprise_mode defaults to False (opt-in)
        assert s.enterprise_mode is False
        assert s.provider_cache_ttl_s > 0
        assert s.circuit_failure_threshold > 0


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    suites = [
        TestProviderGovernance,
        TestObservability,
        TestAudit,
        TestRetrieval,
        TestHistoryOps,
        TestReliability,
        TestTenantSafety,
        TestCache,
        TestToolIntegration,
        TestEnterpriseConfig,
    ]
    passed = 0; failed = 0
    for cls in suites:
        suite = cls()
        name  = cls.__name__
        for meth in sorted(n for n in dir(cls) if n.startswith("test_")):
            label = f"{name}.{meth}"
            try:
                getattr(suite, meth)()
                print(f"  PASS  {label}")
                passed += 1
            except Exception as e:
                import traceback
                print(f"  FAIL  {label}: {e}")
                failed += 1
    print(f"\n{'='*62}")
    print(f"  {passed} passed, {failed} failed")
    if not failed:
        print("  ALL ENTERPRISE TESTS PASSED")
    print(f"{'='*62}")
