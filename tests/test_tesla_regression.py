"""
tests/test_tesla_regression.py

Regression suite for the "Tesla query returns Analysis incomplete" bug.

Root cause
----------
Two compounding failures caused the "Analysis incomplete. No agent outputs
or evidence available." message for the query
"Can Tesla recover margin pressure while demand weakens?":

1. SEC EDGAR ``fetch_recent_filings("TSLA")`` used ``q='"TSLA"'`` for a
   full-text body search, which either:
   - returns filings from *other* companies that mention "TSLA" in their text
     (e.g. a 2017 filing that cited Tesla as a competitor), or
   - returns zero results when date-filtered, leaving ``evidence = []``.

2. ``thesis_synthesizer.synthesize_thesis`` had an overly-strict early-bail
   guard::

       if all(c == 0.0 for c in agent_confidences) and not evidence:
           return _empty_thesis(company, "No agent outputs or evidence available.")

   When both evidence = [] AND all agent confidences = 0.0 (because agents
   also received empty evidence), the guard fired and skipped the LLM call
   entirely — even for well-known companies like Tesla where the LLM has
   strong training knowledge to synthesise a useful thesis.

Fix
---
* ``sec_provider.py``: CIK-based lookup (ticker → EDGAR company_tickers.json
  → submissions API) is now the primary strategy, with entity= EFTS and q=
  EFTS as progressive fallbacks.
* ``thesis_synthesizer.py``: guard now only fires for completely unknown
  companies (no ticker AND no name).  For known tickers, LLM synthesis is
  attempted even when evidence is sparse.

Run
---
    python3 -m pytest tests/test_tesla_regression.py -v
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.providers import sec_provider
from app.schemas import (
    CompanyContext,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    InvestmentThesis,
    RetrievedEvidence,
)


# ── Fixtures and helpers ──────────────────────────────────────────────────────

def _tsla():
    return CompanyContext(
        ticker="TSLA",
        company_name="Tesla, Inc.",
        sector="Consumer Cyclical",
        industry="Auto Manufacturers",
    )


def _empty_agents():
    """All five agents with confidence=0.0 (simulates missing API keys)."""
    return (
        ValuationView(),
        MacroSensitivity(),
        RiskProfile(),
        MarketContext(),
        QualityAssessment(),
    )


def _tsla_submissions_response() -> dict:
    """Minimal ``/submissions/CIK0001318605.json`` response."""
    return {
        "cik": "0001318605",
        "name": "Tesla, Inc.",
        "filings": {
            "recent": {
                "form":        ["10-Q", "10-Q", "10-K",  "10-Q"],
                "filingDate":  ["2025-04-25", "2025-01-27", "2024-01-29", "2024-10-23"],
                "reportDate":  ["2025-03-31", "2024-12-31", "2023-12-31", "2024-09-30"],
            }
        },
    }


def _cik_map_response() -> dict:
    """Minimal ``/files/company_tickers.json`` with just TSLA."""
    return {
        "0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."},
    }


def _make_thesis_json(ticker="TSLA", conclusion="Tesla faces margin pressure but has recovery potential."):
    return json.dumps({
        "ticker": ticker,
        "company_name": "Tesla, Inc.",
        "bull_thesis": "Margin recovery as cost cuts take hold.",
        "bear_thesis": "Demand weakness could persist.",
        "key_drivers": ["FSD revenue", "Energy storage", "Cost reduction", "Volume growth"],
        "key_risks": ["Price war", "BEV competition", "Macro slowdown", "Elon distraction"],
        "valuation_view": "Elevated relative to traditional auto.",
        "macro_sensitivity": "Sensitive to consumer spending and rates.",
        "confidence_score": 0.55,
        "confidence_reasoning": "Synthesised from model knowledge; no live evidence available.",
        "what_changes_the_thesis": ["Margin recovery", "Volume drop", "FSD breakthrough"],
        "conclusion": conclusion,
    })


# ── SEC EDGAR: CIK-based lookup for TSLA ─────────────────────────────────────

class TestSecProviderTslaLookup:
    """Regression: SEC provider must return Tesla's own filings for ticker 'TSLA'."""

    def _patch_both(self, monkeypatch, cik_data, submissions_data):
        """Patch _fetch_json to return different payloads for different URLs."""
        sec_provider._ticker_cik_cache = None  # reset module cache

        def _fake_fetch(url, timeout=10):
            if "company_tickers" in url:
                return cik_data
            if "submissions" in url:
                return submissions_data
            # EFTS fallback — should not be reached in the happy path
            return {"hits": {"hits": []}}

        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            _fake_fetch,
        )

    def test_tsla_cik_lookup_returns_tesla_filings(self, monkeypatch):
        """CIK path: ticker 'TSLA' → CIK 0001318605 → Tesla, Inc. filings."""
        self._patch_both(monkeypatch, _cik_map_response(), _tsla_submissions_response())

        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)

        assert len(result) >= 1, (
            "Expected at least one Tesla filing from CIK-based lookup; got none. "
            "This is the root-cause regression: q='\"TSLA\"' returned wrong/no results."
        )

    def test_tsla_filings_have_correct_entity_name(self, monkeypatch):
        """Filings must be attributed to 'Tesla, Inc.' not some other entity."""
        self._patch_both(monkeypatch, _cik_map_response(), _tsla_submissions_response())

        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)

        for ev in result:
            assert "Tesla" in ev.title, (
                f"Filing title '{ev.title}' does not contain 'Tesla'. "
                "Suggests a false-positive from a different company's filing."
            )

    def test_tsla_filings_include_10k_and_10q(self, monkeypatch):
        """Both annual and quarterly filings should be returned."""
        self._patch_both(monkeypatch, _cik_map_response(), _tsla_submissions_response())

        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)
        form_labels = " ".join(ev.title for ev in result)

        assert "10-K" in form_labels or "Annual" in form_labels, (
            "No 10-K found in TSLA filings. Annual report should be present."
        )
        assert "10-Q" in form_labels or "Quarterly" in form_labels, (
            "No 10-Q found in TSLA filings. Quarterly reports should be present."
        )

    def test_tsla_filings_source_is_sec_edgar(self, monkeypatch):
        self._patch_both(monkeypatch, _cik_map_response(), _tsla_submissions_response())
        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)
        assert all(ev.source == "SEC EDGAR" for ev in result)

    def test_tsla_cik_fallback_to_entity_search_when_cik_map_empty(self, monkeypatch):
        """If CIK map returns empty, fall back to entity= search."""
        sec_provider._ticker_cik_cache = None

        call_log: list = []

        def _fake_fetch(url, timeout=10):
            call_log.append(url)
            if "company_tickers" in url:
                return {}  # Empty map — no TSLA entry
            if "search-index" in url and "entity=" in url:
                # entity= EFTS search returns a real Tesla hit
                return {
                    "hits": {
                        "hits": [{
                            "_source": {
                                "entity_name": "Tesla, Inc.",
                                "form_type":   "10-K",
                                "file_date":   "2024-01-29",
                                "period_of_report": "2023-12-31",
                            }
                        }]
                    }
                }
            return {"hits": {"hits": []}}

        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            _fake_fetch,
        )

        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)
        assert len(result) >= 1
        assert "Tesla" in result[0].title

    def test_false_positive_filtering_in_fulltext_fallback(self, monkeypatch):
        """q= fallback must reject filings where entity name doesn't match query.

        Simulates the scenario where:
          - CIK map is empty (force skip CIK strategy)
          - entity= search returns no results (force skip entity strategy)
          - q= full-text search returns a filing from Rivian (false positive)

        The q= strategy's entity-name sanity check should filter out the Rivian
        hit because "RIVIAN" has no token overlap with the query "TSLA".
        """
        sec_provider._ticker_cik_cache = None

        rivian_hit = {
            "_source": {
                "entity_name": "Rivian Automotive Inc.",   # competitor, not TSLA
                "form_type":   "10-K",
                "file_date":   "2017-03-01",
                "period_of_report": "2016-12-31",
            }
        }

        def _fake_fetch(url, timeout=10):
            if "company_tickers" in url:
                return {}   # force CIK miss (empty map)
            if "search-index" in url and "entity=" in url:
                # entity= search returns nothing → force fallback to q=
                return {"hits": {"hits": []}}
            if "search-index" in url:
                # q= full-text search returns a hit from an unrelated company
                return {"hits": {"hits": [rivian_hit]}}
            return {"hits": {"hits": []}}

        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            _fake_fetch,
        )

        # "TSLA" has no token overlap with "Rivian Automotive Inc."
        result = sec_provider.fetch_recent_filings("TSLA", years_back=3)
        assert result == [], (
            "False-positive filing from Rivian should have been filtered out by "
            "the entity-name sanity check in _fetch_by_fulltext. "
            f"Got: {[ev.title for ev in result]}"
        )

    def test_years_back_cutoff_respected(self, monkeypatch):
        """Filings older than years_back should not appear in results."""
        import datetime as _dt
        sec_provider._ticker_cik_cache = None

        # Provide a CIK map with TSLA, and a submissions response with a very old filing
        old_date  = (_dt.date.today() - _dt.timedelta(days=365 * 5)).isoformat()  # 5 years ago
        old_submissions = {
            "name": "Tesla, Inc.",
            "filings": {
                "recent": {
                    "form":       ["10-K"],
                    "filingDate": [old_date],
                    "reportDate": [old_date],
                }
            },
        }

        def _fake_fetch(url, timeout=10):
            if "company_tickers" in url:
                return {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}
            if "submissions" in url:
                return old_submissions
            return {"hits": {"hits": []}}

        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json",
            _fake_fetch,
        )
        monkeypatch.setattr(
            "app.services.providers.sec_provider._ticker_cik_cache", None
        )
        sec_provider._ticker_cik_cache = None

        result = sec_provider.fetch_recent_filings("TSLA", years_back=2)
        assert result == [], (
            f"Filing from {old_date} should be excluded when years_back=2."
        )


# ── Synthesizer guard: known tickers bypass the early-bail ───────────────────

class TestSynthesizerGuardRelaxedForKnownTicker:
    """Regression: synthesizer must attempt LLM synthesis for known tickers
    even when all agent confidences are 0.0 and evidence is empty."""

    def test_tsla_empty_agents_no_evidence_attempts_llm_not_immediate_bail(self):
        """Guard must NOT trigger for TSLA when evidence is empty.

        Before the fix: ``synthesize_thesis`` returned an empty thesis with
        ``conclusion='Analysis incomplete. No agent outputs or evidence available.'``
        immediately, without ever calling the LLM.

        After the fix: the LLM is called (even with empty evidence); only if
        the LLM itself fails does the synthesiser fall back to an empty thesis.
        """
        from app.services.thesis_synthesizer import synthesize_thesis

        company = _tsla()
        val, mac, risk, market, quality = _empty_agents()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _make_thesis_json()
            result = synthesize_thesis(company, val, mac, risk, market, quality, [])

        # LLM was called — the guard did not short-circuit
        mock_client.call.assert_called(), (
            "model_client.call was never invoked. "
            "The old guard is still firing for TSLA + empty evidence."
        )

        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "TSLA"
        assert "Analysis incomplete" not in result.conclusion, (
            f"Synthesis returned 'Analysis incomplete': {result.conclusion!r}. "
            "Expected a real LLM-generated conclusion."
        )
        assert result.confidence_score > 0.0, (
            "Expected a positive confidence score from the mocked LLM response."
        )

    def test_tsla_conclusion_not_no_agent_outputs_message(self):
        """The specific 'No agent outputs or evidence available.' string must not
        appear in the conclusion when the company is a known ticker."""
        from app.services.thesis_synthesizer import synthesize_thesis

        company = _tsla()
        val, mac, risk, market, quality = _empty_agents()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = _make_thesis_json(
                conclusion="Tesla's margin recovery path depends on cost execution."
            )
            result = synthesize_thesis(company, val, mac, risk, market, quality, [])

        assert "No agent outputs or evidence available" not in result.conclusion, (
            "Found the exact pre-fix failure message in the conclusion. "
            "The guard is still firing for TSLA."
        )

    def test_truly_unknown_company_still_bails_immediately(self):
        """Unknown company (no ticker, no name) must still return empty thesis
        immediately without LLM attempt — to avoid wasting model calls on
        completely opaque inputs."""
        from app.services.thesis_synthesizer import synthesize_thesis

        unknown = CompanyContext(ticker="", company_name="")
        val, mac, risk, market, quality = _empty_agents()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            result = synthesize_thesis(unknown, val, mac, risk, market, quality, [])

        # LLM must NOT have been called
        mock_client.call.assert_not_called(), (
            "model_client.call was invoked for a completely unknown company "
            "(no ticker, no name).  The guard should fire immediately here."
        )
        assert "No agent outputs" in result.conclusion

    def test_llm_failure_still_returns_thesis_not_exception(self):
        """Even if the LLM fails after the guard bypass, synthesize_thesis must
        return an InvestmentThesis rather than raising."""
        from app.services.thesis_synthesizer import synthesize_thesis

        company = _tsla()
        val, mac, risk, market, quality = _empty_agents()

        with patch("app.services.thesis_synthesizer.model_client") as mock_client:
            mock_client.call.return_value = None  # simulates all retries failed
            result = synthesize_thesis(company, val, mac, risk, market, quality, [])

        assert isinstance(result, InvestmentThesis)
        assert result.ticker == "TSLA"
        # conclusion may be the retries-exhausted message — that's acceptable
        assert result.generated_at != ""


# ── CIK cache isolation ───────────────────────────────────────────────────────

class TestCikCacheIsolation:
    """Ensure module-level CIK cache doesn't bleed between tests."""

    def setup_method(self):
        sec_provider._ticker_cik_cache = None

    def teardown_method(self):
        sec_provider._ticker_cik_cache = None

    def test_cache_populated_after_first_call(self, monkeypatch):
        calls = []

        def _fake_fetch(url, timeout=10):
            calls.append(url)
            if "company_tickers" in url:
                return {"0": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."}}
            if "submissions" in url:
                return _tsla_submissions_response()
            return {"hits": {"hits": []}}

        monkeypatch.setattr(
            "app.services.providers.sec_provider._fetch_json", _fake_fetch
        )

        sec_provider.fetch_recent_filings("TSLA", years_back=3)
        first_call_count = len([u for u in calls if "company_tickers" in u])

        # Second call should NOT re-fetch company_tickers.json
        sec_provider.fetch_recent_filings("TSLA", years_back=3)
        second_call_count = len([u for u in calls if "company_tickers" in u])

        assert first_call_count == 1
        assert second_call_count == 1, (
            "company_tickers.json was fetched more than once. "
            "Module-level cache should prevent redundant HTTP calls."
        )
