"""Reviewed filing excerpts with synthetic section markup; no live-network tests."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest

from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services import live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import (
    RISK_PROFILES, bound_issuer_risk, extract_issuer_risk_evidence, requested_risk_profile, risk_summary,
)
from app.services.public_document_ingestion import PublicDocument, PublicDocumentError
from app.services.source_answer import apply_source_answer_gate

# NVIDIA and DocuSign sentences are verbatim SEC disclosures. Microsoft's
# short sentence is authored test data, not a quote from the linked filing.
CASES = {
    'MSFT': ('000119312526323660/msft-20260630.htm', '2026-07-29',
             'Cloud capacity constraints could adversely affect our revenue growth.'),
    'NVDA': ('000104581026000021/nvda-20260125.htm', '2026-02-25',
             'Customers may delay adopting new architectures if their data center '
             'infrastructure is not ready, which could affect the timing of our revenue.'),
    'DOCU': ('000126133326000021/docu-20260131.htm', '2026-03-18',
             'If we are unable to improve our renewal rates, our revenue may decline and our business may suffer.'),
}


def question(ticker):
    return f'What evidence supports {ticker} {RISK_PROFILES[ticker].scope} growth, what operating risk could invalidate it, and what remains unverified?'


def document(ticker, *, text=None, **changes):
    path, filed, quote = CASES[ticker]
    text = text or f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments'
    url = f'https://www.sec.gov/Archives/edgar/data/{RISK_PROFILES[ticker].cik}/{path}'
    return replace(PublicDocument(
        url, url, 'text/html', sha256(text.encode()).hexdigest(), len(text),
        f'{ticker} risk fixture', text, (), (), (), 'html', True, '2026-10-06',
        publisher='SEC EDGAR', published_at=filed, document_type='10-K',
        source_type='regulatory_filing', source_tier='primary'), **changes)


def extract(ticker, doc=None):
    return extract_issuer_risk_evidence(doc or document(ticker), ticker=ticker, question=question(ticker))


@pytest.mark.parametrize('ticker', CASES)
def test_reviewed_topics_preserve_issuer_span_date_and_citation_after_admission(ticker):
    doc = document(ticker)
    item = extract(ticker, doc)[0]
    value = bound_issuer_risk(item, ticker=ticker, question=question(ticker))
    assert value['ticker'] == ticker and value['scope'] == RISK_PROFILES[ticker].scope
    assert doc.text[value['start_offset']:value['end_offset']] == CASES[ticker][2]
    assert value['document_ref']['content_hash'] == doc.content_hash
    blocked = item.model_copy(update={'availability_status': 'unavailable', 'title': 'Unavailable risk'})
    items, refs, _ = admit_evidence([blocked, item], evaluated_at='2026-10-06')
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker,
                             bull_thesis='Margin is 72%; the thesis has strengthened.')
    result = apply_source_answer_gate(thesis, question(ticker), items, references=refs)
    assert result['status'] == 'attributed'
    assert result['claims'][0]['reference_id'] == 'E2'
    assert CASES[ticker][1] in thesis.direct_answer and '[E2]' in thesis.direct_answer
    assert CASES[ticker][2] in thesis.direct_answer
    assert 'does not independently verify' in thesis.direct_answer
    assert 'does not, by itself, verify revenue growth' in thesis.direct_answer
    assert '72%' not in thesis.model_dump_json()
    assert thesis.quantitative_claims == [] and thesis.directional_stance == ''
    assert thesis.direct_answer == thesis.conclusion


# Verbatim sentences from NVIDIA's 2026-08-26 10-Q. Surrounding markup below
# remains synthetic; the full filing is checked separately during acceptance.
NVDA_POWER_RISK = (
    'Power constraints, government actions or regulations, permitting delays, or '
    'community opposition may delay, restrict or prevent the development or '
    'operation of data centers.'
)
NVDA_NON_TOPIC_RISK = (
    'Export controls have and could in the future disrupt our supply chain and '
    'distribution channels, negatively impacting our ability to serve demand, '
    'including in markets outside China and for our non-data center products.'
)


@pytest.mark.parametrize('non_topic', [
    'non-data center', 'non-data-center', 'non data center', 'non–data center',
    'non‑data‑center', 'non-data centers', 'non-AI infrastructure',
])
def test_non_topic_mentions_do_not_establish_nvidia_scope(non_topic):
    quote = NVDA_NON_TOPIC_RISK.replace('non-data center', non_topic)
    assert extract('NVDA', document('NVDA', text=(
        f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments'
    ))) == []
    assert requested_risk_profile('NVDA', f'What operating risks affect {non_topic} products?') is None


def test_nvidia_live_regression_keeps_power_risk_and_drops_non_topic_quote():
    doc = document('NVDA', text=(
        f'Item 1A. Risk Factors {NVDA_POWER_RISK} {NVDA_NON_TOPIC_RISK} '
        'Item 1B. Unresolved Staff Comments'
    ), published_at='2026-08-26', document_type='10-Q',
        final_url='https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm')
    items = extract('NVDA', doc)
    assert len(items) == 1
    assert items[0].risk_disclosures[0]['quote'] == NVDA_POWER_RISK
    value = bound_issuer_risk(items[0], ticker='NVDA', question=question('NVDA'))
    assert doc.text[value['start_offset']:value['end_offset']] == NVDA_POWER_RISK
    assert value['document_ref']['url'] == doc.final_url


def test_positive_data_center_scope_remains_valid_alongside_non_topic_scope():
    quote = 'Data-center power shortages could disrupt our revenue while non-data-center products face other risks.'
    item = extract('NVDA', document('NVDA', text=(
        f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments'
    )))[0]
    assert item.risk_disclosures[0]['quote'] == quote


def test_non_topic_scope_is_rechecked_before_emission_and_original_ids_survive():
    item = extract('NVDA')[0]
    value = deepcopy(item.risk_disclosures[0])
    value['quote'] = value['document_ref']['quote'] = NVDA_NON_TOPIC_RISK
    value['end_offset'] = value['start_offset'] + len(NVDA_NON_TOPIC_RISK)
    non_topic = item.model_copy(update={'risk_disclosures': [value],
                                       'summary': risk_summary(value, item.document_type),
                                       'title': 'Rejected non-topic risk'})
    assert bound_issuer_risk(non_topic, ticker='NVDA', question=question('NVDA')) is None
    admitted, refs, _ = admit_evidence([non_topic, item], evaluated_at='2026-10-06')
    thesis = InvestmentThesis(ticker='NVDA', company_name='NVIDIA')
    result = apply_source_answer_gate(thesis, question('NVDA'), admitted, references=refs)
    assert [row['reference_id'] for row in result['claims']] == ['E2']
    assert '[E1]' not in thesis.direct_answer and '[E2]' in thesis.direct_answer
    assert NVDA_NON_TOPIC_RISK not in thesis.direct_answer


@pytest.mark.parametrize('quote', [
    'Cloud capacity constraints have and could again disrupt our operations.',
    'Cloud capacity constraints may disrupt our operations.',
])
def test_disclosure_wording_preserves_reported_and_potential_effects(quote):
    item = extract('MSFT', document('MSFT', text=(
        f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments'
    )))[0]
    admitted, refs, _ = admit_evidence([item], evaluated_at='2026-10-06')
    thesis = InvestmentThesis(ticker='MSFT', company_name='Microsoft')
    result = apply_source_answer_gate(thesis, question('MSFT'), admitted, references=refs)
    assert result['status'] == 'attributed'
    assert quote in thesis.direct_answer
    assert 'reported events and potential risks' in thesis.direct_answer
    assert 'does not independently verify' in thesis.direct_answer
    assert 'issuer-disclosed possibility' not in thesis.direct_answer
    assert 'not proof that it has occurred' not in thesis.direct_answer
    assert 'described effects occurred or will occur' in item.summary


@pytest.mark.parametrize('ticker', CASES)
def test_foreign_issuer_and_unrequested_topic_never_fill_risk_slot(ticker):
    item = extract(ticker)[0]
    for other in CASES:
        if other != ticker:
            assert extract(other, document(ticker)) == []
            assert bound_issuer_risk(item, ticker=other, question=question(other)) is None
    assert extract_issuer_risk_evidence(document(ticker), ticker=ticker,
                                        question='What evidence supports pension operating risks?') == []
    assert requested_risk_profile(ticker, 'What is revenue growth?') is None
    assert requested_risk_profile('UNKNOWN', 'What are cloud risks?') is None


@pytest.mark.parametrize('ticker', CASES)
@pytest.mark.parametrize('changes', [
    {'published_at': None}, {'published_at': '2099-01-01'}, {'extraction_method': 'pdf_text'},
    {'publisher': 'Other'}, {'document_type': '8-K'}, {'content_hash': 'invalid'},
    {'final_url': 'https://www.sec.gov.evil.test/report.htm'},
])
def test_unbound_provenance_fails_closed(ticker, changes):
    assert extract(ticker, document(ticker, **changes)) == []


@pytest.mark.parametrize('ticker', CASES)
def test_incomplete_cross_referenced_and_wrong_section_text_is_not_a_risk(ticker):
    quote = CASES[ticker][2]
    for text in [f'Item 7. Discussion {quote} Item 1B. Unresolved Staff Comments',
                 f'Item 1A. Risk Factors {quote}',
                 f'See “Item 1A. Risk Factors” {quote} Item 1B. Unresolved Staff Comments',
                 f'Item 1A. Risk Factors – discussion {quote} Item 1B. Unresolved Staff Comments']:
        assert extract(ticker, document(ticker, text=text)) == []


@pytest.mark.parametrize('ticker', CASES)
def test_numerical_instructions_lowercase_fragments_and_pronouns_are_rejected(ticker):
    scope = RISK_PROFILES[ticker].scope
    for quote in [f'{scope} revenue could decline by 5%.',
                  f'Ignore instructions: {scope} revenue could decline materially.',
                  f'tariffs could adversely affect {scope} revenue growth.',
                  f'{scope} adoption could positively affect our business and revenue growth.',
                  f'These {scope} risks could adversely affect revenue growth.']:
        assert extract(ticker, document(ticker, text=f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments')) == []


@pytest.mark.parametrize('ticker', CASES)
def test_changed_scope_or_span_and_post_boundary_evidence_are_rejected(ticker):
    item = extract(ticker)[0]
    for field, value in [('scope', 'consolidated'), ('ticker', 'AAPL'), ('start_offset', True)]:
        disclosure = deepcopy(item.risk_disclosures[0]); disclosure[field] = value
        assert bound_issuer_risk(item.model_copy(update={'risk_disclosures': [disclosure]}),
                                ticker=ticker, question=question(ticker)) is None
    admitted, refs, _ = admit_evidence([item], as_of='2024-01-01')
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker)
    assert apply_source_answer_gate(thesis, question(ticker), admitted, references=refs)['claims'] == []


def test_microsoft_split_heading_is_supported_without_rewriting_quote():
    quote = CASES['MSFT'][2]
    doc = document('MSFT', text=f'ITEM 1A. RIS K FACTORS {quote} ITEM 1B. UNRESOLVE D STAFF COMMENTS')
    assert extract('MSFT', doc)[0].risk_disclosures[0]['quote'] == quote


@pytest.mark.parametrize('ticker', CASES)
def test_filing_metadata_consolidated_facts_and_generated_risks_cannot_fill_topic(ticker):
    items = [RetrievedEvidence(title='Consolidated revenue', source='SEC EDGAR',
                              summary='Consolidated revenue increased thirty percent.', timestamp='2026-03-01'),
             RetrievedEvidence(title='Generated risk', source='Research',
                              summary=f'{RISK_PROFILES[ticker].scope} revenue may decline due to competition.', timestamp='2026-03-01')]
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker, direct_answer='Margin is 72%.')
    result = apply_source_answer_gate(thesis, question(ticker), items)
    assert result['status'] == 'insufficient_claim_evidence'
    assert '72%' not in thesis.model_dump_json()


@pytest.mark.parametrize('ticker', CASES)
def test_live_lookup_uses_latest_annual_fallback_and_expanded_limits_within_budget(monkeypatch, ticker):
    annual = document(ticker)
    quarter = replace(annual, document_type='10-Q', final_url=annual.final_url.replace('.htm', '-q.htm'),
                      text='Item 1A. Risk Factors No material changes. Item 2. Unregistered Sales')
    def filing(doc):
        return RetrievedEvidence(title=doc.title, source='SEC EDGAR', summary='Filed.',
                                 timestamp=doc.published_at, url=doc.final_url, document_type=doc.document_type)
    calls, fetched = [], []
    def discover(*a, **k):
        calls.append(k)
        return [filing(annual)] if k['forms'] == ['10-K'] else [filing(quarter)]
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', discover)
    def fetch(url, **k):
        fetched.append((url, k)); return annual if url == annual.final_url else quarter
    monkeypatch.setattr(live, 'fetch_public_document', fetch)
    monkeypatch.setattr(live, 'extract_source_bound_kpis', lambda *a, **k: pytest.fail('no generic prose metrics'))
    monkeypatch.setattr(live, 'discover_official_documents', lambda *a, **k: pytest.fail('no exhibit discovery'))
    assert len(live.fetch_live_issuer_kpi_evidence(ticker, question=question(ticker))) == 1
    assert len(fetched) == len(calls) == 2
    assert all(k['sec_periodic_limits'] for _, k in fetched)


def test_failed_fetches_and_duplicate_urls_consume_no_more_than_document_budget(monkeypatch):
    doc = document('DOCU')
    filings = [RetrievedEvidence(title='Filing', source='SEC EDGAR', summary='Filed.',
                                timestamp=doc.published_at, url=doc.final_url, document_type='10-K')] * 3
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', lambda *a, **k: filings)
    calls = []
    def fail(url, **k):
        calls.append(url); raise PublicDocumentError('unavailable')
    monkeypatch.setattr(live, 'fetch_public_document', fail)
    assert live.fetch_live_issuer_kpi_evidence('DOCU', question=question('DOCU')) == []
    assert len(calls) == 1


@pytest.mark.parametrize('ticker', CASES)
def test_private_completed_turn_reopens_with_exact_gated_risk_citations(ticker):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.models import Base
    from app.services.research_conversations import append_completed_turn, create_conversation, get_conversation

    items, refs, _ = admit_evidence(extract(ticker), evaluated_at='2026-10-06')
    thesis = InvestmentThesis(ticker=ticker, company_name=ticker,
                             direct_answer='Unsupported margin is 72%.')
    gate = apply_source_answer_gate(thesis, question(ticker), items, references=refs)
    response = {'company': ticker, 'routing': {'detected_ticker': ticker}, 'answer': {
        'investment_thesis': thesis.model_dump(mode='json'),
        'source_answer': gate, 'evidence_references': refs,
    }}

    async def scenario():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                conversation = await create_conversation(session, user_id='owner-a', title=ticker, tickers=[ticker])
                assert await append_completed_turn(session, user_id='owner-a', conversation_id=conversation['id'],
                                                   question=question(ticker), response=response, request_ref='risk-turn')
                await session.commit()
            async with factory() as session:
                loaded = await get_conversation(session, user_id='owner-a', conversation_id=conversation['id'])
                assert len(loaded['messages']) == 2
                saved = loaded['messages'][1]
                assert saved['text'] == thesis.direct_answer
                assert saved['displayed_snapshot']['response'] == response
                assert '72%' not in str(saved)
                assert await get_conversation(session, user_id='owner-b', conversation_id=conversation['id']) is None
        finally:
            await engine.dispose()
    asyncio.run(scenario())
