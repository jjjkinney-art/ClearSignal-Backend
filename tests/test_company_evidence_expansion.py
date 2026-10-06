"""Issuer-independent extraction, real citation flow and adversarial gaps.

Positive documents are authored fixtures, never represented as live SEC facts.
The acceptance CLI separately exercises actual filing discovery/retrieval.
"""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services import issuer_identity, live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import (
    bound_issuer_risk, extract_issuer_risk_evidence,
    requested_risk_profile, requested_risk_topic,
)
from app.services.public_document_ingestion import PublicDocument
from app.services.source_answer import apply_source_answer_gate
from scripts import company_evidence_acceptance as acceptance

CASES = json.loads(acceptance.COHORT_PATH.read_text())["cases"]
US_CASES = [c for c in CASES if c["reporting_scope"] == "us_periodic"]
TERMS = {
    "Services": "Services", "Cloud": "Cloud", "Data Center": "Data center",
    "Subscription renewals": "Subscription renewal", "Staffing demand": "Staffing demand",
    "Energy supply": "Energy supply", "Patient safety": "Patient safety",
    "Customer concentration": "Customer concentration", "Distribution": "Distribution",
    "Supply chain": "Supply chain", "Cybersecurity": "Cybersecurity",
    "Credit losses": "Credit losses", "Liquidity": "Liquidity", "Interest rates": "Interest rates",
    "Drug development": "Drug development", "Patents": "Patent protection",
    "Membership renewals": "Membership renewals", "Marketplace sellers": "Marketplace sellers",
    "Commodity prices": "Commodity prices", "Occupancy": "Occupancy",
    "Production quality": "Product quality", "Export controls": "Export controls",
    "Government contracts": "Government contracts",
}


@pytest.fixture(autouse=True)
def official_directory(monkeypatch):
    directory = issuer_identity.parse_directory({str(i): {
        "ticker": c["ticker"], "title": c["company"], "cik_str": int(c["cik"])
    } for i, c in enumerate(CASES)})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)
    return directory


def document(case, *, quote=None, form="10-K", text=None):
    profile = requested_risk_profile(case["ticker"], case["question"])
    quote = quote or f'{TERMS[profile.scope]} disruptions could adversely affect our operating results.'
    text = text or f"Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments"
    url = f'https://www.sec.gov/Archives/edgar/data/{case["cik"]}/000000000026000001/test.htm'
    return PublicDocument(url, url, "text/html", sha256(text.encode()).hexdigest(), len(text),
        "Authored coverage fixture", text, (), (), (), "html", True, "2026-10-06",
        publisher="SEC EDGAR", published_at="2026-03-02", document_type=form,
        source_type="regulatory_filing", source_tier="primary")


def extract(case, doc):
    return extract_issuer_risk_evidence(doc, ticker=case["ticker"], question=case["question"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["ticker"])
def test_every_cohort_symbol_can_select_topic_without_an_issuer_whitelist(case):
    profile = requested_risk_profile(case["ticker"], case["question"])
    assert profile and profile.cik == case["cik"]
    assert profile.scope in TERMS


@pytest.mark.parametrize("case", US_CASES, ids=lambda c: c["ticker"])
def test_new_topics_survive_admission_and_answer_binding_with_original_spans(case):
    doc = document(case)
    items, refs, _ = admit_evidence(extract(case, doc), evaluated_at="2026-10-06")
    assert items
    value = bound_issuer_risk(items[0], ticker=case["ticker"], question=case["question"])
    assert doc.text[value["start_offset"]:value["end_offset"]] == value["quote"]
    thesis = InvestmentThesis(ticker=case["ticker"], company_name=case["company"],
                             direct_answer="Unsupported: the risk has occurred and reduced margins by 72%.")
    gate = apply_source_answer_gate(thesis, case["question"], items, references=refs)
    assert gate["status"] == "attributed" and "[E1]" in thesis.direct_answer
    assert value["quote"] in thesis.direct_answer
    assert "does not independently verify" in thesis.direct_answer
    assert "72%" not in thesis.model_dump_json()
    row = acceptance.run_case(case, user_agent="test", evaluated_at="2026-10-06",
        fetcher=lambda c: (extract(c, doc), {doc.content_hash: doc}))
    assert row["passed"] and row["admitted_risk_count"] == 1


@pytest.mark.parametrize("case", US_CASES, ids=lambda c: c["ticker"])
def test_each_new_issuer_rejects_foreign_documents_other_topics_and_wrong_sections(case):
    doc = document(case)
    foreign = next(c for c in CASES if c["cik"] != case["cik"])
    assert extract(case, replace(doc, final_url=doc.final_url.replace('/'+case["cik"]+'/', '/'+foreign["cik"]+'/'))) == []
    wrong_topic = "Quantum entanglement failures could adversely affect our operating results."
    assert extract(case, document(case, quote=wrong_topic)) == []
    quote = extract(case, doc)[0].risk_disclosures[0]["quote"]
    assert extract(case, document(case, text=f'Item 7. Discussion {quote} Item 1B. Unresolved Staff Comments')) == []
    assert extract(case, document(case, text=f'Item 1A. Risk Factors {quote}')) == []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["ticker"])
def test_missed_topic_is_a_gap_not_a_successful_company_analysis(case):
    row = acceptance.run_case(case, user_agent="test", fetcher=lambda c: ([], {}))
    assert not row["passed"] and row["status"] == "gap"
    report = acceptance.build_report([case], [row])
    assert not report["passed"] and not report["launch_cleared"]


@pytest.mark.parametrize("form", ["20-F", "6-K", "8-K", "40-F"])
def test_foreign_and_nonperiodic_forms_remain_explicit_coverage_gaps(form):
    case = next(c for c in CASES if c["ticker"] == "ASML")
    doc = document(case, form=form)
    assert extract(case, doc) == []
    row = acceptance.run_case(case, user_agent="test", fetcher=lambda c: (extract(c, doc), {doc.content_hash: doc}))
    assert not row["passed"]


def test_official_identity_outage_unknown_symbols_and_conflicting_entries_fail_closed(monkeypatch):
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: issuer_identity.parse_directory({}))
    assert requested_risk_profile("WDFC", "What distribution risks are disclosed?") is None
    assert requested_risk_profile("ZZZZZ", "What distribution risks are disclosed?") is None
    conflicts = {"0": {"ticker": "WDFC", "title": "One", "cik_str": 1},
                 "1": {"ticker": "WDFC", "title": "Two", "cik_str": 2}}
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: issuer_identity.parse_directory(conflicts))
    assert requested_risk_profile("WDFC", "What distribution risks are disclosed?") is None


def test_unknown_and_multiple_topics_do_not_silently_select_one_answer_slot():
    assert requested_risk_topic("AA", "What risk affects quantum entanglement?") is None
    assert requested_risk_topic("AA", "What risk affects energy supply and liquidity?") is None
    assert requested_risk_topic("COST", "What risk affects membership renewals?")[0] == "Membership renewals"
    assert requested_risk_topic("NVDA", "What risks affect non-data-center products?") is None


def test_topics_before_company_possessives_remain_multiple_and_withheld():
    assert requested_risk_profile("AA", "What risks affect energy supply compared with Alcoa's liquidity?") is None
    assert requested_risk_profile("MSFT", "What risks affect Cloud's liquidity?") is None


def test_plural_company_possessive_is_identity_not_a_liquidity_topic():
    profile = requested_risk_profile("LQDT", "What risks affect Liquidity Services’ marketplace sellers?")
    assert profile and profile.scope == "Marketplace sellers"


def test_cold_identity_lookup_strips_only_verified_name_and_topic_probe_makes_no_network_call(monkeypatch):
    monkeypatch.setattr(issuer_identity, "_cache", None)
    question = "What risks affect Liquidity Services’ marketplace sellers?"
    assert requested_risk_profile("LQDT", question).scope == "Marketplace sellers"
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: pytest.fail("topic probe must not fetch identity"))
    assert requested_risk_topic("AA", "What risks affect energy supply?")[0] == "Energy supply"


def test_long_disclosure_is_complete_in_answer_and_overlong_or_numeric_text_is_withheld():
    case = next(c for c in CASES if c["ticker"] == "WDFC")
    quote = ('Distribution disruptions could adversely affect our operating results because '
             'our partners need to maintain reliable channels across many jurisdictions, '
             'and replacement relationships depend on the availability of appropriately '
             'qualified organizations, contractual negotiations and timely local approvals '
             'that remain outside our control and could delay our ability to reach customers '
             'in affected markets during an interruption.')
    assert 300 < len(quote) < 900
    doc = document(case, quote=quote)
    items, refs, _ = admit_evidence(extract(case, doc), evaluated_at="2026-10-06")
    thesis = InvestmentThesis(ticker="WDFC", company_name=case["company"])
    apply_source_answer_gate(thesis, case["question"], items, references=refs)
    assert quote in thesis.direct_answer and 'during an interruption.”' in thesis.direct_answer
    assert extract(case, document(case, quote=quote.replace('because', 'by 5% because'))) == []
    assert extract(case, document(case, quote='Distribution may disrupt ' + 'our operations ' * 80 + '.')) == []


def test_larger_quote_limit_is_restricted_to_hashed_sec_risk_references():
    from app.integrity.provenance import ClaimDocumentReference
    args = dict(reference_id="risk-1", title="Filing", provider="SEC EDGAR",
                url="https://www.sec.gov/Archives/edgar/data/105132/000010513225000067/wdfc-20250831.htm",
                section="Item 1A. Risk Factors", content_hash="a" * 64, quote="x" * 900)
    assert len(ClaimDocumentReference(**args).quote) == 900
    for changes in ({"quote": "x" * 901}, {"provider": "Other"},
                    {"url": "https://example.com/filing.htm"},
                    {"section": "Management discussion"}, {"content_hash": None}):
        with pytest.raises(ValueError):
            ClaimDocumentReference(**{**args, **changes})


def test_reviewed_wdfc_distribution_sentence_matches_new_topic():
    # One 25-word sentence from the actual 2025 WD-40 10-K; surrounding section
    # markers are a fixture. This is not a full live-document retrieval test.
    # https://www.sec.gov/Archives/edgar/data/105132/000010513225000067/wdfc-20250831.htm
    case = next(c for c in CASES if c["ticker"] == "WDFC")
    quote = ("Changes in marketing distributor relationships that are not managed "
             "successfully by us could result in a disruption in the affected markets.")
    doc = replace(document(case, quote=quote), published_at="2025-10-27")
    row = acceptance.run_case(case, user_agent="test", evaluated_at="2026-10-06",
        fetcher=lambda c: (extract(c, doc), {doc.content_hash: doc}))
    assert row["passed"] and row["disclosures"][0]["exact_span"]


@pytest.mark.parametrize("include_risk", [False, True])
def test_requested_metric_is_separate_from_risk_support(include_risk):
    case = next(c for c in CASES if c["ticker"] == "AA")
    question = "What public evidence supports Alcoa consolidated revenue and energy supply risks?"
    # This test isolates question-part selection; it does not validate a live
    # XBRL value or replace the existing SEC numeric extraction regressions.
    metric = RetrievedEvidence(title="Authored revenue fixture", source="SEC EDGAR — structured XBRL fact",
        summary="AA consolidated revenue rose in the reported quarter.", timestamp="2026-03-02",
        verified_claims=[{"ticker": "AA", "metric": "us-gaap:Revenues",
                          "document_ref": {"reference_id": "reported:revenue"}}])
    material = [metric]
    if include_risk:
        material += extract(case, document(case))
    items, refs, _ = admit_evidence(material, evaluated_at="2026-10-06")
    thesis = InvestmentThesis(ticker="AA", company_name="Alcoa", bull_thesis="Unsupported implication.")
    result = apply_source_answer_gate(thesis, question, items, references=refs)
    assert any(c["reference_id"] == "E1" for c in result["claims"])
    risk_claims = [c for c in result["claims"] if c.get("claim_kind") == "issuer_disclosed_risk"]
    assert bool(risk_claims) == include_risk
    assert result["status"] == ("attributed" if include_risk else "partial")
    assert result["unanswered_parts"] == ([] if include_risk else ["operating risk"])
    assert "Unsupported implication" not in thesis.model_dump_json()


def test_unrequested_consolidated_metric_cannot_substitute_for_new_topic():
    case = next(c for c in CASES if c["ticker"] == "AA")
    metric = RetrievedEvidence(title="Authored revenue fixture", source="SEC EDGAR — structured XBRL fact",
        summary="AA consolidated revenue rose in the reported quarter.", timestamp="2026-03-02",
        verified_claims=[{"ticker": "AA", "metric": "us-gaap:Revenues",
                          "document_ref": {"reference_id": "reported:revenue"}}])
    items, refs, _ = admit_evidence([metric], evaluated_at="2026-10-06")
    thesis = InvestmentThesis(ticker="AA", company_name="Alcoa")
    result = apply_source_answer_gate(thesis, case["question"], items, references=refs)
    assert result["status"] == "insufficient_claim_evidence" and not result["claims"]


def test_acceptance_detects_corrupted_document_span_even_if_payload_shape_is_valid():
    case = next(c for c in CASES if c["ticker"] == "MAN")
    doc = document(case)
    items = extract(case, doc)
    corrupted = replace(doc, text=doc.text.replace('Staffing demand', 'Unrelated topic'))
    row = acceptance.run_case(case, user_agent="test", evaluated_at="2026-10-06",
        fetcher=lambda c: (items, {doc.content_hash: corrupted}))
    assert row["status"] == "error" and row["reason"] == "source_span_mismatch"
    assert not row["passed"]


def test_empty_missing_duplicate_or_reordered_cases_cannot_clear_report():
    assert not acceptance.build_report([], [])["passed"]
    case = CASES[0]
    row = {"ticker": case["ticker"], "status": "pass", "passed": True}
    assert not acceptance.build_report([case], [])["passed"]
    assert not acceptance.build_report([case, case], [row, row])["passed"]
    assert not acceptance.build_report([case], [{**row, "ticker": "FOREIGN"}])["passed"]
    good = acceptance.build_report([case], [row])
    assert good["passed"] and not good["launch_cleared"] and not good["authenticated_ask_tested"]


def test_cli_preserves_incomplete_checkpoint_and_reports_gaps(tmp_path, monkeypatch, capsys):
    from app.config import settings
    monkeypatch.setattr(settings, "sec_user_agent", "configured test contact")
    cases = CASES[:2]
    cohort = tmp_path / "cohort.json"
    output = tmp_path / "report.json"
    cohort.write_text(json.dumps({"cases": cases}))
    def run(case, **kwargs):
        if case == cases[1]:
            checkpoint = json.loads(output.read_text())
            assert not checkpoint["complete"] and not checkpoint["passed"]
        return {"ticker": case["ticker"], "status": "gap", "passed": False}
    monkeypatch.setattr(acceptance, "run_case", run)
    assert acceptance.main(["--cohort", str(cohort), "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["complete"] and not report["passed"] and report["cohort_sha256"]
    assert report["status_counts"] == {"gap": 2} and not report["launch_cleared"]
    captured = capsys.readouterr()
    assert "1/2 AAPL: gap" in captured.err and "2/2 MSFT: gap" in captured.err
    assert "configured test contact" not in captured.out + captured.err


def test_cli_rejects_missing_contact_and_unknown_cohort_selection(monkeypatch, capsys):
    from app.config import settings
    monkeypatch.setattr(settings, "sec_user_agent", "")
    with pytest.raises(SystemExit) as missing:
        acceptance.main([])
    assert missing.value.code == 2
    monkeypatch.setattr(settings, "sec_user_agent", "configured test contact")
    monkeypatch.setattr(acceptance, "run_case", lambda *a, **k: pytest.fail("must not retrieve"))
    with pytest.raises(SystemExit) as unknown:
        acceptance.main(["--case", "ZZZZZ"])
    assert unknown.value.code == 2
    assert "Unknown cohort ticker" in capsys.readouterr().err


def test_annual_risk_fallback_runs_for_new_issuer_with_two_document_ceiling(monkeypatch):
    case = next(c for c in CASES if c["ticker"] == "AA")
    annual = document(case)
    quarter = replace(annual, document_type="10-Q", final_url=annual.final_url.replace('test.htm','quarter.htm'),
                      text='Item 1A. Risk Factors No material changes. Item 2. Unregistered Sales')
    def filing(doc):
        return RetrievedEvidence(title='Filing', source='SEC EDGAR', summary='Filed.', timestamp=doc.published_at,
                                 url=doc.final_url, document_type=doc.document_type)
    monkeypatch.setattr(live.sec_provider, "fetch_recent_filings", lambda *a, **k:
                        [filing(annual if k["forms"] == ["10-K", "10-K/A"] else quarter)])
    fetched = []
    monkeypatch.setattr(live, 'fetch_public_document', lambda url, **k:
                        fetched.append((url, k)) or (quarter if url == quarter.final_url else annual))
    evidence = live.fetch_live_issuer_kpi_evidence("AA", question=case["question"])
    assert len(evidence) == 1 and len(fetched) == 2
    assert all(k["sec_periodic_limits"] for _, k in fetched)
    assert evidence[0].risk_disclosures[0]["scope"] == "Energy supply"


def test_entire_cohort_routes_all_three_input_forms_without_wrong_issuer_or_model_calls():
    from scripts.company_coverage_audit import routing_probe
    rows = routing_probe(CASES)
    assert len(rows) == 3 * len(CASES)
    assert all(r["passed"] and not r["wrong_issuer"] and not r["saved_text_raw_json"] for r in rows)


def test_expanded_issuer_risk_answer_saves_reopens_and_is_owner_scoped():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.models import Base
    from app.services.research_conversations import append_completed_turn, create_conversation, get_conversation
    from app.services.owned_research import save_thesis, list_theses
    from types import SimpleNamespace
    case = next(c for c in CASES if c["ticker"] == "AA")
    doc = document(case)
    items, refs, _ = admit_evidence(extract(case, doc), evaluated_at="2026-10-06")
    thesis = InvestmentThesis(ticker="AA", company_name="Alcoa")
    gate = apply_source_answer_gate(thesis, case["question"], items, references=refs)
    response = {"company": "AA", "answer": {"investment_thesis": thesis.model_dump(mode="json"),
                "source_answer": gate, "evidence_references": refs}}
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as c:
                await c.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                conversation = await create_conversation(session, user_id="owner-a", title="Alcoa", tickers=["AA"])
                assert await append_completed_turn(session, user_id="owner-a", conversation_id=conversation["id"],
                    question=case["question"], response=response, request_ref="expanded-risk")
                assert await save_thesis(session, user_id="owner-a", question=case["question"],
                    company_name="Alcoa", session_id="expanded-risk",
                    result=SimpleNamespace(company="AA", answer=response["answer"]))
                await session.commit()
            async with factory() as session:
                loaded = await get_conversation(session, user_id="owner-a", conversation_id=conversation["id"])
                assert loaded["messages"][1]["text"] == thesis.direct_answer
                assert loaded["messages"][1]["displayed_snapshot"]["response"] == response
                assert await get_conversation(session, user_id="owner-b", conversation_id=conversation["id"]) is None
                history = await list_theses(session, user_id="owner-a", ticker="AA")
                assert len(history) == 1 and history[0]["direct_answer"] == thesis.direct_answer
                assert await list_theses(session, user_id="owner-a", ticker="AAPL") == []
                assert await list_theses(session, user_id="owner-b", ticker="AA") == []
        finally:
            await engine.dispose()
    asyncio.run(scenario())
