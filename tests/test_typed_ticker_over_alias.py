"""A static alias must not take a word the user typed as another issuer's ticker (2026-11-16, confirmation 2).

Found by the second offline confirmation: the ticker question "APLE" (Apple Hospitality REIT) was routed to Apple Inc. because the typo alias "aple" is
looked up before the SEC directory. The same collision exists for "coke" (nickname of Coca-Cola) and COKE (Coca-Cola Consolidated). The ticker wins only
when every occurrence is written as a ticker (upper case, or with a '$'); ordinary names, brands and misspellings keep their meaning. Rows mirror SEC's
company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
    "1": {"ticker": "APLE", "cik_str": 1418121, "title": "Apple Hospitality REIT, Inc."},
    "2": {"ticker": "KO", "cik_str": 21344, "title": "COCA COLA CO"},
    "3": {"ticker": "COKE", "cik_str": 317540, "title": "Coca-Cola Consolidated, Inc."},
    "4": {"ticker": "MSFT", "cik_str": 789019, "title": "MICROSOFT CORP"},
}
THESIS = ("What is the investment thesis for {}, what supports it, and what could invalidate it? "
          "Distinguish reported facts from inference and cite material claims.")


@pytest.fixture
def routed(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []

    def pipeline(**kwargs):
        seen.append(kwargs["company"].ticker)
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agent="stub", agents_used=[], answer={})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


@pytest.mark.parametrize("written,expected", [
    ("APLE", "APLE"), ("COKE", "COKE"), ("$aple", "APLE"), ("$coke", "COKE"), ("$COKE", "COKE"),     # a typed ticker
    ("Apple", "AAPL"), ("apple", "AAPL"), ("Aple", "AAPL"), ("aple", "AAPL"),                          # the brand and its misspelling
    ("Coke", "KO"), ("coke", "KO"), ("Coca-Cola", "KO"), ("coca cola", "KO"),                         # the brand
    ("Apple Hospitality REIT, Inc.", "APLE"), ("Coca-Cola Consolidated, Inc.", "COKE"),               # official names
    ("AAPL", "AAPL"), ("KO", "KO"), ("Microsoft", "MSFT"),
])
def test_the_user_phrasing_decides_between_a_ticker_and_an_alias(routed, written, expected):
    route(THESIS.format(written))
    assert routed == [expected]


def test_a_word_written_both_ways_keeps_the_alias(routed):
    # one occurrence is a ticker, the other prose: the typed-ticker preference needs every occurrence to be a ticker
    route("What is the investment thesis for APLE, and why do people say aple when they mean Apple?")
    assert routed != ["APLE"]          # the preference does not apply: one occurrence is prose


def test_a_question_written_entirely_in_capitals_carries_no_case_information(routed):
    # status quo: the alias is kept (case cannot tell a ticker from a brand)
    route("WHAT IS THE INVESTMENT THESIS FOR COKE, WHAT SUPPORTS IT, AND WHAT COULD INVALIDATE IT?")
    assert routed == ["KO"]


def test_typed_ticker_issuer_helper_conditions():
    parsed = identity.parse_directory(ROWS)
    import app.services.issuer_identity as I
    I_orig = I._load_directory; I._load_directory = lambda: parsed
    try:
        assert I.typed_ticker_issuer("thesis for APLE today", "aple").ticker == "APLE"
        assert I.typed_ticker_issuer("thesis for aple today", "aple") is None
        assert I.typed_ticker_issuer("thesis for $aple today", "aple").ticker == "APLE"
        assert I.typed_ticker_issuer("thesis for Apple", "apple") is None            # not a symbol
        assert I.typed_ticker_issuer("THESIS FOR APLE", "aple") is None               # no lower-case letter anywhere
    finally:
        I._load_directory = I_orig
