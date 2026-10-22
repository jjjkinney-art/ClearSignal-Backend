"""Reconcile a separately bound table total before deriving dated relationships."""
from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from app.providers import sec_segment_facts as parser
from app.providers.sec_inline_facts import parse_inline_observations
from app.services import segment_financial_context as service
from app.services.segment_analysis import segment_analysis, render_segment_analysis
from test_segment_financial_context import xml, document, CIK, item


def with_totals():
    source = xml()
    total_context = f'''<x:context id="total"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">{CIK}</x:identifier><x:segment>
    <d:explicitMember dimension="s:ConsolidationItemsAxis">g:OperatingSegmentsMember</d:explicitMember></x:segment></x:entity>
    <x:period><x:startDate>2024-01-01</x:startDate><x:endDate>2024-12-31</x:endDate></x:period></x:context>'''
    source = source.replace('</ix:resources>', total_context + '</ix:resources>')
    def fact(concept, value):
        return f'<ix:nonFraction id="total-{concept}" name="g:{concept}" contextRef="total" unitRef="usd" format="t:num-dot-decimal" scale="3" decimals="-3">{value}</ix:nonFraction>'
    return source.replace('<td>1,000</td>', '<td>' + fact('Revenues', '1,000') + '</td>').replace('<td>80</td>', '<td>' + fact('OperatingIncomeLoss', '80') + '</td>')


def analysis(source=None):
    proof, = parser.parse_segment_tables(source or with_totals(), cik=CIK)
    return segment_analysis(proof, parser.reconstruct(proof, cik=CIK), cik=CIK)


def test_exact_totals_and_derived_values_keep_table_scope_and_input_identities():
    source = with_totals()
    proof, = parser.parse_segment_tables(source, cik=CIK)
    result = analysis(source)
    assert result['status'] == 'matched' and result['scope'] == 'reported_segment_table'
    assert result['segment_sums_usd'] == {'revenue': 1000000, 'operating_income': 80000}
    assert [r['display_percent'] for r in result['derived_ratios']] == ['20.0', '-10.0', '80.0', '12.5']
    for ratio in result['derived_ratios']:
        assert ratio['provenance'] == 'derived' and ratio['multiplier'] == 100
        assert ratio['input_fact_ids'] and ratio['denominator_usd'] > 0
    total = proof['metrics']['revenue']['total']['observation']
    assert total['scope'] == 'reported_segment_total'
    assert parser.amount(total, cik=CIK) is None
    assert parse_inline_observations(source, cik=CIK, concepts=parser.CONCEPTS) == ()
    assert 'not independently bound consolidated-company revenue' in render_segment_analysis(result)
    assert 'standalone segment margins' in render_segment_analysis(result)


@pytest.mark.parametrize('before,after', [
    ('>1,000</ix:nonFraction>', '>1,001</ix:nonFraction>'),
    ('>80</ix:nonFraction>', '>81</ix:nonFraction>'),
])
def test_any_exact_reconciliation_mismatch_withholds_all_ratios(before, after):
    result = analysis(with_totals().replace(before, after))
    assert result['status'] == 'mismatch' and result['derived_ratios'] == []
    assert 'do not sum exactly' in render_segment_analysis(result)
    evidence = item(with_totals().replace(before, after))
    assert service.bound_segment_financial_context(evidence, ticker='ZQXB', cik=CIK)
    assert evidence.segment_disclosures[0]['segment_context']['totals_reconciled'] is False


@pytest.mark.parametrize('before,after', [
    ('id="total"', 'id="ctx0"'),
    ('contextRef="total"', 'contextRef="missing"'),
    ('g:OperatingSegmentsMember</d:explicitMember></x:segment>', 'g:ConsolidatedEntitiesMember</d:explicitMember></x:segment>'),
    ('id="total-Revenues"', 'id="total-OperatingIncomeLoss"'),
    ('<td>Total</td>', '<td>Company</td>'),
])
def test_unsupported_total_is_not_invented_or_replaced_by_sum(before, after):
    source = with_totals()
    if before not in source:
        assert before == '<td>Total</td>'
        before = '>Total</td>'; after = '>Company</td>'
    proofs = parser.parse_segment_tables(source.replace(before, after), cik=CIK)
    if proofs:
        result = segment_analysis(proofs[0], parser.reconstruct(proofs[0], cik=CIK), cik=CIK)
        assert result['status'] == 'unavailable' and result['derived_ratios'] == []
    # A missing total does not license summing segments to manufacture a denominator.
    assert analysis(xml())['status'] == 'unavailable'


@pytest.mark.parametrize('change', ['amount', 'scope', 'date', 'currency', 'scale', 'sign', 'column', 'fact_id'])
def test_total_binding_reconstructs_display_period_scope_unit_and_scale(change):
    proof = deepcopy(parser.parse_segment_tables(with_totals(), cik=CIK)[0])
    total = proof['metrics']['revenue']['total']
    obs = total['observation']
    if change == 'amount': obs['literal'] = '999'
    elif change == 'scope': obs['scope'] = 'consolidated'
    elif change == 'date': obs['start'] = '2023-01-01'
    elif change == 'currency': obs['unit'] = 'EUR'
    elif change == 'scale': obs['scale'] = 6
    elif change == 'sign': obs['sign'] = '-'
    elif change == 'column': total['column'] = 2
    elif change == 'fact_id': obs['fact_id'] = 'other'
    result = segment_analysis(proof, parser.reconstruct(proof, cik=CIK), cik=CIK)
    assert result['status'] == 'unavailable' and result['derived_ratios'] == []


@pytest.mark.parametrize('change', ['display', 'input', 'denominator', 'provenance', 'formula', 'rounding', 'currency', 'period', 'scope'])
def test_derived_metadata_tampering_is_rejected_even_if_reported_summary_is_preserved(change):
    evidence = item(with_totals())
    value = evidence.segment_disclosures[0]
    assert value['segment_context']['totals_reconciled'] is True
    assert '20.0%' not in evidence.summary
    ratio = value['segment_context']['derived_ratios'][0]
    if change == 'display': ratio['display_percent'] = '99.9'
    elif change == 'input': ratio['input_fact_ids'] = ['invented']
    elif change == 'denominator': ratio['denominator_usd'] += 1
    elif change == 'provenance': ratio['provenance'] = 'reported'
    elif change == 'formula': ratio['formula'] = 'invented'
    elif change == 'rounding': ratio['rounding'] = 'exact'
    elif change == 'currency': ratio['currency'] = 'EUR'
    elif change == 'period': ratio['period_end'] = '2023-12-31'
    elif change == 'scope': value['segment_context']['analysis']['scope'] = 'consolidated'
    assert service.bound_segment_financial_context(evidence, ticker='ZQXB', cik=CIK) is None


def test_global_decimal_precision_does_not_change_display_and_losses_can_exceed_sales():
    with localcontext() as context:
        context.prec = 2
        result = analysis()
    assert [r['display_percent'] for r in result['derived_ratios']] == ['20.0', '-10.0', '80.0', '12.5']
    from app.services.segment_analysis import _ratio
    assert _ratio(-8850000, 1983000, kind='test', label='Safety analogue', input_ids=[])['display_percent'] == '-446.3'


def test_zero_total_revenue_and_zero_segment_sales_do_not_divide_by_zero():
    source = with_totals().replace('>200</ix:nonFraction>', '>0</ix:nonFraction>').replace('>800</ix:nonFraction>', '>0</ix:nonFraction>').replace('>1,000</ix:nonFraction>', '>0</ix:nonFraction>')
    result = analysis(source)
    assert result['status'] == 'zero_revenue' and result['derived_ratios'] == []
    source = with_totals().replace('>200</ix:nonFraction>', '>0</ix:nonFraction>').replace('>800</ix:nonFraction>', '>1,000</ix:nonFraction>')
    result = analysis(source)
    assert result['status'] == 'matched'
    assert [r['display_percent'] for r in result['derived_ratios']] == ['0.0', '100.0', '10.0']
    assert 'unavailable (zero sales)' in render_segment_analysis(result)


def test_one_dollar_total_difference_is_not_rounded_away():
    source = with_totals().replace('>1,000</ix:nonFraction>', '>1,000.001</ix:nonFraction>')
    result = analysis(source)
    assert result['status'] == 'mismatch' and result['derived_ratios'] == []
    assert result['totals']['revenue']['amount_usd'] == 1000001


def test_half_up_rounding_preserves_exact_integer_inputs_and_no_income_share_is_invented():
    from app.services.segment_analysis import _ratio
    assert _ratio(1235, 10000, kind='test', label='A', input_ids=[])['display_percent'] == '12.4'
    assert _ratio(-1235, 10000, kind='test', label='A', input_ids=[])['display_percent'] == '-12.4'
    source = with_totals().replace('>100</ix:nonFraction>', '>20</ix:nonFraction>').replace('>80</ix:nonFraction>', '>0</ix:nonFraction>')
    result = analysis(source)
    assert result['status'] == 'matched' and result['totals']['operating_income']['amount_usd'] == 0
    assert {r['kind'] for r in result['derived_ratios']} == {'share_of_reported_table_external_sales', 'reported_segment_operating_margin'}


def test_final_answer_keeps_reported_values_separate_from_derived_calculations(monkeypatch):
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, "_load_ticker_cik_map", lambda: {"ZQXB": CIK})
    from app.schemas import InvestmentThesis
    from app.services.evidence_references import admit_evidence
    from app.services.source_answer import apply_source_answer_gate
    from test_financial_thesis_foundation import pair
    evidence = item(with_totals())
    admitted, refs, _ = admit_evidence(pair(ticker='ZQXB', cik=CIK) + [evidence], evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker='ZQXB', company_name='Invented issuer')
    response = apply_source_answer_gate(thesis, 'What is the investment thesis for ZQXB? Cite material claims.', admitted, references=refs)
    calculations = [r for r in response['inferences'] if r['kind'] == 'segment_table_calculation']
    assert len(calculations) == 1 and calculations[0]['provenance'] == 'derived'
    assert calculations[0]['analysis']['status'] == 'matched'
    assert calculations[0]['period_start'] == '2024-01-01'
    assert 'Water Systems: sales share 20.0%; reported operating ratio -10.0%.' in thesis.direct_answer
    assert 'For 2024-01-01 to 2024-12-31' in thesis.direct_answer
    assert '20.0%' not in evidence.summary
    assert evidence.claim_type == 'reported_fact' and evidence.verified_claims == []
    assert all(r['provenance'] == 'derived' for r in calculations[0]['analysis']['derived_ratios'])
    assert f"[{calculations[0]['reference_ids'][0]}]" in thesis.direct_answer
    assert response['status'] == 'partial'
    assert 'valuation and expected returns' in response['unanswered_parts']


def test_total_scope_must_match_every_segment_not_only_the_first():
    proof = deepcopy(parser.parse_segment_tables(with_totals(), cik=CIK)[0])
    rows = parser.reconstruct(proof, cik=CIK)
    rows[1]['dimensions'][0]['member_namespace'] = 'http://fasb.org/us-gaap/2024'
    result = segment_analysis(proof, rows, cik=CIK)
    assert result['status'] == 'unavailable' and result['derived_ratios'] == []
