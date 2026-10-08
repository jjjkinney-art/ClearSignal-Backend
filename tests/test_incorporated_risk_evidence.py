"""Authored incorporation/table fixtures; live filing acceptance is separate."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import socket

import pytest
import requests
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services import live_issuer_kpi_service as live, reviewed_incorporations as registry
from app.services.public_document_ingestion import fetch_public_document, PublicDocumentError, _ReviewedRiskTableExtractor
from app.services.reviewed_annual_layouts import reviewed_body_hash
from app.services.incorporated_risk_evidence import reviewed_incorporation_candidate
from app.services.issuer_risk_evidence import extract_issuer_risk_evidence, bound_issuer_risk, requested_risk_profile, risk_quote_rejections
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.services.research_conversations import create_conversation, append_completed_turn, get_conversation
from tests.test_company_evidence_expansion import CASES, official_directory
from tests.test_public_document_ingestion import _Response
from scripts.company_evidence_acceptance import run_case

CASE = next(c for c in CASES if c['ticker'] == 'NVO')
AREA = registry.NVO['risk_area']
DESCRIPTION = 'Findings in clinical activities could delay development of new medicines.'
IMPACT = '• Could adversely affect operating results.'
MITIGATION = 'Pre-clinical activities and consultations with regulators support development.'


@pytest.fixture
def source(monkeypatch):
    entry = {**registry.NVO, 'table_number': 1, 'row_hash': registry.risk_row_hash((AREA, DESCRIPTION, IMPACT))}
    parent = (f"<html><body><h2>Item 3.D. Risk Factors</h2><p>{entry['parent_quote']}</p>"
        f"<a href='{entry['exhibit_url']}'>Annual Report 2025</a><h2>Item 4. Information on the Company</h2></body></html>\n").encode()
    exhibit = ('<html><body><h2>Annual Report 2025 Risk management</h2><table>'
        '<tr><td rowspan="2"></td><th>Risk area</th><th>Description</th><th>Impact</th><th>Mitigating actions</th></tr>'
        f'<tr><td>{AREA}</td><td>{DESCRIPTION}</td><td>{IMPACT}</td><td>{MITIGATION}</td></tr>'
        '</table></body></html>\n').encode()
    entry['parent_canonical_hash'] = reviewed_body_hash(parent)
    entry['exhibit_canonical_hash'] = reviewed_body_hash(exhibit)
    monkeypatch.setattr(registry, 'REVIEWED_INCORPORATIONS', (entry,))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    bodies = {entry['parent_url']: parent, entry['exhibit_url']: exhibit}
    downloads = []
    def response(url, **kwargs):
        downloads.append(url)
        return _Response(bodies[url])
    monkeypatch.setattr(requests, 'get', response)
    filing = RetrievedEvidence(title='NVO 20-F',source='SEC EDGAR', summary='Filed', timestamp=entry['filed_at'], url=entry['parent_url'], document_type='20-F')
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', lambda *a, **k: [filing])
    return entry, bodies, downloads


def fetch(entry, role):
    return fetch_public_document(entry[role + '_url'], publisher='SEC EDGAR', published_at=entry['filed_at'],
        document_type=entry[role + '_form'], source_type='regulatory_filing', source_tier='primary',
        sec_periodic_limits=True, extract_tables=False)


def evidence(source):
    entry, _, _ = source
    parent = fetch(entry, 'parent')
    candidate, proof = reviewed_incorporation_candidate(parent, ticker='NVO', question=CASE['question'])
    exhibit = fetch(entry, 'exhibit')
    items = extract_issuer_risk_evidence(exhibit, ticker='NVO', question=CASE['question'], incorporation=proof)
    return parent, exhibit, items[0]


def test_live_path_admits_exact_row_and_incorporation_without_mitigation(source):
    entry, _, downloads = source
    items = live.fetch_live_issuer_kpi_evidence('NVO', question=CASE['question'], user_agent='fixture')
    assert len(items) == 1 and downloads == [entry['parent_url'], entry['exhibit_url']]
    value = items[0].risk_disclosures[0]
    assert value['quote'] == f'{AREA} {DESCRIPTION} {IMPACT}' and MITIGATION not in value['quote']
    assert value['table_columns']['mitigating_actions_excluded'] is True
    admitted, refs, _ = admit_evidence(items, evaluated_at='2026-10-08')
    thesis = InvestmentThesis(ticker='NVO', company_name=CASE['company'])
    result = apply_source_answer_gate(thesis, CASE['question'], admitted, references=refs)
    assert result['status'] == 'attributed' and '[E1]' in thesis.direct_answer
    assert 'incorporated by its 20-F' in thesis.direct_answer and 'mitigating actions are excluded' in thesis.direct_answer
    assert result['claims'][0]['incorporation'] == refs[0]['incorporation'] == value['incorporation']
    assert refs[0]['table_columns'] == value['table_columns']


def test_acceptance_checks_both_actual_documents_and_each_cell(source):
    row = run_case(CASE, user_agent='fixture', evaluated_at='2026-10-08', inspect_source=True)
    assert row['passed'] and row['documents_attempted'] == 2
    assert row['disclosures'][0]['incorporation_exact_span']
    assert row['disclosures'][0]['exact_span'] and row['disclosures'][0]['cited_in_answer']


@pytest.mark.parametrize('budget', [1, 2])
def test_incorporation_stays_within_document_attempt_budget(source, budget):
    _, _, downloads = source
    items = live.fetch_live_issuer_kpi_evidence('NVO', question=CASE['question'], max_documents=budget)
    assert len(downloads) == budget
    assert bool(items) == (budget == 2)


@pytest.mark.parametrize('alteration', ['missing_link', 'other_cik_link', 'missing_mapping', 'duplicate_mapping'])
def test_parent_without_unambiguous_statement_and_link_cannot_authorize_exhibit(source, alteration):
    entry, bodies, downloads = source
    body = bodies[entry['parent_url']]
    if alteration == 'missing_link': body = body.replace(entry['exhibit_url'].encode(), b'https://example.com/other.htm')
    if alteration == 'other_cik_link': body = body.replace(entry['exhibit_url'].encode(), entry['exhibit_url'].replace('/353278/', '/937966/').encode())
    if alteration == 'missing_mapping': body = body.replace(entry['parent_quote'].encode(), b'Refer to a different report.')
    if alteration == 'duplicate_mapping': body = body.replace(b'</body>', entry['parent_quote'].encode() + b'</body>')
    entry['parent_canonical_hash'] = reviewed_body_hash(body)
    bodies[entry['parent_url']] = body
    assert live.fetch_live_issuer_kpi_evidence('NVO', question=CASE['question']) == []
    assert downloads == [entry['parent_url']]


@pytest.mark.parametrize('field,value', [('final_url', 'https://www.sec.gov/Archives/edgar/data/937966/000035327826000012/nvo-20251231.htm'),
    ('document_type', '20-F/A'), ('published_at', '2026-02-05'), ('canonical_content_hash', 'a' * 64),
    ('publisher', 'Other'), ('source_tier', 'secondary')])
def test_parent_metadata_mismatch_withholds_candidate(source, field, value):
    entry, _, _ = source
    parent = replace(fetch(entry, 'parent'), **{field: value})
    assert reviewed_incorporation_candidate(parent, ticker='NVO', question=CASE['question']) is None


@pytest.mark.parametrize('role', ['parent', 'exhibit'])
def test_changed_source_bytes_reject_before_extraction(source, role):
    entry, bodies, _ = source
    bodies[entry[role + '_url']] += b'Changed visible source'
    with pytest.raises(PublicDocumentError, match='incorporation document hash mismatch'):
        fetch(entry, role)


def test_exhibit_failure_consumes_remaining_slot(source):
    entry, bodies, downloads = source
    bodies[entry['exhibit_url']] = b'Changed report'
    assert live.fetch_live_issuer_kpi_evidence('NVO', question=CASE['question']) == []
    assert downloads == [entry['parent_url'], entry['exhibit_url']]


@pytest.mark.parametrize('change', ['swapped_headers', 'missing_impact', 'numeric_impact', 'mitigation_only', 'duplicate_row', 'semantic_rowspan', 'truncated_table'])
def test_malformed_or_unsupported_table_never_answers(source, change):
    entry, bodies, _ = source
    body = bodies[entry['exhibit_url']]
    if change == 'swapped_headers': body = body.replace(b'<th>Impact</th><th>Mitigating actions</th>', b'<th>Mitigating actions</th><th>Impact</th>')
    if change == 'missing_impact': body = body.replace(IMPACT.encode(), b'')
    if change == 'numeric_impact': body = body.replace(IMPACT.encode(), b'Could adversely affect results by 10%.')
    if change == 'mitigation_only': body = body.replace(DESCRIPTION.encode(), b'Ordinary context.').replace(IMPACT.encode(), b'No adverse effect.').replace(MITIGATION.encode(), b'Clinical activities could delay development and adversely affect results.')
    if change == 'duplicate_row': body = body.replace(b'</table>', f'<tr><td>{AREA}</td><td>{DESCRIPTION}</td><td>{IMPACT}</td><td>{MITIGATION}</td></tr></table>'.encode())
    if change == 'semantic_rowspan': body = body.replace(f'<td>{AREA}</td>'.encode(), f'<td rowspan="2">{AREA}</td>'.encode())
    if change == 'truncated_table': body = body.replace(b'</table>', b'')
    entry['exhibit_canonical_hash'] = reviewed_body_hash(body)
    bodies[entry['exhibit_url']] = body
    assert live.fetch_live_issuer_kpi_evidence('NVO', question=CASE['question']) == []


@pytest.mark.parametrize('field,value', [('registry_id', 'unknown'), ('parent_canonical_hash', 'a' * 64),
    ('exhibit_url', 'https://example.com/report.htm'), ('parent_start_offset', -1), ('parent_end_offset', True),
    ('parent_document_ref', []), ('parent_document_ref', {})])
def test_forged_incorporation_is_rejected_at_extraction_and_answer(source, field, value):
    parent, exhibit, item = evidence(source)
    proof = deepcopy(item.risk_disclosures[0]['incorporation']);proof[field] = value
    assert extract_issuer_risk_evidence(exhibit, ticker='NVO', question=CASE['question'], incorporation=proof) == []
    forged = item.model_copy(deep=True);forged.risk_disclosures[0]['incorporation'] = proof
    assert bound_issuer_risk(forged, ticker='NVO', question=CASE['question']) is None


@pytest.mark.parametrize('field,value', [('url', 'https://example.com/report.htm'), ('section', 'Item 3.D. Risk Factors'),
    ('document_type', '20-F'), ('timestamp', '2026-02-05'), ('page', 41), ('source_tier', 'secondary'), ('summary', 'Invented summary')])
def test_item_tampering_cannot_borrow_table_binding(source, field, value):
    _, _, item = evidence(source)
    assert bound_issuer_risk(item.model_copy(update={field: value}), ticker='NVO', question=CASE['question']) is None


@pytest.mark.parametrize('field,value', [('incorporation', None), ('table_columns', []), ('exhibit_binding', {}),
    ('exhibit_binding', {'registry_id': 'other', 'raw_content_hash': 'a' * 64, 'canonical_content_hash': 'b' * 64}),
    ('quote', 'A fabricated clinical trial risk could adversely affect results.'), ('start_offset', True)])
def test_disclosure_tampering_withholds(source, field, value):
    _, _, item = evidence(source)
    forged = item.model_copy(deep=True);forged.risk_disclosures[0][field] = value
    assert bound_issuer_risk(forged, ticker='NVO', question=CASE['question']) is None


def test_no_proof_other_issuer_or_other_topic_cannot_borrow_report(source):
    _, exhibit, item = evidence(source)
    assert extract_issuer_risk_evidence(exhibit, ticker='NVO', question=CASE['question']) == []
    for ticker, question in [('LLY', CASE['question']), ('NVO', 'What are the patent risks?')]:
        assert bound_issuer_risk(item, ticker=ticker, question=question) is None


@pytest.mark.parametrize('quote', ['Clinical care could adversely affect results.', 'Our pipeline could adversely affect results.', 'Non-clinical activities could adversely affect results.'])
def test_clinical_topic_expansion_stays_specific(source, quote):
    profile = requested_risk_profile('NVO', CASE['question'])
    assert 'topic_scope' in risk_quote_rejections(quote, profile)


def test_snapshot_keeps_parent_and_exhibit_provenance_owned(source):
    _, _, item = evidence(source)
    restored = RetrievedEvidence.model_validate_json(item.model_dump_json())
    assert bound_issuer_risk(restored, ticker='NVO', question=CASE['question'])
    admitted, refs, _ = admit_evidence([restored], evaluated_at='2026-10-08')
    thesis = InvestmentThesis(ticker='NVO', company_name=CASE['company'])
    result = apply_source_answer_gate(thesis, CASE['question'], admitted, references=refs)
    snapshot = {'answer': {'investment_thesis': thesis.model_dump(mode='json'), 'source_answer': result, 'evidence_references': refs}}
    async def persist():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                conversation = await create_conversation(session, user_id='owner-a', title='NVO', tickers=['NVO'])
                await append_completed_turn(session, user_id='owner-a', conversation_id=conversation['id'], question=CASE['question'], response=snapshot, request_ref='nvo-incorporation-test')
                await session.commit()
            async with factory() as session:
                reopened = await get_conversation(session, user_id='owner-a', conversation_id=conversation['id'])
                assert reopened['messages'][1]['displayed_snapshot']['response'] == snapshot
                assert await get_conversation(session, user_id='owner-b', conversation_id=conversation['id']) is None
        finally: await engine.dispose()
    asyncio.run(persist())


@pytest.mark.parametrize('column', ['description', 'impact'])
def test_recomputed_forged_quote_cannot_change_reviewed_cell_content(source, column):
    from app.services.incorporated_risk_evidence import table_risk_summary
    _, _, item = evidence(source)
    forged = item.model_copy(deep=True)
    value = forged.risk_disclosures[0]
    value['table_columns'][column]['text'] = 'Clinical activities could adversely affect different operating results.'
    offset = value['start_offset']
    texts = []
    for key in ('risk_area', 'description', 'impact'):
        cell = value['table_columns'][key]; texts.append(cell['text'])
        cell['start_offset'] = offset; cell['end_offset'] = offset + len(cell['text'])
        offset = cell['end_offset'] + 1
    value['quote'] = ' '.join(texts); value['end_offset'] = offset - 1
    value['document_ref']['quote'] = value['quote']
    forged.summary = table_risk_summary(value)
    assert bound_issuer_risk(forged, ticker='NVO', question=CASE['question']) is None


@pytest.mark.parametrize('declared', [True, False])
def test_registered_exhibit_still_has_fifteen_mb_ceiling(source, monkeypatch, declared):
    entry, _, _ = source
    response = _Response(b'x' * 15_000_001, headers={'Content-Length': '15000001'} if declared else {})
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    with pytest.raises(PublicDocumentError, match='size limit'):
        fetch(entry, 'exhibit')
    assert response.closed


def test_unregistered_exhibit_and_redirect_cannot_borrow_periodic_limits(source, monkeypatch):
    entry, _, _ = source
    other = entry['exhibit_url'].replace('nvo-20251231_d2.htm', 'other.htm')
    with pytest.raises(PublicDocumentError, match='SEC periodic HTML filing'):
        fetch_public_document(other, publisher='SEC EDGAR', published_at=entry['filed_at'],
            document_type='EX-15.1', source_type='regulatory_filing', source_tier='primary', sec_periodic_limits=True)
    response = _Response(b'', status=302, headers={'Location': other})
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    with pytest.raises(PublicDocumentError, match='SEC periodic HTML filing'):
        fetch(entry, 'exhibit')
    assert response.closed


@pytest.mark.parametrize('role', ['parent', 'exhibit'])
@pytest.mark.parametrize('field', ['quote', 'content_hash', 'published_at', 'section'])
def test_missing_optional_reference_fields_fail_closed(source, role, field):
    _, _, item = evidence(source)
    forged = item.model_copy(deep=True)
    value = forged.risk_disclosures[0]
    ref = value['incorporation']['parent_document_ref'] if role == 'parent' else value['document_ref']
    ref.pop(field)
    assert bound_issuer_risk(forged, ticker='NVO', question=CASE['question']) is None
