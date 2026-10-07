"""Read-only SEC risk-evidence coverage, separate from authenticated /ask tests.

Uses the production bounded retriever, admission and answer gate. Missing
disclosures, unsupported filing forms and retrieval failures are coverage gaps,
never successes. No LLM, account writes, shared ticker writes or delivery.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas import InvestmentThesis
from app.services import live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import bound_issuer_risk, requested_risk_profile
from app.services.source_answer import apply_source_answer_gate
from app.services import public_document_ingestion as ingestion
from scripts.company_evidence_inspection import (
    boundary_inspection, rejection_reason, submission_inventory, topic_inspection,
)

COHORT_PATH = ROOT / "validation/company_evidence_coverage.v1.json"


def run_case(case: dict, *, user_agent: str, fetcher=None, evaluated_at=None,
             inspect_source: bool = False) -> dict:
    """One independent issuer/topic probe; preserve exact document spans."""
    row = {"ticker": case["ticker"], "topic": case["topic"], "passed": False,
           "status": "gap", "stage": "identity", "documents_attempted": 0,
           "documents_retrieved": 0, "admitted_risk_count": 0,
           "disclosures": [], "retrieval_failures": [], "document_diagnostics": [],
           "filing_discovery": []}
    profile = requested_risk_profile(case["ticker"], case["question"])
    if not profile:
        row["reason"] = "identity_or_topic_unavailable"
        return row
    if str(int(profile.cik)) != str(int(case["cik"])):
        row.update(status="error", reason="issuer_identity_mismatch")
        return row
    documents = {}
    download_times = {}
    real_fetch = live.fetch_public_document
    real_extract = live.extract_issuer_risk_evidence
    real_discover = live.sec_provider.fetch_recent_filings
    real_json = live.sec_provider._fetch_json
    real_html_result = ingestion._HTMLTextExtractor.result
    html_inspection = None
    inspections = {}

    def observe_html(parser, *args, **kwargs):
        nonlocal html_inspection
        result = real_html_result(parser, *args, **kwargs)
        if inspect_source and kwargs.get("preserve_sec_risk"):
            full_text = parser.normalized_visible_text(preserve_sec_risk=True)
            html_inspection = boundary_inspection(full_text)
        return result

    def observe_discover(company, **kwargs):
        started = time.monotonic()
        diagnostic = {"forms": list(kwargs.get("forms") or []),
                      "limit": kwargs.get("limit"), "filings_returned": []}
        row["filing_discovery"].append(diagnostic)
        def observe_json(url, *args, **json_kwargs):
            data = real_json(url, *args, **json_kwargs)
            # Observe only this issuer's submissions response, never the ticker
            # directory, an unrelated issuer, credentials or arbitrary URLs.
            if (inspect_source and isinstance(data, dict) and url ==
                    f"https://data.sec.gov/submissions/CIK{str(int(case['cik'])).zfill(10)}.json"):
                cutoff = live.sec_provider._lookback_start(kwargs.get("years_back", 2))
                try:
                    diagnostic["submission_inventory"] = submission_inventory(
                        data, forms=diagnostic["forms"], cutoff=cutoff)
                except (TypeError, ValueError, AttributeError):
                    # Optional inspection must not alter discovery behavior.
                    diagnostic["submission_inventory"] = {"status": "invalid_metadata_shape"}
            return data
        try:
            with patch.object(live.sec_provider, "_fetch_json", observe_json):
                filings = real_discover(company, **kwargs) or []
            diagnostic["status"] = "found" if filings else "empty_or_unavailable"
            diagnostic["filings_returned"] = [
                {"form": getattr(filing, "document_type", None),
                 "filed_at": getattr(filing, "timestamp", None)} for filing in filings
            ]
            return filings
        except Exception as exc:
            diagnostic.update(status="error", error_class=type(exc).__name__)
            raise
        finally:
            diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000)

    def observe_fetch(url, **kwargs):
        nonlocal html_inspection
        html_inspection = None
        started = time.monotonic()
        row["documents_attempted"] += 1
        try:
            document = real_fetch(url, **kwargs)
        except live.PublicDocumentError as exc:
            failure = {"kind": exc.failure_kind,
                "http_status": exc.http_status, "form": kwargs.get("document_type"),
                "rejection_reason": rejection_reason(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000)}
            for field in ("size_limit_bytes", "declared_bytes", "observed_bytes"):
                value = getattr(exc, field, None)
                if type(value) is int and 0 <= value <= 2**63 - 1:
                    failure[field] = value
            row["retrieval_failures"].append(failure)
            raise
        row["documents_retrieved"] += 1
        documents[document.content_hash] = document
        if inspect_source:
            inspections[document.content_hash] = {
                "public_source_url": document.final_url, "content_hash": document.content_hash,
                "full_visible_text_observed": html_inspection is not None,
                "boundaries": html_inspection or boundary_inspection(document.text),
                "topic_candidates": topic_inspection(document, ticker=case["ticker"], question=case["question"]),
                "admission_authority": False,
            }
        download_times[document.content_hash] = round((time.monotonic() - started) * 1000)
        return document

    def observe_extract(document, **kwargs):
        started = time.monotonic()
        stats = {}
        result = real_extract(document, **kwargs, diagnostics=stats)
        diagnostic = {
            "form": document.document_type, "filed_at": document.published_at,
            "normalized_text_chars": len(document.text),
            "normalized_text_chars_total": document.normalized_text_chars_total,
            "text_window_start": document.text_window_start,
            "text_selection": document.text_selection,
            "download_elapsed_ms": download_times.get(document.content_hash),
            "extraction_elapsed_ms": round((time.monotonic() - started) * 1000), **stats,
        }
        if inspect_source:
            diagnostic["source_inspection"] = inspections.get(document.content_hash)
        row["document_diagnostics"].append(diagnostic)
        return result

    row["stage"] = "bounded_retrieval"
    retrieval_started = time.monotonic()
    try:
        if fetcher is None:
            with patch.object(live, "fetch_public_document", observe_fetch), \
                    patch.object(live, "extract_issuer_risk_evidence", observe_extract), \
                    patch.object(ingestion._HTMLTextExtractor, "result", observe_html), \
                    patch.object(live.sec_provider, "fetch_recent_filings", observe_discover):
                items = live.fetch_live_issuer_kpi_evidence(
                    case["ticker"], question=case["question"], user_agent=user_agent, max_documents=2)
        else:
            # Injectable for deterministic harness tests; not a CLI live path.
            items, documents = fetcher(case)
        row["retrieval_elapsed_ms"] = round((time.monotonic() - retrieval_started) * 1000)
        admitted, refs, _ = admit_evidence(items, evaluated_at=evaluated_at)
        thesis = InvestmentThesis(ticker=case["ticker"], company_name=case["company"])
        result = apply_source_answer_gate(thesis, case["question"], admitted, references=refs)
        row["source_answer_status"] = result["status"]
        risk_claims = [c for c in result["claims"] if c.get("claim_kind") == "issuer_disclosed_risk"]
        row["stage"] = "source_binding"
        for item in admitted:
            value = bound_issuer_risk(item, ticker=case["ticker"], question=case["question"])
            if not value:
                continue
            doc = documents.get(value["document_ref"]["content_hash"])
            exact = bool(doc and doc.final_url == value["document_ref"]["url"]
                         and doc.published_at == value["document_ref"]["published_at"]
                         and doc.text[value["start_offset"]:value["end_offset"]] == value["quote"])
            cited = any(c["document_ref"] == value["document_ref"]
                        and value["quote"] in c["claim"]
                        and f'[{c["reference_id"]}]' in thesis.direct_answer for c in risk_claims)
            disclosure = {"url": item.url, "filed_at": item.timestamp,
                "document_type": item.document_type, "scope": value["scope"],
                "content_hash": value["document_ref"]["content_hash"],
                "quote_sha256": hashlib.sha256(value["quote"].encode()).hexdigest(),
                "exact_span": exact, "cited_in_answer": cited}
            if value.get("issuer_relationship"):
                disclosure["issuer_relationship"] = value["issuer_relationship"]
            row["disclosures"].append(disclosure)
        row["admitted_risk_count"] = len(row["disclosures"])
        row["passed"] = bool(row["disclosures"] and risk_claims
                              and result["status"] == "attributed"
                              and all(d["exact_span"] and d["cited_in_answer"] for d in row["disclosures"])
                              and row["documents_attempted"] <= 2)
        row["status"] = "pass" if row["passed"] else "gap"
        row["reason"] = "exact_source_spans_and_answer_citations" if row["passed"] else "no_complete_attributed_risk_answer"
        if any(not d["exact_span"] for d in row["disclosures"]):
            row.update(status="error", reason="source_span_mismatch")
        return row
    except Exception as exc:
        row["retrieval_elapsed_ms"] = round((time.monotonic() - retrieval_started) * 1000)
        row.update(status="error", reason=type(exc).__name__)
        return row


def build_report(cases: list[dict], rows: list[dict]) -> dict:
    complete = (bool(cases) and len(cases) == len(rows)
                and len({c["ticker"] for c in cases}) == len(cases)
                and [r["ticker"] for r in rows] == [c["ticker"] for c in cases])
    return {"schema_version": 1, "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "read_only_production_SEC_retrieval_and_evidence_binding",
            "cohort_count": len(cases), "sector_count": len({c["sector"] for c in cases}),
            "topic_count": len({c["topic"] for c in cases}),
            "complete": complete, "passed": complete and all(r["passed"] for r in rows),
            "status_counts": dict(Counter(r["status"] for r in rows)), "results": rows,
            "llm_calls": 0, "account_writes": False, "shared_ticker_writes": False,
            "notifications": False, "authenticated_ask_tested": False,
            "launch_cleared": False,
            "launch_note": "A passed sample does not certify other companies, all topics, /ask timing, persistence or analysis quality."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=COHORT_PATH)
    parser.add_argument("--case", action="append", help="Exact ticker; repeat to select a subset")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inspect-source", action="store_true",
        help="Include bounded public SEC heading/sentence excerpts; diagnostics cannot authorize claims")
    args = parser.parse_args(argv)
    from app.config import settings
    user_agent = (getattr(settings, "sec_user_agent", "") or "").strip()
    if not user_agent:
        parser.error("SEC_USER_AGENT is required for SEC read-only requests")
    cases = json.loads(args.cohort.read_text())["cases"]
    if args.case:
        selected = {c.upper() for c in args.case}
        unknown = selected - {c["ticker"] for c in cases}
        if unknown:
            parser.error("Unknown cohort ticker(s): " + ", ".join(sorted(unknown)))
        cases = [c for c in cases if c["ticker"] in selected]
    rows = []
    for index, case in enumerate(cases, 1):
        with redirect_stdout(io.StringIO()):
            rows.append(run_case(case, user_agent=user_agent, inspect_source=args.inspect_source))
        print(f'{index}/{len(cases)} {case["ticker"]}: {rows[-1]["status"]}',
              file=sys.stderr, flush=True)
        # Preserve a visibly incomplete report if a long cohort is interrupted.
        if args.output:
            args.output.write_text(json.dumps(build_report(cases, rows), indent=2, sort_keys=True) + "\n")
    report = build_report(cases, rows)
    report["source_inspection_requested"] = args.inspect_source
    report["cohort_sha256"] = hashlib.sha256(args.cohort.read_bytes()).hexdigest()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
