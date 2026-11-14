"""The application skips a company-facts request only when SEC's own filing list proves absence,
only inside a request scope, and says why. Everything else behaves as it did before.

Synthetic: the scope is filled by hand the way another evidence stage fills it.
"""
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import verified_sec_fact_service as revenue_service
from app.services import verified_sec_metric_service as metric_service
from app.services.providers import sec_provider
from app.services.source_answer import apply_evidence_not_applicable

RETAINED = json.loads((Path(__file__).parent / 'data' / 'sec_submissions_registration_only_retained_run10.json').read_text())
CIK, TICKER = '0001000377', 'ZZADR'
URL = f'{sec_provider._SUBMISSIONS_BASE}/CIK{CIK}.json'
QUESTION = 'What is the investment thesis for Plain Industries Corporation, what supports it, and what could invalidate it?'


def operating():
    body = copy.deepcopy(RETAINED)
    body['entityType'], body['sic'] = 'operating', '6021'
    body['filings']['recent']['isXBRL'][0] = 1
    return body


def scope_with(body, *, done=True):
    scope = sec_provider.SubmissionsRequestScope()
    entry = {'done': threading.Event(), 'data': copy.deepcopy(body)}
    if done:
        entry['done'].set()
    scope._entries[URL] = entry
    return scope


@pytest.fixture
def facts(monkeypatch):
    """Spy on the company-facts request; it must never be reached when absence is proven."""
    calls = []
    monkeypatch.setattr(metric_service, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    monkeypatch.setattr(revenue_service, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    monkeypatch.setattr(metric_service, 'get_company_fact_records_for_concept_units',
                        lambda cik, **kwargs: calls.append(('metrics', cik)) or [])
    monkeypatch.setattr(revenue_service, 'get_company_fact_records_for_concepts',
                        lambda cik, **kwargs: calls.append(('revenue', cik)) or [])
    return calls


def run(scope, fn):
    return sec_provider.bind_submissions_scope(fn, scope)()


def test_proven_absence_makes_no_facts_request_and_is_recorded(facts):
    scope = scope_with(RETAINED)
    assert run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION)) == []
    assert run(scope, lambda: revenue_service.fetch_verified_revenue_claim(TICKER)) is None
    assert facts == []
    [record] = scope.evidence_not_applicable            # both callers, one record
    assert (record['task'], record['reason']) == ('sec_metrics', 'no_xbrl_filings')
    assert record['evidence']['filings_listed'] == 9 and record['evidence']['xbrl_flags'] == 0
    assert (scope.fetches, scope.reuses, scope.failures) == (0, 0, 0)   # waiting is not a fetch or a reuse


def test_the_annual_eps_path_is_covered_too(facts):
    scope = scope_with(RETAINED)
    question = 'What was the annual diluted EPS for Plain Industries Corporation in fiscal 2025?'
    assert run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=question)) == []
    assert facts == []


def garbage_scope():
    scope = scope_with(RETAINED)
    scope._entries[URL]['data'] = 'not a response'
    return scope


@pytest.mark.parametrize('make_scope', [lambda: scope_with(operating()), garbage_scope],
                         ids=['operating issuer', 'unusable response'])
def test_when_absence_is_not_proven_the_request_is_made_exactly_as_before(facts, make_scope):
    scope = make_scope()
    assert run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION)) == []
    assert facts == [('metrics', CIK)]
    assert scope.evidence_not_applicable == []


def test_without_a_request_scope_nothing_changes(facts):
    assert sec_provider.facts_not_applicable(CIK) is None
    assert metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION) == []
    assert facts == [('metrics', CIK)]


def test_a_failed_or_missing_submissions_fetch_changes_nothing(facts, monkeypatch):
    monkeypatch.setattr(sec_provider, '_FACTS_EVIDENCE_WAIT_SECONDS', 0.05)
    failed = scope_with(RETAINED)
    failed._entries[URL]['data'] = None                       # the owner's fetch failed
    absent = sec_provider.SubmissionsRequestScope()           # no stage ever asked for it
    for scope in (failed, absent):
        assert run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION)) == []
    assert facts == [('metrics', CIK)] * 2


def test_the_stage_waits_for_a_fetch_still_in_flight(facts):
    scope = scope_with(RETAINED, done=False)
    threading.Timer(0.15, scope._entries[URL]['done'].set).start()
    assert run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION)) == []
    assert facts == [] and len(scope.evidence_not_applicable) == 1


def test_the_stage_never_fetches_submissions_itself(facts, monkeypatch):
    # A stage whose quota does not allow a submissions request must not make one.
    monkeypatch.setattr(sec_provider, '_FACTS_EVIDENCE_WAIT_SECONDS', 0.05)
    monkeypatch.setattr(sec_provider, '_fetch_json', lambda *a, **k: pytest.fail('submissions fetched by the facts stage'))
    scope = sec_provider.SubmissionsRequestScope()
    run(scope, lambda: metric_service.fetch_verified_metric_evidence(TICKER, question=QUESTION))
    assert scope.fetches == 0


def test_a_cik_the_name_resolution_did_not_return_is_never_judged(facts):
    scope = scope_with(RETAINED)
    other = '0001471265'                                       # the scope holds only this CIK's response
    assert run(scope, lambda: sec_provider.facts_not_applicable(other)) is None
    assert run(scope, lambda: sec_provider.facts_not_applicable('not-digits')) is None
    assert run(scope, lambda: sec_provider.facts_not_applicable(None)) is None


def thesis(text=''):
    return SimpleNamespace(direct_answer=text)


RECORDS = [{'task': 'sec_metrics', 'reason': 'no_xbrl_filings',
            'evidence': {'cik': CIK, 'filings_listed': 9, 'forms': ['424B3', 'EFFECT', 'F-6', 'F-6 POS', 'F-6EF'],
                         'xbrl_flags': 0, 'complete_listing': True, 'entity_type': 'other', 'sic': '8880'}}]


def test_the_answer_says_why_without_calling_it_a_failure_or_degrading_it():
    source = {'status': 'insufficient_claim_evidence', 'claims': [], 'unanswered_parts': ['operating risk']}
    subject = thesis('No source-bound operating-risk disclosure qualified for this broad question.')
    result = apply_evidence_not_applicable(subject, source, RECORDS)
    assert subject.direct_answer.startswith('No financial analysis is available for this registrant.')
    assert 'No source-bound operating-risk disclosure qualified' in subject.direct_answer
    assert 'degraded' not in result and 'evidence_gaps' not in result
    assert result['evidence_not_applicable'] == RECORDS and result['status'] == 'insufficient_claim_evidence'
    assert result['unanswered_parts'][0] == 'operating risk' and 'not applicable' in result['unanswered_parts'][-1]


def test_applying_it_twice_changes_nothing_further():
    subject = thesis('Body.')
    once = apply_evidence_not_applicable(subject, {'status': 'x', 'unanswered_parts': []}, RECORDS)
    text = subject.direct_answer
    twice = apply_evidence_not_applicable(subject, once, RECORDS)
    assert subject.direct_answer == text and twice['unanswered_parts'] == once['unanswered_parts']


def test_with_nothing_to_declare_or_no_source_answer_nothing_happens():
    source = {'status': 'partial'}
    subject = thesis('Body.')
    assert apply_evidence_not_applicable(subject, source, []) is source
    assert apply_evidence_not_applicable(subject, None, RECORDS) is None
    assert subject.direct_answer == 'Body.'
