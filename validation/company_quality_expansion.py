"""Offline expansion proposal from the existing frozen setup; never execution authority."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from .benchmark_registry import load_registry
from .company_quality_matrix import build_matrix
from .intelligence_benchmark import BenchmarkContractError, content_hash
from .pilot_preflight import FROZEN_SETUP_SHA256, SETUP_DIR


def build_expansion_plan(*, setup_dir=SETUP_DIR):
    """Preserve membership, questions and reservations; propose review stages only."""
    setup_dir = Path(setup_dir)
    documents, hashes = {}, {}
    for name, expected in FROZEN_SETUP_SHA256.items():
        path = setup_dir / name
        if path.is_symlink():
            raise BenchmarkContractError('frozen expansion setup must not be symlinked')
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        if hashes[name] != expected:
            raise BenchmarkContractError('frozen expansion setup changed; separate review required')
        documents[name] = json.loads(raw)
    registry_data = documents['issuer_registry.v2.json']
    metadata = documents['company_quality_manifest.v2.metadata.json']
    matrix = documents['company_quality_manifest.v2.json']
    registry = load_registry(setup_dir / 'issuer_registry.v2.json')
    if content_hash(build_matrix(registry=registry)) != content_hash(matrix):
        raise BenchmarkContractError('canonical question builder differs from frozen setup')
    fixture_name = 'fixtures.v2.json'
    fixture_path = setup_dir / fixture_name
    if fixture_path.is_symlink():
        raise BenchmarkContractError('frozen question fixtures must not be symlinked')
    raw = fixture_path.read_bytes()
    hashes[fixture_name] = hashlib.sha256(raw).hexdigest()
    if hashes[fixture_name] != metadata['artifact_sha256']['validation/' + fixture_name]:
        raise BenchmarkContractError('frozen question fixtures changed')
    development = set(metadata['development_issuers'])
    holdouts = set(metadata['reserved_holdouts'])
    rows = registry_data['issuers']
    if (development & holdouts or development | holdouts != {r['ticker'] for r in rows}
            or len(development) != 80 or len(holdouts) != 20
            or {r['ticker'] for r in rows if r['reserved_holdout']} != holdouts):
        raise BenchmarkContractError('frozen development/holdout partition differs')
    families = matrix['question_families']

    def partition(names):
        selected = [r for r in rows if r['ticker'] in names]
        return dict(issuer_count=len(selected), case_count=len(selected) * len(families),
                    by_market_cap=dict(sorted(Counter(r['market_cap_tier'] for r in selected).items())))

    return {
        'schema_version': 1, 'artifact_type': 'offline_company_quality_expansion_proposal',
        'setup_file_sha256': hashes, 'registry_sha256': matrix['registry_sha256'],
        'matrix_sha256': matrix['matrix_sha256'], 'classification_as_of': matrix['classification_as_of'],
        'classification_scope': 'frozen dated cohort labels; not current market values',
        'question_families': families, 'total': partition(development | holdouts),
        'development': partition(development), 'reserved_holdout': partition(holdouts),
        'reservation_sha256': content_hash(metadata['reserved_holdouts']),
        'development_issuers': metadata['development_issuers'],
        'external_prior_holdout_exposure': 'unknown',
        'stages': [
            {'id': 'offline_pilot_quality', 'case_count': 6,
             'scope': 'existing ASML/ACHC/NPK core_thesis and decision_threshold answers',
             'requirement': 'preserve execution success separately from question completeness and independent review'},
            {'id': 'development_core_and_threshold', 'issuer_count': 80, 'case_count': 160,
             'families': ['core_thesis', 'decision_threshold'],
             'requirement': 'fix demonstrated shared completeness gaps before approving broader capture'},
            {'id': 'development_all_families', 'issuer_count': 80, 'case_count': 480,
             'requirement': 'full six-family development matrix; prior 160 are a subset, not 160 extra passes'},
            {'id': 'reserved_holdout', 'issuer_count': 20, 'case_count': 120,
             'requirement': 'freeze product, prompts and grading references before separately approved holdout execution; no tuning on its answers'},
            {'id': 'signed_in_acceptance',
             'requirement': 'separate account isolation, personalization, saved thesis, save/reopen, latency and freshness acceptance'},
        ],
        'acceptance_targets': {
            'useful_cited_answer_minimum_by_market_cap': '0.90',
            'useful_cited_answer_minimum_by_question_family': '0.90',
            'material_numerical_accuracy_minimum': '0.95',
            'material_claim_source_binding_minimum': '1.00',
            'fabricated_material_sources_allowed': 0,
            'issuer_period_contamination_allowed': 0,
            'account_leakage_allowed': 0,
            'issuer_level_stop_ship_failures_allowed': 0,
            'denominator': 'all frozen scheduled cases; failed, missing, gap-only and unreviewed cases cannot count as useful-answer passes',
            'partial_answer_rule': 'partial status neither passes nor fails usefulness automatically; review the exact question and unresolved requested parts',
            'independent_review': 'primary-document factual/citation adjudication plus existing two-reviewer blind analytical rubric and disagreement resolution',
        },
        'execution_readiness': 'blocked_pending_reviewed_executor_and_separate_approval',
        'execution_authorized': False, 'spending_authorized': False,
        'production_activation_authorized': False, 'captures_executed_by_this_plan': 0,
        'quality_status': 'not_adjudicated', 'quality_pass_rate': None, 'launch_ready': False,
        'blocking_requirements': [
            'A 39-GET six-case approval does not cover 80 or 100 companies; all eleven live approvals are consumed.',
            'Audit actual route/stage inventory for every proposed family and source complexity before setting fixed physical quotas.',
            'Review code, dependencies, configuration, retention, deadlines and spending terms for a new bounded executor/package.',
            'Do not assume source-only core/threshold behavior validates model-backed routes or the other four question families.',
            'No finite benchmark proves every public company works; publish verified market/source scope and gaps.',
        ],
    }
