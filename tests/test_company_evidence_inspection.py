"""Bounded public diagnostics cannot relax attribution or expose credentials."""
import json
import socket

import pytest
import requests

from app.services import issuer_identity, public_document_ingestion as ingestion
from app.services.issuer_risk_evidence import risk_quote_rejections, requested_risk_profile
from scripts import company_evidence_acceptance as acceptance
from scripts.company_evidence_inspection import (
    boundary_inspection, rejection_reason, submission_inventory, topic_inspection,
)

CASE = next(c for c in json.loads(acceptance.COHORT_PATH.read_text())["cases"] if c["ticker"] == "COST")
QUOTE = 'Membership renewals could decline and adversely affect our operating results.'


@pytest.fixture(autouse=True)
def issuer(monkeypatch):
    directory = issuer_identity.parse_directory({"0": {
        "ticker": CASE["ticker"], "title": CASE["company"], "cik_str": int(CASE["cik"])}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    monkeypatch.setattr(issuer_identity, "_cache", directory)
    monkeypatch.setattr(acceptance.live.sec_provider, "_ticker_cik_cache", {CASE["ticker"]: CASE["cik"].zfill(10)})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])


class Response:
    status_code = 200
    encoding = 'utf-8'

    def __init__(self, body, headers=None):
        self.body = body
        self.headers = {'Content-Type': 'text/html', **(headers or {})}
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def raise_for_status(self):
        pass

    def close(self):
        self.closed = True


def prepare(monkeypatch, text, *, headers=None):
    payload = {'name': CASE['company'], 'filings': {'recent': {
        'form': ['10-K'], 'filingDate': ['2026-03-02'], 'reportDate': ['2025-12-31'],
        'accessionNumber': ['0000000000-26-000001'], 'primaryDocument': ['fixture.htm']}, 'files': []},
        'private_test_metadata': 'credential-canary'}
    monkeypatch.setattr(acceptance.live.sec_provider, '_fetch_json', lambda *a, **k: payload)
    response = Response(('<html><body>' + text + '</body></html>').encode(), headers)
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    return response


def test_inspection_preserves_real_fetch_and_binding_with_late_compact_heading(monkeypatch):
    prepare(monkeypatch, 'Visible preface. ' * 22000 + 'Item 1A. Risk Factors ' + QUOTE + ' Item 1B.Unresolved Staff Comments')
    baseline = acceptance.run_case(CASE, user_agent='contact-canary', evaluated_at='2026-10-07')
    inspected = acceptance.run_case(CASE, user_agent='contact-canary', evaluated_at='2026-10-07', inspect_source=True)
    assert baseline['passed'] and inspected['passed']
    assert baseline['disclosures'] == inspected['disclosures']
    assert 'source_inspection' not in baseline['document_diagnostics'][0]
    detail = inspected['document_diagnostics'][0]['source_inspection']
    assert detail['full_visible_text_observed'] and detail['admission_authority'] is False
    assert detail['boundaries']['risk_heading_samples'][0]['offset'] > ingestion.MAX_SEC_PERIODIC_CHARS
    assert detail['topic_candidates']['topic_sentence_samples'][0]['excerpt'] == QUOTE
    assert detail['topic_candidates']['topic_sentence_samples'][0]['rejection_reasons'] == []
    assert inspected['filing_discovery'][0]['submission_inventory']['requested_form_counts'] == {'10-K': 1}
    assert 'contact-canary' not in json.dumps(inspected) and 'credential-canary' not in json.dumps(inspected)
    assert CASE['question'] not in json.dumps(inspected)


def test_rejected_topic_is_inspected_without_becoming_evidence(monkeypatch):
    quote = 'Membership renewals could decline by 15% and adversely affect operating results.'
    prepare(monkeypatch, 'Item 1A. Risk Factors ' + quote + ' Item 1B. Unresolved Staff Comments')
    row = acceptance.run_case(CASE, user_agent='test', inspect_source=True)
    assert not row['passed'] and row['admitted_risk_count'] == 0
    stats = row['document_diagnostics'][0]
    assert stats['topic_rejection_counts']['numeric_content'] == 1
    sample = stats['source_inspection']['topic_candidates']['topic_sentence_samples'][0]
    assert sample['excerpt'] == quote and sample['rejection_reasons'] == ['numeric_content']


def test_optional_inventory_failure_does_not_change_discovery_or_binding(monkeypatch):
    prepare(monkeypatch, 'Item 1A. Risk Factors ' + QUOTE + ' Item 1B. Unresolved Staff Comments')
    def invalid(*args, **kwargs):
        raise ValueError('secret malformed metadata')
    monkeypatch.setattr(acceptance, 'submission_inventory', invalid)
    row = acceptance.run_case(CASE, user_agent='test', inspect_source=True)
    assert row['passed']
    assert row['filing_discovery'][0]['submission_inventory'] == {'status': 'invalid_metadata_shape'}
    assert 'secret malformed metadata' not in json.dumps(row)


def test_topic_excerpt_size_and_count_caps_cannot_promote_overlong_candidates(monkeypatch):
    quote = 'Membership renewals could decline ' + 'and adversely affect operations ' * 40 + '.'
    prepare(monkeypatch, 'Item 1A. Risk Factors ' + (quote + ' ') * 20 + 'Item 1B. Unresolved Staff Comments')
    row = acceptance.run_case(CASE, user_agent='test', inspect_source=True)
    assert not row['passed'] and row['admitted_risk_count'] == 0
    samples = row['document_diagnostics'][0]['source_inspection']['topic_candidates']['topic_sentence_samples']
    assert len(samples) == 8 and all(len(s['excerpt']) == 900 for s in samples)
    assert all(s['excerpt_truncated'] and 'length' in s['rejection_reasons'] for s in samples)


def test_opt_in_inspection_excludes_hidden_html_and_inline_xbrl(monkeypatch):
    prepare(monkeypatch, '<div hidden>secret-hidden-canary Item 1A. Risk Factors</div>'
        '<ix:hidden>secret-xbrl-canary Item 1B. Unusual title</ix:hidden>'
        'Item 1A. Risk Factors ' + QUOTE + ' Item 1B. Unresolved Staff Comments')
    row = acceptance.run_case(CASE, user_agent='test', inspect_source=True)
    assert row['passed']
    assert 'secret-hidden-canary' not in json.dumps(row)
    assert 'secret-xbrl-canary' not in json.dumps(row)


def test_ingestion_size_rejection_is_specific_without_relaxing_size_limit(monkeypatch):
    response = prepare(monkeypatch, QUOTE, headers={'Content-Length': str(ingestion.MAX_SEC_PERIODIC_BYTES + 1)})
    row = acceptance.run_case(CASE, user_agent='contact-canary', inspect_source=True)
    assert not row['passed'] and row['documents_retrieved'] == 0
    assert row['retrieval_failures'][0]['rejection_reason'] == 'document_size_limit'
    assert response.closed and row['document_diagnostics'] == []
    assert 'contact-canary' not in json.dumps(row)


def test_unknown_exception_text_is_never_exported():
    exc = ingestion.PublicDocumentError('secret-token user-question private-contact')
    assert rejection_reason(exc) == 'unclassified_rejection'


def test_submission_alignment_diagnostic_finds_unscanned_metadata_without_promoting_it():
    data = {'filings': {'recent': {'form': ['10-Q', '10-K'],
        'filingDate': ['2026-08-03', '2026-02-20'], 'reportDate': ['2026-06-30'],
        'accessionNumber': ['one', 'two'], 'primaryDocument': ['q.htm', 'k.htm']},
        'files': [{'filingTo': '2026-01-01'}, {'filingTo': '2020-01-01'}]}}
    result = submission_inventory(data, forms=['10-K'], cutoff='2024-10-07')
    assert result['requested_form_counts'] == {'10-K': 1}
    assert result['matched_rows_beyond_report_date_array'] == 1
    assert result['within_lookback_archive_count'] == 1
    assert 'q.htm' not in json.dumps(result) and 'k.htm' not in json.dumps(result)


def test_heading_inspection_is_bounded_and_shows_unrecognized_titles():
    text = ('Item 1A. Risk Factors Membership context. Item 1B.Unusual closing title. ' * 100)
    result = boundary_inspection(text)
    assert len(result['risk_heading_samples']) == 8
    assert len(result['numbered_heading_samples']) == 24
    assert result['risk_heading_samples'][0]['recognized_closing_offset'] is None
    assert any('Unusual closing title' in row['context'] for row in result['numbered_heading_samples'])


@pytest.mark.parametrize('quote,reason', [
    ('Membership renewals could decline.', 'length'),
    ('membership renewals could decline and adversely affect operating results.', 'sentence_start'),
    (QUOTE[:-1], 'sentence_end'),
    (QUOTE.replace('could', 'will'), 'possibility_language'),
    ('Membership renewals could continue to support our operating results.', 'adverse_mechanism'),
    ('These membership renewals could decline and adversely affect operating results.', 'unresolved_reference'),
    ('See membership renewals which could decline and adversely affect operating results.', 'cross_reference_or_instruction'),
])
def test_rejection_reason_does_not_accept_formerly_withheld_quotes(quote, reason):
    profile = requested_risk_profile(CASE['ticker'], CASE['question'])
    assert reason in risk_quote_rejections(quote, profile)


def test_complete_quote_passes_existing_rules_and_empty_quote_is_safe():
    profile = requested_risk_profile(CASE['ticker'], CASE['question'])
    assert risk_quote_rejections(QUOTE, profile) == ()
    assert {'length', 'sentence_start', 'sentence_end'} <= set(risk_quote_rejections('', profile))
