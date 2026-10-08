"""Multi-question coverage capture. Captured output is not adjudicated quality.

Reuse the synthetic pipeline boundary: no user memory, personalization,
persistence or delivery. Signed-in personalized acceptance is a separate gate.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Callable

from .benchmark_registry import IssuerRegistry, load_registry
from .intelligence_benchmark import BenchmarkContractError, content_hash
from .pipeline_capture import MAX_CASES, capture_pipeline_outputs

QUESTION_FAMILIES = {
    "core_thesis": "What is the investment thesis for {company}, what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims.",
    "decision_threshold": "Which valuation and operating assumptions would make {company} attractive or unattractive? Explain decision thresholds, evidence and uncertainty without inventing figures.",
    "structural_risk": "What are the most important operating risks for {company}? Identify the mechanisms, current primary-source evidence and what remains unverified.",
    "financial_trends": "How have {company}'s revenue, profitability and operating cash flow changed across comparable reporting periods? Cite exact figures, units and periods; identify missing data.",
    "operating_metrics": "Which sector-specific operating metrics best explain {company}'s performance? Report the latest disclosed values with issuer definitions, periods and primary-source citations, or explain specific gaps.",
    "recent_developments": "What recent public developments materially affect {company}'s investment thesis? Separate publication dates from reporting periods, cite sources and explain what the evidence does and does not establish.",
}


def build_matrix(*, registry: IssuerRegistry | None = None,
                 tickers: list[str] | None = None,
                 families: list[str] | None = None) -> dict:
    registry = registry or load_registry()
    allowed = registry.by_ticker()
    selected = sorted(allowed) if tickers is None else [t.strip().upper() for t in tickers]
    chosen = list(QUESTION_FAMILIES) if families is None else list(families)
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(allowed):
        raise BenchmarkContractError("matrix requires unique registered issuer tickers")
    if not chosen or len(set(chosen)) != len(chosen) or set(chosen) - set(QUESTION_FAMILIES):
        raise BenchmarkContractError("matrix requires unique supported question families")
    # Interleave size tiers so a bounded first batch is not all large companies.
    groups = {}
    for ticker in sorted(selected):
        groups.setdefault(allowed[ticker].market_cap_tier.value, []).append(ticker)
    ordered = []
    for index in range(max(map(len, groups.values()))):
        for tier in sorted(groups):
            if index < len(groups[tier]):
                ordered.append(groups[tier][index])
    cases = []
    for family in chosen:
        for ticker in ordered:
            issuer = allowed[ticker]
            cases.append({
                "issuer_id": ticker, "question_id": family,
                "question": QUESTION_FAMILIES[family].format(company=issuer.company),
                "dimensions": {"market_cap_tier": issuer.market_cap_tier.value,
                               "sector": issuer.sector, "domicile": issuer.domicile},
            })
    matrix_hash = content_hash(cases)
    return {
        "schema_version": 1,
        "run_id": f"synthetic:company-quality-v1:{registry.registry_sha256[:16]}:{matrix_hash[:16]}",
        "matrix_sha256": matrix_hash,
        "registry_sha256": registry.registry_sha256,
        "classification_as_of": registry.classification_as_of,
        "issuer_count": len(selected), "case_count": len(cases),
        "market_cap_counts": dict(Counter(allowed[t].market_cap_tier.value for t in selected)),
        "coverage_targets": {"issuer_count": registry.targets.issuer_count,
                             "minimum_by_market_cap": {t.value: n for t, n in registry.targets.minimum_by_market_cap}},
        "question_families": chosen, "cases": cases,
    }


def capture_matrix(*, registry: IssuerRegistry | None = None,
                   tickers: list[str] | None = None,
                   families: list[str] | None = None,
                   offset: int = 0, limit: int = MAX_CASES, execute: bool = False,
                   runner: Callable | None = None, checkpoint: Callable | None = None) -> dict:
    registry = registry or load_registry()
    plan = build_matrix(registry=registry, tickers=tickers, families=families)
    if (type(offset) is not int or offset < 0 or offset >= plan["case_count"]
            or type(limit) is not int or not 1 <= limit <= MAX_CASES):
        raise BenchmarkContractError(f"matrix offset must exist and batch limit must be 1-{MAX_CASES}")
    selected = plan["cases"][offset:offset + limit]
    report = {key: value for key, value in plan.items() if key != "cases"}
    report.update(
        execution_enabled=execute, offset=offset, selected_case_count=len(selected),
        started_at=datetime.now(timezone.utc).isoformat(), cases=[],
        capture_safety={"research_memory_enabled": False, "personalization_enabled": False,
                        "persistence_enabled": False, "notification_delivery_enabled": False,
                        "authenticated_api_tested": False},
        quality_status="not_adjudicated", quality_pass_rate=None, launch_ready=False,
        remaining_acceptance=["primary-source factual and citation adjudication",
                              "blind usefulness review by size and question family",
                              "representative 100-issuer registry and unseen holdout",
                              "signed-in personalization and saved-thesis comparisons",
                              "save/reopen, latency and freshness acceptance"],
    )
    def update_progress():
        report["capture_counts"] = dict(Counter(c["capture_status"] for c in report["cases"]))
        report["capture_by_market_cap"] = {
            tier: dict(Counter(c["capture_status"] for c in report["cases"]
                               if c["dimensions"]["market_cap_tier"] == tier))
            for tier in plan["market_cap_counts"]
        }
        report["capture_by_question_family"] = {
            family: dict(Counter(c["capture_status"] for c in report["cases"]
                                 if c["question_id"] == family))
            for family in plan["question_families"]
        }
        report["batch_complete"] = len(report["cases"]) == len(selected)
        report["next_offset"] = offset + len(report["cases"])
        if checkpoint:
            checkpoint(report)
    update_progress()
    for case in selected:
        row = dict(case)
        if not execute:
            row.update(capture_status="not_executed", review_status="not_reviewed")
        else:
            try:
                captured = capture_pipeline_outputs(
                    {"schema_version": 1, "run_id": plan["run_id"], "cases": [case]},
                    execute=True, runner=runner, registry=registry,
                ).captured_cases[0]
                row.update(captured)
                row.update(capture_status="captured", review_status="not_reviewed",
                           response_sha256=content_hash(captured["response"]))
            except Exception as exc:
                # A failing issuer must not suppress later cases or look like a
                # safe evidence-gap answer. Avoid emitting exception secrets.
                row.update(capture_status="execution_failed", review_status="not_reviewed",
                           error_class=type(exc).__name__)
        report["cases"].append(row)
        update_progress()
    return report
