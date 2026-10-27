"""Actual ordinary routing with synthetic SEC facts and one twelve-case ledger.

This test stubs other providers and history. It is not an approved executor,
native socket fence, signed-in flow, or assessment of real-company quality.
"""
import json
import sqlite3
from pathlib import Path

import httpx
from app.schemas import QuestionRequest
from app.services import router_service as router
from app.services.verified_sec_metric_service import fetch_verified_metric_evidence as REAL_METRIC_FETCH
from test_source_evidence_latency import isolated_pipeline

from validation.ordinary_artifacts import export_fixture_packet, store_fixture_answer
from validation.ordinary_case_lifecycle import OfflineCaseLifecycle
from validation.ordinary_pilot_accounting import OfflineAccounting
from validation.ordinary_wire_rehearsal import rehearse_facts

CASES = json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())


def test_actual_routed_answers_retained_in_one_fixture_cohort(isolated_pipeline, monkeypatch, tmp_path):
    from app.config import settings
    from app.providers import sec_client
    from app.services import issuer_identity, verified_sec_metric_service
    monkeypatch.setattr(settings, 'auth_enabled', False)
    monkeypatch.setattr(router.watchlist_service, 'process_new_thesis', lambda thesis: (None, None))
    monkeypatch.setattr(verified_sec_metric_service, 'fetch_verified_metric_evidence', REAL_METRIC_FETCH)
    tick = [0.0]
    book = OfflineAccounting(tmp_path / 'cohort.db', clock=lambda: tick[0])
    lifecycle = OfflineCaseLifecycle(book)
    active = [None]

    def fixture_get(url, **kwargs):
        case = active[0]
        assert url == f'https://data.sec.gov/api/xbrl/companyfacts/CIK{case["expected_cik"]}.json'
        receipt = rehearse_facts(book, case['case_id'], scenario='reported-facts')['receipt']
        with sqlite3.connect(book.path) as db:
            raw, = db.execute('SELECT body FROM bodies WHERE attempt_id=?', (receipt['attempt_id'],)).fetchone()
        return httpx.Response(200, content=raw, request=httpx.Request('GET', url))

    monkeypatch.setattr(sec_client.requests, 'get', fixture_get)
    for case in CASES:
        active[0] = case
        ticker, cik = case['issuer_id'], case['expected_cik']
        directory = issuer_identity.parse_directory({'0': {'ticker': ticker, 'cik_str': int(cik),
                                                           'title': 'Invented fixture issuer ' + ticker}})
        monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
        monkeypatch.setattr(router._sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
        monkeypatch.setattr(verified_sec_metric_service, '_load_ticker_cik_map', lambda: {ticker: cik})
        lifecycle.begin(case['case_id'])
        response = router.route_question(QuestionRequest(company_name=ticker, question=case['question']))
        assert response.company == ticker and response.routing['response_mode'] == 'source_evidence'
        store_fixture_answer(book, case['case_id'], response.model_dump(mode='json'),
                             forbidden_values=('invented-secret',))
        lifecycle.finish(case['case_id'], status='partial_gap')
        tick[0] += 2.0
    lifecycle.finalize()
    packet = export_fixture_packet(book, forbidden_values=('invented-secret',))
    assert len(packet['answers']) == len(packet['attempts']) == packet['denominator'] == 12
    assert all(row['status'] == 'partial_gap' for row in packet['cases'])
    assert all(row['route'] == 'sec/facts' and row['outcome'] == 'success' for row in packet['attempts'])
    assert all(packet['answers'][case['case_id']]['response']['company'] == case['issuer_id'] for case in CASES)
    assert isolated_pipeline == [] and packet['quality_pass_rate'] is None and not packet['launch_ready']
