"""Integrated ordinary boundary, in process: real gate, ledger and owned transport.

The network backend is the invented synthetic SEC backend; no socket, DNS or
credential is used. The approval is an invented TEST-ONLY record and grants
nothing. These checks cover admission, refusal and concurrency behaviour.
"""
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

import validation._ordinary_synthetic_sec as synthetic
from validation.capture_budget import BudgetError
from validation.ordinary_isolated_rehearsal import rehearsal_policy
from validation.ordinary_native_boundary import OrdinaryNativeBoundary
from validation.ordinary_native_ledger import OrdinaryNativeLedger, create_fresh_output
from validation.ordinary_pilot_contract import CASES, COHORT_FILE

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
