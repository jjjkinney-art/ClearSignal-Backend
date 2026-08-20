"""Sprint 3C.1A — progressive response protocol.

Sprint 3C established the constraint this suite exists to enforce: raw
synthesis cannot be streamed as final content, because `polish_thesis`
materially rewrites all seven prose fields afterwards and `direct_answer` is
replaced wholesale by the question-answerer output. So the protocol carries
progress ONLY, and the terminal frame must be identical to what the legacy
path serializes.

The two invariants under test are therefore:
  1. No analytical content escapes before the terminal frame.
  2. `final.data` equals the legacy body, given identical pipeline output.
"""
from __future__ import annotations

import json
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.observability import RequestTrace, record_stage
from app.progress import (
    ALLOWED_PROGRESS_KEYS,
    PROGRESS_MEDIA_TYPE,
    ProgressProjector,
    encode_frame,
    error_frame,
    final_frame,
    progress_frame,
    progressive_requested,
)
from app.schemas import AgentAnswerResponse


def _api():
    """Import app.api lazily.

    A module-scope import makes `AnalysisResponse` resolve to a same-named
    class in another test module during full-suite collection, which FastAPI
    then rejects as a response field. Importing inside the call keeps
    collection order irrelevant.
    """
    import app.api as api
    return api


BODY = {"question": "test?", "company_name": "MSFT", "intent": "company_analysis"}
NDJSON = {"Accept": PROGRESS_MEDIA_TYPE}

# Sentinels that must never reach the wire before the terminal frame.
LEAK_PROMPT = "SENTINEL_PROMPT_You_are_a_specialist_risk_analyst"
LEAK_EVIDENCE = "SENTINEL_EVIDENCE_BODY_10K_risk_factors_text"
LEAK_SYNTH = "SENTINEL_SYNTHESIS_FRAGMENT_bull_thesis_partial"


def _stub_pipeline(*, raise_at_end: str = "", slow: float = 0.03):
    """A route_question stand-in that records the real stage sequence."""
    def _run(request):
        record_stage("routing", 0.1)
        time.sleep(slow)
        record_stage("retrieval_total", 80.0)
        time.sleep(slow)
        for agent in ("market", "question_answerer", "macro",
                      "valuation", "quality", "risk"):
            record_stage(f"agent.{agent}", 100.0)
            time.sleep(slow / 3)
        record_stage("agent_total", 500.0)
        time.sleep(slow)
        if raise_at_end:
            raise RuntimeError(raise_at_end)
        record_stage("synthesis", 400.0)
        time.sleep(slow)
        record_stage("integrity_validation", 1.0)
        return AgentAnswerResponse(
            company="MSFT", request_id="rid-test", agents_used=["risk"],
            answer={"investment_thesis": {"ticker": "MSFT",
                                          "direct_answer": "final answer text"}},
        )
    return _run


@pytest.fixture
def client(monkeypatch):
    logging.disable(logging.CRITICAL)
    monkeypatch.setattr(_api(), "route_question", _stub_pipeline())
    from app.main import app
    yield TestClient(app)
    logging.disable(logging.NOTSET)


def _frames(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


# ── Negotiation / backward compatibility ─────────────────────────────────────

class TestNegotiation:
    @pytest.mark.parametrize("header", [
        None, "", "*/*", "application/json", "text/html, */*;q=0.8",
        "application/json;q=0.9",
    ])
    def test_non_negotiating_callers_never_get_ndjson(self, header):
        assert progressive_requested(header) is False

    @pytest.mark.parametrize("header", [
        "application/x-ndjson", "application/x-ndjson;q=1.0",
        "application/json, application/x-ndjson", "APPLICATION/X-NDJSON",
    ])
    def test_explicit_opt_in_is_honoured(self, header):
        assert progressive_requested(header) is True

    def test_legacy_response_is_a_single_json_object(self, client):
        """The frontend slices from the first '{' to the end and parses once;
        the validation runner calls resp.json(). Both need exactly one doc."""
        r = client.post("/ask", json=BODY)
        assert r.headers["content-type"].startswith("application/json")
        text = r.text
        assert isinstance(json.loads(text[text.index("{"):]), dict)

    def test_progressive_response_is_ndjson(self, client):
        r = client.post("/ask", json=BODY, headers=NDJSON)
        assert r.headers["content-type"].startswith(PROGRESS_MEDIA_TYPE)
        assert len(_frames(r)) > 1


# ── Final-response identity (the hard invariant) ─────────────────────────────

class TestFinalIdentity:
    def test_final_data_equals_legacy_body(self, client):
        legacy_text = client.post("/ask", json=BODY).text
        legacy = json.loads(legacy_text[legacy_text.index("{"):])
        final = dict(_frames(client.post("/ask", json=BODY, headers=NDJSON))[-1]["data"])
        # _observability carries per-request ids and timings that differ between
        # any two requests, so it is compared for shape rather than equality.
        assert set(legacy) == set(final)
        legacy.pop("_observability", None)
        final.pop("_observability", None)
        assert legacy == final

    def test_final_frame_is_last_and_terminal(self, client):
        frames = _frames(client.post("/ask", json=BODY, headers=NDJSON))
        assert frames[-1]["type"] == "final"
        assert sum(1 for f in frames if f["type"] == "final") == 1

    def test_progress_precedes_final(self, client):
        frames = _frames(client.post("/ask", json=BODY, headers=NDJSON))
        assert frames[0]["type"] == "progress"
        assert frames.index(frames[-1]) == len(frames) - 1

    def test_final_payload_is_passed_through_untouched(self):
        payload = {"company": "MSFT", "answer": {"deep": {"nested": [1, 2]}}}
        assert final_frame(payload)["data"] is payload


# ── Nothing analytical may leak early ────────────────────────────────────────

class TestNoLeakage:
    def test_progress_frames_use_only_allowlisted_keys(self, client):
        for frame in _frames(client.post("/ask", json=BODY, headers=NDJSON)):
            if frame["type"] != "progress":
                continue
            assert set(frame) <= ALLOWED_PROGRESS_KEYS, frame

    def test_no_prompt_evidence_or_synthesis_text_before_final(self, monkeypatch):
        """Stage detail carrying sentinels must not reach any progress frame."""
        logging.disable(logging.CRITICAL)

        def leaky(request):
            record_stage("routing", 0.1, detail={"note": LEAK_PROMPT})
            time.sleep(0.05)
            record_stage("retrieval_total", 80.0, detail={"note": LEAK_EVIDENCE})
            time.sleep(0.05)
            record_stage("agent_total", 500.0)
            record_stage("synthesis", 400.0, detail={"note": LEAK_SYNTH})
            record_stage("integrity_validation", 1.0)
            return AgentAnswerResponse(company="MSFT", request_id="r",
                                       agents_used=[], answer={})
        monkeypatch.setattr(_api(), "route_question", leaky)
        from app.main import app
        r = TestClient(app).post("/ask", json=BODY, headers=NDJSON)
        logging.disable(logging.NOTSET)

        body_before_final = r.text.split('{"type":"final"')[0]
        for sentinel in (LEAK_PROMPT, LEAK_EVIDENCE, LEAK_SYNTH):
            assert sentinel not in body_before_final

    def test_snapshot_never_exposes_stage_detail(self):
        from app.observability import StageRecord
        t = RequestTrace("r")
        t.stages.append(StageRecord(stage="synthesis", status="ok",
                                    detail={"note": LEAK_SYNTH}))
        assert LEAK_SYNTH not in json.dumps(t.progress_snapshot())

    def test_error_frame_omits_the_exception_message(self, monkeypatch):
        logging.disable(logging.CRITICAL)
        monkeypatch.setattr(_api(), "route_question",
                            _stub_pipeline(raise_at_end=LEAK_PROMPT))
        from app.main import app
        r = TestClient(app).post("/ask", json=BODY, headers=NDJSON)
        logging.disable(logging.NOTSET)
        assert LEAK_PROMPT not in r.text
        assert _frames(r)[-1]["error"]["error_class"] == "RuntimeError"

    def test_error_frame_truncates_and_keeps_only_safe_fields(self):
        frame = error_frame("x" * 999, error_class="y" * 999, stage="z" * 999)
        assert set(frame["error"]) <= {"message", "error_class", "stage"}
        assert len(frame["error"]["message"]) <= 300


# ── Trace → event mapping ────────────────────────────────────────────────────

class TestProjection:
    def _snapshot(self, stages, elapsed=100.0, sources=5):
        return {"elapsed_ms": elapsed, "source_count": sources,
                "stages": [{"stage": s, "status": "ok"} for s in stages]}

    def test_stage_sequence_is_pipeline_ordered(self, client):
        frames = _frames(client.post("/ask", json=BODY, headers=NDJSON))
        order = [(f["stage"], f["status"]) for f in frames if f["type"] == "progress"]
        assert order[0] == ("request", "running")
        seen = [s for s, st in order if st == "complete"]
        for earlier, later in (("routing", "retrieval"), ("retrieval", "agents"),
                               ("agents", "synthesis")):
            if earlier in seen and later in seen:
                assert seen.index(earlier) < seen.index(later)

    def test_request_frame_is_running_not_complete(self, client):
        """The request has only just begun at generator start — marking it
        complete there would be misleading, not just imprecise."""
        frames = _frames(client.post("/ask", json=BODY, headers=NDJSON))
        request_frames = [f for f in frames
                          if f["type"] == "progress" and f["stage"] == "request"]
        assert request_frames == [{
            "type": "progress", "stage": "request", "status": "running",
            "elapsed_ms": request_frames[0]["elapsed_ms"],
        }]

    def test_no_duplicate_frames(self, client):
        frames = _frames(client.post("/ask", json=BODY, headers=NDJSON))
        keys = [(f.get("stage"), f.get("status"), f.get("agents_complete"))
                for f in frames if f["type"] == "progress"]
        assert len(keys) == len(set(keys))

    def test_projector_emits_nothing_for_an_empty_trace(self):
        assert ProgressProjector().project(self._snapshot([])) == []

    def test_projector_reports_source_count_on_retrieval(self):
        p = ProgressProjector()
        frames = p.project(self._snapshot(["routing", "retrieval_total"], sources=7))
        retrieval = [f for f in frames
                     if f["stage"] == "retrieval" and f["status"] == "complete"]
        assert retrieval and retrieval[0]["source_count"] == 7

    def test_projector_is_idempotent_across_repeated_snapshots(self):
        p = ProgressProjector()
        snap = self._snapshot(["routing", "retrieval_total"])
        first = p.project(snap)
        assert first and p.project(snap) == []

    def test_agent_count_matches_the_router_pool(self):
        """A drifted count would silently misreport 'n of m'."""
        import inspect

        from app.progress import AGENT_COUNT
        from app.services import router_service
        src = inspect.getsource(router_service)
        assert "ThreadPoolExecutor(max_workers=6)" in src
        assert AGENT_COUNT == 6

    def test_frames_are_newline_delimited_and_single_line(self):
        raw = encode_frame(progress_frame("agents", "running", elapsed_ms=1.0,
                                          agents_complete=2))
        assert raw.endswith(b"\n")
        assert raw.count(b"\n") == 1


# ── Error / truncation semantics ─────────────────────────────────────────────

class TestErrorSemantics:
    def test_pipeline_exception_yields_a_terminal_error_frame(self, monkeypatch):
        logging.disable(logging.CRITICAL)
        monkeypatch.setattr(_api(), "route_question",
                            _stub_pipeline(raise_at_end="boom"))
        from app.main import app
        r = TestClient(app).post("/ask", json=BODY, headers=NDJSON)
        logging.disable(logging.NOTSET)
        frames = _frames(r)
        assert frames[-1]["type"] == "error"
        assert not any(f["type"] == "final" for f in frames)

    def test_legacy_exception_still_returns_the_documented_error_body(
            self, monkeypatch):
        """Pre-existing gap fixed in this sprint: the keepalive loop sat outside
        the try, so an exception raised mid-window escaped the generator."""
        logging.disable(logging.CRITICAL)
        monkeypatch.setattr(_api(), "route_question",
                            _stub_pipeline(raise_at_end="boom"))
        from app.main import app
        r = TestClient(app).post("/ask", json=BODY)
        logging.disable(logging.NOTSET)
        assert json.loads(r.text[r.text.index("{"):])["error"] == \
            "Question routing failed"

    def test_truncated_stream_is_rejected_by_the_runner(self):
        from validation.runner import IncompleteStreamError, extract_final_payload
        truncated = encode_frame(
            progress_frame("agents", "running", elapsed_ms=1.0)).decode()
        with pytest.raises(IncompleteStreamError):
            extract_final_payload(truncated)

    def test_empty_stream_is_rejected(self):
        from validation.runner import IncompleteStreamError, extract_final_payload
        with pytest.raises(IncompleteStreamError):
            extract_final_payload("")

    def test_final_frame_without_payload_is_rejected(self):
        from validation.runner import IncompleteStreamError, extract_final_payload
        with pytest.raises(IncompleteStreamError):
            extract_final_payload(json.dumps({"type": "final"}))

    def test_error_frame_raises_rather_than_scoring_as_success(self):
        from validation.runner import extract_final_payload
        with pytest.raises(RuntimeError, match="backend error frame"):
            extract_final_payload(json.dumps(
                {"type": "error", "error": {"message": "failed",
                                            "error_class": "RuntimeError"}}))

    def test_progress_frames_are_discarded_by_the_runner(self):
        from validation.runner import extract_final_payload
        stream = "\n".join([
            json.dumps({"type": "progress", "stage": "retrieval",
                        "status": "complete"}),
            "",                                    # heartbeat no-op
            json.dumps({"type": "final", "data": {"company": "MSFT"}}),
        ])
        assert extract_final_payload(stream) == {"company": "MSFT"}


# ── The analytical pipeline must be untouched ────────────────────────────────

class TestPipelineUntouched:
    def test_no_model_call_is_introduced_by_the_protocol(self):
        import inspect

        from app import progress
        src = inspect.getsource(progress)
        for forbidden in ("model_client", "chat.completions", "openai",
                          "get_structured_response"):
            assert forbidden not in src

    def test_progress_module_never_imports_analytical_code(self):
        import inspect

        from app import progress
        src = inspect.getsource(progress)
        for forbidden in ("thesis_synthesizer", "risk_agent", "conviction_modeler",
                          "thesis_polisher", "signal_ranker"):
            assert forbidden not in src

    def test_route_question_signature_is_unchanged(self):
        import inspect

        from app.services.router_service import route_question
        params = list(inspect.signature(route_question).parameters)
        assert params == ["request"]

    def test_stub_pipeline_makes_no_extra_call(self, client):
        """Both modes invoke route_question exactly once."""
        calls = {"n": 0}
        inner = _stub_pipeline()

        def counting(request):
            calls["n"] += 1
            return inner(request)

        _api().route_question = counting
        client.post("/ask", json=BODY)
        client.post("/ask", json=BODY, headers=NDJSON)
        assert calls["n"] == 2
