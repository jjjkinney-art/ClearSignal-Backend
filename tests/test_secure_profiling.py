"""Sprint 3A.1 — authorized production profiling detail.

Sprint 3A gated stage detail on environment alone, so the sprint3a-asml
production run came back with an empty stage table and `unknown` bottlenecks
for 3/3 queries. Detail is now released to an explicitly authorized request
instead. These tests pin both halves: ordinary users never receive detail, and
an authorized profiler does.

Fully offline: no network, no LLM, no live backend.
"""
from __future__ import annotations

import json
import logging

import pytest

from app import observability as obs
from validation import observability as vobs
from validation.runner import (
    OBSERVABILITY_DETAIL_HEADER, OBSERVABILITY_TOKEN_HEADER, build_ask_headers,
)

SECRET = "test-profile-secret-value"


@pytest.fixture
def configured(monkeypatch):
    """Deployment configured with a profiling secret."""
    from app.config import settings
    monkeypatch.setattr(settings, "observability_profile_token", SECRET,
                        raising=False)
    return SECRET


@pytest.fixture
def unconfigured(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "observability_profile_token", "",
                        raising=False)


@pytest.fixture(autouse=True)
def _clean_trace():
    obs.set_trace(None)
    yield
    obs.set_trace(None)


# ── Authorization gate ───────────────────────────────────────────────────────

class TestProfilingAuthorization:
    def test_valid_request_is_authorized(self, configured):
        assert obs.profiling_authorized("1", SECRET) is True

    @pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_affirmative_opt_in_spellings(self, configured, flag):
        assert obs.profiling_authorized(flag, SECRET) is True

    def test_wrong_token_is_rejected(self, configured):
        assert obs.profiling_authorized("1", "wrong-secret") is False

    def test_token_prefix_is_rejected(self, configured):
        # Guards against any accidental startswith-style comparison.
        assert obs.profiling_authorized("1", SECRET[:-1]) is False

    def test_token_with_extra_suffix_is_rejected(self, configured):
        assert obs.profiling_authorized("1", SECRET + "x") is False

    def test_missing_token_is_rejected(self, configured):
        assert obs.profiling_authorized("1", None) is False
        assert obs.profiling_authorized("1", "") is False

    def test_opt_in_without_token_is_rejected(self, configured):
        assert obs.profiling_authorized("1", "   ") is False

    def test_token_without_opt_in_is_rejected(self, configured):
        # Holding the secret is not by itself a request for detail.
        assert obs.profiling_authorized(None, SECRET) is False
        assert obs.profiling_authorized("", SECRET) is False

    @pytest.mark.parametrize("flag", ["0", "false", "no", "off", "maybe", "２"])
    def test_non_affirmative_flags_are_rejected(self, configured, flag):
        assert obs.profiling_authorized(flag, SECRET) is False

    def test_unconfigured_deployment_always_refuses(self, unconfigured):
        # No secret deployed => the feature cannot be enabled by any header.
        assert obs.profiling_authorized("1", SECRET) is False
        assert obs.profiling_authorized("1", "") is False
        assert obs.profiling_authorized("1", "anything") is False

    def test_malformed_headers_fail_closed(self, configured):
        for detail, token in [
            (None, None), ("", ""), ("1", "\n"), ("\t", SECRET),
            ("1;drop", SECRET), ("1", " " + SECRET + " "),
        ]:
            result = obs.profiling_authorized(detail, token)
            # Only the whitespace-padded correct token may pass (it is stripped).
            expected = (detail == "1" and str(token).strip() == SECRET)
            assert result is expected, f"{detail!r}/{token!r}"


# ── Response-shape decision ──────────────────────────────────────────────────

class TestShouldIncludeDetail:
    def test_normal_production_request_gets_no_detail(self, configured):
        assert obs.should_include_detail(is_production=True) is False

    def test_production_opt_in_without_authorization_gets_no_detail(self, configured):
        assert obs.should_include_detail(
            is_production=True, detail_requested="1", supplied_token=None,
        ) is False

    def test_production_wrong_token_gets_no_detail(self, configured):
        assert obs.should_include_detail(
            is_production=True, detail_requested="1", supplied_token="nope",
        ) is False

    def test_production_authorized_request_gets_detail(self, configured):
        assert obs.should_include_detail(
            is_production=True, detail_requested="1", supplied_token=SECRET,
        ) is True

    def test_development_keeps_sprint_3a_behavior(self, unconfigured):
        # Local/dev debugging is unchanged and needs no secret.
        assert obs.should_include_detail(is_production=False) is True

    def test_unconfigured_production_never_emits_detail(self, unconfigured):
        assert obs.should_include_detail(
            is_production=True, detail_requested="1", supplied_token=SECRET,
        ) is False


# ── Payload shape ────────────────────────────────────────────────────────────

def _populated_trace():
    trace = obs.start_trace("req12345", ticker="ASML", route="/ask")
    obs.record_stage("routing", 12.0)
    obs.record_stage("retrieval_total", 6000.0)
    obs.record_stage("agent_total", 9000.0)
    obs.record_stage("agent.valuation", 3000.0)
    obs.record_stage("synthesis", 8000.0)
    obs.record_provider_call(provider="sec_edgar", stage="retrieval",
                             duration_ms=5200.0, result_count=8)
    obs.record_model_call(stage="synthesis", model="gpt-4o", duration_ms=7800.0,
                          input_tokens=4000, output_tokens=900, total_tokens=4900)
    return trace


COMPACT_KEYS = {"request_id", "total_duration_ms", "backend_version",
                "build_commit", "environment"}
DETAIL_KEYS = {"stages", "model_calls", "provider_calls", "token_totals"}


class TestPayloadShape:
    def test_compact_block_has_exactly_the_public_fields(self):
        payload = _populated_trace().to_dict(include_stages=False)
        assert set(payload) == COMPACT_KEYS
        for key in DETAIL_KEYS:
            assert key not in payload

    def test_detail_block_adds_profiling_fields(self):
        payload = _populated_trace().to_dict(include_stages=True)
        assert COMPACT_KEYS.issubset(set(payload))
        assert DETAIL_KEYS.issubset(set(payload))
        assert payload["stages"]
        assert payload["model_calls"]
        assert payload["provider_calls"]

    def test_both_shapes_are_json_serializable(self):
        trace = _populated_trace()
        assert json.loads(json.dumps(trace.to_dict(include_stages=False)))
        assert json.loads(json.dumps(trace.to_dict(include_stages=True)))

    def test_request_id_present_in_both_shapes(self):
        trace = _populated_trace()
        assert trace.to_dict(include_stages=False)["request_id"] == "req12345"
        assert trace.to_dict(include_stages=True)["request_id"] == "req12345"


# ── Secret containment ───────────────────────────────────────────────────────

class TestSecretsNeverLeak:
    def test_secret_absent_from_detailed_payload(self, configured):
        payload = _populated_trace().to_dict(include_stages=True)
        assert SECRET not in json.dumps(payload)

    def test_secret_absent_from_structured_logs(self, configured, caplog):
        with caplog.at_level(logging.INFO, logger="clearsignal.observability"):
            trace = obs.start_trace("req12345")
            # Even a call site that wrongly passes the secret must not log it.
            obs.record_model_call(stage="synthesis", model="gpt-4o",
                                  duration_ms=1.0, profile_token=SECRET)
            with obs.stage("integrity_validation", auth_token=SECRET):
                pass
        emitted = "".join(r.getMessage() for r in caplog.records)
        assert SECRET not in emitted
        assert SECRET not in json.dumps(trace.to_dict(include_stages=True))

    @pytest.mark.parametrize("key", [
        "token", "profile_token", "auth_token", "observability_token",
        "api_key", "secret", "authorization", "bearer", "cookie", "credential",
    ])
    def test_credential_shaped_keys_are_dropped(self, key):
        scrubbed = obs._scrub({key: SECRET, "duration_ms": 5})
        assert key not in scrubbed
        assert SECRET not in json.dumps(scrubbed)
        assert scrubbed["duration_ms"] == 5

    @pytest.mark.parametrize("key", [
        "input_tokens", "output_tokens", "total_tokens", "token_count",
    ])
    def test_token_count_fields_still_survive(self, key):
        # The singular/plural split must not cost us usage reporting.
        assert obs._scrub({key: 123})[key] == 123

    @pytest.mark.parametrize("key", [
        "prompt", "system_prompt", "completion", "content", "message",
        "reasoning", "chain_of_thought", "evidence", "response_text",
    ])
    def test_redaction_still_removes_content_fields(self, key):
        scrubbed = obs._scrub({key: "SENSITIVE-BODY", "stage": "synthesis"})
        assert key not in scrubbed
        assert "SENSITIVE-BODY" not in json.dumps(scrubbed)

    def test_secret_absent_from_run_artifacts(self, tmp_path):
        """The harness writes raw responses verbatim; the secret travels in a
        request header and so must never appear in a saved artifact."""
        from validation.models import QueryFixture, QueryOutcome
        from validation.runner import _append_result
        fixture = QueryFixture("ASML-core_thesis", "ASML", "ASML",
                               "core_thesis", "q")
        outcome = QueryOutcome(
            fixture=fixture, status="completed",
            raw_response={"answer": {}, "_observability": {
                "request_id": "r1", "total_duration_ms": 20970.0,
                "stages": [{"stage": "synthesis", "duration_ms": 8000.0,
                            "status": "ok"}],
            }},
        )
        _append_result(tmp_path, outcome)
        written = "".join(p.read_text() for p in tmp_path.rglob("*")
                          if p.is_file())
        assert written
        assert SECRET not in written
        assert OBSERVABILITY_TOKEN_HEADER not in written


# ── Runner header construction ───────────────────────────────────────────────

class TestRunnerHeaders:
    def test_ordinary_run_sends_no_profiling_headers(self):
        headers = build_ask_headers()
        assert headers == {"Content-Type": "application/json"}

    def test_auth_token_alone_adds_no_profiling_headers(self):
        headers = build_ask_headers(auth_token="bearer-value")
        assert OBSERVABILITY_DETAIL_HEADER not in headers
        assert OBSERVABILITY_TOKEN_HEADER not in headers

    def test_profiling_run_sends_both_headers(self):
        headers = build_ask_headers(profile_token=SECRET)
        assert headers[OBSERVABILITY_DETAIL_HEADER] == "1"
        assert headers[OBSERVABILITY_TOKEN_HEADER] == SECRET

    def test_profiling_headers_are_opt_in_only(self):
        assert build_ask_headers(profile_token=None) == {
            "Content-Type": "application/json"}
        assert build_ask_headers(profile_token="") == {
            "Content-Type": "application/json"}

    def test_header_names_match_the_backend(self):
        assert OBSERVABILITY_DETAIL_HEADER == obs.DETAIL_REQUEST_HEADER
        assert OBSERVABILITY_TOKEN_HEADER == obs.DETAIL_TOKEN_HEADER

    def test_cli_exposes_the_flag_and_defaults_off(self):
        from validation.runner import build_arg_parser
        args = build_arg_parser().parse_args([])
        assert args.observability_detail is False
        args = build_arg_parser().parse_args(["--observability-detail"])
        assert args.observability_detail is True

    def test_cli_does_not_accept_the_secret_as_a_value(self):
        # Env-only: a CLI value would land in shell history and `ps`.
        from validation.runner import build_arg_parser
        with pytest.raises(SystemExit):
            build_arg_parser().parse_args(["--observability-detail", SECRET])


# ── Aggregation now that detail is available ─────────────────────────────────

def _detailed_raw(total=20970.0):
    return {"_observability": {
        "request_id": "r1", "total_duration_ms": total,
        "stages": [
            {"stage": "routing", "duration_ms": 15.0, "status": "ok"},
            {"stage": "retrieval_total", "duration_ms": 6000.0, "status": "ok"},
            {"stage": "agent_total", "duration_ms": 5000.0, "status": "ok"},
            {"stage": "agent.valuation", "duration_ms": 3000.0, "status": "ok"},
            {"stage": "agent.macro", "duration_ms": 4800.0, "status": "ok"},
            {"stage": "synthesis", "duration_ms": 9500.0, "status": "ok"},
            {"stage": "web_search", "duration_ms": None, "status": "skipped"},
        ],
        "model_calls": [
            {"stage": "agent.valuation", "model": "gpt-4o-mini",
             "duration_ms": 2900.0, "input_tokens": 800, "output_tokens": 200,
             "total_tokens": 1000, "retry_count": 0, "status": "ok"},
            {"stage": "synthesis", "model": "gpt-4o", "duration_ms": 9400.0,
             "input_tokens": 4000, "output_tokens": 900, "total_tokens": 4900,
             "retry_count": 1, "status": "ok"},
        ],
        "provider_calls": [
            {"provider": "sec_edgar", "stage": "retrieval",
             "duration_ms": 5200.0, "result_count": 8, "status": "ok"},
            {"provider": "fmp", "stage": "retrieval", "duration_ms": 900.0,
             "result_count": 20, "status": "ok"},
        ],
        "token_totals": {"input_tokens": 4800, "output_tokens": 1100,
                         "total_tokens": 5900},
    }}


class _Outcome:
    def __init__(self, raw, fid="ASML-core_thesis"):
        self.raw_response = raw
        self.fixture = type("F", (), {"id": fid})()


class TestDetailedAggregation:
    def test_stage_latency_table_populates(self):
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert data["responses_with_observability"] == 1
        assert data["stages"]["synthesis"]["median"] == 9500.0
        assert data["stages"]["retrieval_total"]["median"] == 6000.0

    def test_provider_latency_populates(self):
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert data["providers"]["sec_edgar"]["median"] == 5200.0
        assert data["providers"]["fmp"]["median"] == 900.0

    def test_token_usage_populates(self):
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert data["tokens_total"]["total_tokens"] == 5900
        assert data["tokens_by_stage"]["synthesis"] == 4900
        assert data["tokens_by_stage"]["agent.valuation"] == 1000

    def test_bottleneck_no_longer_unknown(self):
        # The exact regression from sprint3a-asml: 3/3 classified `unknown`.
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert vobs.BOTTLENECK_UNKNOWN not in data["bottlenecks"]
        assert sum(data["bottlenecks"].values()) == 1

    def test_rollup_stages_still_excluded_from_slowest(self):
        block = _detailed_raw()["_observability"]
        # agent_total/retrieval_total contain their children and must not win.
        assert vobs.slowest_stage(block) == "synthesis"

    def test_slowest_agent_identified(self):
        block = _detailed_raw()["_observability"]
        assert vobs.slowest_agent(block) == "agent.macro"

    def test_skipped_stages_excluded_from_percentiles(self):
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert "web_search" not in data["stages"]

    def test_retry_counts_aggregate(self):
        data = vobs.aggregate([_Outcome(_detailed_raw())])
        assert data["counts"]["model_retries"] == 1

    def test_markdown_renders_full_tables(self):
        md = vobs.observability_md([_Outcome(_detailed_raw())])
        assert "## Stage latency (ms)" in md
        assert "## Provider latency (ms)" in md
        assert "sec_edgar" in md
        assert "Run total" in md
        assert "unknown" not in md.split("## Bottleneck classification")[1][:200]

    def test_compact_only_response_still_aggregates(self):
        """A production response WITHOUT authorization must still produce a
        valid (if thin) report rather than an error."""
        compact = {"_observability": {
            "request_id": "r1", "total_duration_ms": 20970.0,
            "backend_version": "7-linear", "build_commit": "abc123",
            "environment": "production",
        }}
        data = vobs.aggregate([_Outcome(compact)])
        assert data["responses_with_observability"] == 1
        assert data["end_to_end"]["median"] == 20970.0
        assert data["stages"] == {}
        assert data["bottlenecks"] == {vobs.BOTTLENECK_UNKNOWN: 1}

    def test_mixed_compact_and_detailed_run(self):
        compact = {"_observability": {"request_id": "r2",
                                      "total_duration_ms": 18000.0}}
        data = vobs.aggregate([_Outcome(_detailed_raw()), _Outcome(compact)])
        assert data["responses_with_observability"] == 2
        assert data["bottlenecks"][vobs.BOTTLENECK_UNKNOWN] == 1
        assert data["stages"]["synthesis"]["count"] == 1
