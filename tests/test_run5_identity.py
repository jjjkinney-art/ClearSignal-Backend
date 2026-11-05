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


# -- eligibility of the foreign-security OTC line rule ------------------------------
# The rule applies only when every match shares one CIK, several unsuffixed symbols
# remain, and exactly one of them is not a five-letter symbol ending in F (an OTC
# line for a foreign issuer's ordinary or preferred shares). Everything else is unchanged.

EDGE_ROWS = {
    # Share classes plus an OTC line: two non-F symbols remain, so it abstains.
    "0": {"ticker": "CLSA", "cik_str": 501, "title": "CLASSCO HOLDINGS INC"},
    "1": {"ticker": "CLSB", "cik_str": 501, "title": "CLASSCO HOLDINGS INC"},
    "2": {"ticker": "CLSHF", "cik_str": 501, "title": "CLASSCO HOLDINGS INC"},
    # Common, an exchange-listed preferred (suffixed) and OTC preferred lines.
    "3": {"ticker": "PRFC", "cik_str": 502, "title": "PREFCO ENERGY INC"},
    "4": {"ticker": "PRFC-PA", "cik_str": 502, "title": "PREFCO ENERGY INC"},
    "5": {"ticker": "PRFPF", "cik_str": 502, "title": "PREFCO ENERGY INC"},
    "6": {"ticker": "PRFQF", "cik_str": 502, "title": "PREFCO ENERGY INC"},
    # An OTC ADR line (five letters ending in Y) beside the ordinary-share line.
    "7": {"ticker": "ADRCY", "cik_str": 503, "title": "ADRCO AG"},
    "8": {"ticker": "ADRCF", "cik_str": 503, "title": "ADRCO AG"},
    # Only OTC lines: nothing distinguishes them, so it abstains.
    "9": {"ticker": "ONLYF", "cik_str": 504, "title": "ONLYCO LTD"},
    "10": {"ticker": "ONLZF", "cik_str": 504, "title": "ONLYCO LTD"},
    # A different issuer with a similar name.
    "11": {"ticker": "PRFE", "cik_str": 505, "title": "PREFCO ENERGY PARTNERS INC"},
    # An ordinary five-letter exchange symbol ending in F for a separate issuer.
    "12": {"ticker": "SOLOF", "cik_str": 506, "title": "SOLO FINANCE CORP"},
}


@pytest.fixture
def edge_directory(monkeypatch):
    parsed = identity.parse_directory(EDGE_ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    return parsed


@pytest.mark.parametrize("name,expected", [
    ("CLASSCO HOLDINGS INC", None),        # share classes still need a selection
    ("PREFCO ENERGY INC", "PRFC"),         # common beside exchange and OTC preferred lines
    ("ADRCO AG", "ADRCY"),                 # the US ADR line beside the OTC ordinary line
    ("ONLYCO LTD", None),                  # only OTC lines: unchanged abstention
    ("PREFCO ENERGY PARTNERS INC", "PRFE"),  # the longer, different registrant name wins
    ("SOLO FINANCE CORP", "SOLOF"),        # a sole symbol is never excluded by the rule
])
def test_foreign_security_line_rule_eligibility(edge_directory, name, expected):
    assert discover(THESIS.format(name)) == expected


def test_two_named_issuers_stay_ambiguous_whatever_their_otc_lines(edge_directory):
    assert discover("Compare PREFCO ENERGY INC with ADRCO AG on margins.") is None
