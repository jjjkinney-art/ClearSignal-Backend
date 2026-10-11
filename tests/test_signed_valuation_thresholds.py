"""Deterministic input-fidelity checks; no threshold investment policy is chosen."""
import pytest
from app.integrity.threshold_parsing import build_decision_thresholds


def band(bull, bear='>20x', metric='Forward P/E'):
    return build_decision_thresholds([{'metric': metric, 'bull_threshold': bull,
                                      'bear_threshold': bear}], ticker='TEST')[0]


@pytest.mark.parametrize('raw,value', [('<-10x', -10), ('<−10x', -10), ('<-.5x', -.5),
    ('<- .5x', -.5), ('<+10x', 10), ('<$-10', -10), ('<-$10', -10)])
def test_boundary_sign_and_display_preserved(raw, value):
    result = band(raw, '>$20' if '$' in raw else '>20x')
    assert result['unavailable'] is False
    assert result['bull_boundary'] == value
    assert result['neutral_interval'][0] == value
    assert str(float(value)) in result['display']


def test_negative_margin_band_keeps_order_and_overlap_validation():
    result = band('>-2%', '<-10%', 'Gross margin')
    assert not result['unavailable']
    assert result['neutral_interval'] == [-10, -2]
    assert band('>-10%', '<-2%', 'Gross margin')['unavailable']


def test_negative_eps_band_is_not_converted_to_positive():
    result = band('>-$1', '<-$3', 'EPS')
    assert not result['unavailable']
    assert result['bull_boundary'] == -1
    assert result['bear_boundary'] == -3


@pytest.mark.parametrize('raw', ['<1e3x', '<1E-3x', '<--2x', '<1,,000x', '<1,00x',
                               '<1.2.3x', '<10-12x', '<-€10', '<−€10', '<($10)', '<10..x',
                               '<-£10', '<- JPY 10', '<(10)x', '<10.x.', '<($10', '<10)x', '<' + '9'*400 + 'x', 123, True])
def test_ambiguous_malformed_or_nonfinite_boundary_is_unavailable(raw):
    assert band(raw)['unavailable'] is True


def test_standard_thousands_and_prose_are_preserved():
    result = band('below <1,000x', 'above >2,000x')
    assert not result['unavailable']
    assert result['neutral_interval'] == [1000, 2000]


@pytest.mark.parametrize('prefix', ['-US$', '−US$', '-usd', '-eur', '-uSd',
                                  '-anything', '- US $ ', '+usd'])
def test_public_builder_rejects_unconsumed_sign_before_numeric_boundary(prefix):
    # Free cash flow exposes the silent positive conversion: 20 > +10 would
    # otherwise be accepted as a coherent band, concealing the lost minus.
    result = band('>US$20', f'<{prefix}10', 'Free cash flow')
    assert result['unavailable'] is True
    assert 'bear_boundary' not in result
    assert result['display'] == 'Threshold unavailable'
    result = band(f'>{prefix}20', '<US$10', 'Free cash flow')
    assert result['unavailable'] is True
    assert 'bull_boundary' not in result


def test_thesis_wiring_preserves_negative_earnings_and_rejects_ambiguous_multiple():
    from types import SimpleNamespace
    from app.integrity.thesis_wiring import attach_structured_content
    thesis = SimpleNamespace(decision_thresholds=[], threshold_zones=[
        {'metric': 'EPS', 'bull_threshold': '>-$1', 'bear_threshold': '<-$3'},
        {'metric': 'Forward P/E', 'bull_threshold': '<1e3x', 'bear_threshold': '>20x'},
        {'metric': 'Forward P/E', 'bull_threshold': '<15x', 'bear_threshold': '>20x'},
    ])
    attach_structured_content(thesis, ticker='TEST', evidence=[])
    negative, invalid, positive = thesis.decision_thresholds
    assert negative['bull_boundary'] == -1
    assert negative['bear_boundary'] == -3
    assert invalid['unavailable']
    assert not positive['unavailable']
    assert positive['bull_boundary'] == 15
