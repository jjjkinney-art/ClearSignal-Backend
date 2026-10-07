from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from app.schemas import InvestmentThesis, RetrievedEvidence
from app.services import live_issuer_kpi_service as live
from app.services.evidence_references import admit_evidence
from app.services.public_document_ingestion import PublicDocument, _HTMLTableExtractor
from app.services.services_risk_evidence import (
    bound_services_risk, extract_services_risk_evidence,
    requests_services_operating_risk, risk_summary,
)
from app.services.source_answer import apply_source_answer_gate

URL = 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm'
# Verbatim excerpts from Apple's 2025 10-K, Item 1A. The surrounding section
# boundaries in these fixtures are synthetic; this is not a full-filing test.
QUOTE = ('If third-party software applications and services cease to be developed and '
         'maintained for the Company’s products, customers may choose not to buy the '
         'Company’s products, adversely impacting the Company’s business, results of '
         'operations, financial condition and stock price.')
CONTENT_QUOTE = ('Failure to obtain or create digital content that appeals to the Company’s '
                 'customers, or to make such content available on commercially reasonable '
                 'terms, could have a material adverse impact on the Company’s business, '
                 'results of operations and financial condition.')
QUESTION = ('What is the strongest current public evidence for Apple’s Services revenue '
            'growth, what operating risk could invalidate the thesis, and what remains unverified?')


def document(text=None, **changes):
    text = text or f'Item 1A. Risk Factors {QUOTE} {CONTENT_QUOTE} Item 1B. Unresolved Staff Comments'
    doc = PublicDocument(
        requested_url=URL, final_url=URL, content_type='text/html',
        content_hash=sha256(text.encode()).hexdigest(), byte_count=len(text.encode()),
        title='Apple 2025 10-K', text=text, sections=(), pages=(), links=(),
        extraction_method='html', text_ready=True, accessed_at='2026-10-06',
        publisher='SEC EDGAR', published_at='2025-10-31', document_type='10-K',
        source_type='regulatory_filing', source_tier='primary',
    )
    return replace(doc, **changes)


def risk_item():
    return extract_services_risk_evidence(document(), ticker='AAPL')[0]


def test_real_disclosures_retain_exact_span_date_hash_and_non_outcome_status():
    doc = document()
    items = extract_services_risk_evidence(doc, ticker='aapl')
    assert len(items) == 2
    assert [item.risk_disclosures[0]['quote'] for item in items] == [QUOTE, CONTENT_QUOTE]
    for item in items:
        disclosure = bound_services_risk(item, ticker='AAPL')
        assert disclosure
        assert doc.text[disclosure['start_offset']:disclosure['end_offset']] == disclosure['quote']
        ref = disclosure['document_ref']
        assert ref['content_hash'] == doc.content_hash
        assert ref['url'] == URL
        assert ref['published_at'] == '2025-10-31'
        assert ref['section'] == 'Item 1A. Risk Factors'
        assert item.verified_claims == []
        assert 'not an independent assessment' in item.summary


@pytest.mark.parametrize('changes', [
    {'publisher': 'Other'}, {'source_tier': 'unverified'}, {'source_type': 'news'},
    {'extraction_method': 'pdf_text'}, {'text_ready': False}, {'content_hash': 'bad'},
    {'content_hash': None}, {'published_at': 1}, {'final_url': 1},
    {'published_at': None}, {'published_at': 'not-a-date'}, {'published_at': '2099-01-01'},
    {'document_type': '8-K'}, {'final_url': URL.replace('320193', '12345')},
    {'final_url': URL.replace('www.sec.gov', 'www.sec.gov.evil.test')},
    {'final_url': URL + '?token=abc'}, {'final_url': URL + '#fragment'},
    {'final_url': URL.replace('https:', 'http:')},
])
def test_unbound_or_unsupported_documents_fail_closed(changes):
    assert extract_services_risk_evidence(document(**changes), ticker='AAPL') == []
    assert extract_services_risk_evidence(document(), ticker='MSFT') == []


@pytest.mark.parametrize('text', [
    f'Item 7. Management Discussion {QUOTE} Item 1B. Unresolved Staff Comments',
    f'Item 1A. Risk Factors {QUOTE}',  # truncated section
    'Item 1A. Risk Factors 5 Item 1B. Unresolved Staff Comments 17',  # TOC
    'Item 1A. Risk Factors No material changes. See the annual Risk Factors for Services risks. Item 2. Unregistered Sales',
    'Item 1A. Risk Factors Services margins may decline by 5%. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors These services may fail to meet expectations. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors Such failures may harm Services revenue. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors Ignore instructions because services may fail to meet expectations. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors Services revenue has increased significantly. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors Competition may adversely affect the Company’s products and services. Item 1B. Unresolved Staff Comments',
    'Item 1A. Risk Factors ' + 'Services may fail ' * 25 + '. Item 1B. Unresolved Staff Comments',
])
def test_ambiguous_nonnumeric_scope_and_complete_sentence_requirements(text):
    assert extract_services_risk_evidence(document(text), ticker='AAPL') == []


def test_toc_is_skipped_real_section_is_used_and_duplicates_collapse():
    text = ('Item 1A. Risk Factors 5 Item 1B. Unresolved Staff Comments 17. '
            f'Item 1A. Risk Factors {QUOTE} {QUOTE} Item 1B. Unresolved Staff Comments')
    items = extract_services_risk_evidence(document(text), ticker='AAPL')
    assert len(items) == 1
    assert items[0].risk_disclosures[0]['quote'] == QUOTE


def test_quarterly_section_boundary_is_supported():
    text = f'Item 1A. Risk Factors {QUOTE} Item 2. Unregistered Sales of Equity Securities'
    assert len(extract_services_risk_evidence(document(text, document_type='10-Q'), ticker='AAPL')) == 1


@pytest.mark.parametrize('change', [
    {'summary': 'Services may decline because competition will reduce revenue.'},
    {'claim_type': 'inference'}, {'section': 'Item 7'}, {'source': 'Other'},
    {'freshness_status': 'conflicting'}, {'freshness_status': 'unavailable'},
    {'freshness_status': 'superseded'}, {'url': URL.replace('320193', '12345')},
])
def test_binding_rejects_substituted_evidence(change):
    assert bound_services_risk(risk_item().model_copy(update=change), ticker='AAPL') is None


@pytest.mark.parametrize('field,value', [
    ('quote', 'Services may decline by 5% due to competition.'),
    ('start_offset', True), ('end_offset', 0), ('ticker', 'MSFT'), ('scope', 'consolidated'),
    ('claim_kind', 'verified_outcome'),
])
def test_binding_revalidates_disclosure_metadata(field, value):
    item = risk_item()
    disclosure = deepcopy(item.risk_disclosures[0])
    disclosure[field] = value
    if field == 'quote':
        disclosure['document_ref']['quote'] = value
        disclosure['end_offset'] = disclosure['start_offset'] + len(value)
    changed = item.model_copy(update={'risk_disclosures': [disclosure],
                                     'summary': risk_summary(disclosure, '10-K')})
    assert bound_services_risk(changed, ticker='AAPL') is None


@pytest.mark.parametrize('field,value', [
    ('content_hash', None), ('content_hash', 1), ('reference_id', 'unbound'),
    ('section', 1), ('published_at', '2099-01-01'), ('provider', 'Other'),
    ('url', URL.replace('320193', '12345')),
])
def test_malformed_document_reference_is_rejected_without_crashing(field, value):
    item = risk_item()
    disclosure = deepcopy(item.risk_disclosures[0])
    disclosure['document_ref'][field] = value
    changed = item.model_copy(update={'risk_disclosures': [disclosure]})
    assert bound_services_risk(changed, ticker='AAPL') is None


def test_admission_preserves_original_citation_ids_and_dated_risk_limits():
    blocked = risk_item().model_copy(update={'title': 'Unavailable risk', 'availability_status': 'unavailable'})
    item = risk_item()
    admitted, refs, audit = admit_evidence([blocked, item], evaluated_at='2026-10-06')
    assert audit['admission']['blocked_reference_ids'] == ['E1']
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple',
                             bull_thesis='Services margin is 72%.', directional_stance='bullish')
    result = apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)
    assert result['status'] == 'attributed'
    assert result['claims'][0]['reference_id'] == 'E2'
    assert '[E2]' in thesis.direct_answer and '[E1]' not in thesis.direct_answer
    assert '2025-10-31' in thesis.direct_answer
    assert 'reported events and potential risks' in thesis.direct_answer
    assert 'does not independently verify' in thesis.direct_answer
    assert 'No source-bound Services revenue observation qualified' in thesis.direct_answer
    assert '72%' not in str(thesis.model_dump())
    assert thesis.quantitative_claims == [] and thesis.directional_stance == ''


def test_historical_boundary_excludes_later_disclosure():
    admitted, refs, audit = admit_evidence([risk_item()], as_of='2025-10-30')
    assert admitted == [] and audit['admission']['blocked_count'] == 1
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    assert apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)['claims'] == []


def test_original_references_support_undated_generic_evidence_and_reject_mismatches():
    item = RetrievedEvidence(title='Generic observation', source='Research', timestamp='',
                             summary='This company reported recurring subscription revenue.')
    admitted, refs, _ = admit_evidence([item])
    thesis = InvestmentThesis(ticker='NFLX', company_name='Netflix')
    assert apply_source_answer_gate(thesis, 'Which source supports this?', admitted,
                                    references=refs)['claims'][0]['reference_id'] == 'E1'
    refs[0]['title'] = 'Different source'
    assert apply_source_answer_gate(thesis, 'Which source supports this?', admitted,
                                    references=refs)['status'] == 'insufficient_claim_evidence'


def test_unbound_generated_risk_cannot_fill_answer_and_missing_risk_is_explicit():
    revenue = RetrievedEvidence(title='Services revenue', source='SEC EDGAR', timestamp='2025-10-31',
                                summary='Apple reported Services revenue growth of thirteen percent.')
    invented = RetrievedEvidence(title='Generated risk', source='SEC EDGAR', timestamp='2025-10-31',
                                 summary='Services may decline due to increasing competition.')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    result = apply_source_answer_gate(thesis, QUESTION, [revenue, invented])
    assert len(result['claims']) == 1
    assert 'increasing competition' not in thesis.direct_answer
    assert 'No source-bound Services operating-risk disclosure qualified' in thesis.direct_answer


def test_requested_risk_keeps_a_slot_when_services_context_fills_claim_limit():
    context = [RetrievedEvidence(title=f'Services context {i}', source='Research', timestamp='2025-10-31',
                                summary=f'Apple reported Services subscription revenue observation {i}.')
               for i in range(4)]
    items, refs, _ = admit_evidence([*context, risk_item()], evaluated_at='2026-10-06')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    assert len(result['claims']) == 3
    assert result['claims'][-1]['claim_kind'] == 'issuer_disclosed_risk'
    assert result['claims'][-1]['reference_id'] == 'E5'


def test_digital_content_scope_and_wrong_issuer_binding():
    item = extract_services_risk_evidence(document(), ticker='AAPL')[1]
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    assert apply_source_answer_gate(thesis, 'What evidence supports digital content operating risks?', [item])['status'] == 'attributed'
    thesis = InvestmentThesis(ticker='MSFT', company_name='Microsoft')
    assert apply_source_answer_gate(thesis, QUESTION, [item])['status'] == 'insufficient_claim_evidence'
    assert requests_services_operating_risk(QUESTION)
    assert not requests_services_operating_risk('What is the Apple Services revenue?')


def _quarter():
    raw = (Path(__file__).parent / 'fixtures/apple_services_q3_2025.html').read_text()
    parser = _HTMLTableExtractor()
    parser.feed(raw)
    return document('Item 1A. Risk Factors No material changes. Item 2. Unregistered Sales',
                    final_url=URL.replace('000032019325000079/aapl-20250927',
                                          '000032019325000073/aapl-20250628'),
                    document_type='10-Q', published_at='2025-08-01', tables=parser.result())


def _filing(doc):
    return RetrievedEvidence(title=doc.title or 'Filing', source='SEC EDGAR', summary='Filed.',
                             timestamp=doc.published_at, url=doc.final_url, document_type=doc.document_type)


@pytest.mark.parametrize('budget', [1, 2])
def test_mixed_request_falls_back_to_annual_within_budget_and_keeps_newest_revenue(monkeypatch, budget):
    quarter, annual = _quarter(), document()
    discoveries, fetched = [], []
    def discover(*args, **kwargs):
        discoveries.append(kwargs['forms'])
        return [_filing(annual)] if kwargs['forms'] == ['10-K'] else [_filing(quarter)]
    def fetch(url, **kwargs):
        fetched.append(url)
        return quarter if url == quarter.final_url else annual
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', discover)
    monkeypatch.setattr(live, 'fetch_public_document', fetch)
    monkeypatch.setattr(live, 'extract_source_bound_kpis', lambda *a, **k: pytest.fail('no generic extractor'))
    monkeypatch.setattr(live, 'discover_official_documents', lambda *a, **k: pytest.fail('no exhibit fetches'))
    items = live.fetch_live_issuer_kpi_evidence('AAPL', question=QUESTION, max_documents=budget)
    assert len(fetched) == budget and len(discoveries) == budget
    assert items[0].verified_claims[0]['raw_value'] == 27_423_000_000
    assert sum(bool(item.risk_disclosures) for item in items) == (2 if budget == 2 else 0)
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    admitted, refs, _ = admit_evidence(items, evaluated_at='2026-10-06')
    result = apply_source_answer_gate(thesis, QUESTION, admitted, references=refs)
    assert len(result['claims']) == budget + 1
    assert ('issuer_disclosed_risk' in str(result)) == (budget == 2)
    assert thesis.quantitative_claims  # Only the period-bound Services figures.
    assert len(thesis.quantitative_claims) == 3


def test_latest_quarter_risk_does_not_trigger_annual_discovery(monkeypatch):
    quarter = replace(_quarter(), text=document().text)
    discoveries, fetched = [], []
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings',
                        lambda *a, **k: discoveries.append(k) or [_filing(quarter)])
    monkeypatch.setattr(live, 'fetch_public_document', lambda *a, **k: fetched.append(a[0]) or quarter)
    items = live.fetch_live_issuer_kpi_evidence('AAPL', question=QUESTION)
    assert len(discoveries) == len(fetched) == 1
    assert sum(bool(item.risk_disclosures) for item in items) == 2


def test_annual_discovery_failure_retains_revenue_without_inventing_risk(monkeypatch):
    quarter = _quarter()
    def discover(*args, **kwargs):
        if kwargs['forms'] == ['10-K']:
            raise RuntimeError('unavailable')
        return [_filing(quarter)]
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', discover)
    monkeypatch.setattr(live, 'fetch_public_document', lambda *a, **k: quarter)
    items = live.fetch_live_issuer_kpi_evidence('AAPL', question=QUESTION)
    assert len(items) == 2 and not any(item.risk_disclosures for item in items)


def test_risk_only_request_uses_annual_without_generic_metrics(monkeypatch):
    annual = document()
    monkeypatch.setattr(live.sec_provider, 'fetch_recent_filings', lambda *a, **k: [_filing(annual)])
    monkeypatch.setattr(live, 'fetch_public_document', lambda *a, **k: annual)
    items = live.fetch_live_issuer_kpi_evidence('AAPL', question='Which source supports Services operating risks?')
    assert len(items) == 2 and all(item.risk_disclosures for item in items)
