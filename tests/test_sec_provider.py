"""
Tests for app.services.providers.sec_provider.

All HTTP calls are intercepted at _fetch_json so no real EDGAR requests are made.
SEC EDGAR needs no API key, but requests need the User-Agent header.
"""

from __future__ import annotations

import pytest

from app.services.providers import sec_provider
from app.schemas import RetrievedEvidence


# ── helpers ───────────────────────────────────────────────────────────────────

def _patch_fetch(monkeypatch, return_value):
    monkeypatch.setattr(
        "app.services.providers.sec_provider._fetch_json",
        lambda url, timeout=10: return_value,
    )


def _make_edgar_response(hits: list) -> dict:
    """Build a minimal EDGAR EFTS search response."""
    return {
        "hits": {
            "total": {"value": len(hits)},
            "hits":  hits,
        }
    }


def _make_hit(entity: str, form: str, file_date: str, period: str) -> dict:
    return {
        "_source": {
            "entity_name":      entity,
            "form_type":        form,
            "file_date":        file_date,
            "period_of_report": period,
        }
    }


# ── Guard: empty / missing company ───────────────────────────────────────────

class TestGuardEmptyCompany:

    def test_empty_string_returns_empty(self, monkeypatch):
        assert sec_provider.fetch_recent_filings("") == []

    def test_whitespace_string_returns_empty(self, monkeypatch):
        assert sec_provider.fetch_recent_filings("   ") == []


# ── Happy path ────────────────────────────────────────────────────────────────

class TestHappyPath:

    def _apple_response(self):
        return _make_edgar_response([
            _make_hit("Apple Inc.", "10-K", "2024-11-01", "2024-09-28"),
            _make_hit("Apple Inc.", "10-Q", "2024-08-02", "2024-06-29"),
            _make_hit("Apple Inc.", "10-Q", "2024-05-03", "2024-03-30"),
        ])

    def test_returns_retrieved_evidence_instances(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        assert all(isinstance(ev, RetrievedEvidence) for ev in result)

    def test_10k_has_highest_relevance(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        annual = [ev for ev in result if "10-K" in ev.title or "Annual" in ev.title]
        quarterly = [ev for ev in result if "10-Q" in ev.title or "Quarterly" in ev.title]
        if annual and quarterly:
            assert annual[0].relevance_score > quarterly[0].relevance_score

    def test_title_contains_form_type_label(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        titles = [ev.title for ev in result]
        assert any("Annual Report" in t or "10-K" in t for t in titles)
        assert any("Quarterly Report" in t or "10-Q" in t for t in titles)

    def test_title_contains_file_date(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        assert any("2024-11-01" in ev.title for ev in result)

    def test_timestamp_set_to_file_date(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        assert result[0].timestamp == "2024-11-01"

    def test_source_is_sec_edgar(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        assert all("SEC EDGAR" in ev.source for ev in result)

    def test_summary_mentions_annual_report_content(self, monkeypatch):
        _patch_fetch(monkeypatch, self._apple_response())
        result = sec_provider.fetch_recent_filings("Apple Inc.")
        annual = [ev for ev in result if "Annual" in ev.title or "10-K" in ev.title]
        if annual:
            assert "risk factors" in annual[0].summary.lower() or "10-K" in annual[0].summary


# ── Limit and deduplication ───────────────────────────────────────────────────

class TestLimitAndDeduplication:

    def test_respects_limit_parameter(self, monkeypatch):
        hits = [
            _make_hit("Co", "10-Q", f"2024-0{i+1}-01", f"2024-0{i+1}-01")
            for i in range(10)
        ]
        _patch_fetch(monkeypatch, _make_edgar_response(hits))
        result = sec_provider.fetch_recent_filings("Co", limit=3)
        assert len(result) <= 3

    def test_duplicates_skipped(self, monkeypatch):
        """Same company + form + period appears twice — only one should survive."""
        hits = [
            _make_hit("Co", "10-K", "2024-11-01", "2024-09-28"),
            _make_hit("Co", "10-K", "2024-11-01", "2024-09-28"),  # exact duplicate
        ]
        _patch_fetch(monkeypatch, _make_edgar_response(hits))
        result = sec_provider.fetch_recent_filings("Co", limit=5)
        assert len(result) == 1

    def test_no_hits_returns_empty_list(self, monkeypatch):
        _patch_fetch(monkeypatch, _make_edgar_response([]))
        assert sec_provider.fetch_recent_filings("Unknown Corp") == []


# ── Form filtering ────────────────────────────────────────────────────────────

class TestFormFiltering:

    def test_custom_forms_accepted(self, monkeypatch):
        """Passing forms=["8-K"] should not crash."""
        _patch_fetch(monkeypatch, _make_edgar_response([
            _make_hit("Co", "8-K", "2024-10-15", "2024-10-15")
        ]))
        result = sec_provider.fetch_recent_filings("Co", forms=["8-K"])
        assert len(result) == 1
        assert "8-K" in result[0].title or "Current Report" in result[0].title


# ── Graceful failure ──────────────────────────────────────────────────────────

class TestGracefulFailure:

    def test_http_error_returns_empty(self, monkeypatch):
        from urllib.error import HTTPError
        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(
                HTTPError(None, 503, "Service Unavailable", {}, None)
            ),
        )
        assert sec_provider.fetch_recent_filings("Apple Inc.") == []

    def test_url_error_returns_empty(self, monkeypatch):
        from urllib.error import URLError
        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(URLError("timeout")),
        )
        assert sec_provider.fetch_recent_filings("Apple Inc.") == []

    def test_malformed_json_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            lambda *a, **kw: (_ for _ in ()).throw(ValueError("not JSON")),
        )
        assert sec_provider.fetch_recent_filings("Apple Inc.") == []

    def test_missing_hits_key_returns_empty(self, monkeypatch):
        _patch_fetch(monkeypatch, {"status": "ok"})   # no "hits" key
        assert sec_provider.fetch_recent_filings("Apple Inc.") == []


# ── _form_label helper ────────────────────────────────────────────────────────

class TestFormLabel:

    def test_10k_label(self):
        assert "Annual" in sec_provider._form_label("10-K")

    def test_10q_label(self):
        assert "Quarterly" in sec_provider._form_label("10-Q")

    def test_8k_label(self):
        assert "Current" in sec_provider._form_label("8-K") or "8-K" in sec_provider._form_label("8-K")

    def test_unknown_form_passthrough(self):
        assert sec_provider._form_label("NT 10-K") == "NT 10-K"
