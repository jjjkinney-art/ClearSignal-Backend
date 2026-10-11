"""Offline provider-to-consumer contracts; no model or live-provider acceptance."""
from datetime import datetime, timedelta, timezone
import socket

import pytest

from app.schemas import (RetrievedEvidence, CompanyContext, ValuationView,
                         MacroSensitivity, RiskProfile, MarketContext, QualityAssessment)
from app.services import confidence_calibrator as coverage
from app.services.freshness_analyzer import analyze_evidence_freshness, _parse_ts
from app.services.providers import fmp_provider
from app.services.thesis_synthesizer import _build_synthesis_prompt


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Freshness regression must not use network or models')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    from app.model_client import model_client
    monkeypatch.setattr(model_client, 'call', blocked)


def prompt(items):
    return _build_synthesis_prompt(
        CompanyContext(ticker='TEST', company_name='Test Company'),
        ValuationView(overall='', confidence=0), MacroSensitivity(overall='', confidence=0),
        RiskProfile(overall='', confidence=0), MarketContext(overall='', confidence=0),
        QualityAssessment(overall='', confidence=0), evidence=items)


def gap_codes(items):
    return {gap.split(' | ')[0] for gap in coverage.compute_evidence_coverage_gaps(items)[1]}


def dated(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def ratio(timestamp=''):
    return RetrievedEvidence(title='TEST Valuation Multiples', source='FMP/ratios-ttm',
        timestamp=timestamp, summary='Trailing P/E (TTM): 25.0x')


def earnings(timestamp):
    return RetrievedEvidence(title='TEST quarterly earnings results beat analyst estimates',
        source='SEC EDGAR', timestamp=timestamp,
        summary='Reported EPS of $2.50 versus consensus estimates of $2.40.',
        claim_type='reported_fact')


def test_actual_ratio_adapter_does_not_clear_current_coverage_or_claim_live_data(monkeypatch):
    monkeypatch.setattr(fmp_provider, '_get_api_key', lambda: 'synthetic')
    monkeypatch.setattr(fmp_provider, '_fetch_json', lambda url:
        [{'priceEarningsRatioTTM': 25}] if '/ratios-ttm/' in url else [])
    items = fmp_provider.fetch_valuation_ratios('TEST')
    assert len(items) == 1 and items[0].timestamp == ''
    dimension = analyze_evidence_freshness(items).valuation
    assert dimension.tier == 'unknown' and dimension.age_days is None
    assert dimension.item_count == 1
    assert 'GAP_VALUATION' in gap_codes(items)
    output = prompt(items)
    assert 'Trailing P/E (TTM): 25.0x' in output  # Evidence retained, not erased.
    assert '- No dated fresh valuation ratios available.' in output
    assert '- Dated fresh valuation ratios (FMP) are present' not in output
    assert 'Preserve unknown publication dates as unknown' in output


@pytest.mark.parametrize('publication', ['', 'not-a-date', dated(-1)])
@pytest.mark.parametrize('estimate_period', ['2000-01-01', '2099-01-01'])
def test_estimate_period_never_becomes_publication_date_or_reported_earnings(publication, estimate_period):
    # Exact restored-provider shape from PR258; this branch has no dependency
    # on that separate constructor repair. Exercise all downstream consumers.
    item = RetrievedEvidence(title='TEST Analyst Estimates', source='FMP/analyst-estimates',
        timestamp=publication, claim_type='estimate',
        summary=f'TEST analyst estimates: EPS est. (period ending {estimate_period}): $2.50.')
    profile = analyze_evidence_freshness([item])
    assert profile.estimates.tier == 'unknown' and profile.estimates.age_days is None
    assert profile.earnings.item_count == 0 and profile.earnings.tier == 'unknown'
    assert 'GAP_EARNINGS' in gap_codes([item])
    output = prompt([item])
    assert item.summary in output
    assert '- No dated recent reported earnings evidence' in output
    assert 'Keep these labeled estimates, not reported earnings' in output
    assert 'An estimate period is not a publication date' in output
    assert 'You MUST reference the consensus target vs current price or forward EPS estimate' not in output


@pytest.mark.parametrize('claim_type,source,title', [
    ('estimate', 'Research', 'TEST EPS'),
    ('unknown', 'FMP/analyst-estimates', 'TEST EPS'),
    ('unknown', 'Research', 'TEST Analyst Estimates'),
])
def test_even_dated_estimates_cannot_clear_reported_earnings_gap(claim_type, source, title):
    item = RetrievedEvidence(title=title, source=source, timestamp=dated(2),
        claim_type=claim_type, summary='EPS $2.50')
    profile = analyze_evidence_freshness([item])
    assert profile.estimates.tier == 'fresh'
    assert profile.earnings.item_count == 0
    assert 'GAP_EARNINGS' in gap_codes([item])


@pytest.mark.parametrize('timestamp', ['', 'unknown', '2026-02-30',
                                      '2026-01-01T99:00:00Z', '2026-01-01 trailing', dated(-1)])
def test_invalid_or_future_dates_stay_unknown_and_do_not_clear_gaps(timestamp):
    items = [ratio(timestamp), earnings(timestamp)]
    profile = analyze_evidence_freshness(items)
    assert profile.valuation.tier == profile.earnings.tier == 'unknown'
    assert {'GAP_VALUATION', 'GAP_EARNINGS'} <= gap_codes(items)


def test_dated_qualifying_items_still_clear_corresponding_gaps():
    items = [ratio(dated(5)), earnings(dated(5))]
    profile = analyze_evidence_freshness(items)
    assert profile.valuation.tier == profile.earnings.tier == 'fresh'
    assert profile.estimates.item_count == 0  # A reported beat is not an estimate item.
    assert not {'GAP_VALUATION', 'GAP_EARNINGS'} & gap_codes(items)
    output = prompt(items)
    assert '- Dated fresh valuation ratios (FMP) are present' in output
    assert '- Dated recent reported earnings evidence is present' in output


def test_mixed_pool_cannot_borrow_date_from_another_dimension():
    assert 'GAP_VALUATION' in gap_codes([ratio(), earnings(dated(2))])
    assert 'GAP_EARNINGS' in gap_codes([ratio(dated(2)), earnings('')])


def test_old_and_undated_ratios_do_not_become_fresh_together():
    items = [ratio(), ratio(dated(120))]
    assert analyze_evidence_freshness(items).valuation.tier == 'very_stale'
    assert 'GAP_VALUATION' in gap_codes(items)


def test_existing_freshness_boundaries_are_preserved():
    assert coverage._has_live_valuation([ratio(dated(14))])
    assert not coverage._has_live_valuation([ratio(dated(15))])
    assert coverage._has_recent_earnings([earnings(dated(90))])
    assert not coverage._has_recent_earnings([earnings(dated(91))])


def test_publication_parser_preserves_timezone_and_legacy_supported_forms():
    assert _parse_ts('2026-01-01T23:30:00-05:00') == datetime(2026, 1, 2, 4, 30, tzinfo=timezone.utc)
    assert _parse_ts('2026-01') == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert coverage._parse_timestamp('2026-01-01') == _parse_ts('2026-01-01')


def calendar(monkeypatch, rows):
    monkeypatch.setattr(fmp_provider, '_get_api_key', lambda: 'synthetic')
    monkeypatch.setattr(fmp_provider, '_fetch_json', lambda url: rows)
    return fmp_provider.fetch_earnings_calendar('TEST')


@pytest.mark.parametrize('actual', [None, True, '2.5', float('nan'), float('inf'), {}])
def test_calendar_estimates_do_not_become_reported_results(monkeypatch, actual):
    event_date = dated(2)[:10]
    items = calendar(monkeypatch, [dict(date=event_date, epsEstimated=2.5,
        revenueEstimated=1000000, eps=actual, revenue=None)])
    assert len(items) == 1 and items[0].claim_type == 'estimate'
    assert items[0].timestamp == '' and event_date in items[0].summary
    profile = analyze_evidence_freshness(items)
    assert profile.earnings.item_count == 0 and profile.earnings.tier == 'unknown'
    assert profile.estimates.item_count == 1 and profile.estimates.tier == 'unknown'
    assert 'GAP_EARNINGS' in gap_codes(items)
    assert '- No dated recent reported earnings evidence' in prompt(items)


@pytest.mark.parametrize('actual', [0, -2.5, 2.5])
def test_calendar_actual_results_retain_their_own_event_date(monkeypatch, actual):
    items = calendar(monkeypatch, [dict(date=dated(2)[:10], eps=actual, epsEstimated=2.5)])
    assert items[0].claim_type == 'reported_fact'
    assert f'EPS actual: ${actual:.2f}' in items[0].summary
    assert analyze_evidence_freshness(items).earnings.tier == 'fresh'
    assert 'GAP_EARNINGS' not in gap_codes(items)
    assert '- Dated recent reported earnings evidence is present' in prompt(items)


def test_calendar_rows_cannot_lend_newer_date_to_older_actual_results(monkeypatch):
    items = calendar(monkeypatch, [
        dict(date=dated(2)[:10], epsEstimated=2.5),
        dict(date=dated(150)[:10], eps=2.4),
    ])
    assert len(items) == 2
    assert items[0].timestamp == '' and items[1].timestamp == dated(150)[:10]
    assert analyze_evidence_freshness(items).earnings.tier == 'stale'
    assert 'GAP_EARNINGS' in gap_codes(items)
    assert '- No dated recent reported earnings evidence' in prompt(items)


@pytest.mark.parametrize('claim_type,source', [('estimate', 'Research'),
                                             ('unknown', 'FMP/analyst-estimates')])
def test_estimated_pe_cannot_become_observed_valuation_coverage(claim_type, source):
    item = RetrievedEvidence(title='TEST PE ratio analyst estimates', source=source,
        timestamp=dated(2), summary='Estimated PE ratio: 25x', claim_type=claim_type)
    profile = analyze_evidence_freshness([item])
    assert profile.valuation.item_count == 0 and profile.valuation.tier == 'unknown'
    assert profile.estimates.tier == 'fresh'
    assert 'GAP_VALUATION' in gap_codes([item])
    output = prompt([item])
    assert '- No dated fresh valuation ratios available.' in output
    assert '- Dated fresh valuation ratios (FMP) are present' not in output
