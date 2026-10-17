"""Invented EPS facts/policy: source-bound inspection, never product admission."""
from copy import deepcopy
from decimal import localcontext

import pytest

from test_filing_share_class import body as cover, args
from validation.filing_eps_basis import inspect_filing_eps_basis, MAX_POLICY_CHARS
from app.providers.sec_inline_facts import parse_inline_observations

UNIT = '''<xbrli:unit id="u"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'''
POLICY = '''<ix:nonNumeric id="policy" name="gaap:EarningsPerShareTextBlock" contextRef="c1" escape="true"><p>Basic earnings per share uses <b>participating securities</b>.</p><p>Diluted EPS includes potential common shares.</p></ix:nonNumeric>'''


def fact(concept='Basic', value='4.63', identifier='eps', attrs=''):
    return f'<ix:nonFraction id="{identifier}" name="gaap:EarningsPerShare{concept}" contextRef="c1" unitRef="u" decimals="INF" scale="0" {attrs}>{value}</ix:nonFraction>'


def document(facts=None, unit=UNIT, policy=POLICY):
    raw = cover().decode().replace('<body>', '''<body xmlns:gaap="http://fasb.org/us-gaap/2025" xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">''')
    raw = raw.replace('</ix:resources>', unit+'</ix:resources>')
    return raw.replace('</body>', (fact() if facts is None else facts)+policy+'</body>').encode()


def inspect(raw=None):
    return inspect_filing_eps_basis(**args(document() if raw is None else raw))


def coverage(report, concept='Basic'):
    return next(row for row in report['reporting_period_coverage'] if row['concept'] == 'EarningsPerShare'+concept)


def test_exact_per_share_unit_and_fact_provenance_without_admission_or_substitution():
    a = args(document())
    original = deepcopy(a)
    r = inspect_filing_eps_basis(**a)
    assert a == original
    assert r['inspected'] and r['status'] == 'partial'
    assert coverage(r) == {'concept': 'EarningsPerShareBasic', 'status': 'observed', 'value': '4.63', 'fact_ids': ['eps']}
    assert coverage(r, 'Diluted')['status'] == 'not_observed'
    row = r['observations'][0]
    assert row['literal'] == row['value'] == '4.63'
    assert row['unit'] == 'USD/shares' and row['decimals'] == 'INF'
    assert row['start'] == '2025-01-01' and row['end'] == '2025-12-31'
    assert row['fact_id'] == 'eps' and row['context_id'] == 'c1'
    assert row['entity_identifier'] == '0001234567'
    assert r['raw_binding']['body_sha256'] == a['receipt']['body_sha256']
    assert r['already_adjusted_through'] is None
    for key in ('admitted', 'launch_ready', 'basic_to_diluted_substitution_performed',
                'split_basis_verified', 'eps_class_compatibility_verified', 'quote_unit_verified', 'independently_adjudicated'):
        assert r[key] is False
    assert 'entry_pe' not in r and 'adjusted_eps' not in r
    policy = r['eps_policy_display_text'][0]
    assert policy['display_text'] == 'Basic earnings per share uses participating securities. Diluted EPS includes potential common shares.'
    assert policy['participating_securities_mentioned'] is True
    assert policy['fact_id'] == 'policy'
    assert 'not_canonical' in policy['representation']


def test_surrounding_basic_and_diluted_heading_does_not_upgrade_basic():
    raw = document().replace(b'</body>', b'<p>Earnings per share, basic and diluted</p></body>')
    assert coverage(inspect(raw), 'Diluted')['value'] is None


def test_basic_diluted_and_equal_duplicates_keep_distinct_source_fact_ids():
    r = inspect(document(fact()+fact('Basic', '4.630', 'copy')+fact('Diluted', '4.12', 'diluted')))
    assert coverage(r)['status'] == 'observed' and coverage(r)['fact_ids'] == ['copy', 'eps']
    assert coverage(r, 'Diluted')['value'] == '4.12'
    assert len(r['observations']) == 3


def test_conflicting_values_are_not_silently_selected():
    r = inspect(document(fact()+fact('Basic', '4.64', 'other')))
    assert coverage(r)['status'] == 'conflicting' and coverage(r)['value'] is None
    assert len(r['observations']) == 2


@pytest.mark.parametrize('unit', [
    '<xbrli:unit id="u"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>',
    UNIT.replace('iso:USD', 'iso:EUR'), UNIT.replace('xbrli:shares', 'iso:shares'),
    UNIT.replace('iso:USD', 'xbrli:USD'), UNIT.replace('iso:USD', 'USD'),
    UNIT.replace('iso:USD', 'iso:shares').replace('xbrli:shares', 'iso:USD'),
    UNIT.replace('<xbrli:measure>iso:USD</xbrli:measure>', '<xbrli:measure>iso:USD</xbrli:measure><xbrli:measure>iso:USD</xbrli:measure>'),
    UNIT.replace('<xbrli:divide>', '<xbrli:divide><xbrli:measure>iso:USD</xbrli:measure>'),
    UNIT.replace('<xbrli:unitDenominator>', '<xbrli:unitDenominator xmlns:xbrli="https://wrong.invalid">'),
])
def test_unsupported_units_never_become_per_share_observations(unit):
    assert not inspect(document(unit=unit))['observations']


@pytest.mark.parametrize('old,new', [
    (b'http://www.xbrl.org/2003/iso4217', b'https://wrong.invalid'),
    (b'http://fasb.org/us-gaap/2025', b'https://wrong.invalid/us-gaap/2025'),
    (b'name="gaap:EarningsPerShareBasic"', b'name="gaap:Revenue"'),
    (b'unitRef="u"', b'unitRef="missing"'),
    (b'contextRef="c1" unitRef="u"', b'contextRef="missing" unitRef="u"'),
    (b'scale="0"', b'scale="10"'), (b'scale="0"', b'scale="-10"'),
    (b'scale="0"', b'scale="1.2"'), (b'decimals="INF"', b'decimals="bad"'),
    (b'id="eps"', b'id="eps" continuedAt=""'), (b'id="eps"', b'id="eps" target=""'),
    (b'id="eps"', b'id="eps" tupleRef="x"'), (b'id="eps"', b'id="eps" precision="3"'),
    (b'id="eps"', b'id="eps" escape="true"'),
    (b'id="eps"', b'id="eps" format="unknown"'),
    (b'id="eps"', b'id="eps" format="missing:unknown"'),
    (b'id="eps"', b'id="eps" format="ixt:unknown"'),
    (b'id="eps"', b'id="eps" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"'),
    (b'>4.63</ix:nonFraction>', b'><b>4.63</b></ix:nonFraction>'),
    (b'>4.63</ix:nonFraction>', b'>1e2</ix:nonFraction>'),
    (b'>4.63</ix:nonFraction>', b'>NaN</ix:nonFraction>'),
    (b'>4.63</ix:nonFraction>', b'>-4.63</ix:nonFraction>'),
    (b'>4.63</ix:nonFraction>', b'>1000000.00000000001</ix:nonFraction>'),
])
def test_unsupported_fact_metadata_or_numeric_representation_remains_missing(old, new):
    assert not inspect(document().replace(old, new))['observations']


@pytest.mark.parametrize('value,attrs,expected', [
    ('4.63', 'sign="-"', '-4.63'), ('0', '', '0'),
    ('1,234.56', 'format="ixt:num-dot-decimal"', '1234.56'),
    ('1000000', '', '1000000'),
])
def test_explicit_negative_zero_and_supported_transform_values_remain_exact(value, attrs, expected):
    assert coverage(inspect(document(fact(value=value, attrs=attrs))))['value'] == expected


def test_decimal_arithmetic_is_independent_of_ambient_precision():
    raw = document(fact(value='4.6300000000000000000000000000001'))
    with localcontext() as ctx:
        ctx.prec = 2
        assert coverage(inspect(raw))['value'] == '4.6300000000000000000000000000001'
        assert not inspect(document(fact(value='1000000.0000000000000000000001')))['observations']
    assert coverage(inspect(document().replace(b'scale="0"', b'scale="-2"')))['value'] == '0.0463'


def context_copy(raw, *, start='2025-01-01', end='2025-12-31', cik='0001234567', extra=''):
    text = raw.decode()
    begin = text.index('<xbrli:context')
    stop = text.index('</xbrli:context>')+len('</xbrli:context>')
    copy = text[begin:stop].replace('id="c1"', 'id="epscontext"').replace('2025-01-01', start).replace('2025-12-31', end).replace('0001234567', cik).replace('</xbrli:entity>', extra+'</xbrli:entity>')
    text = text.replace('</ix:resources>', copy+'</ix:resources>')
    text = text.replace('contextRef="c1" unitRef="u"', 'contextRef="epscontext" unitRef="u"')
    return text.encode()


@pytest.mark.parametrize('start,end,cik,extra', [
    ('2025-04-01', '2025-06-30', '0001234567', ''),
    ('2026-01-01', '2026-12-31', '0001234567', ''),
    ('2024-01-01', '2025-12-31', '0001234567', ''),
    ('2025-01-01', '2025-12-31', '0009999999', ''),
    ('2025-01-01', '2025-12-31', '0001234567', '<xbrli:segment/>'),
    ('2025-13-01', '2025-12-31', '0001234567', ''),
])
def test_quarterly_future_multiyear_wrong_issuer_and_segmented_contexts_are_not_annual_eps(start,end,cik,extra):
    assert not inspect(context_copy(document(), start=start, end=end, cik=cik, extra=extra)).get('observations', [])


def test_prior_annual_observation_is_preserved_but_not_current_coverage():
    r = inspect(context_copy(document(), start='2024-01-01', end='2024-12-31'))
    assert r['observations'][0]['value'] == '4.63'
    assert coverage(r)['status'] == 'not_observed'


@pytest.mark.parametrize('attrs', ['continuedAt="next"', 'target="other"', 'format="ixt:other"', 'tupleRef="other"',
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"'])
def test_unsupported_policy_forms_are_not_displayed(attrs):
    raw = document(policy=POLICY.replace('id="policy"', 'id="policy" '+attrs))
    assert not inspect(raw)['eps_policy_display_text']


def test_policy_exclusion_overflow_and_absent_phrase_do_not_infer_false_absence():
    raw = document(policy=POLICY.replace('participating securities', '<ix:exclude>CANARY</ix:exclude>common shares'))
    r = inspect(raw)
    assert 'CANARY' not in str(r) and r['eps_policy_display_text'][0]['participating_securities_mentioned'] is None
    raw = document(policy=POLICY.replace('participating securities', 'x'*(MAX_POLICY_CHARS+1)))
    r = inspect(raw)
    assert not r['eps_policy_display_text'] and coverage(r)['status'] == 'observed'


def test_late_duplicate_and_wrong_receipt_reject_whole_inspection_without_details():
    for raw in (document().replace(b'</body>', b'<span id="eps"/></body>'), b'<!DOCTYPE html>'+document(), b'\xff'):
        assert not inspect(raw)['inspected']
    a = args(document()); a['receipt']['body_sha256'] = '0'*64
    assert not inspect_filing_eps_basis(**a)['inspected']


def test_original_monetary_parser_is_not_widened_by_eps_inspection():
    raw = document()
    assert not parse_inline_observations(raw.decode(), cik='0001234567', concepts=('EarningsPerShareBasic',))
    assert inspect(raw)['observations']
    assert not parse_inline_observations(raw.decode(), cik='0001234567', concepts=('EarningsPerShareBasic',))


def test_policy_bound_discards_overflow_and_parser_bound_is_not_silent_truncation():
    policy = '<ix:nonNumeric id="policy" name="gaap:EarningsPerShareTextBlock" contextRef="c1">{}</ix:nonNumeric>'
    assert len(inspect(document(policy=policy.format('x'*MAX_POLICY_CHARS)))['eps_policy_display_text'][0]['display_text']) == MAX_POLICY_CHARS
    assert not inspect(document(policy=policy.format('x'*(MAX_POLICY_CHARS+1))))['eps_policy_display_text']
    many = ''.join(POLICY.replace('id="policy"', f'id="policy{i}"') for i in range(33))
    assert inspect(document(policy=many))['stage'] == 'bounded_inline_parse'


def test_namespace_scope_and_unit_divide_order_are_not_guessed():
    raw = document(fact(attrs='xmlns:gaap="https://wrong.invalid/us-gaap/2025"'))
    assert not inspect(raw)['observations']
    raw = document(fact(attrs='format="ixt:num-dot-decimal" xmlns:ixt="https://wrong.invalid"'))
    assert not inspect(raw)['observations']
    denominator = '<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>'
    bad = UNIT.replace(denominator, '').replace('<xbrli:divide>', '<xbrli:divide>'+denominator)
    assert not inspect(document(unit=bad))['observations']


@pytest.mark.parametrize('container', ['exclude', 'continuation'])
def test_excluded_or_continued_facts_and_policy_are_not_independent_literal_evidence(container):
    r = inspect(document(f'<ix:{container}>'+fact()+f'</ix:{container}>', policy=f'<ix:{container}>'+POLICY+f'</ix:{container}>'))
    assert not r['observations'] and not r['eps_policy_display_text']


def test_policy_preserves_source_context_but_does_not_supply_eps_when_none_observed():
    r = inspect(document(facts=''))
    assert r['inspected'] and not r['observations']
    assert all(c['status'] == 'not_observed' for c in r['reporting_period_coverage'])
    p = r['eps_policy_display_text'][0]
    assert p['entity_identifier'] == '0001234567' and p['start'] == '2025-01-01'
    assert p['source_form'] == '10-K' and p['filed_at'] == '2026-02-20'
    assert r['already_adjusted_through'] is None


@pytest.mark.parametrize('form', ['10-Q', '20-F'])
def test_other_form_does_not_silently_enter_annual_eps_contract(form):
    a = args(document().replace(b'>10-K<', ('>'+form+'<').encode()))
    a['form'] = form
    assert not inspect_filing_eps_basis(**a)['inspected']
