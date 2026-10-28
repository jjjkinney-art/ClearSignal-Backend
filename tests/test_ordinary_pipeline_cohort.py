"""Actual ordinary routing with synthetic SEC filing paths and one cohort ledger.

This test stubs other providers and history. It is not an approved executor,
native socket fence, signed-in flow, or assessment of real-company quality.
"""
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from contextvars import ContextVar
import socket
import threading
import ssl
from app.schemas import QuestionRequest
from app.services import router_service as router
from app.services.verified_sec_metric_service import fetch_verified_metric_evidence as REAL_METRIC_FETCH
from app.services.thesis_disclosures import fetch_thesis_disclosures as REAL_DISCLOSURES
from app.services.filing_metric_evidence import fetch_latest_filing_metrics as REAL_FILING_METRICS
from app.services.providers.sec_provider import fetch_recent_filings as REAL_FILINGS
from test_source_evidence_latency import isolated_pipeline

from validation.ordinary_artifacts import export_fixture_packet
from validation.ordinary_coordinator import run_offline_cases
from validation.ordinary_pilot_accounting import OfflineAccounting
from validation.ordinary_wire_rehearsal import rehearse_sec

CASES = json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())


@pytest.mark.parametrize('fault', [None, 'wire_connect_failure', 'wire_read_failure'])
def test_actual_routed_answers_retained_in_one_fixture_cohort(isolated_pipeline, monkeypatch, tmp_path, fault):
    import validation.pilot_approved as approved
    monkeypatch.setattr(approved, 'verify_network_configuration',
                        lambda config, tls=False: ssl.create_default_context() if tls else None)
    from app.config import settings
    from app.providers import sec_client
    from app.services import issuer_identity, verified_sec_metric_service, public_document_ingestion
    from app.services import thesis_disclosures, filing_metric_evidence
    monkeypatch.setattr(settings, 'auth_enabled', False)
    monkeypatch.setattr(router.watchlist_service, 'process_new_thesis', lambda thesis: (None, None))
    monkeypatch.setattr(verified_sec_metric_service, 'fetch_verified_metric_evidence', REAL_METRIC_FETCH)
    tick = [0.0]
    book = OfflineAccounting(tmp_path / 'cohort.db', clock=lambda: tick[0])
    active = [None]
    initial_threads = set(threading.enumerate())

    stage = ContextVar('cohort_fixture_stage', default='evidence.sec')
    def scoped(fn, name):
        def call(*args, **kwargs):
            token = stage.set(name)
            try: return fn(*args, **kwargs)
            finally: stage.reset(token)
        return call
    monkeypatch.setattr(router._sec_provider, 'fetch_recent_filings', REAL_FILINGS)
    monkeypatch.setattr(thesis_disclosures, 'fetch_thesis_disclosures', scoped(REAL_DISCLOSURES, 'evidence.thesis_disclosures'))
    monkeypatch.setattr(filing_metric_evidence, 'fetch_latest_filing_metrics', scoped(REAL_FILING_METRICS, 'evidence.filing_metrics'))
    def fixture_dns(host, port, **kwargs):
        assert host == 'www.sec.gov' and port == 443
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(public_document_ingestion.socket, 'getaddrinfo', fixture_dns)

    def exchange(url):
        case = active[0]
        route = ('sec/facts' if '/companyfacts/' in url else
                 'sec/submissions' if '/submissions/' in url else 'sec/document')
        current_stage = 'evidence.sec_metrics' if route == 'sec/facts' else stage.get()
        scenario = (fault if fault and case['case_id'] == CASES[2]['case_id'] and route == 'sec/facts'
                    else 'reported-facts' if route == 'sec/facts' else 'happy')
        exchange_result = rehearse_sec(book, case['case_id'], stage=current_stage, route=route,
                                      scenario=scenario, bound=True, scoped=True)
        assert exchange_result['scoped_dispatches'] == exchange_result['simulated_connections'] == 1
        receipt = exchange_result['receipt']
        assert receipt['url'] == url
        with sqlite3.connect(book.path) as db:
            raw, = db.execute('SELECT body FROM bodies WHERE attempt_id=?', (receipt['attempt_id'],)).fetchone()
        return raw

    class DocumentResponse:
        headers = {'Content-Type': 'text/html'}
        encoding = 'utf-8'
        status_code = 200
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def iter_content(self, chunk_size=65536):
            for offset in range(0, len(self.body), chunk_size): yield self.body[offset:offset+chunk_size]
        def close(self): pass

    def fixture_get(url, **kwargs):
        raw = exchange(url)
        return (httpx.Response(200, content=raw, request=httpx.Request('GET', url))
                if '/companyfacts/' in url else DocumentResponse(raw))

    monkeypatch.setattr(sec_client.requests, 'get', fixture_get)
    monkeypatch.setattr(router._sec_provider, '_fetch_json', lambda url, **kwargs: json.loads(exchange(url)))
    def invoke(case_id):
        case = next(c for c in CASES if c['case_id'] == case_id)
        active[0] = case
        ticker, cik = case['issuer_id'], case['expected_cik']
        directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'cik_str': int(cik),
                                                           'title': 'Invented fixture issuer ' + ticker}})
        monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
        monkeypatch.setattr(router._sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
        monkeypatch.setattr(verified_sec_metric_service, '_load_ticker_cik_map', lambda: {ticker: cik})
        response = router.route_question(QuestionRequest(company_name=ticker, question=case['question']))
        if not book.summary()['halt']:
            assert response.company == ticker and response.routing['response_mode'] == 'source_evidence'
        tick[0] += 2.0
        return response.model_dump(mode='json')

    def drain():
        workers = [t for t in threading.enumerate() if t not in initial_threads and t.name.startswith('ThreadPoolExecutor-')]
        for worker in workers: worker.join(3)
        return sum(worker.is_alive() for worker in workers)

    result = run_offline_cases(book, invoke, drain, forbidden_values=('invented-secret',))
    with sqlite3.connect(book.path) as db:
        attempts, bound = db.execute('SELECT COUNT(*),COUNT(request_sha256) FROM attempts').fetchone()
        assert attempts == bound
    packet = export_fixture_packet(book, forbidden_values=('invented-secret',), require_bound=True)
    if fault:
        assert result['failure_class']
        assert packet['halt'] and packet['denominator'] == 12
        assert [r['status'] for r in packet['cases']] == ['partial_gap', 'partial_gap', 'halted'] + ['not_run_after_halt'] * 9
        assert set(packet['answers']) == {CASES[0]['case_id'], CASES[1]['case_id']}
        assert packet['quality_pass_rate'] is None and not packet['launch_ready']
        return
    assert result['failure_class'] is None
    assert len(packet['answers']) == packet['denominator'] == 12
    assert len(packet['attempts']) == 48
    assert all(row['status'] == 'partial_gap' for row in packet['cases'])
    assert all(row['outcome'] == 'success' for row in packet['attempts'])
    assert packet['request_binding_required'] and all(r['request_sha256'] for r in packet['attempts'])
    for case in CASES:
        routes = [r['route'] for r in packet['attempts'] if r['case_id'] == case['case_id']]
        assert routes.count('sec/facts') == 1 and routes.count('sec/submissions') == (3 if case['question_id'] == 'core_thesis' else 1)
        assert routes.count('sec/document') == (2 if case['question_id'] == 'core_thesis' else 0)
    assert all(packet['answers'][case['case_id']]['response']['company'] == case['issuer_id'] for case in CASES)
    assert isolated_pipeline == [] and packet['quality_pass_rate'] is None and not packet['launch_ready']
