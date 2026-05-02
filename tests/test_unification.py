from __future__ import annotations
"""
Tests for final unification gaps in the AI analyst backend.

These tests ensure that the evidence service persists retrieved
data to the historical storage, that the ingestion pipeline
invokes the monitoring service to update learning and signal
history, that alerts adjust their severity based on historical
baselines, and that the learning module consults stored outcomes
when computing signal weights.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import evidence_service, alert_service, learning
from app.schemas import ThesisChangeResult, SynthesisOutput
from app.data_pipeline.ingestion import ingest_events
import app.data_pipeline.ingestion as dp_ingest


def test_build_evidence_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should persist price, financial and event data to storage."""
    calls: Dict[str, int] = {"price": 0, "financial": 0, "event": 0}
    # Patch provider functions to return simple values
    monkeypatch.setattr(evidence_service, "get_company_profile", lambda *args, **kwargs: {"name": "Foo"})
    monkeypatch.setattr(evidence_service, "get_market_snapshot", lambda *args, **kwargs: {"price": 10.0, "volume": 1})
    monkeypatch.setattr(evidence_service, "get_financial_context", lambda *args, **kwargs: {"revenue": 100.0})
    monkeypatch.setattr(evidence_service, "get_recent_news", lambda *args, **kwargs: [
        {"title": "News", "date": "2025-01-01"}
    ])
    monkeypatch.setattr(evidence_service, "get_recent_filings", lambda *args, **kwargs: [
        {"filing_type": "10-K", "filing_date": "2025-01-02", "title": "Filing"}
    ])
    monkeypatch.setattr(evidence_service, "get_company_facts", lambda *args, **kwargs: {})
    monkeypatch.setattr(evidence_service, "get_public_context", lambda *args, **kwargs: [])
    monkeypatch.setattr(evidence_service, "get_document_context", lambda *args, **kwargs: [])
    # Patch storage insert functions to count calls
    monkeypatch.setattr(evidence_service, "insert_price_records", lambda *args, **kwargs: calls.__setitem__("price", calls["price"] + 1))
    monkeypatch.setattr(evidence_service, "insert_financial_records", lambda *args, **kwargs: calls.__setitem__("financial", calls["financial"] + 1))
    monkeypatch.setattr(evidence_service, "insert_event_records", lambda *args, **kwargs: calls.__setitem__("event", calls["event"] + 1))
    # Bypass governance so providers are always called regardless of API keys
    monkeypatch.setattr(evidence_service, "_check_provider_access", lambda *a, **kw: True)
    # Build evidence
    ctx = evidence_service.build_evidence("Foo", "FOO", "", ["fmp", "sec"], evidence_service.GroundingContext(company="Foo"))
    # Ensure each insert function was called at least once
    assert calls["price"] == 1
    assert calls["financial"] == 1
    # SEC filings produce event persistence
    assert calls["event"] >= 1


def test_ingest_events_invokes_monitoring(monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest_events should call monitoring_service.process_events after storing events."""
    # Prepare events
    patched_events = []
    # Patch storage insertion to append events to list and do nothing else
    monkeypatch.setattr(dp_ingest, "insert_event_records", lambda events, db_path=None: patched_events.extend(events))
    # Patch monitoring service
    called = {"count": 0}
    def fake_process(events):
        called["count"] += 1
        # ensure events passed are those stored
        assert events is patched_events
    monkeypatch.setattr("app.services.monitoring_service.process_events", fake_process)
    # Patch providers to return one filing and one news
    monkeypatch.setattr(dp_ingest, "get_recent_filings", lambda *args, **kwargs: [
        {"title": "Filing", "filing_date": "2025-01-01"}
    ])
    monkeypatch.setattr(dp_ingest, "get_public_context", lambda *args, **kwargs: ["Headline"])
    # Call ingest_events
    dp_ingest.ingest_events("Foo", "FOO")
    # process_events should have been invoked once
    assert called["count"] == 1


def test_alert_baseline_adjustment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alert severity should be adjusted based on historical baseline."""
    # Prepare a ThesisChangeResult with a single component change
    changes = ThesisChangeResult(
        has_changed=True,
        change_severity="medium",
        change_summary="Macro overlay changed",
        changed_components=["macro_overlay"],
        impact_on_thesis="May affect macro outlook.",
    )
    current = SynthesisOutput()
    # Patch query_records to return high weighted scores to test downgrade
    monkeypatch.setattr("app.data_pipeline.storage.query_records", lambda table, limit=None, **kw: [
        {"weighted_score": 80.0} for _ in range(10)
    ])
    alerts = alert_service.generate_alerts(changes, current, user_focus=None)
    # Severity should be downgraded from medium to low due to high baseline
    assert alerts[0].severity == "low"
    # Patch query_records to return low weighted scores to test upgrade
    monkeypatch.setattr("app.data_pipeline.storage.query_records", lambda table, limit=None, **kw: [
        {"weighted_score": 20.0} for _ in range(10)
    ])
    alerts2 = alert_service.generate_alerts(changes, current, user_focus=None)
    # Severity should be upgraded from medium to high due to low baseline
    assert alerts2[0].severity == "high"


def test_alert_component_specific_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Component‑specific baselines should adjust alert severity relative to the overall baseline."""
    # Prepare a ThesisChangeResult with macro_overlay changed
    changes = ThesisChangeResult(
        has_changed=True,
        change_severity="medium",
        change_summary="Macro overlay changed",
        changed_components=["macro_overlay"],
        impact_on_thesis="Macro factors updated."
    )
    current = SynthesisOutput()
    # Case 1: baseline ~60, component baseline high ~80 → degrade to low
    def query_records_high_comp(table: str, limit: int | None = None, **kwargs):
        # Weighted scores: general signals 40 and 60, macro overlay signals 80
        return [
            {"signal": "other signal", "weighted_score": 40.0},
            {"signal": "general event", "weighted_score": 60.0},
            {"signal": "macro overlay update", "weighted_score": 80.0},
        ]
    monkeypatch.setattr("app.data_pipeline.storage.query_records", query_records_high_comp)
    alerts = alert_service.generate_alerts(changes, current, user_focus=None)
    # base severity is medium → degrade to low due to high component baseline
    assert alerts and alerts[0].severity == "low"
    # Case 2: baseline ~60, component baseline low ~30 → upgrade to high
    def query_records_low_comp(table: str, limit: int | None = None, **kwargs):
        return [
            {"signal": "other signal", "weighted_score": 40.0},
            {"signal": "general event", "weighted_score": 80.0},
            {"signal": "macro overlay update", "weighted_score": 30.0},
        ]
    monkeypatch.setattr("app.data_pipeline.storage.query_records", query_records_low_comp)
    alerts2 = alert_service.generate_alerts(changes, current, user_focus=None)
    assert alerts2 and alerts2[0].severity == "high"


def test_learning_weight_uses_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_signal_weight should load counts from the signal_history table when missing in memory."""
    # Clear the in‑memory memory
    learning._signal_memory.clear()
    # Patch query_records to simulate two past occurrences of the signal
    def _qr_weight(table, limit=None, **kwargs):
        return [
            {"signal": "Regulatory risk", "weighted_score": 50.0},
            {"signal": "regulatory risk", "weighted_score": 60.0},
            {"signal": "Other", "weighted_score": 10.0},
        ]
    monkeypatch.setattr("app.data_pipeline.storage.query_records", _qr_weight)
    weight = learning.get_signal_weight("Regulatory risk")
    # When no explicit outcomes are recorded, the signal profile defaults to noise-driven
    # which applies a 0.8 multiplicative factor to the base weight derived from
    # occurrences and average weighted scores.  With two occurrences and an
    # average weighted score of 55, the base weight is 1 + 0.1*2 + 55/500 = 1.31.
    # Applying the noise-driven factor (0.8) yields 1.048.
    assert abs(weight - 1.048) < 1e-6


def test_monitoring_triggers_reanalysis(monkeypatch: pytest.MonkeyPatch) -> None:
    """process_events should initiate re‑analysis for each event."""
    from app.services import monitoring_service
    from app.data_pipeline.schemas import EventRecord
    # Create sample events
    # Use timezone‑aware timestamp for events to avoid naive datetime usage
    now = datetime.now(timezone.utc)
    events = [
        EventRecord(ticker="ABC", timestamp=now, event_type="news", description="Earnings announcement", source="news"),
        EventRecord(ticker="XYZ", timestamp=now, event_type="filing", description="Regulatory filing", source="SEC"),
    ]
    # Stub learning update and signal ingestion to avoid side effects
    monkeypatch.setattr(monitoring_service, "update_signal_effectiveness", lambda signals: None)
    monkeypatch.setattr(monitoring_service, "ingest_signals", lambda signals, timestamp=None: None)
    # Patch query_records to provide a predictable baseline and event frequency
    def fake_query_records(table: str, limit: int | None = None, **kwargs):
        # Provide a modest baseline for signal_history so threshold is around 55
        if table == "signal_history":
            return [
                {"weighted_score": 50.0},
                {"weighted_score": 60.0},
            ]
        if table == "event_history":
            # Return no events so event_type is rare and factor lowers threshold
            return []
        return []
    monkeypatch.setattr("app.data_pipeline.storage.query_records", fake_query_records)
    # Patch score_signals to assign high weights so threshold passes for each event
    def fake_score_signals(items: List[str], focus: str | None = None):
        return [{"signal": it, "weighted_score": 90.0} for it in items]
    monkeypatch.setattr("app.services.signal_scoring.score_signals", fake_score_signals)
    # Capture analysis calls
    calls = {"count": 0}
    def fake_analyze(req):
        calls["count"] += 1
    # Patch analysis_service.analyze_company to our fake function
    monkeypatch.setattr("app.services.analysis_service.analyze_company", fake_analyze)
    # Invoke process_events
    monitoring_service.process_events(events)
    # Expect analyze_company called once per event (threshold should not filter)
    assert calls["count"] == len(events)