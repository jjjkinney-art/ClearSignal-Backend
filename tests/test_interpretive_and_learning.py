from __future__ import annotations
"""
Additional tests for final completion pass.

These tests verify that datetime usage is timezone aware, historical
summaries are interpretive, monitoring decisions vary based on
contextual judgement, alerts include interpretive fields, and
learning weights incorporate outcome awareness.
"""

from datetime import datetime, timezone

import pytest  # type: ignore


def test_timezone_aware_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest_price_history and ingest_signals should record timezone‑aware timestamps."""
    from app.data_pipeline.ingestion import ingest_price_history, ingest_signals
    # Capture price record
    captured: dict[str, any] = {}
    def fake_insert_price(records, db_path=None):
        captured['price'] = records[0]
    # Patch provider to return price
    monkeypatch.setattr('app.data_pipeline.ingestion.get_market_snapshot', lambda symbol, api_key='': {'price': 10.0})
    monkeypatch.setattr('app.data_pipeline.ingestion.insert_price_records', fake_insert_price)
    ingest_price_history('FOO')
    rec = captured['price']
    assert rec.timestamp.tzinfo is not None and rec.timestamp.tzinfo.utcoffset(rec.timestamp) is not None
    # Capture signal record
    captured2: dict[str, any] = {}
    def fake_insert_signal(records, db_path=None):
        captured2['signal'] = records[0]
    # Patch scoring to produce a predictable score
    monkeypatch.setattr('app.services.signal_scoring.score_signals', lambda signals: [
        {
            'signal': signals[0],
            'importance_score': 10.0,
            'impact_type': 'risk',
            'time_horizon': 'short',
            'confidence_score': 0.5,
            'weighted_score': 10.0,
        }
    ])
    monkeypatch.setattr('app.data_pipeline.ingestion.insert_signal_records', fake_insert_signal)
    ingest_signals(['test_signal'])
    rec2 = captured2['signal']
    assert rec2.timestamp.tzinfo is not None and rec2.timestamp.tzinfo.utcoffset(rec2.timestamp) is not None


def test_interpretive_historical_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should produce interpretive metrics and summary lines."""
    from app.services.evidence_service import build_evidence, GroundingContext
    # Patch provider functions to return deterministic data
    monkeypatch.setattr('app.services.evidence_service.get_company_profile', lambda *args, **kwargs: {'name': 'Foo'})
    monkeypatch.setattr('app.services.evidence_service.get_market_snapshot', lambda *args, **kwargs: {'price': 100.0, 'volume': 10})
    monkeypatch.setattr('app.services.evidence_service.get_financial_context', lambda *args, **kwargs: {'revenue': 100.0})
    monkeypatch.setattr('app.services.evidence_service.get_recent_news', lambda *args, **kwargs: [{'title': 'News', 'date': '2025-01-01'}])
    monkeypatch.setattr('app.services.evidence_service.get_recent_filings', lambda *args, **kwargs: [{'filing_type': '10-K', 'filing_date': '2025-01-01', 'title': 'Filing'}])
    monkeypatch.setattr('app.services.evidence_service.get_company_facts', lambda *args, **kwargs: {})
    monkeypatch.setattr('app.services.evidence_service.get_public_context', lambda *args, **kwargs: [])
    monkeypatch.setattr('app.services.evidence_service.get_document_context', lambda *args, **kwargs: [])
    # Patch storage queries to supply simple histories for interpretive metrics.
    # Use timestamps relative to now so records always fall within the 180-day
    # window used by evidence_service's history_ops queries.
    from datetime import timedelta, timezone as _tz
    _now = datetime.now(_tz.utc)
    _d1 = (_now - timedelta(days=150)).strftime('%Y-%m-%d')
    _d2 = (_now - timedelta(days=100)).strftime('%Y-%m-%d')
    _d3 = (_now - timedelta(days=50)).strftime('%Y-%m-%d')
    _d4 = (_now - timedelta(days=30)).strftime('%Y-%m-%d')

    def fake_query_records(table: str, limit: int | None = None, **kwargs):
        if table == 'price_history':
            return [
                {'timestamp': _d1, 'price': 90.0},
                {'timestamp': _d2, 'price': 100.0},
                {'timestamp': _d3, 'price': 110.0},
            ]
        if table == 'event_history':
            return [
                {'event_type': 'news', 'timestamp': _d1},
                {'event_type': 'news', 'timestamp': _d2},
                {'event_type': 'filing', 'timestamp': _d3},
                {'event_type': 'filing', 'timestamp': _d4},
            ]
        if table == 'signal_history':
            return [
                {'signal': 'news event', 'timestamp': _d1, 'weighted_score': 50.0},
                {'signal': 'news event', 'timestamp': _d2, 'weighted_score': 55.0},
                {'signal': 'filing event', 'timestamp': _d3, 'weighted_score': 60.0},
                {'signal': 'filing event', 'timestamp': _d4, 'weighted_score': 65.0},
            ]
        return []
    monkeypatch.setattr('app.data_pipeline.storage.query_records', fake_query_records)
    ctx = GroundingContext(company='Foo')
    ctx = build_evidence('Foo', 'FOO', '', ['fmp', 'sec'], ctx)
    # Interpretive metrics should still be present in financials for backward compatibility
    for key in [
        'trend_direction', 'trend_strength', 'volatility_regime', 'pattern_behavior',
        'signal_frequency_change', 'alert_frequency_trend', 'repeated_event_patterns',
        'event_frequency_trend'
    ]:
        assert key in ctx.financials
    # New interpretation objects should exist on the context
    assert hasattr(ctx, 'historical_interpretations'), "Historical interpretation objects missing"
    hist = ctx.historical_interpretations
    assert isinstance(hist, dict) and hist, "historical_interpretations should be a non‑empty dict"
    # Expect interpretation objects for price and financial domains
    assert 'price' in hist and 'financial' in hist
    # Each interpretation should have a summary
    for obj in hist.values():
        # The object should have interpretation_summary field
        assert hasattr(obj, 'interpretation_summary'), "Interpretation object missing summary"
        if obj.interpretation_summary:
            # ensure no key=value patterns in summary
            content = obj.interpretation_summary.split(':', 1)[-1].lower()
            assert '=' not in content
            assert any(word in content for word in ['shows', 'is', 'are', 'leading'])
    # There should be at least one interpretive summary line in known_facts
    summaries = [fact for fact in ctx.known_facts if fact.startswith('Interpretive summary:')]
    assert summaries, "No interpretive summary lines found"
    for line in summaries:
        content = line.split(':', 1)[1].lower() if ':' in line else line.lower()
        assert '=' not in content
        assert any(word in content for word in ['shows', 'is', 'are', 'leading'])


def test_monitoring_judgement_based(monkeypatch: pytest.MonkeyPatch) -> None:
    """process_events should make different decisions based on context."""
    from app.services.monitoring_service import process_events
    from app.data_pipeline.schemas import EventRecord
    import app.services.learning as learning
    # Patch update_signal_effectiveness and ingest_signals to avoid side effects
    monkeypatch.setattr('app.services.monitoring_service.update_signal_effectiveness', lambda signals: None)
    monkeypatch.setattr('app.services.monitoring_service.ingest_signals', lambda signals, timestamp=None: None)
    # Patch query_records to control baseline and event frequencies
    def fake_query_records(table: str, limit: int | None = None, **kwargs):
        if table == 'signal_history':
            # Baseline around 55
            return [{'weighted_score': 50.0}, {'weighted_score': 60.0}]
        if table == 'event_history':
            # Frequent 'news' events, one 'filing'
            return [
                {'event_type': 'news'},
                {'event_type': 'news'},
                {'event_type': 'news'},
                {'event_type': 'filing'},
            ]
        return []
    monkeypatch.setattr('app.data_pipeline.storage.query_records', fake_query_records)
    # Patch score_signals to assign moderate weighted scores
    monkeypatch.setattr('app.services.signal_scoring.score_signals', lambda items: [
        {
            'signal': item,
            'importance_score': 50.0,
            'impact_type': 'risk',
            'time_horizon': 'short',
            'confidence_score': 0.5,
            'weighted_score': 60.0,
        }
        for item in items
    ])
    # Clear learning outcome memory and seed outcomes
    learning._signal_outcomes.clear()
    learning._signal_memory.clear()
    # Simulate that 'rare event' previously led to thesis changes
    learning._signal_outcomes['rare event'] = {'thesis_change': 2}
    # Patch analysis_service.analyze_company to no‑op
    monkeypatch.setattr('app.services.analysis_service.analyze_company', lambda req: None)
    now = datetime.now(timezone.utc)
    events = [
        EventRecord(ticker='ABC', timestamp=now, event_type='news', description='news event', source='news'),
        EventRecord(ticker='XYZ', timestamp=now, event_type='filing', description='rare event', source='SEC'),
    ]
    # Capture outcomes via update_signal_outcome instead of inspecting Pydantic models
    recorded_outcomes: list[str] = []
    def fake_update_signal_outcome(signals, outcome):
        # record one entry per signal
        for _ in signals:
            recorded_outcomes.append(outcome)
    monkeypatch.setattr('app.services.monitoring_service.update_signal_outcome', fake_update_signal_outcome)
    process_events(events)
    # For two events we expect two outcome records in order of processing
    assert len(recorded_outcomes) == 2
    # The first outcome corresponds to the news event, which should not be thesis change
    # The second outcome corresponds to the rare event and should be 'thesis_change'
    assert recorded_outcomes[1] == 'thesis_change'
    assert recorded_outcomes[0] in ('alert', 'noise')
    # The event objects should carry contextual_judgment and action_reasoning
    assert hasattr(events[0], 'contextual_judgment')
    assert hasattr(events[0], 'action_reasoning')
    # Ensure action reasoning does not reference 'score' or raw numeric values
    assert 'score' not in events[0].action_reasoning.lower()
    # Each event should include expected_outcome and historical_interpretation attributes
    assert hasattr(events[0], 'expected_outcome')
    assert hasattr(events[0], 'historical_interpretation')
    assert hasattr(events[1], 'expected_outcome') and events[1].expected_outcome == 'thesis_change'
    assert hasattr(events[1], 'historical_interpretation') and events[1].historical_interpretation is not None
    # A MonitoringDecision object should be attached to each event
    for ev in events:
        assert hasattr(ev, 'monitoring_decision'), "Missing monitoring_decision on event"
        md = ev.monitoring_decision
        # The decision's action should match the event's decision_action
        assert md.action == getattr(ev, 'decision_action')
        # Decision reasoning should not reference scores directly
        assert 'score' not in md.decision_reason.lower()
        # The contextual interpretation should match the contextual_judgment string
        assert md.contextual_interpretation == getattr(ev, 'contextual_judgment')


def test_alerts_interpretive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """generate_alerts should include interpretive fields when history is available."""
    from app.services import alert_service
    from app.schemas import ThesisChangeResult, SynthesisOutput
    import app.services.learning as learning
    # Prepare a simple change result
    changes = ThesisChangeResult(
        has_changed=True,
        change_severity='medium',
        change_summary='Macro overlay changed',
        changed_components=['macro_overlay'],
        impact_on_thesis='Macro factors updated.',
    )
    current = SynthesisOutput()
    # Patch query_records: moderate baseline and some matching signals
    def fake_query_records(table: str, limit: int | None = None, **kwargs):
        if table == 'signal_history':
            return [{'signal': 'macro overlay update', 'weighted_score': 50.0}]
        return []
    monkeypatch.setattr('app.data_pipeline.storage.query_records', fake_query_records)
    # Seed learning outcomes for this component
    learning._signal_outcomes.clear()
    learning._signal_outcomes['macro overlay update'] = {'alert': 2, 'thesis_change': 1}
    alerts = alert_service.generate_alerts(changes, current, user_focus=None)
    assert alerts, 'No alerts generated'
    alert = alerts[0]
    # New interpretive and meaning-first fields should be populated
    assert alert.pattern_type in ("cluster", "trend shift", "isolated"), f"Unexpected pattern_type: {alert.pattern_type}"
    # historical_behavior should be a string when data exists (it may be None when no history)
    assert alert.historical_behavior is not None
    # typical_outcome should be one of the recognised outcomes or 'none'
    assert alert.typical_outcome in ("alert", "reanalysis", "thesis_change", "noise", None, "none")
    # interpretive_summary should be a non‑empty string
    assert alert.interpretive_summary is not None and alert.interpretive_summary.strip() != ""
    # why_this_matters should be populated when historical data exists
    assert alert.why_this_matters is not None and alert.why_this_matters.strip() != ""
    # Check meaning-first fields
    # historical_case_type should reflect the dominant outcome profile
    assert alert.historical_case_type in ("alert-heavy", "reanalysis-heavy", "thesis-change-heavy", "noise-heavy", "mixed", None)
    # usual_historical_meaning should map to a plain language outcome
    assert alert.usual_historical_meaning in ("alert only", "re-analysis", "thesis change", "no action", "mixed outcomes", None)
    # current_case_interpretation should describe continuation, escalation or anomaly
    assert alert.current_case_interpretation in ("a growing cluster of similar events", "a trend shift indicating a change in frequency", "an isolated anomaly", None)
    # why_this_is_notable should be non-empty when historical meaning exists
    if alert.historical_case_type:
        assert alert.why_this_is_notable is not None and alert.why_this_is_notable.strip() != ""
    # A primary interpretation object should be attached to the alert
    assert hasattr(alert, 'alert_interpretation'), "Alert is missing alert_interpretation object"
    interp_obj = alert.alert_interpretation
    # The interpretation object should include key fields
    assert interp_obj.situation_type == alert.pattern_type
    assert interp_obj.typical_outcome == alert.typical_outcome
    # The why_this_matters field on the object should reflect the same value
    assert interp_obj.why_this_matters == alert.why_this_matters


def test_learning_weight_outcome_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    """Signals with positive outcomes should have higher weight than noisy signals."""
    import app.services.learning as learning
    # Clear memory and outcome history
    learning._signal_memory.clear()
    learning._signal_outcomes.clear()
    # Patch storage to prevent loading counts
    monkeypatch.setattr('app.data_pipeline.storage.query_records', lambda table, limit=None: [])
    # Set outcomes: positive for 'signal a', negative for 'signal b'
    learning._signal_outcomes['signal a'] = {'thesis_change': 3}
    learning._signal_outcomes['signal b'] = {'noise': 3}
    wa = learning.get_signal_weight('signal a')
    wb = learning.get_signal_weight('signal b')
    assert wa > wb
    assert wa >= 0.5 and wb >= 0.5


def test_learning_signal_profile_and_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Signals should expose explicit outcome profiles and weight ordering by profile."""
    import app.services.learning as learning
    # Clear memory and outcome history
    learning._signal_memory.clear()
    learning._signal_outcomes.clear()
    # Prevent storage queries from populating counts
    monkeypatch.setattr('app.data_pipeline.storage.query_records', lambda table, limit=None: [])
    # Define outcome distributions for four signals
    learning._signal_outcomes['sig_thesis'] = {'thesis_change': 3}
    learning._signal_outcomes['sig_reanalysis'] = {'reanalysis': 4}
    learning._signal_outcomes['sig_alert'] = {'alert': 5}
    learning._signal_outcomes['sig_noise'] = {'noise': 6}
    # Retrieve profiles
    prof_thesis = learning.get_signal_profile('sig_thesis')
    prof_reanalysis = learning.get_signal_profile('sig_reanalysis')
    prof_alert = learning.get_signal_profile('sig_alert')
    prof_noise = learning.get_signal_profile('sig_noise')
    assert prof_thesis['signal_profile'] == 'thesis-driven'
    assert prof_reanalysis['signal_profile'] == 'reanalysis-driven'
    assert prof_alert['signal_profile'] == 'alert-driven'
    assert prof_noise['signal_profile'] == 'noise-driven'
    # Dominant outcome profile should match signal_profile
    assert prof_thesis['dominant_outcome_profile'] == 'thesis-driven'
    assert prof_reanalysis['dominant_outcome_profile'] == 'reanalysis-driven'
    assert prof_alert['dominant_outcome_profile'] == 'alert-driven'
    assert prof_noise['dominant_outcome_profile'] == 'noise-driven'
    # Profile confidence should be between 0 and 1
    assert 0.0 <= prof_thesis['profile_confidence'] <= 1.0
    assert 0.0 <= prof_reanalysis['profile_confidence'] <= 1.0
    assert 0.0 <= prof_alert['profile_confidence'] <= 1.0
    assert 0.0 <= prof_noise['profile_confidence'] <= 1.0
    # Downstream priority policy should correspond to profile
    assert prof_thesis['downstream_priority_policy'] == 'highest priority'
    assert prof_reanalysis['downstream_priority_policy'] == 'medium-high priority'
    assert prof_alert['downstream_priority_policy'] == 'medium priority'
    assert prof_noise['downstream_priority_policy'] == 'reduced priority'
    assert 'outcome_behavior_summary' in prof_thesis and prof_thesis['outcome_behavior_summary']
    # Primary profile object should exist and mirror the dictionary values
    for prof in (prof_thesis, prof_reanalysis, prof_alert, prof_noise):
        assert 'profile_obj' in prof and prof['profile_obj'] is not None
        obj = prof['profile_obj']
        # The profile type should match
        assert obj.profile_type == prof['signal_profile']
        # Behaviour policy should align with downstream priority policy
        assert obj.behavior_policy == prof['downstream_priority_policy']
    # Compute weights based on profile factors
    w_thesis = learning.get_signal_weight('sig_thesis')
    w_reanalysis = learning.get_signal_weight('sig_reanalysis')
    w_alert = learning.get_signal_weight('sig_alert')
    w_noise = learning.get_signal_weight('sig_noise')
    # Expect strict ordering by profile factor (thesis > reanalysis > alert > noise)
    assert w_thesis > w_reanalysis > w_alert > w_noise


def test_monitoring_decision_without_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monitoring decisions should still be driven by interpretations when scores are zeroed."""
    from app.services.monitoring_service import process_events
    from app.data_pipeline.schemas import EventRecord
    import app.services.learning as learning
    # Patch update_signal_effectiveness and ingest_signals to avoid side effects
    monkeypatch.setattr('app.services.monitoring_service.update_signal_effectiveness', lambda signals: None)
    monkeypatch.setattr('app.services.monitoring_service.ingest_signals', lambda signals, timestamp=None: None)
    # Provide no history to emphasise interpretation
    monkeypatch.setattr('app.data_pipeline.storage.query_records', lambda table, limit=None: [])
    # Patch score_signals to return zero weighted score for all signals
    monkeypatch.setattr('app.services.signal_scoring.score_signals', lambda items: [
        {
            'signal': item,
            'importance_score': 0.0,
            'impact_type': 'risk',
            'time_horizon': 'short',
            'confidence_score': 0.0,
            'weighted_score': 0.0,
        }
        for item in items
    ])
    # Clear learning outcome memory and seed a thesis-driven outcome for a rare event
    learning._signal_outcomes.clear()
    learning._signal_memory.clear()
    learning._signal_outcomes['rare event'] = {'thesis_change': 1}
    # Patch analysis_service.analyze_company to no‑op
    monkeypatch.setattr('app.services.analysis_service.analyze_company', lambda req: None)
    now = datetime.now(timezone.utc)
    events = [
        EventRecord(ticker='ABC', timestamp=now, event_type='news', description='news event', source='news'),
        EventRecord(ticker='XYZ', timestamp=now, event_type='filing', description='rare event', source='SEC'),
    ]
    # Capture outcomes via update_signal_outcome
    recorded: list[str] = []
    def fake_update(signals, outcome):
        for _ in signals:
            recorded.append(outcome)
    monkeypatch.setattr('app.services.monitoring_service.update_signal_outcome', fake_update)
    process_events(events)
    # Second event should still produce thesis_change despite zero scores
    assert recorded[1] == 'thesis_change'
    # Each event should carry a monitoring_decision with appropriate action
    for ev in events:
        assert hasattr(ev, 'monitoring_decision')
        md = ev.monitoring_decision
        assert md.action in ('generate_alert', 'trigger_reanalysis', 'trigger_reanalysis_and_thesis_compare', 'record_signal_only')
        # Decision reasoning should not mention score
        assert 'score' not in md.decision_reason.lower()