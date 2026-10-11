"""Synthetic issuer prose: tests do not claim these are actual SEC disclosures."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.services import thesis_disclosures as service
from app.services.public_document_ingestion import PublicDocument, _HTMLTextExtractor
from app.services.financial_thesis_foundation import build_financial_foundation
from app.services.evidence_references import admit_evidence
from app.schemas import InvestmentThesis
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import pair

BUSINESS = "We manufacture specialized components and distribute our products through independent dealers."
RISK = "Supply chain disruptions could adversely affect our ability to manufacture and deliver products."
QUESTION = "What is the investment thesis for AAPL, what supports it, and what could invalidate it? Cite material claims."


def document(text=None, **changes):
    text = text or f"Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments"
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/annual.htm"
    return replace(PublicDocument(url, url, 'text/html', sha256(text.encode()).hexdigest(),
        len(text), 'Synthetic annual', text, (), (), (), 'html', True, '2025-08-01',
        publisher='SEC EDGAR', published_at='2025-08-01', document_type='10-K',
        source_type='regulatory_filing', source_tier='primary'), **changes)


def business_item():
    return service.extract_business_descriptions(document(), ticker="AAPL", cik="320193")[0]


def risk_item():
    return service.extract_issuer_risk_evidence(document(), ticker="AAPL",
        question="What operating risk affects Supply chain?")[0]


def test_exact_business_span_survives_producer_and_binder():
    item = business_item()
    value = service.bound_business_description(item, ticker="AAPL", cik="320193")
    assert value["quote"] == BUSINESS
    assert document().text[value["start_offset"]:value["end_offset"]] == BUSINESS
    assert item.verified_claims == []
    assert "competitive advantage" in item.summary


@pytest.mark.parametrize('quote', [
    'We offer subscriptions to our document workflow products to businesses of all sizes through direct and partner channels.',
    'We generate revenue primarily from marketplace activities, including listing fees, transaction fees and optional seller services.',
    'The company generates revenue from sales of subscriptions to its laboratory software and related customer support services.',
    'We also generate revenue from professional and other non-subscription services associated with customer deployment and integration.',
])
def test_subscription_and_fee_models_survive_unseen_issuer_fetch_and_final_binding(monkeypatch, quote):
    # Authored prose across distinct business models, without named-company rules.
    ticker, cik = 'ZQXB', '1234567'
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({'0': {
        'ticker': ticker, 'cik_str': int(cik), 'title': 'Synthetic test issuer'}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors '
                   f'{RISK} Item 1B. Unresolved Staff Comments', final_url=url, requested_url=url)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = service.fetch_thesis_disclosures(ticker, question=f'What is the investment thesis for {ticker}?')
    business = [item for item in fetched if item.business_disclosures]
    assert len(business) == 1
    value = service.bound_business_description(business[0], ticker=ticker, cik=cik)
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    admitted, refs, _ = admit_evidence(pair(ticker=ticker, cik=cik) + business,
                                     evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker=ticker, company_name='Synthetic test issuer')
    result = apply_source_answer_gate(thesis,
        f'What is the investment thesis for {ticker}? Cite material claims.', admitted, references=refs)
    assert result['status'] == 'partial' and quote in thesis.direct_answer
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert thesis.confidence_score == 0
    tampered = business[0].model_copy(deep=True)
    tampered.url = url.replace('/1234567/', '/9999999/')
    assert service.bound_business_description(tampered, ticker=ticker, cik=cik) is None


@pytest.mark.parametrize('quote', [
    'We offer training and mentoring services to our employees throughout the global workforce.',
    'We also offer employees a comprehensive package of benefits, including family building benefits, mental healthcare access, and flexible stipends for personal well-being.',
    'We offer subscriptions to products which will dominate the market and generate superior returns.',
    'We plan to offer subscriptions to our workflow products to businesses through direct sales channels.',
    'Our competitor offers subscriptions to its workflow products to businesses through direct sales channels.',
    'We generate revenue primarily from marketplace activities and expect rapid growth in the coming year.',
    'We generate revenue from sales of investments and property to finance new business ventures.',
    'We generate revenue from borrowing under credit agreements with independent financial institutions.',
])
def test_new_business_shapes_do_not_admit_internal_forecast_or_financing_prose(quote):
    assert service._business_quote_rejection(quote)


def test_internal_hosting_cannot_fill_business_gap_but_customer_hosting_remains_eligible():
    internal = ('We operate data centers and migrate our production services to a third-party cloud provider '
                'to support our internal applications.')
    customer = 'We offer managed hosting and data center services to customers through subscription contracts.'
    doc = document(f'Item 1. Business {internal} {customer} Item 1A. Risk Factors '
                   f'{RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193', diagnostics=stats)
    assert [i.business_disclosures[0]['quote'] for i in items] == [customer]
    assert stats['rejection_counts']['internal_hosting_activity'] == 1
    # Final binding withholds an older producer's internal-hosting claim too.
    item = business_item()
    value = item.business_disclosures[0]
    value.update(quote=internal, end_offset=value['start_offset'] + len(internal))
    value['document_ref']['quote'] = internal
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='320193') is None


@pytest.mark.parametrize('recipient', ['employees', 'our staff', 'our workforce'])
def test_direct_employee_benefit_recipient_is_rejected_at_extraction_and_final_binding(recipient):
    quote = f'We also offer {recipient} a comprehensive package of benefits, including healthcare and wellness support.'
    customer = 'We offer employee benefits administration software to customers through subscription contracts.'
    doc = document(f'Item 1. Business {quote} {customer} Item 1A. Risk Factors '
                   f'{RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193', diagnostics=stats)
    assert [i.business_disclosures[0]['quote'] for i in items] == [customer]
    assert stats['rejection_counts']['internal_employee_activity'] == 1
    item = business_item()
    value = item.business_disclosures[0]
    value.update(quote=quote, end_offset=value['start_offset'] + len(quote))
    value['document_ref']['quote'] = quote
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='320193') is None
    result = build_financial_foundation('AAPL', pair() + [item], None, expected_cik='320193')
    assert quote not in result['answer']
    assert 'business model and competitive position' in result['unanswered_parts']


def test_employee_products_for_customer_workforces_are_not_internal_benefits():
    quote = ('We offer employees of customer companies access to benefit administration services '
             'through contracts with their employers.')
    assert service._business_quote_rejection(quote) is None


@pytest.mark.parametrize('subject', ['The Firm', 'The company', 'Our company'])
@pytest.mark.parametrize('apostrophe', ["'", '\u2019'])
def test_current_segment_structure_is_bound_without_claiming_advantage(subject, apostrophe):
    quote = (f'{subject}{apostrophe}s consumer business segment is CCB, and '
             f'{subject.lower()}{apostrophe}s wholesale business segments are CIB and AWM.')
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    assert 'competitive advantage and future performance remain unverified' in items[0].summary


def test_operating_descriptions_following_segment_lists_take_bounded_priority():
    segment = 'The Firm\u2019s consumer business segment is CCB, and the Firm\u2019s wholesale business segments are CIB and AWM.'
    second = 'The Firm provides custody and payment processing services to institutional customers.'
    doc = document(f'Item 1. Business Overview. {segment} {segment} {BUSINESS} {second} '
                   f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [BUSINESS, second]
    for item in items:
        value = service.bound_business_description(item, ticker='AAPL', cik='320193')
        assert value and doc.text[value['start_offset']:value['end_offset']] == value['quote']


@pytest.mark.parametrize('ticker,cik,names', [
    ('JPM', '19617', 'Consumer & Community Banking (“CCB”), Commercial & Investment Bank (“CIB”) and Asset & Wealth Management (“AWM”)'),
    ('ZQXS', '1234567', 'Medical Devices (“MD”), Laboratory Products (“LP”) and Specialty Services (“SS”)'),
])
def test_source_named_segments_replace_bare_abbreviations_with_exact_quote(ticker, cik, names, monkeypatch):
    # The first shape reproduces user-supplied normalized filing text; the
    # second is synthetic and proves the rule does not depend on JPM names.
    quote = (f'For management reporting purposes, the Firm has three reportable business segments – '
             f'{names} – with the remaining activities in Corporate.')
    bare = 'The Firm\u2019s consumer business segment is CCB, and the Firm\u2019s wholesale business segments are CIB and AWM.'
    text = (f'Item 1. Business Business segments & Corporate {quote} {bare} '
            f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(text=text, final_url=url, requested_url=url)
    stats = {}
    business = service.extract_business_descriptions(doc, ticker=ticker, cik=cik, diagnostics=stats)
    assert len(business) == 1
    value = service.bound_business_description(business[0], ticker=ticker, cik=cik)
    assert value and value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    assert stats['heading_prefixes_removed'] == 1
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    thesis = InvestmentThesis(ticker=ticker, company_name='Synthetic test issuer')
    result = apply_source_answer_gate(thesis,
        f'What is the investment thesis for {ticker}? Cite material claims.',
        pair(ticker=ticker, cik=cik) + business)
    assert result['status'] == 'partial'
    assert names in thesis.direct_answer and bare not in thesis.direct_answer
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert thesis.confidence_score == 0 and thesis.directional_stance == ''


@pytest.mark.parametrize('quote', [
    'The Firm has three reportable business segments – CCB, CIB and AWM – with the remaining activities in Corporate.',
    'The Firm expects to have three reportable business segments – Consumer Banking, Markets and Wealth Management.',
    'The Firm will have three reportable business segments – Consumer Banking, Markets and Wealth Management.',
    'The Firm has three reportable business segments – Consumer Banking, Markets and Wealth Management – which will lead the industry.',
    'Our competitor has three reportable business segments – Consumer Banking, Markets and Wealth Management.',
    'If approved, the Firm has three reportable business segments – Consumer Banking, Markets and Wealth Management.',
    'The Firm has 3 reportable business segments – Consumer Banking, Markets and Wealth Management.',
])
def test_named_segment_shape_cannot_authorize_acronym_only_forecast_or_other_subject(quote):
    assert service._business_quote_rejection(quote) is not None


def test_operations_keep_priority_and_arbitrary_heading_prefix_is_not_removed():
    quote = 'The Company has two reportable business segments: Medical Devices and Laboratory Services.'
    doc = document(f'Item 1. Business {quote} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [BUSINESS, quote]
    doc = document(f'Item 1. Business Planned acquisition {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    assert service.extract_business_descriptions(doc, ticker='AAPL', cik='320193') == []


def test_named_list_does_not_suppress_a_segment_operating_description():
    named = 'The Company has two reportable business segments: Consumer Banking and Wealth Management.'
    operation = 'The Company\u2019s consumer business segment is a retail bank serving households and small business customers.'
    doc = document(f'Item 1. Business {named} {operation} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert [x.business_disclosures[0]['quote'] for x in items] == [named, operation]


@pytest.mark.parametrize('intro', [
    'Any of the risk factors discussed below could by itself, or combined with other factors, materially and adversely affect our liquidity and results of operations.',
    'Additional risks and uncertainties not presently known to us or that we currently believe to be immaterial could also adversely affect our business, financial condition, liquidity, cash flows, results of operations, reputation, and prospects.',
    'Our operations and financial results are subject to various risks and uncertainties, including those described below, that could adversely affect our business, operations, financial condition, results of operations, liquidity, and the trading price of our common stock.',
])
def test_generic_risk_intro_is_withheld_by_fetch_and_final_foundation(monkeypatch, intro):
    specific = ('Any significant losses in our investment portfolio or from market-making activities '
                'could reduce our profitability and our liquidity and capital levels.')
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors '
                   f'{intro} {specific} Item 1B. Unresolved Staff Comments')
    risk_items = service.extract_issuer_risk_evidence(doc, ticker='AAPL', question='What operating risk affects Liquidity?')
    assert len(risk_items) == 2
    assert service.bound_thesis_risk(risk_items[0], ticker='AAPL') is None
    assert service.bound_thesis_risk(risk_items[1], ticker='AAPL')
    result = build_financial_foundation('AAPL', pair() + risk_items, None, expected_cik='320193')
    assert intro not in result['answer'] and specific in result['answer']
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    assert intro not in repr(fetched) and specific in repr(fetched)


@pytest.mark.parametrize('quote', [
    'We also provide a range of health, savings, retirement, time-off and wellness benefits for our employees, which vary based on local regulations and norms.',
    'We provide budget for skills development across our organization, along with tailored mentorship opportunities.',
    'The Company provides training and support services to our staff throughout its global operations.',
])
def test_internal_employee_programs_cannot_close_business_model_gap(quote):
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    assert service.extract_business_descriptions(doc, ticker='AAPL', cik='320193', diagnostics=stats) == []
    assert stats['rejection_counts']['internal_employee_activity'] == 1
    # Final binding independently checks the predicate even if an older
    # producer or a modified item supplies internally focused prose.
    item = business_item()
    value = item.business_disclosures[0]
    value['quote'] = quote
    value['document_ref']['quote'] = quote
    value['end_offset'] = value['start_offset'] + len(quote)
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='320193') is None
    result = build_financial_foundation('AAPL', pair() + [item], None, expected_cik='320193')
    assert quote not in result['answer']
    assert 'business model and competitive position' in result['unanswered_parts']


def test_employee_service_provider_and_specific_risk_remain_eligible():
    quote = 'We provide employee benefits administration and payroll services to corporate customers.'
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value and doc.text[value['start_offset']:value['end_offset']] == quote
    assert service.bound_thesis_risk(risk_item(), ticker='AAPL')


def test_only_generic_risk_context_cannot_close_mechanism_gap():
    intro = 'All the risks described below could materially and adversely affect our liquidity and business operations.'
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors {intro} Item 1B. Unresolved Staff Comments')
    risks = service.extract_issuer_risk_evidence(doc, ticker='AAPL', question='What operating risk affects Liquidity?')
    assert risks
    result = build_financial_foundation('AAPL', pair() + risks, None, expected_cik='320193')
    assert intro not in result['answer']
    assert 'issuer-disclosed operating-risk mechanisms' in result['unanswered_parts']


@pytest.mark.parametrize('quote,scope', [
    ('Furthermore, our actions may be insufficient, may not be timely, and may not be effective in mitigating harm to our buyers, sellers, or other third parties or avoiding negative publicity.', 'Marketplace sellers'),
    ('Our efforts could be insufficient and materially adversely affect our liquidity and operating results.', 'Liquidity'),
    ('In addition, these measures may fail and adversely affect our liquidity and capital levels.', 'Liquidity'),
    ('Furthermore, such factors could materially adversely affect our liquidity and financial condition.', 'Liquidity'),
])
def test_unresolved_risk_subject_is_withheld_from_broad_fetch_and_final_answer(monkeypatch, quote, scope):
    specific = ('Supply chain disruptions could materially adversely affect our marketplace sellers, '
                'liquidity and operating results.')
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors '
                   f'{quote} {specific} Item 1B. Unresolved Staff Comments')
    risks = service.extract_issuer_risk_evidence(doc, ticker='AAPL',
                                                question=f'What operating risk affects {scope}?')
    assert len(risks) == 2
    # The narrow producer remains unchanged; only broad context rejects the
    # unresolved referent instead of inventing or clipping an antecedent.
    assert service.bound_issuer_risk(risks[0], ticker='AAPL',
                                   question=f'What operating risk affects {scope}?')
    assert service.bound_thesis_risk(risks[0], ticker='AAPL') is None
    assert service.bound_thesis_risk(risks[1], ticker='AAPL')
    result = build_financial_foundation('AAPL', pair() + risks, None, expected_cik='320193')
    assert quote not in result['answer'] and specific in result['answer']
    only_unresolved = build_financial_foundation('AAPL', pair() + risks[:1], None, expected_cik='320193')
    assert 'issuer-disclosed operating-risk mechanisms' in only_unresolved['unanswered_parts']
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    assert quote not in repr(fetched) and specific in repr(fetched)
    thesis = InvestmentThesis(ticker='AAPL', company_name='Apple')
    status = apply_source_answer_gate(thesis, QUESTION, pair() + risks)
    assert status['status'] == 'partial'
    assert quote not in thesis.direct_answer and specific in thesis.direct_answer


@pytest.mark.parametrize('quote', [
    'Our efforts to refinance debt maturities may fail and materially adversely affect our liquidity.',
    'Supply chain disruptions could materially adversely affect our liquidity and operating results.',
])
def test_risk_subject_with_explicit_mechanism_remains_eligible(quote):
    doc = document(f'Item 1. Business {BUSINESS} Item 1A. Risk Factors '
                   f'{quote} Item 1B. Unresolved Staff Comments')
    items = service.extract_issuer_risk_evidence(doc, ticker='AAPL', question='What operating risk affects Liquidity?')
    assert len(items) == 1
    assert service.bound_thesis_risk(items[0], ticker='AAPL')


@pytest.mark.parametrize('quote', [
    'The Firm is a leader in investment banking and financial services for consumers and small businesses.',
    'The Firm\u2019s consumer business segment is expected to grow rapidly and outperform its competitors.',
    'The Firm\u2019s consumer business segment is planned to provide investment services to local customers.',
    'The other firm\u2019s consumer business segment is a retail bank serving independent business customers.',
    'If approved, the Firm\u2019s consumer business segment is a retail bank serving local business customers.',
])
def test_promotional_planned_and_other_subject_segment_prose_stays_unqualified(quote):
    assert service._business_quote_rejection(quote) is not None


def test_segment_description_reaches_foundation_without_closing_competitive_or_risk_gaps():
    quote = ('The Firm\u2019s consumer business segment is CCB, and the Firm\u2019s '
             'wholesale business segments are CIB and AWM.')
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = pair() + service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    result = build_financial_foundation('AAPL', items, None, expected_cik='320193')
    assert quote in result['answer']
    assert 'competitive position' in result['unanswered_parts']
    assert 'valuation and expected returns' in result['unanswered_parts']
    assert 'issuer-disclosed operating-risk mechanisms' in result['unanswered_parts']


@pytest.mark.parametrize("changes", [dict(document_type="20-F"), dict(publisher="Other"),
    dict(published_at="2099-01-01"), dict(source_tier="secondary"), dict(text_ready=False)])
def test_ineligible_document_does_not_authorize_business_description(changes):
    assert service.extract_business_descriptions(document(**changes), ticker="AAPL", cik="320193") == []


@pytest.mark.parametrize("text", [
    f"Item 1. Business 2 {BUSINESS} Item 1A. Risk Factors 3",
    f"See Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors {RISK}",
    f"Item 1. Business Overview. {BUSINESS}",
    "Item 1. Business Overview. We will manufacture superior products and deliver the best results for all customers. Item 1A. Risk Factors",
    "Item 1. Business Overview. We manufacture specialized components and sell 400 products through dealers. Item 1A. Risk Factors",
])
def test_incomplete_toc_cross_reference_forecast_and_numeric_business_text_fail_closed(text):
    assert service.extract_business_descriptions(document(text), ticker="AAPL", cik="320193") == []


@pytest.mark.parametrize("mutation", [
    lambda item: setattr(item, "summary", "Invented moat"),
    lambda item: setattr(item, "source_tier", "secondary"),
    lambda item: setattr(item, "freshness_status", "stale"),
    lambda item: item.business_disclosures[0].update(ticker="TSLA"),
    lambda item: item.business_disclosures[0].update(start_offset=True),
    lambda item: item.business_disclosures[0]["document_ref"].update(content_hash="bad"),
    lambda item: item.business_disclosures[0]["document_ref"].update(quote="Invented quote."),
])
def test_mutated_business_proof_is_rejected(mutation):
    item = business_item()
    mutation(item)
    assert service.bound_business_description(item, ticker="AAPL", cik="320193") is None


def test_other_issuer_cannot_authorize_business_quote():
    assert service.bound_business_description(business_item(), ticker="AAPL", cik="1318605") is None


def test_composer_keeps_disclosures_separate_from_financial_inferences_and_materiality():
    items = pair() + [business_item(), risk_item()]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert len(result["claims"]) == 4
    assert len([row for row in result["inferences"] if row["kind"] == "financial_inference"]) == 2
    assert len([row for row in result["inferences"] if row["kind"] == "risk_monitoring_inference"]) == 1
    assert BUSINESS in result["answer"] and RISK in result["answer"]
    assert "competitive position" in result["unanswered_parts"]
    assert "valuation and expected returns" in result["unanswered_parts"]
    assert "risk materiality, likelihood and effect on the investment case" in result["unanswered_parts"]
    assert "issuer-disclosed operating-risk mechanisms" not in result["unanswered_parts"]
    assert "not a complete business model or a ranking" in result["answer"]


def test_unadmitted_quotes_do_not_close_missing_parts():
    items = pair() + [business_item(), risk_item()]
    refs = [{"id": f"E{i}", "title": item.title, "source": item.source,
             "url": item.url, "published_at": item.timestamp} for i, item in enumerate(items[:2], 1)]
    result = build_financial_foundation("AAPL", items, refs, expected_cik="320193")
    assert len(result["claims"]) == 2
    assert "business model and competitive position" in result["unanswered_parts"]
    assert "issuer-disclosed operating-risk mechanisms" in result["unanswered_parts"]


def test_duplicate_quotes_do_not_expand_context_or_change_reference_ids():
    items = pair() + [business_item(), business_item(), risk_item(), risk_item()]
    result = build_financial_foundation("AAPL", items, None, expected_cik="320193")
    assert len(result["claims"]) == 4
    assert [row["reference_id"] for row in result["claims"]][-2:] == ["E3", "E5"]


def test_gate_is_idempotent_with_canonical_references_and_no_conviction(monkeypatch):
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    items, refs, _ = admit_evidence(pair() + [business_item(), risk_item()], evaluated_at="2025-08-05")
    thesis = InvestmentThesis(ticker="AAPL", company_name="Apple")
    first = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    second = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    assert first == second
    assert first["status"] == "partial"
    assert thesis.confidence_score == 0 and thesis.directional_stance == ""
    assert all(row["reference_id"] in {r["id"] for r in refs} for row in first["claims"])


def test_live_fetch_spends_one_document_slot_and_keeps_both_bound_sections(monkeypatch):
    calls = []
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", lambda: {"AAPL": "0000320193"})
    monkeypatch.setattr(service.sec_provider, "fetch_recent_filings", lambda *a, **k:
        [SimpleNamespace(url=document().final_url, timestamp='2025-08-01', document_type='10-K')])
    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return document()
    monkeypatch.setattr(service, "fetch_public_document", fetch)
    items = service.fetch_thesis_disclosures("AAPL", question=QUESTION)
    assert len(calls) == 1 and calls[0]["preserve_sec_business"] is True
    assert calls[0]["extract_tables"] is False
    assert len(items) == 2
    assert items[0].business_disclosures and items[1].risk_disclosures


def test_discovery_failure_and_segment_requests_return_empty(monkeypatch):
    def unavailable(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(service.sec_provider, "_load_ticker_cik_map", unavailable)
    assert service.fetch_thesis_disclosures("AAPL", question=QUESTION) == []
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for Apple Services? Cite sources.")
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for the App Store? Cite sources.")
    assert not service.requests_thesis_disclosures("AAPL", "What is the investment thesis for supply chain growth? Cite sources.")


def test_large_filing_opt_in_preserves_business_and_risk_without_raising_ceiling():
    parser = _HTMLTextExtractor()
    parser.feed('<p>' + 'Preamble. ' * 100 + document().text + '</p>')
    _, ordinary, _, _ = parser.result(max_chars=400, preserve_sec_risk=True)
    _, combined, _, _ = parser.result(max_chars=400, preserve_sec_risk=True, preserve_sec_business=True)
    assert 'Item 1. Business' not in ordinary
    assert BUSINESS in combined and RISK in combined
    assert len(combined) <= 400


def test_punctuated_contents_rows_do_not_replace_bound_business_and_risk_text():
    toc = ('Item 1. Business . 1 Overview 1 Business segments & Corporate 1 '
           'Item 1A. Risk Factors . 9 Item 1B. Unresolved Staff Comments . 20 ')
    actual = document().text
    parser = _HTMLTextExtractor()
    parser.feed('<p>' + toc + 'Preamble. ' * 100 + actual + '</p>')
    _, text, _, _ = parser.result(max_chars=400, preserve_sec_risk=True,
                                preserve_sec_business=True)
    assert parser.text_selection == 'complete_sec_business_and_risk_section'
    assert BUSINESS in text and RISK in text and 'Business segments & Corporate' not in text
    doc = document(text=text)
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value and value['quote'] == BUSINESS
    assert text[value['start_offset']:value['end_offset']] == BUSINESS
    risks = service.extract_issuer_risk_evidence(doc, ticker='AAPL',
        question='What operating risk affects Supply chain?')
    assert len(risks) == 1 and service.bound_thesis_risk(risks[0], ticker='AAPL')


def test_oversized_business_falls_back_to_complete_risk_section():
    parser = _HTMLTextExtractor()
    parser.feed('<p>' + 'Preamble. ' * 100 + 'Item 1. Business Overview. ' + BUSINESS * 10
                + f' Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments</p>')
    _, text, _, _ = parser.result(max_chars=400, preserve_sec_risk=True, preserve_sec_business=True)
    assert RISK in text and BUSINESS not in text
    assert len(text) <= 400


def test_directory_resolved_unseen_issuer_uses_same_producers(monkeypatch):
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({"0": {
        "ticker": "ZQXS", "title": "Synthetic Components Inc.", "cik_str": 1234567}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)
    url = document().final_url.replace('/320193/', '/1234567/')
    doc = document(final_url=url, requested_url=url)
    business = service.extract_business_descriptions(doc, ticker="ZQXS", cik="1234567")
    risks = service.extract_issuer_risk_evidence(doc, ticker="ZQXS",
        question="What operating risk affects Supply chain?")
    items = pair(ticker="ZQXS", cik="1234567") + business + risks
    result = build_financial_foundation("ZQXS", items, None, expected_cik="1234567")
    assert len(result["claims"]) == 4
    assert BUSINESS in result["answer"] and RISK in result["answer"]
    assert "competitive position" in result["unanswered_parts"]


@pytest.mark.parametrize('heading', ['Company Background', 'Overview', 'GENERAL',
                                     'Business Overview', 'Segment Information'])
def test_unpunctuated_shared_heading_preserves_complete_sentence_and_exact_span(heading):
    doc = document(f'Item 1. Business {heading} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193', diagnostics=stats)
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='320193')
    assert value['quote'] == BUSINESS
    assert doc.text[value['start_offset']:value['end_offset']] == BUSINESS
    assert stats['status'] == 'business_extracted' and stats['heading_prefixes_removed'] == 1
    assert BUSINESS not in repr(stats)


@pytest.mark.parametrize('prefix', ['If approved,', 'Our competitor says', 'Previously,',
                                    'Overview we may change our plans.', 'General hypothetical case'])
def test_arbitrary_prefix_cannot_be_removed_to_create_current_business_fact(prefix):
    doc = document(f'Item 1. Business {prefix} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    # Only the separately punctuated complete sentence qualifies, never a
    # clipped conditional or a sentence attributed to a competitor.
    assert len(items) == (1 if prefix.endswith('.') else 0)


def test_business_diagnostics_distinguish_missing_section_from_rejected_prose():
    missing, rejected = {}, {}
    service.extract_business_descriptions(document(text=f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments'),
        ticker='AAPL', cik='320193', diagnostics=missing)
    service.extract_business_descriptions(document(text='Item 1. Business Overview We may manufacture specialized components for customers in the future. Item 1A. Risk Factors'),
        ticker='AAPL', cik='320193', diagnostics=rejected)
    assert missing['status'] == 'no_complete_business_section'
    assert rejected['status'] == 'no_qualifying_business_sentence'
    assert rejected['rejection_counts'] == {'numeric_or_forward_looking': 1}


@pytest.mark.parametrize('ticker,cik', [('AAPL', '320193'), ('AA', '1675149'),
                                      ('ACHC', '1520697'), ('TSLA', '1318605')])
def test_business_identity_accepts_zero_padded_directory_cik_without_changing_issuer(ticker, cik):
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(final_url=url, requested_url=url)
    padded = cik.zfill(10)
    stats = {}
    items = service.extract_business_descriptions(doc, ticker=ticker, cik=padded, diagnostics=stats)
    assert len(items) == 1
    assert stats['status'] == 'business_extracted'
    assert service.bound_business_description(items[0], ticker=ticker, cik=padded)
    assert not service.bound_business_description(items[0], ticker=ticker, cik='9999999999')


@pytest.mark.parametrize('cik', ['', '0', '0000000000', '12345678901',
                               '320193|1318605', '320193.0', '-320193', True, None])
def test_invalid_business_identity_cannot_authorize_sec_document(cik):
    assert service.extract_business_descriptions(document(), ticker='AAPL', cik=cik) == []
    assert service.bound_business_description(business_item(), ticker='AAPL', cik=cik) is None


@pytest.mark.parametrize('quote', [
    'We are committed to providing the communities we serve with high-quality, cost-effective behavioral healthcare services, while growing our business, increasing profitability and creating long-term value for our stockholders.',
    'We generate strong returns by profitably operating our business and by actively managing our working capital.',
    'The Company also seeks to maintain a strong balance sheet through monetization of non-operating assets and further reductions in total debt, while evaluating value-creating growth opportunities.',
    'We are focused on bringing artificial intelligence into the real world, through products and services, as well as working to develop and commercialize robots.',
    'We generally sell our products directly to customers, and continue to grow our global retail, service and charging footprint to accelerate the widespread adoption of our products.',
])
def test_aspirations_and_promotional_performance_do_not_become_business_facts(quote):
    # Reproduce sentence shapes exposed by the post222 capture in a synthetic
    # document; neither a genuine filing nor source accuracy is asserted here.
    doc = document(f'Item 1. Business Overview. {quote} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    stats = {}
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193', diagnostics=stats)
    assert [item.business_disclosures[0]['quote'] for item in items] == [BUSINESS]
    assert stats['rejection_counts']['aspirational_or_promotional'] == 1
    # Final binding must also reject previously admitted aspirational prose.
    item = business_item()
    value = item.business_disclosures[0]
    value.update(quote=quote, end_offset=value['start_offset'] + len(quote))
    value['document_ref']['quote'] = quote
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='0000320193') is None


@pytest.mark.parametrize('quote', [
    'We provide inpatient behavioral healthcare services through our network of treatment facilities.',
    'The Company designs, manufactures and markets smartphones and sells related services to customers.',
    'We generally sell our products directly to customers through our retail and service locations.',
    'The Company\u2019s operations are comprised of two reportable business segments: Alumina and Aluminum.',
])
def test_concrete_operations_remain_exact_issuer_descriptions(quote):
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193')
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='0000320193')
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote


def test_only_promotional_prose_preserves_missing_business_context():
    quote = 'We generate strong returns by profitably operating our business and by actively managing our working capital.'
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193')
    assert items == []
    result = build_financial_foundation('AAPL', pair() + items, None, expected_cik='320193')
    assert 'business model and competitive position' in result['unanswered_parts']
    assert quote not in result['answer']


@pytest.mark.parametrize('quote', [
    'We focus on projects that build upon our existing operational strengths, enable us to serve customer demand growth, and that provide opportunities to unlock synergies through our technical expertise and scalable systems.',
    'We have a number of potential acquisitions, joint ventures and wholly-owned de novo facilities in various stages of development and consideration.',
    'We emphasize performance, attractive styling and the safety of our users and workforce in the design and manufacture of our products and are continuing to develop full self-driving technology for improved safety.',
    'We believe our products create unmatched value for our customers and support our investment strategy.',
    'We review opportunities to provide additional services to customers in new markets.',
])
def test_incidental_activity_vocabulary_cannot_authorize_business_context(quote):
    doc = document(f'Item 1. Business Overview. {quote} {BUSINESS} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193')
    assert [item.business_disclosures[0]['quote'] for item in items] == [BUSINESS]
    item = business_item()
    value = item.business_disclosures[0]
    value.update(quote=quote, end_offset=value['start_offset'] + len(quote))
    value['document_ref']['quote'] = quote
    item.summary = service._business_summary(value)
    assert service.bound_business_description(item, ticker='AAPL', cik='0000320193') is None


@pytest.mark.parametrize('quote', [
    'We operate as two reportable segments: (i) automotive and (ii) energy generation and storage.',
    'The Company\u2019s line of wireless headphones includes branded products sold through retail channels.',
    'Our company primarily distributes specialty medical devices to hospitals and outpatient providers.',
    'We are a manufacturer of specialized industrial equipment sold through independent dealers.',
])
def test_current_predicates_and_defined_products_remain_exact(quote):
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments')
    items = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193')
    assert len(items) == 1
    value = service.bound_business_description(items[0], ticker='AAPL', cik='0000320193')
    assert value['quote'] == quote
    assert doc.text[value['start_offset']:value['end_offset']] == quote



@pytest.mark.parametrize('name,heading', [
    ('Quanta Works, Inc.', 'Our Products '),
    ('General Instruments Corporation', ''),
])
def test_named_issuer_operations_require_directory_identity_and_preserve_exact_span(monkeypatch, name, heading):
    from app.services import issuer_identity
    ticker, cik = 'ZQXN', '1234567'
    subject = issuer_identity.name_key(name).title()
    quote = f'{subject} enables laboratories to organize sample workflows using its software products and integration services.'
    directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'title': name, 'cik_str': int(cik)}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    url = document().final_url.replace('/320193/', f'/{cik}/')
    fees = 'We generate revenue from sales of subscriptions to our software and related customer support services.'
    doc = document(f'Item 1. Business {fees} {BUSINESS} {heading}{quote} '
                   f'Item 1A. Risk Factors {RISK} Item 1B. Unresolved Staff Comments', final_url=url, requested_url=url)
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    fetched = service.fetch_thesis_disclosures(ticker, question=f'What is the investment thesis for {ticker}?')
    items = [item for item in fetched if item.business_disclosures]
    assert len(items) == 2 and items[0].business_disclosures[0]['quote'] == quote
    value = service.bound_business_description(items[0], ticker=ticker, cik=cik)
    assert value and doc.text[value['start_offset']:value['end_offset']] == quote
    admitted, refs, _ = admit_evidence(pair(ticker=ticker, cik=cik) + items, evaluated_at='2025-08-05')
    thesis = InvestmentThesis(ticker=ticker, company_name=name)
    status = apply_source_answer_gate(thesis, f'What is the investment thesis for {ticker}? Cite material claims.',
                                     admitted, references=refs)
    assert status['status'] == 'partial' and quote in thesis.direct_answer
    assert 'competitive position' in status['unanswered_parts']
    assert 'valuation and expected returns' in status['unanswered_parts']
    assert thesis.confidence_score == 0
    other = issuer_identity.parse_directory({'0': {'ticker': ticker, 'title': 'Other Issuer Inc.', 'cik_str': int(cik)}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: other)
    assert service.bound_business_description(items[0], ticker=ticker, cik=cik) is None


@pytest.mark.parametrize('failure', ['other_name', 'alias', 'wrong_cik', 'unavailable', 'promotional', 'forecast', 'incomplete'])
def test_named_issuer_does_not_relax_identity_or_qualitative_guardrails(monkeypatch, failure):
    from app.services import issuer_identity
    ticker, cik = 'ZQXN', '1234567'
    directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'title': 'Quanta Works Inc.',
        'cik_str': 9999999 if failure == 'wrong_cik' else int(cik)}})
    if failure == 'unavailable':
        directory = issuer_identity.Directory({}, {})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    subject = 'Other Issuer' if failure == 'other_name' else 'Quanta' if failure == 'alias' else 'Quanta Works'
    quote = f'{subject} enables laboratories to organize sample workflows using software products and integration services.'
    if failure == 'promotional':
        quote = quote[:-1] + ' with superior results.'
    if failure == 'forecast':
        quote = quote[:-1] + ' that will dominate the market.'
    if failure == 'incomplete':
        quote = quote[:-1]
    url = document().final_url.replace('/320193/', f'/{cik}/')
    doc = document(f'Item 1. Business Our Products {quote} Item 1A. Risk Factors '
                   f'{RISK} Item 1B. Unresolved Staff Comments', final_url=url, requested_url=url)
    assert service.extract_business_descriptions(doc, ticker=ticker, cik=cik) == []


@pytest.mark.parametrize('closing', ['Item 4A. Unresolved Staff Comments',
                                     'Item 5. Operating and Financial Review and Prospects'])
def test_foreign_business_uses_explicit_item4_boundaries_and_actual_form(closing):
    doc = document(f'Item 4. Information on the Company Overview. {BUSINESS} {closing}',
                   document_type='20-F')
    item, = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert item.document_type == '20-F'
    assert item.section == 'Item 4. Information on the Company'
    assert 'in its 20-F filed' in item.summary
    assert service.bound_business_description(item, ticker='AAPL', cik='320193')
    foundation = build_financial_foundation('AAPL', pair() + [item], None, expected_cik='320193')
    assert 'business model and competitive position' not in foundation['unanswered_parts']
    assert 'competitive position' in foundation['unanswered_parts']
    assert 'valuation and expected returns' in foundation['unanswered_parts']
    assert BUSINESS in foundation['answer']
    value = item.business_disclosures[0]
    assert doc.text[value['start_offset']:value['end_offset']] == BUSINESS
    tampered = item.model_copy(deep=True)
    tampered.document_type = '10-K'
    assert service.bound_business_description(tampered, ticker='AAPL', cik='320193') is None


@pytest.mark.parametrize('text', [
    f'Item 4. Information on the Company 14 {BUSINESS} Item 5. Operating and Financial Review 20',
    f'See Item 4. Information on the Company Overview. {BUSINESS} Item 5. Operating and Financial Review',
    f'Item 4. Information on the Company Overview. {BUSINESS}',
    f'Business Overview. {BUSINESS} Item 5. Operating and Financial Review',
    f'Item 4. Information on the Company Overview. {BUSINESS} See Item 5. Operating and Financial Review',
    f'Item 4. Information on the Company Overview. {"Context. " * 20000} {BUSINESS} Item 5. Operating and Financial Review',
])
def test_foreign_business_toc_cross_reference_incomplete_and_oversized_fail_closed(text):
    assert service.extract_business_descriptions(document(text, document_type='20-F'),
                                                 ticker='AAPL', cik='320193') == []


@pytest.mark.parametrize('quote', [
    'To help our customers improve their manufacturing workflows, we provide equipment maintenance and technical support services.',
    'To help our customers correct production errors, we develop software and provide support throughout the manufacturing process.',
])
def test_complete_customer_purpose_activity_keeps_exact_sentence(quote):
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK}')
    item, = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert service.bound_business_description(item, ticker='AAPL', cik='320193')['quote'] == quote


@pytest.mark.parametrize('quote', [
    'To help our customers improve workflows, we will provide software and technical support services.',
    'To help our customers improve workflows, we provide the best software and technical support services.',
    'To help our employees improve workflows, we provide software and technical support services.',
    'To help our customers improve workflows, our competitor provides software and technical support services.',
    'To help our customers improve workflows, we provide software and expect rapid future revenue growth.',
    'To help our customers improve workflows, we plan to provide software and technical support services.',
])
def test_customer_purpose_does_not_authorize_forecasts_promotions_or_wrong_subject(quote):
    doc = document(f'Item 1. Business Overview. {quote} Item 1A. Risk Factors {RISK}')
    assert service.extract_business_descriptions(doc, ticker='AAPL', cik='320193') == []


def test_foreign_text_selection_retains_business_after_risk_with_closing_heading():
    prefix = 'Preface. ' * 15000
    text = prefix + f'Item 3.D. Risk Factors {RISK} Item 4. Information on the Company Overview. {BUSINESS} Item 5. Operating and Financial Review and Prospects'
    parser = _HTMLTextExtractor()
    parser.feed('<html><body>' + text + '</body></html>')
    _, selected, _, _ = parser.result(max_chars=1500, preserve_sec_risk=True,
                                     preserve_sec_business=True, risk_form='20-F')
    assert parser.text_selection == 'complete_sec_business_and_risk_section'
    assert 'Item 5. Operating and Financial Review' in selected
    doc = document(selected, document_type='20-F')
    item, = service.extract_business_descriptions(doc, ticker='AAPL', cik='320193')
    assert service.bound_business_description(item, ticker='AAPL', cik='320193')


@pytest.mark.parametrize("cik", ["937966", "0000937966"])
def test_reviewed_integrated_business_layout_requires_producer_and_binder_authorization(cik):
    from app.services.reviewed_annual_layouts import REVIEWED_ANNUAL_LAYOUTS
    layout = REVIEWED_ANNUAL_LAYOUTS[0]
    quote = 'To help our customers improve manufacturing workflows, we provide technical support and equipment maintenance services.'
    text = (layout['business_mapping'] + ' Mapping ends. '
            'Our holistic approach to lithography Lithography – using light describes our process. '
            f'Navigating challenges in advanced lithography {quote} '
            'Our market place Th e macro headlines concern the economy.')
    doc = document(text, requested_url=layout['url'], final_url=layout['url'],
                   document_type='20-F', published_at=layout['filed_at'],
                   content_hash=layout['content_hash'])
    item, = service.extract_business_descriptions(doc, ticker='ASML', cik=cik)
    value = service.bound_business_description(item, ticker='ASML', cik=cik)
    assert value['quote'] == quote
    assert item.section == layout['business_section']
    assert doc.text[value['start_offset']:value['end_offset']] == quote
    for updates in ({'content_hash': 'a' * 64}, {'document_type': '20-F/A'},
                    {'published_at': '2026-02-26'}):
        assert service.extract_business_descriptions(replace(doc, **updates), ticker='ASML', cik=cik) == []
    for key in ('raw_content_hash', 'canonical_content_hash', 'registry_id'):
        tampered = item.model_copy(deep=True)
        tampered.business_disclosures[0]['reviewed_layout'][key] = 'changed'
        assert service.bound_business_description(tampered, ticker='ASML', cik=cik) is None
    tampered = item.model_copy(deep=True)
    del tampered.business_disclosures[0]['reviewed_layout']
    assert service.bound_business_description(tampered, ticker='ASML', cik=cik) is None

QUARTER_SEGMENTS = 'Our four reportable segments are Manufacturing, Distribution, Service Products, and Specialty Products.'


def quarterly_document(text=None):
    return document(text or f'Note 3. Disclosures about Segments and Related Information {QUARTER_SEGMENTS} Note 4. Pension Benefits Other context.', document_type='10-Q')


def test_current_quarter_segment_context_survives_admission_and_binding():
    doc = quarterly_document()
    item, = service.extract_business_descriptions(doc, ticker='AAPL', cik='0000320193')
    admitted, refs, _ = admit_evidence([item], evaluated_at='2025-09-01')
    value = service.bound_business_description(admitted[0], ticker='AAPL', cik='320193')
    assert value['quote'] == QUARTER_SEGMENTS
    assert doc.text[value['start_offset']:value['end_offset']] == QUARTER_SEGMENTS
    assert refs[0]['document_type'] == '10-Q'
    assert refs[0]['section'] == 'Notes to Financial Statements - Segments'
    assert service.bound_business_description(item, ticker='AAPL', cik='937966') is None
    assert service.bound_business_description(item.model_copy(update={'document_type':'10-K'}), ticker='AAPL', cik='320193') is None


@pytest.mark.parametrize('text', [
    f'Note 3. Disclosures about Segments and Related Information 9 {QUARTER_SEGMENTS} Note 4. Pension Benefits 10',
    f'See Note 3. Disclosures about Segments and Related Information {QUARTER_SEGMENTS} Note 4. Pension Benefits Other context.',
    f'Note 3. Disclosures about Segments and Related Information {QUARTER_SEGMENTS}',
    f'Note 3. Disclosures about Segments and Related Information Context only. Note 4. Pension Benefits {QUARTER_SEGMENTS}',
    f'Note 3. Disclosures about Segments and Related Information Our four reportable segments are expected to be Manufacturing and Distribution. Note 4. Pension Benefits Other context.',
])
def test_quarterly_context_rejects_toc_cross_references_unclosed_and_forecasts(text):
    assert service.extract_business_descriptions(quarterly_document(text), ticker='AAPL', cik='320193') == []


def test_absent_annual_fetches_one_current_quarter_without_predecessor_inheritance(monkeypatch):
    calls = []
    doc = quarterly_document()
    filing = SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-Q')
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL':'0000320193'})
    def discovery(*args, **kwargs):
        calls.append(kwargs['forms'])
        return [filing] if kwargs['forms'] == ['10-Q'] else []
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', discovery)
    monkeypatch.setattr(service, 'reviewed_predecessor_annual', lambda ticker: None)
    monkeypatch.setattr(service, 'fetch_public_document', lambda *args, **kwargs: doc)
    item, = service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    assert calls == [['10-K','20-F'], ['10-Q']]
    assert item.document_type == '10-Q' and item.business_disclosures
    assert not item.risk_disclosures


def test_bound_risk_produces_cited_specific_condition_without_claiming_occurrence():
    result = build_financial_foundation('AAPL', pair() + [risk_item()], None, expected_cik='320193')
    inference, = [row for row in result['inferences'] if row['kind'] == 'risk_monitoring_inference']
    assert inference['condition'] == 'Supply chain disruptions'
    assert inference['potential_effect'] == 'our ability to manufacture and deliver products'
    assert inference['reference_ids'] == ['E3']
    assert not inference['historical_context_only']
    assert inference['text'].startswith('Watch:')
    assert 'disclosure alone does not invalidate' in inference['conditional_test'].lower()
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']
    assert '[E3]' in result['answer'].split('Conditional risk monitoring')[1]


@pytest.mark.parametrize('modal', ['could', 'may'])
@pytest.mark.parametrize('condition,scope', [
    ('Supply chain disruptions', 'Liquidity'),
    ('Cyberattacks', 'Cybersecurity'),
    ('Loan defaults', 'Credit losses'),
])
@pytest.mark.parametrize('modifier', ['', 'materially '])
def test_bound_mechanism_survives_binding_and_final_answer(monkeypatch, modal, condition, scope, modifier):
    import socket

    def unexpected_network(*args, **kwargs):
        pytest.fail('Bound risk monitoring must not use the network')

    monkeypatch.setattr(socket, 'getaddrinfo', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_network)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map',
                        lambda: {'AAPL': '0000320193'})
    quote = (f'{condition} {modal} {modifier}adversely affect '
             'our liquidity and operating results.')
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors '
                   f'{quote} Item 1B. Unresolved Staff Comments')
    risk, = service.extract_issuer_risk_evidence(doc, ticker='AAPL',
                                                question=f'What operating risk affects {scope}?')
    bound = service.bound_thesis_risk(risk, ticker='AAPL')
    assert bound['quote'] == quote
    assert doc.text[bound['start_offset']:bound['end_offset']] == quote
    items, references, _ = admit_evidence(pair() + [risk], evaluated_at='2025-09-01')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=references)
    inference, = [row for row in result['inferences'] if row['kind'] == 'risk_monitoring_inference']
    assert inference['condition'] == condition
    assert inference['potential_effect'] == 'our liquidity and operating results'
    assert inference['reference_ids'] == ['E3']
    assert quote in thesis.direct_answer
    assert not inference['historical_context_only']
    assert 'not a forecast' in inference['conditional_test']
    assert result['status'] == 'partial' and thesis.confidence_score == 0
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']
    tampered = risk.model_copy(update={'summary': 'Unbound material risk claim'})
    rejected = build_financial_foundation('AAPL', pair() + [tampered], None, expected_cik='320193')
    assert not any(row['kind'] == 'risk_monitoring_inference' for row in rejected['inferences'])
    missing_ref = build_financial_foundation('AAPL', pair() + [risk], references[:2], expected_cik='320193')
    assert not any(row['kind'] == 'risk_monitoring_inference' for row in missing_ref['inferences'])


def test_unbound_risk_or_missing_reference_cannot_produce_monitoring_test():
    bad = risk_item().model_copy(update={'summary':'Altered unbound claim'})
    result = build_financial_foundation('AAPL', pair() + [bad], None, expected_cik='320193')
    assert all(row['kind'] == 'financial_inference' for row in result['inferences'])
    items = pair() + [risk_item()]
    refs = [dict(id=f'E{i}', title=item.title, source=item.source, url=item.url,
                 published_at=item.timestamp) for i, item in enumerate(items[:2], 1)]
    result = build_financial_foundation('AAPL', items, refs, expected_cik='320193')
    assert 'Conditional risk monitoring' not in result['answer']


@pytest.mark.parametrize('quote', [
    'Supply chain disruptions are among the risks described elsewhere in this annual report.',
    'Supply chain disruptions may occur and could adversely affect our manufacturing operations.',
    'Supply chain disruptions will occur and could adversely affect our manufacturing operations.',
    'Supply chain disruptions could not adversely affect our manufacturing operations.',
    'Supply chain disruptions could not materially adversely affect our manufacturing operations.',
    'Supply chain disruptions will materially adversely affect our manufacturing operations.',
    'Supply chain disruptions may occur and could materially adversely affect our manufacturing operations.',
    'Supply chain disruptions could probably materially adversely affect our manufacturing operations.',
])
def test_monitoring_does_not_invent_missing_or_nested_condition_effect(quote):
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    assert _risk_monitoring_inference(dict(quote=quote, scope='Supply chain'), 'E1') is None


@pytest.mark.parametrize('condition', ['', ' ', '...', '—', 'X', 'It', 'These risks',
                                      'Furthermore, it', 'However, ...',
                                      'Cyberattacks may occur and', 'Cyberattacks will occur and',
                                      'A' * 501])
def test_short_condition_still_requires_explicit_lexical_mechanism(condition):
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    quote = f'{condition} could adversely affect our business and operating results.'
    assert _risk_monitoring_inference(dict(quote=quote, scope='Cybersecurity'), 'E1') is None


def test_short_subject_must_name_bound_topic_not_borrow_it_from_effect():
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    quote = 'The situation could adversely affect our cybersecurity and operating results.'
    assert _risk_monitoring_inference(dict(quote=quote, scope='Cybersecurity'), 'E1') is None
    quote = 'Cyberattacks could adversely affect our liquidity and operating results.'
    assert _risk_monitoring_inference(dict(quote=quote, scope='Liquidity'), 'E1') is None


@pytest.mark.parametrize('condition', ['The foregoing', 'The above', 'We',
                                      'The situation', 'The risks', 'In turn, this',
                                      'All of this', 'Both'])
@pytest.mark.parametrize('prefix', ['', 'Furthermore, ', 'On the other hand, ',
                                    'Moreover, ', 'However, ', 'In addition, '])
def test_bound_anaphoric_subject_does_not_become_monitoring(monkeypatch, condition, prefix):
    import socket

    def unexpected_network(*args, **kwargs):
        pytest.fail('Anaphoric risk acceptance must not use the network')

    monkeypatch.setattr(socket, 'getaddrinfo', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_network)
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    quote = f'{prefix}{condition} could adversely affect our liquidity and operating results.'
    doc = document(f'Item 1. Business Overview. {BUSINESS} Item 1A. Risk Factors '
                   f'{quote} Item 1B. Unresolved Staff Comments')
    risk, = service.extract_issuer_risk_evidence(doc, ticker='AAPL',
                                               question='What operating risk affects Liquidity?')
    bound = service.bound_thesis_risk(risk, ticker='AAPL')
    assert bound and bound['quote'] == quote
    assert doc.text[bound['start_offset']:bound['end_offset']] == quote
    items, refs, _ = admit_evidence(pair() + [risk], evaluated_at='2025-09-01')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=refs)
    assert result['status'] == 'partial' and thesis.confidence_score == 0
    assert not any(row['kind'] == 'risk_monitoring_inference' for row in result['inferences'])
    assert 'Conditional risk monitoring' not in thesis.direct_answer
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']


@pytest.mark.parametrize('quote', [RISK, RISK.replace('could adversely', 'could materially adversely'),
                                 RISK.replace('could adversely', 'may materially adversely')])
def test_historical_risk_monitoring_requires_current_successor_confirmation(quote):
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    result = _risk_monitoring_inference(dict(quote=quote, scope='Supply chain',
        issuer_relationship={'use':'historical_risk_context_only'}), 'E6')
    assert result['historical_context_only']
    assert result['text'].startswith('Historical predecessor watch:')
    assert 'Confirm current successor relevance' in result['conditional_test']
    assert 'not a current successor invalidation test' in result['conditional_test']


def test_source_answer_gate_retains_risk_inference_as_partial_analysis(monkeypatch):
    import socket

    def unexpected_network(*args, **kwargs):
        pytest.fail('Synthetic risk-inference acceptance must not use the network')

    monkeypatch.setattr(socket, 'getaddrinfo', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_network)
    # Match the authored financial/risk fixtures without loading SEC's directory.
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map',
                        lambda: {'AAPL': '0000320193'})
    items, references, _ = admit_evidence(pair() + [risk_item()], evaluated_at='2025-09-01')
    thesis = InvestmentThesis(ticker='AAPL', company_name='Synthetic company')
    result = apply_source_answer_gate(thesis, QUESTION, items, references=references)
    assert result['status'] == 'partial'
    inference, = [row for row in result['inferences'] if row['kind'] == 'risk_monitoring_inference']
    assert inference['reference_ids'] == ['E3']
    assert 'Conditional risk monitoring' in thesis.direct_answer
    assert 'risk materiality, likelihood and effect on the investment case' in result['unanswered_parts']


def test_risk_display_drops_only_leading_transition_retaining_source_condition():
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    quote = 'On the other hand, a material increase in commodity prices could have a material adverse effect on our manufacturing operations.'
    value = dict(quote=quote, scope='Commodity prices')
    result = _risk_monitoring_inference(value, 'E7')
    assert value['quote'] == quote
    assert result['condition'] == 'On the other hand, a material increase in commodity prices'
    assert result['display_condition'] == 'a material increase in commodity prices'
    assert 'On the other hand' not in result['text']
    assert result['text'].count(result['display_condition']) == 1
    assert result['display_condition'] not in result['conditional_test']
    assert result['potential_effect'] not in result['conditional_test']
    assert result['reference_ids'] == ['E7']


@pytest.mark.parametrize('condition', ['Any failure to maintain customer support',
                                     'Our inability to secure raw materials',
                                     'A decline, however, in customer demand'])
def test_risk_display_retains_substantive_conditions_and_internal_qualifiers(condition):
    from app.services.financial_thesis_foundation import _risk_monitoring_inference
    result = _risk_monitoring_inference(dict(quote=f'{condition} could adversely affect our manufacturing operations.',
        scope='Supply chain'), 'E1')
    assert result['display_condition'] == condition == result['condition']
