"""Explicit security questions (2026-11-16, confirmation 2 diagnostic and offline sample).

Before: "the Acme warrants" was answered as the Acme thesis under Acme's name and common ticker, and nothing said so (72 of 140 intent questions per arm in the
second confirmation; 8 of 12 in the offline sample of user-visible answers). Now: ask which line when several fit and none was resolved; otherwise answer at
issuer level and say so in the first sentence of the visible answer; ordinary questions are untouched. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router, security_scope as scope

ROWS = {}
_n = [0]


def add(ticker, cik, title):
    ROWS[str(_n[0])] = {"ticker": ticker, "cik_str": cik, "title": title}; _n[0] += 1


add("ACME", 2001, "Acme Holdings Inc."); add("ACMEW", 2001, "Acme Holdings Inc."); add("ACMEU", 2001, "Acme Holdings Inc.")     # one warrant line, one unit line
add("DUOO", 2002, "Duo Therapeutics Corp"); add("DUOOW", 2002, "Duo Therapeutics Corp"); add("DUOOWS", 2002, "Duo Therapeutics Corp")   # two warrant lines
add("PFDX", 2003, "Pfdx Industries Corp"); add("PFDX-PA", 2003, "Pfdx Industries Corp"); add("PFDX-PB", 2003, "Pfdx Industries Corp")  # two preferred series
add("SOLR", 2004, "Solar Grid Inc."); add("SOLR-PJ", 2004, "Solar Grid Inc.")                                                          # one preferred series
add("CLSA", 2005, "Classy Media Group"); add("CLSB", 2005, "Classy Media Group")                                                      # two share classes
add("ONLY", 2006, "Onlyco Ltd")                                                                                                       # one line
add("ZZFN", 2007, "Zeta Foreign NV"); add("ZZFNF", 2007, "Zeta Foreign NV"); add("ZZFNY", 2007, "Zeta Foreign NV")                  # two foreign/ADR lines
add("RYAL", 2008, "Royal Banco SA"); add("RYALF", 2008, "Royal Banco SA")                                                           # one foreign line
add("PREF", 2009, "Preferred Bank"); add("PREFX", 2009, "Preferred Bank")                                                            # a name that contains a security word
add("WRNT", 2010, "Warrant Group Inc.")                                                                                              # likewise
THESIS = "What is the investment thesis for {}, what supports it, and what could invalidate it? Distinguish reported facts from inference and cite material claims."
THESIS_BODY = {"investment_thesis": {"direct_answer": "ORIGINAL ANSWER", "analysis_foundation_constraints": ["existing constraint"], "ticker": "X"},
               "source_answer": {"unanswered_parts": ["existing gap"]}}


@pytest.fixture
def routed(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []

    def pipeline(**kwargs):
        seen.append(kwargs["company"].ticker)
        import copy
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agents_used=[], answer=copy.deepcopy(THESIS_BODY), routing={"pipeline": "investment_thesis"})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


def visible(response):
    return response.answer["investment_thesis"]["direct_answer"]


@pytest.mark.parametrize("question,kind_words", [
    ("the Acme Holdings Inc. warrants", ["warrants", "Acme Holdings Inc.", "issuer level", "not available"]),
    ("the Solar Grid Inc. preferred stock", ["preferred stock", "Solar Grid Inc.", "issuer level", "not available"]),
    ("the Onlyco Ltd senior notes (the bonds)", ["notes or bonds", "Onlyco Ltd", "issuer level", "lists no line for the notes or bonds", "not available"]),
    ("Onlyco Ltd Class B shares", ["share class", "only one share class", "issuer level", "not available"]),
    ("the Royal Banco SA depositary shares", ["depositary shares", "Royal Banco SA", "issuer level", "not available"]),
    ("the Acme Holdings Inc. convertible notes due 2030", ["notes or bonds", "lists no line for", "issuer level"]),
])
def test_an_answer_about_a_named_kind_of_security_says_it_is_at_issuer_level(routed, question, kind_words):
    response = route(THESIS.format(question))
    text = visible(response)
    assert text.startswith(scope.LABEL_START), text[:120]
    assert text.rstrip().endswith("ORIGINAL ANSWER")               # the original answer follows the label, unchanged
    for word in kind_words:
        assert word in text, (word, text[:400])
    assert response.answer["investment_thesis"]["analysis_foundation_constraints"][0] == text.split("\n\n")[0]
    assert any("Security-specific evidence" in part for part in response.answer["source_answer"]["unanswered_parts"])
    assert response.routing["security_scope"]["security_specific_evidence"] == "unavailable"


def test_the_one_matching_line_is_named(routed):
    text = visible(route(THESIS.format("the Acme Holdings Inc. warrants")))
    assert "(ACMEW)" in text and "(ACME)" in text                 # the warrant line asked about, and the line the answer is about
    assert routed == ["ACME"]                                     # the pipeline still runs on the issuer's common line


@pytest.mark.parametrize("question,expected_lines", [
    ("the Duo Therapeutics Corp warrants", {"DUOOW", "DUOOWS"}),
    ("the Pfdx Industries Corp preferred stock", {"PFDX-PA", "PFDX-PB"}),
    ("Classy Media Group Class B shares", {"CLSA", "CLSB"}),
    ("the Zeta Foreign NV depositary shares", {"ZZFNF", "ZZFNY"}),
])
def test_several_lines_of_the_kind_asked_ask_which_one(routed, question, expected_lines):
    response = route(THESIS.format(question))
    assert routed == []                                           # the pipeline did not run
    assert response.routing["pipeline"] == "security_clarification"
    assert {t.replace("-", ".") for t, _ in response.routing["candidates"]} == {t.replace("-", ".") for t in expected_lines}
    text = response.answer["general"]["answer"]
    assert "Which one do you mean?" in text and "not available" in text


def test_a_typed_security_ticker_is_not_asked_about(routed):
    response = route(THESIS.format("DUOOW warrants"))
    assert routed != [] and visible(response).startswith(scope.LABEL_START)
    assert "(DUOOW)" in visible(response)


@pytest.mark.parametrize("question", [
    "Acme Holdings Inc.", "Preferred Bank", "Warrant Group Inc.",                                                  # names that contain a security word
    "Acme Holdings Inc. and the bond market", "bond yields at Acme Holdings Inc.", "Does Acme Holdings Inc. face a class action?",
    "How many business units does Acme Holdings Inc. have?", "Is Acme Holdings Inc. a preferred supplier to retailers?",
    "Does the evidence warrant a closer look at Acme Holdings Inc.?", "Acme Holdings Inc. earnings this class of assets",
    "Acme Holdings Inc. interest rate sensitivity and corporate governance", "Acme Holdings Inc. note on revenue recognition",
])
def test_ordinary_questions_are_untouched(routed, question):
    response = route(THESIS.format(question) if "?" not in question and "Does" not in question and "How" not in question else question)
    assert routed, "the pipeline ran"
    text = visible(response)
    assert text == "ORIGINAL ANSWER" and "security_scope" not in response.routing


def test_several_kinds_are_named_together(routed):
    text = visible(route(THESIS.format("the Acme Holdings Inc. warrants and preferred stock")))
    assert text.startswith(scope.LABEL_START) and "warrants and preferred stock" in text


def test_lexicon_cases():
    k = lambda q: scope.requested_kinds(q)
    assert k("thesis for the warrants") == ["warrants"] and k("the evidence warrants a closer look") == []
    assert k("senior notes") == ["debt"] and k("the bond market") == [] and k("their bonds") == ["debt"]
    assert k("Class B shares") == ["share_class"] and k("class action") == []
    assert k("preferred stock") == ["preferred"] and k("preferred supplier") == []


def test_the_letter_naming_a_share_class_is_not_a_ticker(routed, monkeypatch):
    # "Class B shares": the B must not be read as the ticker B (a different issuer), which made the question unresolvable.
    rows = dict(ROWS); rows["99"] = {"ticker": "B", "cik_str": 9999, "title": "Barnes Group Inc"}
    parsed = identity.parse_directory(rows); monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    response = route(THESIS.format("Onlyco Ltd Class B shares"))
    assert routed == ["ONLY"] and visible(response).startswith(scope.LABEL_START)
    routed.clear(); route(THESIS.format("B"))
    assert routed == ["B"]                                    # the ticker B on its own is still the ticker


@pytest.mark.parametrize("question", [
    "What is the investment thesis for Vibra Energia S.A./ADR, what supports it, and what could invalidate it?",
    "Which valuation assumptions would make Inficon Holding AG/ADR attractive or unattractive?",
    "What is the investment thesis for RESOLUTION MINERALS LTD/ADR, what supports it?",
    "What about Industria de Diseno Textil Inditex SA / ADR today?",
])
def test_a_registry_tag_in_an_official_name_is_not_a_security_term(question):
    assert scope.requested_kinds(question) == []


def test_an_adr_named_outside_a_registry_tag_is_still_a_security_term():
    assert scope.requested_kinds("What is the outlook for the Vibra Energia S.A. ADR?") == ["depositary"]
    assert scope.requested_kinds("Compare Inficon Holding AG/ADR with its ADRs") == ["depositary"]
