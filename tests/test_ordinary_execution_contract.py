import json
from pathlib import Path

import pytest

from validation.ordinary_execution_contract import pending_manifest, matches_separate_approval, _digest

CASES = json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())


def proposal(**changes):
    values = {'cases': CASES, 'source_sha256': 'a' * 64, 'dependency_sha256': 'b' * 64,
              'output_dir': '/tmp/invented-output', 'all_in_usd': '0.00',
              'retention_reference': 'test-only-retention'}
    values.update(changes)
    return pending_manifest(**values)


def consent(manifest):
    return {'reference': 'test-only', 'manifest_sha256': _digest(manifest),
            'output_dir': manifest['output_dir'], 'all_in_usd': manifest['all_in_usd'],
            'execution_allowed': True, 'spending_authorized': True}


def test_pending_contract_is_bound_without_authorizing_execution():
    manifest = proposal()
    result = matches_separate_approval(manifest, consent(manifest))
    assert manifest['limits']['sec_gets'] == 66
    assert manifest['limits']['paid_provider_attempts'] == manifest['limits']['model_attempts'] == 0
    assert len(manifest['case_order']) == 12 and manifest['approval_status'] == 'pending'
    assert result == {'binding_matches': True, 'execution_authorized': False,
                      'invoice_ceiling_verified': False, 'identity_verified': False}


@pytest.mark.parametrize('changes', [
    {'cases': CASES[::-1]}, {'source_sha256': 'bad'}, {'dependency_sha256': 'A' * 64},
    {'output_dir': '/tmp/../tmp/run'}, {'output_dir': 'relative'},
    {'all_in_usd': None}, {'all_in_usd': 'NaN'}, {'all_in_usd': '-1.00'},
    {'all_in_usd': '1.001'}, {'retention_reference': ''},
])
def test_missing_or_invalid_contract_fields_refused(changes):
    with pytest.raises(ValueError): proposal(**changes)


@pytest.mark.parametrize('field,value', [('manifest_sha256', 'bad'), ('output_dir', '/tmp/other'),
                                         ('all_in_usd', '0.01'), ('execution_allowed', False),
                                         ('spending_authorized', False), ('reference', 'pending')])
def test_approval_must_match_every_bound_field(field, value):
    manifest = proposal(); approval = consent(manifest); approval[field] = value
    with pytest.raises(ValueError): matches_separate_approval(manifest, approval)


def test_changed_question_or_cost_invalidates_prior_binding():
    manifest = proposal(); approval = consent(manifest)
    cases = [dict(c) for c in CASES]; cases[0]['question'] += ' changed'
    with pytest.raises(ValueError): matches_separate_approval(proposal(cases=cases), approval)
    with pytest.raises(ValueError): matches_separate_approval(proposal(all_in_usd='0.01'), approval)
