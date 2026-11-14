"""The registration-only predicate: every condition, in both copies, kept equal.

The positive fixture is a trimmed copy of the submissions response Run 10 retained for a
depositary-receipt registration entity (fields the rule never reads are dropped). The negative
fixtures mutate it one condition at a time, using SEC's real encodings (0/1 integers; null where
SEC records no numeric flag).
"""
import copy
import json
from pathlib import Path

import pytest

from app.services import sec_registration_only as app_copy
from validation import ordinary_registration_only as pilot_copy

RETAINED = json.loads((Path(__file__).parent / 'data' / 'sec_submissions_registration_only_retained_run10.json').read_text())
CIK = '0001000377'
COPIES = [pytest.param(app_copy.registration_only_evidence, id='application'),
          pytest.param(pilot_copy.registration_only_evidence, id='pilot')]


def mutated(change):
    body = copy.deepcopy(RETAINED)
    change(body)
    return body


def recent(body):
    return body['filings']['recent']


def operating():
    """An operating issuer's listing in SEC's encoding: XBRL filings, annual and quarterly forms, older pages."""
    body = copy.deepcopy(RETAINED)
    n = 6
    body['entityType'], body['sic'], body['category'] = 'operating', '6021', 'Large accelerated filer'
    body['filings'] = {'recent': {'form': ['10-Q', '8-K', '10-K', '4', '10-Q', '10-K'], 'isXBRL': [1, 0, 1, 0, 1, 1],
                                  'isInlineXBRL': [1, 0, 1, 0, 1, 0], 'isXBRLNumeric': [None, None, 1, 0, None, None]},
                       'files': [{'name': 'CIK0001471265-submissions-001.json', 'filingCount': 325}]}
    return body


MUTATIONS = {
    # 2 and 4: parallel arrays and the XBRL flags
    'an isXBRL of 1': lambda b: recent(b)['isXBRL'].__setitem__(0, 1),
    'an isInlineXBRL of 1': lambda b: recent(b)['isInlineXBRL'].__setitem__(4, 1),
    'an isXBRLNumeric of 1': lambda b: recent(b)['isXBRLNumeric'].__setitem__(2, 1),
    'a string flag': lambda b: recent(b)['isXBRL'].__setitem__(0, '0'),
    'a boolean flag': lambda b: recent(b)['isXBRL'].__setitem__(0, False),
    'a float flag': lambda b: recent(b)['isInlineXBRL'].__setitem__(0, 0.0),
    'a null primary flag': lambda b: recent(b)['isXBRL'].__setitem__(0, None),
    'a non-null non-zero numeric flag type': lambda b: recent(b)['isXBRLNumeric'].__setitem__(0, '0'),
    'a missing isXBRL array': lambda b: recent(b).pop('isXBRL'),
    'a missing isInlineXBRL array': lambda b: recent(b).pop('isInlineXBRL'),
    'a missing isXBRLNumeric array': lambda b: recent(b).pop('isXBRLNumeric'),
    'a missing form array': lambda b: recent(b).pop('form'),
    'a ragged flag array': lambda b: recent(b)['isXBRL'].pop(),
    'a ragged form array': lambda b: recent(b)['form'].pop(),
    'a flag array that is not a list': lambda b: recent(b).__setitem__('isXBRL', 'x' * 9),
    'empty arrays': lambda b: [recent(b).__setitem__(k, []) for k in ('form', 'isXBRL', 'isInlineXBRL', 'isXBRLNumeric')],
    # 3: a complete listing
    'older filing pages': lambda b: b['filings'].__setitem__('files', [{'name': 'CIK0001000377-submissions-001.json'}]),
    'a missing files field': lambda b: b['filings'].pop('files'),
    'a null files field': lambda b: b['filings'].__setitem__('files', None),
    # 5: the closed set of forms
    'a 10-K': lambda b: recent(b)['form'].__setitem__(0, '10-K'),
    'a 20-F': lambda b: recent(b)['form'].__setitem__(1, '20-F'),
    'a 6-K': lambda b: recent(b)['form'].__setitem__(1, '6-K'),
    'an F-1': lambda b: recent(b)['form'].__setitem__(2, 'F-1'),
    'an amended F-6': lambda b: recent(b)['form'].__setitem__(2, 'F-6/A'),
    'a non-string form': lambda b: recent(b)['form'].__setitem__(0, None),
    # 6: corroboration
    'an operating entity type': lambda b: b.__setitem__('entityType', 'operating'),
    'a missing entity type': lambda b: b.pop('entityType'),
    'another SIC': lambda b: b.__setitem__('sic', '6021'),
    'a numeric SIC': lambda b: b.__setitem__('sic', 8880),
    'a missing SIC': lambda b: b.pop('sic'),
    # 1: the exact CIK
    'another reported CIK': lambda b: b.__setitem__('cik', '0001471265'),
    'a missing reported CIK': lambda b: b.pop('cik'),
    'a numeric reported CIK': lambda b: b.__setitem__('cik', 1000377),
    'a non-digit reported CIK': lambda b: b.__setitem__('cik', '00010003x7'),
    # the shape of the response
    'no filings object': lambda b: b.pop('filings'),
    'no recent listing': lambda b: b['filings'].pop('recent'),
}


@pytest.mark.parametrize('check', COPIES)
def test_the_retained_registration_only_response_qualifies(check):
    assert check(copy.deepcopy(RETAINED), CIK) == {
        'cik': CIK, 'filings_listed': 9, 'forms': ['424B3', 'EFFECT', 'F-6', 'F-6 POS', 'F-6EF'], 'xbrl_flags': 0,
        'complete_listing': True, 'entity_type': 'other', 'sic': '8880'}


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('label', sorted(MUTATIONS))
def test_every_unmet_condition_is_refused(check, label):
    assert check(mutated(MUTATIONS[label]), CIK) is None


@pytest.mark.parametrize('check', COPIES)
def test_an_operating_issuer_never_qualifies(check):
    assert check(operating(), '0001471265') is None
    assert check(operating(), CIK) is None


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('expected', [1000377, None, '', 'abc', '0001471265', '00010003770', '-1000377', ' 1000377'])
def test_the_expected_cik_must_be_exactly_this_registrant(check, expected):
    assert check(copy.deepcopy(RETAINED), expected) is None


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('expected', ['0001000377', '1000377'])
def test_the_cik_is_compared_as_a_number_not_by_spelling(check, expected):
    assert check(copy.deepcopy(RETAINED), expected) is not None


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('body', [None, [], 'text', 7, [RETAINED], {}])
def test_a_response_that_is_not_the_expected_object_never_qualifies(check, body):
    assert check(body, CIK) is None


@pytest.mark.parametrize('check', COPIES)
def test_the_name_ticker_and_suffix_decide_nothing(check):
    # Registration-only evidence still qualifies under an ordinary name with no suffix and another ticker ...
    renamed = mutated(lambda b: b.update(name='Plain Industries Corporation', tickers=['PLNI'], exchanges=['Nasdaq']))
    assert check(renamed, CIK) is not None
    # ... and operating evidence is refused under a name that ends "/ADR".
    suffixed = operating()
    suffixed.update(name='Vibra Energia S.A./ADR', tickers=['VBREY'])
    assert check(suffixed, CIK) is None and check(suffixed, '0001471265') is None
    # An HTTP error is not an input at all: the predicate takes only a response body and a CIK.
    import inspect
    assert list(inspect.signature(check).parameters) == ['submissions', 'expected_cik']


@pytest.mark.parametrize('label', sorted(MUTATIONS) + ['retained', 'operating'])
def test_the_application_and_pilot_copies_agree_on_every_fixture(label):
    body = (copy.deepcopy(RETAINED) if label == 'retained' else operating() if label == 'operating'
            else mutated(MUTATIONS[label]))
    for cik in (CIK, '1000377', '0001471265', None):
        assert app_copy.registration_only_evidence(body, cik) == pilot_copy.registration_only_evidence(body, cik)


def test_the_two_copies_share_the_same_closed_form_set():
    assert app_copy.REGISTRATION_FORMS == pilot_copy.REGISTRATION_FORMS == frozenset(
        {'F-6', 'F-6 POS', 'F-6EF', '424B3', 'EFFECT'})
    assert (app_copy.REASON, 'sec_metrics') == (pilot_copy.REASON, pilot_copy.TASK)


def test_the_explanation_is_plain_and_not_a_failure_notice():
    text = app_copy.explanation(app_copy.registration_only_evidence(copy.deepcopy(RETAINED), CIK))
    assert text.startswith('No financial analysis is available for this registrant.')
    assert 'no company-facts request was made' in text and 'not a retrieval failure' in text
    assert '9 filings' in text and 'F-6' in text and 'IFRS' not in text and 'Incomplete answer' not in text
