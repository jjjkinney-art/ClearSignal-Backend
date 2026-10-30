"""Losses, zero crossings and sign changes are described in absolute terms.

A percentage of a negative base, or across a sign change, reads as growth or
decline in the wrong sense (run 2: "+542.7%" for a move from a loss to a
profit). Negative margins are described as losses relative to revenue.
"""
import pytest

from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.operating_margin_assessment import operating_margin_assessment
from test_financial_thesis_foundation import evidence, reference


@pytest.mark.parametrize('current,prior,expected', [
    (-33, -22, 'operating income was a loss in both periods; the loss widened by $11; signed amounts: -$33 '),
    (-46, -67, 'operating income was a loss in both periods; the loss narrowed by $21; signed amounts: -$46 '),
    (112, -25, 'operating income moved from a loss to a profit, a change of $137; signed amounts: $112 '),
    (-5, 40, 'operating income moved from a profit to a loss, a change of $45; signed amounts: -$5 '),
    (0, 40, 'operating income moved from a profit to zero, a change of $40; signed amounts: $0 '),
])
def test_profit_measures_across_losses_use_absolute_changes(current, prior, expected):
    item = evidence('OperatingIncomeLoss', 'operating income', current=current, prior=prior)
    assert expected in item.summary
    assert '%' not in item.summary


def test_positive_bases_keep_percentages():
    item = evidence('Revenues', 'revenue', current=120, prior=100)
    assert 'increased 20.0% to $120 ' in item.summary


def test_negative_non_profit_measures_are_not_called_losses():
    item = evidence('Revenues', 'revenue', current=-10, prior=-20)
    assert 'was negative in both periods and rose by $10' in item.summary
    assert 'loss' not in item.summary and 'profit' not in item.summary


def _margin(revenue, income):
    items = [evidence('Revenues', 'revenue', current=revenue[0], prior=revenue[1]),
             evidence('OperatingIncomeLoss', 'operating income', current=income[0], prior=income[1])]
    comparisons = {'revenue': (items[0], 'E1'), 'operating income': (items[1], 'E2')}
    return items, operating_margin_assessment(comparisons, [reference(i, f'E{n}') for n, i in enumerate(items, 1)])


def test_negative_margins_describe_the_loss_not_a_signed_narrowing():
    _, margin = _margin((1000, 1000), (-25, -20))
    assert 'was negative in both periods; the operating loss relative to revenue widened by 0.50 percentage points' in margin['text']
    assert 'narrowed' not in margin['text']
    assert 'larger operating loss relative to revenue' in margin['conditional_test']
    assert 'profitability assumption' not in margin['conditional_test']
    _, margin = _margin((1000, 1000), (-10, -20))
    assert 'the operating loss relative to revenue narrowed by 1.00 percentage points' in margin['text']


def test_margin_sign_changes_are_named():
    _, margin = _margin((1000, 1000), (20, -10))
    assert 'moved from an operating loss or break-even to an operating profit, up 3.00 percentage points' in margin['text']
    _, margin = _margin((1000, 1000), (-10, 20))
    assert 'moved from an operating profit to an operating loss or break-even, down 3.00 percentage points' in margin['text']


def test_threshold_answer_for_a_loss_making_issuer():
    items = [evidence('Revenues', 'revenue', current=1000, prior=1000),
             evidence('OperatingIncomeLoss', 'operating income', current=-25, prior=-20)]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    answer = build_decision_monitoring('AAPL', items, refs, expected_cik='320193')['answer']
    assert 'would mean a larger operating loss relative to revenue and weaken any recovery assumption' in answer
    assert 'profitability assumption' not in answer
