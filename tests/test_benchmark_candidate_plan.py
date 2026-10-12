"""Offline integrity of the approved policy and still-unadmitted candidate plan."""
import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
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


def test_only_explicitly_approved_conflicting_values_can_be_selected():
    plan = read(DOCS / 'candidate_plan.json')
    caps = read(DOCS / 'reconciliation' / 'cap_value_review.json')['rows']
    assert len(caps) == 100
    assert Counter(r['cap_decision'] for r in caps) == {
        'equal_displayed_values': 55, 'conflict_unresolved': 26,
        'approved_historical_row_precedence': 19,
    }
    candidates = {r['ticker_candidate']: r for r in plan['candidates']}
    assert set(candidates) == {r['ticker'] for r in caps}
    for row in caps:
        assert row['summary_as_of'] == row['historical_row_as_of'] == '2026-10-09'
        different = row['summary']['normalized_usd'] != row['historical_row']['normalized_usd']
        assert row['conflict_unresolved'] is different
        if row['cap_decision'] == 'approved_historical_row_precedence':
            assert row['selected_value_usd'] == row['historical_row']['normalized_usd']
            assert row['discrepancy_cause'] == 'unexplained'
            selection = candidates[row['ticker']]['classification_cap_selection']
            assert selection['normalized_usd'] == int(row['selected_value_usd'])
            assert candidates[row['ticker']]['market_cap_observation']['normalized_rounded_usd'] == int(row['summary']['normalized_usd'])
        elif different:
            assert row['selected_value_usd'] is None
        readiness = read(DOCS / 'reconciliation' / 'classification_setup_readiness.json')
        admitted = {r['ticker']: r['company_admitted'] for r in readiness['rows']}
        assert candidates[row['ticker']]['admission_review']['company_admitted'] is admitted[row['ticker']]
        assert row['eligible_to_execute'] is False


def test_archived_decision_preserves_pre_replacement_registry_and_block():
    decision = read(DOCS / 'reconciliation' / 'canonical_setup_decision_before_npk.json')
    assert decision['active_registry_changed'] is False
    readiness = read(DOCS / 'reconciliation' / 'classification_setup_readiness.json')
    assert decision['individual_admissions'] == readiness['summary']['company_admitted_count']
    assert decision['individual_admissions'] < 100
    assert decision['full_cohort_admission_allowed'] is False
    assert decision['execution_authorized'] is False
    assert len(set(decision['cap_conflict_blocked_tickers'])) == 26
    actual = hashlib.sha256((ROOT / decision['active_registry']).read_bytes()).hexdigest()
    assert actual == decision['active_registry_sha256']


def test_followup_covers_every_difference_and_applies_only_approved_scope():
    directory = DOCS / 'reconciliation'
    summary = read(directory / 'followup_admission_summary.json')
    covered = []
    for filename in summary['evidence_files']:
        evidence = read(directory / filename)
        covered.extend(r['ticker'] for r in evidence.get('rows', [evidence]))
    conflicts = {r['ticker'] for r in read(directory / 'cap_value_review.json')['rows']
                 if r['conflict_unresolved']}
    assert len(covered) == len(set(covered)) == 45
    assert set(covered) == conflicts == {r['ticker'] for r in summary['rows']}
    tiny = read(directory / 'rounding_followup.json')['rows']
    choice = summary['smallest_user_choice']
    assert len(tiny) == 19
    assert set(choice['scope_tickers']) == {r['ticker'] for r in tiny}
    assert choice['status'] == 'approved_and_applied'
    assert read(DOCS / 'canonical_setup_decision.json')['source_precedence_proposal_activated'] is True
    for row in tiny:
        assert row['source_confirmed_rounding'] is False
        assert row['selected_value_usd'] == row['history_usd']
        admitted = {r['ticker']: r['company_admitted'] for r in read(directory / 'classification_setup_readiness.json')['rows']}
        assert row['admitted'] is admitted[row['ticker']]
    for row in summary['rows']:
        assert row['tier_crossing'] is False
        expected = abs(Decimal(row['summary_usd']) - Decimal(row['historical_usd']))
        assert Decimal(row['absolute_difference_usd']) == expected
        percent = expected / Decimal(row['summary_usd']) * 100
        assert abs(Decimal(row['absolute_difference_percent_of_summary']) - percent) < Decimal('1e-24')


def test_primary_share_estimates_preserve_class_arithmetic_and_date_limits():
    rows = read(DOCS / 'reconciliation' / 'domestic_material_cap_followup.json')['rows']
    for row in rows:
        counts = row['primary_shares']['share_counts']
        prices = row['price']['prices_by_class']
        if row['ticker'] == 'JOUT':
            # Unquoted B uses an explicitly conditional A-price proxy.
            assert 'Class B' not in prices
            actual = sum(Decimal(v) for v in counts.values()) * Decimal(prices['Class A'])
            assert any('proxy' in a.lower() for a in row['calculation']['assumptions'])
        else:
            actual = sum(Decimal(count) * Decimal(prices[share_class])
                         for share_class, count in counts.items())
        assert actual == Decimal(row['calculation']['conditional_reported_share_value_usd'])
        age = date.fromisoformat(row['price']['date']) - date.fromisoformat(row['primary_shares']['observation_date'])
        assert age.days == row['calculation']['shares_older_than_price_days'] > 0
        assert row['exact_oct9_verified'] is False
        assert row['admission_changed'] is False
        assert row['execution_enabled'] is False
    remaining = read(DOCS / 'reconciliation' / 'domestic_remaining_cap_followup.json')['rows']
    estimates = [r for r in remaining if r.get('provisional_estimate')]
    assert len(estimates) == 7
    for row in estimates:
        estimate = row['provisional_estimate']
        actual = Decimal(estimate['observed_primary_shares']) * Decimal(row['price_observation']['close_usd'])
        assert actual == Decimal(estimate['calculated_usd'])
        assert estimate['share_measurement_date'] < row['price_observation']['date']


def test_tday_and_boundary_check_use_regular_close_without_admission():
    directory = DOCS / 'reconciliation'
    tday = read(directory / 'tday_cap_followup.json')
    sources = {r['id']: r for r in tday['sources']}
    product = Decimal(sources['primary_10q']['common_shares_outstanding']) * Decimal(sources['dated_price']['close_usd'])
    assert product == Decimal(tday['calculations']['primary_reported_shares_times_Oct9_close']['result_usd'])
    assert tday['cap_conflict_resolved'] is False
    assert tday['company_admitted'] is False
    assert tday['execution_authorized'] is False
    grc = read(directory / 'grc_boundary_followup.json')
    product = Decimal(grc['common_shares_outstanding']) * Decimal(grc['regular_close_usd'])
    assert product == Decimal(grc['calculation']['usd'])
    assert Decimal(grc['approved_mid_boundary_usd']) - product == Decimal(grc['calculated_distance_to_boundary_usd'])
    assert grc['calculation']['share_count_date_is_price_date'] is False
    assert grc['canonical_admitted'] is False
    assert grc['execution_authorized'] is False


def test_visa_class_equivalents_do_not_become_exact_cap_or_admission():
    rows = read(DOCS / 'reconciliation' / 'domestic_remaining_cap_followup.json')['rows']
    visa = next(r for r in rows if r['ticker'] == 'V')
    estimate = visa['class_equivalent_estimate']
    equivalents = sum(Decimal(count) * Decimal(estimate['class_A_equivalent_ratios'][kind])
                      for kind, count in estimate['counts'].items())
    assert equivalents == Decimal(estimate['class_A_equivalents'])
    assert equivalents * Decimal(estimate['class_A_close_usd']) == Decimal(estimate['total_proxy_usd'])
    assert estimate['convention_approved'] is False
    assert estimate['exact_oct9_cap_verified'] is False
    assert visa['selected_value_usd'] is None
    assert visa['eligible_to_execute'] is False


def test_approved_source_rule_is_exactly_nineteen_and_preserves_other_gates():
    expected = set('RGR SWBI BGS HBB VLGEA CAL ANGO UTMD USNA MLR MTRX PLOW SGC NATH RELL ACNB CCBG NGS FRPH'.split())
    rule = read(DOCS / 'reconciliation' / 'approved_historical_precedence.json')
    assert set(rule['scope_tickers']) == expected
    assert rule['status'] == 'approved_and_applied'
    assert rule['approval_evidence']['user_answer'] == 'yes'
    for field in ('source_confirmed_rounding', 'general_tolerance_authorized',
                  'broader_classification_only_rule_approved',
                  'automatic_company_admission', 'execution_authorized'):
        assert rule[field] is False
    cap = read(DOCS / 'reconciliation' / 'cap_value_review.json')
    selected = {r['ticker'] for r in cap['rows'] if r['cap_decision'] == 'approved_historical_row_precedence'}
    assert selected == expected
    blocked = {r['ticker'] for r in cap['rows'] if r['cap_decision'] == 'conflict_unresolved'}
    decision = read(DOCS / 'canonical_setup_decision.json')
    assert blocked == set(decision['cap_conflict_blocked_tickers'])
    assert len(blocked) == 26 and not blocked & expected
    assert decision['broader_classification_only_rule_approved'] is True
