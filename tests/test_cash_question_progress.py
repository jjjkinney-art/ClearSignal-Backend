from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.services.operating_research_questions import operating_research_questions


@pytest.mark.parametrize('change', ['matched', 'hash', 'period', 'duplicate', 'absent'])
def test_cash_question_acknowledges_only_same_source_and_period_bridge(change):
    rows = deepcopy(json.loads(Path('docs/CASH_ANSWER_REPLAY_20261025.json').read_text())['results']['candidate']['source_answer']['claims'])
    bridge = rows[-1]
    if change == 'hash': bridge['document_ref']['content_hash'] = '0' * 64
    elif change == 'period': bridge['cash_reconciliation']['totals'][0]['end'] = '2026-12-31'
    elif change == 'duplicate': rows.append(deepcopy(bridge))
    elif change == 'absent': rows.pop()
    q = next(q for q in operating_research_questions(rows) if q['topic'] == 'annual_cash_conversion')
    assert q['causal_attribution_established'] is False
    if change == 'matched':
        assert q['reference_ids'] == ['E17', 'E18']
        assert 'reconciliation is provided below' in q['text']
        assert 'recur or reverse?' in q['text']
    else:
        assert q['reference_ids'] == ['E17']
        assert 'Reconcile the complete cash-flow statement' in q['text']
