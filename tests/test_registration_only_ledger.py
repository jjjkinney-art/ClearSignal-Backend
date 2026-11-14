"""The ledger re-proves a declared absence of company facts from the case's own retained evidence.

Invented ledgers; no network. The retained submissions body is a trimmed copy of the response
Run 10 kept for a depositary-receipt registration entity.
"""
import copy
import json
from pathlib import Path

import pytest

from validation.capture_budget import BudgetError, digest
from validation.ordinary_pilot_contract import CASES, COHORT
from validation.pilot_live import TransportFailure
from test_ordinary_native_ledger import RECORDS, ledger

pytestmark = pytest.mark.skipif(COHORT != 'run10', reason='uses the cohort 5 case order')

RETAINED = json.loads((Path(__file__).parent / 'data' / 'sec_submissions_registration_only_retained_run10.json').read_text())
FORBIDDEN = ('TEST-ONLY-secret',)
VBREY, VBREY_THRESHOLD, GALT = CASES[2], CASES[3], CASES[4]
CIK = next(r['expected_cik'] for r in RECORDS if r['case_id'] == VBREY)
EVIDENCE = {'cik': CIK, 'filings_listed': 9, 'forms': ['424B3', 'EFFECT', 'F-6', 'F-6 POS', 'F-6EF'], 'xbrl_flags': 0,
            'complete_listing': True, 'entity_type': 'other', 'sic': '8880'}
RECORD = {'task': 'sec_metrics', 'reason': 'no_xbrl_filings', 'evidence': EVIDENCE}


def declaration(records=None, company='VBREY'):
    return {'company': company, 'answer': {'source_answer': {
        'status': 'insufficient_claim_evidence', 'claims': [],
        'evidence_not_applicable': [RECORD] if records is None else records}}}


def retain(book, case, route, url, body, stage):
    fingerprint = digest({'method': 'GET', 'url': url, 'stage': stage, 'route': route})
    attempt = book.reserve(case, route, stage=stage, input_bound=0, output_bound=0, request_sha256=fingerprint)
    binding = dict(case_run=case, route=route, request_sha256=fingerprint)
    book.claim_dispatch(attempt, **binding, input_bound=0, output_bound=0)
    book.claim_native_dispatch(attempt, **binding)
    book.claim_wire_entry(attempt, **binding)
    book.complete_response(attempt, url=url, media_type='application/json', body=json.dumps(body).encode(),
                           forbidden_values=FORBIDDEN)
    return attempt


def submissions_url(cik=CIK):
    return f'https://data.sec.gov/submissions/CIK{cik}.json'


def book_at_vbrey(tmp_path):
    """A ledger whose first two cases are done, with the third (VBREY, position 3) begun."""
    book = ledger(tmp_path)
    for case in CASES[:2]:
        book.complete_case(book.begin_case(case), {'company': '', 'answer': {}}, forbidden_values=FORBIDDEN)
    return book, book.begin_case(VBREY)


def operating_body():
    body = copy.deepcopy(RETAINED)
    body['entityType'], body['sic'] = 'operating', '6021'
    body['filings']['recent']['isXBRL'][0] = 1
    return body


def test_a_proven_declaration_completes_the_case_and_later_cases_run(tmp_path):
    book, run = book_at_vbrey(tmp_path)
    retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec')
    book.complete_case(run, declaration(), forbidden_values=FORBIDDEN)
    second = book.begin_case(VBREY_THRESHOLD)
    retain(book, second, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec')
    book.complete_case(second, declaration(), forbidden_values=FORBIDDEN)
    # The run is not halted: the next issuer's case begins and completes normally.
    book.complete_case(book.begin_case(GALT), {'company': 'GALT', 'answer': {}}, forbidden_values=FORBIDDEN)
    assert book.summary()['halted'] is None
    with book.transaction() as db:
        assert [r[0] for r in db.execute('SELECT case_id FROM ordinary_answers ORDER BY rowid')] == list(CASES[:5])
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE route='sec/facts'").fetchone() == (0,)


def _other_cik_response(book, run):
    other = '0001471265'
    retain(book, run, 'sec/submissions', submissions_url(other), {**RETAINED, 'cik': other}, 'evidence.sec')


UNSUPPORTED = {
    'operating evidence': (lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), operating_body(), 'evidence.sec'),
                           declaration()),
    'no submissions response at all': (lambda book, run: None, declaration()),
    'another issuer\'s response retained': (_other_cik_response, declaration()),
    'a body naming another CIK at the right URL': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), {**RETAINED, 'cik': '0001471265'}, 'evidence.sec'),
        declaration()),
    'a facts request was made': (
        lambda book, run: (retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
                           retain(book, run, 'sec/facts', f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json', {}, 'evidence.sec_metrics')),
        declaration()),
    'evidence that differs from the retained response': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
        declaration([{**RECORD, 'evidence': {**EVIDENCE, 'filings_listed': 8}}])),
    'an empty declaration list': (lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
                                  declaration([])),
    'a declaration that is not a list': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
        declaration('yes')),
    'a record with another reason': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
        declaration([{**RECORD, 'reason': 'ticker_is_an_adr'}])),
    'a record with another task': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
        declaration([{**RECORD, 'task': 'filing_metrics'}])),
    'a record with an extra field': (
        lambda book, run: retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec'),
        declaration([{**RECORD, 'note': 'because of the suffix'}])),
}


@pytest.mark.parametrize('label', sorted(UNSUPPORTED))
def test_a_declaration_the_run_cannot_prove_halts(tmp_path, label):
    book, run = book_at_vbrey(tmp_path)
    prepare, payload = UNSUPPORTED[label]
    prepare(book, run)
    with pytest.raises(BudgetError):
        book.complete_case(run, payload, forbidden_values=FORBIDDEN)
    assert book.summary()['halted'] == 'invalid_response'
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_answers WHERE case_id=?', (VBREY,)).fetchone() == (0,)


def test_a_proven_declaration_does_not_excuse_a_different_issuer(tmp_path):
    book, run = book_at_vbrey(tmp_path)
    retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec')
    with pytest.raises(BudgetError):
        book.complete_case(run, declaration(company='GOOGL'), forbidden_values=FORBIDDEN)
    assert book.summary()['halted'] == 'invalid_response'


@pytest.mark.parametrize('detail', ['http_client_error_404', 'http_client_error_400', 'http_auth_403', 'http_auth_401',
                                    'http_throttled_429', 'http_server_error_500', 'http_redirect_301', 'read_error',
                                    'response_json', 'http_client_error'])
def test_a_failed_facts_exchange_still_halts_and_a_declaration_cannot_rescue_it(tmp_path, detail):
    book, run = book_at_vbrey(tmp_path)
    retain(book, run, 'sec/submissions', submissions_url(), RETAINED, 'evidence.sec')   # absence IS provable ...
    fingerprint = digest({'method': 'GET', 'url': f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json',
                          'stage': 'evidence.sec_metrics', 'route': 'sec/facts'})
    attempt = book.reserve(run, 'sec/facts', stage='evidence.sec_metrics', input_bound=0, output_bound=0,
                           request_sha256=fingerprint)
    # ... but a facts request was issued and failed: that is a real failure whatever the filing list says.
    book.record_exchange_failure(attempt, 'transport', detail)
    assert book.summary()['halted'] == 'post_claim_failure'
    with pytest.raises(BudgetError):
        book.complete_case(run, declaration(), forbidden_values=FORBIDDEN)
    with book.transaction() as db:
        assert db.execute('SELECT detail FROM ordinary_exchange_failures').fetchone() == (detail,)
        assert db.execute('SELECT COUNT(*) FROM ordinary_answers WHERE case_id=?', (VBREY,)).fetchone() == (0,)


def test_the_numeric_status_is_diagnosis_only():
    plain = TransportFailure('read_error')
    assert plain.status is None
    failure = TransportFailure('http_client_error')
    failure.status = 404
    assert (failure.code, failure.status) == ('http_client_error', 404)       # the code, and so the halt, is the same
    with pytest.raises(BudgetError):
        TransportFailure('http_not_a_code')
