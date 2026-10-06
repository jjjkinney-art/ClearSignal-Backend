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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas import InvestmentThesis
from app.services import live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import bound_issuer_risk, requested_risk_profile
from app.services.source_answer import apply_source_answer_gate

COHORT_PATH = ROOT / "validation/company_evidence_coverage.v1.json"


def run_case(case: dict, *, user_agent: str, fetcher=None, evaluated_at=None) -> dict:
    """One independent issuer/topic probe; preserve exact document spans."""
    row = {"ticker": case["ticker"], "topic": case["topic"], "passed": False,
           "status": "gap", "stage": "identity", "documents_attempted": 0,
           "documents_retrieved": 0, "admitted_risk_count": 0,
           "disclosures": [], "retrieval_failures": []}
    profile = requested_risk_profile(case["ticker"], case["question"])
    if not profile:
        row["reason"] = "identity_or_topic_unavailable"
        return row
    if str(int(profile.cik)) != str(int(case["cik"])):
        row.update(status="error", reason="issuer_identity_mismatch")
        return row
    documents = {}
    real_fetch = live.fetch_public_document

    def observe_fetch(url, **kwargs):
        row["documents_attempted"] += 1
        try:
            document = real_fetch(url, **kwargs)
        except live.PublicDocumentError as exc:
            row["retrieval_failures"].append({"kind": exc.failure_kind,
                                               "http_status": exc.http_status})
            raise
        row["documents_retrieved"] += 1
        documents[document.content_hash] = document
        return document

    row["stage"] = "bounded_retrieval"
    try:
        if fetcher is None:
            with patch.object(live, "fetch_public_document", observe_fetch):
                items = live.fetch_live_issuer_kpi_evidence(
                    case["ticker"], question=case["question"], user_agent=user_agent, max_documents=2)
        else:
            # Injectable for deterministic harness tests; not a CLI live path.
            items, documents = fetcher(case)
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
            row["disclosures"].append({"url": item.url, "filed_at": item.timestamp,
                "document_type": item.document_type, "scope": value["scope"],
                "content_hash": value["document_ref"]["content_hash"],
                "quote_sha256": hashlib.sha256(value["quote"].encode()).hexdigest(),
                "exact_span": exact, "cited_in_answer": cited})
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
            rows.append(run_case(case, user_agent=user_agent))
        print(f'{index}/{len(cases)} {case["ticker"]}: {rows[-1]["status"]}',
              file=sys.stderr, flush=True)
        # Preserve a visibly incomplete report if a long cohort is interrupted.
        if args.output:
            args.output.write_text(json.dumps(build_report(cases, rows), indent=2, sort_keys=True) + "\n")
    report = build_report(cases, rows)
    report["cohort_sha256"] = hashlib.sha256(args.cohort.read_bytes()).hexdigest()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
