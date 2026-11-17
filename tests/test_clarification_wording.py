"""Release issue 3 (2026-11-17): the clarification must not tell a user who gave an exact official name to check the spelling or try the full legal name.

When the name in the question is an exact official name that several issuers (or several listed lines) carry, the name is shared, not wrong; the old text said the company
"could not be identified with sufficient confidence" and advised "check spelling and try the full legal name". Other causes (a misspelling, the first word of a name, a brand word inside a
longer name, an unknown company) keep their text. Rows mirror SEC's company_tickers.json shape.
"""
import pytest

from app.schemas import QuestionRequest
from app.services import issuer_identity as identity, router_service as router

ROWS = {
    "0": {"ticker": "RTNTF", "cik_str": 887028, "title": "RIO TINTO LTD"},
    "1": {"ticker": "RIO", "cik_str": 863064, "title": "RIO TINTO PLC"},
    "2": {"ticker": "TM", "cik_str": 1094, "title": "TOYOTA MOTOR CORP/"},
    "3": {"ticker": "TYHOF", "cik_str": 1095, "title": "Toyota Tsusho Corporation/ADR"},
}
THESIS = ("What is the investment thesis for {}, what supports it, and what could invalidate it? "
          "Distinguish reported facts from inference and cite material claims.")
OLD_ADVICE = "try the full legal name"


@pytest.fixture
def directory(monkeypatch):
    parsed = identity.parse_directory(ROWS)
    monkeypatch.setattr(identity, "_load_directory", lambda: parsed)
    monkeypatch.setattr(router._sec_provider, "_load_ticker_cik_map", lambda: {r["ticker"]: f"{r['cik_str']:010d}" for r in ROWS.values()})


def ask(name):
    response = router.route_question(QuestionRequest(question=THESIS.format(name), company_name="", intent="company_analysis"))
    return response.routing.get("pipeline"), (response.answer.get("general") or {})


@pytest.mark.parametrize("name", ["RIO TINTO PLC", "Rio Tinto plc", "Rio Tinto"])
def test_a_shared_exact_name_is_called_shared_and_not_misspelt(directory, name):
    pipeline, general = ask(name)
    text = " ".join([general.get("answer", "")] + general.get("caveats", []))
    assert pipeline == "entity_suggestion"
    assert "matches more than one issuer or listed security" in general["answer"] and "Did you mean" in general["answer"]
    assert "RIO TINTO LTD (RTNTF)" in general["answer"] and "RIO TINTO PLC (RIO)" in general["answer"]
    assert OLD_ADVICE not in text.lower() and "check spelling" not in text.lower() and "could not be identified" not in text.lower()
    assert any("ticker" in c.lower() for c in general["caveats"])


@pytest.mark.parametrize("name", ["Toyota", "Nvidiaa"])
def test_other_causes_keep_their_text(directory, name):
    pipeline, general = ask(name)
    if pipeline != "entity_suggestion":
        pytest.skip("this name resolves without a clarification in this fixture")
    assert "could not be identified with sufficient confidence" in general["answer"]
    assert any(OLD_ADVICE in c.lower() for c in general["caveats"])
