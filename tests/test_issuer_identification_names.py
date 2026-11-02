"""Issuer identification for SEC-style names found by run 3 (2026-11-01).

The frozen version abstained on "SOUTHERN COPPER CORP" (the shorter official
name "SOUTHERN CO" sits inside it) and "LINCOLN NATIONAL CORP" (common and
preferred symbols of one issuer), and routed "BETTERWARE DE MEXICO, S.A.P.I.
DE C.V" to ticker DE. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "SCCO", "cik_str": 1001838, "title": "SOUTHERN COPPER CORP/"},
    "1": {"ticker": "SO", "cik_str": 92122, "title": "SOUTHERN CO"},
    "2": {"ticker": "SOJC", "cik_str": 92122, "title": "SOUTHERN CO"},
    "3": {"ticker": "LNC", "cik_str": 59558, "title": "LINCOLN NATIONAL CORP"},
    "4": {"ticker": "LNC-PD", "cik_str": 59558, "title": "LINCOLN NATIONAL CORP"},
    "5": {"ticker": "BWMX", "cik_str": 1788257, "title": "BETTERWARE DE MEXICO, S.A.P.I. DE C.V"},
    "6": {"ticker": "DE", "cik_str": 315189, "title": "DEERE & CO"},
    "7": {"ticker": "GOOGL", "cik_str": 1652044, "title": "Alphabet Inc."},
    "8": {"ticker": "GOOG", "cik_str": 1652044, "title": "Alphabet Inc."},
}
THESIS = ("What is the investment thesis for {}, what supports it, and what could invalidate it? "
          "Distinguish reported facts from inference and cite material claims.")


@pytest.fixture
def directory(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    return parsed


def discover(text):
    found = identity.discover_company(text, question_text=True)
    return found.ticker if found else None


def test_the_longest_exact_name_wins_over_a_shorter_name_inside_it(directory):
    assert discover(THESIS.format("SOUTHERN COPPER CORP")) == "SCCO"
    # Unchanged limit: SOUTHERN CO's other securities carry no class suffix
    # (SO, SOJC), so its base symbol is not unique and it still abstains.
    assert discover(THESIS.format("SOUTHERN CO")) is None
    # Two separately named companies remain ambiguous.
    assert discover("Compare SOUTHERN COPPER CORP with SOUTHERN CO") is None


def test_one_issuers_securities_resolve_to_its_base_symbol(directory):
    assert discover(THESIS.format("LINCOLN NATIONAL CORP")) == "LNC"
    # Two base symbols of one issuer (two share classes) still need a selection.
    assert discover(THESIS.format("Alphabet Inc.")) is None


def test_unrelated_text_identifies_nothing(directory):
    assert discover("How do interest rates affect bank stocks?") is None


@pytest.fixture
def routed(monkeypatch, directory):
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


def test_a_ticker_word_inside_an_official_name_does_not_select_another_company(routed):
    route(THESIS.format("BETTERWARE DE MEXICO, S.A.P.I. DE C.V"))
    assert routed == ["BWMX"]


def test_a_plain_ticker_question_keeps_its_ticker(routed):
    route("What is the investment thesis for DE, what supports it, and what could invalidate it?")
    assert routed == ["DE"]


def test_full_names_route_to_their_issuers(routed):
    for name in ("SOUTHERN COPPER CORP", "LINCOLN NATIONAL CORP"):
        route(THESIS.format(name))
    assert routed == ["SCCO", "LNC"]
