"""Comparisons between securities of ONE issuer (2026-11-17): the answer names the securities asked about and says what it cannot do.

Before: "Compare F with F-PB" and "Compare RGTI with RGTIW" returned a plain thesis for the common ticker and never mentioned the second security; "Compare GOOG and GOOGL" ranked the
two lines as a "tie"; "Compare Alphabet Class A shares with Alphabet Class C shares" ranked Alphabet against Citigroup (the C of "Class C"). Comparisons between different issuers keep the ranking.
"""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity as identity, router_service as router, security_scope as scope

ROWS = {}
_n = [0]


def add(ticker, cik, title):
    ROWS[str(_n[0])] = {"ticker": ticker, "cik_str": cik, "title": title}; _n[0] += 1


add("GOOGL", 1652044, "Alphabet Inc."); add("GOOG", 1652044, "Alphabet Inc.")
add("F", 37996, "FORD MOTOR CO"); add("F-PB", 37996, "FORD MOTOR CO"); add("F-PC", 37996, "FORD MOTOR CO")
add("RGTI", 1838359, "Rigetti Computing, Inc."); add("RGTIW", 1838359, "Rigetti Computing, Inc.")
add("AAPL", 320193, "Apple Inc."); add("MSFT", 789019, "MICROSOFT CORP"); add("BAC", 70858, "BANK OF AMERICA CORP /DE/"); add("DE", 315189, "DEERE & CO"); add("C", 831001, "CITIGROUP INC")
BODY = {"investment_thesis": {"direct_answer": "ORIGINAL ANSWER", "analysis_foundation_constraints": [], "ticker": "X"}, "source_answer": {"unanswered_parts": []}}


@pytest.fixture
def routed(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    seen = []

    def pipeline(**kwargs):
        import copy
        seen.append(kwargs["company"].ticker)
        return AgentAnswerResponse(company=kwargs["company"].ticker, request_id="x", agents_used=[], answer=copy.deepcopy(BODY), routing={"pipeline": "investment_thesis"})
    monkeypatch.setattr(router, "_run_investment_pipeline", pipeline)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})
    return seen


def route(question):
    return router.route_question(QuestionRequest(question=question, company_name="", intent="company_analysis"))


def text(response):
    return response.answer["investment_thesis"]["direct_answer"]


@pytest.mark.parametrize("question,named", [
    ("Compare GOOG and GOOGL", ["GOOG", "GOOGL"]),
    ("Compare F with F-PB", ["F", "F.PB"]),
    ("Compare RGTI with RGTIW", ["RGTI", "RGTIW"]),
    ("Which is better, F-PB or F-PC?", ["F.PB", "F.PC"]),
    ("compare $RGTI to $RGTIW", ["RGTI", "RGTIW"]),
])
def test_two_lines_of_one_issuer_are_labelled_with_the_securities_named(routed, question, named):
    response = route(question)
    assert response.routing.get("pipeline") != "comparative_ranking"
    t = text(response)
    assert t.startswith(scope.LABEL_START) and "one issuer" in t and "does not distinguish between them" in t and "not available" in t
    assert all(name in t for name in named), t[:300]
    assert t.rstrip().endswith("ORIGINAL ANSWER")


def test_class_designators_in_a_comparison_are_named_and_not_citigroup(routed):
    response = route("Compare Alphabet Class A shares with Alphabet Class C shares")
    t = text(response)
    assert routed and routed[0] in {"GOOGL", "GOOG"}
    assert "Class A shares and Class C shares" in t and "does not distinguish between them" in t


def test_common_stock_against_its_warrants_says_what_is_missing(routed):
    t = text(route("Compare Rigetti Computing, Inc. common stock with its warrants"))
    assert t.startswith(scope.LABEL_START) and "warrants" in t and "not available" in t


@pytest.mark.parametrize("question", ["Compare AAPL and MSFT", "Compare Apple and Microsoft", "Compare BAC with $DE", "Compare BANK OF AMERICA CORP /DE/ with Apple"])
def test_comparisons_between_different_issuers_still_rank(routed, question):
    response = route(question)
    assert response.routing.get("pipeline") == "comparative_ranking" and routed == []


def test_the_registry_tag_is_not_a_second_issuer(routed):
    response = route("Compare the BANK OF AMERICA CORP /DE/ senior notes with its common stock")
    assert response.routing.get("pipeline") != "comparative_ranking"
    assert text(response).startswith(scope.LABEL_START)
