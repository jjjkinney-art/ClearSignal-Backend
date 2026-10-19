"""Invented primary-filing bytes and source binding; no network or real issuers."""
from copy import deepcopy
import hashlib

import pytest

from test_quote_eps_binding import inputs as binding_inputs
from validation.filing_share_class import extract_filed_share_class, MAX_FILING_BYTES
from validation.share_basis_binding import assess_filed_share_basis

URL = 'https://www.sec.gov/Archives/edgar/data/1234567/000123456726000001/zqxb-20251231.htm'


def body(title='Class A common stock, $0.01 par value', symbol='ZQXB'):
    return f'''<html xmlns="http://www.w3.org/1999/xhtml"
        xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
        xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2025">
    <body><ix:header><ix:resources>
    <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    </ix:resources><ix:hidden>
    <ix:nonNumeric id="cik" name="dei:EntityCentralIndexKey" contextRef="c1">0001234567</ix:nonNumeric>
    </ix:hidden></ix:header>
    <ix:nonNumeric id="form" name="dei:DocumentType" contextRef="c1">10-K</ix:nonNumeric>
    <table><tr><td><ix:nonNumeric id="title" name="dei:Security12bTitle" contextRef="c1">{title}</ix:nonNumeric></td>
    <td><ix:nonNumeric id="symbol" name="dei:TradingSymbol" contextRef="c1">{symbol}</ix:nonNumeric></td>
    <td><ix:nonNumeric id="exchange" name="dei:SecurityExchangeName" contextRef="c1">Synthetic Exchange</ix:nonNumeric></td></tr></table>
    </body></html>'''.encode()


def args(raw=None):
    raw = body() if raw is None else raw
    return {'body': raw, 'receipt': {'url': URL, 'body_sha256': hashlib.sha256(raw).hexdigest(),
        'body_bytes': len(raw), 'http_status': 200, 'media_type': 'text/html', 'content_encoding': 'identity'},
        'expected_cik': '0001234567', 'expected_symbol': 'ZQXB', 'form': '10-K',
        'filed_at': '2026-02-20', 'reporting_period_end': '2025-12-31'}


def combined_body(raw=None):
    raw = body() if raw is None else raw
    raw = raw.replace(b'<body>', b'<body xmlns:gaap="http://fasb.org/us-gaap/2025" xmlns:iso="http://www.xbrl.org/2003/iso4217">')
    unit = b'<xbrli:unit id="epsunit"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>'
    fact = b'<ix:nonFraction id="filedEPS" name="gaap:EarningsPerShareDiluted" contextRef="c1" unitRef="epsunit" decimals="INF">5.00</ix:nonFraction>'
    return raw.replace(b'</ix:resources>', unit+b'</ix:resources>').replace(b'</body>', fact+b'</body>')


def combined(a=None, inputs=None):
    a = args(combined_body()) if a is None else a
    return assess_filed_share_basis(binding_inputs() if inputs is None else inputs,
        a['body'], a['receipt'], form=a['form'], filed_at=a['filed_at'], reporting_period_end=a['reporting_period_end'])


def reject(a):
    r = extract_filed_share_class(**a)
    assert r == {'extracted': False, 'admitted': False, 'launch_ready': False,
        'classification': 'offline_filed_common_share_class', 'reason': 'filed_share_class_rejected',
        'diagnostic_type': r['diagnostic_type']}
    return r


@pytest.mark.parametrize('title', ['Common stock', 'Class A common stock, $0.01 par value',
    '$1.00 par value common stock', 'Common shares, no par value', 'Class B Common Stock'])
def test_source_bound_title_symbol_exchange_are_retained_as_filed_only(title):
    a = args(body(title))
    original = deepcopy(a)
    r = extract_filed_share_class(**a)
    assert r['extracted'] and not r['admitted']
    assert r['declared_security']['title'] == title
    assert r['declared_security']['trading_symbol'] == 'ZQXB'
    assert r['declared_security']['context_id'] == 'c1'
    assert r['raw_binding']['fields']['Security12bTitle']['fact_id'] == 'title'
    assert r['raw_binding']['fields']['TradingSymbol']['namespace'] == 'http://xbrl.sec.gov/dei/2025'
    for key in ('current_listing_verified', 'quote_unit_verified', 'split_compatibility_verified',
                'eps_class_compatibility_verified', 'independently_adjudicated', 'launch_ready'):
        assert r[key] is False
    r['raw_binding']['fields']['TradingSymbol']['text'] = 'CHANGED'
    assert a == original


@pytest.mark.parametrize('title', ['Preferred stock', 'Convertible preferred into common stock',
    'Common stock and notes', 'Depositary shares representing common stock',
    'Ordinary shares', 'Common stock units', 'Warrants for common stock', '', 'A'*501])
def test_non_common_or_ambiguous_class_grammar_remains_unsupported(title):
    reject(args(body(title)))


@pytest.mark.parametrize('old,new', [
    (b'http://xbrl.sec.gov/dei/2025', b'https://attacker.invalid/dei/2025'),
    (b'http://www.sec.gov/CIK', b'http://attacker.invalid/CIK'),
    (b'>0001234567<', b'>0009999999<'),
    (b'>2025-12-31<', b'>2024-12-31<'),
    (b'>2025-01-01<', b'>2026-01-01<'),
    (b'>2025-01-01<', b'>not-a-date<'),
    (b'contextRef="c1"', b'contextRef="missing"'),
    (b'>10-K<', b'>10-Q<'),
    (b'>ZQXB<', b'>OTHER<'),
    (b'id="exchange"', b'id="title"'),
    (b'id="title"', b'id="invalid id"'),
    (b'name="dei:Security12bTitle"', b'name="dei:Security12bTitle" continuedAt="other"'),
    (b'name="dei:TradingSymbol"', b'name="dei:TradingSymbol" format="dei:other"'),
    (b'<table>', b'<ix:hidden><table>'),
    (b'<tr>', b'<div>'),
    (b'</html>', b'<span id="title"/></html>'),
    (b'<html ', b'<!DOCTYPE html [<!ENTITY canary "SECRET">]><html '),
    (b'Class A common stock, $0.01 par value', b'Common stock<ix:exclude> preferred</ix:exclude>'),
])
def test_context_namespace_ids_structure_and_unsupported_transforms_fail_closed(old, new):
    reject(args(body().replace(old, new)))


@pytest.mark.parametrize('mutation', [
    lambda a: a.update(body=a['body']+b' '),
    lambda a: a['receipt'].update(body_sha256='0'*64),
    lambda a: a['receipt'].update(body_bytes=True),
    lambda a: a['receipt'].update(http_status=True),
    lambda a: a['receipt'].update(http_status=403),
    lambda a: a['receipt'].update(media_type='application/pdf'),
    lambda a: a['receipt'].update(content_encoding='gzip'),
    lambda a: a['receipt'].update(url=URL+'?secret=CANARY'),
    lambda a: a['receipt'].update(url=URL.replace('/1234567/', '/9999999/')),
    lambda a: a['receipt'].update(url=URL.replace('www.sec.gov', 'attacker.invalid')),
    lambda a: a.update(expected_cik='1234567'),
    lambda a: a.update(expected_cik='0000000000'),
    lambda a: a.update(expected_symbol=[]),
    lambda a: a.update(form='20-F'),
    lambda a: a.update(filed_at='2099-01-01'),
    lambda a: a.update(filed_at='2025-01-01'),
    lambda a: a.update(reporting_period_end='2025-13-01'),
])
def test_wrong_metadata_body_or_receipt_never_exposes_diagnostics(mutation):
    a = args()
    mutation(a)
    assert 'CANARY' not in str(reject(a))


def test_same_symbol_across_rows_and_cross_row_field_mix_are_not_selected():
    raw = body()
    start, end = raw.index(b'<tr>'), raw.index(b'</tr>')+len(b'</tr>')
    second = raw[start:end].replace(b'id="', b'id="second-')
    reject(args(raw.replace(b'</table>', second+b'</table>')))
    reject(args(raw.replace(b'<td><ix:nonNumeric id="exchange"', b'</tr><tr><td><ix:nonNumeric id="exchange"')))


def test_context_namespaces_are_scoped_not_guessed_from_prefix_and_contexts_can_follow_facts():
    raw = body().replace(b'name="dei:Security12bTitle"',
        b'xmlns:dei="https://attacker.invalid/dei/2025" name="dei:Security12bTitle"')
    reject(args(raw))
    raw = body()
    start, end = raw.index(b'<ix:resources>'), raw.index(b'</ix:resources>')+len(b'</ix:resources>')
    resources = raw[start:end]
    raw = raw[:start]+raw[end:]
    raw = raw.replace(b'</body>', resources+b'</body>')
    assert extract_filed_share_class(**args(raw))['extracted']


def test_unrelated_long_generated_ids_do_not_discard_valid_cover_but_duplicate_still_rejects():
    unrelated = b'generated-' + b'x'*250
    raw = body().replace(b'</body>', b'<span id="'+unrelated+b'"/></body>')
    assert extract_filed_share_class(**args(raw))['extracted']
    reject(args(raw.replace(b'</body>', b'<span id="'+unrelated+b'"/></body>')))
    reject(args(body().replace(b'id="title"', b'id="'+unrelated+b'"')))


def test_well_formed_hidden_security_or_mixed_contexts_are_rejected():
    raw = body().replace(b'<table>', b'<ix:hidden><table>').replace(b'</table>', b'</table></ix:hidden>')
    reject(args(raw))
    raw = body().replace(b'<tr>', b'<div>').replace(b'</tr>', b'</div>')
    reject(args(raw))
    raw = body()
    begin, end = raw.index(b'<xbrli:context'), raw.index(b'</xbrli:context>')+len(b'</xbrli:context>')
    copy = raw[begin:end].replace(b'id="c1"', b'id="c2"')
    raw = raw.replace(b'</ix:resources>', copy+b'</ix:resources>')
    raw = raw.replace(b'id="exchange" name="dei:SecurityExchangeName" contextRef="c1"',
                      b'id="exchange" name="dei:SecurityExchangeName" contextRef="c2"')
    reject(args(raw))


def test_body_depth_and_dtd_resource_bounds_and_malformed_bytes():
    for raw in (b'', b'\xff', b'<html>', b'<x>'*129+b'</x>'*129):
        reject(args(raw))
    raw = body()
    bounded = raw+b' '*(MAX_FILING_BYTES-len(raw))
    assert extract_filed_share_class(**args(bounded))['extracted']
    reject(args(bounded+b' '))


def test_stream_clearing_preserves_nested_selected_text_and_later_context_resources():
    raw = body().replace(b'Class A common stock, $0.01 par value',
        b'<span>Class A </span><b>common stock</b>, $0.01 par value')
    raw = raw.replace(b'<table>', b'<div><span>discarded display text</span></div><table>')
    r = extract_filed_share_class(**args(raw))
    assert r['extracted']
    assert r['declared_security']['title'] == 'Class A common stock, $0.01 par value'


def test_encoded_declarations_large_id_and_node_flood_are_refused_within_byte_cap():
    reject(args(body().decode().encode('utf-16-le')))
    reject(args(body().replace(b'id="title"', b'id="'+b'x'*4097+b'"')))
    reject(args(body().replace(b'</body>', b'<span/>'*100001+b'</body>')))


@pytest.mark.parametrize('declaration', [b'<?xml version="1.0" encoding="unknown-codec"?>',
    b'<?xml version="1.0" encoding="iso-2022-jp"?>'])
def test_unsupported_encoding_declarations_cannot_escape_sanitized_rejection(declaration):
    reject(args(declaration+body()))


@pytest.mark.parametrize('attribute', [b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"',
    b'escape="true"', b'continuedAt=""'])
def test_nil_escape_and_empty_continuation_are_not_literal_security_claims(attribute):
    reject(args(body().replace(b'id="title"', b'id="title" '+attribute)))


def test_same_annual_eps_filing_binds_class_but_never_proves_splits_or_quote_unit():
    r = combined()
    assert r['binding_passed'] and r['same_eps_filing'] and r['declared_common_share_title_bound']
    assert r['quote_profile_eps']['source_eps']['document_type'] == '10-K'
    assert r['filed_share_class']['declared_security']['title'].startswith('Class A common stock')
    assert r['corporate_action_status'] == 'not_established_no_complete_event_evidence'
    for key in ('admitted', 'launch_ready', 'current_security_mapping_verified', 'split_compatibility_verified',
                'price_unit_verified', 'eps_class_compatibility_verified', 'market_pe_verified'):
        assert r[key] is False
    assert 'values' not in r and 'entry_pe_derivation' not in r


@pytest.mark.parametrize('mutation', [
    lambda a: a['receipt'].update(url=URL.replace('000123456726000001', '000123456726000002')),
    lambda a: a.update(filed_at='2026-02-21'),
])
def test_another_filing_or_date_cannot_supply_eps_class_binding(mutation):
    a = args()
    mutation(a)
    r = combined(a)
    assert not r['binding_passed'] and r['stage'] == 'same_eps_filing'


def test_quarterly_document_in_same_accession_cannot_masquerade_as_annual_eps_filing():
    a = args(body().replace(b'>10-K<', b'>10-Q<'))
    a['form'] = '10-Q'
    r = combined(a)
    assert not r['binding_passed'] and r['stage'] == 'same_eps_filing'


def test_already_passing_reports_or_event_lists_are_not_accepted_instead_of_raw_inputs():
    r = combined(inputs={'binding_passed': True, 'split_events': []})
    assert not r['binding_passed'] and r['stage'] == 'input_contract'
    a = binding_inputs()
    a['split_events'] = []
    assert combined(inputs=a)['stage'] == 'input_contract'
    a = binding_inputs()
    a['quote_receipt']['sha256'] = '0'*64
    assert combined(inputs=a)['stage'] == 'quote_profile_eps'


def test_fabricated_matching_receipt_is_not_origin_verification_or_split_clearance():
    a = args(combined_body(body('Class B common stock')))
    a['receipt']['unused_secret'] = 'CANARY'
    r = combined(a)
    assert r['binding_passed'] and not r['split_compatibility_verified']
    assert not r['filed_share_class']['independently_adjudicated']
    assert 'CANARY' not in str(r)
