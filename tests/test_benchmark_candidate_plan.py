"""Offline integrity of the approved policy and still-unadmitted candidate plan."""
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs' / 'benchmark_proposal_20261011'


def read(path):
    return json.loads(path.read_text())


def test_approved_policy_is_explicit_and_does_not_authorize_execution():
    policy = read(ROOT / 'validation' / 'benchmark_classification_policy.v1.json')
    assert policy['status'] == 'approved_by_user'
    assert policy['classification_as_of'] == '2026-10-09'
    assert policy['currency'] == 'USD'
    assert policy['basis'] == 'total_company_common_equity_value'
    assert policy['tiers'] == {
        'large': {'min_inclusive_usd': 10_000_000_000},
        'mid': {'min_inclusive_usd': 2_000_000_000, 'max_exclusive_usd': 10_000_000_000},
        'small_micro': {'min_exclusive_usd': 0, 'max_exclusive_usd': 2_000_000_000},
    }
    assert policy['execution_authorized'] is False


def test_candidate_allocation_and_company_keys_are_unique():
    rows = read(DOCS / 'candidate_plan.json')['candidates']
    assert len(rows) == len({r['ticker_candidate'] for r in rows}) == 100
    assert len({r['current_primary_identity']['deduplication_key'] for r in rows}) == 100
    assert Counter(r['allocation_slot'] for r in rows) == {
        'large': 30, 'mid': 30, 'small_micro': 30, 'extra': 10,
    }
    for row in rows:
        value = row['market_cap_observation']['normalized_rounded_usd']
        tier = 'large' if value >= 10_000_000_000 else 'mid' if value >= 2_000_000_000 else 'small_micro'
        assert value > 0 and row['proposed_size_tier'] == tier


def test_holdout_membership_and_unknown_external_exposure_are_preserved():
    plan = read(DOCS / 'candidate_plan.json')
    expected = set('AON AJG DTE PCAR ODFL VTR ENS OGS KBR AVT VNT RHI BKH HBB VLGEA SENEA ANGO UTMD USNA MTRX'.split())
    assert set(plan['reserved_holdout']) == expected
    assert {r['ticker_candidate'] for r in plan['candidates'] if r['reserved_holdout']} == expected
    assert plan['user_exposure_statement']['verified_unseen'] is False
    assert plan['user_exposure_statement']['holdout_membership_changed'] is False
    for row in plan['candidates']:
        if row['reserved_holdout']:
            assert 'external_prior_exposure_unknown' in row['holdout_exposure_status']


def test_primary_identity_evidence_joins_without_duplicate_companies():
    plan = read(DOCS / 'candidate_plan.json')
    for candidate in plan['candidates']:
        observed = []
        for ref in candidate['current_primary_identity']['evidence_refs']:
            rows = read(DOCS / ref)['rows']
            matches = [r for r in rows if r.get('ticker_candidate', r.get('ticker')) == candidate['ticker_candidate']]
            assert len(matches) == 1
            row = matches[0]
            observed.append(row.get('cik', row.get('current_identity', {}).get('cik')))
        assert observed and len(set(observed)) == 1
        assert candidate['current_primary_identity']['deduplication_key'] == 'SEC_CIK:' + observed[0]
    etsy = next(r for r in read(DOCS / 'reconciliation' / 'domestic_identity_a.json')['rows']
                if r['ticker_candidate'] == 'ETSY')
    assert etsy['exchange_observed'] == etsy['exchange_source_conflict']['sec_mapping_exchange'] == 'Nasdaq'
    assert etsy['proposed_exchange_from_dated_issuer_evidence'] == 'NYSE'


def test_conflicting_values_cannot_be_selected_or_admitted():
    plan = read(DOCS / 'candidate_plan.json')
    caps = read(DOCS / 'reconciliation' / 'cap_value_review.json')['rows']
    assert len(caps) == 100
    assert Counter(r['cap_decision'] for r in caps) == {
        'equal_displayed_values': 55, 'conflict_unresolved': 26,
        'compatible_display_rounding_only': 19,
    }
    candidates = {r['ticker_candidate']: r for r in plan['candidates']}
    assert set(candidates) == {r['ticker'] for r in caps}
    for row in caps:
        assert row['summary_as_of'] == row['historical_row_as_of'] == '2026-10-09'
        different = row['summary']['normalized_usd'] != row['historical_row']['normalized_usd']
        assert row['conflict_unresolved'] is different
        if different:
            assert row['selected_value_usd'] is None
            assert candidates[row['ticker']]['admission_review']['company_admitted'] is False
        assert row['eligible_to_execute'] is False


def test_canonical_registry_is_preserved_and_full_cohort_is_blocked():
    decision = read(DOCS / 'canonical_setup_decision.json')
    assert decision['active_registry_changed'] is False
    assert decision['individual_admissions'] == 0
    assert decision['full_cohort_admission_allowed'] is False
    assert decision['execution_authorized'] is False
    assert len(set(decision['cap_conflict_blocked_tickers'])) == 45
    actual = hashlib.sha256((ROOT / decision['active_registry']).read_bytes()).hexdigest()
    assert actual == decision['active_registry_sha256']
