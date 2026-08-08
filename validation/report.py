"""Objective 9 — output artifact generation."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from .models import QueryOutcome, Severity
from .severity import all_findings_flat, count_by_severity, findings_by_code


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_artifacts(output_dir: Path, outcomes: List[QueryOutcome]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. validation_results.json — full machine-readable results (no raw
    #    response bodies inline; those live under raw_responses/<id>.json).
    results_json = {
        "run_output_dir": str(output_dir),
        "total_queries": len(outcomes),
        "results": [o.to_dict(include_raw=False) for o in outcomes],
    }
    _write(output_dir / "validation_results.json", json.dumps(results_json, indent=2))

    # 2. validation_summary.md
    _write(output_dir / "validation_summary.md", _summary_md(outcomes))

    # 3. failures_by_severity.md
    _write(output_dir / "failures_by_severity.md", _failures_by_severity_md(outcomes))

    # 4. failures_by_company.md
    _write(output_dir / "failures_by_company.md", _failures_by_company_md(outcomes))

    # 5. latency_summary.md
    _write(output_dir / "latency_summary.md", _latency_summary_md(outcomes))

    # 6. observability_summary.md (Sprint 3A) — backend-reported stage timings,
    #    token usage and provider latency. Written as a NEW artifact so every
    #    existing file keeps its exact format and any downstream parsing of
    #    them is unaffected. Degrades to a one-line note for runs whose
    #    responses predate Sprint 3A.
    try:
        from .observability import observability_md
        _write(output_dir / "observability_summary.md", observability_md(outcomes))
    except Exception:
        # An observability-reporting bug must never cost us the correctness
        # artifacts, which are the reason the run exists.
        pass


def _summary_md(outcomes: List[QueryOutcome]) -> str:
    total = len(outcomes)
    completed = sum(1 for o in outcomes if o.status == "completed")
    failed_requests = total - completed
    passed = sum(1 for o in outcomes if o.passed())
    pass_rate = (passed / total * 100) if total else 0.0

    sev_counts = count_by_severity(outcomes)
    latencies = [o.elapsed_s for o in outcomes if o.status == "completed"]
    median_lat = statistics.median(latencies) if latencies else 0.0
    p95_lat = _percentile(latencies, 0.95) if latencies else 0.0

    by_company: Dict[str, int] = defaultdict(int)
    for o in outcomes:
        if not o.passed():
            by_company[o.fixture.company] += 1
    worst_companies = sorted(by_company.items(), key=lambda kv: -kv[1])[:5]

    code_counts = findings_by_code(outcomes)
    top_codes = sorted(code_counts.items(), key=lambda kv: -kv[1])[:8]

    # Missing-field rates across the tracked optional fields.
    field_totals: Dict[str, int] = defaultdict(int)
    field_present: Dict[str, int] = defaultdict(int)
    completed_outcomes = [o for o in outcomes if o.status == "completed"]
    for o in completed_outcomes:
        for field_name, present in o.field_presence.items():
            field_totals[field_name] += 1
            if present:
                field_present[field_name] += 1

    # Provenance coverage across all quantitative_claims.
    provenance_counts: Counter = Counter()
    total_claims = 0
    for o in completed_outcomes:
        claims = (o.thesis or {}).get("quantitative_claims") or []
        for c in claims:
            if isinstance(c, dict):
                total_claims += 1
                provenance_counts[str(c.get("provenance", "unknown")).lower()] += 1

    # Threshold availability / invalidity rates.
    total_thresholds = 0
    unavailable_thresholds = 0
    contradictory_thresholds = 0
    for o in completed_outcomes:
        bands = (o.thesis or {}).get("decision_thresholds") or []
        for b in bands:
            if isinstance(b, dict):
                total_thresholds += 1
                if b.get("unavailable"):
                    unavailable_thresholds += 1
        contradictory_thresholds += sum(
            1 for f in o.findings if f.code == "threshold_shown_available_but_contradictory"
        )

    # Integrity aggregation. Three DIFFERENT questions are tracked separately —
    # conflating them is what made every Sprint 2A/2B run report "36/36 not
    # clean" and hid whether the Sprint 2B status ladder discriminates at all:
    #   * any_signal   — carries any violation or caveat (the broadest measure)
    #   * not_ok       — ok=false, i.e. a hard/blocking failure
    #   * status_counts— the ladder itself (clean/qualified/degraded/blocked)
    integrity_any_signal = 0
    integrity_not_ok = 0
    integrity_present = 0
    status_counts: Dict[str, int] = {
        "clean": 0, "qualified": 0, "degraded": 0, "blocked": 0, "missing/unknown": 0,
    }
    for o in completed_outcomes:
        integ = (o.thesis or {}).get("_integrity")
        if isinstance(integ, dict):
            integrity_present += 1
            if integ.get("ok") is False:
                integrity_not_ok += 1
            if integ.get("ok") is False or integ.get("violations") or integ.get("caveats"):
                integrity_any_signal += 1
            # Responses predating the Sprint 2B ladder have no `status`; they
            # are counted as missing/unknown rather than silently bucketed.
            status = integ.get("status")
            if isinstance(status, str) and status in status_counts and status != "missing/unknown":
                status_counts[status] += 1
            else:
                status_counts["missing/unknown"] += 1

    lines = [
        "# Validation Summary",
        "",
        f"- Total queries: **{total}**",
        f"- Completed: **{completed}**",
        f"- Failed requests (non-completed status): **{failed_requests}**",
        f"- Pass rate (completed, no CRITICAL/HIGH findings): **{pass_rate:.1f}%**",
        "",
        "## Findings by severity",
        f"- CRITICAL: {sev_counts.get('critical', 0)}",
        f"- HIGH: {sev_counts.get('high', 0)}",
        f"- MEDIUM: {sev_counts.get('medium', 0)}",
        f"- LOW: {sev_counts.get('low', 0)}",
        "",
        "## Latency",
        f"- Median: {median_lat:.2f}s",
        f"- p95: {p95_lat:.2f}s",
        "",
        "## Companies with the most failures",
    ]
    if worst_companies:
        for company, count in worst_companies:
            lines.append(f"- {company}: {count} failing quer{'y' if count == 1 else 'ies'}")
    else:
        lines.append("- (none — all queries passed)")

    lines += ["", "## Most common failure categories"]
    if top_codes:
        for code, count in top_codes:
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- (none)")

    lines += ["", "## Missing-field rates (of completed queries)"]
    for field_name in sorted(field_totals):
        tot = field_totals[field_name]
        present = field_present[field_name]
        missing_pct = ((tot - present) / tot * 100) if tot else 0.0
        lines.append(f"- {field_name}: {missing_pct:.0f}% missing ({present}/{tot} present)")

    lines += ["", "## Provenance coverage (quantitative_claims)"]
    if total_claims:
        for prov in ("reported", "derived", "estimated", "scenario", "heuristic"):
            n = provenance_counts.get(prov, 0)
            lines.append(f"- {prov}: {n} ({n / total_claims * 100:.0f}%)")
        unknown = total_claims - sum(provenance_counts.get(p, 0) for p in ("reported", "derived", "estimated", "scenario", "heuristic"))
        if unknown:
            lines.append(f"- unknown/invalid: {unknown} ({unknown / total_claims * 100:.0f}%)")
    else:
        lines.append("- (no quantitative_claims observed)")

    lines += ["", "## Threshold availability / invalidity"]
    if total_thresholds:
        lines.append(f"- Total structured thresholds observed: {total_thresholds}")
        lines.append(f"- Marked unavailable: {unavailable_thresholds} ({unavailable_thresholds / total_thresholds * 100:.0f}%)")
        lines.append(f"- Shown available but contradictory (should be 0): {contradictory_thresholds}")
    else:
        lines.append("- (no decision_thresholds observed)")

    lines += ["", "## Integrity status distribution"]
    if integrity_present:
        lines.append(f"- Responses with an _integrity block: {integrity_present}/{completed}")
        for name in ("clean", "qualified", "degraded", "blocked", "missing/unknown"):
            count = status_counts[name]
            lines.append(
                f"- `{name}`: {count} ({count / integrity_present * 100:.0f}%)"
            )
        lines += ["", "## Integrity signal rates"]
        lines.append(
            f"- Hard failures (ok=false): {integrity_not_ok} "
            f"({integrity_not_ok / integrity_present * 100:.0f}%)"
        )
        # Kept for continuity with earlier runs, but relabelled: this counts any
        # violation or caveat at all, so it is expected to stay high even on a
        # healthy run and must not be read as a failure rate.
        lines.append(
            f"- Any violation or caveat present (advisory, not a failure rate): "
            f"{integrity_any_signal} ({integrity_any_signal / integrity_present * 100:.0f}%)"
        )
    else:
        lines.append("- (no _integrity blocks observed)")

    return "\n".join(lines) + "\n"


def _failures_by_severity_md(outcomes: List[QueryOutcome]) -> str:
    rows = all_findings_flat(outcomes)
    lines = ["# Failures by Severity", ""]
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        matching = [r for r in rows if r["severity"] == sev.value]
        lines.append(f"## {sev.value.upper()} ({len(matching)})")
        if not matching:
            lines.append("- (none)")
        for r in matching:
            lines.append(f"- **{r['fixture_id']}** [`{r['code']}`] {r['field'] or ''}: {r['message']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _failures_by_company_md(outcomes: List[QueryOutcome]) -> str:
    by_company: Dict[str, List[QueryOutcome]] = defaultdict(list)
    for o in outcomes:
        by_company[o.fixture.company].append(o)

    lines = ["# Failures by Company", ""]
    for company in sorted(by_company):
        group = by_company[company]
        failing = [o for o in group if not o.passed()]
        lines.append(f"## {company} — {len(failing)}/{len(group)} failing")
        for o in failing:
            worst = o.worst_severity()
            worst_s = worst.value.upper() if worst else o.status
            lines.append(f"- **{o.fixture.id}** ({o.fixture.category}) — {worst_s}, {len(o.findings)} finding(s), status={o.status}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _latency_summary_md(outcomes: List[QueryOutcome]) -> str:
    completed = [o for o in outcomes if o.status == "completed"]
    lines = ["# Latency Summary", ""]
    if not completed:
        lines.append("(no completed queries)")
        return "\n".join(lines) + "\n"

    latencies = sorted(((o.fixture.id, o.elapsed_s) for o in completed), key=lambda t: -t[1])
    all_vals = [v for _, v in latencies]
    lines += [
        f"- Count: {len(all_vals)}",
        f"- Min: {min(all_vals):.2f}s",
        f"- Median: {statistics.median(all_vals):.2f}s",
        f"- Mean: {statistics.mean(all_vals):.2f}s",
        f"- p95: {_percentile(all_vals, 0.95):.2f}s",
        f"- Max: {max(all_vals):.2f}s",
        "",
        "## Slowest queries",
    ]
    for fixture_id, elapsed in latencies[:10]:
        lines.append(f"- {fixture_id}: {elapsed:.2f}s")
    return "\n".join(lines) + "\n"
