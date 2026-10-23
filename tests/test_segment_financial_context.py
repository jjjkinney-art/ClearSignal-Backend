"""Synthetic segment identities; no real source/model requests or holdouts."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from app.providers import sec_segment_facts as parser
from app.providers.sec_inline_facts import parse_inline_observations
from app.services import segment_financial_context as service, thesis_disclosures as disclosures
from app.services.public_document_ingestion import PublicDocument, _HTMLTextExtractor
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from test_financial_thesis_foundation import pair

CIK = '1234567'
URL = 'https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/company.htm'
LABELS = ('Water Systems', 'Clinical Devices')


def xml(labels=LABELS):
    def context(i):
        return f'''<x:context id="ctx{i}"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">{CIK}</x:identifier><x:segment>
        <d:explicitMember dimension="s:ConsolidationItemsAxis">g:OperatingSegmentsMember</d:explicitMember>
        <d:explicitMember dimension="g:StatementBusinessSegmentsAxis">custom:UnknownMember{i}</d:explicitMember>
        </x:segment></x:entity><x:period><x:startDate>2024-01-01</x:startDate><x:endDate>2024-12-31</x:endDate></x:period></x:context>'''
    def fact(i, metric, value):
        sign = ' sign="-"' if value < 0 else ''
        f = f'<ix:nonFraction id="{metric}{i}" name="g:{metric}" contextRef="ctx{i}" unitRef="usd" format="t:num-dot-decimal" scale="3" decimals="-3"{sign}>{abs(value):,}</ix:nonFraction>'
        return '<td>$</td><td>' + ('(' if value < 0 else '') + f + '</td><td>' + (')' if value < 0 else '') + '</td>'
    revenue = '<tr><td>External net sales</td>' + fact(0, 'Revenues', 200) + fact(1, 'Revenues', 800) + '<td>$</td><td>1,000</td><td></td></tr>'
    income = '<tr><td>Operating profit (loss)</td>' + fact(0, 'OperatingIncomeLoss', -20) + fact(1, 'OperatingIncomeLoss', 100) + '<td>$</td><td>80</td><td></td></tr>'
    return f'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:x="http://www.xbrl.org/2003/instance"
    xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:d="http://xbrl.org/2006/xbrldi"
    xmlns:s="http://fasb.org/srt/2025" xmlns:g="http://fasb.org/us-gaap/2025" xmlns:custom="https://issuer.invalid/taxonomy/2025"
    xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:t="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">
    <body><ix:header><ix:resources>{context(0)}{context(1)}<x:unit id="usd"><x:measure>iso:USD</x:measure></x:unit></ix:resources></ix:header>
    <p>Item 1. Business Products are sold directly to retailers and also through independent distributors. Item 1A. Risk Factors Supply disruption could affect operations. Item 1B. Unresolved Staff Comments</p>
    <p>{parser.DEFINITION} Costs associated with corporate activities (such as treasury management) and the assets associated with such activities are included within the {labels[0]} segment for all periods presented.</p>
    <table><tr><td colspan="10">(in thousands)</td></tr><tr><td></td><td colspan="3">{labels[0]}</td><td colspan="3">{labels[1]}</td><td colspan="3">Total</td></tr>
    <tr><td colspan="10">Year ended December 31, 2024</td></tr>{revenue}{income}</table></body></html>'''


def document(source=None):
    source = source or xml()
    p = _HTMLTextExtractor(); p.feed(source)
    title, text, sections, _ = p.result(preserve_sec_business=True, preserve_sec_risk=True)
    return PublicDocument(URL, URL, 'text/html', hashlib.sha256(source.encode()).hexdigest(), len(source.encode()),
        title, text, sections, (), (), 'html', True, '2025-08-02', publisher='SEC EDGAR',
        published_at='2025-08-01', document_type='10-K', source_type='regulatory_filing', source_tier='primary',
        segment_financial_tables=parser.parse_segment_tables(source, cik=CIK))


def item(source=None):
    return service.extract_segment_financial_context(document(source), ticker='ZQXB', cik=CIK)[0]


@pytest.mark.parametrize('labels', [LABELS, ('Cloud Platforms', 'Industrial Sensors'), ('Consumer / Retail', 'Medical Devices')])
def test_dimension_and_visible_header_binding_without_member_name_guess(labels):
    source = xml(labels)
    proof, = parser.parse_segment_tables(source, cik=CIK)
    rows = parser.reconstruct(proof, cik=CIK)
    assert [r['label'] for r in rows] == list(labels)
    assert [(r['revenue_usd'], r['operating_income_usd']) for r in rows] == [(200000, -20000), (800000, 100000)]
    assert rows[0]['dimensions'][1]['member'] == 'UnknownMember0'
    # Dimensional facts never leak into the consolidated parser.
    assert parse_inline_observations(source, cik=CIK, concepts=parser.CONCEPTS) == ()
    result = service.bound_segment_financial_context(item(source), ticker='ZQXB', cik=CIK)
    assert result['segment_context']['totals_reconciled'] is False
    assert result['proof']['allocation'] in item(source).summary
    assert 'operating loss $20,000' in item(source).summary


@pytest.mark.parametrize('before,after', [
    ('>1234567<', '>9876543<'),
    ('http://www.sec.gov/CIK', 'https://bad.invalid/CIK'),
    ('http://fasb.org/srt/2025', 'https://bad.invalid/srt/2025'),
    ('g:OperatingSegmentsMember', 'g:ConsolidatedEntitiesMember'),
    ('g:StatementBusinessSegmentsAxis', 'g:ProductOrServiceAxis'),
    ('d:explicitMember', 'd:typedMember'),
    ('iso:USD', 'iso:EUR'),
    ('<td>$</td>', '<td>€</td>'),
    (' sign="-"', ''),
    ('scale="3"', 'scale="6"'),
    ('t:num-dot-decimal', 't:num-comma-decimal'),
    ('2024-01-01', '2024-10-01'),
    ('id="Revenues1"', 'id="Revenues0"'),
    ('colspan="3"', 'colspan="2"'),
    ('rowspan="1"', 'rowspan="2"'),
    ('<table>', '<table style="display:none">'),
    (parser.DEFINITION, 'Operating profit is an expected future result.'),
    ('for all periods presented.', 'for future periods only.'),
    ('Water Systems</td>', 'Different Segment</td>'),
    ('>200<', '>20,0<'),
    ('<ix:nonFraction id="Revenues0"', '<ix:nonFraction hidden="hidden" id="Revenues0"'),
])
def test_unsupported_or_contaminated_sources_fail_closed(before, after):
    source = xml()
    if before not in source:
        # Exercise row-span rejection explicitly rather than a vacuous mutation.
        assert before == 'rowspan="1"'
        source = source.replace('<td>', '<td rowspan="1">')
    assert before in source
    assert parser.parse_segment_tables(source.replace(before, after), cik=CIK) == ()


@pytest.mark.parametrize('suffix', ['<span id="Revenues0"/>', '<span id="ctx0"/>', '<broken>'])
def test_entire_document_checked_before_admission(suffix):
    assert parser.parse_segment_tables(xml().replace('</body>', suffix + '</body>'), cik=CIK) == ()


@pytest.mark.parametrize('change', ['amount', 'label', 'scope', 'currency', 'bool', 'row', 'fact', 'definition', 'allocation', 'ref', 'income_ref', 'summary', 'issuer', 'period', 'stale'])
def test_final_binding_reconstructs_observation_and_display_proof(change):
    evidence = deepcopy(item())
    value = evidence.segment_disclosures[0]
    if change == 'amount': value['segment_context']['segments'][0]['revenue_usd'] += 1
    elif change == 'label': value['proof']['metrics']['revenue']['entries'][0]['label'] = 'Other'
    elif change == 'scope': value['proof']['metrics']['revenue']['entries'][0]['observation']['scope'] = 'consolidated'
    elif change == 'currency': value['segment_context']['currency'] = 'EUR'
    elif change == 'bool': value['segment_context']['totals_reconciled'] = 0
    elif change == 'row': value['proof']['metrics']['revenue']['cells'][2]['text'] = '999'
    elif change == 'fact': value['proof']['metrics']['revenue']['entries'][0]['observation']['fact_id'] = 'other'
    elif change == 'definition': value['proof']['definition'] = 'Operating profit is future earnings.'
    elif change == 'allocation': value['proof']['allocation'] = 'No corporate allocation.'
    elif change == 'ref': value['document_ref']['content_hash'] = 'bad'
    elif change == 'income_ref': value['operating_income_ref']['quote'] = '999'
    elif change == 'summary': evidence.summary = 'Buy now.'
    elif change == 'issuer': value['ticker'] = 'OTHER'
    elif change == 'period': evidence.reporting_period_end = '2023-12-31'
    elif change == 'stale': evidence.freshness_status = 'stale'
    assert service.bound_segment_financial_context(evidence, ticker='ZQXB', cik=CIK) is None


def test_normal_retrieval_and_final_answer_are_additive_and_keep_gaps(monkeypatch):
    monkeypatch.setattr(disclosures.sec_provider, '_load_ticker_cik_map', lambda: {'ZQXB': CIK})
    monkeypatch.setattr(disclosures.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [SimpleNamespace(url=URL, timestamp='2025-08-01', document_type='10-K')])
    calls = []
    def saved(url, **kwargs):
        calls.append((url, kwargs)); return document()
    monkeypatch.setattr(disclosures, 'fetch_public_document', saved)
    items = disclosures.fetch_thesis_disclosures('ZQXB', question='What is the investment thesis for ZQXB?')
    assert len(calls) == 1 and calls[0][1]['segment_fact_cik'] == CIK
    assert sum(bool(i.segment_disclosures) for i in items) == 1
    admitted, refs, _ = admit_evidence(pair(ticker='ZQXB', cik=CIK) + items, evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker='ZQXB', company_name='Invented issuer')
    result = apply_source_answer_gate(thesis, 'What is the investment thesis for ZQXB? Cite material claims.', admitted, references=refs)
    claims = [c for c in result['claims'] if c['claim_kind'] == 'issuer_segment_financial_context']
    assert len(claims) == 1
    assert 'Water Systems: external revenue $200,000; operating loss $20,000' in thesis.direct_answer
    assert claims[0]['caveat_refs'][1]['quote'] in thesis.direct_answer
    assert claims[0]['operating_income_ref']['quote'] == claims[0]['source_proof']['metrics']['operating_income']['row_text']
    assert f"[{claims[0]['reference_id']}]" in thesis.direct_answer
    assert result['status'] == 'partial'
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert result['business_context_coverage']['complete_business_model'] is False
    opening = thesis.direct_answer.split('Positive, rising reported comparisons:')[0]
    assert 'Reported segment economics (2024-01-01 to 2024-12-31; USD)' in opening
    assert 'Water Systems: external sales $200,000, operating loss $20,000' in opening
    assert 'Clinical Devices: external sales $800,000, operating profit $100,000' in opening
    assert claims[0]['source_proof']['allocation'] in opening
    assert f"[{claims[0]['reference_id']}]" in opening
    assert 'neither persistence nor the causes of later consolidated results' in opening
    assert 'Current period: 2025-04-01 to 2025-06-30' in opening


def test_newer_incomplete_period_cannot_fall_back_to_older_table_rows():
    newer = '<tr><td colspan="10">Year ended December 31, 2025</td></tr>'
    assert parser.parse_segment_tables(xml().replace('</table>', newer + '</table>'), cik=CIK) == ()


def test_conflicting_duplicate_observation_and_local_namespace_rebinding_fail_closed():
    nested = xml().replace('<table>', '<table><tr><td><table>').replace('</table>', '</table></td></tr></table>')
    assert parser.parse_segment_tables(nested, cik=CIK) == ()
    duplicate = '<ix:nonFraction id="duplicate" name="g:Revenues" contextRef="ctx0" unitRef="usd" format="t:num-dot-decimal" scale="3" decimals="-3">201</ix:nonFraction>'
    assert parser.parse_segment_tables(xml().replace('</body>', duplicate + '</body>'), cik=CIK) == ()
    assert parser.parse_segment_tables(xml().replace('<d:explicitMember dimension="s:',
        '<d:explicitMember xmlns:s="https://untrusted.invalid/axis" dimension="s:'), cik=CIK) == ()


def test_ingestion_uses_same_bounded_download_and_checks_before_fetch(monkeypatch):
    import socket
    import requests
    from app.services.public_document_ingestion import fetch_public_document, PublicDocumentError
    from test_public_document_ingestion import _Response
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    calls = []
    response = _Response(xml().encode())
    def saved(url, **kwargs):
        calls.append(url); return response
    monkeypatch.setattr(requests, 'get', saved)
    with pytest.raises(PublicDocumentError, match='SEC periodic limits'):
        fetch_public_document(URL, segment_fact_cik=CIK)
    assert calls == []
    doc = fetch_public_document(URL, publisher='SEC EDGAR', published_at='2025-08-01',
        document_type='10-K', source_type='regulatory_filing', source_tier='primary',
        sec_periodic_limits=True, extract_tables=False, preserve_sec_business=True, segment_fact_cik=CIK)
    assert calls == [URL] and response.closed
    assert len(doc.segment_financial_tables) == 1
    assert doc.content_hash == hashlib.sha256(xml().encode()).hexdigest()
    assert service.extract_segment_financial_context(doc, ticker='ZQXB', cik=CIK)


@pytest.mark.parametrize('changes', [
    {'document_type': '10-Q'}, {'publisher': 'Other'}, {'source_tier': 'secondary'},
    {'extraction_method': 'pdf'}, {'text_ready': False},
    {'final_url': URL.replace('/1234567/', '/7654321/')},
    {'published_at': '2023-01-01'}, {'published_at': '2099-01-01'},
])
def test_document_and_chronology_gates(changes):
    assert service.extract_segment_financial_context(replace(document(), **changes), ticker='ZQXB', cik=CIK) == []


def test_table_context_must_not_drop_an_unsupported_segment():
    unrelated = xml().replace('<table>', '<p>A different accounting discussion intervenes.</p><table>')
    assert parser.parse_segment_tables(unrelated, cik=CIK) == ()
    # One inconsistent row must not silently produce an apparently complete set.
    source = xml().replace('name="g:Revenues" contextRef="ctx1"', 'name="g:Assets" contextRef="ctx1"')
    assert parser.parse_segment_tables(source, cik=CIK) == ()
