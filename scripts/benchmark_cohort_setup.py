"""Build an offline v2 cohort and fixtures; no captures or default-registry changes."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    from scripts.benchmark_candidate_admission import build_readiness, HOLDOUTS, is_url
except ModuleNotFoundError:
    from benchmark_candidate_admission import build_readiness, HOLDOUTS, is_url

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ('core_thesis', 'decision_threshold', 'structural_risk', 'financial_trends', 'operating_metrics', 'recent_developments')
TARGETS = {'issuer_count': 100, 'minimum_by_market_cap': {'mega_large': 30, 'mid': 30, 'small_micro': 30}, 'minimum_sector_count': 10, 'minimum_complexity_tag_count': 20}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def templates():
    """Read literal canonical templates without importing capture dependencies."""
    tree = ast.parse((ROOT / 'validation/company_quality_matrix.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'QUESTION_FAMILIES' for t in node.targets):
            value = ast.literal_eval(node.value)
            require(tuple(value) == FAMILIES, 'canonical question families changed')
            return value
    raise ValueError('canonical question templates missing')


def reject_capture_payload(value):
    if isinstance(value, dict):
        forbidden = {'response', 'responses', 'response_sha256', 'raw_response', 'answers', 'captures', 'results', 'source_snapshots', 'capture_hashes'}
        require(not forbidden.intersection(value), 'capture/result payload forbidden in offline setup')
        for child in value.values():
            reject_capture_payload(child)
    elif isinstance(value, list):
        for child in value:
            reject_capture_payload(child)


def validate_setup(registrydict, manifestdict):
    """Validate the offline fixture document, not a capture-run matrix."""
    r, m = registrydict, manifestdict
    reject_capture_payload(r)
    reject_capture_payload(m)
    require(set(m) == {'version', 'registry_version', 'artifact_type', 'question_families', 'fixtures', 'partition_counts', 'captures_executed', 'execution_authorized'}, 'unexpected fixture metadata or capture payload')
    require(set(r) == {'schema_version', 'registry_version', 'classification_as_of', 'coverage_targets', 'issuers', 'execution_authorized', 'exact_market_values_verified', 'external_prior_holdout_exposure', 'registry_default_changed'}, 'unexpected registry metadata or capture payload')
    require(r.get('registry_version') == 2 and r.get('schema_version') == 1, 'registry version')
    require(r.get('classification_as_of') == '2026-10-09', 'classification date')
    require(r.get('coverage_targets') == TARGETS, 'coverage targets weakened')
    require(r.get('execution_authorized') is False and m.get('execution_authorized') is False, 'execution is not authorized')
    require(r.get('exact_market_values_verified') is False, 'exact market values must remain unverified')
    issuers = r.get('issuers', [])
    require(len(issuers) == 100, 'requires 100 issuers')
    tickers = [x.get('ticker') for x in issuers]
    require(tickers == sorted(set(tickers)) and 'NPK' in tickers and 'JOUT' not in tickers, 'unique sorted substituted tickers required')
    keys = [x.get('issuer_deduplication_key') for x in issuers]
    require(all(isinstance(k, str) and re.fullmatch(r'SEC_CIK:[0-9]{10}', k) for k in keys) and len(set(keys)) == 100, 'unique CIKs required')
    require({x['ticker'] for x in issuers if x.get('reserved_holdout') is True} == HOLDOUTS, 'frozen holdouts changed')
    require(all(type(x.get('reserved_holdout')) is bool for x in issuers), 'holdout flags must be boolean')
    tiers = Counter(x.get('market_cap_tier') for x in issuers)
    require(tiers == {'mega_large': 40, 'mid': 30, 'small_micro': 30}, 'tier composition changed')
    require(len({x.get('sector') for x in issuers}) >= 10, 'sector shortfall')
    tags = set()
    for x in issuers:
        require(all(isinstance(x.get(k), str) and x[k].strip() for k in ('company', 'sector', 'domicile', 'reporting_basis')), 'required issuer metadata missing')
        ts = x.get('complexity_tags')
        require(isinstance(ts, list) and all(isinstance(t, str) and t for t in ts) and ts == sorted(set(ts)), 'invalid complexity tags')
        tags.update(ts)
    require(len(tags) >= 20, 'tag shortfall')
    require(m.get('registry_version') == 2 and m.get('version') == 2 and m.get('captures_executed') == 0, 'fixture version or capture state invalid')
    require(m.get('artifact_type') == 'offline_question_fixtures_not_capture_matrix', 'fixture artifact type')
    require(m.get('question_families') == list(FAMILIES), 'family list changed')
    fixtures = m.get('fixtures', [])
    require(len(fixtures) == 600, 'requires 600 fixtures')
    by_ticker = {x['ticker']: x for x in issuers}
    expected = {(t, f) for t in tickers for f in FAMILIES}
    pairs, ids = set(), set()
    counts = Counter()
    qs = templates()
    for f in fixtures:
        require(set(f) == {'id', 'ticker', 'company', 'category', 'question', 'partition'}, 'unexpected fixture fields or capture data')
        t, family = f['ticker'], f['category']
        require((t, family) in expected and (t, family) not in pairs and f['id'] not in ids, 'duplicate or unknown fixture')
        issuer = by_ticker[t]
        require(f['id'] == t+'-'+family and f['company'] == issuer['company'], 'fixture identity mismatch')
        require(f['question'] == qs[family].format(company=issuer['company']), 'question template changed')
        partition = 'holdout' if t in HOLDOUTS else 'development'
        require(f['partition'] == partition, 'fixture partition changed')
        pairs.add((t, family)); ids.add(f['id']); counts[partition] += 1
    require(pairs == expected and counts == {'development': 480, 'holdout': 120}, 'incomplete family matrix')
    require(m.get('partition_counts') == dict(counts), 'partition summary mismatch')
    return {'integrity_passed': True, 'coverage_complete': True, 'issuers': 100, 'fixtures': 600, 'tier_counts': dict(tiers), 'partition_counts': dict(counts), 'holdout_issuers': 20, 'execution_authorized': False}


def build_setup(proposal_dir):
    p = Path(proposal_dir); q = p / 'reconciliation'
    plan = read(p / 'candidate_plan.json')
    require(plan.get('planned_question_families') == list(FAMILIES), 'proposal question families changed')
    archived = build_readiness(p)
    require(not archived['cohort_blockers'], 'archived cohort blockers')
    require(archived['summary']['company_admitted_count'] == 99 and archived['summary']['classification_excluded_tickers'] == ['JOUT'], 'requires archived 99-company admission')
    require({r['ticker'] for r in archived['rows'] if not r['company_admitted']} == {'JOUT'}, 'unexpected admission exclusion')
    jout = next(r for r in archived['rows'] if r['ticker'] == 'JOUT')
    require(jout['reserved_holdout'] is False, 'JOUT must be development')
    approval = read(q / 'approved_npk_replacement.json')
    required = {'status':'approved_by_user', 'from_ticker':'JOUT', 'to_ticker':'NPK', 'pool':'development', 'holdout_membership_change_authorized':False, 'execution_authorized':False}
    require(all(approval.get(k) == v and (not isinstance(v, bool) or approval.get(k) is v) for k,v in required.items()), 'replacement approval missing or changed')
    npk = read(q / 'replacement_candidate_review.json')
    require(npk.get('ticker') == 'NPK' and npk.get('pool') == 'development' and npk.get('proposed_replacement_for') == 'JOUT', 'replacement identity/pool')
    ident, cap, md = npk['identity'], npk['market_cap'], npk['registry_metadata_proposal']
    require(ident.get('cik') == '0000080172' and ident.get('issuer_deduplication_key') == 'SEC_CIK:0000080172' and npk.get('company') == 'National Presto Industries, Inc.', 'NPK company mapping changed')
    require(is_url(ident.get('source_url')) and is_url(ident.get('class_source_url')) and bool(ident.get('security_class')), 'NPK identity/class sources missing')
    require(cap.get('source_as_of') == '2026-10-09' and cap.get('currency') == 'USD' and is_url(cap.get('source_url')) and cap.get('same_date_displays_equal') is True, 'NPK dated cap evidence missing')
    values = [cap.get(k) for k in ('summary_normalized_usd', 'history_normalized_usd')]
    require(all(type(v) in (str, int) for v in values), 'invalid NPK cap types')
    try:
        a,b = map(Decimal, map(str, values))
        require(a.is_finite() and b.is_finite() and a == b and 0 < a < Decimal('2000000000'), 'NPK cap outside small tier or mismatched')
    except InvalidOperation as exc:
        raise ValueError('invalid NPK cap') from exc
    require(md.get('domicile') == 'US' and md.get('reporting_basis') == 'US_GAAP' and md.get('sector') == 'Industrials', 'NPK metadata changed')
    require(is_url(md.get('source_url')) and all(md.get(k) for k in ('domicile_evidence', 'reporting_evidence', 'sector_evidence')), 'NPK metadata evidence missing')
    require(npk.get('execution_authorized') is False and cap.get('selected_exact_value_certified') is False, 'replacement exceeds approved scope')
    names = {}
    for filename in ('domestic_identity_a.json', 'domestic_identity_b.json', 'international_identity_review.json'):
        for item in read(q / filename)['rows']:
            t = item.get('ticker_candidate', item.get('ticker'))
            current = item.get('current_identity', {})
            name = item.get('issuer_name_observed', current.get('name'))
            cik = item.get('cik', current.get('cik'))
            if name and cik: names[t] = (name, 'SEC_CIK:'+cik)
    finalized_rows = copy.deepcopy([r for r in archived['rows'] if r['ticker'] != 'JOUT'])
    fields = {k:{'value':md[k], 'status':'verified_primary' if k!='sector' else 'analyst_mapping_from_primary_business_evidence', 'source_ref':md['source_url']} for k in ('domicile', 'reporting_basis', 'sector')}
    fields['complexity_tags'] = {'value':[], 'status':'valid_empty_not_exhaustively_assessed'}
    finalized_rows.append({'ticker':'NPK', 'proposed_size_tier':'small_micro', 'reserved_holdout':False, 'issuer_deduplication_key':ident['issuer_deduplication_key'], 'company_admitted':True, 'metadata_fields':fields, 'exact_cap_verified_for_answers':False, 'evidence_ref':'replacement_candidate_review.json', 'classification_eligible':True, 'identity_class_eligible':True, 'metadata_blockers':[]})
    names['NPK'] = (npk['company'], ident['issuer_deduplication_key'])
    issuers = []
    for r in sorted(finalized_rows, key=lambda x:x['ticker']):
        t = r['ticker']; f = r['metadata_fields']
        require(t in names and names[t][1] == r['issuer_deduplication_key'], 'primary name/CIK missing: '+t)
        issuers.append({'ticker':t, 'company':names[t][0], 'market_cap_tier':'mega_large' if r['proposed_size_tier']=='large' else r['proposed_size_tier'], 'sector':f['sector']['value'], 'domicile':f['domicile']['value'], 'reporting_basis':f['reporting_basis']['value'], 'complexity_tags':sorted(f['complexity_tags']['value']), 'issuer_deduplication_key':r['issuer_deduplication_key'], 'reserved_holdout':r['reserved_holdout'], 'admission_evidence':r})
    registry = {'schema_version':1, 'registry_version':2, 'classification_as_of':'2026-10-09', 'coverage_targets':copy.deepcopy(TARGETS), 'issuers':issuers, 'execution_authorized':False, 'exact_market_values_verified':False, 'external_prior_holdout_exposure':'unknown; not claimed verified unseen', 'registry_default_changed':False}
    qs = templates(); fixtures = []
    for issuer in issuers:
        for family in FAMILIES:
            t = issuer['ticker']
            fixtures.append({'id':t+'-'+family, 'ticker':t, 'company':issuer['company'], 'category':family, 'question':qs[family].format(company=issuer['company']), 'partition':'holdout' if t in HOLDOUTS else 'development'})
    manifest = {'version':2, 'registry_version':2, 'artifact_type':'offline_question_fixtures_not_capture_matrix', 'question_families':list(FAMILIES), 'fixtures':fixtures, 'partition_counts':{'development':480, 'holdout':120}, 'captures_executed':0, 'execution_authorized':False}
    result = validate_setup(registry, manifest)
    cohort = {'schema_version':1, 'artifact_type':'finalized_offline_cohort', 'replacement':required, 'archived_proposal_ref':'../candidate_plan.json', 'archived_readiness_ref':'classification_setup_readiness.json', 'archived_candidate_sha256':hashlib.sha256((p/'candidate_plan.json').read_bytes()).hexdigest(), 'rows':finalized_rows, 'validation':result, 'execution_authorized':False, 'captures_executed':0, 'holdout_membership_changed':False, 'external_prior_holdout_exposure':'unknown; not claimed verified unseen'}
    return {'finalized_cohort':cohort, 'registry':registry, 'manifest':manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposal_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    result = build_setup(args.proposal_dir)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        for key, name in [('finalized_cohort','finalized_cohort.json'),('registry','issuer_registry.v2.json'),('manifest','fixtures.v2.json')]:
            with (args.output_dir / name).open('x') as stream:
                json.dump(result[key], stream, indent=2); stream.write('\n')
    print(json.dumps(result['finalized_cohort']['validation'], indent=2))


if __name__ == '__main__':
    main()
