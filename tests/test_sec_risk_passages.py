"""Observed layout regressions and authored adversarial passages, no live certification."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from app.schemas import InvestmentThesis
from app.services import issuer_identity, public_document_ingestion as ingestion
from app.services.evidence_references import admit_evidence
from app.services.issuer_risk_evidence import extract_issuer_risk_evidence, bound_issuer_risk, requested_risk_profile
from app.services.sec_risk_sections import complete_risk_window, risk_section_spans, risk_sentence_spans
from app.services.source_answer import apply_source_answer_gate
from scripts.company_evidence_acceptance import COHORT_PATH
from scripts.company_evidence_inspection import topic_inspection

CASES = {c['ticker']: c for c in json.loads(COHORT_PATH.read_text())['cases']}


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    directory = issuer_identity.parse_directory({str(i): {
        'ticker': c['ticker'], 'title': c['company'], 'cik_str': int(c['cik'])
    } for i, c in enumerate(CASES.values())})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(issuer_identity, '_cache', directory)


def document(ticker, text):
    c = CASES[ticker]
    url = f'https://www.sec.gov/Archives/edgar/data/{c["cik"]}/000000000026000001/authored.htm'
    return ingestion.PublicDocument(url, url, 'text/html', sha256(text.encode()).hexdigest(), len(text),
        'Authored layout fixture', text, (), (), (), 'html', True, '2026-10-07',
        publisher='SEC EDGAR', published_at='2026-02-13', document_type='10-K',
        source_type='regulatory_filing', source_tier='primary')


@pytest.mark.parametrize('prefix', [
    'See the human capital discussion in ', 'As discussed above and below in ',
    'Read the risks described under ', 'The explanation appears within ',
])
def test_narrative_reference_cannot_open_business_text_as_risk_section(prefix):
    outside = 'Cloud capacity constraints could harm our revenue.'
    inside = 'Cloud disruptions could adversely affect our operating results.'
    text = prefix + 'Item 1A. Risk Factors. ' + outside + ' Item 1A. Risk Factors ' + inside + ' Item 1B. Unresolved Staff Comments'
    doc = document('MSFT', text)
    items = extract_issuer_risk_evidence(doc, ticker='MSFT', question=CASES['MSFT']['question'])
    assert [i.risk_disclosures[0]['quote'] for i in items] == [inside]
    assert complete_risk_window(text)[0] == text.rindex('Item 1A.')


def test_continued_headers_do_not_repeat_scans_or_bypass_section_ceiling():
    text = 'Item 1A. Risk Factors Historical context. 18 Item 1A. Risk Factors (Continued) Cloud context. Item 1B. Unresolved Staff Comments'
    stats = {}
    spans = list(risk_section_spans(text, max_section_chars=1000, diagnostics=stats))
    assert len(spans) == 1 and stats['complete_sections'] == 1
    assert list(risk_section_spans(text, max_section_chars=50)) == []
    assert complete_risk_window(text, max_section_chars=50) is None


def test_duplicate_unmarked_openings_are_scanned_once():
    text = 'Item 1A. Risk Factors Context. Item 1A. Risk Factors Context. Item 1B. Unresolved Staff Comments'
    assert len(list(risk_section_spans(text, max_section_chars=1000))) == 1


def test_legacy_renewal_question_routing_survives_narrower_source_qualification():
    profile = requested_risk_profile('DOCU', 'What operating risks affect renewals?')
    assert profile and profile.scope == 'Subscription renewals'


@pytest.mark.parametrize('abbreviation', ['e.g.', 'i.e.', 'U.S.', 'U.K.', 'Inc.', 'Ltd.', 'vs.'])
def test_abbreviations_preserve_complete_sentence_and_original_offsets(abbreviation):
    quote = f'Product defects may incur additional costs, {abbreviation} remediation and customer support costs.'
    text = quote + ' Subscription renewals could decline.'
    spans = list(risk_sentence_spans(text))
    assert [text[a:b] for a, b in spans] == [quote, 'Subscription renewals could decline.']


def test_abbreviated_fragment_and_unpunctuated_tail_are_not_complete_sentences():
    assert list(risk_sentence_spans('Product defects may harm revenue, e.g.')) == []
    assert list(risk_sentence_spans('Product defects may harm revenue')) == []
    doc = document('F', 'Item 1A. Risk Factors Product defects may harm revenue, e.g. Item 1B. Unresolved Staff Comments')
    assert extract_issuer_risk_evidence(doc, ticker='F', question=CASES['F']['question']) == []


def test_numeric_metrics_still_fail_closed_after_sentence_repair():
    doc = document('F', 'Item 1A. Risk Factors Product defects may incur 12% higher costs, e.g. repairs. Item 1B. Unresolved Staff Comments')
    assert extract_issuer_risk_evidence(doc, ticker='F', question=CASES['F']['question']) == []


def test_only_periodic_text_removes_observed_page_footer_and_remaps_headings():
    parser = ingestion._HTMLTextExtractor()
    parser.feed('<p>Visible context.</p><p>36 Table of Contents</p><h2>Item 1A. Risk Factors</h2><p>Occupancy could decline.</p>')
    _, ordinary, _, _ = parser.result()
    _, periodic, headings, _ = parser.result(preserve_sec_risk=True)
    assert '36 Table of Contents' in ordinary and '36 Table of Contents' not in periodic
    assert 'Visible context.' in periodic
    assert all(periodic[h.start_offset:h.start_offset + len(h.heading)] == h.heading for h in headings)
    assert parser.normalized_visible_text(preserve_sec_risk=True) == periodic


@pytest.mark.parametrize('content', ['Occupancy fell 36 percent.', 'Revenue 36.', '36 Table of Other Contents', '12345 Table of Contents'])
def test_footer_normalization_preserves_substantive_or_unrecognized_numbers(content):
    parser = ingestion._HTMLTextExtractor(); parser.feed('<p>' + content + '</p>')
    assert parser.normalized_visible_text(preserve_sec_risk=True) == content


# Full sentence observed in the uploaded Hyatt diagnostic, with synthetic HTML
# surroundings. This is a replay, not a fresh SEC retrieval or coverage result.
HYATT = ('Additionally, the timing of renovations and capital improvements has in the past, '
         'and could in the future, affect property performance, including occupancy and ADR, '
         'particularly if we need to close a 36 Table of Contents significant number of rooms '
         'or other facilities, such as ballrooms, meeting spaces, or restaurants.')
BOEING = ('Many of our suppliers are experiencing inflationary pressures, as well as resource '
          'constraints and disruptions due to production quality issues, global supply chain '
          'constraints, and labor instability.')


@pytest.mark.parametrize('ticker,quote', [('H', HYATT), ('BA', BOEING),
    ('F', 'Product defects may incur additional costs, e.g. remediation and customer support costs.')])
def test_observed_or_authored_passages_bind_without_unverified_numeric_claims(ticker, quote):
    parser = ingestion._HTMLTextExtractor()
    parser.feed('<h2>Item 1A. Risk Factors</h2><p>' + quote + '</p><h2>Item 1B. Unresolved Staff Comments</h2>')
    text = parser.result(preserve_sec_risk=True)[1]
    doc = document(ticker, text)
    items = extract_issuer_risk_evidence(doc, ticker=ticker, question=CASES[ticker]['question'])
    assert len(items) == 1
    value = bound_issuer_risk(items[0], ticker=ticker, question=CASES[ticker]['question'])
    assert doc.text[value['start_offset']:value['end_offset']] == quote.replace('36 Table of Contents ', '')
    admitted, refs, _ = admit_evidence(items, evaluated_at='2026-10-07')
    thesis = InvestmentThesis(ticker=ticker, company_name=CASES[ticker]['company'])
    result = apply_source_answer_gate(thesis, CASES[ticker]['question'], admitted, references=refs)
    assert result['status'] == 'attributed' and '[E1]' in thesis.direct_answer
    assert 'does not independently verify' in thesis.direct_answer
    samples = topic_inspection(doc, ticker=ticker, question=CASES[ticker]['question'])['topic_sentence_samples']
    assert len(samples) == 1 and samples[0]['start_offset'] == value['start_offset']


@pytest.mark.parametrize('quote', [
    'Membership pricing may change from time to time.',
    'Occupancy could affect our property performance.',
    'Product quality is experiencing improvements in customer satisfaction.',
    'Renewals related to entertainment industry collective bargaining agreements could negatively impact production costs.',
    'We could incur additional costs to renew content licenses.',
])
def test_topicless_or_nonadverse_language_is_not_promoted(quote):
    ticker = 'NFLX' if 'renew' in quote.lower() else 'H' if 'Occupancy' in quote else 'F'
    doc = document(ticker, f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments')
    assert extract_issuer_risk_evidence(doc, ticker=ticker, question=CASES[ticker]['question']) == []


def test_observed_long_section_length_fits_bounded_window_but_larger_still_fails():
    quote = 'Government contracts may be lost, which could harm our revenue.'
    text = 'Item 1A. Risk Factors ' + 'Context. ' * 33170 + quote + ' Item 1B. Unresolved Staff Comments'
    doc = document('PLTR', text)
    assert len(text) > 298000 and len(text) < 320000
    assert len(extract_issuer_risk_evidence(doc, ticker='PLTR', question=CASES['PLTR']['question'])) == 1
    oversized = replace(doc, text=text.replace('Context. ', 'Longer context. '))
    assert extract_issuer_risk_evidence(oversized, ticker='PLTR', question=CASES['PLTR']['question']) == []


def test_large_section_survives_periodic_retention_with_explicit_closing():
    quote = 'Government contracts may be lost, which could harm our revenue.'
    parser = ingestion._HTMLTextExtractor()
    parser.feed('<p>' + 'Preface. ' * 5500 + '</p><h2>Item 1A. Risk Factors</h2><p>'
                + 'Context. ' * 33170 + quote + '</p><h2>Item 1B. Unresolved Staff Comments</h2>')
    text = parser.result(max_chars=ingestion.MAX_SEC_PERIODIC_CHARS, preserve_sec_risk=True)[1]
    assert 340000 < len(text) <= ingestion.MAX_SEC_PERIODIC_CHARS
    doc = document('PLTR', text)
    items = extract_issuer_risk_evidence(doc, ticker='PLTR', question=CASES['PLTR']['question'])
    value = bound_issuer_risk(items[0], ticker='PLTR', question=CASES['PLTR']['question'])
    assert doc.text[value['start_offset']:value['end_offset']] == quote
