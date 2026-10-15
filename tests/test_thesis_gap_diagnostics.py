"""Offline diagnostics use synthetic filings and never relax evidence admission."""
import logging
from types import SimpleNamespace

import pytest

from app.services import thesis_disclosures as service
from app.services.public_document_ingestion import PublicDocumentError
from test_thesis_disclosures import document, QUESTION
from validation.thesis_diagnostics import ThesisDiagnosticCollector, safe_thesis_diagnostic


@pytest.fixture
def collector():
    handler = ThesisDiagnosticCollector()
    handler.begin('ASML:core_thesis')
    old = service.logger.level
    service.logger.setLevel(logging.INFO)
    service.logger.addHandler(handler)
    yield handler
    service.logger.removeHandler(handler)
    service.logger.setLevel(old)


def setup(monkeypatch, doc):
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **kw: [
        SimpleNamespace(url=doc.final_url, timestamp=doc.published_at, document_type='10-K')])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **kw: doc)
    monkeypatch.setattr(service, 'extract_issuer_risk_evidence', lambda *a, **kw: [])
    from app.services import thesis_competition
    monkeypatch.setattr(thesis_competition, 'extract_competition_descriptions', lambda *a, **kw: [])


def test_business_success_persists_counts_without_source_text(monkeypatch, collector):
    doc = document(); setup(monkeypatch, doc)
    items = service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    assert len(items) == 1
    row = collector.rows[0]
    assert row['stage'] == 'extraction' and row['status'] == 'extraction_complete'
    assert row['business_count'] == 1
    assert row['business_extraction']['status'] == 'business_extracted'
    assert doc.text not in str(row) and doc.final_url not in str(row)


def test_missing_section_is_distinct_from_rejected_sentences(monkeypatch, collector):
    setup(monkeypatch, document('Synthetic unrelated section without business headings.'))
    assert not service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    assert collector.rows[-1]['business_extraction']['status'] == 'no_complete_business_section'
    collector.begin('NPK:core_thesis')
    setup(monkeypatch, document('Item 1. Business We expect to grow our business and generate superior returns. '
                               'Item 1A. Risk Factors Synthetic risk. Item 1B. Unresolved Staff Comments'))
    assert not service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    row = collector.rows[-1]
    assert row['case_id'] == 'NPK:core_thesis'
    assert row['business_extraction']['status'] == 'no_qualifying_business_sentence'
    assert row['business_extraction']['rejection_counts']


def test_document_failure_records_fixed_code_not_exception_text(monkeypatch, collector):
    setup(monkeypatch, document())
    def fail(*a, **kw):
        raise PublicDocumentError('PRIVATE-CANARY document URL', failure_kind='http_error', http_status=403)
    monkeypatch.setattr(service, 'fetch_public_document', fail)
    assert not service.fetch_thesis_disclosures('AAPL', question=QUESTION)
    row = collector.rows[0]
    assert row['stage'] == 'annual_document' and row['status'] == 'document_error'
    assert row['document_failure_kind'] == 'http_error' and row['http_status'] == 403
    assert 'PRIVATE-CANARY' not in str(row)


@pytest.mark.parametrize('value', [None, [], {'stage': []},
    {'stage': 'PRIVATE-CANARY', 'status': 'document_error'},
    {'stage': 'extraction', 'status': {'secret': 'PRIVATE-CANARY'}}])
def test_malformed_or_unknown_diagnostic_is_discarded(value):
    assert safe_thesis_diagnostic(value) is None


def test_diagnostic_allowlist_drops_credentials_text_and_invalid_counts():
    row = safe_thesis_diagnostic({'stage': 'extraction', 'status': 'extraction_complete',
        'url': 'PRIVATE-CANARY', 'error': 'PRIVATE-CANARY', 'business_count': True,
        'risk_count': 2001, 'http_status': '403', 'document_failure_kind': 'PRIVATE-CANARY',
        'business_extraction': {'status': [], 'sentences': -1,
            'rejection_counts': {'PRIVATE-CANARY': 1, 'length': 2, 'subject_or_activity': False}}})
    assert row == {'stage': 'extraction', 'status': 'extraction_complete',
                   'business_extraction': {'rejection_counts': {'length': 2}}}


def test_collector_does_not_capture_formatted_logs_and_is_bounded():
    collector = ThesisDiagnosticCollector(); collector.begin('ASML:core_thesis')
    ordinary = logging.LogRecord(service.logger.name, logging.INFO, '', 0, 'PRIVATE-CANARY', (), None)
    collector.handle(ordinary)
    assert not collector.rows
    for _ in range(10):
        record = logging.LogRecord(service.logger.name, logging.INFO, '', 0, 'PRIVATE-CANARY', (), None)
        record.thesis_disclosure_diagnostics = {'stage':'identity', 'status':'identity_unavailable'}
        collector.handle(record)
    assert len(collector.rows) == 6 and 'PRIVATE-CANARY' not in str(collector.rows)


def test_terminal_snapshot_is_sealed_against_late_worker_diagnostics():
    collector = ThesisDiagnosticCollector(); collector.begin('ACHC:core_thesis')
    record = logging.LogRecord(service.logger.name, logging.INFO, '', 0, 'ignored', (), None)
    record.thesis_disclosure_diagnostics = {'stage':'identity', 'status':'identity_unavailable'}
    collector.handle(record)
    terminal = collector.snapshot()
    collector.begin('NPK:core_thesis')
    collector.handle(record)
    assert collector.snapshot() == terminal and len(terminal) == 1
    assert terminal[0]['case_id'] == 'ACHC:core_thesis'
