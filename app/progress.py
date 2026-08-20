"""Progressive response protocol (Sprint 3C.1A).

Why
---
Sprint 3C measured the pipeline: evidence is ready at ~101 ms, all agents
finish at ~9,656 ms, and the final response lands at ~21,467 ms — but on 82.4%
of requests the first byte a caller receives *is* the complete answer. The
interface fills that 21-second gap with a fixed 480 ms timer that advances
captions unrelated to real backend state.

This module emits the real state instead.

What it deliberately does NOT do
--------------------------------
Sprint 3C also established that raw synthesis cannot be streamed as final
content: ``polish_thesis`` materially rewrites all seven prose fields
(valuation language, stripped percentages, dropped sentences, fiscal-year
expansion), and ``direct_answer`` is replaced wholesale by the
question-answerer output afterwards. So **no analytical prose is exposed
before the terminal frame**. Progress frames carry stage names, statuses and
counts — nothing else.

Frames are built from an explicit allowlist constructed here, never by passing
trace ``detail`` through a filter. A filter can be widened by accident; a
constructor that only ever writes known keys cannot.

Backward compatibility
----------------------
Both current consumers require exactly one JSON document in the body: the
validation runner calls ``resp.json()``, and the frontend takes
``rawText.indexOf("{")`` and parses to the end. Emitting NDJSON by default
would break both. Progressive mode is therefore strictly opt-in via an
explicit ``Accept: application/x-ndjson`` — a caller sending ``*/*`` (the
browser and ``requests`` default) always gets the legacy bytes unchanged.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# One JSON object per line. Explicit frame boundaries, and a truncated stream
# is detectable because the terminal frame is simply absent.
PROGRESS_MEDIA_TYPE = "application/x-ndjson"
LEGACY_MEDIA_TYPE = "application/json"

FRAME_PROGRESS = "progress"
FRAME_FINAL = "final"
FRAME_ERROR = "error"

# Semantic stages, in pipeline order. These are the only stage names a caller
# will ever see; internal trace names are mapped onto them.
STAGE_REQUEST = "request"
STAGE_ROUTING = "routing"
STAGE_RETRIEVAL = "retrieval"
STAGE_AGENTS = "agents"
STAGE_SYNTHESIS = "synthesis"
STAGE_FINALIZING = "finalizing"

ORDERED_STAGES = (STAGE_REQUEST, STAGE_ROUTING, STAGE_RETRIEVAL,
                  STAGE_AGENTS, STAGE_SYNTHESIS, STAGE_FINALIZING)

STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"

# Internal trace stage -> semantic stage whose COMPLETION it marks. The
# pipeline is strictly ordered (routing -> retrieval -> agents -> synthesis ->
# integrity), so a completion also implies the next stage is now running. That
# inference is read off the real execution order, not invented.
_TRACE_TO_STAGE = {
    "routing": STAGE_ROUTING,
    "retrieval_total": STAGE_RETRIEVAL,
    "agent_total": STAGE_AGENTS,
    "synthesis": STAGE_SYNTHESIS,
    "integrity_validation": STAGE_FINALIZING,
}

# Total specialist agents dispatched by the router pool. Used only to report
# "n of m complete"; a mismatch would misreport progress, so it is asserted
# against the router's own task table in the test suite.
AGENT_COUNT = 6

# The keys a progress frame may ever contain. Anything else is a bug, and the
# test suite asserts emitted frames never exceed this set.
ALLOWED_PROGRESS_KEYS = frozenset({
    "type", "stage", "status", "elapsed_ms", "agents_complete",
    "agents_total", "source_count",
})


def progressive_requested(accept_header: Optional[str]) -> bool:
    """Whether the caller explicitly opted into the progressive protocol.

    Requires the exact ``application/x-ndjson`` token. A wildcard ``*/*`` — what
    browsers and ``requests`` send by default — is deliberately NOT a match, so
    every existing caller keeps the legacy response byte-for-byte.
    """
    if not accept_header:
        return False
    for part in str(accept_header).split(","):
        if part.split(";")[0].strip().lower() == PROGRESS_MEDIA_TYPE:
            return True
    return False


def encode_frame(frame: Dict[str, Any]) -> bytes:
    """Serialize one NDJSON frame.

    ``separators`` is pinned so a frame never contains a stray newline from
    pretty-printing, which would split one frame into two on the wire.
    """
    return (json.dumps(frame, separators=(",", ":"), default=str) + "\n").encode()


def progress_frame(stage: str, status: str, *, elapsed_ms: float,
                   agents_complete: Optional[int] = None,
                   source_count: Optional[int] = None) -> Dict[str, Any]:
    """Build one progress frame from an explicit allowlist of safe fields."""
    frame: Dict[str, Any] = {
        "type": FRAME_PROGRESS,
        "stage": stage,
        "status": status,
        "elapsed_ms": round(float(elapsed_ms), 1),
    }
    if agents_complete is not None:
        frame["agents_complete"] = int(agents_complete)
        frame["agents_total"] = AGENT_COUNT
    if source_count is not None:
        frame["source_count"] = int(source_count)
    return frame


def final_frame(data: Any) -> Dict[str, Any]:
    """The authoritative terminal frame.

    ``data`` is the exact object the legacy path serializes — it is passed
    through untouched so the progressive and legacy payloads cannot diverge.
    """
    return {"type": FRAME_FINAL, "data": data}


def error_frame(message: str, *, error_class: str = "",
                stage: str = "") -> Dict[str, Any]:
    """Terminal error frame.

    Carries a class name and stage, never an exception payload: a raised
    message can contain a prompt fragment or an upstream response body.
    """
    err: Dict[str, Any] = {"message": str(message)[:300]}
    if error_class:
        err["error_class"] = str(error_class)[:80]
    if stage:
        err["stage"] = str(stage)[:40]
    return {"type": FRAME_ERROR, "error": err}


class ProgressProjector:
    """Maps RequestTrace state onto the semantic event stream.

    Holds only the set of events already emitted — it is a projection of the
    trace, not a second state machine. If the trace never records a stage, no
    event for it is ever invented.
    """

    def __init__(self) -> None:
        self._emitted: set = set()

    def _mark(self, stage: str, status: str) -> bool:
        """True the first time this (stage, status) is seen — dedupe."""
        key = (stage, status)
        if key in self._emitted:
            return False
        self._emitted.add(key)
        return True

    def initial(self, elapsed_ms: float) -> List[Dict[str, Any]]:
        """The opening frame, emitted before the pipeline reports anything.

        This is the one event not derived from a trace transition. It reports
        `request:running`, not `request:complete` — the request has only just
        begun at this point, and the vocabulary elsewhere in this module is
        `running`/`complete`, so `running` is what "not yet finished" means
        here rather than introducing a third status value.
        """
        out = []
        if self._mark(STAGE_REQUEST, STATUS_RUNNING):
            out.append(progress_frame(STAGE_REQUEST, STATUS_RUNNING,
                                      elapsed_ms=elapsed_ms))
        if self._mark(STAGE_ROUTING, STATUS_RUNNING):
            out.append(progress_frame(STAGE_ROUTING, STATUS_RUNNING,
                                      elapsed_ms=elapsed_ms))
        return out

    def project(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """New frames implied by a trace snapshot since the last call."""
        frames: List[Dict[str, Any]] = []
        elapsed = float(snapshot.get("elapsed_ms") or 0.0)
        stages = snapshot.get("stages") or []

        completed_traces = {
            s.get("stage") for s in stages
            if s.get("stage") and s.get("status") not in (None, "skipped")
        }
        agents_done = sum(
            1 for s in stages
            if str(s.get("stage", "")).startswith("agent.")
        )

        for trace_name, semantic in _TRACE_TO_STAGE.items():
            if trace_name not in completed_traces:
                continue
            if self._mark(semantic, STATUS_COMPLETE):
                kwargs: Dict[str, Any] = {}
                if semantic == STAGE_RETRIEVAL:
                    kwargs["source_count"] = snapshot.get("source_count") or 0
                if semantic == STAGE_AGENTS:
                    kwargs["agents_complete"] = min(agents_done, AGENT_COUNT)
                frames.append(progress_frame(
                    semantic, STATUS_COMPLETE, elapsed_ms=elapsed, **kwargs))

                nxt = _next_stage(semantic)
                if nxt and self._mark(nxt, STATUS_RUNNING):
                    frames.append(progress_frame(
                        nxt, STATUS_RUNNING, elapsed_ms=elapsed))

        # Per-agent progress while the pool is still running. Reported as a
        # count rather than named agents: which specialist finished first is
        # execution detail, and naming them would leak pipeline shape without
        # telling the caller anything actionable.
        if agents_done and STAGE_AGENTS not in {s for s, _ in self._emitted
                                                if _ == STATUS_COMPLETE}:
            key = (STAGE_AGENTS, f"{STATUS_RUNNING}:{agents_done}")
            if key not in self._emitted:
                self._emitted.add(key)
                frames.append(progress_frame(
                    STAGE_AGENTS, STATUS_RUNNING, elapsed_ms=elapsed,
                    agents_complete=min(agents_done, AGENT_COUNT)))

        return frames


def _next_stage(stage: str) -> Optional[str]:
    try:
        idx = ORDERED_STAGES.index(stage)
    except ValueError:
        return None
    if idx + 1 < len(ORDERED_STAGES):
        return ORDERED_STAGES[idx + 1]
    return None
