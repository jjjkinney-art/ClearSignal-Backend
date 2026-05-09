"""
Tests for app.services.providers.retrieve_market_evidence — the provider router.

Validates routing decisions, evidence merging, deduplication, caps, and
graceful degradation when providers return empty or fail.

All individual provider functions are mocked so no network calls are made.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.services.providers import retrieve_market_evidence
from app.services.providers import fmp_provider, sec_provider, news_provider
from app.schemas import RetrievedEvidence


# ── helpers ───────────────────────────────────────────────────────────────────

def _ev(title: str, score: float = 0.90) -> RetrievedEvidence:
    return RetrievedEvidence(
        title=title, source="mock", summary="mock summary",
        timestamp="2024-01-01", relevance_score=score,
    )


class _Providers:
    """Context manager that patches all three provider entry-points."""

    def __init__(
        self,
        monkeypatch,
        fmp=None,
        sec=None,
        co_news=None,
        macro_news=None,
    ):
        self.mp       = monkeypatch
        self.fmp      = fmp      or []
        self.sec      = sec      or []
        self.co_news  = co_news  or []
        self.macro_news = macro_news or []
        self.calls    = []

    def __enter__(self):
        def _fmp(co):
            self.calls.append("fmp")
            return self.fmp

        def _sec(co, **kw):
            self.calls.append("sec")
            return self.sec

        def _co_news(co, **kw):
            self.calls.append("co_news")
            return self.co_news

        def _macro_news(topics, **kw):
            self.calls.append("macro_news")
            return self.macro_news

        self.mp.setattr("app.services.providers.fmp_provider.fetch_company_evidence", _fmp)
        self.mp.setattr("app.services.providers.sec_provider.fetch_recent_filings",   _sec)
        self.mp.setattr("app.services.providers.news_provider.fetch_company_news",    _co_news)
        self.mp.setattr("app.services.providers.news_provider.fetch_macro_news",      _macro_news)
        return self

    def __exit__(self, *_):
        pass


# ── Routing: company question ─────────────────────────────────────────────────

class TestCompanyRouting:

    def test_company_triggers_fmp(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("What is Apple's revenue?", [], company="Apple")
        assert "fmp" in p.calls

    def test_company_triggers_sec(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("Show Apple filings.", [], company="Apple")
        assert "sec" in p.calls

    def test_company_triggers_company_news(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("Latest Apple news.", [], company="Apple")
        assert "co_news" in p.calls

    def test_company_no_macro_topics_skips_macro_news(self, monkeypatch):
        """Pure company question with no FRED topics → macro news not called."""
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("What is Apple's PE ratio?", [], company="Apple")
        assert "macro_news" not in p.calls

    def test_company_with_macro_topics_calls_macro_news_too(self, monkeypatch):
        """Company + macro topics (e.g. 'How does inflation affect Apple?') →
        both company and macro news are fetched."""
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence(
                "How does inflation affect Apple?",
                detected_topics=["inflation"],
                company="Apple",
            )
        assert "co_news" in p.calls
        assert "macro_news" in p.calls


# ── Routing: macro-only question ──────────────────────────────────────────────

class TestMacroRouting:

    def test_no_company_skips_fmp(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("Why are yields rising?", ["yields"])
        assert "fmp" not in p.calls

    def test_no_company_skips_sec(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("Why are yields rising?", ["yields"])
        assert "sec" not in p.calls

    def test_no_company_calls_macro_news(self, monkeypatch):
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("Why are yields rising?", ["yields"])
        assert "macro_news" in p.calls

    def test_no_company_no_topics_still_calls_macro_news(self, monkeypatch):
        """Even with no topics the macro fallback query should run."""
        with _Providers(monkeypatch) as p:
            retrieve_market_evidence("What is happening in markets?", [])
        assert "macro_news" in p.calls


# ── Evidence merging ──────────────────────────────────────────────────────────

class TestEvidenceMerging:

    def test_results_from_all_providers_are_combined(self, monkeypatch):
        fmp_ev   = [_ev("FMP profile",   0.92)]
        sec_ev   = [_ev("SEC 10-K",      0.90)]
        co_news  = [_ev("Apple news",    0.88)]
        macro_ev = [_ev("Fed rates",     0.82)]
        with _Providers(monkeypatch,
                        fmp=fmp_ev, sec=sec_ev, co_news=co_news, macro_news=macro_ev):
            result = retrieve_market_evidence(
                "Inflation impact on Apple?", ["inflation"], company="Apple"
            )
        titles = {ev.title for ev in result}
        assert "FMP profile"  in titles
        assert "SEC 10-K"     in titles
        assert "Apple news"   in titles
        assert "Fed rates"    in titles

    def test_sorted_by_relevance_descending(self, monkeypatch):
        items = [_ev(f"item_{i}", 0.90 - i * 0.05) for i in range(4)]
        # Shuffle before providing
        shuffled = [items[2], items[0], items[3], items[1]]
        with _Providers(monkeypatch, fmp=shuffled):
            result = retrieve_market_evidence("?", [], company="Apple")
        scores = [ev.relevance_score for ev in result]
        assert scores == sorted(scores, reverse=True)

    def test_duplicate_titles_deduplicated(self, monkeypatch):
        """Same title from two providers should appear only once."""
        shared = _ev("Apple Inc. Profile", 0.90)
        with _Providers(monkeypatch, fmp=[shared], sec=[shared]):
            result = retrieve_market_evidence("?", [], company="Apple")
        apple_profile_count = sum(
            1 for ev in result if ev.title == "Apple Inc. Profile"
        )
        assert apple_profile_count == 1

    def test_macro_only_result_non_empty_when_news_available(self, monkeypatch):
        macro_items = [_ev("Fed holds", 0.82), _ev("CPI beat", 0.80)]
        with _Providers(monkeypatch, macro_news=macro_items):
            result = retrieve_market_evidence("Why is inflation high?", ["inflation"])
        assert len(result) > 0


# ── Caps ──────────────────────────────────────────────────────────────────────

class TestCaps:

    def test_company_result_capped_at_8(self, monkeypatch):
        many = [_ev(f"item {i}", 0.90 - i * 0.01) for i in range(20)]
        with _Providers(monkeypatch, fmp=many, sec=many, co_news=many):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) <= 8

    def test_macro_result_capped_at_4(self, monkeypatch):
        many = [_ev(f"macro {i}", 0.82 - i * 0.01) for i in range(20)]
        with _Providers(monkeypatch, macro_news=many):
            result = retrieve_market_evidence("Why are yields rising?", ["yields"])
        assert len(result) <= 4


# ── Graceful degradation ──────────────────────────────────────────────────────

class TestGracefulDegradation:

    def test_all_providers_empty_returns_empty_list(self, monkeypatch):
        with _Providers(monkeypatch):   # all return []
            result = retrieve_market_evidence("?", [], company="Apple")
        assert result == []

    def test_fmp_fails_others_still_contribute(self, monkeypatch):
        sec_ev  = [_ev("Apple 10-K", 0.90)]
        co_news = [_ev("Apple news", 0.88)]
        with _Providers(monkeypatch, fmp=[], sec=sec_ev, co_news=co_news):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) == 2

    def test_sec_fails_others_still_contribute(self, monkeypatch):
        fmp_ev  = [_ev("Apple profile", 0.92)]
        co_news = [_ev("Apple news", 0.88)]
        with _Providers(monkeypatch, fmp=fmp_ev, sec=[], co_news=co_news):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) == 2

    def test_news_fails_others_still_contribute(self, monkeypatch):
        fmp_ev = [_ev("Apple profile", 0.92)]
        sec_ev = [_ev("Apple 10-K", 0.90)]
        with _Providers(monkeypatch, fmp=fmp_ev, sec=sec_ev, co_news=[]):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) == 2

    def test_macro_news_fails_for_macro_question_returns_empty(self, monkeypatch):
        with _Providers(monkeypatch, macro_news=[]):
            result = retrieve_market_evidence("Why are yields rising?", ["yields"])
        assert result == []   # no other providers called for macro-only

    def test_returns_list_not_none_on_total_failure(self, monkeypatch):
        with _Providers(monkeypatch):
            result = retrieve_market_evidence("?", ["inflation"])
        assert isinstance(result, list)


# ── Evidence count propagation (schema-level) ─────────────────────────────────

class TestEvidenceCountIntegrity:
    """retrieve_market_evidence returns List[RetrievedEvidence]; callers (agents)
    are responsible for stamping evidence_count on GeneralFinanceAnswer.
    Verify that the returned list length is correct so callers can count it."""

    def test_evidence_count_matches_list_length(self, monkeypatch):
        items = [_ev(f"item {i}") for i in range(3)]
        with _Providers(monkeypatch, fmp=items):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) == 3

    def test_zero_evidence_when_all_fail(self, monkeypatch):
        with _Providers(monkeypatch):
            result = retrieve_market_evidence("?", [], company="Apple")
        assert len(result) == 0


# ── Mixed macro + company query end-to-end ────────────────────────────────────

class TestMixedQuery:

    def test_mixed_query_calls_all_four_providers(self, monkeypatch):
        """'How does the Fed rate cycle affect Apple's valuation?' has both
        a company (Apple) and macro topics (rates_fed)."""
        with _Providers(
            monkeypatch,
            fmp=[_ev("Apple profile")],
            sec=[_ev("Apple 10-K")],
            co_news=[_ev("Apple news")],
            macro_news=[_ev("Fed holds")],
        ) as p:
            retrieve_market_evidence(
                "How does the Fed rate cycle affect Apple's valuation?",
                detected_topics=["rates_fed"],
                company="Apple Inc.",
            )
        assert "fmp"        in p.calls
        assert "sec"        in p.calls
        assert "co_news"    in p.calls
        assert "macro_news" in p.calls

    def test_mixed_query_evidence_all_present_in_result(self, monkeypatch):
        with _Providers(
            monkeypatch,
            fmp=[_ev("FMP")],
            sec=[_ev("SEC")],
            co_news=[_ev("CoNews")],
            macro_news=[_ev("Macro")],
        ):
            result = retrieve_market_evidence(
                "Inflation impact on Apple?",
                detected_topics=["inflation"],
                company="Apple",
            )
        titles = {ev.title for ev in result}
        assert titles == {"FMP", "SEC", "CoNews", "Macro"}
