"""
Tests for the expanded general-finance evidence topic system.

Covers:
  - _SERIES_META: every new series has a human-readable title and description
  - _TOPIC_SERIES: each topic maps to the correct FRED series IDs
  - _TOPIC_KEYWORDS / _detect_topics: new phrases trigger the correct topics
  - _NORMALIZATIONS: colloquial Fed-action and inversion phrases are canonicalised
  - Co-occurrence rules: treasury-inversion rule pulls both yields + recession
  - No regression: existing yield topic detection still works

All tests are pure-logic (no network calls, no FRED_API_KEY required).
"""

from __future__ import annotations

import pytest

from app.services.general_finance_evidence import (
    _SERIES_META,
    _TOPIC_SERIES,
    _TOPIC_KEYWORDS,
    _NORMALIZATIONS,
    _detect_topics,
    normalize_macro_query,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _series_for_topic(topic: str):
    """Return just the series-ID list for a topic (strip relevance scores)."""
    return [sid for sid, _ in _TOPIC_SERIES.get(topic, [])]


def _topics(question: str):
    return _detect_topics(question)


# ─────────────────────────────────────────────────────────────────────────────
# _SERIES_META — every series used in _TOPIC_SERIES must have metadata
# ─────────────────────────────────────────────────────────────────────────────

class TestSeriesMeta:
    """Every FRED series referenced in _TOPIC_SERIES must have a metadata
    entry with a non-empty human-readable title and description."""

    def _all_series(self):
        seen = []
        for entries in _TOPIC_SERIES.values():
            for sid, _ in entries:
                if sid not in seen:
                    seen.append(sid)
        return seen

    def test_all_topic_series_have_meta(self):
        missing = [sid for sid in self._all_series() if sid not in _SERIES_META]
        assert missing == [], f"Missing _SERIES_META entries: {missing}"

    def test_meta_titles_are_non_empty(self):
        for sid in self._all_series():
            title, _, _ = _SERIES_META[sid]
            assert title, f"{sid} has empty display title"

    def test_meta_descriptions_are_non_empty(self):
        for sid in self._all_series():
            _, _, desc = _SERIES_META[sid]
            assert desc, f"{sid} has empty description"

    # ── New series added in this expansion ───────────────────────────────────

    def test_pcepilfe_meta_present(self):
        assert "PCEPILFE" in _SERIES_META

    def test_pcepilfe_title_mentions_pce(self):
        title, _, _ = _SERIES_META["PCEPILFE"]
        assert "PCE" in title or "pce" in title.lower()

    def test_gdp_growth_rate_meta_present(self):
        assert "A191RL1Q225SBEA" in _SERIES_META

    def test_gdp_growth_rate_title_mentions_gdp(self):
        title, _, _ = _SERIES_META["A191RL1Q225SBEA"]
        assert "GDP" in title or "Gross Domestic" in title

    def test_vix_meta_present(self):
        assert "VIXCLS" in _SERIES_META

    def test_vix_title_mentions_volatility(self):
        title, _, _ = _SERIES_META["VIXCLS"]
        assert "Volatility" in title or "VIX" in title

    def test_hy_spread_meta_present(self):
        assert "BAMLH0A0HYM2" in _SERIES_META

    def test_hy_spread_title_mentions_high_yield(self):
        title, _, _ = _SERIES_META["BAMLH0A0HYM2"]
        assert "High Yield" in title or "high yield" in title.lower()

    def test_ig_spread_meta_present(self):
        assert "BAMLC0A0CM" in _SERIES_META

    def test_ig_spread_title_mentions_corporate(self):
        title, _, _ = _SERIES_META["BAMLC0A0CM"]
        assert "Corporate" in title or "corporate" in title.lower()


# ─────────────────────────────────────────────────────────────────────────────
# _TOPIC_SERIES — correct series per topic
# ─────────────────────────────────────────────────────────────────────────────

class TestTopicSeriesInflation:
    """Inflation topic must cover headline CPI, core CPI, and core PCE."""

    def test_cpiaucsl_in_inflation(self):
        assert "CPIAUCSL" in _series_for_topic("inflation")

    def test_cpilfesl_in_inflation(self):
        assert "CPILFESL" in _series_for_topic("inflation")

    def test_pcepilfe_in_inflation(self):
        assert "PCEPILFE" in _series_for_topic("inflation"), (
            "Core PCE (PCEPILFE) must be in inflation topic — it is the Fed's preferred gauge"
        )

    def test_inflation_has_3_or_more_series(self):
        assert len(_series_for_topic("inflation")) >= 3

    def test_cpiaucsl_highest_relevance(self):
        # Headline CPI should be the top-scored series
        top_sid, top_rel = _TOPIC_SERIES["inflation"][0]
        assert top_sid == "CPIAUCSL"
        assert top_rel >= 0.90


class TestTopicSeriesFedRates:
    """Fed/rates topic must include the effective rate, target bounds,
    and Treasury yields that track policy expectations."""

    def test_fedfunds_in_rates_fed(self):
        assert "FEDFUNDS" in _series_for_topic("rates_fed")

    def test_dfedtaru_in_rates_fed(self):
        assert "DFEDTARU" in _series_for_topic("rates_fed")

    def test_dfedtarl_in_rates_fed(self):
        assert "DFEDTARL" in _series_for_topic("rates_fed")

    def test_dgs2_in_rates_fed(self):
        assert "DGS2" in _series_for_topic("rates_fed"), (
            "2-year Treasury (DGS2) must be in rates_fed — tracks near-term policy expectations"
        )

    def test_dgs10_in_rates_fed(self):
        assert "DGS10" in _series_for_topic("rates_fed"), (
            "10-year Treasury (DGS10) must be in rates_fed — broader rate environment"
        )

    def test_fedfunds_highest_relevance(self):
        top_sid, top_rel = _TOPIC_SERIES["rates_fed"][0]
        assert top_sid == "FEDFUNDS"
        assert top_rel >= 0.90


class TestTopicSeriesRecession:
    """Recession topic must include the yield curve spread, unemployment,
    GDP growth rate, and industrial production."""

    def test_t10y2y_in_recession(self):
        assert "T10Y2Y" in _series_for_topic("recession"), (
            "Yield curve spread (T10Y2Y) must be in recession topic — leading indicator"
        )

    def test_unrate_in_recession(self):
        assert "UNRATE" in _series_for_topic("recession")

    def test_gdp_growth_rate_in_recession(self):
        assert "A191RL1Q225SBEA" in _series_for_topic("recession"), (
            "GDP growth rate (A191RL1Q225SBEA) must be in recession topic"
        )

    def test_indpro_in_recession(self):
        assert "INDPRO" in _series_for_topic("recession")

    def test_recession_has_3_or_more_series(self):
        assert len(_series_for_topic("recession")) >= 3

    def test_t10y2y_highest_relevance_in_recession(self):
        # Yield curve is the leading recession indicator — should be top-scored
        top_sid, top_rel = _TOPIC_SERIES["recession"][0]
        assert top_sid == "T10Y2Y"
        assert top_rel >= 0.88


class TestTopicSeriesMarketConditions:
    """market_conditions topic must include VIX and both credit spreads."""

    def test_vixcls_in_market_conditions(self):
        assert "VIXCLS" in _series_for_topic("market_conditions"), (
            "VIX (VIXCLS) must be in market_conditions topic"
        )

    def test_hy_spread_in_market_conditions(self):
        assert "BAMLH0A0HYM2" in _series_for_topic("market_conditions"), (
            "High-yield spread (BAMLH0A0HYM2) must be in market_conditions"
        )

    def test_ig_spread_in_market_conditions(self):
        assert "BAMLC0A0CM" in _series_for_topic("market_conditions"), (
            "IG corporate spread (BAMLC0A0CM) must be in market_conditions"
        )

    def test_vix_highest_relevance(self):
        top_sid, top_rel = _TOPIC_SERIES["market_conditions"][0]
        assert top_sid == "VIXCLS"
        assert top_rel >= 0.88

    def test_market_conditions_has_3_series(self):
        assert len(_series_for_topic("market_conditions")) == 3


class TestTopicSeriesYields:
    """Yield topic must be unchanged from original spec."""

    def test_dgs10_in_yields(self):
        assert "DGS10" in _series_for_topic("yields")

    def test_dgs2_in_yields(self):
        assert "DGS2" in _series_for_topic("yields")

    def test_t10y2y_in_yields(self):
        assert "T10Y2Y" in _series_for_topic("yields")

    def test_dgs10_highest_relevance(self):
        top_sid, _ = _TOPIC_SERIES["yields"][0]
        assert top_sid == "DGS10"


# ─────────────────────────────────────────────────────────────────────────────
# Relevance scores: ordering within each topic
# ─────────────────────────────────────────────────────────────────────────────

class TestRelevanceOrdering:
    """Within each topic the series must be listed highest relevance first."""

    def _check_descending(self, topic: str):
        scores = [rel for _, rel in _TOPIC_SERIES.get(topic, [])]
        assert scores == sorted(scores, reverse=True), (
            f"Topic '{topic}' relevance scores are not descending: {scores}"
        )

    def test_rates_fed_descending(self):
        self._check_descending("rates_fed")

    def test_yields_descending(self):
        self._check_descending("yields")

    def test_inflation_descending(self):
        self._check_descending("inflation")

    def test_recession_descending(self):
        self._check_descending("recession")

    def test_market_conditions_descending(self):
        self._check_descending("market_conditions")


# ─────────────────────────────────────────────────────────────────────────────
# _TOPIC_KEYWORDS / _detect_topics — new phrase coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestInflationPhraseDetection:

    def test_inflation_rising(self):
        assert "inflation" in _topics("Why is inflation rising right now?")

    def test_sticky_inflation(self):
        assert "inflation" in _topics("Sticky inflation is keeping the Fed on hold.")

    def test_price_pressures(self):
        assert "inflation" in _topics("Price pressures remain elevated in services.")

    def test_core_pce(self):
        assert "inflation" in _topics("What is core PCE doing?")

    def test_pce_inflation(self):
        assert "inflation" in _topics("PCE inflation came in hotter than expected.")

    def test_cpi_bare(self):
        assert "inflation" in _topics("CPI was above consensus this month.")

    def test_inflationary_pressures(self):
        assert "inflation" in _topics("Inflationary pressures are building in shelter costs.")


class TestFedRatesPhraseDetection:

    def test_fed_cuts(self):
        assert "rates_fed" in _topics("Will the Fed cuts rates this year?")

    def test_fed_hikes(self):
        assert "rates_fed" in _topics("The Fed hikes rates by 25 bps.")

    def test_fed_pivot(self):
        assert "rates_fed" in _topics("Is the Fed pivot coming soon?")

    def test_fed_pause(self):
        assert "rates_fed" in _topics("The Fed is expected to pause at the next meeting.")

    def test_rate_cuts_plural(self):
        assert "rates_fed" in _topics("How many rate cuts will there be in 2025?")

    def test_fed_cuts_rates_normalization(self):
        """'Fed cuts rates' should normalize and match rates_fed."""
        assert "rates_fed" in _topics("Why did the Fed cuts rates today?")

    def test_fed_hikes_rates_normalization(self):
        assert "rates_fed" in _topics("The Fed hikes rates for the tenth time.")

    def test_rate_reduction(self):
        assert "rates_fed" in _topics("Expecting a rate reduction in Q3.")


class TestRecessionPhraseDetection:

    def test_recession_risk(self):
        assert "recession" in _topics("What is the recession risk right now?")

    def test_growth_risk(self):
        assert "recession" in _topics("Growth risk is rising as PMI falls below 50.")

    def test_hard_landing(self):
        assert "recession" in _topics("Is the economy headed for a hard landing?")

    def test_soft_landing(self):
        assert "recession" in _topics("Can the Fed engineer a soft landing?")

    def test_economic_slowdown(self):
        assert "recession" in _topics("The economic slowdown is accelerating.")

    def test_inverted_yield_curve_phrase(self):
        assert "recession" in _topics("The inverted yield curve signals a downturn.")

    def test_yield_curve_inverted_phrase(self):
        assert "recession" in _topics("Why is the yield curve inverted?")

    def test_2s10s_spread(self):
        assert "recession" in _topics("The 2s10s spread is deeply negative.")


class TestMarketConditionsPhraseDetection:

    def test_vix_bare(self):
        assert "market_conditions" in _topics("The VIX is spiking today.")

    def test_market_volatility(self):
        assert "market_conditions" in _topics("Market volatility is elevated heading into earnings.")

    def test_credit_spread(self):
        assert "market_conditions" in _topics("Credit spread widening is a concern.")

    def test_credit_spreads(self):
        assert "market_conditions" in _topics("Credit spreads are blowing out.")

    def test_high_yield(self):
        assert "market_conditions" in _topics("High yield is selling off hard today.")

    def test_junk_bond(self):
        assert "market_conditions" in _topics("Junk bond spreads hit a 2-year wide.")

    def test_risk_off(self):
        assert "market_conditions" in _topics("Markets are in full risk-off mode.")

    def test_spreads_widening(self):
        assert "market_conditions" in _topics("Spreads widening signals credit stress.")

    def test_financial_conditions(self):
        assert "market_conditions" in _topics("Financial conditions have tightened significantly.")

    def test_flight_to_quality(self):
        assert "market_conditions" in _topics("Flight to quality is driving bond demand.")

    def test_volatility_spike(self):
        assert "market_conditions" in _topics("The volatility spike caught traders off guard.")


# ─────────────────────────────────────────────────────────────────────────────
# _NORMALIZATIONS — colloquial phrase canonicalisation
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizationRules:

    def _norm(self, q: str) -> str:
        return normalize_macro_query(q)

    # Fed-action colloquials
    def test_fed_cuts_rates_normalized(self):
        assert "rate cut" in self._norm("The Fed cuts rates by 50 bps.")

    def test_fed_hikes_rates_normalized(self):
        assert "rate hike" in self._norm("The Fed hikes rates to combat inflation.")

    def test_fed_is_cutting_normalized(self):
        assert "rate cut" in self._norm("The Fed is cutting borrowing costs.")

    def test_fed_is_hiking_normalized(self):
        assert "rate hike" in self._norm("The Fed is hiking to fight inflation.")

    def test_fed_cutting_rates_normalized(self):
        assert "rate cut" in self._norm("Why is the Fed cutting rates now?")

    def test_fed_hiking_rates_normalized(self):
        assert "rate hike" in self._norm("The Fed hiking rates was expected.")

    # Yield-curve inversion colloquials
    def test_inverted_yield_curve_normalized(self):
        assert "yield curve" in self._norm("The inverted yield curve signals recession.")

    def test_yield_curve_inverted_normalized(self):
        assert "yield curve" in self._norm("The yield curve inverted again this week.")

    def test_yield_curve_inversion_normalized(self):
        assert "yield curve" in self._norm("Yield curve inversion is flashing red.")

    def test_curve_is_inverted_normalized(self):
        assert "yield curve" in self._norm("The curve is inverted — is recession coming?")

    # Credit / volatility colloquials
    def test_spreads_are_widening_normalized(self):
        result = self._norm("Credit spreads are widening sharply.")
        assert "credit spread" in result or "widening" in result

    def test_spreads_blowing_out_normalized(self):
        result = self._norm("Spreads blowing out across all credit.")
        assert "credit spread" in result or "widening" in result


# ─────────────────────────────────────────────────────────────────────────────
# Co-occurrence rules
# ─────────────────────────────────────────────────────────────────────────────

class TestCoOccurrenceRules:

    def test_treasury_bond_pulls_yields(self):
        """Treasury + bond → yields topic even without an explicit yield keyword."""
        topics = _topics("How do Treasury bond prices move?")
        assert "yields" in topics

    def test_treasury_rate_pulls_yields(self):
        topics = _topics("What drives the Treasury rate higher?")
        assert "yields" in topics

    def test_inverted_yield_curve_pulls_both_yields_and_recession(self):
        """Inverted yield curve should detect both yields (for rate data)
        and recession (for context on what inversion historically signals)."""
        topics = _topics("Why is the yield curve inverted and does it predict recession?")
        assert "yields" in topics, "yields topic missing for inverted yield curve"
        assert "recession" in topics, "recession topic missing for inverted yield curve"

    def test_2s10s_pulls_recession(self):
        topics = _topics("The 2s10s is deeply negative — what does this mean?")
        assert "recession" in topics

    def test_yield_curve_alone_also_pulls_recession(self):
        """The inversion rule: any 'yield curve' mention should add recession."""
        topics = _topics("What is the yield curve telling us?")
        assert "recession" in topics


# ─────────────────────────────────────────────────────────────────────────────
# Regression: existing yield behaviour preserved
# ─────────────────────────────────────────────────────────────────────────────

class TestYieldRegressionNoPbreak:

    def test_why_are_treasury_yields_rising(self):
        assert "yields" in _topics("Why are Treasury yields rising?")

    def test_bond_yield_question(self):
        assert "yields" in _topics("What are bond yields doing today?")

    def test_yield_curve_question(self):
        assert "yields" in _topics("Why is the yield curve inverted?")

    def test_10yr_treasury_question(self):
        assert "yields" in _topics("What is the 10-year Treasury yield?")

    def test_2yr_treasury_question(self):
        assert "yields" in _topics("Where is the 2-year Treasury?")

    def test_bare_yields_not_broken(self):
        # bare "yields" alone doesn't match the keyword list (compound phrases
        # only), but the _detect_topics function still works without error
        result = _topics("Why are yields rising right now?")
        assert isinstance(result, list)  # must return a list, not raise


# ─────────────────────────────────────────────────────────────────────────────
# Deduplicated series across topics
# ─────────────────────────────────────────────────────────────────────────────

class TestDeduplcationAcrossTopics:
    """Series shared between topics (DGS2, DGS10, T10Y2Y) must only appear
    once per topic, and the topic lists themselves have no internal duplicates."""

    def test_no_internal_duplicates_in_any_topic(self):
        for topic, entries in _TOPIC_SERIES.items():
            ids = [sid for sid, _ in entries]
            assert len(ids) == len(set(ids)), (
                f"Topic '{topic}' has duplicate series IDs: {ids}"
            )

    def test_dgs2_in_both_rates_fed_and_yields(self):
        """DGS2 legitimately appears in both topics — that's intentional.
        Deduplication happens at retrieval time (seen-set in the loop)."""
        assert "DGS2" in _series_for_topic("rates_fed")
        assert "DGS2" in _series_for_topic("yields")

    def test_t10y2y_in_both_yields_and_recession(self):
        assert "T10Y2Y" in _series_for_topic("yields")
        assert "T10Y2Y" in _series_for_topic("recession")
