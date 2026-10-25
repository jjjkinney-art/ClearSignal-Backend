from copy import deepcopy
from app.services.thesis_evidence_overview import segment_persistence_case


def row():
    return {'reference_id': 'E9', 'segment_context': {'totals_reconciled': True,
        'segments': [{'label': label, 'start': '2025-01-01', 'end': '2025-12-31',
                      'operating_income_usd': value}
                     for label, value in [('Alpha', 8), ('Beta', -2), ('Gamma', 0)]]}}


def test_conditional_case_uses_reported_signs_and_preserves_scope():
    value = row()
    original = deepcopy(value)
    text = segment_persistence_case(value)
    assert 'Alpha was the only reported segment' in text
    assert 'Beta reported operating losses' in text
    assert 'Gamma' not in text
    assert 'weaken this case' in text and 'would support it' in text
    assert 'cost allocations apply' in text and '[E9]' in text
    assert value == original


def test_unreconciled_or_mixed_periods_withheld():
    value = row()
    value['segment_context']['totals_reconciled'] = False
    assert segment_persistence_case(value) is None
    value = row()
    value['segment_context']['segments'][1]['end'] = '2024-12-31'
    assert segment_persistence_case(value) is None


def test_multiple_profit_segments_and_zero_are_explicit():
    value = row()
    value['segment_context']['segments'].append(
        dict(value['segment_context']['segments'][0], label='Delta'))
    text = segment_persistence_case(value)
    assert 'Alpha; Delta' in text and 'Beta' in text
    assert 'Zero reported operating income: Gamma' in text
    assert 'only reported segment' not in text


def test_profit_only_is_not_attractiveness():
    value = row()
    value['segment_context']['segments'][1]['operating_income_usd'] = 2
    text = segment_persistence_case(value)
    assert 'sustain their contributions' in text
    assert 'do not establish an attractive investment' in text


def test_loss_only_requires_recovery_evidence():
    value = row()
    value['segment_context']['segments'][0]['operating_income_usd'] = -8
    text = segment_persistence_case(value)
    assert 'recovery case requires evidence' in text
    assert 'shares are inexpensive' in text
    assert 'Positive reported operating income:' not in text


def test_all_zero_or_empty_withheld():
    value = row()
    for segment in value['segment_context']['segments']:
        segment['operating_income_usd'] = 0
    assert segment_persistence_case(value) is None
    value['segment_context']['segments'] = []
    assert segment_persistence_case(value) is None


def test_complete_overview_uses_case_and_keeps_source_statement():
    from app.services.thesis_evidence_overview import render_bound_overview
    value = row()
    value.update(claim_kind='issuer_segment_financial_context', claim='Complete bound statement.')
    text = render_bound_overview([value])
    assert text.count('Complete bound statement.') == 1
    assert 'Alpha was the only reported segment' in text
    assert 'valuation and expected returns remain unverified' in text
    value['segment_context']['totals_reconciled'] = False
    text = render_bound_overview([value])
    assert 'only reported segment' not in text
    assert 'research case is whether' in text
