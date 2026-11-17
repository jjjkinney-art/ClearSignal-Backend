"""Realistic Intelligence questions that routed wrongly or not at all (broad routing challenge, 2026-11-15).

An exchange label before a symbol ("NASDAQ: BTMD") made the user choose between BTMD and Nasdaq, Inc.; "T-Mobile" was read as the
symbol T (AT&T); the ordinary words "all" and "cost" fuzzy-matched Apple and Costco in macro questions; "How is Microsoft doing compared
with last year?" fell to a general answer that never mentioned the company; and a symbol that is another issuer's whole official name
(SUN) was routed silently. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {str(i): r for i, r in enumerate([
    {"ticker": "BTMD", "cik_str": 1,  "title": "biote Corp."},
    {"ticker": "NDAQ", "cik_str": 1120193, "title": "NASDAQ, INC."},
    {"ticker": "T", "cik_str": 732717, "title": "AT&T INC."},
    {"ticker": "TMUS", "cik_str": 1283699, "title": "T-Mobile US, Inc."},
    {"ticker": "MSFT", "cik_str": 789019, "title": "MICROSOFT CORP"},
    {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
    {"ticker": "COST", "cik_str": 909832, "title": "COSTCO WHOLESALE CORP /NEW"},
    {"ticker": "SUN", "cik_str": 1552275, "title": "Sunoco LP"},
    {"ticker": "SUNI", "cik_str": 2070845, "title": "SUN"},
])}


@pytest.fixture
def routed(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []

    def pipeline(**kwargs):
        seen.append(kwargs["company"].ticker)
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agent="stub", agents_used=[], answer={})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map",
                        lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name=""))


@pytest.mark.parametrize("question", [
    "Is NASDAQ: BTMD a good investment right now?", "Should I buy NYSE: BTMD?", "Is OTC:BTMD overvalued?"])
def test_an_exchange_label_before_a_symbol_is_not_a_second_company(routed, question):
    route(question)
    assert routed == ["BTMD"]


def test_a_symbol_that_starts_a_hyphenated_word_is_not_that_symbol(routed):
    route("What are the main risks for T-Mobile?")
    assert "T" not in routed


@pytest.mark.parametrize("question", [
    "How does a recession affect cost of capital?",
    "How do rising interest rates affect all companies in the market?"])
def test_ordinary_words_do_not_fuzzy_match_a_company(routed, question):
    route(question)
    assert routed == []


def test_a_symbol_that_is_another_issuers_whole_name_asks_which(routed):
    response = route("What is the investment thesis for SUN?")
    assert routed == []
    text = response.answer["general"]["answer"]
    assert "Did you mean" in text and "SUN" in text and "SUNI" in text


def test_the_plain_symbol_questions_still_route_directly(routed):
    route("What is the investment thesis for MSFT?")
    route("What is the investment thesis for BTMD?")
    assert routed == ["MSFT", "BTMD"]


# --- a company typed by the first word of its official name is offered as itself (suggestions only) ---------------------------------
PREFIX_ROWS = dict(ROWS)
PREFIX_ROWS.update({
    "20": {"ticker": "TM", "cik_str": 1094517, "title": "TOYOTA MOTOR CORP/"},
    "21": {"ticker": "F", "cik_str": 37996, "title": "FORD MOTOR CO"},
    "22": {"ticker": "ZNRG", "cik_str": 10, "title": "Zentrix Energy, Inc."},
    "23": {"ticker": "ZNPH", "cik_str": 11, "title": "Zentrix Pharmaceuticals Inc / MA"},
})


@pytest.fixture
def prefix_routed(monkeypatch):
    parsed = identity.parse_directory(PREFIX_ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []
    monkeypatch.setattr(router, "_run_investment_pipeline", lambda **kw: seen.append(kw["company"].ticker))
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in PREFIX_ROWS.values()})
    return seen


def test_a_first_word_offers_that_issuer_and_selects_nothing(prefix_routed):
    response = route("Should I buy Toyota?")
    assert prefix_routed == []
    text = response.answer["general"]["answer"]
    assert "Did you mean" in text and "(TM)" in text and "Ford" not in text


def test_a_first_word_shared_by_two_issuers_offers_both(prefix_routed):
    response = route("Should I buy Zentrix?")
    assert prefix_routed == []
    text = response.answer["general"]["answer"]
    assert "(ZNRG)" in text and "(ZNPH)" in text


def test_generic_words_offer_no_issuer(prefix_routed):
    assert identity.name_prefix_candidates("What is the investment thesis for the global market?") == []


def test_a_lowercase_or_sentence_opening_word_offers_no_issuer(prefix_routed):
    assert identity.name_prefix_candidates("how does the price of toyota matter for car stocks") == []
    assert identity.name_prefix_candidates("Zentrix prices rose across every sector this week, what does it mean?") == []
    assert [i.ticker for i in identity.name_prefix_candidates("What about Zentrix Energy?")] == ["ZNRG"]

