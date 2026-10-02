"""Frozen point-in-time entity-identity acceptance cohort.

These cases run before retrieval. They prove that a historical benchmark's
``as_of`` boundary reaches the production resolver and that successor issuers
are never substituted before their legal ownership or formation date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from app.services.entity_resolution_service import resolve_for_analysis


@dataclass(frozen=True)
class TemporalIdentityCase:
    case_id: str
    company_hint: str
    question: str
    as_of: str
    expected_ticker: str
    expected_behavior: str
    expected_status: str
    expected_predecessors: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TemporalIdentityOutcome:
    case_id: str
    passed: bool
    actual_ticker: str
    actual_behavior: str
    actual_status: str
    reason: str = ""


TEMPORAL_IDENTITY_CASES: Tuple[TemporalIdentityCase, ...] = (
    TemporalIdentityCase(
        "linkedin-before-msft", "LinkedIn", "LinkedIn revenue",
        "2015-12-31T23:59:59Z", "", "clarify", "not_yet_owned", ("LNKD",),
    ),
    TemporalIdentityCase(
        "linkedin-at-msft-close", "LinkedIn", "LinkedIn revenue",
        "2016-12-08T23:59:59Z", "MSFT", "answer", "current", ("LNKD",),
    ),
    TemporalIdentityCase(
        "paypal-before-separation", "PayPal", "PayPal revenue",
        "2014-12-31T23:59:59Z", "", "clarify", "pre_separation", ("EBAY",),
    ),
    TemporalIdentityCase(
        "ge-vernova-at-separation", "GE Vernova", "GE Vernova revenue",
        "2024-04-02T23:59:59Z", "GEV", "answer", "current", ("GE",),
    ),
    TemporalIdentityCase(
        "fb-historical-symbol", "FB", "FB earnings",
        "2021-12-31T23:59:59Z", "META", "answer", "historical_alias_active",
    ),
    TemporalIdentityCase(
        "viatris-before-merger", "Viatris", "Viatris revenue",
        "2019-12-31T23:59:59Z", "", "clarify", "pre_merger", ("MYL", "PFE"),
    ),
    TemporalIdentityCase(
        "wbd-current-successor", "Warner Bros Discovery", "WBD revenue",
        "2024-12-31T23:59:59Z", "WBD", "answer", "current", ("T", "DISCA"),
    ),
    TemporalIdentityCase(
        "mylan-current-successor", "Mylan", "Mylan revenue",
        "2024-12-31T23:59:59Z", "VTRS", "answer", "current", ("MYL",),
    ),
)


def evaluate_temporal_identity_case(
    case: TemporalIdentityCase,
) -> TemporalIdentityOutcome:
    result = resolve_for_analysis(
        user_question=case.question,
        company_hint=case.company_hint,
        as_of=case.as_of,
    )
    behavior = "clarify" if result.needs_clarification else "answer"
    actual_predecessors = result.predecessor_tickers
    if not actual_predecessors and result.historical_ticker:
        actual_predecessors = (result.historical_ticker,)
    checks = {
        "ticker": result.canonical_ticker == case.expected_ticker,
        "behavior": behavior == case.expected_behavior,
        "status": result.relationship_status == case.expected_status,
        "predecessors": actual_predecessors == case.expected_predecessors,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return TemporalIdentityOutcome(
        case_id=case.case_id,
        passed=not failed,
        actual_ticker=result.canonical_ticker,
        actual_behavior=behavior,
        actual_status=result.relationship_status,
        reason="" if not failed else "mismatch: " + ", ".join(failed),
    )


def run_temporal_identity_benchmark() -> Tuple[TemporalIdentityOutcome, ...]:
    return tuple(evaluate_temporal_identity_case(case) for case in TEMPORAL_IDENTITY_CASES)
