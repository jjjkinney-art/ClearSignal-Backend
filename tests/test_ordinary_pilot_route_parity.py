"""Offline routing/composition parity, not native fencing or research grading."""
from datetime import datetime, timezone
import json
import threading
from pathlib import Path

import pytest
from app.schemas import QuestionRequest
from app.services import router_service as router
from test_source_evidence_latency import isolated_pipeline
from test_financial_thesis_foundation import pair

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
@pytest.mark.parametrize('has_evidence', [False, True], ids=['source-gap', 'reported-comparisons'])
def test_normal_route_matches_side_effect_free_composition(isolated_pipeline, monkeypatch, case, has_evidence):
    from app.services import issuer_identity, verified_sec_metric_service
    from app.config import settings
    monkeypatch.setattr(settings, 'auth_enabled', False)
    ticker, cik = case['issuer_id'], case['expected_cik']
    directory = issuer_identity.parse_directory({'0': {
        'ticker': ticker, 'cik_str': int(cik), 'title': 'Invented fixture issuer ' + ticker}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(router._sec_provider, '_load_ticker_cik_map', lambda: {ticker: cik})
    items = pair(ticker=ticker, cik=cik) if has_evidence else []
    monkeypatch.setattr(verified_sec_metric_service, 'fetch_verified_metric_evidence', lambda *a, **k: items)
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
    isolated = original(**routed, side_effects_enabled=False)
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
    if has_evidence and case['question_id'] == 'core_thesis':
        assert len(normal.answer['source_answer']['claims']) == 2
