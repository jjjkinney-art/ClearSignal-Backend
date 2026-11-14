"""The ledger re-proves a blank-SIC declaration from the same case's retained filing list.

Invented ledgers; no network. The retained body is a trimmed copy of the response Run 11 kept for
Inficon Holding AG/ADR, whose SIC SEC leaves blank. The case is placed where cohort 5 put it, 11th.
"""
import copy
import json
from pathlib import Path

import pytest

from validation.capture_budget import BudgetError
from validation.ordinary_pilot_contract import CASES, COHORT
from test_ordinary_native_ledger import ledger
from test_registration_only_ledger import FORBIDDEN, retain

pytestmark = pytest.mark.skipif(COHORT != 'run10' or 'IFCNF:core_thesis' not in CASES,
                                reason='uses the cohort 5 case order')

BLANK = json.loads((Path(__file__).parent / 'data' / 'sec_submissions_registration_only_blank_sic_retained_run11.json').read_text())
IFCNF_CORE, IFCNF_THRESHOLD = 'IFCNF:core_thesis', 'IFCNF:decision_threshold'
CIK = '0002035057'
URL = f'https://data.sec.gov/submissions/CIK{CIK}.json'
EVIDENCE = {'cik': CIK, 'filings_listed': 2, 'forms': ['F-6 POS', 'F-6EF'], 'xbrl_flags': 0,
            'complete_listing': True, 'entity_type': 'other', 'sic': ''}
RECORD = {'task': 'sec_metrics', 'reason': 'no_xbrl_filings', 'evidence': EVIDENCE}


def declaration(evidence=None):
    record = {**RECORD, 'evidence': EVIDENCE if evidence is None else evidence}
    return {'company': 'IFCNF', 'answer': {'source_answer': {
        'status': 'insufficient_claim_evidence', 'claims': [], 'evidence_not_applicable': [record]}}}


def book_at_ifcnf(tmp_path):
    book = ledger(tmp_path)
    for case in CASES[:CASES.index(IFCNF_CORE)]:
        book.complete_case(book.begin_case(case), {'company': '', 'answer': {}}, forbidden_values=FORBIDDEN)
    return book, book.begin_case(IFCNF_CORE)


def facts_attempts(book):
    with book.transaction() as db:
        return db.execute("SELECT COUNT(*) FROM attempts WHERE route='sec/facts'").fetchone()[0]


def test_a_proven_blank_sic_declaration_completes_the_case_with_no_facts_request_and_the_next_case_runs(tmp_path):
    book, run = book_at_ifcnf(tmp_path)
    retain(book, run, 'sec/submissions', URL, BLANK, 'evidence.sec')
    book.complete_case(run, declaration(), forbidden_values=FORBIDDEN)
    second = book.begin_case(IFCNF_THRESHOLD)          # the next case begins: the run is not halted
    retain(book, second, 'sec/submissions', URL, BLANK, 'evidence.sec')
    book.complete_case(second, declaration(), forbidden_values=FORBIDDEN)
    assert book.summary()['halted'] is None and facts_attempts(book) == 0
    with book.transaction() as db:
        assert [r[0] for r in db.execute('SELECT case_id FROM ordinary_answers ORDER BY rowid')][-2:] == [IFCNF_CORE, IFCNF_THRESHOLD]


UNSUPPORTED = {
    'evidence claims SIC 8880 for a blank list': (lambda b: None, {**EVIDENCE, 'sic': '8880'}),
    'a conflicting SIC in the retained list': (lambda b: b.update(sic='6021', sicDescription='National Commercial Banks'), None),
    'a blank SIC beside a description': (lambda b: b.update(sicDescription='American Depositary Receipts'), None),
    'a missing SIC in the retained list': (lambda b: b.pop('sic'), None),
    'older pages the run did not read': (lambda b: b['filings'].__setitem__('files', [{'name': 'x.json'}]), None),
    'one flagged filing': (lambda b: b['filings']['recent']['isXBRL'].__setitem__(0, 1), None),
    'an operating annual form': (lambda b: b['filings']['recent']['form'].__setitem__(0, '10-K'), None),
    'a 40-F': (lambda b: b['filings']['recent']['form'].__setitem__(0, '40-F'), None),
    'a ragged flag array': (lambda b: b['filings']['recent']['isInlineXBRL'].pop(), None),
    'another registrant\'s CIK in the body': (lambda b: b.update(cik='0001000377'), None),
    'evidence with a different count': (lambda b: None, {**EVIDENCE, 'filings_listed': 3}),
    'evidence that omits the SIC': (lambda b: None, {k: v for k, v in EVIDENCE.items() if k != 'sic'}),
}


@pytest.mark.parametrize('label', sorted(UNSUPPORTED))
def test_a_declaration_the_retained_list_does_not_prove_halts(tmp_path, label):
    change, evidence = UNSUPPORTED[label]
    book, run = book_at_ifcnf(tmp_path)
    body = copy.deepcopy(BLANK)
    change(body)
    retain(book, run, 'sec/submissions', URL, body, 'evidence.sec')
    with pytest.raises(BudgetError):
        book.complete_case(run, declaration(evidence), forbidden_values=FORBIDDEN)
    assert book.summary()['halted'] == 'invalid_response'
    with book.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM ordinary_answers WHERE case_id=?', (IFCNF_CORE,)).fetchone() == (0,)


@pytest.mark.parametrize('detail', ['http_client_error_404', 'http_client_error', 'http_auth_403', 'http_throttled_429',
                                    'http_server_error_500', 'read_error', 'connect_error'])
def test_an_issued_facts_request_that_fails_still_halts_and_a_blank_sic_list_cannot_rescue_it(tmp_path, detail):
    from validation.capture_budget import digest
    book, run = book_at_ifcnf(tmp_path)
    retain(book, run, 'sec/submissions', URL, BLANK, 'evidence.sec')          # the list does prove absence ...
    fingerprint = digest({'method': 'GET', 'url': f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json',
                          'stage': 'evidence.sec_metrics', 'route': 'sec/facts'})
    attempt = book.reserve(run, 'sec/facts', stage='evidence.sec_metrics', input_bound=0, output_bound=0,
                           request_sha256=fingerprint)
    book.record_exchange_failure(attempt, 'transport', detail)                 # ... but a request was issued and failed
    assert book.summary()['halted'] == 'post_claim_failure'
    with pytest.raises(BudgetError):
        book.complete_case(run, declaration(), forbidden_values=FORBIDDEN)
    with book.transaction() as db:
        assert db.execute('SELECT detail FROM ordinary_exchange_failures').fetchone() == (detail,)
