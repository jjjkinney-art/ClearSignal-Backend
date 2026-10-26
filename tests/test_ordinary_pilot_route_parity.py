"""Offline routing/composition parity, not native fencing or research grading."""
from datetime import datetime, timezone
import json
import threading
from pathlib import Path

import pytest
from app.schemas import QuestionRequest
from app.services import router_service as router
from app.services.verified_sec_metric_service import fetch_verified_metric_evidence as REAL_METRIC_FETCH
from test_source_evidence_latency import isolated_pipeline
from test_financial_thesis_foundation import pair

from app.services.thesis_disclosures import fetch_thesis_disclosures as REAL_DISCLOSURES
from app.services.filing_metric_evidence import fetch_latest_filing_metrics as REAL_FILING_METRICS
from app.services.providers.sec_provider import fetch_recent_filings as REAL_FILINGS

CASES = json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())


@pytest.fixture(autouse=True)
def drain_workers():
    before = set(threading.enumerate())
    yield
    for worker in threading.enumerate():
        if worker not in before and worker.name.startswith('ThreadPoolExecutor-'):
            worker.join(5)
            assert not worker.is_alive()


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['case_id'])
@pytest.mark.parametrize('has_evidence', [False, True, 'wire', 'wire-positive', 'wire-filings'], ids=['source-gap', 'reported-comparisons', 'bounded-facts-gap', 'bounded-reported-facts', 'bounded-filing-paths'])
def test_normal_route_matches_side_effect_free_composition(isolated_pipeline, monkeypatch, tmp_path, case, has_evidence):
    from app.services import issuer_identity, verified_sec_metric_service
    from app.config import settings
    monkeypatch.setattr(settings, 'auth_enabled', False)
    ticker, cik = case['issuer_id'], case['expected_cik']
    directory = issuer_identity.parse_directory({'0': {
        'ticker': ticker, 'cik_str': int(cik), 'title': 'Invented fixture issuer ' + ticker}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(router._sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    items = pair(ticker=ticker, cik=cik) if has_evidence is True else []
    monkeypatch.setattr(verified_sec_metric_service, 'fetch_verified_metric_evidence', lambda *a, **k: items)
    books = None
    if has_evidence in ('wire', 'wire-positive', 'wire-filings'):
        import httpx
        import sqlite3
        from app.providers import sec_client
        from validation.ordinary_pilot_accounting import OfflineAccounting
        from validation.ordinary_wire_rehearsal import rehearse_facts
        books = [OfflineAccounting(tmp_path / ('path-' + str(i) + '.db')) for i in range(2)]
        active_book = [books[0]]
        monkeypatch.setattr(verified_sec_metric_service, '_load_ticker_cik_map', lambda: {ticker: cik})
        monkeypatch.setattr(verified_sec_metric_service, 'fetch_verified_metric_evidence', REAL_METRIC_FETCH)
        def fixture_get(url, **kwargs):
            assert url == f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            book = active_book[0]
            result = rehearse_facts(book, case['case_id'],
                                    scenario='reported-facts' if has_evidence == 'wire-positive' else 'happy')
            with sqlite3.connect(book.path) as db:
                body = db.execute('SELECT body FROM bodies WHERE attempt_id=?',
                                  (result['receipt']['attempt_id'],)).fetchone()[0]
            return httpx.Response(200, content=body, request=httpx.Request('GET', url))
        monkeypatch.setattr(sec_client.requests, 'get', fixture_get)
        if has_evidence == 'wire-filings':
            from contextvars import ContextVar
            import socket
            from app.services import public_document_ingestion
            def fixture_dns(host, port, **kwargs):
                assert host == 'www.sec.gov' and port == 443
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
            monkeypatch.setattr(public_document_ingestion.socket, 'getaddrinfo', fixture_dns)
            from app.services import thesis_disclosures, filing_metric_evidence
            from validation.ordinary_wire_rehearsal import rehearse_sec
            stage = ContextVar('fixture_stage', default='evidence.sec')
            def scoped(fn, name):
                def call(*args, **kwargs):
                    token = stage.set(name)
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        stage.reset(token)
                return call
            monkeypatch.setattr(router._sec_provider, 'fetch_recent_filings', REAL_FILINGS)
            monkeypatch.setattr(thesis_disclosures, 'fetch_thesis_disclosures', scoped(REAL_DISCLOSURES, 'evidence.thesis_disclosures'))
            monkeypatch.setattr(filing_metric_evidence, 'fetch_latest_filing_metrics', scoped(REAL_FILING_METRICS, 'evidence.filing_metrics'))
            def exchange(url):
                route = ('sec/facts' if '/companyfacts/' in url else
                         'sec/submissions' if '/submissions/' in url else 'sec/document')
                current_stage = 'evidence.sec_metrics' if route == 'sec/facts' else stage.get()
                result = rehearse_sec(active_book[0], case['case_id'], stage=current_stage,
                    route=route, scenario='reported-facts' if route == 'sec/facts' else 'happy')
                assert result['receipt']['url'] == url
                with sqlite3.connect(active_book[0].path) as db:
                    return db.execute('SELECT body FROM bodies WHERE attempt_id=?',
                        (result['receipt']['attempt_id'],)).fetchone()[0]
            monkeypatch.setattr(router._sec_provider, '_fetch_json', lambda url, **kwargs: json.loads(exchange(url)))
            class DocumentResponse:
                headers = {'Content-Type': 'text/html'}
                encoding = 'utf-8'
                status_code = 200
                def __init__(self, body): self.body = body
                def raise_for_status(self): pass
                def iter_content(self, chunk_size=65536):
                    for offset in range(0, len(self.body), chunk_size):
                        yield self.body[offset:offset+chunk_size]
                def close(self): pass
            def get(url, **kwargs):
                body = exchange(url)
                return (httpx.Response(200, content=body, request=httpx.Request('GET', url))
                        if '/companyfacts/' in url else DocumentResponse(body))
            monkeypatch.setattr(sec_client.requests, 'get', get)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 10, 26, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(router, 'datetime', FrozenDateTime)
    from app.services import evidence_integrity
    monkeypatch.setattr(evidence_integrity, 'datetime', FrozenDateTime)
    history = []
    def snapshot(thesis):
        history.append(thesis.ticker)
        return None, None
    monkeypatch.setattr(router.watchlist_service, 'process_new_thesis', snapshot)
    calls = []
    original = router._run_investment_pipeline
    def observed(*args, **kwargs):
        calls.append(kwargs.copy())
        return original(*args, **kwargs)
    monkeypatch.setattr(router, '_run_investment_pipeline', observed)
    normal = router.route_question(QuestionRequest(company_name=ticker, question=case['question']))
    assert len(calls) == 1
    routed = calls[0]
    assert routed['company'].ticker == ticker
    assert routed['question'] == case['question']
    assert routed.get('side_effects_enabled', True) is True
    if books:
        active_book[0] = books[1]
    isolated = original(**routed, side_effects_enabled=False)
    if books:
        for book in books:
            expected = (6 if case['question_id'] == 'core_thesis' else 2) if has_evidence == 'wire-filings' else 1
            assert book.summary()['outcomes'] == {'success': expected}
            assert not book.summary()['halt']
            if has_evidence == 'wire-filings':
                with sqlite3.connect(book.path) as db:
                    routes = dict(db.execute('SELECT route,COUNT(*) FROM attempts GROUP BY route'))
                assert routes == ({'sec/facts': 1, 'sec/submissions': 3, 'sec/document': 2}
                                  if case['question_id'] == 'core_thesis' else
                                  {'sec/facts': 1, 'sec/submissions': 1})
    # Compare the entire answer, including prose, citations, claims and gaps.
    # Fix only the router's generation clock; do not discard differing fields.
    assert normal.model_dump(mode='json')['answer'] == isolated.model_dump(mode='json')['answer']
    assert normal.agents_used == isolated.agents_used == ['source_answer']
    assert normal.routing['response_mode'] == isolated.routing['response_mode'] == 'source_evidence'
    assert isolated_pipeline == []
    assert history == [ticker]  # normal snapshot seam called; isolated call omitted
    for key in ('memory_context_block', 'memory_context_data', 'dossier_context_block',
                'personalization_context_data', 'research_memory_context_block',
                'research_memory_context_data'):
        assert routed.get(key) is None
    if has_evidence is True and case['question_id'] == 'core_thesis':
        assert len(normal.answer['source_answer']['claims']) == 2
    if has_evidence == 'wire-positive' and case['question_id'] == 'core_thesis':
        claims = normal.answer['source_answer']['claims']
        assert len(claims) == 2
        assert any('revenue' in c['claim'].lower() for c in claims)
        assert any('operating income' in c['claim'].lower() for c in claims)
        refs = {r['id'] for r in normal.answer['evidence_references']}
        assert all(c['reference_id'] in refs for c in claims)
        assert all(c['claim'] in normal.answer['investment_thesis']['direct_answer'] for c in claims)
