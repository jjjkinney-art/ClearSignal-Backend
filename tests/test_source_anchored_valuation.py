"""Invented SEC observations and explicitly hypothetical price/scenario inputs."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_client import SecFactRecord
from app.services.evidence_references import admit_evidence
from app.services.financial_thesis_foundation import _rebuild, build_financial_foundation
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from validation.source_anchored_valuation import evaluate_source_anchored_scenario

TICKER, CIK = 'ZQXB', '1234567'


def eps_item(current=5, *, annual=True):
    records = []
    for year, amount in ((2024, 4), (2025, current)):
        accession = f'{int(CIK):010d}-{str(year + 1)[-2:]}-000001'
        records.append(SecFactRecord(cik=CIK, taxonomy='us-gaap', concept='EarningsPerShareDiluted',
            label='Earnings Per Share Diluted', unit='USD/shares', value=amount,
            start=f'{year}-01-01' if annual else f'{year}-04-01',
            end=f'{year}-12-31' if annual else f'{year}-06-30',
            filed=f'{year+1}-02-20' if annual else f'{year}-08-01',
            form='10-K' if annual else '10-Q', accession=accession,
            filing_url=f'https://www.sec.gov/Archives/edgar/data/{CIK}/{accession.replace("-", "")}/{accession}-index.htm'))
    return comparable_metric_evidence(records, ticker=TICKER, expected_cik=CIK,
        concepts=('EarningsPerShareDiluted',), metric_name='diluted EPS', unit='USD/shares')


def assumptions(mode='evaluate_growth_scenario'):
    def operand(value, unit):
        return {'value': value, 'unit': unit,
                'provenance': {'kind': 'user_assumption', 'reference': 'Explicit invented research scenario'}}
    rate = 'eps_growth_rate' if mode == 'evaluate_growth_scenario' else 'annual_price_return_rate'
    return {'mode': mode, 'scenario_as_of': '2026-03-02', 'distributions': 'excluded',
        'price_per_underlying_common_share': True, 'price': operand('100', 'USD/share'),
        'exit_pe': operand('45', 'x'), 'horizon': operand(2, 'years'), rate: operand('0', 'annual_fraction'),
        'eps_basis': {'issuer': TICKER, 'currency': 'USD', 'accounting': 'gaap',
            'adjustment_definition': 'none', 'share_basis': 'diluted',
            'period_basis': 'fiscal_year', 'earnings_scope': 'total_operations',
            'split_basis': 'User assumes identical unconverted underlying common-share basis'}}


def admitted(items=None):
    return admit_evidence(items or [eps_item()], evaluated_at='2026-03-01')[:2]


def run(payload=None, items=None, refs=None):
    if items is None:
        items, refs = admitted()
    return evaluate_source_anchored_scenario(TICKER, items, refs, expected_cik=CIK,
        assumptions=assumptions() if payload is None else payload, evaluated_at='2026-03-03')


def test_source_anchor_and_assumed_price_produce_independently_reproducible_conditional_ratio():
    items, refs = admitted()
    refs[0]['id'] = 'E12'
    payload = assumptions()
    original = deepcopy(payload)
    result = run(payload, items, refs)
    assert result['available'] and result['status'] == 'partial' and not result['launch_ready']
    assert Decimal(result['entry_pe_derivation']['value']) == Fraction(100, 5) == 20
    assert Fraction(45, 20) == Fraction(3, 2) ** 2
    assert Decimal(result['values']['annualized_price_change']) == Decimal('0.5')
    assert Decimal(result['values']['terminal_price_factor']) == Decimal('2.25')
    eps = result['source_eps']
    assert eps['reference_id'] == 'E12' and eps['value'] == '5'
    assert (eps['period_start'], eps['period_end'], eps['filed_at']) == ('2025-01-01', '2025-12-31', '2026-02-20')
    assert eps['source_consistency_reconstructed'] and not eps['independently_adjudicated']
    assert not result['entry_pe_derivation']['market_pe_verified']
    assert result['inputs']['entry_pe']['provenance']['kind'] == 'user_assumption'
    assert result['inputs']['entry_pe']['eps_basis']['period_basis'] == 'fiscal_year'
    assert 'not current TTM or forward EPS' in ' '.join(result['limitations'])
    assert result['basis_verification']['earnings_scope_and_split_basis'] == 'user_assertions_not_independently_verified'
    assert payload == original  # constructing the ratio cannot rewrite supplied assumptions


def test_solve_mode_uses_same_source_anchor_with_explicit_price_return_assumption():
    payload = assumptions('solve_required_earnings_growth')
    payload['price']['value'] = '225'  # entry 45x, exit 20x
    payload['exit_pe']['value'] = '20'
    payload['annual_price_return_rate']['value'] = '0.1'
    result = run(payload)
    assert result['available']
    assert Fraction(20, 45) * Fraction(33, 20) ** 2 == Fraction(11, 10) ** 2
    assert Decimal(result['values']['eps_growth_rate']) == Decimal('0.65')


@pytest.mark.parametrize('mutate', [
    lambda p: p['eps_basis'].update(issuer='OTHER'),
    lambda p: p['eps_basis'].update(currency='EUR'),
    lambda p: p['eps_basis'].update(accounting='adjusted', adjustment_definition='company adjusted EPS'),
    lambda p: p['eps_basis'].update(share_basis='basic'),
    lambda p: p['eps_basis'].update(period_basis='trailing_12_months'),
    lambda p: p['eps_basis'].update(period_basis='forward_12_months'),
    lambda p: p.update(price_per_underlying_common_share=False),
    lambda p: p.update(price_per_underlying_common_share='true'),
    lambda p: p.update(scenario_as_of='2026-02-19'),
    lambda p: p.update(scenario_as_of='2099-01-01'),
    lambda p: p['price'].update(unit='EUR/share'),
    lambda p: p['price'].update(value='0'),
    lambda p: p['price'].update(value='-100'),
    lambda p: p['price'].update(value=True),
    lambda p: p['price'].update(value='1e2'),
    lambda p: p['price'].update(provenance={'kind': 'source_observation', 'reference': 'Unverified price', 'observation_date': '2026-03-02'}),
    lambda p: p['price'].update(provenance=[]),
    lambda p: p['exit_pe'].update(provenance={'kind': 'source_observation', 'reference': 'Not an assumption', 'observation_date': '2026-03-02'}),
    lambda p: p['exit_pe'].update(eps_basis={'issuer': 'caller override'}),
    lambda p: p['horizon'].update(value=True),
    lambda p: p.update(distributions='included'),
    lambda p: p.update(surprise='unreviewed input'),
    lambda p: p.update(mode=[]),
])
def test_incompatible_missing_or_observation_disguised_inputs_never_calculate(mutate):
    payload = assumptions()
    mutate(payload)
    result = run(payload)
    assert not result['available'] and result['reason']
    assert 'values' not in result and 'entry_pe_derivation' not in result


@pytest.mark.parametrize('mutation', [
    lambda item: setattr(item, 'summary', 'Invented EPS supports a recommendation.'),
    lambda item: setattr(item, 'availability_status', 'unavailable'),
    lambda item: setattr(item, 'freshness_status', 'stale'),
    lambda item: setattr(item, 'url', 'https://example.com/unrelated'),
    lambda item: setattr(item, 'document_type', '10-Q'),
    lambda item: setattr(item, 'document_type', None),
    lambda item: item.verified_claims[0].update(raw_value=999),
    lambda item: item.verified_claims[0].update(ticker='OTHER'),
    lambda item: item.verified_claims[0].update(unit='USD'),
    lambda item: item.verified_claims[0].update(currency='EUR'),
    lambda item: item.verified_claims[0].update(scope='segment'),
])
def test_mutated_source_observation_cannot_authorize_entry_multiple(mutation):
    items, refs = admitted()
    mutation(items[0])
    result = run(items=items, refs=refs)
    assert not result['available'] and 'values' not in result


@pytest.mark.parametrize('mutation', [
    lambda refs: refs.clear(),
    lambda refs: refs.append(deepcopy(refs[0])),
    lambda refs: refs.append({'id': refs[0]['id'], 'title': 'Unrelated duplicate ID'}),
    lambda refs: refs[0].update(claim_type='filing_metadata'),
    lambda refs: refs[0].update(reporting_period_end='2024-12-31'),
    lambda refs: refs[0].update(document_type='10-Q'),
    lambda refs: refs[0].update(freshness_status='superseded'),
    lambda refs: refs[0].update(id='made-up-id'),
    lambda refs: refs.append('malformed'),
    lambda refs: refs[0].update(freshness_status=[]),
])
def test_ambiguous_unavailable_unmatched_or_metadata_only_references_refused(mutation):
    items, refs = admitted()
    mutation(refs)
    assert not run(items=items, refs=refs)['available']


@pytest.mark.parametrize('current', [0, -1])
def test_nonpositive_eps_cannot_create_a_positive_pe_opinion(current):
    items, refs = admitted([eps_item(current)])
    result = run(items=items, refs=refs)
    assert not result['available'] and 'positive annual EPS' in result['reason']


def test_quarterly_eps_cannot_be_annualized_or_silently_replaced_by_older_annual():
    items, refs = admitted([eps_item(annual=False), eps_item()])
    result = run(items=items, refs=refs)
    assert not result['available'] and 'no quarterly annualization' in result['reason']


def test_conflicting_annual_pairs_and_wrong_trusted_cik_refused():
    items, refs = admitted([eps_item(5), eps_item(6)])
    assert not run(items=items, refs=refs)['available']
    items, refs = admitted()
    result = evaluate_source_anchored_scenario(TICKER, items, refs, expected_cik='99999',
        assumptions=assumptions(), evaluated_at='2026-03-03')
    assert not result['available']


def test_ratio_and_scenario_ignore_ambient_decimal_precision_and_inputs_are_not_aliased():
    payload = assumptions()
    payload['price']['value'] = '101'
    items, refs = admitted([eps_item(3)])
    with localcontext() as context:
        context.prec = 6
        first = run(payload, items, refs)
    with localcontext() as context:
        context.prec = 80
        second = run(payload, items, refs)
    assert first == second and first['available']
    with localcontext() as context:
        context.prec = 50
        assert Decimal(first['entry_pe_derivation']['value']) == Decimal(101) / Decimal(3)
    first['supplied_assumptions']['price']['value'] = 'changed'
    assert payload['price']['value'] == '101'


def test_eps_extension_is_not_a_generic_unit_override_or_an_ordinary_financial_metric():
    item = eps_item()
    assert _rebuild(item, ticker=TICKER, cik=CIK, name='diluted EPS', concepts=('EarningsPerShareDiluted',)) is None
    assert _rebuild(item, ticker=TICKER, cik=CIK, name='diluted EPS',
                    concepts=('EarningsPerShareDiluted',), expected_unit='shares') is None
    assert _rebuild(item, ticker=TICKER, cik=CIK, name='revenue',
                    concepts=('Revenues',), expected_unit='USD/shares') is None
    assert build_financial_foundation(TICKER, [item], None, expected_cik=CIK) is None


def test_existing_source_answer_boundary_still_withholds_unbound_investment_thresholds():
    thesis = InvestmentThesis(ticker=TICKER, company_name='Invented company', direct_answer='Buy below 20x.')
    result = apply_source_answer_gate(thesis, 'Explain decision thresholds', [], references=[])
    assert result['status'] == 'insufficient_claim_evidence'
    assert thesis.confidence_score == 0 and 'Buy below 20x' not in thesis.direct_answer


def test_per_share_opt_in_rejects_monetary_inline_claim_before_it_can_be_rebuilt():
    item = eps_item()
    for claim in item.verified_claims:
        claim['unit'] = 'USD'
        claim['inline_binding'] = {'concept': 'EarningsPerShareDiluted', 'accession': 'invented'}
    assert _rebuild(item, ticker=TICKER, cik=CIK, name='diluted EPS',
        concepts=('EarningsPerShareDiluted',), expected_unit='USD/shares') is None


@pytest.mark.parametrize('mode', ['evaluate_growth_scenario', 'solve_required_earnings_growth'])
def test_missing_explicit_assumption_is_a_gap_not_a_default(mode):
    payload = assumptions(mode)
    del payload['horizon']
    assert not run(payload)['available']


def test_source_ratio_cannot_round_a_nonzero_multiple_change_to_identity():
    payload = assumptions()
    payload['price']['value'] = '100.' + '0' * 48 + '1'
    payload['exit_pe']['value'] = '20'
    result = run(payload)
    assert not result['available']
    assert 'entry-ratio difference' in result['reason']
