"""
Tests for app.services.providers.news_provider.

All HTTP calls are intercepted at _fetch_json.  NEWS_API_KEY is injected via
monkeypatch.
"""

from __future__ import annotations

import pytest

from app.services.providers import news_provider
from app.schemas import RetrievedEvidence


# ── helpers ───────────────────────────────────────────────────────────────────

def _patch_key(monkeypatch):
    monkeypatch.setenv("NEWS_API_KEY", "test-news-key")


def _patch_fetch(monkeypatch, return_value):
    monkeypatch.setattr(
        "app.services.providers.news_provider._fetch_json",
        lambda url, timeout=8: return_value,
    )


def _ok_response(articles: list) -> dict:
    return {"status": "ok", "totalResults": len(articles), "articles": articles}


def _article(title: str, description: str = "", pub: str = "2024-01-15T12:00:00Z",
             source_name: str = "Reuters") -> dict:
    return {
        "title":       title,
        "description": description,
        "url":         f"https://example.com/{title[:20].replace(' ', '-')}",
        "publishedAt": pub,
        "source":      {"name": source_name},
    }


# ── Missing API key ───────────────────────────────────────────────────────────

class TestMissingApiKey:

    def test_company_news_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("NEWS_API_KEY", raising=False)
        assert news_provider.fetch_company_news("Apple") == []

    def test_macro_news_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("NEWS_API_KEY", raising=False)
        assert news_provider.fetch_macro_news(["yields"]) == []


# ── _build_macro_query ────────────────────────────────────────────────────────

class TestBuildMacroQuery:

    def test_known_topic_yields_non_empty_query(self):
        q = news_provider._build_macro_query(["yields"])
        assert q and len(q) > 5

    def test_multiple_topics_combined(self):
        q = news_provider._build_macro_query(["yields", "inflation"])
        assert "Treasury" in q or "inflation" in q.lower()

    def test_unknown_topic_falls_back_to_general(self):
        q = news_provider._build_macro_query(["no_such_topic"])
        assert q == news_provider._GENERAL_MARKET_QUERY

    def test_empty_topics_falls_back_to_general(self):
        q = news_provider._build_macro_query([])
        assert q == news_provider._GENERAL_MARKET_QUERY

    def test_rates_fed_topic(self):
        q = news_provider._build_macro_query(["rates_fed"])
        assert "Federal Reserve" in q or "FOMC" in q or "interest rate" in q.lower()

    def test_inflation_topic(self):
        q = news_provider._build_macro_query(["inflation"])
        assert "inflation" in q.lower() or "CPI" in q

    def test_recession_topic(self):
        q = news_provider._build_macro_query(["recession"])
        assert "recession" in q.lower() or "GDP" in q

    def test_market_conditions_topic(self):
        q = news_provider._build_macro_query(["market_conditions"])
        assert "VIX" in q or "credit spread" in q.lower() or "volatility" in q.lower()


# ── fetch_company_news ────────────────────────────────────────────────────────

class TestFetchCompanyNews:

    def test_returns_evidence_objects(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([
            _article("Apple earnings beat estimates"),
            _article("Apple stock hits record high"),
        ]))
        result = news_provider.fetch_company_news("Apple")
        assert all(isinstance(ev, RetrievedEvidence) for ev in result)

    def test_title_from_article(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([_article("Apple Q4 revenue $119B")]))
        result = news_provider.fetch_company_news("Apple")
        assert "Apple Q4 revenue $119B" in result[0].title

    def test_source_contains_newsapi(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([_article("Apple news", source_name="Bloomberg")]))
        result = news_provider.fetch_company_news("Apple")
        assert "NewsAPI" in result[0].source or "Bloomberg" in result[0].source

    def test_timestamp_is_date_only(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([_article("Apple", pub="2024-07-15T08:30:00Z")]))
        result = news_provider.fetch_company_news("Apple")
        assert result[0].timestamp == "2024-07-15"

    def test_summary_includes_description(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([
            _article("Apple news", description="Detailed description here")
        ]))
        result = news_provider.fetch_company_news("Apple")
        assert "Detailed description here" in result[0].summary

    def test_page_size_respected(self, monkeypatch):
        _patch_key(monkeypatch)
        articles = [_article(f"Article {i}") for i in range(10)]
        _patch_fetch(monkeypatch, _ok_response(articles))
        result = news_provider.fetch_company_news("Apple", page_size=3)
        assert len(result) <= 3

    def test_empty_company_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        assert news_provider.fetch_company_news("") == []

    def test_whitespace_company_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        assert news_provider.fetch_company_news("   ") == []

    def test_removed_articles_filtered_out(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([
            {"title": "[Removed]", "description": "", "url": "", "publishedAt": "",
             "source": {"name": "x"}},
            _article("Real article"),
        ]))
        result = news_provider.fetch_company_news("Apple")
        assert all("[Removed]" not in ev.title for ev in result)

    def test_relevance_scores_descending(self, monkeypatch):
        _patch_key(monkeypatch)
        articles = [_article(f"Article {i}") for i in range(3)]
        _patch_fetch(monkeypatch, _ok_response(articles))
        result = news_provider.fetch_company_news("Apple", page_size=3)
        scores = [ev.relevance_score for ev in result]
        assert scores == sorted(scores, reverse=True)

    def test_no_api_key_no_network_call(self, monkeypatch):
        monkeypatch.delenv("NEWS_API_KEY", raising=False)
        called = []
        monkeypatch.setattr(
            "app.services.providers.news_provider._fetch_json",
            lambda *a, **kw: called.append(1) or {},
        )
        news_provider.fetch_company_news("Apple")
        assert called == []  # no HTTP call made


# ── fetch_macro_news ──────────────────────────────────────────────────────────

class TestFetchMacroNews:

    def test_returns_evidence_objects(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([
            _article("Fed holds rates steady"),
            _article("CPI beats estimates"),
        ]))
        result = news_provider.fetch_macro_news(["rates_fed", "inflation"])
        assert all(isinstance(ev, RetrievedEvidence) for ev in result)

    def test_empty_topics_still_returns_general_news(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([_article("Market update")]))
        result = news_provider.fetch_macro_news([])
        assert isinstance(result, list)

    def test_relevance_lower_than_company_news(self, monkeypatch):
        """Macro news has a lower baseline relevance than company news."""
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, _ok_response([_article("Fed news")]))
        macro  = news_provider.fetch_macro_news(["rates_fed"])
        co_key = monkeypatch.setenv("NEWS_API_KEY", "test-news-key")
        _patch_fetch(monkeypatch, _ok_response([_article("Company news")]))
        company = news_provider.fetch_company_news("Apple")
        if macro and company:
            assert macro[0].relevance_score <= company[0].relevance_score


# ── Graceful failure ──────────────────────────────────────────────────────────

class TestGracefulFailure:

    def test_http_error_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        from urllib.error import HTTPError
        monkeypatch.setattr(
            "app.services.providers.news_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(
                HTTPError(None, 426, "Too Many Requests", {}, None)
            ),
        )
        assert news_provider.fetch_company_news("Apple") == []

    def test_url_error_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        from urllib.error import URLError
        monkeypatch.setattr(
            "app.services.providers.news_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(URLError("connection refused")),
        )
        assert news_provider.fetch_macro_news(["yields"]) == []

    def test_non_ok_status_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, {
            "status": "error", "code": "apiKeyExhausted",
            "message": "You have made too many requests today."
        })
        assert news_provider.fetch_company_news("Apple") == []

    def test_malformed_response_returns_empty(self, monkeypatch):
        _patch_key(monkeypatch)
        _patch_fetch(monkeypatch, "not a dict")
        # Should not raise — returns empty gracefully
        assert news_provider.fetch_company_news("Apple") == []
