"""Approved replacement and offline v2 cohort integration; no providers."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts.benchmark_cohort_setup import build_setup, validate_setup
from scripts.benchmark_candidate_admission import HOLDOUTS
from validation.benchmark_registry import load_registry, load_query_fixtures, audit_registry
from validation.company_quality_matrix import build_matrix, QUESTION_FAMILIES
from validation.company_quality_review import reconcile_captures

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / 'docs/benchmark_proposal_20261011'

def read(path):
    return json.loads(path.read_text())

@pytest.fixture
def proposal(tmp_path):
    target = tmp_path / 'proposal'
    shutil.copytree(PROPOSAL, target)
    return target

def alter(path, fn):
    data = read(path)
    fn(data)
    path.write_text(json.dumps(data))

def test_canonical_setup_reproduces_and_passes_strict_coverage():
    built = build_setup(PROPOSAL)
    assert built['registry'] == read(ROOT / 'validation/issuer_registry.v2.json')
    assert built['manifest'] == read(ROOT / 'validation/fixtures.v2.json')
    assert built['finalized_cohort'] == read(PROPOSAL / 'reconciliation/finalized_cohort.json')
    validate_setup(built['registry'], built['manifest'])
    registry = load_registry(ROOT / 'validation/issuer_registry.v2.json')
    fixtures = load_query_fixtures(ROOT / 'validation/fixtures.v2.json')
    report = audit_registry(registry, fixtures)
    assert report.launch_coverage_ready
    assert report.issuer_count == 100 and report.fixture_count == 600
    assert dict(report.market_cap_counts) == {'mega_large':40,'mid':30,'small_micro':30,'unknown':0}
    assert report.sector_count >= 10 and report.complexity_tag_count >= 20
    assert 'JOUT' not in registry.by_ticker() and 'NPK' in registry.by_ticker()

@pytest.mark.parametrize('field,value', [('status','pending'),('from_ticker','AON'),('to_ticker','OTHER'),('pool','holdout'),('execution_authorized',True),('holdout_membership_change_authorized',True)])
def test_replacement_scope_is_exact(proposal, field, value):
    alter(proposal / 'reconciliation/approved_npk_replacement.json', lambda d:d.update({field:value}))
    with pytest.raises(ValueError):
        build_setup(proposal)

@pytest.mark.parametrize('field,value', [('summary_normalized_usd',2000000000),('history_normalized_usd',1090000000),('source_as_of','2026-10-08'),('currency','EUR')])
def test_replacement_classification_fails_closed(proposal, field, value):
    alter(proposal / 'reconciliation/replacement_candidate_review.json', lambda d:d['market_cap'].update({field:value}))
    with pytest.raises(ValueError):
        build_setup(proposal)

@pytest.mark.parametrize('field', ['domicile','reporting_basis','sector','source_url'])
def test_replacement_required_metadata_cannot_disappear(proposal, field):
    alter(proposal / 'reconciliation/replacement_candidate_review.json', lambda d:d['registry_metadata_proposal'].update({field:''}))
    with pytest.raises(ValueError):
        build_setup(proposal)

def test_existing_unresolved_metadata_blocks_new_registry(proposal):
    def edit(d):
        r=next(r for r in d['rows'] if r['ticker']=='AON')
        r['registry_metadata_adjudicated']['domicile']['status']='unresolved'
    alter(proposal / 'reconciliation/metadata_completion_batch0.json', edit)
    with pytest.raises(ValueError):
        build_setup(proposal)

def test_missing_duplicate_or_changed_fixture_is_rejected():
    built=build_setup(PROPOSAL)
    for mutation in ('missing','duplicate','question'):
        fixture=copy.deepcopy(built['manifest'])
        if mutation=='missing': fixture['fixtures'].pop()
        elif mutation=='duplicate': fixture['fixtures'][-1]=fixture['fixtures'][0]
        else: fixture['fixtures'][0]['question']='Invent a figure'
        with pytest.raises(ValueError): validate_setup(built['registry'],fixture)

def test_actual_capture_matrix_has_600_uncaptured_pending_cases():
    registry=load_registry(ROOT / 'validation/issuer_registry.v2.json')
    manifest=read(ROOT / 'validation/company_quality_manifest.v2.json')
    assert manifest==build_matrix(registry=registry)
    assert len({(r['issuer_id'],r['question_id']) for r in manifest['cases']})==600
    assert set(manifest['question_families'])==set(QUESTION_FAMILIES)
    review=reconcile_captures(manifest,[],registry=registry)
    assert review['capture_counts']=={'missing':600}
    assert review['quality_status']=='not_adjudicated' and review['launch_ready'] is False
    assert all(r['factual_review_status']=='pending' and 'response' not in r for r in review['cases'])

def test_artifact_hashes_and_reserved_partition():
    metadata=read(ROOT / 'validation/company_quality_manifest.v2.metadata.json')
    assert metadata['execution_authorized'] is False and metadata['launch_ready'] is False
    assert set(metadata['reserved_holdouts'])==HOLDOUTS
    assert len(metadata['development_issuers'])==80
    assert not set(metadata['development_issuers']) & HOLDOUTS
    assert metadata['development_case_count']==480 and metadata['holdout_case_count']==120
    for path,digest in metadata['artifact_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    assert metadata['external_prior_exposure']=='unknown'
    assert metadata['captures_executed']==0


@pytest.mark.parametrize('mutation', ['identity','holdout','tier','execution','target','capture','nested_capture'])
def test_registry_and_manifest_changes_are_rejected(mutation):
    built=build_setup(PROPOSAL)
    r,m=built['registry'],built['manifest']
    if mutation=='identity': r['issuers'][1]['issuer_deduplication_key']=r['issuers'][0]['issuer_deduplication_key']
    elif mutation=='holdout': next(x for x in r['issuers'] if x['ticker']=='AON')['reserved_holdout']=False
    elif mutation=='tier': r['issuers'][0]['market_cap_tier']='unknown'
    elif mutation=='execution': m['execution_authorized']=True
    elif mutation=='target': r['coverage_targets']['issuer_count']=99
    elif mutation=='capture': m['responses']=['fabricated capture']
    else: r['issuers'][0]['admission_evidence']['response']='fabricated capture'
    with pytest.raises(ValueError): validate_setup(r,m)


def test_canonical_matrix_tampering_rejected():
    from validation.intelligence_benchmark import BenchmarkContractError
    registry=load_registry(ROOT / 'validation/issuer_registry.v2.json')
    manifest=read(ROOT / 'validation/company_quality_manifest.v2.json')
    manifest['cases'][0]['question']='altered question'
    with pytest.raises(BenchmarkContractError):
        reconcile_captures(manifest, [], registry=registry)


def test_plan_cli_cannot_call_capture(monkeypatch, tmp_path):
    from scripts import benchmark_company_quality as cli
    def forbidden(**kwargs): raise AssertionError('capture path reached')
    monkeypatch.setattr(cli,'capture_matrix',forbidden)
    output=tmp_path/'plan.json'
    assert cli.main(['--registry',str(ROOT/'validation/issuer_registry.v2.json'),'--plan','--output',str(output)])==0
    assert read(output)==read(ROOT/'validation/company_quality_manifest.v2.json')


def test_current_canonical_decision_and_archived_jout():
    current=read(PROPOSAL/'canonical_setup_decision.json')
    assert current['individual_admissions']==100 and current['full_cohort_admission_allowed'] is True
    assert current['active_registry']=='validation/issuer_registry.v2.json'
    assert current['execution_authorized'] is False
    assert hashlib.sha256((ROOT/current['active_registry']).read_bytes()).hexdigest()==current['active_registry_sha256']
    archived=read(PROPOSAL/'reconciliation/classification_setup_readiness.json')
    assert next(r for r in archived['rows'] if r['ticker']=='JOUT')['company_admitted'] is False
    assert 'JOUT' in {r['ticker_candidate'] for r in read(PROPOSAL/'candidate_plan.json')['candidates']}
