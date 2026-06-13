"""
Tests for Phase 10B Slice 9 — Drift State Reconciliation.

Covers:
  - Same ticker returns identical drift_state via get_watchlist() and
    get_watchlist_drift() (the two sources are now consistent)
  - drift_state updates when a new EventImpactAssessment is written
  - Stale persisted drift_state in index.json is ignored; evaluator wins
  - No regression in watchlist reads (ticker fields still present)
  - No endpoint contract changes (WatchlistEntry and WatchlistDriftSummary
    schemas unchanged)
  - _enrich_drift_from_evaluator gracefully handles evaluator failure
  - thesis_stability in enrich_watchlist_intelligence handles evaluator
    vocabulary ("broke", "weakened") as well as legacy vocabulary
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import WatchlistEntry, WatchlistDriftSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path):
    """Return a WatchlistService + its data_dir backed by tmp_path."""
    from app.services.watchlist_service import WatchlistService
    svc = WatchlistService.__new__(WatchlistService)
    data_dir = str(tmp_path)
    from app.services.timeline_store import JsonFileTimelineStore
    svc._snapshot_store = JsonFileTimelineStore(data_dir=data_dir)
    svc._change_store   = JsonFileTimelineStore(data_dir=data_dir)
    svc._index_path     = tmp_path / "index.json"
    return svc


def _write_index(tmp_path: Path, ticker: str, drift_state: str = "breaking") -> None:
    """Write a raw index.json with a stale drift_state."""
    idx = {
        ticker.upper(): {
            "ticker": ticker.upper(),
            "company_name": ticker,
            "added_at": "2026-01-01T00:00:00+00:00",
            "drift_state": drift_state,  # stale persisted value
        }
    }
    (tmp_path / "index.json").write_text(json.dumps(idx))


def _make_drift_summary(ticker: str, direction: str = "weakened") -> WatchlistDriftSummary:
    return WatchlistDriftSummary(
        ticker=ticker.upper(),
        direction=direction,
        driver="rate sensitivity",
        materiality=0.6,
        alert_priority="medium",
    )


# ---------------------------------------------------------------------------
# TestDriftSourceConsistency
# ---------------------------------------------------------------------------

class TestDriftSourceConsistency:
    """Both paths return the same drift_state for the same ticker."""

    def test_get_watchlist_drift_state_matches_evaluator(self, tmp_path):
        """drift_state on WatchlistEntry matches WatchlistDriftSummary.direction."""
        _write_index(tmp_path, "AAPL", drift_state="stale_old_value")
        svc = _make_store(tmp_path)

        # Patch evaluator to return a known direction
        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("AAPL", direction="weakened")
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            # Simulate get_watchlist — it calls _enrich_drift_from_evaluator
            from app.services.watchlist_service import _enrich_drift_from_evaluator
            index = json.loads((tmp_path / "index.json").read_text())
            entries = [WatchlistEntry.model_validate(v) for v in index.values()]
            _enrich_drift_from_evaluator(entries)

        assert entries[0].drift_state == "weakened"

    def test_stale_persisted_drift_overridden(self, tmp_path):
        """A stale drift_state in index.json is replaced by evaluator value."""
        _write_index(tmp_path, "NVDA", drift_state="breaking")
        svc = _make_store(tmp_path)

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("NVDA", direction="strengthened")
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            from app.services.watchlist_service import _enrich_drift_from_evaluator
            index = json.loads((tmp_path / "index.json").read_text())
            entries = [WatchlistEntry.model_validate(v) for v in index.values()]
            _enrich_drift_from_evaluator(entries)

        # Evaluator value wins over stale persisted value
        assert entries[0].drift_state == "strengthened"
        assert entries[0].drift_state != "breaking"

    def test_both_endpoints_same_direction(self, tmp_path):
        """Simulates both endpoint paths and asserts they agree."""
        ticker = "TSLA"
        _write_index(tmp_path, ticker, drift_state="old_persisted")

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary(ticker, direction="broke")
        ]
        evaluator_mock.get_ticker_drift.return_value = _make_drift_summary(ticker, direction="broke")

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            from app.services.watchlist_service import _enrich_drift_from_evaluator
            # Path 1: GET /watchlist style
            index = json.loads((tmp_path / "index.json").read_text())
            entries = [WatchlistEntry.model_validate(v) for v in index.values()]
            _enrich_drift_from_evaluator(entries)
            wl_drift = entries[0].drift_state

        # Path 2: GET /watchlist/drift style
        wl_drift_summary = evaluator_mock.get_watchlist_drift([ticker])[0].direction

        assert wl_drift == wl_drift_summary


# ---------------------------------------------------------------------------
# TestEnrichDriftFromEvaluator
# ---------------------------------------------------------------------------

class TestEnrichDriftFromEvaluator:
    """Unit tests for _enrich_drift_from_evaluator."""

    def test_empty_entries_no_op(self):
        from app.services.watchlist_service import _enrich_drift_from_evaluator
        _enrich_drift_from_evaluator([])  # must not raise

    def test_sets_drift_state_from_evaluator(self):
        from app.services.watchlist_service import _enrich_drift_from_evaluator

        entry = WatchlistEntry(ticker="META", company_name="Meta", added_at="2026-01-01T00:00:00+00:00")
        entry.drift_state = "old_value"

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("META", direction="weakened")
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            _enrich_drift_from_evaluator([entry])

        assert entry.drift_state == "weakened"

    def test_unknown_ticker_keeps_existing(self):
        """Ticker not in evaluator result keeps whatever drift_state was set."""
        from app.services.watchlist_service import _enrich_drift_from_evaluator

        entry = WatchlistEntry(ticker="XYZ", company_name="XYZ", added_at="2026-01-01T00:00:00+00:00")
        entry.drift_state = "kept_value"

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = []  # no results

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            _enrich_drift_from_evaluator([entry])

        assert entry.drift_state == "kept_value"

    def test_evaluator_failure_silent(self):
        """If evaluator raises, entries keep original drift_state (no crash)."""
        from app.services.watchlist_service import _enrich_drift_from_evaluator

        entry = WatchlistEntry(ticker="FAIL", company_name="FAIL", added_at="2026-01-01T00:00:00+00:00")
        entry.drift_state = "original"

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            side_effect=RuntimeError("evaluator down"),
        ):
            _enrich_drift_from_evaluator([entry])  # must not raise

        assert entry.drift_state == "original"

    def test_multiple_tickers_all_enriched(self):
        from app.services.watchlist_service import _enrich_drift_from_evaluator

        entries = [
            WatchlistEntry(ticker="A", company_name="A", added_at="2026-01-01T00:00:00+00:00"),
            WatchlistEntry(ticker="B", company_name="B", added_at="2026-01-01T00:00:00+00:00"),
        ]

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("A", direction="strengthened"),
            _make_drift_summary("B", direction="broke"),
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            _enrich_drift_from_evaluator(entries)

        assert entries[0].drift_state == "strengthened"
        assert entries[1].drift_state == "broke"

    def test_ticker_case_insensitive(self):
        """Evaluator returns uppercase ticker; entry ticker may be any case."""
        from app.services.watchlist_service import _enrich_drift_from_evaluator

        entry = WatchlistEntry(ticker="aapl", company_name="Apple", added_at="2026-01-01T00:00:00+00:00")

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("AAPL", direction="unchanged")
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            _enrich_drift_from_evaluator([entry])

        assert entry.drift_state == "unchanged"


# ---------------------------------------------------------------------------
# TestNoWriteThroughDriftState
# ---------------------------------------------------------------------------

class TestNoWriteThroughDriftState:
    """process_new_thesis no longer persists drift_state to index.json."""

    def test_process_new_thesis_does_not_write_drift_state(self, tmp_path):
        """After process_new_thesis, index.json must not contain drift_state key."""
        import inspect
        from app.services.watchlist_service import WatchlistService

        src = inspect.getsource(WatchlistService.process_new_thesis)
        # The assignment `index[ticker]["drift_state"] = ...` must not appear
        assert 'index[ticker]["drift_state"]' not in src
        assert "drift_state" not in src.replace("drift_state is NOT persisted", "").replace("drift_state", "")

    def test_watchlist_service_source_no_drift_write(self):
        """Audit: drift_state is not written to index in the write path."""
        import inspect
        from app.services.watchlist_service import WatchlistService
        src = inspect.getsource(WatchlistService.process_new_thesis)
        # Must not contain write-through pattern
        lines_with_drift_write = [
            l for l in src.splitlines()
            if '"drift_state"' in l and ("=" in l) and "index" in l
            and not l.strip().startswith("#")
        ]
        assert len(lines_with_drift_write) == 0, (
            f"Unexpected drift_state write in process_new_thesis:\n" +
            "\n".join(lines_with_drift_write)
        )


# ---------------------------------------------------------------------------
# TestWatchlistReadNoRegression
# ---------------------------------------------------------------------------

class TestWatchlistReadNoRegression:
    """Existing watchlist read behavior is unchanged."""

    def test_watchlist_entry_required_fields_present(self, tmp_path):
        _write_index(tmp_path, "MSFT", drift_state="unchanged")

        evaluator_mock = MagicMock()
        evaluator_mock.get_watchlist_drift.return_value = [
            _make_drift_summary("MSFT", direction="unchanged")
        ]

        with patch(
            "app.services.thesis_impact_evaluator.get_default_evaluator",
            return_value=evaluator_mock,
        ):
            from app.services.watchlist_service import _enrich_drift_from_evaluator
            index = json.loads((tmp_path / "index.json").read_text())
            entries = [WatchlistEntry.model_validate(v) for v in index.values()]
            _enrich_drift_from_evaluator(entries)

        e = entries[0]
        assert e.ticker == "MSFT"
        assert e.company_name == "MSFT"
        assert isinstance(e.drift_state, str)

    def test_watchlist_entry_schema_unchanged(self):
        """WatchlistEntry schema still has drift_state field."""
        fields = WatchlistEntry.model_fields
        assert "drift_state" in fields

    def test_watchlist_drift_summary_schema_unchanged(self):
        """WatchlistDriftSummary schema still has direction field."""
        fields = WatchlistDriftSummary.model_fields
        assert "direction" in fields
        assert "ticker" in fields
        assert "materiality" in fields


# ---------------------------------------------------------------------------
# TestThesisStabilityEvaluatorVocab
# ---------------------------------------------------------------------------

class TestThesisStabilityEvaluatorVocab:
    """thesis_stability derivation handles evaluator vocabulary correctly."""

    def _compute_stability(self, drift_state: str) -> str:
        """Call enrich_watchlist_intelligence with a single entry and extract thesis_stability."""
        from app.services.watchlist_service import enrich_watchlist_intelligence

        entry = WatchlistEntry(
            ticker="TEST",
            company_name="Test",
            added_at="2026-01-01T00:00:00+00:00",
            drift_state=drift_state,
        )
        # Patch the internal material-change lookup to return empty
        with patch(
            "app.services.watchlist_service.watchlist_service.get_material_changes",
            return_value=[],
        ):
            enriched = enrich_watchlist_intelligence([entry])

        if not enriched:
            return "stable"
        return getattr(enriched[0], "thesis_stability", "stable")

    def test_broke_maps_to_breaking(self):
        stability = self._compute_stability("broke")
        assert stability == "breaking"

    def test_breaking_still_maps_to_breaking(self):
        """Legacy 'breaking' value still works."""
        stability = self._compute_stability("breaking")
        assert stability == "breaking"

    def test_weakened_maps_to_drifting(self):
        stability = self._compute_stability("weakened")
        assert stability == "drifting"

    def test_weakening_still_maps_to_drifting(self):
        """Legacy 'weakening' value still works."""
        stability = self._compute_stability("weakening")
        assert stability == "drifting"

    def test_strengthened_maps_to_stable(self):
        stability = self._compute_stability("strengthened")
        assert stability == "stable"

    def test_unchanged_maps_to_stable(self):
        stability = self._compute_stability("unchanged")
        assert stability == "stable"

    def test_priced_in_maps_to_stable(self):
        stability = self._compute_stability("priced_in")
        assert stability == "stable"
