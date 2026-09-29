#!/usr/bin/env python3
"""Read-only acceptance harness for live issuer-KPI evidence.

The harness uses the same bounded SEC discovery, public-document ingestion,
official Exhibit 99 discovery, source-bound extraction, and evidence promotion
as the live research path.  It does not call an LLM, mutate account data, or
touch History/Research Trail records.

Examples
--------
    python scripts/issuer_kpi_acceptance.py
    python scripts/issuer_kpi_acceptance.py --case CRM --case TSLA
    python scripts/issuer_kpi_acceptance.py --json

Exit codes: 0 all pass · 1 one or more misses/errors · 2 usage/configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import live_issuer_kpi_service as live_service
from app.services.issuer_kpi_evidence import extract_source_bound_kpis, kpi_as_evidence
from app.services.official_document_discovery import discover_official_documents
from app.services.providers import sec_provider
from app.services.public_document_ingestion import PublicDocumentError, fetch_public_document


@dataclass(frozen=True)
class CanaryCase:
    key: str
    ticker: str
    question: str


@dataclass
class Stage:
    name: str
    status: str
    count: int = 0
    detail: str = ""


@dataclass
class CanaryResult:
    case: str
    ticker: str
    question: str
    status: str = "miss"
    terminal_stage: str = "question_gate"
    documents_attempted: int = 0
    evidence_count: int = 0
    stages: list[Stage] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)


CASES = (
    CanaryCase("CRM", "CRM", "What is Salesforce current RPO?"),
    CanaryCase("SPOT", "SPOT", "What are Spotify monthly active users?"),
    CanaryCase("MAR", "MAR", "What was Marriott worldwide RevPAR growth?"),
    CanaryCase("TSLA", "TSLA", "What were Tesla total vehicle deliveries?"),
    CanaryCase("NFLX", "NFLX", "What were Netflix paid memberships?"),
)


def _stage(result: CanaryResult, name: str, status: str, *, count=0, detail="") -> None:
    result.stages.append(Stage(name=name, status=status, count=count, detail=detail))
    result.terminal_stage = name


def _public_evidence(value) -> dict:
    return {
        "title": value.title,
        "url": value.url,
        "timestamp": value.timestamp,
        "document_type": value.document_type,
        "page": value.page,
        "section": value.section,
    }


def run_case(
    case: CanaryCase,
    *,
    user_agent: str,
    max_documents: int = 2,
    filing_discovery: Callable = sec_provider.fetch_recent_filings,
    document_fetch: Callable = fetch_public_document,
    document_discovery: Callable = discover_official_documents,
    extractor: Callable = extract_source_bound_kpis,
) -> CanaryResult:
    """Run one canary and return fixed-category diagnostics."""
    result = CanaryResult(case=case.key, ticker=case.ticker, question=case.question)
    aliases = live_service.requested_issuer_kpi_aliases(case.question)
    if not aliases:
        _stage(result, "question_gate", "miss", detail="no_supported_kpi")
        return result
    _stage(result, "question_gate", "pass", count=len(aliases))

    try:
        filings = filing_discovery(
            case.ticker,
            forms=["8-K", "8-K/A", "6-K", "6-K/A"],
            limit=max_documents,
            years_back=2,
            prefer_results=True,
        ) or []
    except Exception:
        _stage(result, "filing_discovery", "error", detail="provider_error")
        result.status = "error"
        return result
    if not filings:
        _stage(result, "filing_discovery", "miss", detail="no_ranked_filings")
        return result
    _stage(result, "filing_discovery", "pass", count=len(filings))

    resolved: set[str] = set()
    retrieval_failures = 0
    extraction_documents = 0
    exhibits_discovered = 0
    evidence = []

    def process(document) -> None:
        nonlocal extraction_documents
        extraction_documents += 1
        remaining = {key: value for key, value in aliases.items() if key not in resolved}
        for kpi in extractor(document, ticker=case.ticker, metric_aliases=remaining):
            evidence.append(kpi_as_evidence(kpi, document))
            resolved.add(kpi.metric)

    for filing in filings:
        if result.documents_attempted >= max_documents or len(resolved) == len(aliases):
            break
        url = getattr(filing, "url", None)
        published_at = getattr(filing, "timestamp", None)
        document_type = getattr(filing, "document_type", None)
        if not url or not published_at or not document_type:
            continue
        result.documents_attempted += 1
        try:
            document = document_fetch(
                url,
                user_agent=user_agent,
                publisher="SEC EDGAR",
                published_at=str(published_at),
                document_type=document_type,
                source_type="regulatory_filing",
                source_tier="primary",
            )
        except (PublicDocumentError, OSError, ValueError):
            retrieval_failures += 1
            continue
        process(document)
        if len(resolved) == len(aliases):
            break
        candidates = document_discovery(
            document,
            issuer_hosts=("www.sec.gov",),
            publisher="SEC EDGAR",
            published_at=str(published_at),
            limit=max_documents,
        )
        exhibits_discovered += len(candidates)
        for candidate in candidates:
            if result.documents_attempted >= max_documents:
                break
            result.documents_attempted += 1
            try:
                exhibit = document_fetch(
                    candidate.url,
                    user_agent=user_agent,
                    publisher=candidate.publisher,
                    published_at=candidate.published_at,
                    document_type=candidate.document_type,
                    source_type=candidate.source_type,
                    source_tier=candidate.source_tier,
                )
            except (PublicDocumentError, OSError, ValueError):
                retrieval_failures += 1
                continue
            process(exhibit)
            if len(resolved) == len(aliases):
                break

    successful_retrievals = result.documents_attempted - retrieval_failures
    _stage(
        result,
        "document_retrieval",
        "pass" if successful_retrievals else "miss",
        count=successful_retrievals,
        detail="bounded_failures" if retrieval_failures else "",
    )
    if not successful_retrievals:
        return result
    _stage(
        result,
        "official_document_discovery",
        "pass" if exhibits_discovered else "not_needed",
        count=exhibits_discovered,
    )
    _stage(
        result,
        "source_bound_extraction",
        "pass" if evidence else "miss",
        count=extraction_documents,
        detail="no_unambiguous_requested_metric" if not evidence else "",
    )
    if not evidence:
        return result

    result.evidence = [_public_evidence(value) for value in evidence]
    result.evidence_count = len(evidence)
    result.status = "pass"
    _stage(result, "evidence_binding", "pass", count=len(evidence))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run read-only issuer KPI canaries")
    parser.add_argument(
        "--case", action="append", choices=[case.key for case in CASES],
        help="Canary key; repeat to select several. Defaults to all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--max-documents", type=int, default=2, choices=(1, 2, 3))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    selected = set(args.case or [case.key for case in CASES])
    cases = [case for case in CASES if case.key in selected]
    try:
        from app.config import settings
        user_agent = (getattr(settings, "sec_user_agent", "") or "").strip()
    except Exception:
        user_agent = ""
    if not user_agent:
        print("refused: SEC_USER_AGENT is not configured", file=sys.stderr)
        return 2

    results = [
        run_case(case, user_agent=user_agent, max_documents=args.max_documents)
        for case in cases
    ]
    if args.json:
        print(json.dumps({"results": [asdict(value) for value in results]}, sort_keys=True))
    else:
        for value in results:
            print(
                f"{value.case}: {value.status.upper()} "
                f"stage={value.terminal_stage} documents={value.documents_attempted} "
                f"evidence={value.evidence_count}"
            )
            for stage in value.stages:
                suffix = f" detail={stage.detail}" if stage.detail else ""
                print(f"  {stage.name}: {stage.status} count={stage.count}{suffix}")
    return 0 if all(value.status == "pass" for value in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
