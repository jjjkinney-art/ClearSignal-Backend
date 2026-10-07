"""Explicit successor context must preserve attribution and historical dates."""
import asyncio
from dataclasses import replace
from hashlib import sha256

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services import issuer_identity, live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import bound_issuer_risk, extract_issuer_risk_evidence, risk_summary
from app.services.issuer_succession import reviewed_predecessor_annual, reviewed_succession
from app.services.public_document_ingestion import PublicDocument, PublicDocumentError
from app.services.research_conversations import create_conversation, append_completed_turn, get_conversation
from app.services.source_answer import apply_source_answer_gate

QUESTION = "What current public evidence identifies an operating risk to XOM commodity prices?"
QUOTE = "Commodity prices could decline and adversely affect our operating results."
URL = "https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/xom-20251231.htm"
CURRENT_URL = "https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/xom-20260630.htm"


def set_identity(monkeypatch, *, cik=2115436, name="ExxonMobil Holdings Corp", ticker="XOM"):
    directory = issuer_identity.parse_directory({"0": {"ticker": ticker, "title": name, "cik_str": cik}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)


@pytest.fixture(autouse=True)
def current_identity(monkeypatch):
    set_identity(monkeypatch)


def document(**changes):
    # Authored sentence and markup, not a verbatim claim about the actual annual.
    text = f"Item 1A. Risk Factors {QUOTE} Item 1B. Unresolved Staff Comments"
    return replace(PublicDocument(URL, URL, "text/html", sha256(text.encode()).hexdigest(),
        len(text), "Authored predecessor annual", text, (), (), (), "html", True,
        "2026-10-07", publisher="SEC EDGAR", published_at="2026-02-18",
        document_type="10-K", source_type="regulatory_filing", source_tier="primary"), **changes)


def extract(doc=None, provenance=None):
    return extract_issuer_risk_evidence(doc or document(), ticker="XOM", question=QUESTION,
        issuer_relationship=provenance or reviewed_succession("XOM").provenance())


def test_foreign_filing_requires_explicit_reviewed_authorization():
    assert extract_issuer_risk_evidence(document(), ticker="XOM", question=QUESTION) == []
    item = extract()[0]
    value = bound_issuer_risk(item, ticker="XOM", question=QUESTION)
    assert document().text[value["start_offset"]:value["end_offset"]] == QUOTE
    assert value["document_ref"]["url"] == URL
    assert value["document_ref"]["published_at"] == "2026-02-18"
    assert value["issuer_relationship"]["subject_issuer"]["cik"] == "2115436"
    assert value["issuer_relationship"]["source_issuer"]["cik"] == "34088"


@pytest.mark.parametrize("changes", [
    {"final_url": URL.replace("34088/", "99999/")},
    {"final_url": URL.replace("20251231", "20241231")},
    {"final_url": URL + "?token=secret"},
    {"final_url": URL + "#risk"}, {"final_url": URL.replace("https:", "http:")},
    {"document_type": "10-K/A"}, {"document_type": "10-Q"},
    {"published_at": "2026-07-01"}, {"published_at": "2027-02-18"},
    {"source_tier": "unverified"}, {"content_hash": "bad"},
])
def test_authorization_is_exact_document_form_date_and_primary_binding(changes):
    assert extract(document(**changes)) == []


@pytest.mark.parametrize("key,value", [
    ("registry_id", "unreviewed"), ("relationship", "subsidiary"),
    ("effective_at", "2026-01-01"), ("available_at", "2026-01-01"),
    ("subject_issuer", {"ticker": "XOM", "cik": "34088", "name": "Exxon Mobil Corporation"}),
    ("source_issuer", {"cik": "99999", "name": "Foreign issuer"}),
    ("sources", [{"url": "https://example.com/relationship"}]),
    ("use", "current_thesis_direction"),
])
def test_asserted_or_mutated_relationship_cannot_self_authorize(key, value):
    provenance = reviewed_succession("XOM").provenance()
    provenance[key] = value
    assert extract(provenance=provenance) == []
    item = extract()[0].model_copy(deep=True)
    item.risk_disclosures[0]["issuer_relationship"][key] = value
    item.summary = risk_summary(item.risk_disclosures[0], item.document_type)
    assert bound_issuer_risk(item, ticker="XOM", question=QUESTION) is None
    assert admit_evidence([item])[0] == []


@pytest.mark.parametrize("cik,name,ticker", [
    (34088, "Exxon Mobil Corp", "XOM"),
    (2115436, "Unrelated Holdings Corp", "XOM"),
    (2115436, "ExxonMobil Holdings Corp", "OTHER"),
])
def test_directory_identity_cannot_be_replaced_by_registry(monkeypatch, cik, name, ticker):
    item = extract()[0]
    set_identity(monkeypatch, cik=cik, name=name, ticker=ticker)
    assert reviewed_predecessor_annual("XOM") is None
    assert bound_issuer_risk(item, ticker="XOM", question=QUESTION) is None
    assert admit_evidence([item])[0] == []


def test_unavailable_identity_fails_closed(monkeypatch):
    def unavailable():
        raise issuer_identity.CompanyIdentityError("unavailable")
    monkeypatch.setattr(issuer_identity, "_load_directory", unavailable)
    assert reviewed_predecessor_annual("XOM") is None


def test_relationship_is_not_available_before_both_primary_proofs():
    from datetime import date
    assert reviewed_succession("XOM", as_of=date(2026, 6, 30)) is None
    assert reviewed_succession("XOM", as_of=date(2026, 7, 2)) is None
    assert reviewed_succession("XOM", as_of=date(2026, 8, 3)) is not None
    for as_of in ["2026-06-30", "2026-07-02", "2026-08-02"]:
        item = extract()[0]
        # Even an asserted current status must not bypass the temporal boundary.
        item.freshness_status = "current"
        admitted, refs, _ = admit_evidence([item], as_of=as_of)
        assert admitted == [] and refs[0]["freshness_status"] == "unavailable"


def test_answer_references_and_snapshot_keep_historical_issuer_and_date():
    item = extract()[0]
    admitted, refs, _ = admit_evidence([item], evaluated_at="2026-10-07")
    assert refs[0]["published_at"] == refs[0]["filed_at"] == "2026-02-18"
    assert refs[0]["observed_at"] is None
    assert "231 days old" in refs[0]["status_reason"]
    assert "predecessor" in refs[0]["title"]
    thesis = InvestmentThesis(ticker="XOM", company_name="ExxonMobil Holdings Corp",
        direct_answer="The thesis strengthened", bull_thesis="Growth is certain")
    result = apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)
    assert result["status"] == "attributed" and "[E1]" in thesis.direct_answer
    assert "Exxon Mobil Corporation (predecessor)" in thesis.direct_answer
    assert "2026-02-18" in thesis.direct_answer and "not a new successor disclosure" in thesis.direct_answer
    assert thesis.directional_stance == "" and thesis.bull_thesis == ""
    assert result["claims"][0]["issuer_relationship"] == refs[0]["issuer_relationship"]
    snapshot = {"answer": {"investment_thesis": thesis.model_dump(mode="json"),
                           "source_answer": result, "evidence_references": refs}}

    async def persist_and_reopen():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                conversation = await create_conversation(session, user_id="owner-a", title="XOM", tickers=["XOM"])
                await append_completed_turn(session, user_id="owner-a", conversation_id=conversation["id"],
                    question=QUESTION, response=snapshot, request_ref="succession-test")
                await session.commit()
            async with factory() as session:
                reopened = await get_conversation(session, user_id="owner-a", conversation_id=conversation["id"])
                assert len(reopened["messages"]) == 2
                assert reopened["messages"][1]["displayed_snapshot"]["response"] == snapshot
                assert reopened["messages"][1]["text"] == thesis.direct_answer
                assert await get_conversation(session, user_id="owner-b", conversation_id=conversation["id"]) is None
        finally:
            await engine.dispose()
    asyncio.run(persist_and_reopen())


@pytest.mark.parametrize("annual_exists,max_documents,first_has_risk", [
    (False, 2, False), (True, 2, False), (False, 1, False), (False, 2, True),
])
def test_live_fallback_keeps_current_first_and_two_attempt_budget(monkeypatch, annual_exists, max_documents, first_has_risk):
    quarterly = RetrievedEvidence(title="Current quarter", source="SEC EDGAR", summary="Filed.",
        timestamp="2026-08-03", url=CURRENT_URL, document_type="10-Q")
    own_annual = quarterly.model_copy(update={"document_type": "10-K", "url": CURRENT_URL.replace("20260630", "annual")})
    discovery, downloads = [], []
    def discover(ticker, **kwargs):
        discovery.append((ticker, kwargs["forms"]))
        return ([own_annual] if annual_exists else []) if kwargs["forms"] == ["10-K"] else [quarterly]
    def fetch(url, **kwargs):
        downloads.append((url, kwargs))
        text = document().text if first_has_risk or url != CURRENT_URL else "Item 1A. Risk Factors No material changes."
        return document(final_url=url, text=text, published_at=kwargs["published_at"], document_type=kwargs["document_type"])
    monkeypatch.setattr(live.sec_provider, "fetch_recent_filings", discover)
    monkeypatch.setattr(live, "fetch_public_document", fetch)
    items = live.fetch_live_issuer_kpi_evidence("XOM", question=QUESTION, max_documents=max_documents)
    assert downloads[0][0] == CURRENT_URL and len(downloads) <= max_documents
    if max_documents == 1 and not first_has_risk:
        assert items == [] and len(discovery) == 1
    elif first_has_risk:
        assert len(downloads) == 1 and "issuer_relationship" not in items[0].risk_disclosures[0]
    else:
        assert len(items) == 1 and len(downloads) == 2
        assert downloads[1][0] == (own_annual.url if annual_exists else URL)
        assert ("issuer_relationship" in items[0].risk_disclosures[0]) is not annual_exists
    assert all(ticker == "XOM" for ticker, _ in discovery)
    assert all(kwargs["extract_tables"] is False and kwargs["sec_periodic_limits"] for _, kwargs in downloads)


def test_failed_predecessor_attempt_does_not_retry_another_foreign_filing(monkeypatch):
    quarterly = RetrievedEvidence(title="Quarter", source="SEC EDGAR", summary="Filed.",
        timestamp="2026-08-03", url=CURRENT_URL, document_type="10-Q")
    monkeypatch.setattr(live.sec_provider, "fetch_recent_filings",
        lambda *a, **k: [] if k["forms"] == ["10-K"] else [quarterly])
    downloads = []
    def unavailable(url, **kwargs):
        downloads.append(url)
        raise PublicDocumentError("unavailable")
    monkeypatch.setattr(live, "fetch_public_document", unavailable)
    assert live.fetch_live_issuer_kpi_evidence("XOM", question=QUESTION) == []
    assert downloads == [CURRENT_URL, URL]


def test_succession_proof_does_not_make_old_disclosure_newer_than_saved_thesis():
    from app.services.research_comparison import apply_evidence_gated_comparison
    item = extract()[0]
    thesis = InvestmentThesis(ticker="XOM", company_name="ExxonMobil Holdings Corp",
        direct_answer="The thesis has strengthened", confidence_score=0.8)
    result = apply_evidence_gated_comparison(thesis, {
        "applied": True, "created_at": "2026-03-01T00:00:00+00:00",
        "historical_thesis": {"direct_answer": "Commodity prices affect operating results.", "confidence_score": 0.6},
    }, [item])
    assert result["status"] == "insufficient_new_evidence"
    assert result["evidence_changes"] == [] and "cannot verify" in thesis.direct_answer


def test_stripping_provenance_does_not_relabel_predecessor_as_current():
    item = extract()[0].model_copy(deep=True)
    item.risk_disclosures[0].pop("issuer_relationship")
    item.summary = risk_summary(item.risk_disclosures[0], item.document_type)
    assert bound_issuer_risk(item, ticker="XOM", question=QUESTION) is None
    thesis = InvestmentThesis(ticker="XOM", company_name="ExxonMobil Holdings Corp")
    assert apply_source_answer_gate(thesis, QUESTION, [item])["status"] == "insufficient_claim_evidence"


@pytest.mark.parametrize("change", ["quote", "offset", "hash", "url", "date"])
def test_predecessor_uses_original_exact_quote_binding(change):
    item = extract()[0].model_copy(deep=True)
    value = item.risk_disclosures[0]
    if change == "quote":
        value["quote"] = "Commodity prices could decline and harm our earnings."
    elif change == "offset":
        value["start_offset"] += 1
    elif change == "hash":
        value["document_ref"]["content_hash"] = "f" * 64
    elif change == "url":
        value["document_ref"]["url"] = CURRENT_URL
    else:
        item.timestamp = "2026-08-03"
    item.summary = risk_summary(value, item.document_type)
    assert bound_issuer_risk(item, ticker="XOM", question=QUESTION) is None


def test_acceptance_report_exports_validated_predecessor_identity():
    from scripts import company_evidence_acceptance as acceptance
    case = {"ticker": "XOM", "company": "ExxonMobil Holdings Corp", "cik": "2115436",
            "topic": "commodity prices", "question": QUESTION, "reporting_scope": "us_periodic"}
    doc = document()
    result = acceptance.run_case(case, user_agent="test", evaluated_at="2026-10-07",
        fetcher=lambda _: (extract(doc), {doc.content_hash: doc}))
    assert result["passed"] and result["status"] == "pass"
    proof = result["disclosures"][0]
    assert proof["exact_span"] and proof["cited_in_answer"]
    assert proof["filed_at"] == "2026-02-18" and proof["url"] == URL
    assert proof["issuer_relationship"] == reviewed_succession("XOM").provenance()


def test_same_issuer_document_cannot_be_labeled_as_reviewed_predecessor():
    assert extract(document(final_url=CURRENT_URL, document_type="10-Q", published_at="2026-08-03")) == []


def test_long_predecessor_quote_remains_complete_in_answer():
    quote = QUOTE[:-1] + " due to " + "volatile market conditions " * 30 + "."
    assert 850 < len(quote) <= 900
    doc = document(text=f"Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments")
    items = extract(doc)
    admitted, refs, _ = admit_evidence(items, evaluated_at="2026-10-07")
    thesis = InvestmentThesis(ticker="XOM", company_name="ExxonMobil Holdings Corp")
    result = apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)
    assert result["status"] == "attributed"
    assert result["claims"][0]["document_ref"]["quote"] == quote
    assert quote in thesis.direct_answer and "[E1]" in thesis.direct_answer
