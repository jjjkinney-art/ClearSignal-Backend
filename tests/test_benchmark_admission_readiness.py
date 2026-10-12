"""Offline admission gates: classification approval is not blanket admission."""
import json
from collections import Counter
from pathlib import Path

from validation.benchmark_registry import audit_registry, load_query_fixtures, load_registry

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs' / 'benchmark_proposal_20261011'
RECONCILIATION = DOCS / 'reconciliation'
TIERS = ('large', 'mid', 'small_micro')
CLASSIFICATION_ONLY = set(
    'NVDA ASML V LLY AJG VTR PG NEE NVS SHW RHI WDFC GEF NOG AIN '
    'TDAY NNBR JOUT PETS SAP SONY TM RY BHP UL EQNR'.split()
)
HOLDOUT = set(
    'AON AJG DTE PCAR ODFL VTR ENS OGS KBR AVT VNT RHI BKH HBB '
    'VLGEA SENEA ANGO UTMD USNA MTRX'.split()
)


def read(path):
    return json.loads(path.read_text())


def test_admission_readiness_joins_candidates_and_preserves_all_gates():
    report = read(RECONCILIATION / 'classification_setup_readiness.json')
    candidates = read(DOCS / 'candidate_plan.json')['candidates']
    by_ticker = {row['ticker_candidate']: row for row in candidates}
    rows = report['rows']
    assert len(rows) == len({r['ticker'] for r in rows}) == 100
    assert {r['ticker'] for r in rows} == set(by_ticker)
    for row in rows:
        assert row['proposed_size_tier'] == by_ticker[row['ticker']]['proposed_size_tier']
        assert row['proposed_size_tier'] in TIERS
        for field in ('classification_eligible', 'identity_class_eligible',
                      'company_admitted', 'exact_cap_verified_for_answers'):
            assert type(row[field]) is bool
        assert isinstance(row['metadata_blockers'], list)
        assert all(isinstance(blocker, str) and blocker.strip()
                   for blocker in row['metadata_blockers'])
        assert row['company_admitted'] is (
            row['classification_eligible'] and row['identity_class_eligible']
            and not row['metadata_blockers']
        )
        assert row['exact_cap_verified_for_answers'] is False
    admitted = [r for r in rows if r['company_admitted']]
    counts = Counter(r['proposed_size_tier'] for r in admitted)
    summary = report['summary']
    assert summary['classification_eligible_count'] == sum(r['classification_eligible'] for r in rows)
    assert summary['company_admitted_count'] == len(admitted)
    assert summary['admitted_tier_counts'] == {tier: counts[tier] for tier in TIERS}
    assert summary['issuer_shortfall'] == max(0, 100 - len(admitted))
    assert summary['minimum_tier_shortfalls'] == {
        tier: max(0, 30 - counts[tier]) for tier in TIERS
    }
    assert type(report['registry_activation_allowed']) is bool
    deduplication_keys = [r['issuer_deduplication_key'] for r in rows]
    assert all(isinstance(key, str) and key.strip() for key in deduplication_keys)
    assert len(set(deduplication_keys)) == 100
    sectors = {r['metadata_fields']['sector']['value'] for r in admitted}
    tags = {tag for r in admitted
            for tag in r['metadata_fields']['complexity_tags']['value']}
    assert summary['admitted_sector_count'] == len(sectors)
    assert summary['admitted_distinct_complexity_tags'] == len(tags)
    if (len(admitted) < 100 or any(counts[tier] < 30 for tier in TIERS)
            or len(sectors) < 10 or len(tags) < 20):
        assert report['registry_activation_allowed'] is False
    assert report['execution_authorized'] is False
    assert report['holdout_membership_changed'] is False


def test_classification_only_approval_cannot_select_disputed_exact_values():
    rule = read(RECONCILIATION / 'approved_classification_only.json')
    assert len(rule['scope_tickers']) == len(CLASSIFICATION_ONLY) == 26
    assert set(rule['scope_tickers']) == CLASSIFICATION_ONLY
    assert rule['status'] == 'approved_by_user'
    for field in ('exact_market_values_verified', 'use_as_verified_answer_valuation_data',
                  'automatic_company_admission', 'holdout_membership_change_authorized',
                  'general_numeric_tolerance_authorized', 'execution_authorized'):
        assert rule[field] is False
    caps = {r['ticker']: r for r in read(RECONCILIATION / 'cap_value_review.json')['rows']}
    candidates = {r['ticker_candidate']: r for r in read(DOCS / 'candidate_plan.json')['candidates']}
    for ticker in CLASSIFICATION_ONLY:
        row = caps[ticker]
        assert row['summary']['normalized_usd'] != row['historical_row']['normalized_usd']
        assert row['conflict_unresolved'] is True
        assert row['selected_value_usd'] is None
        assert row['eligible_to_execute'] is False
        selection = candidates[ticker].get('classification_cap_selection')
        assert selection is None or selection.get('normalized_usd') is None


def test_holdouts_and_external_exposure_are_preserved():
    plan = read(DOCS / 'candidate_plan.json')
    assert len(plan['reserved_holdout']) == 20
    assert set(plan['reserved_holdout']) == HOLDOUT
    assert {r['ticker_candidate'] for r in plan['candidates'] if r['reserved_holdout']} == HOLDOUT
    assert plan['user_exposure_statement']['verified_unseen'] is False
    assert plan['user_exposure_statement']['holdout_membership_changed'] is False
    assert all('external_prior_exposure_unknown' in r['holdout_exposure_status']
               for r in plan['candidates'] if r['reserved_holdout'])


def test_existing_registry_fixture_integration_remains_incomplete():
    registry = load_registry(ROOT / 'validation' / 'issuer_registry.v1.json')
    fixtures = load_query_fixtures(ROOT / 'validation' / 'fixtures.json')
    report = audit_registry(registry, fixtures)
    assert registry.registry_version == 1
    assert registry.classification_as_of == '2026-09-29'
    assert report.fixture_count == 54
    assert report.issuer_count == 18
    assert report.integrity_passed is True
    assert report.launch_coverage_ready is False
    assert report.target_deficits


def test_international_classification_uses_dated_net_shares_and_adr_ratio():
    from decimal import Decimal
    evidence = read(RECONCILIATION / 'international_classification_admission.json')
    rows = evidence['rows']
    assert {r['ticker'] for r in rows} == set('ASML NVS SAP SONY TM RY BHP UL'.split())
    for row in rows:
        assert row['answer_valuation_verified'] is False
        assert row['exact_oct9_cap_verified'] is False
        if row['admitted_tier_evidence']:
            assert row['primary_count_date'] <= '2026-10-09'
            assert row['primary_publication_date'] <= '2026-10-09'
            assert row['price_date'] == '2026-10-09'
            value = (Decimal(row['net_common_count']) /
                     Decimal(row['underlying_common_per_us_security']) *
                     Decimal(row['price_usd']))
            assert value == Decimal(row['calculation']['result_usd'])
            assert value >= 10_000_000_000 and row['tier'] == 'large'
        else:
            assert row['blocked_reason']


def test_jout_exclusion_and_replacement_preserve_holdouts_and_exact_values():
    evidence = read(RECONCILIATION / 'classification_domestic_adjudication.json')
    jout = next(r for r in evidence['rows'] if r['ticker'] == 'JOUT')
    assert jout['tier_eligible'] is False
    assert jout['blocked_reason']
    visa = next(r for r in evidence['rows'] if r['ticker'] == 'V')
    assert visa['tier_eligible'] is True and visa['tier'] == 'large'
    assert visa['verified_answer_market_cap_usd'] is None
    alternative = read(RECONCILIATION / 'replacement_candidate_review.json')
    assert alternative['ticker'] == 'NPK'
    assert alternative['proposed_replacement_for'] == 'JOUT'
    assert alternative['replacement_applied'] is False
    assert alternative['holdouts_changed'] is False
    assert alternative['execution_authorized'] is False
    cap = alternative['market_cap']
    assert cap['source_as_of'] == '2026-10-09'
    assert cap['summary_normalized_usd'] == cap['history_normalized_usd'] < 2_000_000_000
    assert cap['selected_exact_value_certified'] is False


def test_classification_readiness_matches_all_approved_source_adjudications():
    report = read(RECONCILIATION / 'classification_setup_readiness.json')
    readiness = {r['ticker']: r for r in report['rows']}
    domestic = read(RECONCILIATION / 'classification_domestic_adjudication.json')['rows']
    international = read(RECONCILIATION / 'international_classification_admission.json')['rows']
    source_rows = [(r, 'tier_eligible', 'classification_domestic_adjudication.json')
                   for r in domestic]
    source_rows += [(r, 'admitted_tier_evidence', 'international_classification_admission.json')
                    for r in international]
    assert len(source_rows) == len(CLASSIFICATION_ONLY)
    assert {r['ticker'] for r, _, _ in source_rows} == CLASSIFICATION_ONLY
    for source, eligible_field, artifact in source_rows:
        row = readiness[source['ticker']]
        assert type(source[eligible_field]) is bool
        assert row['classification_eligible'] is source[eligible_field]
        assert row['classification_evidence_ref'] == artifact + '#' + source['ticker']
        if source[eligible_field]:
            assert row['proposed_size_tier'] == source['tier']
