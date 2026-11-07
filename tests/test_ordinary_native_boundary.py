"""Integrated ordinary boundary, in process: real gate, ledger and owned transport.

The network backend is the invented synthetic SEC backend; no socket, DNS or
credential is used. The approval is an invented TEST-ONLY record and grants
nothing. These checks cover admission, refusal and concurrency behaviour.
"""
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

import validation._ordinary_synthetic_sec as synthetic
from _ordinary_cohort_expectations import attempt_reconciliation_problems
from validation.capture_budget import BudgetError, RateLimitDelay
from validation.ordinary_native_export import ExportRefused, export_packet
from validation.ordinary_isolated_rehearsal import rehearsal_policy
from validation.ordinary_native_boundary import OrdinaryNativeBoundary
from validation.ordinary_native_ledger import AbandonedExchange, OrdinaryNativeLedger, create_fresh_output
from validation.ordinary_pilot_contract import CASES, COHORT_FILE, quota_contract
from _ordinary_cohort_expectations import ORIGINAL_QUOTA_SHAPE

# The first case's issuer in the active cohort; its synthetic filings are generic.
FIRST = next(c for c in json.loads((Path(__file__).resolve().parents[1] / COHORT_FILE).read_text())
             if c['case_id'] == CASES[0])
FIRST_CIK = FIRST['expected_cik']
DIRECTORY = 'https://www.sec.gov/files/company_tickers.json'
SUBMISSIONS = f'https://data.sec.gov/submissions/CIK{FIRST_CIK}.json'
FACTS = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{FIRST_CIK}.json'
ANNUAL = (f'https://www.sec.gov/Archives/edgar/data/{int(FIRST_CIK)}/000095017026019334/'
          f'{FIRST["issuer_id"].lower()}-20251231.htm')
RUNTIME = {'OPENAI_API_KEY': 'TEST_ONLY_ORDINARY_PLACEHOLDER',
           'SEC_USER_AGENT': 'Ordinary rehearsal fixture rehearsal@example.invalid'}


def make_boundary(tmp_path, monkeypatch, backend=None):
    output = tmp_path / 'out'
    create_fresh_output(output)
    policy = rehearsal_policy(output)
    execution = policy['execution_configuration']
    monkeypatch.chdir(output)
    for name in ('FMP_API_KEY', 'FRED_API_KEY', 'NEWS_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HOME', str(output / 'isolated-home'))
    monkeypatch.setenv('CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED', 'false')
    for name, value in RUNTIME.items():
        monkeypatch.setenv(name, value)
    for name in execution['proxy_selectors']:
        monkeypatch.setenv(name, execution['proxy'])
    for name in execution['ca_selectors']:
        monkeypatch.setenv(name, execution['ca_identity']['path'])
    ledger = OrdinaryNativeLedger(output / 'ledger.sqlite', policy, create=True)
    return OrdinaryNativeBoundary(ledger, backend=backend or synthetic.OrdinarySyntheticSEC())


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    owner = make_boundary(tmp_path, monkeypatch)
    owner.begin(owner.cases[0])
    yield owner
    owner.close()


def fetch(owner, stage, url):
    token = owner.stage.set(stage)
    try:
        return owner.sec_exchange('GET', url, None)
    finally:
        owner.stage.reset(token)


def rows(owner, sql):
    with owner.ledger.transaction() as db:
        return db.execute(sql).fetchall()


# -- filing-document admission -----------------------------------------------------

def test_documents_are_admitted_only_from_this_case_and_stage_submissions(boundary):
    with pytest.raises(BudgetError):  # before any submissions response: not routable
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    assert rows(boundary, 'SELECT COUNT(*) FROM attempts') == [(0,)]
    assert boundary.refused_requests == [{'stage': 'evidence.thesis_disclosures', 'target': ANNUAL}]


@ORIGINAL_QUOTA_SHAPE
def test_multi_row_submissions_admit_exact_supported_documents_for_their_stage(tmp_path, monkeypatch):
    owner = make_boundary(tmp_path, monkeypatch)
    try:
        owner.begin(owner.cases[0])
        fetch(owner, 'evidence.sec', SUBMISSIONS)
        admitted = owner.admitted[(owner.case_run, 'evidence.sec')]
        recent = synthetic.submissions(int(FIRST_CIK))['filings']['recent']
        supported = [(f, a, d) for f, a, d in zip(recent['form'], recent['accessionNumber'], recent['primaryDocument'])
                     if f in {'10-K', '10-Q', '8-K'} and d.endswith('.htm')]
        assert len(admitted) == len(supported) == 6
        assert ANNUAL in admitted
        assert not any('form4' in url or 'def14a' in url or 'sc13ga' in url for url in admitted)
        # Admission in evidence.sec does not carry over to another stage.
        with pytest.raises(BudgetError):
            fetch(owner, 'evidence.thesis_disclosures', ANNUAL)
    finally:
        owner.close()


def test_document_follows_same_stage_submissions(boundary):
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    media, body = fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    assert media == 'text/html' and b'invented rehearsal' in body.lower()
    retained = rows(boundary, 'SELECT url,sha256 FROM ordinary_responses ORDER BY completed_ns')
    assert [url for url, _ in retained] == [SUBMISSIONS, ANNUAL]
    assert rows(boundary, "SELECT COUNT(*) FROM attempts WHERE status='settled'") == [(2,)]


@pytest.mark.parametrize('url', [
    'https://data.sec.gov/submissions/CIK0001652044.json',             # another issuer
    'https://data.sec.gov/api/xbrl/companyfacts/CIK0001652044.json',   # another issuer
    'https://www.sec.gov/Archives/edgar/data/80172/000095017026019334/other.htm',
    'https://financialmodelingprep.com/api/v3/profile/NPK',            # paid provider
    'https://efts.sec.gov/LATEST/search-index?q=NPK',                  # unreviewed SEC host
])
def test_unlisted_and_cross_issuer_requests_are_refused_before_any_attempt(boundary, url):
    with pytest.raises(BudgetError):
        fetch(boundary, 'evidence.sec', url)
    assert rows(boundary, 'SELECT COUNT(*) FROM attempts') == [(0,)]
    assert boundary.ledger.summary()['halted'] == 'invalid_request'


def test_threshold_case_cannot_fetch_documents(boundary):
    boundary.ledger.complete_case(boundary.case_run, {'company': FIRST['issuer_id'], 'answer': {}},
                                  forbidden_values=tuple(RUNTIME.values()))
    boundary.begin(boundary.cases[1])
    fetch(boundary, 'evidence.sec', SUBMISSIONS)
    with pytest.raises(BudgetError):  # threshold stage quotas admit no document
        fetch(boundary, 'evidence.sec', ANNUAL)
    assert boundary.ledger.summary()['halted']


# -- semantic refusals keep the first meaningful cause ------------------------------

@pytest.mark.parametrize('fault,code', [('accession', 'sec_accession_syntax'),
                                        ('shape', 'sec_recent_array_shape'),
                                        ('issuer', None)])
def test_semantic_refusals_record_the_first_cause_and_never_retain(boundary, monkeypatch, fault, code):
    original = synthetic.submissions

    def changed(cik):
        data = original(cik)
        recent = data['filings']['recent']
        if fault == 'accession': recent['accessionNumber'][0] = 'not-an-accession'
        elif fault == 'shape': recent['form'] = recent['form'][:-1]
        else: data['cik'] = '0001652044'
        return data
    monkeypatch.setattr(synthetic, 'submissions', changed)
    with pytest.raises(BudgetError):
        fetch(boundary, 'evidence.sec', SUBMISSIONS)
    summary = boundary.ledger.summary()
    if code:
        assert summary['first_sec_refusal']['code'] == code and summary['halted'] == 'invalid_response'
    else:
        assert summary['halted'] == 'identity_mismatch'
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_responses') == [(0,)]
    assert rows(boundary, "SELECT status FROM attempts") == [('claimed',)]  # consumed, unresolved
    failure, = rows(boundary, 'SELECT code FROM ordinary_exchange_failures')
    assert failure == ('sec_refusal' if code else 'identity_mismatch',)


@ORIGINAL_QUOTA_SHAPE
def test_submissions_drift_within_a_case_halts(boundary, monkeypatch):
    fetch(boundary, 'evidence.sec', SUBMISSIONS)
    original = synthetic._filings

    def drifted(cik):
        recent = original(cik)
        recent['primaryDocument'][0] = 'npk-20260630-amended.htm'
        return recent
    monkeypatch.setattr(synthetic, '_filings', drifted)
    with pytest.raises(BudgetError):
        fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    assert boundary.ledger.summary()['halted'] == 'configuration_drift'


# -- concurrency: wait for a slot, never a fifth request in flight -------------------

class HeldSEC(synthetic.OrdinarySyntheticSEC):
    """Holds every response until released; counts requests in flight."""
    def __init__(self):
        super().__init__()
        self.lock, self.active, self.peak, self.release = threading.Lock(), 0, 0, threading.Event()

    def connect_tcp(self, *args, **kwargs):
        proxy = super().connect_tcp(*args, **kwargs)
        tunnel, owner, read = proxy.tunnel, self, proxy.tunnel.read

        def held_read(max_bytes, timeout=None):
            if tunnel.response is None:
                with owner.lock:
                    owner.active += 1
                    owner.peak = max(owner.peak, owner.active)
                assert owner.release.wait(20)
                with owner.lock:
                    owner.active -= 1
            return read(max_bytes, timeout)
        tunnel.read = held_read
        return proxy


@ORIGINAL_QUOTA_SHAPE
def test_requests_wait_for_one_of_four_slots_instead_of_halting(tmp_path, monkeypatch):
    backend = HeldSEC()
    owner = make_boundary(tmp_path, monkeypatch, backend)
    try:
        owner.begin(owner.cases[0])
        plan = [('evidence.sec', DIRECTORY), ('evidence.sec', SUBMISSIONS),
                ('evidence.sec_metrics', DIRECTORY), ('evidence.sec_metrics', FACTS),
                ('evidence.thesis_disclosures', SUBMISSIONS), ('evidence.filing_metrics', SUBMISSIONS)]
        errors = []

        def run(stage, url):
            try:
                fetch(owner, stage, url)
            except BaseException as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=run, args=item) for item in plan]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 15
        while (backend.active < 4 or owner.slot_waits == 0) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert backend.active == 4 and owner.slot_waits > 0  # two requests are waiting, not halted
        backend.release.set()
        for thread in threads:
            thread.join(20)
        assert not errors and backend.peak == 4
        assert owner.ledger.summary()['halted'] is None
        assert rows(owner, "SELECT COUNT(*) FROM attempts WHERE status='settled'") == [(6,)]
    finally:
        backend.release.set()
        owner.close()


# -- abandonment between reservation and the wire -----------------------------------

@pytest.fixture
def stoppable(tmp_path, monkeypatch):
    backend = synthetic.OrdinarySyntheticSEC()
    owner = make_boundary(tmp_path, monkeypatch, backend)
    owner.begin(owner.cases[0])
    yield owner, backend
    owner.close()


def abandon_while_waiting_for_a_slot(owner):
    """Deterministic: every slot is held until the stage has been abandoned."""
    for _ in range(4):
        assert owner.slots.acquire(blocking=False)
    outcome = []

    def run():
        try:
            fetch(owner, 'evidence.sec', SUBMISSIONS)
            outcome.append('returned')
        except BaseException as exc:
            outcome.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 15
    while owner.slot_waits == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert owner.slot_waits > 0 and rows(owner, 'SELECT status FROM attempts') == [('pending',)]
    owner.abandon('evidence.sec')
    thread.join(15)
    for _ in range(4):
        owner.slots.release()
    assert type(outcome[0]) is AbandonedExchange
    return outcome[0]


def assert_never_dispatched(owner, backend, *, claimed, native):
    """One terminal attempt, nothing on the wire, and every resource given back."""
    assert rows(owner, 'SELECT route,status FROM attempts') == [('sec/submissions', 'abandoned')]
    assert rows(owner, 'SELECT code,detail FROM ordinary_exchange_failures') == [('abandoned', 'sec/submissions')]
    assert rows(owner, 'SELECT COUNT(*) FROM ordinary_wire_entries') == [(0,)]
    assert rows(owner, 'SELECT COUNT(*) FROM ordinary_responses') == [(0,)]
    assert rows(owner, 'SELECT COUNT(*) FROM sec_claims') == [(1 if claimed else 0,)]
    # The table appears with the first native dispatch.
    table = rows(owner, "SELECT COUNT(*) FROM sqlite_master WHERE name='native_dispatches'") == [(1,)]
    assert table is native and (not native or rows(owner, 'SELECT COUNT(*) FROM native_dispatches') == [(1,)])
    assert rows(owner, 'SELECT stage FROM ordinary_stage_abandonments') == [('evidence.sec',)]
    assert backend.requests == [] and backend.connects == 0
    assert owner.inflight == 0 and owner.slots._value == 4  # concurrency and slots released
    assert owner.gate.dispatched == 0 and owner.ledger.summary()['halted'] is None
    assert owner.gate.grants == {} and owner.gate.open_states == {}


def test_an_abandonment_before_reservation_charges_nothing(stoppable):
    owner, backend = stoppable
    owner.abandon('evidence.sec')
    with pytest.raises(AbandonedExchange):
        fetch(owner, 'evidence.sec', SUBMISSIONS)
    assert rows(owner, 'SELECT COUNT(*) FROM attempts') == [(0,)] and backend.requests == []


def test_an_abandonment_waiting_for_a_slot_never_dispatches(stoppable):
    owner, backend = stoppable
    abandon_while_waiting_for_a_slot(owner)
    assert_never_dispatched(owner, backend, claimed=False, native=False)
    # Other stages carry on: the run is degraded, not halted.
    fetch(owner, 'evidence.sec_metrics', FACTS)
    assert len(backend.requests) == 1 and owner.ledger.summary()['halted'] is None


def test_an_abandonment_during_claim_pacing_never_dispatches(stoppable, monkeypatch):
    owner, backend = stoppable

    def paced(*args, **kwargs):
        owner.abandon('evidence.sec')
        raise RateLimitDelay(0.01)
    monkeypatch.setattr(owner.ledger, 'claim_dispatch', paced)
    with pytest.raises(AbandonedExchange):
        fetch(owner, 'evidence.sec', SUBMISSIONS)
    assert_never_dispatched(owner, backend, claimed=False, native=False)


def test_an_abandonment_after_claim_never_reaches_the_wire(stoppable, monkeypatch):
    owner, backend = stoppable
    claim = owner.ledger.claim_dispatch

    def claimed_then_abandoned(*args, **kwargs):
        result = claim(*args, **kwargs)
        owner.abandon('evidence.sec')
        return result
    monkeypatch.setattr(owner.ledger, 'claim_dispatch', claimed_then_abandoned)
    with pytest.raises(AbandonedExchange):
        fetch(owner, 'evidence.sec', SUBMISSIONS)
    assert_never_dispatched(owner, backend, claimed=True, native=True)


def test_an_abandoned_reservation_stays_charged_against_every_quota(stoppable):
    owner, _ = stoppable
    abandon_while_waiting_for_a_slot(owner)
    limit = quota_contract()['per_case'][CASES[0]]['sec/submissions']
    digest = '0' * 64
    for stage in ('evidence.filing_metrics', 'evidence.thesis_disclosures')[:limit - 1]:
        owner.ledger.reserve(owner.case_run, 'sec/submissions', stage=stage, input_bound=0, output_bound=0,
                             request_sha256=digest)
    with pytest.raises(BudgetError, match='quota'):  # the abandoned one still counts
        owner.ledger.reserve(owner.case_run, 'sec/submissions', stage='evidence.filing_metrics', input_bound=0,
                             output_bound=0, request_sha256=digest)


def _export(owner, path=None):
    return export_packet(path or owner.ledger.path, owner.ledger.policy,
                         forbidden_values=tuple(RUNTIME.values()), synthetic=True)


def test_a_never_dispatched_attempt_reconciles_through_export(stoppable):
    owner, backend = stoppable
    abandon_while_waiting_for_a_slot(owner)
    fetch(owner, 'evidence.sec_metrics', FACTS)
    owner.complete_case({'company': FIRST['issuer_id'], 'answer': {}})
    packet = _export(owner)
    assert (packet['attempt_count'], packet['wire_entries'], len(backend.requests)) == (2, 1, 1)
    never = [a for a in packet['attempts'] if a['wire_entered_offset_ms'] is None]
    assert [(a['stage'], a['route'], a['status']) for a in never] == [('evidence.sec', 'sec/submissions', 'abandoned')]
    assert never[0]['failure'] == {'code': 'abandoned', 'detail': 'sec/submissions'} and never[0]['response'] is None
    assert attempt_reconciliation_problems(packet, quota_contract()) == []
    assert packet['cases'][0]['status'] == 'answered_degraded_unadjudicated'
    assert packet['abandoned_stages'] == [{'case_id': CASES[0], 'stage': 'evidence.sec'}]


@pytest.mark.parametrize('sql', [
    "UPDATE attempts SET status='claimed' WHERE status='abandoned'",
    "DELETE FROM ordinary_exchange_failures",
    "INSERT INTO ordinary_wire_entries SELECT id, 1 FROM attempts WHERE status='abandoned'",
    "INSERT INTO ordinary_responses SELECT id, 'https://www.sec.gov/x', 200, 'text/html', '0', x'00', 1 FROM attempts WHERE status='abandoned'",
], ids=['status_reopened', 'no_terminal_record', 'invented_wire_entry', 'invented_response'])
def test_export_refuses_an_inconsistent_never_dispatched_attempt(stoppable, tmp_path, sql):
    owner, _ = stoppable
    abandon_while_waiting_for_a_slot(owner)
    owner.complete_case({'company': FIRST['issuer_id'], 'answer': {}})
    assert _export(owner)['attempt_count'] == 1
    copy = tmp_path / 'tampered.sqlite'
    shutil.copyfile(owner.ledger.path, copy)
    with sqlite3.connect(copy) as db:
        db.execute(sql)
    with pytest.raises((ExportRefused, TypeError)):
        _export(owner, copy)


def test_reconciliation_rejects_attempts_that_do_not_account_for_themselves():
    limits = quota_contract()
    good = {'case_id': CASES[0], 'stage': 'evidence.sec', 'route': 'sec/submissions', 'status': 'abandoned',
            'wire_entered_offset_ms': None, 'response': None, 'failure': {'code': 'abandoned', 'detail': 'sec/submissions'}}
    packet = {'attempts': [good], 'attempt_count': 1, 'wire_entries': 0,
              'abandoned_stages': [{'case_id': CASES[0], 'stage': 'evidence.sec'}]}
    assert attempt_reconciliation_problems(packet, limits) == []
    for change, expected in [
            ({'wire_entries': 1}, 'wire entries'), ({'attempt_count': 2}, 'attempt count'),
            ({'abandoned_stages': []}, 'without its stage record'),
            ({'attempts': [{**good, 'status': 'claimed'}]}, 'without an abandoned status'),
            ({'attempts': [{**good, 'failure': None}]}, 'terminal record'),
            ({'attempts': [{**good, 'response': {}}]}, 'has a response'),
            ({'attempts': [{**good, 'stage': 'evidence.sec_metrics'}], 'abandoned_stages': [
                {'case_id': CASES[0], 'stage': 'evidence.sec_metrics'}]}, 'stage limit'),
            ({'attempts': [good] * 99, 'attempt_count': 99}, 'run limit')]:
        assert any(expected in problem for problem in attempt_reconciliation_problems({**packet, **change}, limits)), expected


# -- zero model and paid-provider calls ----------------------------------------------

def test_any_model_request_halts(boundary):
    request = httpx.Request('POST', 'https://api.openai.com/v1/chat/completions', content=b'{}')
    with pytest.raises(BudgetError):
        boundary.model_request(request)
    assert boundary.refused_model_requests == 1
    assert boundary.ledger.summary()['halted'] == 'invalid_request'
    assert rows(boundary, 'SELECT COUNT(*) FROM attempts') == [(0,)]


@pytest.mark.parametrize('name', ['FMP_API_KEY', 'FRED_API_KEY', 'NEWS_API_KEY'])
def test_a_paid_provider_key_in_the_environment_halts(boundary, monkeypatch, name):
    monkeypatch.setenv(name, 'invented-paid-provider-key')
    with pytest.raises(BudgetError):
        boundary.active()
    assert boundary.ledger.summary()['halted'] == 'configuration_drift'


@pytest.mark.parametrize('drift', ['filing_fallback', 'auth_disabled', 'auth_missing'])
def test_settings_drift_halts(boundary, drift):
    values = dict(decision_monitoring_inputs_enabled=True, decision_monitoring_filing_fallback_enabled=False,
                  auth_enabled=True, fmp_api_key='', fred_api_key='', sec_user_agent=boundary.contact)
    if drift == 'filing_fallback': values['decision_monitoring_filing_fallback_enabled'] = True
    elif drift == 'auth_disabled': values['auth_enabled'] = False  # would write global legacy history
    else: values.pop('auth_enabled')
    boundary.settings = SimpleNamespace(**values)
    with pytest.raises(BudgetError):
        boundary.active()
    assert boundary.ledger.summary()['halted'] == 'configuration_drift'


# -- the owned transport itself ------------------------------------------------------

@pytest.mark.parametrize('method,url,body', [
    ('POST', 'https://api.openai.com/v1/chat/completions', b'{}'),
    ('POST', SUBMISSIONS, b''),
    ('GET', SUBMISSIONS.replace('https', 'http'), b''),
    ('GET', SUBMISSIONS.replace('data.sec.gov', 'data.sec.gov:443'), b''),
    ('GET', SUBMISSIONS + '?x=1', b''),
    ('GET', SUBMISSIONS.replace('https://', 'https://user@'), b''),
    ('GET', SUBMISSIONS, b'body'),
])
def test_transport_refuses_unapproved_request_forms_before_dispatch(boundary, method, url, body):
    with pytest.raises(BudgetError):
        boundary.wire.exchange(method, url, body=body)
    assert boundary.gate.dispatched == 0
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_wire_entries') == [(0,)]


def test_transport_never_grants_the_historic_reviewed_envelope(boundary):
    from validation.pilot_live import ReviewedDocumentEnvelope
    envelope = ReviewedDocumentEnvelope(FIRST_CIK, ANNUAL, '10-K', '2026-02-24', 'invented')
    assert boundary.wire.authorize_reviewed_document(FIRST_CIK, ANNUAL, '10-K', '2026-02-24') is None
    assert boundary.wire.response_limit('GET', ANNUAL, None) == 16 * 1024 * 1024
    with pytest.raises(BudgetError):
        boundary.wire.response_limit('GET', ANNUAL, envelope)


def test_dispatch_claim_pacing_waits_rather_than_halting(boundary):
    import time as clock
    now = clock.monotonic_ns()
    with boundary.ledger.transaction() as db:  # ten SEC claims in the last ~0.2 seconds
        for i in range(10):
            db.execute('INSERT INTO sec_claims VALUES (?,?)', (f'synthetic-{i}', now - 20_000_000 * i))
    started = clock.monotonic()
    fetch(boundary, 'evidence.sec', DIRECTORY)
    assert clock.monotonic() - started >= 0.5  # waited for the window to open
    assert boundary.claim_pacing_waits > 0 and boundary.ledger.summary()['halted'] is None


@pytest.mark.parametrize('url', [SUBMISSIONS, FACTS])
def test_routing_stage_admits_only_the_directory(boundary, url):
    fetch(boundary, 'routing', DIRECTORY)  # identity resolution
    with pytest.raises(BudgetError):
        fetch(boundary, 'routing', url)
    assert boundary.ledger.summary()['halted']
    assert rows(boundary, "SELECT COUNT(*) FROM attempts WHERE status='settled'") == [(1,)]


# -- oversized filing documents ------------------------------------------------------
OBSERVED = {'limit_bytes': 16 * 1024 * 1024, 'declared_bytes': None, 'bytes_read': 16 * 1024 * 1024 + 1}


def oversized(monkeypatch, owner, observation=OBSERVED):
    from validation.pilot_live import TransportFailure

    def exchange(method, url, **kwargs):
        owner.gate.validate_request(method, url, b'')
        owner.gate.record_dispatch()
        error = TransportFailure('response_size')
        error.size_observation = observation
        raise error
    monkeypatch.setattr(owner.wire, 'exchange', exchange)


def test_without_the_profile_an_oversized_filing_keeps_its_historic_halt(boundary, monkeypatch):
    boundary.threshold_filing = False
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    oversized(monkeypatch, boundary)
    with pytest.raises(BudgetError, match='ordinary SEC exchange refused'):
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    assert rows(boundary, 'SELECT halted FROM policy') == [('post_claim_failure',)]
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_size_rejections') == [(0,)]


def test_a_profile_rejection_is_recorded_raised_to_the_application_and_charged(boundary, monkeypatch):
    from app.services.public_document_ingestion import PublicDocumentError
    boundary.threshold_filing = True
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    oversized(monkeypatch, boundary)
    with pytest.raises(PublicDocumentError) as caught:
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    assert caught.value.size_limit_bytes == OBSERVED['limit_bytes']
    assert rows(boundary, 'SELECT halted FROM policy') == [(None,)]
    assert rows(boundary, "SELECT route,status FROM attempts WHERE status='size_rejected'") == [('sec/document', 'size_rejected')]
    assert rows(boundary, 'SELECT stage,url,bytes_read FROM ordinary_size_rejections') == [
        ('evidence.thesis_disclosures', ANNUAL, OBSERVED['bytes_read'])]
    assert rows(boundary, "SELECT code,detail FROM ordinary_exchange_failures") == [('size_rejected', 'response_size')]
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_responses WHERE url=?'.replace('?', repr(ANNUAL))) == [(0,)]
    assert rows(boundary, 'SELECT COUNT(*) FROM first_transport_failure') == [(0,)]


@pytest.mark.parametrize('observation', [None, {**OBSERVED, 'limit_bytes': 8}, {**OBSERVED, 'bytes_read': 8},
                                         {**OBSERVED, 'bytes_read': 64 * 1024 * 1024}],
                         ids=['unclean_close', 'other_limit', 'under_limit', 'over_read'])
def test_a_rejection_that_does_not_reconcile_halts(boundary, monkeypatch, observation):
    boundary.threshold_filing = True
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    oversized(monkeypatch, boundary, observation)
    with pytest.raises(BudgetError, match='ordinary SEC exchange refused'):
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    assert rows(boundary, 'SELECT halted FROM policy') != [(None,)]
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_size_rejections') == [(0,)]


def test_oversized_json_under_the_profile_still_halts(boundary, monkeypatch):
    boundary.threshold_filing = True
    oversized(monkeypatch, boundary)
    with pytest.raises(BudgetError, match='ordinary SEC exchange refused'):
        fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    assert rows(boundary, 'SELECT halted FROM policy') == [('post_claim_failure',)]


def test_an_answer_silent_about_its_rejected_filing_is_not_retained(boundary, monkeypatch):
    boundary.threshold_filing = True
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    oversized(monkeypatch, boundary)
    with pytest.raises(Exception):
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    company = boundary.case['case_id'].split(':')[0]
    with pytest.raises(BudgetError):
        boundary.complete_case({'company': company, 'answer': {'source_answer': {'status': 'partial'}}})
    assert rows(boundary, 'SELECT halted FROM policy') == [('invalid_response',)]
    assert rows(boundary, 'SELECT COUNT(*) FROM ordinary_answers') == [(0,)]


def test_a_declared_rejection_finishes_the_case_with_no_halt(boundary, monkeypatch):
    boundary.threshold_filing = True
    fetch(boundary, 'evidence.thesis_disclosures', SUBMISSIONS)
    oversized(monkeypatch, boundary)
    with pytest.raises(Exception):
        fetch(boundary, 'evidence.thesis_disclosures', ANNUAL)
    company = boundary.case['case_id'].split(':')[0]
    boundary.complete_case({'company': company, 'answer': {'source_answer': {
        'status': 'partial', 'degraded': True,
        'evidence_gaps': [{'source': 'the latest SEC filing', 'task': 'thesis_disclosures', 'reason': 'too_large'}]}}})
    assert rows(boundary, 'SELECT halted FROM policy') == [(None,)]
    assert rows(boundary, "SELECT status FROM cases") == [('complete',)]
    assert rows(boundary, 'SELECT stage FROM ordinary_stage_abandonments') == [('evidence.thesis_disclosures',)]
