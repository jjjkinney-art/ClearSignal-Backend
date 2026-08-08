"""Sprint 3A — request tracing, stage timing, and observability aggregation.

Fully offline: no network, no LLM, no live provider. Model and provider
behavior is supplied by fakes so timing and metadata capture can be asserted
deterministically.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app import observability as obs
from validation import observability as vobs


@pytest.fixture(autouse=True)
def _clean_trace():
    """Every test starts and ends without an ambient trace."""
    obs.set_trace(None)
    yield
    obs.set_trace(None)


# ── A. Request tracing ───────────────────────────────────────────────────────

class TestRequestTracing:
    def test_trace_generates_a_request_id(self):
        trace = obs.start_trace()
        assert trace.request_id
        assert len(trace.request_id) >= 8

    def test_supplied_request_id_is_reused_not_replaced(self):
        # The /ask route passes the id the timing middleware already made; a
        # single request must never end up with two identifiers.
        trace = obs.start_trace("abc12345")
        assert trace.request_id == "abc12345"

    def test_trace_is_the_active_one(self):
        trace = obs.start_trace("abc12345")
        assert obs.current_trace() is trace

    def test_no_active_trace_is_tolerated(self):
        # Instrumentation is a no-op outside a request rather than an error.
        assert obs.current_trace() is None
        with obs.stage("routing") as record:
            assert record is None
        obs.record_model_call(stage="x", model="m", duration_ms=1.0)
        obs.record_provider_call(provider="p", stage="retrieval", duration_ms=1.0)
        obs.skip_stage("synthesis", "not needed")

    def test_bind_propagates_across_a_thread(self):
        trace = obs.start_trace("abc12345")
        seen = {}

        def _worker():
            seen["id"] = getattr(obs.current_trace(), "request_id", None)

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obs.bind(_worker)).result()
        assert seen["id"] == "abc12345"

    def test_unbound_thread_does_not_see_the_trace(self):
        # Establishes WHY bind() is needed rather than assuming it.
        obs.start_trace("abc12345")
        seen = {}

        def _worker():
            seen["id"] = getattr(obs.current_trace(), "request_id", None)

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_worker).result()
        assert seen["id"] is None

    def test_correlation_survives_an_exception(self):
        trace = obs.start_trace("abc12345")
        with pytest.raises(ValueError):
            with obs.stage("agent_total"):
                raise ValueError("boom")
        assert trace.request_id == "abc12345"
        assert trace.stages[0].stage == "agent_total"

    def test_response_block_carries_the_request_id(self):
        trace = obs.start_trace("abc12345")
        payload = trace.to_dict()
        assert payload["request_id"] == "abc12345"
        assert "total_duration_ms" in payload
        assert "build_commit" in payload
        assert "backend_version" in payload


# ── B. Timing ────────────────────────────────────────────────────────────────

class TestStageTiming:
    def test_duration_is_captured(self):
        trace = obs.start_trace()
        with obs.stage("retrieval_total"):
            time.sleep(0.02)
        record = trace.stages[0]
        assert record.stage == "retrieval_total"
        assert record.status == obs.STATUS_OK
        assert record.duration_ms >= 15

    def test_nested_stages_both_recorded(self):
        trace = obs.start_trace()
        with obs.stage("agent_total"):
            with obs.stage("agent.valuation"):
                time.sleep(0.01)
            time.sleep(0.01)
        names = [s.stage for s in trace.stages]
        # Inner completes first, so it is appended first.
        assert names == ["agent.valuation", "agent_total"]
        inner = trace.stages[0].duration_ms
        outer = trace.stages[1].duration_ms
        assert outer >= inner

    def test_failed_stage_still_records_timing(self):
        trace = obs.start_trace()
        with pytest.raises(RuntimeError):
            with obs.stage("synthesis"):
                time.sleep(0.01)
                raise RuntimeError("nope")
        record = trace.stages[0]
        assert record.status == obs.STATUS_ERROR
        assert record.error_class == "RuntimeError"
        assert record.duration_ms >= 5

    def test_timeout_is_distinguished_from_error(self):
        trace = obs.start_trace()
        with pytest.raises(TimeoutError):
            with obs.stage("agent.macro"):
                raise TimeoutError()
        assert trace.stages[0].status == obs.STATUS_TIMEOUT

    def test_skipped_stage_is_distinguishable_from_zero_duration(self):
        trace = obs.start_trace()
        obs.skip_stage("web_search", "provider disabled")
        with obs.stage("routing"):
            pass
        skipped, ran = trace.stages
        assert skipped.status == obs.STATUS_SKIPPED
        assert skipped.duration_ms is None      # not 0.0
        assert ran.status == obs.STATUS_OK
        assert ran.duration_ms is not None

    def test_record_stage_for_worker_measured_work(self):
        trace = obs.start_trace()
        obs.record_stage("agent.risk", 1234.5)
        record = trace.stages[0]
        assert record.duration_ms == 1234.5
        assert record.status == obs.STATUS_OK

    def test_record_stage_can_mark_a_timeout(self):
        trace = obs.start_trace()
        obs.record_stage("agent.quality", 16000.0, status=obs.STATUS_TIMEOUT,
                         error_class="WallCapExceeded")
        assert trace.stages[0].status == obs.STATUS_TIMEOUT
        assert trace.stages[0].error_class == "WallCapExceeded"

    def test_total_duration_is_monotonic_and_positive(self):
        trace = obs.start_trace()
        time.sleep(0.01)
        assert trace.total_duration_ms() > 0

    def test_concurrent_stage_writes_are_not_lost(self):
        trace = obs.start_trace()

        def _worker(i):
            obs.record_stage(f"agent.{i}", 10.0)

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(obs.bind(_worker), range(6)))
        assert len(trace.stages) == 6


# ── C. Model-call metadata ───────────────────────────────────────────────────

class TestModelMetadata:
    def test_usage_recorded_when_supplied(self):
        trace = obs.start_trace()
        obs.record_model_call(
            stage="synthesis", model="gpt-4o", duration_ms=1200.0,
            input_tokens=1500, output_tokens=800, total_tokens=2300,
        )
        call = trace.model_calls[0]
        assert call["input_tokens"] == 1500
        assert call["total_tokens"] == 2300
        assert call["status"] == "ok"

    def test_usage_is_null_when_unavailable(self):
        trace = obs.start_trace()
        obs.record_model_call(stage="synthesis", model="gpt-4o", duration_ms=5.0)
        call = trace.model_calls[0]
        assert call["input_tokens"] is None
        assert call["total_tokens"] is None

    def test_retries_are_represented(self):
        trace = obs.start_trace()
        obs.record_model_call(stage="agent.macro", model="gpt-4o-mini",
                              duration_ms=900.0, retry_count=2)
        assert trace.model_calls[0]["retry_count"] == 2

    def test_failures_are_represented(self):
        trace = obs.start_trace()
        obs.record_model_call(stage="agent.risk", model="gpt-4o-mini",
                              duration_ms=15000.0, status="timeout",
                              error_class="APITimeoutError")
        call = trace.model_calls[0]
        assert call["status"] == "timeout"
        assert call["error_class"] == "APITimeoutError"

    def test_token_totals_skip_unreported_calls(self):
        trace = obs.start_trace()
        obs.record_model_call(stage="a", model="m", duration_ms=1.0,
                              total_tokens=100, input_tokens=60, output_tokens=40)
        obs.record_model_call(stage="b", model="m", duration_ms=1.0)
        totals = trace.token_totals()
        assert totals["total_tokens"] == 100

    def test_token_totals_are_none_when_nothing_reported(self):
        trace = obs.start_trace()
        obs.record_model_call(stage="a", model="m", duration_ms=1.0)
        assert trace.token_totals()["total_tokens"] is None

    def test_model_client_extracts_usage(self):
        from app.model_client import ModelClient
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=50, total_tokens=150))
        assert ModelClient._usage(response) == {
            "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
        }

    def test_model_client_usage_absent_is_none_not_zero(self):
        from app.model_client import ModelClient
        assert ModelClient._usage(SimpleNamespace()) == {
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
        }

    def test_model_client_records_failure_and_reraises(self):
        from app.model_client import ModelClient
        trace = obs.start_trace()
        client = ModelClient(api_key="", model="gpt-4o-mini",
                             temperature=0.2, max_tokens=100)
        with pytest.raises(RuntimeError):
            client.call("hello", stage="agent.valuation")
        call = trace.model_calls[0]
        assert call["stage"] == "agent.valuation"
        assert call["status"] == "error"
        assert call["total_tokens"] is None


# ── D. Provider metadata ─────────────────────────────────────────────────────

class TestProviderMetadata:
    def test_duration_and_result_count(self):
        trace = obs.start_trace()
        obs.record_provider_call(provider="sec_edgar", stage="retrieval",
                                 duration_ms=820.0, result_count=12)
        call = trace.provider_calls[0]
        assert call["provider"] == "sec_edgar"
        assert call["duration_ms"] == 820.0
        assert call["result_count"] == 12

    def test_cache_state(self):
        trace = obs.start_trace()
        obs.record_provider_call(provider="fmp", stage="retrieval",
                                 duration_ms=5.0, cache="hit")
        assert trace.provider_calls[0]["cache"] == "hit"

    def test_retry_count(self):
        trace = obs.start_trace()
        obs.record_provider_call(provider="news", stage="retrieval",
                                 duration_ms=900.0, retry_count=3)
        assert trace.provider_calls[0]["retry_count"] == 3

    def test_timeout_and_failure_state(self):
        trace = obs.start_trace()
        obs.record_provider_call(provider="fred", stage="retrieval",
                                 duration_ms=10000.0, status="timeout",
                                 error_class="ReadTimeout", result_count=None)
        call = trace.provider_calls[0]
        assert call["status"] == "timeout"
        assert call["error_class"] == "ReadTimeout"
        assert call["result_count"] is None


# ── E. Structured logging & redaction ────────────────────────────────────────

class TestStructuredLogging:
    def _capture(self, caplog):
        return [r.getMessage() for r in caplog.records
                if r.name == "clearsignal.observability"]

    def test_events_are_json_serializable(self, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            obs.start_trace("abc12345")
            with obs.stage("routing"):
                pass
        messages = self._capture(caplog)
        assert messages
        payload = json.loads(messages[-1])
        assert payload["request_id"] == "abc12345"

    def test_required_fields_present(self, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            obs.start_trace("abc12345", ticker="MSFT", route="/ask")
            with obs.stage("synthesis"):
                pass
        payload = json.loads(self._capture(caplog)[-1])
        for field in ("timestamp", "request_id", "event", "stage", "duration_ms",
                      "status", "ticker", "route", "backend_version", "build_commit"):
            assert field in payload, f"missing {field}"

    def test_model_call_log_has_model_and_tokens(self, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            obs.start_trace("abc12345")
            obs.record_model_call(stage="synthesis", model="gpt-4o",
                                  duration_ms=10.0, total_tokens=42)
        payload = json.loads(self._capture(caplog)[-1])
        assert payload["event"] == "model_call"
        assert payload["model"] == "gpt-4o"
        assert payload["total_tokens"] == 42

    def test_provider_log_has_provider_field(self, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            obs.start_trace("abc12345")
            obs.record_provider_call(provider="sec_edgar", stage="retrieval",
                                     duration_ms=10.0, result_count=3)
        payload = json.loads(self._capture(caplog)[-1])
        assert payload["provider"] == "sec_edgar"

    @pytest.mark.parametrize("key", [
        "prompt", "system_prompt", "completion", "content", "message",
        "reasoning", "chain_of_thought", "api_key", "secret", "authorization",
        "evidence", "answer_text",
    ])
    def test_sensitive_keys_are_dropped(self, key):
        scrubbed = obs._scrub({key: "sk-live-SECRET-VALUE", "duration_ms": 5})
        assert key not in scrubbed
        assert "SECRET" not in json.dumps(scrubbed)
        assert scrubbed["duration_ms"] == 5

    def test_token_count_keys_survive_scrubbing(self):
        # "token" appears in the denylist markers; the count fields must not be
        # collateral damage.
        scrubbed = obs._scrub({
            "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
            "result_count": 3, "evidence_count": 7,
        })
        assert scrubbed["total_tokens"] == 15
        assert scrubbed["evidence_count"] == 7

    def test_secrets_cannot_reach_a_stage_record(self, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            trace = obs.start_trace("abc12345")
            with obs.stage("synthesis", prompt="TOP-SECRET", zone_count=3):
                pass
        assert "TOP-SECRET" not in json.dumps(trace.to_dict())
        assert trace.stages[0].detail == {"zone_count": 3}
        assert "TOP-SECRET" not in "".join(self._capture(caplog))

    def test_collections_are_recorded_as_length_only(self):
        scrubbed = obs._scrub({"tickers": ["MSFT", "NVDA", "AAPL"]})
        assert scrubbed["tickers"] == 3

    def test_response_block_has_no_prompt_material(self):
        trace = obs.start_trace("abc12345")
        obs.record_model_call(stage="synthesis", model="gpt-4o", duration_ms=1.0,
                              prompt="LEAK", total_tokens=10)
        serialized = json.dumps(trace.to_dict())
        assert "LEAK" not in serialized

    def test_logging_never_raises_on_unserializable_detail(self):
        trace = obs.start_trace("abc12345")
        obs.record_model_call(stage="s", model="m", duration_ms=1.0,
                              widget=object())
        assert trace.model_calls  # recorded, did not blow up


class TestBuildIdentity:
    def test_fields_present(self):
        identity = obs.build_identity()
        assert set(identity) == {"backend_version", "build_commit", "environment"}

    def test_commit_read_from_render_env(self, monkeypatch):
        monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567890")
        assert obs.build_identity()["build_commit"] == "abcdef123456"

    def test_unknown_commit_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
        monkeypatch.delenv("GIT_COMMIT", raising=False)
        assert obs.build_identity()["build_commit"] == "unknown"


# ── F. Validation aggregation ────────────────────────────────────────────────

def _raw(stages=None, model_calls=None, provider_calls=None, total=1000.0,
         token_totals=None):
    block = {"request_id": "r1", "total_duration_ms": total}
    if stages is not None:
        block["stages"] = stages
    if model_calls is not None:
        block["model_calls"] = model_calls
    if provider_calls is not None:
        block["provider_calls"] = provider_calls
    if token_totals is not None:
        block["token_totals"] = token_totals
    return {"_observability": block}


def _outcome(raw, fid="Q1"):
    return SimpleNamespace(raw_response=raw, fixture=SimpleNamespace(id=fid))


def _stage(name, ms, status="ok"):
    return {"stage": name, "duration_ms": ms, "status": status}


class TestValidationAggregation:
    def test_old_response_without_observability_still_works(self):
        data = vobs.aggregate([_outcome({"answer": {}})])
        assert data["responses_with_observability"] == 0
        assert data["bottlenecks"] == {vobs.BOTTLENECK_UNKNOWN: 1}

    def test_markdown_renders_for_old_responses(self):
        md = vobs.observability_md([_outcome({"answer": {}})])
        assert "# Observability Summary" in md
        assert "0/1" in md

    def test_medians_and_p95_aggregate(self):
        outcomes = [
            _outcome(_raw(stages=[_stage("synthesis", ms)], total=ms))
            for ms in (100.0, 200.0, 300.0, 400.0)
        ]
        data = vobs.aggregate(outcomes)
        assert data["responses_with_observability"] == 4
        assert data["stages"]["synthesis"]["median"] == 250.0
        assert data["stages"]["synthesis"]["max"] == 400.0
        assert data["end_to_end"]["median"] == 250.0

    def test_skipped_stages_excluded_from_percentiles(self):
        outcomes = [_outcome(_raw(stages=[
            _stage("routing", 100.0),
            {"stage": "web_search", "duration_ms": None, "status": "skipped"},
        ]))]
        data = vobs.aggregate(outcomes)
        assert "web_search" not in data["stages"]
        assert data["stages"]["routing"]["median"] == 100.0

    def test_slowest_stage_identified(self):
        block = _raw(stages=[
            _stage("routing", 10.0), _stage("synthesis", 900.0),
            _stage("agent.macro", 400.0),
        ])["_observability"]
        assert vobs.slowest_stage(block) == "synthesis"

    def test_rollup_stages_excluded_from_slowest(self):
        # agent_total contains the agents, so it would always win.
        block = _raw(stages=[
            _stage("agent_total", 5000.0), _stage("agent.macro", 400.0),
            _stage("synthesis", 900.0),
        ])["_observability"]
        assert vobs.slowest_stage(block) == "synthesis"

    def test_slowest_agent_identified(self):
        block = _raw(stages=[
            _stage("agent.macro", 400.0), _stage("agent.risk", 1200.0),
            _stage("synthesis", 5000.0),
        ])["_observability"]
        assert vobs.slowest_agent(block) == "agent.risk"

    def test_token_totals_aggregate(self):
        outcomes = [
            _outcome(_raw(model_calls=[
                {"stage": "synthesis", "total_tokens": 100,
                 "input_tokens": 60, "output_tokens": 40},
            ])),
            _outcome(_raw(model_calls=[
                {"stage": "synthesis", "total_tokens": 50,
                 "input_tokens": 30, "output_tokens": 20},
            ])),
        ]
        data = vobs.aggregate(outcomes)
        assert data["tokens_total"]["total_tokens"] == 150
        assert data["tokens_by_stage"]["synthesis"] == 150

    def test_unknown_token_usage_handled_gracefully(self):
        outcomes = [_outcome(_raw(model_calls=[
            {"stage": "synthesis", "total_tokens": None},
        ]))]
        data = vobs.aggregate(outcomes)
        assert data["tokens_total"] is None
        assert "no model call reported token usage" in vobs.observability_md(outcomes)

    def test_provider_latency_summary(self):
        outcomes = [_outcome(_raw(provider_calls=[
            {"provider": "sec_edgar", "duration_ms": 800.0},
            {"provider": "fmp", "duration_ms": 200.0},
        ]))]
        data = vobs.aggregate(outcomes)
        assert data["providers"]["sec_edgar"]["median"] == 800.0
        assert data["providers"]["fmp"]["median"] == 200.0

    def test_retry_and_error_counts(self):
        outcomes = [_outcome(_raw(
            model_calls=[{"stage": "a", "retry_count": 2, "status": "timeout"}],
            provider_calls=[{"provider": "p", "duration_ms": 1.0,
                             "retry_count": 1, "status": "error"}],
            stages=[_stage("agent.risk", 16000.0, status="timeout")],
        ))]
        counts = vobs.aggregate(outcomes)["counts"]
        assert counts["model_retries"] == 2
        assert counts["model_timeouts"] == 1
        assert counts["provider_retries"] == 1
        assert counts["provider_errors"] == 1
        assert counts["stage_timeouts"] == 1

    def test_malformed_block_does_not_crash(self):
        for bad in ({"_observability": "nope"}, {"_observability": None},
                    None, [], "string"):
            assert vobs.aggregate([_outcome(bad)])["responses_total"] == 1

    def test_full_markdown_renders(self):
        outcomes = [_outcome(_raw(
            stages=[_stage("routing", 10.0), _stage("retrieval_total", 3000.0),
                    _stage("agent_total", 8000.0), _stage("synthesis", 20000.0)],
            model_calls=[{"stage": "synthesis", "total_tokens": 2000,
                          "input_tokens": 1500, "output_tokens": 500}],
            provider_calls=[{"provider": "sec_edgar", "duration_ms": 2000.0}],
            total=31000.0,
        ))]
        md = vobs.observability_md(outcomes)
        assert "## Stage latency (ms)" in md
        assert "## Provider latency (ms)" in md
        assert "## Bottleneck classification" in md
        assert "synthesis-bound" in md
        assert "sec_edgar" in md


# ── Bottleneck classification ────────────────────────────────────────────────

class TestBottleneckClassification:
    def _classify(self, stages, provider_calls=None):
        return vobs.classify_bottleneck(
            _raw(stages=stages, provider_calls=provider_calls)["_observability"]
        )

    def test_synthesis_bound(self):
        assert self._classify([
            _stage("routing", 10.0), _stage("retrieval_total", 1000.0),
            _stage("agent_total", 2000.0), _stage("synthesis", 20000.0),
        ]) == vobs.BOTTLENECK_SYNTHESIS

    def test_agent_bound(self):
        assert self._classify([
            _stage("routing", 10.0), _stage("retrieval_total", 1000.0),
            _stage("agent_total", 16000.0), _stage("synthesis", 2000.0),
        ]) == vobs.BOTTLENECK_AGENT

    def test_retrieval_bound(self):
        assert self._classify([
            _stage("routing", 10.0), _stage("retrieval_total", 9000.0),
            _stage("agent_total", 2000.0), _stage("synthesis", 2000.0),
        ]) == vobs.BOTTLENECK_RETRIEVAL

    def test_routing_bound(self):
        assert self._classify([
            _stage("routing", 9000.0), _stage("retrieval_total", 500.0),
            _stage("agent_total", 500.0), _stage("synthesis", 500.0),
        ]) == vobs.BOTTLENECK_ROUTING

    def test_provider_bound_refines_retrieval_bound(self):
        assert self._classify(
            [_stage("routing", 10.0), _stage("retrieval_total", 9000.0),
             _stage("agent_total", 1000.0), _stage("synthesis", 1000.0)],
            provider_calls=[{"provider": "sec_edgar", "duration_ms": 8500.0},
                            {"provider": "fmp", "duration_ms": 300.0}],
        ) == vobs.BOTTLENECK_PROVIDER

    def test_evenly_spread_is_mixed(self):
        assert self._classify([
            _stage("routing", 2000.0), _stage("retrieval_total", 2500.0),
            _stage("agent_total", 2500.0), _stage("synthesis", 2500.0),
        ]) == vobs.BOTTLENECK_MIXED

    def test_no_stage_data_is_unknown(self):
        assert vobs.classify_bottleneck(None) == vobs.BOTTLENECK_UNKNOWN
        assert vobs.classify_bottleneck({}) == vobs.BOTTLENECK_UNKNOWN

    def test_unrecognized_stages_only_is_unknown(self):
        assert self._classify([_stage("mystery", 5000.0)]) == vobs.BOTTLENECK_UNKNOWN

    def test_classification_is_deterministic(self):
        stages = [_stage("routing", 10.0), _stage("retrieval_total", 1000.0),
                  _stage("agent_total", 2000.0), _stage("synthesis", 20000.0)]
        results = {self._classify(stages) for _ in range(10)}
        assert len(results) == 1


# ── G. Correctness guardrail ─────────────────────────────────────────────────

class TestNoBehaviorChange:
    def test_stage_returns_the_block_value_unchanged(self):
        obs.start_trace()
        with obs.stage("routing"):
            value = 42
        assert value == 42

    def test_bind_preserves_arguments_and_return(self):
        obs.start_trace()
        fn = obs.bind(lambda a, b=2: (a, b))
        assert fn(1, b=3) == (1, 3)

    def test_exceptions_propagate_unchanged(self):
        obs.start_trace()

        class Custom(Exception):
            pass

        with pytest.raises(Custom):
            with obs.stage("synthesis"):
                raise Custom("original message")

    def test_instrumentation_overhead_is_negligible(self):
        """Guards against instrumentation itself becoming a latency source."""
        obs.start_trace()
        started = time.monotonic()
        for _ in range(1000):
            with obs.stage("noop"):
                pass
        elapsed_ms = (time.monotonic() - started) * 1000.0
        # 1000 stages well under 1s => < 1ms per stage.
        assert elapsed_ms < 1000, f"{elapsed_ms:.0f}ms for 1000 stages"
