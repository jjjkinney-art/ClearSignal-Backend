"""Release issue 4 (2026-11-17): a legal-form or country word that is also a ticker is part of the name before it.

"Siemens AG" was answered as First Majestic Silver (ticker AG), "Allianz SE" as Sea Limited (SE), "Ericsson AB" as AllianceBernstein (AB), "Santander USA" as Liberty All-Star Equity Fund (USA): the free-text
ticker scan read the legal form as the company at full confidence. Identical on main (e81dcb0) and every candidate before this fix. Written after a capitalised name word the word is now part of that name;
on its own ("the thesis for AG"), with a "$", or as an exact official name it is still what it was. Rows mirror SEC's company_tickers.json shape; the company names are invented.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "AG", "cik_str": 1, "title": "FIRST FICTIONAL SILVER CORP"}, "1": {"ticker": "SE", "cik_str": 2, "title": "SEAFIC LTD"},
    "2": {"ticker": "AB", "cik_str": 3, "title": "ALLIANCEFIC HOLDING L.P."}, "3": {"ticker": "BV", "cik_str": 4, "title": "BRIGHTFIC HOLDINGS INC"},
    "4": {"ticker": "SA", "cik_str": 5, "title": "SEAFICGOLD LTD"}, "5": {"ticker": "UK", "cik_str": 6, "title": "UCOMFIC INTERNATIONAL LTD"},
    "6": {"ticker": "USA", "cik_str": 7, "title": "LIBERTYFIC ALL STAR EQUITY FUND"}, "7": {"ticker": "ACME", "cik_str": 8, "title": "ACME AG"},
    "8": {"ticker": "ZRBX", "cik_str": 9, "title": "Zorbex Therapeutics, Inc."},
}
THESIS = ("What is the investment thesis for {}, what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims.")


@pytest.fixture
def routed(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []

    def pipeline(**kwargs):
        seen.append(kwargs["company"].ticker)
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agents_used=[], answer={})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


@pytest.mark.parametrize("name", [
    "Siemens AG", "Allianz SE", "Total SE", "Ericsson AB", "Volvo AB", "Heineken BV", "Philips SA", "Santander USA", "Fidelity UK", "Polestar Automotive UK",
    "SIEMENS AG",
])
def test_a_legal_form_or_country_word_after_a_name_is_not_a_ticker(routed, name):
    route(THESIS.format(name))
    assert routed == []            # nothing in this directory matches the name: no company is selected, certainly not the legal form's ticker


@pytest.mark.parametrize("question,expected", [
    (THESIS.format("AG"), "AG"), (THESIS.format("SE"), "SE"), (THESIS.format("UK"), "UK"), (THESIS.format("USA"), "USA"),             # the ticker on its own
    ("Analyze AG", "AG"), ("Is UK a good stock?", "UK"), ("What do you think of AB?", "AB"), ("thesis for $SE please", "SE"),         # after a function word, a verb or a $
    (THESIS.format("ACME AG"), "ACME"),                                                                                              # an exact official name: the name wins
    (THESIS.format("Zorbex Therapeutics, Inc."), "ZRBX"), (THESIS.format("ZRBX"), "ZRBX"),                                          # ordinary names and tickers are unchanged
])
def test_the_ticker_is_still_a_ticker_when_written_as_one(routed, question, expected):
    route(question)
    assert routed == [expected]


def test_an_all_capitals_question_follows_the_same_rule(routed):
    route("WHAT IS THE INVESTMENT THESIS FOR ZORBEX AG, WHAT SUPPORTS IT?")
    assert routed == []
    route("WHAT IS THE INVESTMENT THESIS FOR AG, WHAT SUPPORTS IT?")
    assert routed == ["AG"]
