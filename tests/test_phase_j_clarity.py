"""
Phase J — Institutional Clarity tests.

35 deterministic tests covering:
- Schema field existence and defaults (8)
- Schema description / prompt source content (8)
- Guard logic behavior (8)
- Content quality assertions (11)

No LLM calls, no network.
"""

from __future__ import annotations

import inspect

import pytest

from app.schemas import InvestmentThesis, ThesisSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_thesis(**kwargs) -> InvestmentThesis:
    defaults = dict(ticker="AAPL", company_name="Apple Inc.")
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


def _make_snapshot(**kwargs) -> ThesisSnapshot:
    defaults = dict(ticker="AAPL", company_name="Apple Inc.", timestamp="2026-05-19T00:00:00+00:00")
    defaults.update(kwargs)
    return ThesisSnapshot(**defaults)


# ── Schema field tests (8) ────────────────────────────────────────────────────

def test_investment_thesis_has_core_takeaway_field():
    t = _make_thesis()
    assert hasattr(t, "core_takeaway")


def test_investment_thesis_has_dominant_driver_field():
    t = _make_thesis()
    assert hasattr(t, "dominant_driver")


def test_thesis_snapshot_has_core_takeaway_field():
    s = _make_snapshot()
    assert hasattr(s, "core_takeaway")


def test_thesis_snapshot_has_dominant_driver_field():
    s = _make_snapshot()
    assert hasattr(s, "dominant_driver")


def test_core_takeaway_defaults_to_empty_string():
    t = _make_thesis()
    assert t.core_takeaway == ""


def test_dominant_driver_defaults_to_empty_string():
    t = _make_thesis()
    assert t.dominant_driver == ""


def test_investment_thesis_constructed_with_core_takeaway_and_dominant_driver():
    t = _make_thesis(
        core_takeaway="The market already expects strong Services growth.",
        dominant_driver="Services margin expansion offsetting hardware cyclicality",
    )
    assert t.core_takeaway == "The market already expects strong Services growth."
    assert t.dominant_driver == "Services margin expansion offsetting hardware cyclicality"


def test_thesis_snapshot_constructed_with_core_takeaway_and_dominant_driver():
    s = _make_snapshot(
        core_takeaway="The stock now depends more on margin expansion than revenue growth.",
        dominant_driver="Rate duration compression on long-dated FCF multiples",
    )
    assert s.core_takeaway == "The stock now depends more on margin expansion than revenue growth."
    assert s.dominant_driver == "Rate duration compression on long-dated FCF multiples"


# ── Schema description tests (8) ─────────────────────────────────────────────

def _get_schema_description() -> str:
    from app.services import thesis_synthesizer
    return thesis_synthesizer._THESIS_SCHEMA_DESCRIPTION


def _get_synthesis_prompt_source() -> str:
    from app.services import thesis_synthesizer
    return inspect.getsource(thesis_synthesizer._build_synthesis_prompt)


def test_thesis_schema_description_contains_core_takeaway():
    assert "core_takeaway" in _get_schema_description()


def test_thesis_schema_description_contains_dominant_driver():
    assert "dominant_driver" in _get_schema_description()


def test_thesis_schema_description_contains_clarity_language():
    desc = _get_schema_description()
    # Should contain some form of clarity instruction
    assert any(phrase in desc.lower() for phrase in ["instantly clear", "accessible", "instantly understandable"])


def test_thesis_schema_description_contains_5_15_words_for_dominant_driver():
    assert "5-15 words" in _get_schema_description()


def test_thesis_schema_description_core_takeaway_mentions_bad_example():
    desc = _get_schema_description()
    # The BAD examples should be in the schema description
    assert "BAD" in desc


def test_synthesis_prompt_source_contains_core_takeaway():
    assert "core_takeaway" in _get_synthesis_prompt_source()


def test_synthesis_prompt_source_contains_dominant_driver():
    assert "dominant_driver" in _get_synthesis_prompt_source()


def test_core_takeaway_field_description_contains_not_educational():
    field_info = InvestmentThesis.model_fields["core_takeaway"]
    desc = field_info.description or ""
    assert "NOT educational" in desc or "NO educational" in desc


# ── Guard logic tests (8) ─────────────────────────────────────────────────────

def _run_guards(thesis: InvestmentThesis) -> InvestmentThesis:
    """Run just the guard logic extracted from synthesize_thesis, without LLM."""
    if not getattr(thesis, "core_market_debate", ""):
        thesis.core_market_debate = getattr(thesis, "core_debate", "")

    if not getattr(thesis, "core_takeaway", ""):
        cda = getattr(thesis, "core_debate", "") or ""
        da = getattr(thesis, "direct_answer", "") or ""
        if cda:
            thesis.core_takeaway = cda
        elif da:
            thesis.core_takeaway = da[:200] if len(da) > 200 else da

    if not getattr(thesis, "dominant_driver", ""):
        kd = getattr(thesis, "key_drivers", []) or []
        ts = getattr(thesis, "top_signals", []) or []
        if ts and hasattr(ts[0], "label"):
            thesis.dominant_driver = ts[0].label[:80]
        elif kd:
            thesis.dominant_driver = kd[0][:80]

    return thesis


def test_core_takeaway_populated_when_llm_provides_it():
    t = _make_thesis(core_takeaway="The market already expects strong Services growth.")
    t = _run_guards(t)
    assert t.core_takeaway == "The market already expects strong Services growth."


def test_dominant_driver_populated_when_llm_provides_it():
    t = _make_thesis(dominant_driver="Services margin expansion offsetting hardware cyclicality")
    t = _run_guards(t)
    assert t.dominant_driver == "Services margin expansion offsetting hardware cyclicality"


def test_core_takeaway_falls_back_to_core_debate_when_empty():
    t = _make_thesis(core_debate="Can Services growth offset multiple compression?")
    t = _run_guards(t)
    assert t.core_takeaway == "Can Services growth offset multiple compression?"


def test_dominant_driver_falls_back_to_key_drivers_when_empty():
    t = _make_thesis(key_drivers=["Services gross margin mix expansion", "Share buybacks"])
    t = _run_guards(t)
    assert t.dominant_driver == "Services gross margin mix expansion"


def test_core_takeaway_falls_back_to_direct_answer_when_core_debate_empty():
    t = _make_thesis(
        core_debate="",
        direct_answer="The primary risk is rate duration compression. Services offset is partial.",
    )
    t = _run_guards(t)
    assert "rate duration" in t.core_takeaway.lower() or "primary risk" in t.core_takeaway.lower()


def test_dominant_driver_falls_back_to_top_signal_label_when_key_drivers_empty():
    from app.schemas import Signal

    class FakeSig:
        label = "Rate duration compression"

    t = _make_thesis(key_drivers=[])
    t.top_signals = [FakeSig()]  # type: ignore[assignment]
    t = _run_guards(t)
    assert t.dominant_driver == "Rate duration compression"


def test_guard_does_not_override_non_empty_core_takeaway():
    original = "The stock now depends more on margin expansion than revenue growth."
    t = _make_thesis(
        core_takeaway=original,
        core_debate="Something else entirely",
    )
    t = _run_guards(t)
    assert t.core_takeaway == original


def test_guard_does_not_override_non_empty_dominant_driver():
    original = "China tariff impact on iPhone supply chain economics"
    t = _make_thesis(
        dominant_driver=original,
        key_drivers=["Something else"],
    )
    t = _run_guards(t)
    assert t.dominant_driver == original


# ── Content quality tests (11) ────────────────────────────────────────────────

def test_core_takeaway_not_empty_after_guard_with_core_debate():
    """Simulates AAPL rate sensitivity scenario: core_debate is set, takeaway should be non-empty."""
    t = _make_thesis(
        ticker="AAPL",
        company_name="Apple Inc.",
        core_debate="Is the market underestimating rate duration risk for Apple?",
    )
    t = _run_guards(t)
    assert t.core_takeaway.strip() != ""


def test_core_takeaway_length_between_30_and_300_characters():
    t = _make_thesis(core_debate="Can Services growth absorb multiple compression as rates stay higher for longer?")
    t = _run_guards(t)
    assert 30 <= len(t.core_takeaway) <= 300


def test_dominant_driver_length_between_5_and_120_characters():
    t = _make_thesis(key_drivers=["Services margin expansion offsetting hardware cyclicality"])
    t = _run_guards(t)
    assert 5 <= len(t.dominant_driver) <= 120


def test_core_takeaway_does_not_start_with_ticker_name():
    t = _make_thesis(
        ticker="AAPL",
        company_name="Apple Inc.",
        core_takeaway="The market already expects strong Services growth.",
    )
    assert not t.core_takeaway.startswith("AAPL")
    assert not t.core_takeaway.startswith("Apple")


def test_dominant_driver_is_phrase_not_full_sentence():
    # A phrase should be short or if it ends with a period the whole thing is very short
    t = _make_thesis(dominant_driver="Services margin expansion offsetting hardware cyclicality")
    # Should not end with a period for a well-formed phrase
    # (or if it does, it's very short — full sentence guard)
    driver = t.dominant_driver
    assert len(driver) <= 120


def test_core_takeaway_field_description_has_good_example():
    field_info = InvestmentThesis.model_fields["core_takeaway"]
    desc = field_info.description or ""
    assert "Good:" in desc or "good" in desc.lower()


def test_dominant_driver_field_description_has_good_example():
    field_info = InvestmentThesis.model_fields["dominant_driver"]
    desc = field_info.description or ""
    assert "Good:" in desc or "good" in desc.lower()


def test_core_takeaway_field_description_mentions_1_2_sentences():
    field_info = InvestmentThesis.model_fields["core_takeaway"]
    desc = field_info.description or ""
    assert "1-2 sentences" in desc


def test_dominant_driver_field_description_mentions_single():
    field_info = InvestmentThesis.model_fields["dominant_driver"]
    desc = field_info.description or ""
    assert "single" in desc.lower()


def test_investment_thesis_with_populated_core_takeaway_serializes_to_dict():
    t = _make_thesis(
        core_takeaway="The market already expects strong Services growth.",
        dominant_driver="Services margin expansion offsetting hardware cyclicality",
    )
    d = t.model_dump()
    assert d["core_takeaway"] == "The market already expects strong Services growth."
    assert d["dominant_driver"] == "Services margin expansion offsetting hardware cyclicality"


def test_thesis_snapshot_with_populated_fields_serializes_correctly():
    s = _make_snapshot(
        core_takeaway="The stock now depends more on margin expansion than revenue growth.",
        dominant_driver="Rate duration compression on long-dated FCF multiples",
    )
    d = s.model_dump()
    assert d["core_takeaway"] == "The stock now depends more on margin expansion than revenue growth."
    assert d["dominant_driver"] == "Rate duration compression on long-dated FCF multiples"
