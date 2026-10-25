"""Synthetic complete tables, not retained issuers or live requests."""
from copy import deepcopy
import hashlib
import pytest

from app.providers import sec_cash_reconciliation as service


def xml(*, currency='USD', label='Factory receivables', amounts=(30, 20),
        total=(75, 90), extra=False, zero=False):
    contexts = ''.join(f'<x:context id="year{y}"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">1234567</x:identifier></x:entity><x:period><x:startDate>{y}-01-01</x:startDate><x:endDate>{y}-12-31</x:endDate></x:period></x:context>' for y in (2025, 2024))
    def row(key, concept, values, *, signs=('', ''), display_negative=False, fixed_zero=False):
        result = '<tr><td>' + key + '</td>'
        for y, n, sign in zip((2025, 2024), values, signs):
            literal = '-' if fixed_zero else str(n)
            transform = 'fixed-zero' if fixed_zero else 'num-dot-decimal'
            fact = f'<ix:nonFraction id="{key.replace(" ", "")}{y}" contextRef="year{y}" unitRef="money" name="{concept}" scale="0" sign="{sign}" format="t:{transform}" decimals="0">{literal}</ix:nonFraction>'
            result += '<td>' + ('(' if display_negative else '') + fact + '</td><td>' + (')' if display_negative else '') + '</td>'
        return result + '</tr>'
    rows = row('Net earnings', 'g:NetIncomeLoss', (100, 100))
    rows += row('Depreciation', 'g:Depreciation', (5, 10))
    if extra:
        rows += row('Adjustment', 'custom:SpecialAdjustment', (7, 9))
    if zero:
        rows += row('Zero adjustment', 'custom:ZeroAdjustment', (0, 0), fixed_zero=True)
    rows += row(label, 'g:IncreaseDecreaseInAccountsReceivable', amounts, display_negative=True)
    rows += row('Operating cash', 'g:NetCashProvidedByUsedInOperatingActivities', total)
    return f'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:x="http://www.xbrl.org/2003/instance"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:g="http://fasb.org/us-gaap/2025"
      xmlns:custom="https://synthetic.invalid/taxonomy" xmlns:iso="http://www.xbrl.org/2003/iso4217"
      xmlns:t="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"><body>
      {contexts}<x:unit id="money"><x:measure>iso:{currency}</x:measure></x:unit>
      <table><tr><td colspan="5">For the years ended December 31,</td></tr>
      <tr><td></td><td colspan="2">2025</td><td colspan="2">2024</td></tr>
      <tr><td>Cash flows from operating activities:</td><td></td><td></td><td></td><td></td></tr>
      {rows}<tr><td>Cash flows from investing activities:</td><td></td><td></td><td></td><td></td></tr>
      </table></body></html>'''


def parse(source=None, currency='USD'):
    return service.parse_cash_reconciliations(source or xml(), cik='1234567', currency=currency)


@pytest.mark.parametrize('currency', ['USD', 'EUR', 'GBP'])
@pytest.mark.parametrize('label', ['Factory receivables', 'Clinical accounts', 'Platform billings'])
def test_display_contributions_are_separate_and_complete(currency, label):
    proof, = parse(xml(currency=currency, label=label), currency)
    result = service.reconstruct_cash_reconciliation(proof, cik='1234567', currency=currency)
    assert [t['operating_cash_flow'] for t in result['totals']] == [75, 90]
    assert all(t['residual'] == 0 for t in result['totals'])
    receivable = result['rows'][2]['values'][0]
    assert receivable['signed_taxonomy_value'] == 30
    assert receivable['display_contribution'] == -30
    assert result['operating_cash_flow_change'] == -15
    assert sum(c['change'] for c in result['current_vs_prior_component_changes']) == -15
    assert result['currency'] == currency
    assert result['admitted'] is result['source_binding_established'] is result['launch_ready'] is False


@pytest.mark.parametrize('extra,zero,total', [(True, False, (82, 99)), (False, True, (75, 90)), (True, True, (82, 99))])
def test_different_row_sets_extensions_and_explicit_zero(extra, zero, total):
    proof, = parse(xml(extra=extra, zero=zero, total=total))
    result = service.reconstruct_cash_reconciliation(proof, cik='1234567')
    assert len(result['rows']) == 4 + extra + zero


@pytest.mark.parametrize('before,after', [
    ('>75</ix:nonFraction>', '>76</ix:nonFraction>'),
    ('>2025</td>', '>2026</td>'),
    ('2025-01-01', '2025-04-01'),
    ('2025-12-31', '2025-06-30'),
    ('>1234567<', '>999999<'),
    ('iso:USD', 'iso:EUR'),
    ('<x:entity>', '<x:entity><x:segment/>'),
    ('Cash flows from investing activities:', 'Missing boundary'),
    ('Cash flows from operating activities:', 'Missing opening'),
    ('For the years ended December 31,', 'For the quarters ended June 30,'),
    ('<td>Depreciation</td>', '<td>Depreciation</td><td>99</td>'),
    ('name="g:Depreciation"', 'name="g:NetIncomeLoss"'),
    ('name="g:NetIncomeLoss"', 'name="custom:NetIncomeLoss"'),
    ('<td>(<ix:', '<td><ix:'),
    ('decimals="0"', 'decimals="unknown"'),
    ('scale="0"', 'scale="10"'),
    ('t:num-dot-decimal', 't:unsupported'),
    ('<table>', '<table style="display:none">'),
    ('<table>', '<table xmlns:g="https://other.invalid/changed">'),
    ('<table>', '<table><table></table>'),
    ('<body>', '<body hidden="hidden">'),
    ('<body>', '<body><noscript>'),
    ('<table>', '<table><ix:nonFraction>99</ix:nonFraction>'),
    ('<td>Net earnings</td>', '<td>Net earnings</td><td>unbound</td>'),
])
def test_incomplete_mismatched_or_ambiguous_sources_fail_closed(before, after):
    assert parse(xml().replace(before, after)) == ()


def test_duplicate_fact_and_competing_complete_tables_are_rejected():
    assert parse(xml().replace('id="Depreciation2025"', 'id="Netearnings2025"')) == ()
    source = xml()
    table = source[source.index('<table>'):source.index('</table>') + 8]
    assert parse(source.replace('</body>', table + '</body>')) == ()


def test_incomplete_untagged_row_is_not_silently_a_heading():
    source = xml().replace('<td>Depreciation</td>', '<td>Unknown adjustment</td>')
    import re
    source = re.sub(r'<ix:nonFraction[^>]+id="Depreciation\d+"[^>]*>\d+</ix:nonFraction>', '0', source)
    assert parse(source) == ()


@pytest.mark.parametrize('mutation', ['sign', 'missing_row', 'period', 'context', 'duplicate', 'hash', 'source_hash', 'version', 'extra_key'])
def test_capsule_is_reparsed_not_accepted_as_derived_metadata(mutation):
    proof, = parse()
    changed = deepcopy(proof)
    if mutation == 'sign': changed['xml'] = changed['xml'].replace('>(<', '><', 1)
    elif mutation == 'missing_row':
        import re
        changed['xml'] = re.sub(r'<[^>]*tr><[^>]*td>Depreciation</[^>]*td>.*?</[^>]*tr>', '', changed['xml'])
    elif mutation == 'period': changed['xml'] = changed['xml'].replace('2025-01-01', '2025-04-01')
    elif mutation == 'context': changed['xml'] = changed['xml'].replace('contextRef="year2025"', 'contextRef="missing"')
    elif mutation == 'duplicate': changed['xml'] = changed['xml'].replace('id="Depreciation2025"', 'id="Netearnings2025"')
    elif mutation == 'hash': changed['capsule_sha256'] = '0' * 64
    elif mutation == 'source_hash': changed['source_sha256'] = 'invalid'
    elif mutation == 'version': changed['version'] = True
    elif mutation == 'extra_key': changed['component_sum'] = 75
    if mutation != 'hash': changed['capsule_sha256'] = hashlib.sha256(changed['xml'].encode()).hexdigest()
    import json
    assert json.dumps(changed) != json.dumps(proof)
    assert service.reconstruct_cash_reconciliation(changed, cik='1234567') is None


def test_zero_transformation_does_not_turn_unknown_literal_into_zero():
    source = xml(zero=True)
    assert parse(source.replace('>-</ix:nonFraction>', '>unknown</ix:nonFraction>')) == ()
    assert parse(source.replace('t:fixed-zero', 't:num-dot-decimal')) == ()


def test_no_currency_fallback_no_declaration_and_bounded_proof():
    assert parse(xml(currency='EUR')) == ()
    assert parse('<!DOCTYPE html>' + xml()) == ()
    proof, = parse()
    assert service.reconstruct_cash_reconciliation(proof, cik='999') is None
    assert service.reconstruct_cash_reconciliation(proof, cik='1234567', currency='JPY') is None
    huge = deepcopy(proof)
    huge['xml'] += ' ' * service.MAX_CAPSULE
    huge['capsule_sha256'] = hashlib.sha256(huge['xml'].encode()).hexdigest()
    assert service.reconstruct_cash_reconciliation(huge, cik='1234567') is None


def test_consistent_scale_is_preserved_but_one_changed_operand_cannot_reconcile():
    proof, = parse(xml().replace('scale="0"', 'scale="3"'))
    result = service.reconstruct_cash_reconciliation(proof, cik='1234567')
    assert result['totals'][0]['operating_cash_flow'] == 75000
    assert parse(xml().replace('scale="0"', 'scale="3"', 1)) == ()


def test_taxonomy_negative_is_not_automatically_a_negative_cash_adjustment():
    proof, = parse(xml().replace('name="g:Depreciation" scale="0" sign=""',
                                 'name="g:Depreciation" scale="0" sign="-"'))
    value = service.reconstruct_cash_reconciliation(proof, cik='1234567')['rows'][1]['values'][0]
    assert value['signed_taxonomy_value'] == -5 and value['display_contribution'] == 5


def test_gap_years_and_valid_hidden_ancestor_are_rejected():
    assert parse(xml().replace('2024', '2023')) == ()
    source = xml().replace('<table>', '<noscript><table>').replace('</table>', '</table></noscript>')
    assert parse(source) == ()


def test_valid_source_hash_alone_does_not_establish_origin_binding():
    proof, = parse()
    proof['source_sha256'] = '0' * 64
    result = service.reconstruct_cash_reconciliation(proof, cik='1234567')
    assert result is not None and result['source_binding_established'] is False


def test_structure_depth_and_unsupported_resource_forms_are_bounded():
    source = xml().replace('<table>', '<div>' * 130 + '<table>').replace('</table>', '</table>' + '</div>' * 130)
    assert parse(source) == ()
    assert parse(xml().replace('<x:measure>iso:USD</x:measure>', '<x:divide/>')) == ()
    assert parse(xml().replace('unitRef="money"', 'unitRef="missing"')) == ()


def test_losses_negative_cash_and_zero_flow_keep_signs_without_directional_signal():
    source = xml().replace('name="g:NetIncomeLoss" scale="0" sign=""', 'name="g:NetIncomeLoss" scale="0" sign="-"')
    source = source.replace('<td><ix:nonFraction id="Netearnings', '<td>(<ix:nonFraction id="Netearnings')
    source = source.replace('>100</ix:nonFraction></td><td></td>', '>100</ix:nonFraction></td><td>)</td>')
    source = source.replace('>75</ix:nonFraction>', '>125</ix:nonFraction>').replace('>90</ix:nonFraction>', '>110</ix:nonFraction>')
    source = source.replace('name="g:NetCashProvidedByUsedInOperatingActivities" scale="0" sign=""', 'name="g:NetCashProvidedByUsedInOperatingActivities" scale="0" sign="-"')
    source = source.replace('<td><ix:nonFraction id="Operatingcash', '<td>(<ix:nonFraction id="Operatingcash')
    source = source.replace('>125</ix:nonFraction></td><td></td>', '>125</ix:nonFraction></td><td>)</td>')
    source = source.replace('>110</ix:nonFraction></td><td></td>', '>110</ix:nonFraction></td><td>)</td>')
    proof, = parse(source)
    result = service.reconstruct_cash_reconciliation(proof, cik='1234567')
    assert [t['operating_cash_flow'] for t in result['totals']] == [-125, -110]
    assert 'signal' not in result
    proof, = parse(xml(amounts=(105, 110), total=(0, 0)))
    assert service.reconstruct_cash_reconciliation(proof, cik='1234567')['totals'][0]['operating_cash_flow'] == 0


def test_consistent_substitute_capsule_still_has_no_original_source_authority():
    # Exact totals cannot detect deleting two offsetting contributions. The
    # eventual final binder must match this capsule back to the source document.
    import re
    source = xml(total=(70, 80))
    depreciation = re.search(r'<tr><td>Depreciation</td>.*?</tr>', source).group()
    offset = depreciation.replace('Depreciation', 'Offset').replace('g:Depreciation', 'custom:Offset')
    offset = offset.replace('<td><ix:', '<td>(<ix:').replace('</ix:nonFraction></td><td></td>', '</ix:nonFraction></td><td>)</td>')
    source = source.replace(depreciation, depreciation + offset)
    proof, = parse(source)
    changed = deepcopy(proof)
    changed['xml'] = re.sub(r'<[^>]*tr><[^>]*td>(?:Depreciation|Offset)</[^>]*td>.*?</[^>]*tr>', '', changed['xml'])
    changed['capsule_sha256'] = hashlib.sha256(changed['xml'].encode()).hexdigest()
    result = service.reconstruct_cash_reconciliation(changed, cik='1234567')
    assert result is not None and result['totals'][0]['residual'] == 0
    assert result['source_binding_established'] is result['admitted'] is False
