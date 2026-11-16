"""A brand alias that occurs only inside another issuer's full official name must not select the brand's issuer.

Found by the broad identity scan (2026-11-15): "COCA-COLA EUROPACIFIC PARTNERS plc" routed to KO, "BlackRock Capital Allocation Term
Trust" to BLK and "Eaton Vance Municipal Income 2028 Term Trust" to ETN, because the brand alias matched first and the official-name
discovery ran only for non-alias matches. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "KO", "cik_str": 21344, "title": "COCA COLA CO"},
    "1": {"ticker": "CCEP", "cik_str": 1650107, "title": "COCA-COLA EUROPACIFIC PARTNERS plc"},
    "2": {"ticker": "BLK", "cik_str": 2012383, "title": "BlackRock, Inc."},
    "3": {"ticker": "BCAT", "cik_str": 1823776, "title": "BlackRock Capital Allocation Term Trust"},
    "4": {"ticker": "ETN", "cik_str": 1551182, "title": "Eaton Corp plc"},
    "5": {"ticker": "ETX", "cik_str": 1814070, "title": "Eaton Vance Municipal Income 2028 Term Trust"},
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
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map",
                        lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


@pytest.mark.parametrize("name,expected", [
    ("COCA-COLA EUROPACIFIC PARTNERS plc", "CCEP"),
    ("BlackRock Capital Allocation Term Trust", "BCAT"),
    ("Eaton Vance Municipal Income 2028 Term Trust", "ETX"),
])
def test_a_brand_alias_inside_another_issuers_official_name_does_not_win(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


@pytest.mark.parametrize("name,expected", [("Coca-Cola", "KO"), ("BlackRock", "BLK"), ("Eaton", "ETN")])
def test_the_brand_alias_alone_still_routes_to_the_brand(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


# --- one issuer's offering lines (warrants, units, rights) must not make its official name ambiguous -------------------------
LINES = {
    "0": {"ticker": "GRAB", "cik_str": 1855612, "title": "Grab Holdings Ltd"},
    "1": {"ticker": "GRABW", "cik_str": 1855612, "title": "Grab Holdings Ltd"},
    "2": {"ticker": "CORZ", "cik_str": 1878848, "title": "Core Scientific, Inc."},
    "3": {"ticker": "CORZW", "cik_str": 1878848, "title": "Core Scientific, Inc."},
    "4": {"ticker": "CORZR", "cik_str": 1878848, "title": "Core Scientific, Inc."},
    # A symbol ending in Z is not treated as a derivative line (T-Mobile's TMUSZ is a note): the name still abstains.
    "9": {"ticker": "TMUS", "cik_str": 1283699, "title": "T-Mobile US, Inc."},
    "10": {"ticker": "TMUSZ", "cik_str": 1283699, "title": "T-Mobile US, Inc."},
    "5": {"ticker": "GOOGL", "cik_str": 1652044, "title": "Alphabet Inc."},
    "6": {"ticker": "GOOG", "cik_str": 1652044, "title": "Alphabet Inc."},
    "7": {"ticker": "RUSHA", "cik_str": 1012019, "title": "RUSH ENTERPRISES INC"},
    "8": {"ticker": "RUSHB", "cik_str": 1012019, "title": "RUSH ENTERPRISES INC"},
}


def discover(monkeypatch, name):
    parsed = identity.parse_directory(LINES)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    found = identity.discover_company(THESIS.format(name), question_text=True)
    return found.ticker if found else None


@pytest.mark.parametrize("name,expected", [("Grab Holdings Ltd", "GRAB"), ("Core Scientific, Inc.", "CORZ"),
                                           ("Alphabet Inc.", "GOOGL"), ("RUSH ENTERPRISES INC", "RUSHA"), ("T-Mobile US, Inc.", "TMUS")])
def test_warrant_unit_and_right_lines_name_the_common_symbol_and_share_classes_the_first_listed_line(monkeypatch, name, expected):
    # Changed on purpose (round 3, 2026-11-16): these were expected to abstain. Several lines of ONE issuer are one issuer for a
    # company-level question; the first-listed line stands for it. Several issuers still abstain (tests elsewhere).
    assert discover(monkeypatch, name) == expected
