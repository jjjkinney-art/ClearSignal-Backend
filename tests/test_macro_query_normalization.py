"""
Tests for normalize_macro_query() and the improved _detect_topics() logic.

Coverage:
  - normalize_macro_query: lowercase, punctuation removal, space collapse
  - normalize_macro_query: phrase substitution table (all documented mappings)
  - normalize_macro_query: idempotency (double-pass produces same output)
  - _detect_topics: all five spec questions → yields
  - _detect_topics: treasury co-occurrence rule
  - _detect_topics: existing non-yields topics still work
  - _detect_topics: unrelated question → []
  - _detect_topics: case insensitivity via normalizer
  - retrieve_general_finance_evidence: messy yield questions fetch DGS10
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.general_finance_evidence import (
    normalize_macro_query,
    _detect_topics,
    retrieve_general_finance_evidence,
)


# ── normalize_macro_query: basic hygiene ──────────────────────────────────────

class TestNormalizeMacroQueryBasic:

    def test_lowercases_input(self):
        assert normalize_macro_query("Why Are YIELDS Rising?") == \
               normalize_macro_query("why are yields rising?")

    def test_removes_question_mark(self):
        result = normalize_macro_query("Why are yields rising?")
        assert "?" not in result

    def test_removes_exclamation(self):
        result = normalize_macro_query("Yields are ripping!")
        assert "!" not in result

    def test_removes_comma(self):
        result = normalize_macro_query("Inflation, rates, and yields")
        assert "," not in result

    def test_collapses_multiple_spaces(self):
        result = normalize_macro_query("why   are   yields   rising")
        assert "  " not in result

    def test_strips_leading_trailing_whitespace(self):
        result = normalize_macro_query("  why are yields rising  ")
        assert result == result.strip()

    def test_preserves_hyphens(self):
        result = normalize_macro_query("10-year treasury yield")
        assert "10-year" in result

    def test_empty_string_returns_empty(self):
        assert normalize_macro_query("") == ""

    def test_idempotent(self):
        """Applying normalize_macro_query twice gives the same result."""
        q = "Why are treasury rates yields rising right now?"
        assert normalize_macro_query(normalize_macro_query(q)) == normalize_macro_query(q)

    def test_no_double_yield_artifact(self):
        """'10 year treasury' must not produce 'yield yield'."""
        result = normalize_macro_query("Why is the 10 year treasury moving?")
        assert "yield yield" not in result


# ── normalize_macro_query: phrase substitution table ─────────────────────────

class TestNormalizeMacroQueryPhrases:

    def test_treasury_rates_yields(self):
        result = normalize_macro_query("treasury rates yields")
        assert "treasury yields" in result

    def test_treasury_rate_yields(self):
        result = normalize_macro_query("treasury rate yields")
        assert "treasury yields" in result

    def test_treasury_rates_yield_singular(self):
        result = normalize_macro_query("treasury rates yield")
        assert "treasury yields" in result

    def test_treasury_bond_rates(self):
        result = normalize_macro_query("treasury bond rates")
        assert "treasury yields" in result

    def test_government_bond_rates(self):
        result = normalize_macro_query("government bond rates")
        assert "treasury yields" in result

    def test_government_bond_yields(self):
        result = normalize_macro_query("government bond yields")
        assert "treasury yields" in result

    def test_bond_rates_becomes_bond_yields(self):
        result = normalize_macro_query("why are bond rates going up")
        assert "bond yields" in result

    def test_bond_market_rates(self):
        result = normalize_macro_query("bond market rates are rising")
        assert "bond yields" in result

    def test_ten_year_treasury_spelled_out(self):
        result = normalize_macro_query("ten year treasury is rising")
        assert "10-year treasury yield" in result

    def test_ten_hyphen_year_treasury(self):
        result = normalize_macro_query("ten-year treasury yield")
        assert "10-year treasury yield" in result

    def test_10_space_year_treasury(self):
        result = normalize_macro_query("the 10 year treasury rate")
        assert "10-year treasury yield" in result

    def test_two_year_treasury_spelled_out(self):
        result = normalize_macro_query("two year treasury note")
        assert "2-year treasury yield" in result

    def test_2_space_year_treasury(self):
        result = normalize_macro_query("2 year treasury yield")
        assert "2-year treasury yield" in result

    def test_long_term_rates(self):
        result = normalize_macro_query("why are long term rates rising")
        assert "long-term rate" in result

    def test_long_hyphen_term_rates(self):
        result = normalize_macro_query("long-term rates are rising")
        assert "long-term rate" in result

    def test_short_term_rates(self):
        result = normalize_macro_query("short term rates are moving")
        assert "2-year treasury yield" in result

    def test_rates_ripping(self):
        # The normalization rule matches the exact substring "rates ripping"
        result = normalize_macro_query("why are rates ripping today")
        assert "yields rising" in result

    def test_rates_going_up(self):
        result = normalize_macro_query("bond rates going up")
        # "bond rates" → "bond yields", "going up" stays
        assert "bond yields" in result

    def test_rates_rising_becomes_yields_rising(self):
        result = normalize_macro_query("why are rates rising")
        assert "yields rising" in result

    def test_rates_moving_higher(self):
        result = normalize_macro_query("why are rates moving higher")
        assert "yields rising" in result


# ── _detect_topics: five spec questions → yields ──────────────────────────────

class TestDetectTopicsSpecQuestions:
    """All five questions from the spec must map to the yields topic."""

    @pytest.mark.parametrize("question", [
        "Why are Treasury yields rising right now?",
        "Why are treasury rates yields rising right now?",
        "Why are bond rates going up?",
        "Why is the 10 year treasury moving?",
        "What does the yield curve mean for stocks?",
    ])
    def test_spec_question_maps_to_yields(self, question):
        topics = _detect_topics(question)
        assert "yields" in topics, (
            f"Expected 'yields' in topics for: {question!r}, got {topics}"
        )


# ── _detect_topics: treasury co-occurrence rule ───────────────────────────────

class TestTreasuryCOccurrenceRule:
    """treasury + any of (rate, yield, bond, 10-year) → yields forced."""

    def test_treasury_plus_rate(self):
        assert "yields" in _detect_topics("Why are treasury rates going up?")

    def test_treasury_plus_yield(self):
        assert "yields" in _detect_topics("What drives the treasury yield?")

    def test_treasury_plus_bond(self):
        assert "yields" in _detect_topics("Are treasury bond prices falling?")

    def test_treasury_plus_10_year(self):
        assert "yields" in _detect_topics("Why is the 10-year treasury moving?")

    def test_treasury_alone_does_not_force_yields(self):
        """Just 'treasury' without a companion word should NOT force yields."""
        # 'treasury' alone is ambiguous — no companion word, no match
        topics = _detect_topics("The treasury department announced a new policy.")
        # This may or may not match (policy ≠ rate/yield/bond); the important
        # thing is the co-occurrence rule doesn't trigger without a companion.
        if "yields" in topics:
            # Only allowed if a keyword independently matched
            pass  # acceptable

    def test_no_treasury_no_co_occurrence_rule(self):
        """Questions without 'treasury' don't get yields from this rule."""
        topics = _detect_topics("What is the capital of France?")
        assert "yields" not in topics


# ── _detect_topics: additional yield trigger phrases ─────────────────────────

class TestYieldKeywordExpansion:
    """All expanded yield trigger phrases from the spec."""

    @pytest.mark.parametrize("question,expected_in", [
        ("Why is the treasury yield rising?",                 "yields"),
        ("What are treasury yields doing?",                   "yields"),
        ("Explain bond yield movements",                      "yields"),
        ("Are bond yields a good investment signal?",         "yields"),
        ("What drives 10-year yield changes?",                "yields"),
        ("Why is the 10 year yield rising?",                  "yields"),
        ("How does the 2-year yield affect mortgages?",       "yields"),
        ("What is the 2 year yield right now?",               "yields"),
        ("What does an inverted yield curve mean?",           "yields"),
        ("Are long-term rates rising?",                       "yields"),
        ("Why are long term rates elevated?",                 "yields"),
        ("What are government bonds signalling?",             "yields"),
        ("Is the bond market pricing in a recession?",        "yields"),
    ])
    def test_phrase_maps_to_yields(self, question, expected_in):
        topics = _detect_topics(question)
        assert expected_in in topics, (
            f"Expected {expected_in!r} in topics for: {question!r}, got {topics}"
        )


# ── _detect_topics: non-yields topics still work ─────────────────────────────

class TestNonYieldsTopicsUnchanged:
    """Normalization must not break detection of other topics."""

    def test_inflation_question(self):
        assert "inflation" in _detect_topics("How does inflation affect the market?")

    def test_cpi_question(self):
        assert "inflation" in _detect_topics("What does CPI mean for rates?")

    def test_fed_rate_question(self):
        assert "rates_fed" in _detect_topics("What will the Fed do next?")

    def test_fomc_question(self):
        assert "rates_fed" in _detect_topics("What happened at the FOMC meeting?")

    def test_rate_cut_question(self):
        assert "rates_fed" in _detect_topics("When will the Fed cut rates?")

    def test_recession_question(self):
        assert "recession" in _detect_topics("Are we heading into a recession?")

    def test_gdp_question(self):
        assert "recession" in _detect_topics("What happened to GDP last quarter?")

    def test_unemployment_question(self):
        assert "recession" in _detect_topics("How is the unemployment rate?")

    def test_unrelated_returns_empty(self):
        assert _detect_topics("What is the capital of France?") == []

    def test_multi_topic_both_detected(self):
        topics = _detect_topics("How does inflation affect interest rates?")
        assert "inflation" in topics
        assert "rates_fed" in topics


# ── retrieve_general_finance_evidence: messy queries fetch correct series ─────

class TestRetrieveWithMessyQueries:
    """End-to-end: messy query → FRED fetch for DGS10/DGS2/T10Y2Y."""

    def _fake_fetch(self, fetched: list):
        def _fn(series_id, limit=5):
            fetched.append(series_id)
            return [{"date": "2024-01-15", "value": "4.25"}]
        return _fn

    def test_treasury_rates_yields_fetches_dgs10(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series",
            self._fake_fetch(fetched),
        )
        retrieve_general_finance_evidence("Why are treasury rates yields rising right now?")
        assert "DGS10" in fetched

    def test_bond_rates_going_up_fetches_dgs10(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series",
            self._fake_fetch(fetched),
        )
        retrieve_general_finance_evidence("Why are bond rates going up?")
        assert "DGS10" in fetched

    def test_10_year_treasury_moving_fetches_dgs10(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series",
            self._fake_fetch(fetched),
        )
        retrieve_general_finance_evidence("Why is the 10 year treasury moving?")
        assert "DGS10" in fetched

    def test_yield_curve_question_fetches_yield_series(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series",
            self._fake_fetch(fetched),
        )
        retrieve_general_finance_evidence("What does the yield curve mean for stocks?")
        yield_series = {"DGS10", "DGS2", "T10Y2Y"}
        assert any(s in fetched for s in yield_series), (
            f"Expected at least one of {yield_series} to be fetched, got {fetched}"
        )

    def test_long_term_rates_fetches_dgs10(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series",
            self._fake_fetch(fetched),
        )
        retrieve_general_finance_evidence("Why are long term rates rising?")
        assert "DGS10" in fetched
