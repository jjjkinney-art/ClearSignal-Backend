"""Offline adversarial checks against copied proposal evidence."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('candidate_admission', ROOT / 'scripts/benchmark_candidate_admission.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def proposal(tmp_path):
    source = ROOT / 'docs/benchmark_proposal_20261011'
    target = tmp_path / 'proposal'
    (target / 'reconciliation').mkdir(parents=True)
    shutil.copyfile(source / 'candidate_plan.json', target / 'candidate_plan.json')
    names = ['metadata_admission_audit.json', 'classification_domestic_adjudication.json',
             'international_classification_admission.json', 'cap_value_review.json',
             'approved_classification_only.json', 'approved_historical_precedence.json']
    names += [p.name for p in (source / 'reconciliation').glob('metadata_completion_batch*.json')]
    for name in names:
        shutil.copyfile(source / 'reconciliation' / name, target / 'reconciliation' / name)
    return target


def change(proposal, name, edit):
    path = proposal / name
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def row(report, ticker):
    return next(r for r in report['rows'] if r['ticker'] == ticker)


def test_missing_jout_adjudication_is_not_permission(proposal):
    change(proposal, 'reconciliation/classification_domestic_adjudication.json',
           lambda d: d.update(rows=[r for r in d['rows'] if r['ticker'] != 'JOUT']))
    report = module.build_readiness(proposal)
    assert row(report, 'JOUT')['classification_eligible'] is False
    assert row(report, 'JOUT')['company_admitted'] is False
    assert report['registry_activation_allowed'] is False


def test_truthy_unresolved_metadata_is_blocked(proposal):
    def edit(d):
        r = next(r for r in d['rows'] if r['ticker'] == 'AON')
        for name in ('domicile', 'reporting_basis', 'sector'):
            r['registry_metadata_adjudicated'][name]['status'] = 'unresolved'
    change(proposal, 'reconciliation/metadata_completion_batch0.json', edit)
    r = row(module.build_readiness(proposal), 'AON')
    assert not r['company_admitted']
    assert len(r['metadata_blockers']) == 3


def test_unknown_source_identifier_is_blocked(proposal):
    def edit(d):
        r = next(r for r in d['rows'] if r['ticker'] == 'AON')
        r['registry_metadata_adjudicated']['domicile']['source_ref'] = 'NOT_A_SOURCE'
    change(proposal, 'reconciliation/metadata_completion_batch0.json', edit)
    assert 'invalid_or_unresolved_domicile' in row(module.build_readiness(proposal), 'AON')['metadata_blockers']


def test_holdout_swap_detected_even_at_twenty(proposal):
    def edit(d):
        for c in d['candidates']:
            if c['ticker_candidate'] == 'AON': c['reserved_holdout'] = False
            if c['ticker_candidate'] == 'AAPL': c['reserved_holdout'] = True
        d['reserved_holdout'] = ['AAPL' if t == 'AON' else t for t in d['reserved_holdout']]
    change(proposal, 'candidate_plan.json', edit)
    report = module.build_readiness(proposal)
    assert 'frozen_holdout_membership_changed' in report['cohort_blockers']
    assert report['holdout_membership_changed'] is True
    assert not report['registry_activation_allowed']


def test_duplicate_company_and_duplicate_ticker_fail_closed(proposal):
    def edit(d):
        d['rows'][1]['issuer_deduplication_key'] = d['rows'][0]['issuer_deduplication_key']
    change(proposal, 'reconciliation/metadata_admission_audit.json', edit)
    report = module.build_readiness(proposal)
    assert 'requires_100_unique_CIKs' in report['cohort_blockers']
    assert not report['registry_activation_allowed']
    change(proposal, 'candidate_plan.json', lambda d: d['candidates'].append(d['candidates'][0]))
    with pytest.raises(ValueError, match='Duplicate'):
        module.build_readiness(proposal)


def test_approval_scope_cannot_broaden(proposal):
    change(proposal, 'reconciliation/approved_classification_only.json',
           lambda d: d['scope_tickers'].append('AAPL'))
    with pytest.raises(ValueError, match='scope'):
        module.build_readiness(proposal)


def test_build_is_read_only_and_preserves_exact_value_limits(proposal):
    before = {str(p): p.read_bytes() for p in proposal.rglob('*.json')}
    report = module.build_readiness(proposal)
    assert not report['execution_authorized']
    assert all(r['exact_cap_verified_for_answers'] is False for r in report['rows'])
    assert before == {str(p): p.read_bytes() for p in proposal.rglob('*.json')}
