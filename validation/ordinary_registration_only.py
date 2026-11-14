"""Verification of a registration-only declaration against the run's own retained evidence.

The application may skip a company-facts request, and say so, only when SEC's complete filing
list proves the registrant has no XBRL data (app/services/sec_registration_only.py). The pilot
does not take that on trust: the ledger and the export re-evaluate the same conditions on the
submissions response the same case retained, for the exact CIK the case registered, and
require that the case made no ``sec/facts`` attempt. This module is a second, independent copy
of the predicate (validation never imports application code); a test keeps the two equal.

A missing, malformed or misaligned field never qualifies, and nothing here reads a name,
a ticker, an "/ADR" suffix or an HTTP error.
"""
import json
import re

from validation.capture_budget import BudgetError

REGISTRATION_FORMS = frozenset({'F-6', 'F-6 POS', 'F-6EF', '424B3', 'EFFECT'})
TASK, REASON = 'sec_metrics', 'no_xbrl_filings'
_PARALLEL = ('form', 'isXBRL', 'isInlineXBRL', 'isXBRLNumeric')


def _zero(value):
    return type(value) is int and value == 0


def _sic_allows(submissions):
    """SIC '8880', or SEC's blank for an unclassified entity: the key present as '' with an empty description."""
    if 'sic' not in submissions or type(submissions['sic']) is not str:
        return False
    if submissions['sic'] == '8880':
        return True
    return submissions['sic'] == '' and 'sicDescription' in submissions and submissions['sicDescription'] == ''


def registration_only_evidence(submissions, expected_cik):
    """The evidence summary if every condition holds, else None."""
    if type(expected_cik) is not str or not re.fullmatch(r'[0-9]{1,10}', expected_cik) or type(submissions) is not dict:
        return None
    reported = submissions.get('cik')
    if type(reported) is not str or not re.fullmatch(r'[0-9]{1,10}', reported) or int(reported) != int(expected_cik):
        return None
    filings = submissions.get('filings')
    recent = filings.get('recent') if type(filings) is dict else None
    if type(recent) is not dict or filings.get('files') != []:
        return None
    arrays = [recent.get(key) for key in _PARALLEL]
    if any(type(array) is not list for array in arrays):
        return None
    count = len(arrays[0])
    if count < 1 or any(len(array) != count for array in arrays):
        return None
    forms, is_xbrl, is_inline, numeric = arrays
    if (any(type(form) is not str or form not in REGISTRATION_FORMS for form in forms)
            or not all(_zero(value) for value in is_xbrl) or not all(_zero(value) for value in is_inline)
            or any(value is not None and not _zero(value) for value in numeric)):
        return None
    if submissions.get('entityType') != 'other' or not _sic_allows(submissions):
        return None
    return {'cik': reported, 'filings_listed': count, 'forms': sorted(set(forms)), 'xbrl_flags': 0,
            'complete_listing': True, 'entity_type': 'other', 'sic': submissions['sic']}


def declared_not_applicable(payload):
    """The not-applicable records an answer declares, () when it declares none.

    Raises BudgetError for a declaration of any other shape; an answer of every consumed run
    declares nothing.
    """
    answer = payload.get('answer') if type(payload) is dict else None
    source = answer.get('source_answer') if type(answer) is dict else None
    if type(source) is not dict or 'evidence_not_applicable' not in source:
        return ()
    records = source['evidence_not_applicable']
    if (type(records) is not list or not records
            or any(type(r) is not dict or set(r) != {'task', 'reason', 'evidence'} or r['task'] != TASK
                   or r['reason'] != REASON or type(r['evidence']) is not dict for r in records)):
        raise BudgetError('malformed not-applicable declaration')
    return tuple(records)


def declaration_supported(records, expected_cik, submissions_body, facts_attempts):
    """True only if the retained evidence proves every declared record and no facts request was made."""
    if not records or facts_attempts != 0 or type(submissions_body) is not bytes:
        return False
    try:
        evidence = registration_only_evidence(json.loads(submissions_body), expected_cik)
    except (ValueError, RecursionError):
        return False
    return evidence is not None and all(r['evidence'] == evidence for r in records)


def submissions_url(expected_cik):
    return f'https://data.sec.gov/submissions/CIK{int(expected_cik):010d}.json'
