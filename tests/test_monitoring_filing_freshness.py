"""Opt-in monitoring fallback; synthetic filings and no live requests."""

import pytest
from app.config import Settings
from app.services import filing_metric_evidence as service
from app.services.decision_monitoring_evidence import build_decision_monitoring
from test_filing_metric_evidence import CIK, URL, _xml, _document, _filing
from test_financial_thesis_foundation import reference

QUESTION = 'Which operating assumptions would make this issuer attractive or unattractive? Explain decision thresholds and cite evidence.'


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(service.settings, 'decision_monitoring_inputs_enabled', True)
    monkeypatch.setattr(service.settings, 'decision_monitoring_filing_fallback_enabled', True)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL':CIK})


def _financial_document():
    # A revenue/net-income/cash comparison with no operating-income fact.
    # No inferred operating margin is permitted.
    concepts = ('Revenues','NetIncomeLoss','NetCashProvidedByUsedInOperatingActivities')
    doc = _document()
    from app.providers.sec_inline_facts import parse_inline_observations
    doc.inline_xbrl_facts = tuple(row for concept in concepts for row in
        parse_inline_observations(_xml(concept).replace('id="f-',f'id="{concept}-f-'),cik=CIK,concepts=concepts))
    return doc


def test_rollout_default_disabled():
    assert Settings.model_fields['decision_monitoring_filing_fallback_enabled'].default is False


def test_disabled_broad_monitoring_does_not_fetch(monkeypatch):
    monkeypatch.setattr(service.settings,'decision_monitoring_filing_fallback_enabled',False)
    monkeypatch.setattr(service.sec_provider,'fetch_recent_filings',lambda *a,**k: pytest.fail('disabled fetch'))
    assert not service.requests_filing_metrics('AAPL',QUESTION)
    assert service.fetch_latest_filing_metrics('AAPL',question=QUESTION)==[]


def test_enabled_requires_source_monitoring_setting(enabled,monkeypatch):
    monkeypatch.setattr(service.settings,'decision_monitoring_inputs_enabled',False)
    assert not service.requests_filing_metrics('AAPL',QUESTION)


def test_enabled_fetch_keeps_full_core_metrics_and_bound_missing_margin(enabled,monkeypatch):
    calls=[]
    monkeypatch.setattr(service.sec_provider,'fetch_recent_filings',lambda *a,**k: [_filing()])
    monkeypatch.setattr(service,'fetch_public_document',lambda *a,**k: (calls.append((a,k)) or _financial_document()))
    assert service.requests_filing_metrics('AAPL',QUESTION)
    items=service.fetch_latest_filing_metrics('AAPL',question=QUESTION)
    assert len(items)==3 and len(calls)==1
    assert calls[0][0]==(URL,) and calls[0][1]['inline_fact_cik']==CIK
    assert all(item.reporting_period_end=='2026-06-30' for item in items)
    refs=[reference(item,f'E{i}') for i,item in enumerate(items,1)]
    result=build_decision_monitoring('AAPL',items,refs,expected_cik=CIK)
    assert result and result['answer'].startswith('Evidence-backed financial monitoring (partial)')
    assert result['benchmarks']==[]
    assert len(result['foundation']['claims'])==3
    assert 'operating income' in result['unanswered_parts']


@pytest.mark.parametrize('question',[
    'Give decision thresholds for Services revenue and App Store growth with evidence.',
    'Give decision thresholds for segment revenue with evidence.',
    'What is the weather today?',
])
def test_unrelated_or_specialized_request_not_broadened(enabled,question):
    assert not service.requests_filing_metrics('AAPL',question)


def test_asof_still_refuses_document_fetch(enabled,monkeypatch):
    monkeypatch.setattr(service.sec_provider,'fetch_recent_filings',lambda *a,**k: pytest.fail('as-of fetch'))
    assert service.fetch_latest_filing_metrics('AAPL',question=QUESTION,as_of='2025-01-01')==[]


def test_failed_fallback_retains_existing_facts(enabled,monkeypatch):
    from test_financial_thesis_foundation import evidence
    old=evidence('Revenues','revenue')
    monkeypatch.setattr(service.sec_provider,'fetch_recent_filings',lambda *a,**k: [_filing()])
    def failure(*a,**k):raise ValueError('invented failure')
    monkeypatch.setattr(service,'fetch_public_document',failure)
    fresh=service.fetch_latest_filing_metrics('AAPL',question=QUESTION)
    assert fresh==[]
    assert service.merge_latest_filing_metrics([old],fresh,ticker='AAPL',question=QUESTION)==[old]


def test_newer_same_concept_replaces_whole_pair_without_cross_period_arithmetic(enabled):
    from test_financial_thesis_foundation import evidence
    old=evidence('Revenues','revenue')
    fresh=service.evidence_from_filing(_financial_document(),_filing(),ticker='AAPL',cik=CIK)
    merged=service.merge_latest_filing_metrics([old],fresh,ticker='AAPL',question=QUESTION)
    assert old not in merged and len(merged)==3
    assert all(item.reporting_period_end=='2026-06-30' for item in merged)
    assert all(all(c['inline_binding'] for c in item.verified_claims) for item in merged)


def test_metadata_or_wrong_issuer_cannot_supply_new_financials(enabled):
    doc=_financial_document();doc.final_url='https://www.sec.gov/Archives/edgar/data/999999/000032019326000001/company.htm'
    assert service.evidence_from_filing(doc,_filing(),ticker='AAPL',cik=CIK)==[]
    assert service.merge_latest_filing_metrics([],[_filing()],ticker='AAPL',question=QUESTION)==[]


def test_newer_filing_comparisons_clear_metadata_gap_only_when_covered(enabled):
    from test_financial_thesis_foundation import evidence
    old=evidence('Revenues','revenue')
    fresh=service.evidence_from_filing(_financial_document(),_filing(),ticker='AAPL',cik=CIK)
    merged=service.merge_latest_filing_metrics([old],fresh,ticker='AAPL',question=QUESTION)
    listing=_filing()
    items=merged+[listing]
    refs=[reference(item,f'E{i}') for i,item in enumerate(items,1)]
    refs[-1].update(claim_type='filing_metadata',document_type='10-Q',reporting_period_end='2026-06-30')
    result=build_decision_monitoring('AAPL',items,refs,expected_cik=CIK)
    assert result and 'reporting_period_coverage' not in result
    assert 'operating margin' in result['unanswered_parts'] and result['benchmarks']==[]


def test_freshness_never_makes_revenue_aliases_interchangeable(enabled):
    from test_financial_thesis_foundation import evidence
    from app.providers.sec_inline_facts import parse_inline_observations
    old=evidence('Revenues','revenue')
    alternative='RevenueFromContractWithCustomerExcludingAssessedTax'
    doc=_document(_xml(alternative))
    doc.inline_xbrl_facts=parse_inline_observations(_xml(alternative),cik=CIK,concepts=(alternative,))
    fresh=service.evidence_from_filing(doc,_filing(),ticker='AAPL',cik=CIK)
    assert len(fresh)==1
    merged=service.merge_latest_filing_metrics([old],fresh,ticker='AAPL',question=QUESTION)
    assert merged==[old]
