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
from validation.ordinary_native_ledger import OrdinaryNativeLedger, OrdinaryNativeGate, create_fresh_output
from validation.ordinary_pilot_contract import CASES, COHORT_FILE
from validation.pilot_policy import AUDITED_DEPENDENCIES
from validation.pilot_approved import ScopedBackend, ExchangeGate
from validation.ordinary_transport import OrdinaryHTTPTransport
from validation._pilot_wire_fixtures import SyntheticProxyBackend
from validation.pilot_live import TransportFailure

RECORDS = json.loads((Path(__file__).resolve().parents[1] / COHORT_FILE).read_text())
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
    policy = approved_policy(output)
    create_fresh_output(output)  # the launcher owns creation of the approved directory
    return OrdinaryNativeLedger(output/'ledger.sqlite', policy, create=True)


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
    # Reuse is refused: the directory is no longer the launcher's fresh state.
    with pytest.raises(BudgetError): OrdinaryNativeLedger(book.path, book.policy, create=True)
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
    book.complete_case(case, {'company': CASES[0].split(':')[0], 'answer': {}}, forbidden_values=('TEST-ONLY-secret',))
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


# -- launcher-owned fresh output --------------------------------------------------

@pytest.mark.parametrize('state', ['missing', 'extra_file', 'group_readable', 'home_not_empty', 'home_missing'])
def test_ledger_accepts_only_the_launcher_created_fresh_directory(tmp_path, state):
    output = tmp_path / 'out'
    policy = approved_policy(output)
    if state != 'missing':
        create_fresh_output(output)
    if state == 'extra_file': (output / 'resumed-state.sqlite').write_bytes(b'')
    elif state == 'group_readable': output.chmod(0o750)
    elif state == 'home_not_empty': (output / 'isolated-home' / '.netrc').write_text('invented')
    elif state == 'home_missing': (output / 'isolated-home').rmdir()
    with pytest.raises(BudgetError):
        OrdinaryNativeLedger(output / 'ledger.sqlite', policy, create=True)
    assert not (output / 'ledger.sqlite').exists()
    if state == 'missing':
        assert not output.exists()  # the ledger never creates the approved directory


def test_launcher_inputs_are_the_only_permitted_extra_entry(tmp_path):
    output = tmp_path / 'out'
    policy = approved_policy(output)
    create_fresh_output(output)
    (output / 'request.json').write_text('{}')
    OrdinaryNativeLedger(output / 'ledger.sqlite', policy, create=True)
    with pytest.raises(FileExistsError):
        create_fresh_output(output)


# -- pacing versus halting at wire entry --------------------------------------------

def test_rate_excess_paces_without_halting(tmp_path, monkeypatch):
    import validation.ordinary_native_ledger as native
    from validation.capture_budget import RateLimitDelay
    now = [10_000_000_000]
    monkeypatch.setattr(native.time, 'monotonic_ns', lambda: now[0])
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    attempt, binding = reserve(book, case, *PLAN[0])
    with book.transaction() as db:  # ten entries already in this one-second window
        for i in range(10):
            db.execute('INSERT INTO ordinary_wire_entries VALUES (?,?)', (f'synthetic-{i}', now[0] - 100_000_000 * i))
    with pytest.raises(RateLimitDelay) as delay:
        book.claim_wire_entry(attempt, **binding)
    assert 0 < delay.value.seconds <= 1
    assert book.summary()['halted'] is None  # paced, not halted, and not consumed
    now[0] += 1_000_000_000
    book.claim_wire_entry(attempt, **binding)
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_wire_entries WHERE attempt_id=?', (attempt,)).fetchone() == (1,)


def test_a_fifth_concurrent_wire_entry_halts(tmp_path):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    claims = [reserve(book, case, *scope) for scope in PLAN[:5]]
    for attempt, binding in claims[:4]:
        book.claim_wire_entry(attempt, **binding)  # four in flight, none completed
    with pytest.raises(BudgetError):
        book.claim_wire_entry(claims[4][0], **claims[4][1])
    assert book.summary()['halted'] == 'invalid_request'


# -- screening that does not require UTF-8 -----------------------------------------

@pytest.mark.parametrize('body,admitted', [
    (b'<html>Caf\xe9 \x92quoted\x92 Windows-1252 bytes</html>', True),
    (b'<html>TEST-ONLY-&#115;ecret</html>', False),
    (b'<html>TEST-ONLY-secret</html>', False),
])
def test_document_screening_tolerates_non_utf8_but_refuses_encoded_secrets(tmp_path, body, admitted):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    attempt, binding = reserve(book, case, 'evidence.thesis_disclosures', 'sec/document')
    book.claim_wire_entry(attempt, **binding)
    args = dict(url='https://www.sec.gov/TEST-ONLY/document', media_type='text/html',
                body=body, forbidden_values=('TEST-ONLY-secret',))
    if admitted:
        book.complete_response(attempt, **args)
        with book.transaction() as db:
            assert db.execute('SELECT body FROM ordinary_responses').fetchone() == (body,)
    else:
        with pytest.raises(BudgetError): book.complete_response(attempt, **args)
        assert book.summary()['halted'] == 'invalid_response'


# -- answers finish cases atomically -----------------------------------------------

def finish_all(book, case):
    for attempt, binding in [reserve(book, case, *scope) for scope in PLAN]:
        book.claim_wire_entry(attempt, **binding); complete(book, attempt, binding)


@pytest.mark.parametrize('fault', ['none', 'unsettled', 'issuer', 'secret', 'late', 'twice', 'oversize'])
def test_case_completes_only_with_its_own_screened_timely_answer(tmp_path, monkeypatch, fault):
    import validation.ordinary_native_ledger as native
    now = [10_000_000_000]
    monkeypatch.setattr(native.time, 'monotonic_ns', lambda: now[0])
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    if fault == 'unsettled':
        reserve(book, case, 'evidence.sec', 'sec/directory')
    else:
        for attempt, binding in [reserve(book, case, *scope) for scope in PLAN]:
            now[0] += 150_000_000
            book.claim_wire_entry(attempt, **binding); complete(book, attempt, binding)
    answer = {'company': CASES[0].split(':')[0], 'answer': {'text': 'Invented'}}
    if fault == 'issuer': answer['company'] = 'GOOGL'
    elif fault == 'secret': answer['answer']['text'] = 'TEST-ONLY-secret'
    elif fault == 'late': now[0] += 30_000_000_000
    elif fault == 'oversize': answer['answer']['text'] = 'x' * (4 * 1024 * 1024)
    if fault in ('none', 'twice'):
        book.complete_case(case, answer, forbidden_values=('TEST-ONLY-secret',))
        with book.transaction() as db:
            assert db.execute('SELECT status FROM cases WHERE id=?', (case,)).fetchone() == ('complete',)
            assert db.execute('SELECT case_id FROM ordinary_answers').fetchall() == [(CASES[0],)]
        if fault == 'twice':
            with pytest.raises(BudgetError):
                book.complete_case(case, answer, forbidden_values=('TEST-ONLY-secret',))
            assert book.summary()['halted']
        return
    with pytest.raises(BudgetError):
        book.complete_case(case, answer, forbidden_values=('TEST-ONLY-secret',))
    assert book.summary()['halted']
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_answers').fetchone() == (0,)


def test_no_late_work_after_a_case_is_complete(tmp_path):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    finish_all(book, case)
    book.complete_case(case, {'company': CASES[0].split(':')[0], 'answer': {}}, forbidden_values=('TEST-ONLY-secret',))
    with pytest.raises(BudgetError):
        reserve(book, case, 'evidence.sec', 'sec/directory')


def test_failure_records_use_fixed_codes_only(tmp_path):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    attempt, _ = reserve(book, case, 'evidence.sec', 'sec/directory')
    with pytest.raises(BudgetError):
        book.record_exchange_failure(attempt, 'transport', 'contains spaces and TEST-ONLY-secret')
    with pytest.raises(BudgetError):
        book.record_exchange_failure(attempt, 'invented_code', 'read_error')
    book.record_exchange_failure(attempt, 'transport', 'read_error')
    book.record_exchange_failure(attempt, 'interrupted', 'sec/directory')  # first record kept
    with book.transaction() as db:
        assert db.execute('SELECT code,detail FROM ordinary_exchange_failures').fetchall() == [('transport', 'read_error')]
    assert book.summary()['halted'] == 'post_claim_failure'


def test_an_unresolved_identity_answer_is_retained_but_another_issuer_halts(tmp_path):
    book = ledger(tmp_path); case = book.begin_case(CASES[0])
    book.complete_case(case, {'company': '', 'answer': {'text': 'Could not verify the company.'}},
                       forbidden_values=('TEST-ONLY-secret',))
    with book.transaction() as db:
        assert db.execute('SELECT case_id FROM ordinary_answers').fetchall() == [(CASES[0],)]
    case = book.begin_case(CASES[1])
    with pytest.raises(BudgetError):
        book.complete_case(case, {'company': 'GOOGL', 'answer': {}}, forbidden_values=('TEST-ONLY-secret',))
    assert book.summary()['halted'] == 'invalid_response'
