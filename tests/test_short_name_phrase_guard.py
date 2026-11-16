"""A brand alias or ticker-like word inside a LONGER proper name must not select the brand's issuer when the name is not written exactly as SEC titles it.

Found on development data (2026-11-16): "Eaton Vance Duration Income Fund" routed to Eaton, "Invesco Senior Income" to Invesco, "Universal Health Realty Income" to
Realty Income, "Portland General Electric" to General Electric, "Consumers Bancorp" to The Bancorp. The official full title already routed correctly (2cf0693); these
are the names a person types. A registry tag ("/OR/", "/DE") is not part of the name. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "ETN", "cik_str": 1551182, "title": "Eaton Corp plc"},
    "1": {"ticker": "EVV", "cik_str": 1285650, "title": "Eaton Vance Ltd Duration Income Fund"},
    "2": {"ticker": "EVT", "cik_str": 1285651, "title": "Eaton Vance Tax-Advantaged Dividend Income Fund"},
    "3": {"ticker": "O", "cik_str": 726728, "title": "REALTY INCOME CORP"},
    "4": {"ticker": "UHT", "cik_str": 798783, "title": "UNIVERSAL HEALTH REALTY INCOME TRUST"},
    "5": {"ticker": "GE", "cik_str": 40545, "title": "GENERAL ELECTRIC CO"},
    "6": {"ticker": "POR", "cik_str": 784977, "title": "PORTLAND GENERAL ELECTRIC CO /OR/"},
    "7": {"ticker": "TBBK", "cik_str": 1295401, "title": "Bancorp, Inc."},
    "8": {"ticker": "CBKM", "cik_str": 757010, "title": "CONSUMERS BANCORP INC /OH/"},
    "9": {"ticker": "IVZ", "cik_str": 914208, "title": "Invesco Ltd."},
    "10": {"ticker": "VVR", "cik_str": 1229206, "title": "Invesco Senior Income Trust"},
    "11": {"ticker": "DE", "cik_str": 315189, "title": "DEERE & CO"},
    "12": {"ticker": "LFUS", "cik_str": 889331, "title": "LITTELFUSE INC /DE"},
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


def test_the_registry_tag_is_not_part_of_the_name_key():
    assert identity.name_key("PORTLAND GENERAL ELECTRIC CO /OR/") == "portland general electric"
    assert identity.name_key("LITTELFUSE INC /DE") == "littelfuse"
    assert identity.name_key("Patriot Acquisition Corp./CI") == "patriot acquisition"
    assert identity.name_key("AT&T Inc.") == "at t"          # no tag: unchanged


@pytest.mark.parametrize("name,expected", [
    ("Portland General Electric", "POR"),          # tag-free official name beats "General Electric" inside it
    ("Consumers Bancorp", "CBKM"),                  # beats the word "Bancorp" (The Bancorp, Inc.)
    ("Littelfuse", "LFUS"),
    ("Universal Health Realty Income", "UHT"),      # the name continues only with "Trust"
    ("Invesco Senior Income", "VVR"),               # beats the brand "Invesco"
])
def test_a_name_typed_without_its_legal_tail_routes_to_that_issuer(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


@pytest.mark.parametrize("name", ["Eaton Vance Duration Income Fund", "Eaton Vance Dividend Income Fund"])
def test_a_brand_word_starting_a_longer_name_asks_instead_of_choosing_the_brand(routed, name):
    response = route(THESIS.format(name))
    assert routed == []
    assert response.routing["pipeline"] == "entity_suggestion"
    assert not {"ETN", "IVZ"} & {c[0] for c in response.routing["candidates"]}


def test_the_clarification_for_a_longer_name_offers_that_issuers_securities(routed):
    response = route(THESIS.format("Eaton Vance Duration Income Fund"))
    assert {"EVV", "EVT"} <= {c[0] for c in response.routing["candidates"]}


@pytest.mark.parametrize("name,expected", [
    ("Eaton", "ETN"), ("Eaton Corporation", "ETN"), ("Realty Income", "O"), ("General Electric", "GE"), ("Invesco", "IVZ"),
    ("The Bancorp", "TBBK"), ("Deere & Company", "DE"), ("DE", "DE"),
])
def test_the_brand_or_its_own_name_still_routes_to_the_brand(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


# --- regressions seen on the first development run: the registry tag after an official name, and a legal form after a SPAC-style name ----------
ROWS.update({
    "20": {"ticker": "AGCO", "cik_str": 880266, "title": "AGCO CORP /DE"},
    "21": {"ticker": "RANG", "cik_str": 2035644, "title": "Range Capital Acquisition Corp."},
    "22": {"ticker": "RNGT", "cik_str": 2078653, "title": "Range Capital Acquisition Corp II"},
    "23": {"ticker": "MD", "cik_str": 1885, "title": "Pediatrix Medical Group, Inc."},
    "24": {"ticker": "BCOW", "cik_str": 1990, "title": "1895 Bancorp of Wisconsin, Inc. /MD/"},
})


@pytest.mark.parametrize("name,expected", [
    ("AGCO CORP /DE", "AGCO"),                                # the tag is part of the name written, not Deere's symbol
    ("1895 Bancorp of Wisconsin, Inc. /MD/", "BCOW"),         # nor Pediatrix's
    ("Range Capital Acquisition Corp.", "RANG"),              # the legal form is not a longer name (the sibling is "... Corp II")
    ("Range Capital Acquisition Corp II", "RNGT"),
])
def test_an_official_title_still_routes_to_its_issuer(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


ROWS.update({
    "30": {"ticker": "E", "cik_str": 1002242, "title": "ENI SPA"},
    "31": {"ticker": "MASK", "cik_str": 2020000, "title": "3 E Network Technology Group Ltd"},
})


def test_a_single_letter_ticker_inside_a_longer_name_does_not_win(routed):
    route(THESIS.format("3 E Network Technology"))
    assert routed == ["MASK"]
    routed.clear()
    route(THESIS.format("What is the outlook for E"))
    assert routed == ["E"]            # the symbol on its own still routes


def test_a_word_that_also_stands_on_its_own_keeps_its_issuer(routed, monkeypatch):
    # "T" is AT&T's symbol written alone AND the first letter of "T-Mobile US": one occurrence stands on its own, so the symbol is really there.
    rows = dict(ROWS); rows["40"] = {"ticker": "T", "cik_str": 732717, "title": "AT&T INC."}; rows["41"] = {"ticker": "TMUS", "cik_str": 1283699, "title": "T-Mobile US, Inc."}
    monkeypatch.setattr(identity, "_load_directory", lambda p=identity.parse_directory(rows): p)
    route("What is the investment thesis for T, given competition from T-Mobile US, Inc.?")
    assert routed == ["T"]
