"""Round 3 (2026-11-16): a company-level question about an issuer whose every plausible security belongs to ONE CIK resolves to that issuer.

Found by the 2026-11-16 confirmation (offline): 38 of 44 non-correct official-name questions asked which of the issuer's own securities
(common, preferred, warrants, units, share classes) was meant. Explicit security intent, a typed ticker and a structured selection are
unchanged, and names shared by several issuers still ask. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {}
_n = [0]


def add(ticker, cik, title):
    ROWS[str(_n[0])] = {"ticker": ticker, "cik_str": cik, "title": title}; _n[0] += 1


add("ACME", 1001, "Acme Holdings Inc."); add("ACMEW", 1001, "Acme Holdings Inc."); add("ACMEU", 1001, "Acme Holdings Inc.")      # common, warrants, units
add("PFD", 1002, "Pfd Industries Corp"); add("PFD-PA", 1002, "Pfd Industries Corp"); add("PFD-PB", 1002, "Pfd Industries Corp")    # common, preferred series
add("CLSA", 1003, "Classy Media Group"); add("CLSB", 1003, "Classy Media Group")                                                  # two share classes
add("MRDN", 1004, "Meridian Utility Co"); add("MRDNJ", 1004, "Meridian Utility Co"); add("MRDNK", 1004, "Meridian Utility Co")         # common plus note lines
add("PREF", 1005, "Preferred Bank"); add("PREFP", 1005, "Preferred Bank")                                                         # a name that contains an intent word
add("TWINA", 1006, "Twin Names Ltd"); add("TWINB", 1007, "Twin Names Ltd")                                                        # one name, two issuers
add("FNLC", 1008, "FIRST BANCORP /ME/"); add("FBP", 1009, "FIRST BANCORP /PR/"); add("FBNC", 1010, "FIRST BANCORP /NC/")          # same name, told apart by the tag
add("BN", 1011, "BROOKFIELD Corp /ON/"); add("BAMGF", 1011, "BROOKFIELD Corp /ON/")
add("BEP", 1012, "Brookfield Renewable Partners L.P."); add("BEPH", 1012, "Brookfield Renewable Partners L.P."); add("BEPJ", 1012, "Brookfield Renewable Partners L.P.")
add("BEPC", 1013, "Brookfield Renewable Corp")
add("RAMEL", 1014, "Ramel Partners L.P."); add("RAMEX", 1015, "Ramel Partners L.P.")                                                 # a name shared by two issuers, inside a shorter brand
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


@pytest.mark.parametrize("name,expected", [
    ("Acme Holdings Inc.", "ACME"),            # common, warrants, units: one issuer
    ("Pfd Industries Corp", "PFD"),            # common and preferred series
    ("Classy Media Group", "CLSA"),            # two share classes: the first-listed class stands for the issuer
    ("Meridian Utility Co", "MRDN"),             # common and note lines
    ("Preferred Bank", "PREF"),                # the word 'preferred' is the name, not a request for the preferred shares
    ("Brookfield Renewable Partners L.P.", "BEP"),
])
def test_a_company_level_question_resolves_to_the_issuer(routed, name, expected):
    route(THESIS.format(name))
    assert routed == [expected]


@pytest.mark.parametrize("issuer", ["Classy Media Group", "Meridian Utility Co"])      # lines only the issuer-level rule collapses: two share classes; common plus note lines
@pytest.mark.parametrize("tail", ["units", "Series A"])      # security terms the scope step does not handle keep asking
def test_a_named_kind_of_security_the_scope_step_does_not_handle_keeps_asking(routed, issuer, tail):
    route(THESIS.format(f"the {issuer} {tail}"))
    assert routed == []


@pytest.mark.parametrize("issuer", ["Classy Media Group", "Meridian Utility Co"])
@pytest.mark.parametrize("tail", ["warrants", "preferred stock", "senior notes (the bonds)", "Class B shares", "depositary shares", "convertible notes", "ADR"])
def test_a_named_kind_of_security_is_asked_about_or_labelled_never_resolved_silently(routed, issuer, tail):
    # Round 4 (security scope): these used to ask with the generic "company not identified" message (round 3 kept them from resolving). They now resolve to the
    # issuer and the scope step either asks which line or labels the answer as issuer-level; the stub answer here has no text, so the label goes to the note.
    response = route(THESIS.format(f"the {issuer} {tail}"))
    assert response.routing.get("pipeline") == "security_clarification" or response.routing.get("security_scope", {}).get("action") == "answered_at_issuer_level"


def test_the_existing_warrant_and_unit_reduction_is_unchanged(routed):
    # Before round 3 a warrant or unit line already stood for the common line of its offering (ACME / ACMEW / ACMEU); that is not changed here.
    route(THESIS.format("the Acme Holdings Inc. warrants"))
    assert routed == ["ACME"]


def test_a_typed_ticker_is_the_security_asked_for(routed):
    route(THESIS.format("ACMEW"))
    assert routed == ["ACMEW"]


def test_one_name_shared_by_two_issuers_still_asks_and_offers_both(routed):
    response = route(THESIS.format("Twin Names Ltd"))
    assert routed == []
    assert {"TWINA", "TWINB"} <= {c[0] for c in response.routing["candidates"]}


def test_a_registry_tag_written_in_the_question_tells_same_named_issuers_apart(routed):
    route(THESIS.format("FIRST BANCORP /ME/")); route(THESIS.format("First Bancorp, Inc /PR/"))
    assert routed == ["FNLC", "FBP"]


def test_without_the_tag_the_name_is_shared_and_asks_offering_every_issuer(routed):
    response = route(THESIS.format("First Bancorp"))
    assert routed == []
    assert {"FNLC", "FBP", "FBNC"} <= {c[0] for c in response.routing["candidates"]}


def test_a_clarification_offers_the_issuers_named_by_the_longest_span_first(routed):
    # Two issuers carry the full name; the shorter brand "Brookfield" inside it must not crowd them out.
    response = route(THESIS.format("Ramel Partners L.P."))
    assert routed == []
    assert {"RAMEL", "RAMEX"} <= {c[0] for c in response.routing["candidates"]}
    assert "BN" not in {c[0] for c in response.routing["candidates"]}


def test_the_brand_inside_a_longer_name_does_not_crowd_out_the_named_issuer(routed, monkeypatch):
    rows = dict(ROWS); rows["99"] = {"ticker": "BEPX", "cik_str": 1099, "title": "Brookfield Renewable Partners L.P."}
    parsed = identity.parse_directory(rows); monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    response = route(THESIS.format("Brookfield Renewable Partners L.P."))
    assert routed == []                                                                 # two issuers share the name: ask
    assert {"BEP", "BEPX"} & {c[0] for c in response.routing["candidates"]}           # the named issuers are offered, not only the shorter brand's BN
    assert "BN" not in {c[0] for c in response.routing["candidates"]}
