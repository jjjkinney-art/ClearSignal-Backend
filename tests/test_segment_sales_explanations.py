"""Unseen synthetic segment labels, offline period and explanation binding."""
from copy import deepcopy
from dataclasses import replace
import re

import pytest

from test_segment_financial_context import CIK, xml, document
from app.providers.sec_segment_facts import parse_segment_tables
from app.services import segment_financial_context as service
from app.services.segment_sales_explanations import source_window, explanations

OPEN = "ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS"
CLOSE = 'ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK'
QUOTE = "Net sales of the Water Systems segment increased by $200,000 (100%), from $200,000 to $400,000, reflecting an increase in shipments from the segment's backlog."


def source(quote=QUOTE):
    old = xml()
    contexts = ''.join(re.findall(r'<x:context.*?</x:context>', old, re.S))
    new_contexts = contexts.replace('ctx0', 'new0').replace('ctx1', 'new1').replace('2024-', '2025-')
    old = old.replace('<x:unit', new_contexts + '<x:unit', 1)
    table = old[old.index('<tr><td colspan="10">Year ended'):old.index('</table>')]
    new = table.replace('2024', '2025').replace('ctx0', 'new0').replace('ctx1', 'new1')
    new = re.sub(r'id="([^"]+)"', r'id="new_\1"', new)
    new = new.replace('>200<', '>400<').replace('>800<', '>1,600<')
    old = old.replace(table, new + table)
    discussion = f'<p>{OPEN}</p><p>An overview of operations follows.</p><p>2025 COMPARED TO 2024</p><p>{quote}</p><p>2024 COMPARED TO 2023</p><p>Prior discussion.</p><p>{CLOSE}</p>'
    return old.replace('</body>', discussion + '</body>')


def extracted(body=None):
    doc = replace(document(body or source()), published_at='2026-03-13')
    return service.extract_segment_financial_context(doc, ticker='ZQXB', cik=CIK)[0]


def test_two_annual_proofs_and_exact_management_attribution():
    body = source()
    proof, = parse_segment_tables(body, cik=CIK)
    assert proof['period_end'] == '2025-12-31'
    assert proof['comparison_period']['period_end'] == '2024-12-31'
    value = service.bound_segment_financial_context(extracted(body), ticker='ZQXB', cik=CIK)
    row, = value['sales_explanations']
    assert row['quote'] == QUOTE and row['current_revenue_usd'] == 400000
    assert row['prior_revenue_usd'] == 200000 and row['attribution'] == 'management'
    assert row['limitation'] in extracted(body).summary
    assert value['sales_explanation_refs'][0]['quote'] == QUOTE


@pytest.mark.parametrize('before,after', [
    ('$200,000 (100%)', '$199,999 (100%)'), ('(100%)', '(99%)'),
    ('to $400,000', 'to $400,001'), ('from $200,000', 'from $200,001'),
    ('increased by', 'decreased by'), ('an increase in', 'an decrease in'),
    ('Water Systems', 'Other Segment'), ('reflecting', 'potentially reflecting'),
    ('shipments from the segment\'s backlog', 'future revenue growth'),
    ('Net sales of the Water Systems segment', 'Its sales'),
    ('from $200,000 to', 'to'), ('$', '€'),
])
def test_unsupported_sentence_preserves_original_segment_context(before, after):
    value = extracted(source(QUOTE.replace(before, after))).segment_disclosures[0]
    assert 'sales_explanations' not in value
    assert value['segment_context']['segments'][0]['revenue_usd'] == 400000


@pytest.mark.parametrize('change', ['amount', 'period', 'scope', 'label', 'hash', 'text', 'offset', 'ref', 'summary', 'missing', 'prior_ref', 'heading_ref', 'bool'])
def test_final_binding_rejects_tampering(change):
    evidence = deepcopy(extracted());v=evidence.segment_disclosures[0]
    if change == 'amount':v['sales_explanations'][0]['current_revenue_usd'] += 1
    elif change == 'period':v['proof']['comparison_period']['period_end'] = '2023-12-31'
    elif change == 'scope':v['proof']['comparison_period']['metrics']['revenue']['entries'][0]['observation']['scope']='consolidated'
    elif change == 'label':v['sales_explanations'][0]['label']='Other'
    elif change == 'hash':v['operating_explanation_source']['sha256']='0'*64
    elif change == 'text':v['operating_explanation_source']['text'] += 'Buy now.'
    elif change == 'offset':v['sales_explanations'][0]['start_offset'] += 1
    elif change == 'ref':v['sales_explanation_refs'][0]['quote']='Buy now.'
    elif change == 'summary':evidence.summary='Buy now.'
    elif change == 'missing':del v['sales_explanations']
    elif change == 'prior_ref':v['comparison_revenue_ref']['quote']='Other row.'
    elif change == 'heading_ref':v['sales_comparison_heading_refs'][0]['quote']='2020 COMPARED TO 2019'
    elif change == 'bool':v['sales_explanations'][0]['change_usd']=True
    assert service.bound_segment_financial_context(evidence,ticker='ZQXB',cik=CIK) is None


@pytest.mark.parametrize('before,after', [
    ('2025 COMPARED TO 2024', '2024 COMPARED TO 2023'),
    ('2024 COMPARED TO 2023', '2023 COMPARED TO 2022'),
    (OPEN, OPEN+' 20'), (CLOSE, 'No closing heading'),
    (OPEN, OPEN+' '+OPEN),
])
def test_section_or_comparison_ambiguity_withholds(before,after):
    assert 'sales_explanations' not in extracted(source().replace(before,after)).segment_disclosures[0]


def test_duplicate_explanations_and_single_year_withhold():
    assert 'sales_explanations' not in extracted(source(QUOTE+' '+QUOTE)).segment_disclosures[0]
    assert 'sales_explanations' not in extracted(xml()).segment_disclosures[0]


def test_generic_label_and_shipment_grammar():
    body=source().replace('Water Systems','Industrial Sensors').replace("shipments from the segment's backlog",'units shipped')
    assert extracted(body).segment_disclosures[0]['sales_explanations'][0]['label']=='Industrial Sensors'


def test_decrease_and_optional_printed_percentage():
    quote=QUOTE.replace('increased by $200,000 (100%)','decreased by $100,000 (50%)').replace('to $400,000','to $100,000').replace('an increase in','an decrease in')
    # Correct English remains required, not a direction guess from malformed prose.
    assert 'sales_explanations' not in extracted(source(quote).replace('>400<','>100<')).segment_disclosures[0]
    quote=quote.replace('an decrease','a decrease')
    assert extracted(source(quote).replace('>400<','>100<')).segment_disclosures[0]['sales_explanations'][0]['change_usd']==-100000
    quote=QUOTE.replace(' (100%)','')
    assert extracted(source(quote)).segment_disclosures[0]['sales_explanations'][0]['change_usd']==200000


@pytest.mark.parametrize('mutation', ['unit', 'namespace', 'duplicate', 'period', 'table', 'dimensions'])
def test_comparison_proof_must_reconstruct(mutation):
    doc=document(source());proof=deepcopy(doc.segment_financial_tables[0]);prior=proof['comparison_period']
    if mutation=='unit':prior['metrics']['revenue']['entries'][0]['observation']['unit']='EUR'
    elif mutation=='namespace':prior['metrics']['revenue']['entries'][0]['observation']['dimensions'][1]['axis_namespace']='https://bad.invalid/gaap'
    elif mutation=='duplicate':prior['metrics']['revenue']['entries'][1]['label']=prior['metrics']['revenue']['entries'][0]['label']
    elif mutation=='period':prior['period_end']='2022-12-31'
    elif mutation=='table':prior['table_number']+=1
    elif mutation=='dimensions':prior['metrics']['revenue']['entries'][0]['observation']['dimensions'][1]['member']='ChangedMember'
    assert explanations(proof,source_window(doc.text),cik=CIK)==[]


def test_missing_comparison_does_not_substitute_older_primary_year():
    body=source().replace('>400<','>40,0<')
    assert parse_segment_tables(body,cik=CIK)==()
