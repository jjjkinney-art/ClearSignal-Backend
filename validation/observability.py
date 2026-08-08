"""Aggregation of backend `_observability` blocks across a benchmark run.

Sprint 3A. The backend now reports per-request stage timings, model-call token
usage and provider latency; this turns 36 of those blocks into the summary that
answers "where does the p95 come from".

Every function here is tolerant of responses that predate Sprint 3A: a missing
`_observability` block, a missing `stages` list (production omits stage detail)
or an unparseable value yields "unknown" rather than an exception, so a mixed
run of old and new responses still produces a report.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

# Bottleneck labels. Diagnostic only — Sprint 3A measures, it does not optimize.
BOTTLENECK_ROUTING = "routing-bound"
BOTTLENECK_RETRIEVAL = "retrieval-bound"
BOTTLENECK_AGENT = "agent-bound"
BOTTLENECK_SYNTHESIS = "synthesis-bound"
BOTTLENECK_PROVIDER = "provider-bound"
BOTTLENECK_MIXED = "mixed"
BOTTLENECK_UNKNOWN = "unknown"

# Stage name -> bottleneck label for the coarse spans.
_STAGE_BUCKET = {
    "routing": BOTTLENECK_ROUTING,
    "retrieval_total": BOTTLENECK_RETRIEVAL,
    "agent_total": BOTTLENECK_AGENT,
    "synthesis": BOTTLENECK_SYNTHESIS,
}
# A single stage must own at least this share of measured time to be called the
# bottleneck; below it the query is "mixed".
_DOMINANCE_RATIO = 0.45
# A provider owning this much of retrieval reclassifies retrieval-bound as
# provider-bound — the distinction between "retrieval is slow" and "one
# provider is slow" is the whole point of the label.
_PROVIDER_DOMINANCE_RATIO = 0.60


def get_observability(raw: Any) -> Optional[Dict[str, Any]]:
    """Extract the `_observability` block from a raw /ask response, or None."""
    if not isinstance(raw, dict):
        return None
    block = raw.get("_observability")
    if isinstance(block, dict):
        return block
    answer = raw.get("answer")
    if isinstance(answer, dict):
        for key in ("_observability", "investment_thesis"):
            candidate = answer.get(key)
            if key == "_observability" and isinstance(candidate, dict):
                return candidate
            if isinstance(candidate, dict) and isinstance(
                candidate.get("_observability"), dict
            ):
                return candidate["_observability"]
    return None


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def stage_durations(block: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Map stage name -> duration_ms for stages that actually ran.

    Skipped stages are excluded: they carry no duration, and counting them as
    zero would drag every percentile toward zero.
    """
    out: Dict[str, float] = {}
    if not block:
        return out
    for entry in block.get("stages") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") == "skipped":
            continue
        duration = _num(entry.get("duration_ms"))
        name = entry.get("stage")
        if duration is None or not name:
            continue
        # Repeated stage names (retries) accumulate rather than overwrite.
        out[str(name)] = out.get(str(name), 0.0) + duration
    return out


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = min(int(round((pct / 100.0) * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[index], 2)


def summarize_stage(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"count": 0, "median": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "median": round(statistics.median(values), 2),
        "p95": percentile(values, 95),
        "max": round(max(values), 2),
    }


def slowest_stage(block: Optional[Dict[str, Any]]) -> Optional[str]:
    """Name of the single slowest stage, ignoring the coarse roll-up spans that
    contain the others (they would always win)."""
    durations = stage_durations(block)
    leaf = {k: v for k, v in durations.items()
            if k not in ("retrieval_total", "agent_total")}
    if not leaf:
        return None
    return max(leaf.items(), key=lambda kv: kv[1])[0]


def slowest_agent(block: Optional[Dict[str, Any]]) -> Optional[str]:
    agents = {k: v for k, v in stage_durations(block).items()
              if k.startswith("agent.")}
    if not agents:
        return None
    return max(agents.items(), key=lambda kv: kv[1])[0]


def token_totals(block: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    """Token usage for one response.

    Prefers the backend's own `token_totals`; falls back to summing model
    calls. Returns None per field when nothing reported it, keeping "not
    reported" distinct from "zero".
    """
    if not block:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    reported = block.get("token_totals")
    if isinstance(reported, dict):
        return {k: reported.get(k) if isinstance(reported.get(k), int) else None
                for k in ("input_tokens", "output_tokens", "total_tokens")}
    out: Dict[str, Optional[int]] = {}
    calls = block.get("model_calls") or []
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        values = [c.get(key) for c in calls
                  if isinstance(c, dict) and isinstance(c.get(key), int)]
        out[key] = sum(values) if values else None
    return out


def tokens_by_stage(block: Optional[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not block:
        return out
    for call in block.get("model_calls") or []:
        if not isinstance(call, dict):
            continue
        total = call.get("total_tokens")
        if isinstance(total, int):
            out[str(call.get("stage") or "unknown")] = (
                out.get(str(call.get("stage") or "unknown"), 0) + total
            )
    return out


def provider_latencies(block: Optional[Dict[str, Any]]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    if not block:
        return out
    for call in block.get("provider_calls") or []:
        if not isinstance(call, dict):
            continue
        duration = _num(call.get("duration_ms"))
        if duration is None:
            continue
        out.setdefault(str(call.get("provider") or "unknown"), []).append(duration)
    return out


def retry_and_error_counts(block: Optional[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"model_retries": 0, "model_errors": 0, "model_timeouts": 0,
              "provider_retries": 0, "provider_errors": 0, "stage_timeouts": 0}
    if not block:
        return counts
    for call in block.get("model_calls") or []:
        if not isinstance(call, dict):
            continue
        counts["model_retries"] += int(call.get("retry_count") or 0)
        if call.get("status") == "error":
            counts["model_errors"] += 1
        elif call.get("status") == "timeout":
            counts["model_timeouts"] += 1
    for call in block.get("provider_calls") or []:
        if not isinstance(call, dict):
            continue
        counts["provider_retries"] += int(call.get("retry_count") or 0)
        if call.get("status") in ("error", "timeout"):
            counts["provider_errors"] += 1
    for entry in block.get("stages") or []:
        if isinstance(entry, dict) and entry.get("status") == "timeout":
            counts["stage_timeouts"] += 1
    return counts


def classify_bottleneck(block: Optional[Dict[str, Any]]) -> str:
    """Label the dominant latency source for one query.

    Deterministic and purely diagnostic. Returns `unknown` whenever the
    response carries no usable stage timings, rather than guessing.
    """
    durations = stage_durations(block)
    if not durations:
        return BOTTLENECK_UNKNOWN
    buckets = {label: 0.0 for label in
               (BOTTLENECK_ROUTING, BOTTLENECK_RETRIEVAL,
                BOTTLENECK_AGENT, BOTTLENECK_SYNTHESIS)}
    for name, duration in durations.items():
        label = _STAGE_BUCKET.get(name)
        if label:
            buckets[label] += duration
    measured = sum(buckets.values())
    if measured <= 0:
        return BOTTLENECK_UNKNOWN

    top_label, top_value = max(buckets.items(), key=lambda kv: kv[1])
    if top_value / measured < _DOMINANCE_RATIO:
        return BOTTLENECK_MIXED

    if top_label == BOTTLENECK_RETRIEVAL:
        # One provider dominating retrieval is a more actionable diagnosis
        # than "retrieval is slow".
        latencies = provider_latencies(block)
        if latencies:
            slowest = max(
                ((p, max(v)) for p, v in latencies.items()), key=lambda kv: kv[1],
            )
            if top_value > 0 and slowest[1] / top_value >= _PROVIDER_DOMINANCE_RATIO:
                return BOTTLENECK_PROVIDER
    return top_label


def aggregate(outcomes: List[Any]) -> Dict[str, Any]:
    """Aggregate observability across a run's completed outcomes."""
    per_stage: Dict[str, List[float]] = {}
    end_to_end: List[float] = []
    bottlenecks: Dict[str, int] = {}
    slowest_stages: Dict[str, int] = {}
    slowest_agents: Dict[str, int] = {}
    provider_all: Dict[str, List[float]] = {}
    tokens_stage_all: Dict[str, int] = {}
    tokens_by_query: List[Dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    token_reported = False
    counts = {"model_retries": 0, "model_errors": 0, "model_timeouts": 0,
              "provider_retries": 0, "provider_errors": 0, "stage_timeouts": 0}
    with_block = 0

    for outcome in outcomes:
        block = get_observability(getattr(outcome, "raw_response", None))
        fixture_id = getattr(getattr(outcome, "fixture", None), "id", "?")
        if not block:
            bottlenecks[BOTTLENECK_UNKNOWN] = bottlenecks.get(BOTTLENECK_UNKNOWN, 0) + 1
            continue
        with_block += 1

        total_ms = _num(block.get("total_duration_ms"))
        if total_ms is not None:
            end_to_end.append(total_ms)
        for name, duration in stage_durations(block).items():
            per_stage.setdefault(name, []).append(duration)

        label = classify_bottleneck(block)
        bottlenecks[label] = bottlenecks.get(label, 0) + 1
        stage_name = slowest_stage(block)
        if stage_name:
            slowest_stages[stage_name] = slowest_stages.get(stage_name, 0) + 1
        agent_name = slowest_agent(block)
        if agent_name:
            slowest_agents[agent_name] = slowest_agents.get(agent_name, 0) + 1

        for provider, values in provider_latencies(block).items():
            provider_all.setdefault(provider, []).extend(values)
        for stage_key, value in tokens_by_stage(block).items():
            tokens_stage_all[stage_key] = tokens_stage_all.get(stage_key, 0) + value

        query_tokens = token_totals(block)
        if any(isinstance(v, int) for v in query_tokens.values()):
            token_reported = True
            for key in totals:
                if isinstance(query_tokens.get(key), int):
                    totals[key] += query_tokens[key]
        tokens_by_query.append({"id": fixture_id, **query_tokens})

        for key, value in retry_and_error_counts(block).items():
            counts[key] += value

    return {
        "responses_with_observability": with_block,
        "responses_total": len(outcomes),
        "end_to_end": summarize_stage(end_to_end),
        "stages": {name: summarize_stage(values)
                   for name, values in sorted(per_stage.items())},
        "bottlenecks": bottlenecks,
        "slowest_stage_counts": slowest_stages,
        "slowest_agent_counts": slowest_agents,
        "providers": {name: summarize_stage(values)
                      for name, values in sorted(provider_all.items())},
        "tokens_total": totals if token_reported else None,
        "tokens_by_stage": tokens_stage_all,
        "tokens_by_query": tokens_by_query,
        "counts": counts,
    }


def observability_md(outcomes: List[Any]) -> str:
    """Render `observability_summary.md`."""
    data = aggregate(outcomes)
    lines = ["# Observability Summary", ""]
    lines.append(
        f"- Responses with an `_observability` block: "
        f"**{data['responses_with_observability']}/{data['responses_total']}**"
    )
    if data["responses_with_observability"] == 0:
        lines += [
            "",
            "No response carried observability metadata. This is expected for "
            "runs recorded before Sprint 3A, or when the backend omits stage "
            "detail in production.",
            "",
        ]
        return "\n".join(lines) + "\n"

    e2e = data["end_to_end"]
    lines += ["", "## End-to-end (backend-measured)"]
    lines.append(f"- median: {e2e['median']} ms · p95: {e2e['p95']} ms · max: {e2e['max']} ms")

    lines += ["", "## Stage latency (ms)", "",
              "| stage | n | median | p95 | max |", "|---|---|---|---|---|"]
    for name, summary in data["stages"].items():
        lines.append(
            f"| `{name}` | {summary['count']} | {summary['median']} | "
            f"{summary['p95']} | {summary['max']} |"
        )

    if data["providers"]:
        lines += ["", "## Provider latency (ms)", "",
                  "| provider | calls | median | p95 | max |", "|---|---|---|---|---|"]
        for name, summary in data["providers"].items():
            lines.append(
                f"| `{name}` | {summary['count']} | {summary['median']} | "
                f"{summary['p95']} | {summary['max']} |"
            )

    lines += ["", "## Bottleneck classification"]
    for label, count in sorted(data["bottlenecks"].items(),
                               key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{label}`: {count}")

    if data["slowest_stage_counts"]:
        lines += ["", "## Slowest stage (times it was the slowest in a query)"]
        for name, count in sorted(data["slowest_stage_counts"].items(),
                                  key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{name}`: {count}")

    if data["slowest_agent_counts"]:
        lines += ["", "## Slowest agent"]
        for name, count in sorted(data["slowest_agent_counts"].items(),
                                  key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{name}`: {count}")

    lines += ["", "## Token usage"]
    if data["tokens_total"]:
        totals = data["tokens_total"]
        lines.append(
            f"- Run total — input: {totals['input_tokens']} · "
            f"output: {totals['output_tokens']} · total: {totals['total_tokens']}"
        )
        if data["tokens_by_stage"]:
            for name, value in sorted(data["tokens_by_stage"].items(),
                                      key=lambda kv: -kv[1]):
                lines.append(f"- `{name}`: {value}")
    else:
        lines.append("- (no model call reported token usage)")

    lines += ["", "## Retries, errors and timeouts"]
    for key, value in data["counts"].items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines) + "\n"
