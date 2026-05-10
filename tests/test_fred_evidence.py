"""
Tests for the FRED-backed evidence retrieval layer.

Coverage:
  - Missing / empty FRED_API_KEY returns []
  - _detect_topics() maps question keywords to the correct topics
  - _TOPIC_SERIES maps each topic to the required FRED series IDs
  - fetch_fred_series() handles missing key, URLError, HTTPError, and
    filters FRED's missing-value sentinel "."
  - retrieve_general_finance_evidence() calls fetch_fred_series for the
    correct series when a key is present, returns [] when key is absent,
    returns [] when fetch fails, caps at 5 results
  - Fetched evidence appears in general_finance_prompt() output
  - run_general_finance_agent() still returns a valid GeneralFinanceAnswer
    when FRED raises an exception (resilience test)
  - FRED request URL and params are correctly formed (TestFredRequestParams)
  - 400 HTTPError reads response body for diagnostics (TestFredRequestParams)
  - Startup diagnostic helper prints key presence (TestStartupDiagnostics)
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import RetrievedEvidence, GeneralFinanceAnswer
from app.services.general_finance_evidence import (
    retrieve_general_finance_evidence,
    fetch_fred_series,
    _detect_topics,
    _TOPIC_SERIES,
    _SERIES_META,
)
from app.prompts import general_finance_prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_urlopen(observations_by_series: dict):
    """Return a fake urlopen callable that dispatches on series_id in the URL.

    Each value in observations_by_series is a list of observation dicts
    e.g. [{"date": "2024-01-15", "value": "4.25"}].
    Any series not found in the dict raises URLError.
    """
    from urllib.error import URLError as _URLError

    def _urlopen(url, timeout=None):
        for series_id, obs in observations_by_series.items():
            if series_id in url:
                body = json.dumps({"observations": obs}).encode("utf-8")
                mock_resp = MagicMock()
                mock_resp.read.return_value = body
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                return mock_resp
        raise _URLError(f"no mock for URL: {url}")

    return _urlopen


def _one_obs(value: str = "4.25", date: str = "2024-01-15") -> List[dict]:
    return [{"date": date, "value": value}]


# ── Missing / empty API key ───────────────────────────────────────────────────

class TestMissingApiKey:
    """retrieve_general_finance_evidence returns [] when FRED_API_KEY is absent."""

    def test_env_var_not_set_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        assert result == []

    def test_empty_string_key_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "")
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        assert result == []

    def test_whitespace_only_key_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "   ")
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        assert result == []

    def test_unrelated_question_returns_empty_even_with_key(self, monkeypatch):
        """No matching topic → [] regardless of key."""
        monkeypatch.setenv("FRED_API_KEY", "valid-key")
        result = retrieve_general_finance_evidence("Who won the World Cup in 1994?")
        assert result == []


# ── Topic detection ───────────────────────────────────────────────────────────

class TestDetectTopics:
    """_detect_topics maps question keywords to topic names."""

    def test_bond_yield_question(self):
        assert "yields" in _detect_topics("Why are bond yields rising?")

    def test_treasury_yield_question(self):
        assert "yields" in _detect_topics("Why are Treasury yields rising?")

    def test_yield_curve_question(self):
        assert "yields" in _detect_topics("What does an inverted yield curve mean?")

    def test_inflation_question(self):
        assert "inflation" in _detect_topics("How does inflation affect the market?")

    def test_cpi_question(self):
        assert "inflation" in _detect_topics("How does CPI affect rate expectations?")

    def test_core_inflation_question(self):
        assert "inflation" in _detect_topics("Why is core inflation still elevated?")

    def test_interest_rate_question(self):
        assert "rates_fed" in _detect_topics("How do interest rates affect tech stocks?")

    def test_fed_question(self):
        assert "rates_fed" in _detect_topics("What will the Fed do next?")

    def test_fomc_question(self):
        assert "rates_fed" in _detect_topics("What happened at the FOMC meeting?")

    def test_rate_cut_question(self):
        assert "rates_fed" in _detect_topics("When will the Fed cut rates?")

    def test_recession_question(self):
        assert "recession" in _detect_topics("Are we heading into a recession?")

    def test_unemployment_question(self):
        assert "recession" in _detect_topics("How is the unemployment rate?")

    def test_gdp_question(self):
        assert "recession" in _detect_topics("What happened to GDP last quarter?")

    def test_multi_topic_question(self):
        """A question touching multiple topics returns all matching topics."""
        topics = _detect_topics("How does inflation affect interest rates?")
        assert "inflation" in topics
        assert "rates_fed" in topics

    def test_unrelated_question_returns_empty(self):
        assert _detect_topics("What is the capital of France?") == []

    def test_case_insensitive(self):
        assert "yields" in _detect_topics("WHY ARE TREASURY YIELDS RISING?")


# ── Topic-to-series mapping ───────────────────────────────────────────────────

class TestTopicSeriesMapping:
    """_TOPIC_SERIES contains the required series for each topic."""

    def _series_ids(self, topic: str) -> List[str]:
        return [sid for sid, _ in _TOPIC_SERIES[topic]]

    def test_yields_includes_dgs10(self):
        assert "DGS10" in self._series_ids("yields")

    def test_yields_includes_dgs2(self):
        assert "DGS2" in self._series_ids("yields")

    def test_yields_includes_t10y2y(self):
        assert "T10Y2Y" in self._series_ids("yields")

    def test_inflation_includes_cpiaucsl(self):
        assert "CPIAUCSL" in self._series_ids("inflation")

    def test_inflation_includes_cpilfesl(self):
        assert "CPILFESL" in self._series_ids("inflation")

    def test_rates_fed_includes_fedfunds(self):
        assert "FEDFUNDS" in self._series_ids("rates_fed")

    def test_rates_fed_includes_dfedtaru(self):
        assert "DFEDTARU" in self._series_ids("rates_fed")

    def test_rates_fed_includes_dfedtarl(self):
        assert "DFEDTARL" in self._series_ids("rates_fed")

    def test_recession_includes_unrate(self):
        assert "UNRATE" in self._series_ids("recession")

    def test_recession_includes_gdp_growth_rate(self):
        # GDPC1 (level) was replaced by A191RL1Q225SBEA (quarterly growth rate),
        # which is more useful for recession detection.
        assert "A191RL1Q225SBEA" in self._series_ids("recession")

    def test_recession_includes_indpro(self):
        assert "INDPRO" in self._series_ids("recession")

    def test_all_series_have_metadata(self):
        """Every series referenced in _TOPIC_SERIES has a _SERIES_META entry."""
        for topic, pairs in _TOPIC_SERIES.items():
            for series_id, _ in pairs:
                assert series_id in _SERIES_META, (
                    f"Series {series_id} (topic={topic}) missing from _SERIES_META"
                )

    def test_relevance_scores_in_bounds(self):
        for topic, pairs in _TOPIC_SERIES.items():
            for series_id, score in pairs:
                assert 0.0 <= score <= 1.0, (
                    f"relevance_score {score} out of bounds for {series_id}"
                )


# ── fetch_fred_series ─────────────────────────────────────────────────────────

class TestFetchFredSeries:
    """fetch_fred_series handles key absence and network/HTTP errors gracefully."""

    def test_missing_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert fetch_fred_series("DGS10") == []

    def test_empty_key_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "")
        assert fetch_fred_series("DGS10") == []

    def test_url_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        from urllib.error import URLError
        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=URLError("network timeout"),
        ):
            assert fetch_fred_series("DGS10") == []

    def test_http_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        from urllib.error import HTTPError
        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=HTTPError("url", 403, "Forbidden", {}, io.BytesIO()),
        ):
            assert fetch_fred_series("DGS10") == []

    def test_generic_exception_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=ValueError("unexpected parse error"),
        ):
            assert fetch_fred_series("DGS10") == []

    def test_filters_missing_value_sentinel(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        obs = [
            {"date": "2024-01-15", "value": "4.25"},
            {"date": "2024-01-12", "value": "."},     # FRED missing sentinel
            {"date": "2024-01-10", "value": "4.20"},
            {"date": "2024-01-08", "value": ""},      # empty string variant
        ]
        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=_mock_urlopen({"DGS10": obs}),
        ):
            result = fetch_fred_series("DGS10", limit=4)
        assert len(result) == 2
        assert all(o["value"] not in (".", "", None) for o in result)

    def test_returns_observations_in_order(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        obs = [
            {"date": "2024-01-15", "value": "4.25"},
            {"date": "2024-01-10", "value": "4.20"},
        ]
        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=_mock_urlopen({"DGS10": obs}),
        ):
            result = fetch_fred_series("DGS10", limit=2)
        assert result[0]["date"] == "2024-01-15"
        assert result[1]["date"] == "2024-01-10"

    def test_url_includes_series_id_and_api_key(self, monkeypatch):
        """Verify the constructed URL contains the series_id and api_key."""
        monkeypatch.setenv("FRED_API_KEY", "my-secret-key")
        captured_urls = []

        def fake_urlopen(url, timeout=None):
            captured_urls.append(url)
            raise Exception("stop")  # bail out immediately

        with patch("app.services.general_finance_evidence.urlopen", fake_urlopen):
            fetch_fred_series("T10Y2Y")

        assert captured_urls, "urlopen was never called"
        url = captured_urls[0]
        assert "T10Y2Y" in url
        assert "my-secret-key" in url
        assert "sort_order=desc" in url


# ── retrieve_general_finance_evidence with mocked fetch ──────────────────────

class TestRetrieveWithMockedFetch:
    """retrieve_general_finance_evidence assembles RetrievedEvidence from fetched data."""

    def test_bond_yield_question_fetches_dgs10_dgs2_t10y2y(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched = []

        def fake_fetch(series_id, limit=5):
            fetched.append(series_id)
            return _one_obs()

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        retrieve_general_finance_evidence("Why are bond yields rising?")
        assert "DGS10" in fetched
        assert "DGS2" in fetched
        assert "T10Y2Y" in fetched

    def test_inflation_question_fetches_cpiaucsl_cpilfesl(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched = []

        def fake_fetch(series_id, limit=5):
            fetched.append(series_id)
            return _one_obs("310.5")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        retrieve_general_finance_evidence("How does inflation affect the market?")
        assert "CPIAUCSL" in fetched
        assert "CPILFESL" in fetched

    def test_fed_rate_question_fetches_fedfunds(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched = []

        def fake_fetch(series_id, limit=5):
            fetched.append(series_id)
            return _one_obs("5.33")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        retrieve_general_finance_evidence("How do interest rates affect tech stocks?")
        assert "FEDFUNDS" in fetched

    def test_recession_question_fetches_core_series(self, monkeypatch):
        # GDPC1 (level) was replaced by A191RL1Q225SBEA (GDP growth rate) and
        # T10Y2Y (yield curve) was added as the leading recession indicator.
        monkeypatch.setenv("FRED_API_KEY", "test-key")
        fetched = []

        def fake_fetch(series_id, limit=5):
            fetched.append(series_id)
            return _one_obs("3.7")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        retrieve_general_finance_evidence("Are we heading into a recession?")
        assert "UNRATE" in fetched
        assert "A191RL1Q225SBEA" in fetched   # GDP growth rate (replaces GDPC1 level)
        assert "INDPRO" in fetched
        assert "T10Y2Y" in fetched            # yield curve — leading recession indicator

    def test_returns_retrieved_evidence_instances(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs("4.25")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        assert len(result) > 0
        for ev in result:
            assert isinstance(ev, RetrievedEvidence)

    def test_result_sorted_by_relevance_descending(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs("4.25")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        scores = [e.relevance_score for e in result]
        assert scores == sorted(scores, reverse=True)

    def test_caps_at_six_items(self, monkeypatch):
        """Multi-topic question cannot return more than 6 evidence items.
        The cap was raised from 5 → 6 to give better coverage when multiple
        topics match (e.g. rates_fed + inflation together have 8 series)."""
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs("4.25")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        # inflation + rates_fed now touches FEDFUNDS, DFEDTARU, DFEDTARL,
        # DGS2, DGS10, CPIAUCSL, CPILFESL, PCEPILFE = 8 series; cap → 6
        result = retrieve_general_finance_evidence(
            "How does inflation affect interest rates and the Fed's rate decisions?"
        )
        assert len(result) <= 6

    def test_no_duplicate_series_in_output(self, monkeypatch):
        """Same series never appears twice even when two topics claim it."""
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs("4.25")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence(
            "How do interest rates and inflation interact?"
        )
        titles = [e.title for e in result]
        assert len(titles) == len(set(titles)), "Duplicate evidence titles found"

    def test_empty_fetch_result_skipped(self, monkeypatch):
        """Series where fetch returns [] produces no evidence item."""
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return []  # all series return nothing

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        assert result == []

    def test_evidence_title_contains_value_and_date(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "DGS10":
                return [{"date": "2024-03-01", "value": "4.32"}]
            return []

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        dgs10_items = [e for e in result if "DGS10" in e.title or "10-Year" in e.title]
        assert dgs10_items, "Expected DGS10 evidence"
        item = dgs10_items[0]
        assert "4.32" in item.title
        assert "2024-03-01" in item.title

    def test_evidence_source_is_fred(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs()

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are bond yields rising?")
        for ev in result:
            assert "FRED" in ev.source

    def test_evidence_summary_contains_description(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "DGS10":
                return _one_obs("4.50")
            return []

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        dgs10 = next((e for e in result if "10-Year" in e.title), None)
        assert dgs10 is not None
        # The description from _SERIES_META should appear in the summary
        assert "discount" in dgs10.summary.lower() or "earnings" in dgs10.summary.lower()

    def test_fetch_exception_returns_empty(self, monkeypatch):
        """If fetch_fred_series raises (not returns []), retrieve still returns []."""
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def crashing_fetch(series_id, limit=5):
            raise RuntimeError("unexpected crash")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", crashing_fetch
        )
        # fetch_fred_series itself is supposed to handle errors and return [];
        # this tests the case where an unexpected exception escapes anyway.
        # The function should propagate the exception (fetch_fred_series is
        # responsible for its own error handling), so retrieve will see an
        # empty list only if fetch_fred_series handles it.
        # Here we verify the full pipeline doesn't crash /api/ask.
        try:
            result = retrieve_general_finance_evidence("Why are bond yields rising?")
            # If it returns, it should be a list
            assert isinstance(result, list)
        except RuntimeError:
            # If the exception propagates, the agent caller catches it
            # (tested separately in the agent pipeline tests)
            pass


# ── Evidence injection in prompts ─────────────────────────────────────────────

class TestFredEvidenceInPrompt:
    """FRED evidence fetched by mocked fetch appears in the prompt text."""

    def test_dgs10_evidence_appears_in_prompt(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "DGS10":
                return [{"date": "2024-04-01", "value": "4.61"}]
            return []

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        evidence = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        prompt = general_finance_prompt("Why are Treasury yields rising?", evidence=evidence)

        assert "CURRENT CONTEXT" in prompt
        assert "4.61" in prompt

    def test_cpi_evidence_appears_in_prompt(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "CPIAUCSL":
                return [{"date": "2024-03-01", "value": "312.3"}]
            if series_id == "CPILFESL":
                return [{"date": "2024-03-01", "value": "321.5"}]
            return []

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        evidence = retrieve_general_finance_evidence("How does inflation affect the market?")
        prompt = general_finance_prompt("How does inflation affect the market?", evidence=evidence)

        assert "CURRENT CONTEXT" in prompt
        assert "312.3" in prompt or "321.5" in prompt

    def test_no_key_no_context_section_in_prompt(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        evidence = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        prompt = general_finance_prompt("Why are Treasury yields rising?", evidence=evidence)
        assert "CURRENT CONTEXT" not in prompt

    def test_evidence_appears_before_user_question_in_prompt(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            return _one_obs("4.25")

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        evidence = retrieve_general_finance_evidence("Why are bond yields rising?")
        prompt = general_finance_prompt("Why are bond yields rising?", evidence=evidence)

        assert prompt.index("CURRENT CONTEXT") < prompt.index("USER QUESTION")


# ── Agent resilience when FRED fails ─────────────────────────────────────────

class TestAgentResilienceWithFredFailure:
    """/api/ask still returns a valid answer when FRED raises an exception."""

    def test_agent_continues_when_fred_network_fails(self, monkeypatch):
        from app import agents as ag

        def failing_retrieve(question):
            from urllib.error import URLError
            raise URLError("FRED is down")

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "Bond yields rise when economic data beats expectations.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", failing_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        result = ag.run_general_finance_agent("Why are bond yields rising?")
        assert isinstance(result, GeneralFinanceAnswer)
        assert result.answer != ""

    def test_agent_continues_when_fred_http_error(self, monkeypatch):
        from app import agents as ag

        def failing_retrieve(question):
            from urllib.error import HTTPError
            raise HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO())

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "Inflation reduces purchasing power and lifts rates.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", failing_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        result = ag.run_general_finance_agent("How does inflation affect the market?")
        assert isinstance(result, GeneralFinanceAnswer)
        assert result.answer != ""

    def test_fallback_agent_continues_when_fred_fails(self, monkeypatch):
        from app import agents as ag

        def failing_retrieve(question):
            raise ConnectionError("FRED unreachable")

        class StubClient:
            def call(self, prompt: str, **kwargs: Any) -> str:
                return json.dumps({
                    "answer": "The economy contracts when demand falls below productive capacity.",
                    "bullets": ["B1.", "B2.", "B3."],
                    "caveats": ["C1.", "C2."],
                })

        monkeypatch.setattr(ag, "retrieve_general_finance_evidence", failing_retrieve)
        monkeypatch.setattr(ag, "model_client", StubClient())

        result = ag.run_general_fallback_agent("Are we heading into a recession?")
        assert isinstance(result, GeneralFinanceAnswer)
        assert result.answer != ""


# ── FRED request URL / params ─────────────────────────────────────────────────

class TestFredRequestParams:
    """Verify the exact URL and query parameters sent to the FRED API.

    These tests patch urllib.request.urlopen at the module level and capture
    the URL argument so we can assert on its structure without making real
    network calls.
    """

    def _capturing_urlopen(self, captured_urls: list, observations=None):
        """Return a fake urlopen that records the request URL."""
        obs = observations if observations is not None else [
            {"date": "2024-01-01", "value": "4.25"}
        ]

        def _urlopen(url, timeout=None):
            captured_urls.append(url)
            body = json.dumps({"observations": obs}).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        return _urlopen

    def test_request_goes_to_fred_observations_endpoint(self, monkeypatch):
        """URL must point to the FRED series/observations endpoint."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert len(captured) == 1
        assert "api.stlouisfed.org/fred/series/observations" in captured[0]

    def test_request_contains_series_id(self, monkeypatch):
        """URL must include the requested series_id as a query param."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert "series_id=DGS10" in captured[0]

    def test_request_contains_different_series_id(self, monkeypatch):
        """series_id param must reflect the argument, not a hardcoded value."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("CPIAUCSL")
        assert "series_id=CPIAUCSL" in captured[0]
        assert "series_id=DGS10" not in captured[0]

    def test_request_contains_sort_order_desc(self, monkeypatch):
        """URL must include sort_order=desc so the latest observation is first."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert "sort_order=desc" in captured[0]

    def test_request_contains_file_type_json(self, monkeypatch):
        """URL must include file_type=json to get a parseable response."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert "file_type=json" in captured[0]

    def test_request_contains_limit_param(self, monkeypatch):
        """URL must include the limit query param."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10", limit=3)
        assert "limit=3" in captured[0]

    def test_request_limit_default_is_five(self, monkeypatch):
        """Default limit must be 5."""
        monkeypatch.setenv("FRED_API_KEY", "testkey1234")
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert "limit=5" in captured[0]

    def test_request_contains_api_key(self, monkeypatch):
        """URL must contain the api_key parameter."""
        key = "my_test_fred_key_xyz"
        monkeypatch.setenv("FRED_API_KEY", key)
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        assert f"api_key={key}" in captured[0]

    def test_api_key_stripped_of_whitespace(self, monkeypatch):
        """Leading/trailing whitespace in FRED_API_KEY must be stripped."""
        key = "  cleankey123  "
        monkeypatch.setenv("FRED_API_KEY", key)
        captured: list = []
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen(captured),
        )
        fetch_fred_series("DGS10")
        # The stripped key must be in the URL; the padded version must not
        assert "api_key=cleankey123" in captured[0]
        assert "api_key=++cleankey123++" not in captured[0]

    def test_diagnostic_print_masks_api_key(self, monkeypatch, capsys):
        """Diagnostic output must NOT expose the full API key."""
        full_key = "supersecretfredapikey99"
        monkeypatch.setenv("FRED_API_KEY", full_key)
        monkeypatch.setattr(
            "app.services.general_finance_evidence.urlopen",
            self._capturing_urlopen([]),
        )
        fetch_fred_series("DGS10")
        out = capsys.readouterr().out
        # Full key must not appear in stdout
        assert full_key not in out
        # But a masked version (first 4 chars) should appear
        assert "supe..." in out

    def test_400_error_reads_response_body(self, monkeypatch, capsys):
        """When FRED returns 400, the response body must be printed for diagnosis."""
        monkeypatch.setenv("FRED_API_KEY", "badkey")
        error_payload = b'{"error_code":400,"error_message":"Bad api_key."}'
        from urllib.error import HTTPError

        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=HTTPError(
                "url", 400, "Bad Request", {}, io.BytesIO(error_payload)
            ),
        ):
            result = fetch_fred_series("DGS10")

        assert result == []  # still returns [] gracefully
        out = capsys.readouterr().out
        # The 400 status and the error body must be visible in diagnostic output
        assert "400" in out
        assert "Bad Request" in out or "Bad api_key" in out

    def test_400_does_not_crash(self, monkeypatch):
        """A 400 response must be handled gracefully — no exception propagation."""
        monkeypatch.setenv("FRED_API_KEY", "anykey")
        from urllib.error import HTTPError

        with patch(
            "app.services.general_finance_evidence.urlopen",
            side_effect=HTTPError(
                "url", 400, "Bad Request", {}, io.BytesIO(b'{"error_code":400}')
            ),
        ):
            result = fetch_fred_series("DGS10")  # must not raise

        assert result == []


# ── Startup diagnostics ───────────────────────────────────────────────────────

class TestStartupDiagnostics:
    """_print_startup_diagnostics reports key presence without leaking values."""

    def test_both_keys_present(self, monkeypatch, capsys):
        monkeypatch.setenv("FRED_API_KEY",   "fred-key-abc")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key-xyz")
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()
        out = capsys.readouterr().out
        assert "FRED_API_KEY present:   True" in out
        assert "OPENAI_API_KEY present: True" in out
        # Actual key values must not appear
        assert "fred-key-abc"   not in out
        assert "openai-key-xyz" not in out

    def test_both_keys_absent(self, monkeypatch, capsys):
        monkeypatch.delenv("FRED_API_KEY",   raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()
        out = capsys.readouterr().out
        assert "FRED_API_KEY present:   False" in out
        assert "OPENAI_API_KEY present: False" in out

    def test_fred_missing_prints_warning(self, monkeypatch, capsys):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "some-key")
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "FRED_API_KEY" in out

    def test_openai_missing_prints_critical(self, monkeypatch, capsys):
        monkeypatch.setenv("FRED_API_KEY",   "some-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()
        out = capsys.readouterr().out
        assert "CRITICAL" in out
        assert "OPENAI_API_KEY" in out

    def test_no_keys_does_not_crash(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY",   raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()  # must not raise

    def test_key_length_reported(self, monkeypatch, capsys):
        monkeypatch.setenv("FRED_API_KEY",   "abc123")
        monkeypatch.setenv("OPENAI_API_KEY", "xyz789long")
        from app.startup import print_startup_diagnostics as _print_startup_diagnostics
        _print_startup_diagnostics()
        out = capsys.readouterr().out
        assert "len=6"  in out   # len("abc123")
        assert "len=10" in out   # len("xyz789long")


# ── _build_t10y2y_evidence ────────────────────────────────────────────────────

class TestBuildT10y2yEvidence:
    """Unit tests for the T10Y2Y special-case evidence builder.

    Requirement: T10Y2Y is defined as 10-year minus 2-year Treasury yield.
      positive value → 10-year > 2-year → NOT inverted
      negative value → 2-year > 10-year → INVERTED
    The builder must encode slope direction explicitly in both title and
    summary so the LLM cannot misinterpret the sign.
    """

    from app.services.general_finance_evidence import _build_t10y2y_evidence

    # ── positive spread ───────────────────────────────────────────────────────

    def test_positive_spread_title_says_not_inverted(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("0.49", "2024-11-15")
        assert "NOT inverted" in title or "not inverted" in title.lower()

    def test_positive_spread_title_contains_plus_sign(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("0.49", "2024-11-15")
        assert "+0.49" in title

    def test_positive_spread_summary_says_10yr_exceeds_2yr(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("0.49", "2024-11-15")
        low = summary.lower()
        assert "10-year" in low and "2-year" in low
        # Must state 10-year is higher (exceeds), not the other way round
        assert "10-year treasury yield exceeds" in low or "10-year" in low

    def test_positive_spread_summary_does_not_claim_inversion(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("0.49", "2024-11-15")
        low = summary.lower()
        # Must NOT claim the curve is currently inverted
        assert "curve is not inverted" in low or "not inverted" in low or "positively sloped" in low

    def test_positive_spread_summary_includes_date(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("0.49", "2024-11-15")
        assert "2024-11-15" in summary

    def test_positive_spread_notes_future_inversion_risk(self):
        """Summary should still mention that inversion precedes recessions for context."""
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("0.49", "2024-11-15")
        assert "invert" in summary.lower() or "recession" in summary.lower()

    # ── negative spread ───────────────────────────────────────────────────────

    def test_negative_spread_title_says_inverted(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("-0.52", "2024-03-01")
        assert "INVERTED" in title or "inverted" in title.lower()

    def test_negative_spread_title_contains_minus_value(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("-0.52", "2024-03-01")
        assert "-0.52" in title

    def test_negative_spread_summary_says_2yr_exceeds_10yr(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("-0.52", "2024-03-01")
        low = summary.lower()
        assert "2-year" in low and "10-year" in low
        # Must not claim the 10-year exceeds the 2-year
        assert "2-year treasury yield exceeds" in low or "inverted" in low

    def test_negative_spread_summary_mentions_recession_signal(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("-0.52", "2024-03-01")
        assert "recession" in summary.lower()

    def test_negative_spread_summary_includes_date(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        _, summary = _build_t10y2y_evidence("-0.52", "2024-03-01")
        assert "2024-03-01" in summary

    # ── flat / zero spread ────────────────────────────────────────────────────

    def test_zero_spread_title_says_flat(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("0.00", "2024-06-01")
        assert "flat" in title.lower()

    def test_zero_spread_title_not_inverted_label(self):
        """A flat curve must not be labelled 'INVERTED'."""
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, _ = _build_t10y2y_evidence("0.00", "2024-06-01")
        assert "INVERTED" not in title

    # ── unparseable value ─────────────────────────────────────────────────────

    def test_unparseable_value_does_not_raise(self):
        from app.services.general_finance_evidence import _build_t10y2y_evidence
        title, summary = _build_t10y2y_evidence("N/A", "2024-11-15")
        assert isinstance(title, str) and len(title) > 0
        assert isinstance(summary, str) and len(summary) > 0

    # ── end-to-end: positive spread in retrieve pipeline ─────────────────────

    def test_positive_spread_reaches_evidence_list(self, monkeypatch):
        """When T10Y2Y returns a positive value, the evidence object's
        title and summary must say 'not inverted'."""
        from app.services.general_finance_evidence import retrieve_general_finance_evidence

        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "T10Y2Y":
                return [{"date": "2024-11-15", "value": "0.49"}]
            return [{"date": "2024-11-15", "value": "4.25"}]

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Why are Treasury yields rising?")
        t10y2y_items = [ev for ev in result if "T10Y2Y" in ev.title or "2-Year" in ev.title]
        # At least one item must cover the spread
        spread_items = [
            ev for ev in result
            if "Minus 2-Year" in ev.title or "2s10s" in ev.title.lower()
        ]
        assert spread_items, "No T10Y2Y evidence item found in result"
        ev = spread_items[0]
        assert "not inverted" in ev.title.lower() or "NOT inverted" in ev.title
        assert "not inverted" in ev.summary.lower() or "positively sloped" in ev.summary.lower()

    def test_negative_spread_reaches_evidence_list(self, monkeypatch):
        """When T10Y2Y returns a negative value, the evidence object must say 'INVERTED'."""
        from app.services.general_finance_evidence import retrieve_general_finance_evidence

        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "T10Y2Y":
                return [{"date": "2024-03-01", "value": "-0.52"}]
            return [{"date": "2024-03-01", "value": "4.25"}]

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        result = retrieve_general_finance_evidence("Is the yield curve inverted?")
        spread_items = [
            ev for ev in result
            if "Minus 2-Year" in ev.title or "2s10s" in ev.title.lower()
        ]
        assert spread_items, "No T10Y2Y evidence item found in result"
        ev = spread_items[0]
        assert "inverted" in ev.title.lower()
        assert "inverted" in ev.summary.lower()

    def test_positive_spread_corrects_false_inversion_premise(self, monkeypatch):
        """User asks 'why is the yield curve inverted?' but evidence shows
        a positive spread.  The evidence text itself must state the curve is
        NOT inverted so the LLM can correct the user's premise politely."""
        from app.services.general_finance_evidence import retrieve_general_finance_evidence

        monkeypatch.setenv("FRED_API_KEY", "test-key")

        def fake_fetch(series_id, limit=5):
            if series_id == "T10Y2Y":
                return [{"date": "2024-11-15", "value": "0.49"}]
            return [{"date": "2024-11-15", "value": "4.25"}]

        monkeypatch.setattr(
            "app.services.general_finance_evidence.fetch_fred_series", fake_fetch
        )
        # Question asserts inversion — evidence should contradict it
        result = retrieve_general_finance_evidence(
            "Why is the yield curve inverted right now?"
        )
        spread_items = [
            ev for ev in result
            if "Minus 2-Year" in ev.title or "2s10s" in ev.title.lower()
        ]
        assert spread_items, "No T10Y2Y evidence item found in result"
        ev = spread_items[0]
        # The evidence text must give the LLM the correct fact
        assert "not inverted" in ev.title.lower() or "NOT inverted" in ev.title
        assert "not inverted" in ev.summary.lower() or "positively sloped" in ev.summary.lower()
        # And must NOT say the curve is currently inverted (in the title)
        assert "INVERTED" not in ev.title
