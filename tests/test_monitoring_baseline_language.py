"""Monitoring baselines are historical comparisons, never investment thresholds.

A lower later figure must be compared only with the corresponding period one
year later, must not be described as making a company unattractive, and the
unassessed seasonality between different quarters must be stated.
"""
import re

from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.financial_thesis_foundation import build_financial_foundation
from test_financial_thesis_foundation import evidence, reference

UNATTRACTIVE_CLAIM = re.compile(r'(?<!not by itself )make[s]? the company unattractive', re.I)


def _items():
    items = [evidence('Revenues', 'revenue', current=200, prior=100),
             evidence('OperatingIncomeLoss', 'operating income', current=40, prior=10)]
    return items, [reference(item, f'E{i}') for i, item in enumerate(items, 1)]


def test_thesis_tests_name_the_baseline_period_and_comparable_period():
    items, refs = _items()
    result = build_financial_foundation('AAPL', items, refs, expected_cik='320193')
    revenue = next(row for row in result['inferences'] if row.get('metric') == 'revenue (as reported)')
    assert revenue['conditional_test'].startswith('Historical baseline: $200 for 2025-04-01 to 2025-06-30 '
                                                  '(quarterly period).')
    assert 'corresponding period one year later' in revenue['conditional_test']
    assert 'would not by itself make the company unattractive' in revenue['conditional_test']
    assert 'not a forecast' in revenue['conditional_test']
    answer = result['answer']
    assert 'not valuation or investment thresholds' in answer
    assert 'Seasonality between different quarters has not been assessed' in answer
    assert 'a sequential quarter is not a comparable period' in answer
    assert not UNATTRACTIVE_CLAIM.search(answer)


def test_year_to_date_baselines_say_so():
    items = [evidence('Revenues', 'revenue', ytd=True), evidence('OperatingIncomeLoss', 'operating income', ytd=True)]
    result = build_financial_foundation('AAPL', items, None, expected_cik='320193')
    assert '(year-to-date period)' in result['inferences'][0]['conditional_test']


def test_threshold_answer_separates_baseline_from_investment_threshold():
    items, refs = _items()
    result = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')
    answer = result['answer']
    assert ('Historical baseline, not an investment threshold: operating margin of 20.00% for '
            '2025-04-01 to 2025-06-30.') in answer
    assert 'corresponding period one year later' in answer
    assert 'a sequential quarter is not a comparable period' in answer
    assert 'They do not determine whether the stock is attractive or unattractive.' in answer
    assert not UNATTRACTIVE_CLAIM.search(answer)
    assert 'below' not in result['benchmarks'][0]['condition']
    assert 'not a buy/sell boundary' in result['benchmarks'][0]['limitation']
