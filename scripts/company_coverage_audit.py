"""Read-only launch coverage audit; never runs an analysis or writes account data.

Routing probes stop at pipeline handoff. Live SEC checks are independent of the
application resolver and cannot establish end-to-end analysis quality.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AuditBoundary(BaseException):
    """Stop even when production code catches ordinary provider exceptions."""


def identity_probe(issuers):
    from app.services.company_detection import resolve_entity
    rows = []
    for issuer in issuers:
        for kind, value in (("ticker", issuer["ticker"]), ("name", issuer["company"])):
            resolution = resolve_entity(value)
            actual = resolution.context.ticker if resolution.context else None
            rows.append({"ticker": issuer["ticker"], "input_kind": kind,
                         "input": value, "resolved_ticker": actual,
                         "method": resolution.method, "confidence": resolution.confidence,
                         "passed": actual == issuer["ticker"],
                         "wrong_issuer": actual is not None and actual != issuer["ticker"]})
    return rows


def routing_probe(issuers):
    from app.schemas import AgentAnswerResponse, GeneralFinanceAnswer, QuestionRequest
    from app.services import router_service
    from app.services.research_conversations import assistant_text_from_response
    rows = []
    for issuer in issuers:
        for kind in ("explicit_ticker", "explicit_name", "question_only"):
            question = (f"What current public evidence identifies an operating risk to "
                        f"{issuer['company']}, and what remains unverified?")
            company = {"explicit_ticker": issuer["ticker"],
                       "explicit_name": issuer["company"], "question_only": ""}[kind]
            captured = []

            def handoff(**kwargs):
                ticker = kwargs["company"].ticker
                captured.append(ticker)
                return AgentAnswerResponse(company=ticker, request_id="audit",
                    agents_used=[], answer={"investment_thesis": {"direct_answer": "Audit handoff only."}},
                    routing={"pipeline": "investment_thesis"})

            def forbidden(*args, **kwargs):
                raise AuditBoundary("provider_or_legacy_analysis_boundary")

            def general(**kwargs):
                return GeneralFinanceAnswer(answer="Audit general-agent boundary only. No research, retrieval, or analysis was executed.",
                                             bullets=[], caveats=[])

            try:
                with ExitStack() as stack, redirect_stdout(io.StringIO()):
                    stack.enter_context(patch.object(router_service, "_run_investment_pipeline", handoff))
                    for name in ("run_general_finance_agent", "run_general_fallback_agent"):
                        stack.enter_context(patch.object(router_service, name, general))
                    for name in ("enrich_grounding_context", "build_evidence",
                                 "run_equity_agent", "run_synthesizer_agent"):
                        stack.enter_context(patch.object(router_service, name, forbidden))
                    stack.enter_context(patch("requests.sessions.Session.request", forbidden))
                    stack.enter_context(patch("app.services.issuer_identity._fetch_directory_json", forbidden))
                    response = router_service.route_question(QuestionRequest(
                        company_name=company, question=question, intent="company_analysis"))
                    pipeline = response.routing.get("pipeline") if response.routing else None
                    actual = captured[0] if captured else None
                    saved = assistant_text_from_response(response.model_dump(mode="json"))
                    raw_json = saved.lstrip().startswith("{")
            except AuditBoundary as exc:
                pipeline, actual, raw_json = str(exc), None, None
            rows.append({"ticker": issuer["ticker"], "input_kind": kind,
                         "pipeline": pipeline, "handoff_ticker": actual,
                         "passed": actual == issuer["ticker"],
                         "wrong_issuer": actual is not None and actual != issuer["ticker"],
                         "saved_text_raw_json": raw_json})
    return rows


def topic_probe():
    """Consolidated revenue is a decoy, never proof of an operating risk."""
    from app.schemas import InvestmentThesis, RetrievedEvidence
    from app.services.source_answer import apply_source_answer_gate
    cases = [("DOCU", "subscription renewals"), ("ETSY", "seller retention"),
             ("AA", "smelter energy supply"), ("ACHC", "facility safety")]
    rows = []
    for ticker, topic in cases:
        thesis = InvestmentThesis(ticker=ticker, company_name=ticker,
                                 bull_thesis="Unverified generated investment case.")
        item = RetrievedEvidence(title=f"{ticker} revenue", source="SEC EDGAR — structured XBRL fact",
            summary=f"{ticker} reported consolidated revenue of $100 million in its latest quarter.",
            timestamp="2026-09-01", relevance_score=0.9)
        result = apply_source_answer_gate(thesis,
            f"What current public evidence identifies an operating risk to {ticker}'s {topic}?", [item])
        rows.append({"ticker": ticker, "topic": topic, "fixture": "consolidated_revenue_decoy",
                     "source_answer_status": result["status"],
                     "unrelated_claim_accepted": bool(result["claims"]),
                     "generated_bull_case_retained": bool(thesis.bull_thesis),
                     "passed": not result["claims"] and not thesis.bull_thesis})
    return rows


def live_sec_probe(sec_rows, tickers, transport="requests"):
    """Official read-only discovery/fact inventory, not a real /ask run."""
    import requests
    lookup = {r["ticker"]: r for r in sec_rows.values()}
    rows = []
    for ticker in tickers:
        entry = lookup.get(ticker)
        if not entry:
            rows.append({"ticker": ticker, "passed": False, "reason": "absent_official_snapshot"})
            continue
        cik = str(entry["cik_str"]).zfill(10)
        row = {"ticker": ticker, "cik": cik, "checks": {}}
        for kind, url in (("submissions", f"https://data.sec.gov/submissions/CIK{cik}.json"),
                          ("companyfacts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")):
            try:
                if transport == "curl":
                    result = subprocess.run(["curl", "-fsS", "--max-time", "15", "-A",
                        "ClearSignal research support@clearsignal.ai", "-w", "\n%{http_code}", url],
                        capture_output=True, timeout=20, check=True)
                    body, status = result.stdout.rsplit(b"\n", 1)
                    data, http_status = json.loads(body), int(status)
                else:
                    response = requests.get(url, timeout=15,
                        headers={"User-Agent": "ClearSignal research support@clearsignal.ai"})
                    response.raise_for_status()
                    data, body, http_status = response.json(), response.content, response.status_code
                check = {"status": http_status, "url": url, "transport": transport,
                         "sha256": hashlib.sha256(body).hexdigest()}
                if kind == "submissions":
                    recent = data.get("filings", {}).get("recent", {})
                    matches = [(form, filed) for form, filed in zip(
                        recent.get("form", []), recent.get("filingDate", []))
                        if form in {"10-K", "10-Q", "20-F", "6-K"}]
                    check.update(issuer_name=data.get("name"), ticker_list=data.get("tickers", []),
                                 periodic_filing_count=len(matches), newest_periodic=matches[:1],
                                 passed=ticker in data.get("tickers", []) and bool(matches))
                else:
                    facts = data.get("facts", {})
                    counts = {namespace: len(concepts) for namespace, concepts in facts.items()}
                    check.update(issuer_name=data.get("entityName"), taxonomy_concept_counts=counts,
                                 passed=str(data.get("cik", "")).lstrip("0") == cik.lstrip("0")
                                        and any(counts.values()))
                row["checks"][kind] = check
            except (requests.RequestException, ValueError, OSError, subprocess.SubprocessError) as exc:
                row["checks"][kind] = {"passed": False, "error_type": type(exc).__name__}
        row["passed"] = all(check["passed"] for check in row["checks"].values())
        rows.append(row)
    return rows


def build_report(registry, sec_snapshot=None, live_tickers=(), live_transport="requests"):
    from app.services.company_detection import _COMPANY_DB
    from app.services.issuer_risk_evidence import RISK_PROFILES
    issuers = registry["issuers"]
    identities, routing, topics = identity_probe(issuers), routing_probe(issuers), topic_probe()
    tier_counts = defaultdict(Counter)
    for issuer in issuers:
        rows = [r for r in routing if r["ticker"] == issuer["ticker"]]
        tier_counts[issuer["market_cap_tier"]].update(
            issuers=1, correct_all_routes=int(all(r["passed"] for r in rows)))
    report = {"schema_version": 1, "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local public router handoff, identity and synthetic topic relevance",
        "production_authenticated_ask_tested": False, "production_writes": False,
        "llm_calls": 0, "cohort_count": len(issuers),
        "classification_as_of": registry["classification_as_of"],
        "registry_sha256": hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest(),
        "classification_note": "Frozen benchmark tiers, not current market capitalizations.",
        "sector_count": len({r["sector"] for r in issuers}),
        "static_company_count": len(_COMPANY_DB),
        "reviewed_risk_topics": {t: p.scope for t, p in RISK_PROFILES.items()},
        "identity_checks": identities, "routing_checks": routing, "topic_checks": topics,
        "routing_by_tier": dict(tier_counts),
        "identity_passed": sum(r["passed"] for r in identities),
        "routing_passed": sum(r["passed"] for r in routing),
        "wrong_issuer_routes": sum(r["wrong_issuer"] for r in routing),
        "topic_passed": sum(r["passed"] for r in topics)}
    report["audited_source_sha256"] = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in ("app/services/company_detection.py", "app/services/router_service.py",
                     "app/services/source_answer.py", "app/services/research_conversations.py",
                     "app/services/issuer_identity.py", "app/services/entity_resolution_service.py",
                     "app/services/providers/sec_provider.py", "app/services/issuer_kpi_evidence.py")}
    if sec_snapshot:
        data = json.loads(sec_snapshot.read_text())
        report["official_identity_snapshot"] = {
            "source_url": "https://www.sec.gov/files/company_tickers.json",
            "sha256": hashlib.sha256(sec_snapshot.read_bytes()).hexdigest(),
            "ticker_row_count": len(data),
            "exact_tickers_in_static_registry": sum(r["ticker"] in _COMPANY_DB for r in data.values()),
            "note": "SEC ticker rows include share classes and foreign issuers; this is not an analysis-quality score."}
        from app.services.issuer_identity import parse_directory, exact_issuer, symbol
        from unittest.mock import patch
        directory = parse_directory(data)
        valid_rows = [row for row in data.values() if isinstance(row, dict)
                      and isinstance(row.get("ticker"), str) and row.get("cik_str")]
        exact_passed = sum(
            bool((item := exact_issuer(row["ticker"], directory))
                 and item.ticker == symbol(row["ticker"])
                 and item.cik == str(int(row["cik_str"])).zfill(10))
            for row in valid_rows
        )
        # Exercise the runtime discovery path beyond the local reviewed registry.
        canaries = [dict(ticker=item.ticker, company=item.name)
                    for ticker in ("WDFC", "MOD", "LQDT", "NWE", "AZZ")
                    if (item := directory.symbols.get(ticker)) and ticker not in _COMPANY_DB]
        with patch("app.services.issuer_identity._load_directory", return_value=directory):
            report["official_directory_routing_checks"] = routing_probe(canaries)
        report["official_identity_snapshot"].update(
            parsed_symbol_count=len(directory.symbols),
            withheld_or_conflicting_row_count=len(valid_rows) - exact_passed,
            exact_symbol_checks=len(valid_rows), exact_symbol_passed=exact_passed,
            routing_canary_count=len(canaries),
        )
        report["independent_live_sec_checks"] = live_sec_probe(data, live_tickers, live_transport) if live_tickers else []
    report["coverage_checks_complete"] = bool(issuers) and (
        len(identities) == 2 * len(issuers) and len(routing) == 3 * len(issuers)
        and len(topics) == 4)
    report["passed"] = report["coverage_checks_complete"] and all(
        r["passed"] for r in identities + routing + topics
        + report.get("independent_live_sec_checks", [])
        + report.get("official_directory_routing_checks", []))
    report["launch_blocked_for_unrestricted_company_coverage"] = True
    report["launch_clearance_note"] = (
        "Local audit success does not authorize unrestricted launch. Authenticated production "
        "analysis, issuer/topic quality and persistence acceptance remain separate gates.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "validation/issuer_registry.v1.json")
    parser.add_argument("--sec-snapshot", type=Path)
    parser.add_argument("--live-sec-tickers", nargs="*", default=[])
    parser.add_argument("--live-sec-transport", choices=("requests", "curl"), default="requests")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.live_sec_tickers and not args.sec_snapshot:
        parser.error("--live-sec-tickers requires --sec-snapshot")
    with redirect_stdout(io.StringIO()):
        report = build_report(json.loads(args.registry.read_text()), args.sec_snapshot,
                              args.live_sec_tickers, args.live_sec_transport)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
