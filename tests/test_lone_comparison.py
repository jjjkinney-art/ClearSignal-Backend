"""One verified annual comparison is delivered as a partial answer, with the specific reason each other measure was not compared.

Defect (offline-review/DEFECT_LOSS_MAKING_PARTIAL_20261113.md): CGC and MTA, both loss-making, kept only a revenue pair; the
financial foundation needed two, so the verified pair was dropped and the answer said it "could not be used". Facts are
trimmed retained SEC Company Facts from diagnostic D1."""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.providers import sec_client
from app.services import as_reported_financials as ar
from app.services import financial_thesis_foundation as foundation
from app.services import lone_comparison as lone

DATA = json.loads((Path(__file__).resolve().parent / 'data' / 'company_facts_lone_comparison_retained_d1.json').read_text())
FULL = json.loads((Path(__file__).resolve().parent / 'data' / 'company_facts_as_reported_retained_runs4_11.json').read_text())


@pytest.fixture(autouse=True)
def as_reported_on(monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)


def built(key, source=DATA):
    cik = str(source[key]['cik'])
    records = sec_client.as_reported_records_from_facts(source[key], cik, specs=ar.requested_specs())
    items, withheld = ar.build_comparisons(records, ticker=key, cik=cik)
    for item in items:
        item.freshness_status = 'current'
    refs = [{'id': f'E{i}', 'title': item.title.strip()[:300], 'source': item.source.strip()[:120], 'url': item.url,
             'published_at': item.timestamp, 'freshness_status': 'current'} for i, item in enumerate(items, 1)]
    return items, withheld, refs, cik


@pytest.mark.parametrize('key,taxonomy,currency', [('CGC', 'US-GAAP', 'CAD'), ('MTA', 'IFRS', 'USD')])
def test_the_retained_cases_build_one_revenue_comparison_and_withhold_the_rest_as_non_positive(key, taxonomy, currency):
    items, withheld, _, _ = built(key)
    assert [i.verified_claims[0]['metric'].split(':')[1] for i in items][0] in (
        'RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenue')
    assert len(items) == 1
    assert {(w['metric'], w['reason']) for w in withheld} == {('operating income', 'non_positive_value'),
                                                              ('net income', 'non_positive_value'),
                                                              ('operating cash flow', 'non_positive_value')}
    assert all(w['basis'] == taxonomy and w['currency'] == currency for w in withheld)


@pytest.mark.parametrize('key', ['CGC', 'MTA'])
def test_by_default_the_lone_comparison_is_still_dropped(key):
    items, withheld, refs, cik = built(key)
    assert foundation.build_financial_foundation(key, items, refs, expected_cik=cik) is None
    assert foundation.build_financial_foundation(key, items, refs, expected_cik=cik, allow_lone=False, withheld=withheld) is None


@pytest.mark.parametrize('key', ['CGC', 'MTA'])
def test_with_the_flag_the_lone_comparison_is_delivered_with_its_citation_and_the_reasons(key):
    items, withheld, refs, cik = built(key)
    result = foundation.build_financial_foundation(key, items, refs, expected_cik=cik, allow_lone=True, withheld=withheld)
    assert result is not None and len(result['claims']) == 1
    row = result['claims'][0]
    assert row['reference_id'] == 'E1' and row['claim'] == items[0].summary and row['claim_kind'] == 'reported_financial_comparison'
    text = result['answer']
    assert items[0].summary in text and 'What was not compared, and why' in text
    for name in ('operating income', 'net income', 'operating cash flow'):
        assert f'- {name}: not compared; at least one of its two annual amounts is zero or negative' in text
        assert name in result['unanswered_parts']
    assert 'Only one measure (revenue) could be compared' in text and 'nothing about profitability or cash generation' in text


@pytest.mark.parametrize('key', ['CGC', 'MTA'])
def test_the_explanation_states_no_figure_beyond_the_cited_pair(key):
    items, withheld, refs, cik = built(key)
    text = foundation.build_financial_foundation(key, items, refs, expected_cik=cik, allow_lone=True, withheld=withheld)['answer']
    section = text[text.index('What was not compared, and why'):]
    section = section[:section.index('Only one measure')]
    assert not any(ch.isdigit() for ch in section)


def test_a_reason_without_a_recorded_withheld_row_uses_a_generic_statement():
    items, _, refs, cik = built('CGC')
    text = foundation.build_financial_foundation('CGC', items, refs, expected_cik=cik, allow_lone=True, withheld=None)['answer']
    assert '- operating income: not compared; no verified comparison for the latest annual period was available.' in text


@pytest.mark.parametrize('reason,words', [('prior_value_zero', 'prior-year amount is zero'), ('periods_not_comparable', 'same length of time'),
                                          ('claim_binding_failed', 'could not be tied to the SEC filing'),
                                          ('older_period_than_other_measures', 'older than the period of the measure shown'),
                                          ('concept_not_reported', 'did not report this measure')])
def test_each_recorded_reason_has_its_own_wording(reason, words):
    assert words in lone.reason_for('net income', [{'metric': 'net income', 'reason': reason}])


def test_answers_with_two_or_more_comparisons_are_identical_with_the_flag(monkeypatch):
    for key in ('BP', 'MRX', 'FORFF'):
        items, withheld, refs, cik = built(key, FULL)
        off = foundation.build_financial_foundation(key, items, refs, expected_cik=cik)
        on = foundation.build_financial_foundation(key, items, refs, expected_cik=cik, allow_lone=True, withheld=withheld)
        assert off is not None and off == on and 'What was not compared' not in on['answer']


def test_the_flag_defaults_off_and_follows_the_setting(monkeypatch):
    assert type(settings).model_fields['lone_comparison_enabled'].default is False
    monkeypatch.setattr(settings, 'lone_comparison_enabled', True, raising=False)
    assert lone.enabled() is True
    monkeypatch.setattr(settings, 'lone_comparison_enabled', False, raising=False)
    assert lone.enabled() is False


# --- through the source-answer gate ---------------------------------------------------------------------------------

THESIS_Q = ('What is the investment thesis for Canopy Growth Corp, what supports it, and what could invalidate it? '
            'Distinguish reported facts from inference and cite material claims.')
THRESHOLD_Q = ('Which valuation and operating assumptions would make Canopy Growth Corp attractive or unattractive? Explain decision '
               'thresholds, evidence and uncertainty without inventing figures.')


def gate(monkeypatch, flag, question, withheld_passed=True, key='CGC'):
    from app.schemas import InvestmentThesis
    from app.services import source_answer
    from app.services.providers import sec_provider
    monkeypatch.setattr(settings, 'lone_comparison_enabled', flag, raising=False)
    items, withheld, refs, cik = built(key)
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {key: cik.zfill(10)})
    thesis = InvestmentThesis(ticker=key, company_name='Synthetic')
    result = source_answer.apply_source_answer_gate(thesis, question, items, references=refs,
                                                    as_reported_withheld=withheld if withheld_passed else None)
    return thesis, result, items


def test_the_gate_returns_a_partial_answer_with_one_bound_claim_when_the_flag_is_on(monkeypatch):
    thesis, result, items = gate(monkeypatch, True, THESIS_Q)
    assert result['status'] == 'partial' and len(result['claims']) == 1
    assert result['claims'][0]['claim'] == items[0].summary
    assert 'What was not compared, and why' in thesis.direct_answer and items[0].summary in thesis.direct_answer
    assert {'operating income', 'net income', 'operating cash flow'} <= set(result['unanswered_parts'])


def test_the_gate_still_fails_closed_when_the_flag_is_off(monkeypatch):
    thesis, result, _ = gate(monkeypatch, False, THESIS_Q)
    assert result is None or (result.get('status') != 'partial' or not result.get('claims'))
    assert 'What was not compared' not in (thesis.direct_answer or '')


def test_a_decision_threshold_question_is_identical_with_and_without_the_flag(monkeypatch):
    _, off, _ = gate(monkeypatch, False, THRESHOLD_Q)
    _, on, _ = gate(monkeypatch, True, THRESHOLD_Q)
    assert off == on
