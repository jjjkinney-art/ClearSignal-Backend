"""Invented approval records; fake sockets only, no authority for a real run."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import sqlite3
import ssl
from types import SimpleNamespace

import pytest

from validation.capture_budget import AttemptLedger, BudgetError, digest, validate_policy
from validation.ordinary_native_policy import execution_package, policy_for
from validation.ordinary_native_ledger import OrdinaryNativeLedger, OrdinaryNativeGate
from validation.ordinary_pilot_contract import CASES
from validation.pilot_policy import AUDITED_DEPENDENCIES
from validation.pilot_approved import ScopedBackend, ExchangeGate
from validation.ordinary_transport import OrdinaryHTTPTransport
from validation._pilot_wire_fixtures import SyntheticProxyBackend
from validation.pilot_live import TransportFailure

RECORDS = json.loads(Path(__file__).with_name('ordinary_pilot_cases.json').read_text())
CONFIG = {'documentation_reference': 'TEST-ONLY', 'verification_reference': 'TEST-ONLY',
          'substitution': 'explicit_environment_proxy', 'bearer_source': 'OPENAI_API_KEY',
          'sec_contact_source': 'SEC_USER_AGENT', 'proxy': 'http://proxy:8080',
          'proxy_selectors': ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'],
          'ca_selectors': ['SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE'],
          'ca_identity': {'path': '/tmp/TEST-ONLY-ca', 'sha256': 'c'*64}, 'contains_no_credentials': True}


def inputs(output):
    return dict(cases=deepcopy(RECORDS), code_binding={'revision': 'TEST-ONLY', 'source_sha256': 'a'*64},
                dependencies=dict(AUDITED_DEPENDENCIES), execution=deepcopy(CONFIG), output_dir=str(output),
                all_in_usd='0.00', retention_reference='TEST-ONLY-retention', pricing_review_reference='TEST-ONLY-pricing')


def approved_policy(output):
    values = inputs(output)
    approval = {'reference': 'TEST-ONLY-NOT-REAL-APPROVAL', 'run_id': 'TEST-ONLY-run',
                'manifest_sha256': digest(execution_package(**values)), 'output_dir': str(output),
                'all_in_usd': '0.00', 'execution_allowed': True, 'spending_authorized': True}
    values.pop('output_dir')
    return policy_for(**values, approval=approval)


def ledger(tmp_path):
    output = tmp_path / 'new-output'
    return OrdinaryNativeLedger(output/'ledger.sqlite', approved_policy(output), create=True)


PLAN = [('evidence.sec', 'sec/directory'), ('evidence.sec', 'sec/submissions'),
        ('evidence.sec_metrics', 'sec/directory'), ('evidence.sec_metrics', 'sec/facts'),
        ('evidence.thesis_disclosures', 'sec/submissions'), ('evidence.thesis_disclosures', 'sec/document'),
        ('evidence.filing_metrics', 'sec/submissions'), ('evidence.filing_metrics', 'sec/document')]


def reserve(book, case, stage, route):
    url = 'https://www.sec.gov/TEST-ONLY/' + route.split('/')[1]
    fingerprint = digest({'method': 'GET', 'url': url, 'stage': stage, 'route': route})
    attempt = book.reserve(case, route, stage=stage, input_bound=0, output_bound=0, request_sha256=fingerprint)
    book.claim_dispatch(attempt, case_run=case, route=route, request_sha256=fingerprint, input_bound=0, output_bound=0)
    book.claim_native_dispatch(attempt, case_run=case, route=route, request_sha256=fingerprint)
    return attempt, dict(case_run=case, route=route, request_sha256=fingerprint)


def complete(book, attempt, binding):
    document = binding['route'] == 'sec/document'
    book.complete_response(attempt, url='https://www.sec.gov/TEST-ONLY/' + binding['route'].split('/')[1],
        media_type='text/html' if document else 'application/json',
        body=b'<html>Invented</html>' if document else b'{}', forbidden_values=('TEST-ONLY-secret',))


def test_new_profile_is_fixed_and_cannot_reopen_or_reuse_output(tmp_path):
    book = ledger(tmp_path)
    assert validate_policy(book.policy) == 0
    assert book.policy['invoice_ceiling_verified'] is False
    with pytest.raises(BudgetError): OrdinaryNativeLedger(book.path, book.policy)
    with pytest.raises(FileExistsError): OrdinaryNativeLedger(book.path, book.policy, create=True)
    with pytest.raises(BudgetError): book.begin_case(CASES[1])
    case = book.begin_case(CASES[0])
    with pytest.raises(BudgetError): ExchangeGate(SimpleNamespace(ledger=book))
    with pytest.raises(BudgetError): book.reserve(case, 'model/valuation', stage='valuation', input_bound=0, output_bound=0, request_sha256='a'*64)


@pytest.mark.parametrize('field', ['execution', 'all_in_usd', 'retention_reference', 'pricing_review_reference', 'code_binding', 'cases'])
def test_changed_package_needs_new_approval(tmp_path, field):
    policy = approved_policy(tmp_path/'out')
    values = inputs(tmp_path/'out'); values.pop('output_dir')
    if field == 'execution': values[field]['verification_reference'] += '-changed'
    elif field == 'code_binding': values[field]['revision'] += '-changed'
    elif field == 'cases': values[field][0]['question'] += ' changed'
    elif field == 'all_in_usd': values[field] = '0.01'
    else: values[field] += '-changed'
    with pytest.raises(ValueError): policy_for(**values, approval=policy['approval'])


def test_mutated_or_legacy_profile_cannot_enter_new_native_ledger(tmp_path):
    policy = approved_policy(tmp_path/'out')
    policy['quotas']['per_case'][CASES[0]]['sec/document'] += 1
    with pytest.raises(BudgetError): OrdinaryNativeLedger(tmp_path/'out'/'ledger.sqlite', policy, create=True)
    assert not (tmp_path/'out').exists()
    policy['purpose'] = 'approved_six_case_pilot'
    with pytest.raises(BudgetError): OrdinaryNativeLedger(tmp_path/'out'/'ledger.sqlite', policy, create=True)
    with pytest.raises(BudgetError): OrdinaryNativeGate(SimpleNamespace(ledger=object()))


def test_concurrency_is_checked_at_wire_entry_and_duplicate_claims_never_replay(tmp_path):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    claims = [reserve(book, case, *scope) for scope in PLAN[:5]]
    for attempt, binding in claims[:4]: book.claim_wire_entry(attempt, **binding)
    with pytest.raises(BudgetError): book.claim_wire_entry(*claims[4][:1], **claims[4][1])
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_wire_entries').fetchone()[0] == 4
    with pytest.raises(BudgetError): book.claim_wire_entry(claims[0][0], **claims[0][1])


def test_actual_entry_rate_is_independent_of_earlier_reservation_rate(tmp_path, monkeypatch):
    import validation.ordinary_native_ledger as native
    now = [10_000_000_000]
    monkeypatch.setattr(native.time, 'monotonic_ns', lambda: now[0])
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    claims = [reserve(book, case, *scope) for scope in PLAN]
    now[0] += 1_100_000_000  # Earlier reservation rate window has elapsed.
    for attempt, binding in claims:
        book.claim_wire_entry(attempt, **binding)
        complete(book, attempt, binding)
    book.finish_case(case)
    case = book.begin_case(CASES[1])
    claims = [reserve(book, case, *scope) for scope in (PLAN[0], PLAN[1], PLAN[3])]
    for attempt, binding in claims[:2]:
        book.claim_wire_entry(attempt, **binding); complete(book, attempt, binding)
    with pytest.raises(BudgetError): book.claim_wire_entry(claims[2][0], **claims[2][1])
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_wire_entries').fetchone()[0] == 10


@pytest.mark.parametrize('scenario', ['happy', 'wire_connect_failure'])
def test_new_ledger_gate_and_owned_transport_share_the_same_immutable_attempt(tmp_path, monkeypatch, scenario):
    import validation.pilot_approved as approved
    monkeypatch.setattr(approved, 'verify_network_configuration', lambda config, tls=False: ssl.create_default_context() if tls else None)
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    class Owner:
        monitoring = True
        ledger = book
        used = set()
        def active(self): self.ledger.require_active()
        def once(self, scenarios):
            if scenario in scenarios and scenario not in self.used:
                self.used.add(scenario); return True
            return False
    owner = Owner()
    owner.scenario = scenario
    owner.case = {'identity': {'ticker': 'NPK', 'cik': '0000080172', 'company_name': 'Invented issuer'}}
    owner.identities = [owner.case['identity']]
    gate = OrdinaryNativeGate(owner)
    wire = OrdinaryHTTPTransport(gate=gate, execution=CONFIG, runtime={'sec_contact': 'Fixture contact@example.invalid'})
    wire._wire._pool._network_backend = ScopedBackend(SyntheticProxyBackend(owner), gate)
    url = 'https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json'
    stage, route = 'evidence.sec_metrics', 'sec/facts'
    fingerprint = digest({'method': 'GET', 'url': url, 'stage': stage, 'route': route})
    attempt = book.reserve(case, route, stage=stage, input_bound=0, output_bound=0, request_sha256=fingerprint)
    book.claim_dispatch(attempt, case_run=case, route=route, request_sha256=fingerprint, input_bound=0, output_bound=0)
    grant = gate.issue(attempt, fingerprint, route, case, stage)
    try:
        if scenario == 'happy':
            with gate.exchange(url, grant, fingerprint):
                media, body = wire.exchange('GET', url)
            assert media == 'application/json' and body
            book.complete_response(attempt, url=url, media_type=media, body=body,
                                   forbidden_values=('TEST-ONLY-secret',))
            with book.transaction() as db:
                assert db.execute('SELECT url,http_status,media_type,sha256,body FROM ordinary_responses').fetchone() == (
                    url, 200, media, hashlib.sha256(body).hexdigest(), body)
        else:
            with pytest.raises(TransportFailure):
                with gate.exchange(url, grant, fingerprint): wire.exchange('GET', url)
            book.halt_dispatch(attempt)
        assert gate.dispatched == 1
        with book.transaction() as db:
            assert db.execute('SELECT attempt_id FROM native_dispatches').fetchall() == [(attempt,)]
            assert db.execute('SELECT attempt_id FROM ordinary_wire_entries').fetchall() == [(attempt,)]
            assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='fixture_dispatches'").fetchone()
        with pytest.raises(BudgetError):
            with gate.exchange(url, grant, fingerprint): pass
    finally:
        gate.seal(); wire.close()


@pytest.mark.parametrize('fault', ['missing', 'changed_url', 'media', 'escaped_secret', 'size', 'late'])
def test_success_requires_complete_bound_screened_timely_original_body(tmp_path, monkeypatch, fault):
    import validation.ordinary_native_ledger as native
    now = [10_000_000_000]
    monkeypatch.setattr(native.time, 'monotonic_ns', lambda: now[0])
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    attempt, binding = reserve(book, case, 'evidence.sec_metrics', 'sec/facts')
    book.claim_wire_entry(attempt, **binding)
    args = dict(url='https://www.sec.gov/TEST-ONLY/facts', media_type='application/json',
                body=b'{}', forbidden_values=('TEST-ONLY-secret',))
    if fault == 'changed_url': args['url'] += '-changed'
    elif fault == 'media': args['media_type'] = 'text/html'
    elif fault == 'escaped_secret': args['body'] = b'{"value":"TEST-ONLY-\\u0073ecret"}'
    elif fault == 'size': args['body'] = b'x' * (16*1024*1024+1)
    elif fault == 'late': now[0] += 30_000_000_000
    with pytest.raises(BudgetError):
        if fault == 'missing': book.settle(attempt, input_tokens=0, output_tokens=0)
        else: book.complete_response(attempt, **args)
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_responses').fetchone()[0] == 0
        assert db.execute('SELECT status FROM attempts').fetchone()[0] == 'claimed'
    with pytest.raises(BudgetError): book.finish_case(case)


def test_worker_exchange_adapter_retains_before_return_and_rejects_cross_issuer(tmp_path, monkeypatch):
    from validation.ordinary_native_exchange import exchange_sec
    import validation.pilot_approved as approved
    monkeypatch.setattr(approved, 'verify_network_configuration', lambda config, tls=False: ssl.create_default_context() if tls else None)
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    owner = SimpleNamespace(ledger=book, monitoring=True, active=book.require_active,
        scenario='happy', once=lambda scenarios: False,
        case={'identity': {'ticker': 'NPK', 'cik': '0000080172', 'company_name': 'Invented'}},
        identities=[{'ticker': 'NPK', 'cik': '0000080172', 'company_name': 'Invented'}])
    owner.gate = OrdinaryNativeGate(owner)
    wire = OrdinaryHTTPTransport(gate=owner.gate, execution=CONFIG, runtime={'sec_contact': 'Fixture contact@example.invalid'})
    wire._wire._pool._network_backend = ScopedBackend(SyntheticProxyBackend(owner), owner.gate)
    try:
        media, body = exchange_sec(owner, wire, case_run=case, stage='evidence.sec_metrics', route='sec/facts',
            url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000080172.json', forbidden_values=('TEST-ONLY-secret',))
        with book.transaction() as db:
            assert db.execute('SELECT body FROM ordinary_responses').fetchone() == (body,)
            assert db.execute('SELECT status FROM attempts').fetchone() == ('settled',)
        with pytest.raises(BudgetError):
            exchange_sec(owner, wire, case_run=case, stage='evidence.sec', route='sec/submissions',
                url='https://data.sec.gov/submissions/CIK0001652044.json', forbidden_values=('TEST-ONLY-secret',))
        assert owner.gate.dispatched == 1
    finally:
        owner.gate.seal(); wire.close()
