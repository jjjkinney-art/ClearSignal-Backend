"""Issuer identification for the run-5 cohort's names (development evidence).

Run 5 left "SUMITOMO MITSUI FINANCIAL GROUP, INC." unresolved (its US listing
SMFG beside the OTC foreign-ordinary line SMFNF on one CIK) and
"BLUE OWL CAPITAL INC." unresolved (Blue Owl Capital Corp shares the name core;
an existing safeguard, kept), and offered unrelated suggestions (Ford, Citigroup, Applied Materials) from
fuzzy matches on other words of the question. Rows mirror SEC's directory shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "SMFG", "cik_str": 1022837, "title": "SUMITOMO MITSUI FINANCIAL GROUP, INC."},
    "1": {"ticker": "OWL", "cik_str": 1823945, "title": "BLUE OWL CAPITAL INC."},
    "2": {"ticker": "OBDC", "cik_str": 1655888, "title": "Blue Owl Capital Corp"},
    "3": {"ticker": "OTF", "cik_str": 1747777, "title": "Blue Owl Technology Finance Corp."},
    "4": {"ticker": "GOOGL", "cik_str": 1652044, "title": "Alphabet Inc."},
    "5": {"ticker": "GOOG", "cik_str": 1652044, "title": "Alphabet Inc."},
    "6": {"ticker": "SMFNF", "cik_str": 1022837, "title": "SUMITOMO MITSUI FINANCIAL GROUP, INC."},
    "7": {"ticker": "F", "cik_str": 37996, "title": "FORD MOTOR CO"},
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


def test_a_us_listing_beside_its_foreign_ordinary_otc_line_names_the_issuer(directory):
    assert discover(THESIS.format("SUMITOMO MITSUI FINANCIAL GROUP, INC.")) == "SMFG"
    # Two share classes of one issuer still need an explicit selection.
    assert discover(THESIS.format("Alphabet Inc.")) is None


def test_registrants_sharing_a_name_core_stay_ambiguous_even_with_a_legal_form(directory):
    # Existing safeguard (AB INC / AB CORP): a written legal form does not choose
    # between registrants that share a name core. Changing that is a proposal,
    # not part of this fix.
    for name in ("BLUE OWL CAPITAL INC.", "Blue Owl Capital Corp", "Blue Owl Capital"):
        assert discover(THESIS.format(name)) is None


@pytest.fixture
def routed(directory, monkeypatch):
    seen = []

    def pipeline(**kwargs):
        seen.append(kwargs["company"].ticker)
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agent="stub",
                                   agents_used=[], answer={})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map",
                        lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


def test_the_us_listing_reaches_research_on_its_own_issuer(routed):
    route(THESIS.format("SUMITOMO MITSUI FINANCIAL GROUP, INC."))
    assert routed == ["SMFG"]


def test_an_ambiguous_exact_name_suggests_its_own_registrants_not_fuzzy_matches(routed):
    response = route(THESIS.format("BLUE OWL CAPITAL INC."))
    assert routed == []
    general = (response.answer or {}).get("general") or {}
    text = general.get("answer", "")
    # The named registrants are suggested, never Ford, Citigroup or Applied
    # Materials from "for", "cite" or "material".
    assert not any(word in text for word in ("Ford", "Citigroup", "Applied Materials"))
    assert "Did you mean" in text and "(OWL)" in text and "(OBDC)" in text
