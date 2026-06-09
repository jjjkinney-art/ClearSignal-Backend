"""
Tests for app.db.concern_extractor — pure Python, no DB required.
"""

from __future__ import annotations

import pytest
from app.db.concern_extractor import extract_concerns, dominant_concern


class TestExtractConcerns:
    """extract_concerns() — keyword matching against taxonomy."""

    def test_empty_inputs_return_empty_set(self):
        result = extract_concerns()
        assert isinstance(result, set)
        assert len(result) == 0

    def test_cre_credit_risk_from_question(self):
        tags = extract_concerns(question="What is JPM's CRE loan loss threshold?")
        assert "cre_credit_risk" in tags

    def test_cre_credit_risk_from_bear_thesis(self):
        tags = extract_concerns(bear_thesis="Office delinquency rates are rising rapidly.")
        assert "cre_credit_risk" in tags

    def test_geopolitical_risk_taiwan(self):
        tags = extract_concerns(question="How does a Taiwan Strait escalation transmit to TSMC revenue?")
        assert "geopolitical_risk" in tags

    def test_geopolitical_risk_tariff(self):
        tags = extract_concerns(question="What is the tariff impact on TSMC's margins?")
        assert "geopolitical_risk" in tags

    def test_capex_cycle(self):
        tags = extract_concerns(
            question="If hyperscalers reduce capex growth by 20 percentage points..."
        )
        assert "capex_cycle" in tags

    def test_margin_pressure(self):
        tags = extract_concerns(question="What is the primary driver of Costco's gross margin expansion?")
        assert "margin_pressure" in tags

    def test_interest_rate_risk(self):
        tags = extract_concerns(bear_thesis="Rising Fed rate hikes will compress net interest margin.")
        assert "interest_rate_risk" in tags

    def test_valuation_risk(self):
        tags = extract_concerns(question="At what premium valuation should investors reconsider the multiple?")
        assert "valuation_risk" in tags

    def test_att_privacy_risk(self):
        tags = extract_concerns(
            question="Has Meta fully recovered its advertising revenue run rate to pre-ATT levels?"
        )
        assert "att_privacy_risk" in tags

    def test_ai_adoption_risk(self):
        tags = extract_concerns(
            question="What percentage of Google's search revenue is at risk of AI substitution?"
        )
        assert "ai_adoption_risk" in tags

    def test_multiple_tags_same_call(self):
        tags = extract_concerns(
            question="What are the CRE loan loss risks?",
            bear_thesis="Rising interest rate environment compresses NIM and capex cycle slows."
        )
        assert "cre_credit_risk" in tags
        assert "interest_rate_risk" in tags
        assert "capex_cycle" in tags

    def test_concentration_risk(self):
        tags = extract_concerns(
            bear_thesis="Four customers accounted for 61% of NVIDIA revenue — customer concentration risk."
        )
        assert "concentration_risk" in tags

    def test_case_insensitive(self):
        tags = extract_concerns(question="COMMERCIAL REAL ESTATE LOAN LOSSES AT JPM")
        assert "cre_credit_risk" in tags

    def test_no_false_positive_on_unrelated_text(self):
        tags = extract_concerns(
            question="What is the membership renewal rate at Costco?",
            bull_thesis="Membership fees grow 5% annually with 90% renewal rates.",
        )
        # Should not fire geopolitical, CRE, or ATT tags
        assert "geopolitical_risk" not in tags
        assert "cre_credit_risk" not in tags
        assert "att_privacy_risk" not in tags

    def test_returns_set_not_list(self):
        result = extract_concerns(question="CRE loan losses")
        assert isinstance(result, set)


class TestDominantConcern:
    """dominant_concern() — max-by-count from tag dict."""

    def test_empty_dict_returns_empty_string(self):
        assert dominant_concern({}) == ""

    def test_single_tag(self):
        assert dominant_concern({"cre_credit_risk": 5}) == "cre_credit_risk"

    def test_max_wins(self):
        counts = {
            "cre_credit_risk": 3,
            "geopolitical_risk": 8,
            "margin_pressure": 2,
        }
        assert dominant_concern(counts) == "geopolitical_risk"

    def test_tie_returns_one_of_the_tied(self):
        counts = {"tag_a": 5, "tag_b": 5}
        result = dominant_concern(counts)
        assert result in {"tag_a", "tag_b"}

    def test_single_mention(self):
        assert dominant_concern({"capex_cycle": 1}) == "capex_cycle"
