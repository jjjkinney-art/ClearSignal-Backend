"""Threshold filing explanations: same-request submissions reuse and honest gaps.

No network: the SEC fetch is replaced in every test. The switch is off by default
and off means the previous code path.
"""
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import Settings, settings
from app.services import filing_metric_evidence, router_service
from app.services.providers import sec_provider
from app.services.source_answer import apply_evidence_gaps, evidence_gaps

CIK = '0001234567'
URL = f'https://data.sec.gov/submissions/CIK{CIK}.json'
BODY = {'cik': '1234567', 'name': 'Invented Co', 'filings': {'recent': {'form': ['10-Q']}}}


class Fetches:
    def __init__(self, result=BODY, delay=0.0):
        self.urls, self.result, self.delay, self.lock = [], result, delay, threading.Lock()

    def __call__(self, url, timeout=10):
        with self.lock:
            self.urls.append(url)
        time.sleep(self.delay)
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


def test_the_switch_is_off_by_default():
    assert Settings.model_fields['threshold_filing_explanations_enabled'].default is False


def test_concurrent_stages_share_one_get_and_get_their_own_copy(monkeypatch):
    fetch = Fetches(delay=0.2)
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    scope = sec_provider.SubmissionsRequestScope()
    with ThreadPoolExecutor(8) as pool:
        bodies = list(pool.map(lambda _: scope.fetch(URL, CIK, timeout=10), range(8)))
    assert fetch.urls == [URL]
    assert scope.fetches == 1 and scope.reuses == 7 and scope.failures == 0
    assert all(body == BODY for body in bodies)
    bodies[0]['filings']['recent']['form'].append('tampered')
    assert scope.fetch(URL, CIK, timeout=10) == BODY
    assert bodies[1] == BODY


def test_a_failed_get_is_shared_and_never_retried_within_the_request(monkeypatch):
    fetch = Fetches(result=OSError('read failed'), delay=0.1)
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    scope = sec_provider.SubmissionsRequestScope()

    def attempt(_):
        try:
            scope.fetch(URL, CIK, timeout=10)
        except OSError:
            return 'owner failure'
        except sec_provider.SubmissionsUnavailable:
            return 'shared failure'

    with ThreadPoolExecutor(4) as pool:
        outcomes = sorted(pool.map(attempt, range(4)))
    assert outcomes == ['owner failure'] + ['shared failure'] * 3
    assert fetch.urls == [URL] and scope.failures == 1
    with pytest.raises(sec_provider.SubmissionsUnavailable):
        scope.fetch(URL, CIK, timeout=10)
    assert fetch.urls == [URL]


def test_an_abort_while_fetching_releases_waiters(monkeypatch):
    class Abandoned(BaseException):
        pass
    monkeypatch.setattr(sec_provider, '_fetch_json', Fetches(result=Abandoned(), delay=0.1))
    scope = sec_provider.SubmissionsRequestScope()
    owner = threading.Thread(target=lambda: pytest.raises(Abandoned, scope.fetch, URL, CIK, timeout=10))
    owner.start()
    time.sleep(0.02)
    started = time.monotonic()
    with pytest.raises(sec_provider.SubmissionsUnavailable):
        scope.fetch(URL, CIK, timeout=10)
    owner.join()
    assert time.monotonic() - started < 5


@pytest.mark.parametrize('body', [{'cik': '7654321', 'name': 'Another Co'}, {'name': 'No cik'}, ['not', 'an', 'object']])
def test_a_response_for_another_issuer_is_refused_and_not_reused(monkeypatch, body):
    monkeypatch.setattr(sec_provider, '_fetch_json', Fetches(result=body))
    scope = sec_provider.SubmissionsRequestScope()
    with pytest.raises(sec_provider.SubmissionsUnavailable):
        scope.fetch(URL, CIK, timeout=10)
    with pytest.raises(sec_provider.SubmissionsUnavailable):
        scope.fetch(URL, CIK, timeout=10)
    assert scope.failures == 1


def test_issuers_and_requests_never_share_a_response(monkeypatch):
    other_url = 'https://data.sec.gov/submissions/CIK0007654321.json'
    def fetch(url, timeout=10):
        fetch.urls.append(url)
        return {'cik': url[-15:-5].lstrip('0'), 'name': url}
    fetch.urls = []
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    first, second = sec_provider.SubmissionsRequestScope(), sec_provider.SubmissionsRequestScope()
    assert first.fetch(URL, CIK, timeout=10)['name'] == URL
    assert first.fetch(other_url, '0007654321', timeout=10)['name'] == other_url
    assert second.fetch(URL, CIK, timeout=10)['name'] == URL
    assert fetch.urls == [URL, other_url, URL]


def test_the_scope_reaches_worker_threads_only_when_bound_and_does_not_leak(monkeypatch):
    scope = sec_provider.SubmissionsRequestScope()
    with ThreadPoolExecutor(1) as pool:
        assert pool.submit(sec_provider._submissions_scope.get).result() is None
        bound = sec_provider.bind_submissions_scope(sec_provider._submissions_scope.get, scope)
        assert pool.submit(bound).result() is scope
        assert pool.submit(sec_provider._submissions_scope.get).result() is None
    assert sec_provider.bind_submissions_scope(print, None) is print


def test_the_provider_fetches_every_time_without_a_scope(monkeypatch):
    fetch = Fetches()
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'INVT': CIK})
    for _ in range(2):
        sec_provider._fetch_by_cik('INVT', None, 2, 2)
    assert fetch.urls == [URL, URL]


def test_the_provider_uses_the_bound_scope(monkeypatch):
    fetch = Fetches()
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'INVT': CIK})
    scope = sec_provider.SubmissionsRequestScope()
    run = sec_provider.bind_submissions_scope(lambda: sec_provider._fetch_by_cik('INVT', None, 2, 2), scope)
    run(), run()
    assert fetch.urls == [URL] and scope.reuses == 1


@pytest.mark.parametrize('fallback,option_b,expected', [(False, False, False), (True, False, True),
                                                        (False, True, True), (True, True, True)])
def test_the_filing_request_needs_a_switch(monkeypatch, fallback, option_b, expected):
    question = ('Which valuation and operating assumptions would make Invented Co attractive or unattractive? '
                'Explain decision thresholds, evidence and uncertainty without inventing figures.')
    monkeypatch.setattr(settings, 'decision_monitoring_inputs_enabled', True)
    monkeypatch.setattr(settings, 'decision_monitoring_filing_fallback_enabled', fallback)
    monkeypatch.setattr(settings, 'threshold_filing_explanations_enabled', option_b)
    assert filing_metric_evidence._monitoring_filing_request(question) is expected


def test_option_b_needs_the_monitoring_inputs(monkeypatch):
    monkeypatch.setattr(settings, 'decision_monitoring_inputs_enabled', False)
    monkeypatch.setattr(settings, 'threshold_filing_explanations_enabled', True)
    assert filing_metric_evidence._monitoring_filing_request('What decision thresholds apply?') is False


def _collect(tasks, **kwargs):
    with ThreadPoolExecutor(len(tasks)) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        return router_service._collect_investment_evidence(futures, source_evidence_view=True, **kwargs)


def test_the_document_wait_is_shorter_only_when_asked_and_late_evidence_is_dropped(monkeypatch):
    waits = []
    def fake_wait(fs, timeout=None, return_when=None):
        waits.append(timeout)
        return set(), set(fs)
    monkeypatch.setattr(router_service, '_cf_wait', fake_wait)
    release = threading.Event()
    abandoned = []
    def late():
        release.wait(5)
        return ['late filing evidence']
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(late)
        results = router_service._collect_investment_evidence(
            {'filing_metrics': future}, source_evidence_view=True, document_seconds=16, abandoned=abandoned)
        release.set()
        assert future.result() == ['late filing evidence']
    assert results == {'filing_metrics': []} and abandoned == ['filing_metrics']
    assert waits[0] == 10 and 15 < waits[1] <= 16


def test_collection_defaults_are_unchanged():
    assert _collect({'sec': lambda: ['fact']}) == {'sec': ['fact']}


def test_failed_tasks_are_not_reported_as_abandoned():
    abandoned = []
    def boom():
        raise OSError('failed')
    assert _collect({'filing_metrics': boom}, abandoned=abandoned) == {'filing_metrics': []}
    assert abandoned == []


class Thesis:
    direct_answer = 'Evidence-backed financial monitoring (partial)'


def test_a_gap_is_stated_to_the_user_and_recorded():
    thesis = Thesis()
    gaps = evidence_gaps(['filing_metrics', 'news_co'], 0)
    assert gaps == [{'source': 'the latest SEC filing', 'task': 'filing_metrics', 'reason': 'time_limit'}]
    source = apply_evidence_gaps(thesis, {'status': 'attributed', 'claims': [1]}, gaps)
    assert thesis.direct_answer.startswith('Incomplete answer: the latest SEC filing could not be read for this answer')
    assert 'including any drivers management states there' in thesis.direct_answer
    assert thesis.direct_answer.endswith('Evidence-backed financial monitoring (partial)')
    assert source['degraded'] is True and source['status'] == 'partial' and source['evidence_gaps'] == gaps
    assert source['claims'] == [1] and 'evidence from the latest SEC filing' in source['unanswered_parts']
    apply_evidence_gaps(thesis, source, gaps)
    assert thesis.direct_answer.count('Incomplete answer') == 1


def test_a_failed_filing_list_is_a_gap():
    assert evidence_gaps([], 1) == [{'source': 'the SEC filing list', 'task': 'sec_submissions',
                                     'reason': 'retrieval_failed'}]


def test_a_failed_filing_read_is_a_gap_and_reaches_the_request_scope():
    assert evidence_gaps([], 0, 1) == [{'source': 'the latest SEC filing', 'task': 'filing_document',
                                        'reason': 'not_read'}]
    scope = sec_provider.SubmissionsRequestScope()
    sec_provider.note_filing_read_failure()  # no active scope: nothing to tell
    sec_provider.bind_submissions_scope(sec_provider.note_filing_read_failure, scope)()
    assert scope.filing_read_failures == 1


def test_a_gap_elsewhere_does_not_claim_the_drivers_are_missing():
    thesis = Thesis()
    apply_evidence_gaps(thesis, {'status': 'partial'}, evidence_gaps(['sec_metrics'], 0))
    assert thesis.direct_answer.startswith('Incomplete answer: SEC company facts could not be read')
    assert 'drivers' not in thesis.direct_answer


def test_a_filing_arriving_after_the_cutoff_is_not_parsed(monkeypatch):
    from app.services import public_document_ingestion as ingestion
    parsed = []
    monkeypatch.setattr(ingestion, 'parse_inline_observations', lambda *a, **k: parsed.append(1) or [], raising=False)
    monkeypatch.setattr(ingestion, '_validate_public_url', lambda url: url)
    class Response:
        status_code, is_redirect, url = 200, False, 'https://www.sec.gov/Archives/edgar/data/1/a/b.htm'
        headers = {'Content-Type': 'text/html'}
        encoding = 'utf-8'
        def close(self): pass
        def raise_for_status(self): pass
    monkeypatch.setattr(ingestion.requests, 'get', lambda *a, **k: Response())
    monkeypatch.setattr(ingestion, '_read_bounded', lambda *a, **k: b'<html>body</html>')
    monkeypatch.setattr(ingestion, '_guarded_request', lambda *a, **k: Response(), raising=False)
    with pytest.raises(ingestion.PublicDocumentError) as refused:
        ingestion.fetch_public_document(Response.url, user_agent='Invented invented@example.invalid',
                                        parse_deadline=time.monotonic() - 1)
    assert refused.value.failure_kind == 'time_limit' and parsed == []


def test_only_a_scope_with_a_cutoff_limits_parsing():
    assert sec_provider.filing_parse_deadline() is None
    scope = sec_provider.SubmissionsRequestScope()
    assert sec_provider.bind_submissions_scope(sec_provider.filing_parse_deadline, scope)() is None
    scope.filing_parse_deadline = 123.0
    assert sec_provider.bind_submissions_scope(sec_provider.filing_parse_deadline, scope)() == 123.0


def test_no_gap_changes_nothing():
    thesis, source = Thesis(), {'status': 'partial'}
    assert apply_evidence_gaps(thesis, source, []) is source
    assert thesis.direct_answer == 'Evidence-backed financial monitoring (partial)'
    assert apply_evidence_gaps(thesis, None, evidence_gaps(['sec'], 0)) is None
