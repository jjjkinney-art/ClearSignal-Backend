"""A blank SIC no longer defeats the registration-only predicate, and nothing else does.

Positive fixtures are trimmed copies of the submissions responses retained for two depositary-receipt
registration entities: Inficon Holding AG/ADR (Run 11, SEC's `sic` present and exactly "") and Vibra
Energia S.A./ADR (Run 10, `sic` "8880"). Negative fixtures are retained operating and cross-border
issuers (Runs 8 to 11) and one-condition mutations of the positives. No network access is used.

What is established: SEC's own complete filing list for the exact CIK shows only registration forms and
no XBRL-flagged filing. What is NOT: anything about what SEC's company-facts service holds for the CIK;
no such request is made, and no HTTP result, 40-F, IFRS taxonomy or empty metadata is an input.
"""
import copy
import inspect
import json
from pathlib import Path

import pytest

from app.services import sec_registration_only as app_copy
from validation import ordinary_registration_only as pilot_copy

DATA = Path(__file__).parent / 'data'
IFCNF = json.loads((DATA / 'sec_submissions_registration_only_blank_sic_retained_run11.json').read_text())
VBREY = json.loads((DATA / 'sec_submissions_registration_only_retained_run10.json').read_text())
OPERATING = json.loads((DATA / 'sec_submissions_operating_retained_runs8_11.json').read_text())
IFCNF_CIK, VBREY_CIK = '0002035057', '0001000377'
COPIES = [pytest.param(app_copy.registration_only_evidence, id='application'),
          pytest.param(pilot_copy.registration_only_evidence, id='pilot')]


def mutated(base, change):
    body = copy.deepcopy(base)
    change(body)
    return body


def recent(body):
    return body['filings']['recent']


# --- the positives ----------------------------------------------------------------------------------------

@pytest.mark.parametrize('check', COPIES)
def test_the_retained_blank_sic_registration_entity_qualifies(check):
    assert IFCNF['sic'] == '' and IFCNF['sicDescription'] == '' and IFCNF['entityType'] == 'other'
    assert check(copy.deepcopy(IFCNF), IFCNF_CIK) == {
        'cik': IFCNF_CIK, 'filings_listed': 2, 'forms': ['F-6 POS', 'F-6EF'], 'xbrl_flags': 0,
        'complete_listing': True, 'entity_type': 'other', 'sic': ''}


@pytest.mark.parametrize('check', COPIES)
def test_the_sic_8880_registration_entity_still_qualifies_exactly_as_before(check):
    assert check(copy.deepcopy(VBREY), VBREY_CIK) == {
        'cik': VBREY_CIK, 'filings_listed': 9, 'forms': ['424B3', 'EFFECT', 'F-6', 'F-6 POS', 'F-6EF'],
        'xbrl_flags': 0, 'complete_listing': True, 'entity_type': 'other', 'sic': '8880'}


# --- the blank is accepted only as SEC writes it ----------------------------------------------------------

BLANK_SIC_REFUSALS = {
    'a conflicting operating SIC': lambda b: b.update(sic='6021', sicDescription='National Commercial Banks'),
    'a conflicting SIC with a blank description': lambda b: b.update(sic='6021'),
    'a whitespace SIC': lambda b: b.update(sic=' '),
    'a padded 8880': lambda b: b.update(sic='8880 '),
    'a null SIC': lambda b: b.update(sic=None),
    'a numeric zero SIC': lambda b: b.update(sic=0),
    'a missing SIC': lambda b: b.pop('sic'),
    'a blank SIC beside a description': lambda b: b.update(sicDescription='American Depositary Receipts'),
    'a blank SIC with no description field': lambda b: b.pop('sicDescription'),
    'a blank SIC with a null description': lambda b: b.update(sicDescription=None),
    'a blank SIC with a whitespace description': lambda b: b.update(sicDescription=' '),
}
CONDITIONS_STILL_REQUIRED = {
    # unread older pages and a malformed listing
    'unread older pages': lambda b: b['filings'].__setitem__('files', [{'name': 'CIK0002035057-submissions-001.json'}]),
    'a missing files field': lambda b: b['filings'].pop('files'),
    'a null files field': lambda b: b['filings'].__setitem__('files', None),
    'empty arrays': lambda b: [recent(b).__setitem__(k, []) for k in ('form', 'isXBRL', 'isInlineXBRL', 'isXBRLNumeric')],
    'a ragged flag array': lambda b: recent(b)['isXBRL'].pop(),
    'a ragged form array': lambda b: recent(b)['form'].pop(),
    'a missing flag array': lambda b: recent(b).pop('isInlineXBRL'),
    'a string flag': lambda b: recent(b)['isXBRL'].__setitem__(0, '0'),
    'a boolean flag': lambda b: recent(b)['isXBRL'].__setitem__(0, False),
    'a null primary flag': lambda b: recent(b)['isInlineXBRL'].__setitem__(1, None),
    'a non-zero numeric flag': lambda b: recent(b)['isXBRLNumeric'].__setitem__(0, 1),
    # a flagged or operating filing
    'one XBRL-flagged filing': lambda b: recent(b)['isXBRL'].__setitem__(0, 1),
    'one inline-XBRL filing': lambda b: recent(b)['isInlineXBRL'].__setitem__(1, 1),
    'an operating 10-K': lambda b: recent(b)['form'].__setitem__(0, '10-K'),
    'a 20-F': lambda b: recent(b)['form'].__setitem__(1, '20-F'),
    'a 40-F': lambda b: recent(b)['form'].__setitem__(1, '40-F'),
    'a 6-K': lambda b: recent(b)['form'].__setitem__(0, '6-K'),
    'an amended F-6': lambda b: recent(b)['form'].__setitem__(0, 'F-6/A'),
    'a non-string form': lambda b: recent(b)['form'].__setitem__(0, None),
    # entity type and CIK
    'an operating entity type': lambda b: b.update(entityType='operating'),
    'a capitalised entity type': lambda b: b.update(entityType='Other'),
    'a missing entity type': lambda b: b.pop('entityType'),
    'another reported CIK': lambda b: b.update(cik='0001471265'),
    'a missing reported CIK': lambda b: b.pop('cik'),
    'no filings object': lambda b: b.pop('filings'),
}


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('label', sorted(BLANK_SIC_REFUSALS))
def test_a_blank_is_accepted_only_exactly_as_sec_writes_it(check, label):
    assert check(mutated(IFCNF, BLANK_SIC_REFUSALS[label]), IFCNF_CIK) is None


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('label', sorted(CONDITIONS_STILL_REQUIRED))
def test_every_other_condition_is_still_required_with_a_blank_sic(check, label):
    assert check(mutated(IFCNF, CONDITIONS_STILL_REQUIRED[label]), IFCNF_CIK) is None


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('expected', [2035057, None, '', 'abc', '0001471265', '00020350570', ' 2035057'])
def test_the_expected_cik_must_be_exactly_this_registrant(check, expected):
    assert check(copy.deepcopy(IFCNF), expected) is None


@pytest.mark.parametrize('check', COPIES)
def test_the_cik_is_compared_as_a_number_not_by_spelling(check):
    assert check(copy.deepcopy(IFCNF), '2035057') is not None


# --- retained operating and cross-border issuers never qualify, however empty their metadata -------------

def _as_blank_registration_entity(body):
    """The most permissive metadata: SEC type 'other' and a blank SIC, exactly like IFCNF's."""
    body = copy.deepcopy(body)
    body.update(entityType='other', sic='', sicDescription='')
    return body


@pytest.mark.parametrize('check', COPIES)
@pytest.mark.parametrize('label', sorted(OPERATING))
def test_a_retained_operating_or_cross_border_issuer_never_qualifies(check, label):
    body = OPERATING[label]
    cik = body['cik']
    # As SEC returned it, and with the blank metadata that would be enough if nothing else were checked.
    assert check(copy.deepcopy(body), cik) is None
    assert check(_as_blank_registration_entity(body), cik) is None
    # Even with its older pages removed and its flags zeroed, an operating or foreign annual form still refuses it.
    cleared = _as_blank_registration_entity(body)
    cleared['filings']['files'] = []
    for key in ('isXBRL', 'isInlineXBRL'):
        cleared['filings']['recent'][key] = [0] * len(cleared['filings']['recent']['form'])
    assert check(cleared, cik) is None


@pytest.mark.parametrize('check', COPIES)
def test_the_foreign_and_ifrs_filers_carry_the_forms_that_refuse_them_not_their_metadata(check):
    for label in ('FORFF (40-F, XBRL-flagged)', 'AUDC (20-F, XBRL-flagged)', 'BP (20-F, IFRS, older pages)',
                  'MRX (20-F, IFRS)'):
        forms = set(OPERATING[label]['filings']['recent']['form'])
        assert forms & {'40-F', '20-F', '6-K'} and not forms <= app_copy.REGISTRATION_FORMS, label


@pytest.mark.parametrize('check', COPIES)
def test_the_name_ticker_http_errors_and_taxonomy_decide_nothing(check):
    renamed = mutated(IFCNF, lambda b: b.update(name='Plain Industries Corporation', tickers=['PLNI'], exchanges=['Nasdaq']))
    assert check(renamed, IFCNF_CIK) is not None
    suffixed = mutated(OPERATING['GALT (operating pharma)'], lambda b: b.update(name='Inficon Holding AG/ADR'))
    assert check(_as_blank_registration_entity(suffixed), suffixed['cik']) is None
    assert list(inspect.signature(check).parameters) == ['submissions', 'expected_cik']


@pytest.mark.parametrize('label', sorted(BLANK_SIC_REFUSALS) + sorted(CONDITIONS_STILL_REQUIRED))
def test_the_application_and_pilot_copies_agree_on_every_blank_sic_fixture(label):
    change = {**BLANK_SIC_REFUSALS, **CONDITIONS_STILL_REQUIRED}[label]
    body = mutated(IFCNF, change)
    for cik in (IFCNF_CIK, '2035057', '0001471265', None):
        assert app_copy.registration_only_evidence(body, cik) == pilot_copy.registration_only_evidence(body, cik)


def test_the_two_copies_agree_on_every_retained_fixture():
    bodies = [IFCNF, VBREY, *OPERATING.values(), *(_as_blank_registration_entity(b) for b in OPERATING.values())]
    for body in bodies:
        for cik in (IFCNF_CIK, VBREY_CIK, body['cik'], None):
            assert app_copy.registration_only_evidence(body, cik) == pilot_copy.registration_only_evidence(body, cik)


# --- what the answer says ---------------------------------------------------------------------------------

@pytest.mark.parametrize('body,cik', [(IFCNF, IFCNF_CIK), (VBREY, VBREY_CIK)], ids=['blank-sic', 'sic-8880'])
def test_the_explanation_states_what_the_filing_list_shows_and_not_what_the_facts_service_holds(body, cik):
    text = app_copy.explanation(app_copy.registration_only_evidence(copy.deepcopy(body), cik))
    assert text.startswith('No financial analysis is available for this registrant.')
    assert 'no company-facts request was made' in text and 'not a retrieval failure' in text
    assert "rests on SEC's filing list alone" in text and 'was not queried' in text
    assert 'nothing here states what it holds' in text
    for claim in ('confirmed', 'verified', '404', 'returned', 'does not exist', 'no data', 'IFRS', 'SIC'):
        assert claim not in text, claim
