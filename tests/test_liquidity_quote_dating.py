"""Dating guards for the liquidity-statement quote (open release issue, IRMD, 2026-11-14).

RETAINED: tests/data/liquidity_statement_irmd_retained_d1.json is a verbatim slice of the IRMD 10-Q filed 2026-10-30
(period ended 2026-09-30) in which the statement's leading neighbour is the PRIOR year-end balance, with a page number
("23") and a layout artifact ("milli on ."). CONSTRUCTED cases are labelled. Model-assisted: the same model wrote the rule
and these tests.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import liquidity_statement as L

DATA = json.loads((Path(__file__).resolve().parent / 'data' / 'liquidity_statement_irmd_retained_d1.json').read_text())['IRMD']
CIK, PERIOD = '0001325618', '2026-09-30'


def doc(text, published='2026-10-30'):
    return SimpleNamespace(document_type='10-Q', publisher='SEC EDGAR', source_type='regulatory_filing', source_tier='primary',
                           extraction_method='html', text=text, final_url=DATA['url'], published_at=published,
                           content_hash=hashlib.sha256(text.encode()).hexdigest(), title='IRMD 10-Q')


def extract(text):
    items = L.extract_liquidity_statement(doc(text), ticker='IRMD', cik=CIK, period_end=PERIOD)
    for item in items:
        item.availability_status, item.freshness_status = 'available', 'current'
    return items


def bound(item):
    return L.bound_liquidity_statement(item, ticker='IRMD', cik=CIK)


STATEMENT = ('We believe that our current cash, and cash generated from operations will be sufficient to meet our ongoing operating '
             'requirements for at least the next 12 months and into the foreseeable future.')
CAVEAT = ('We do not anticipate requiring additional capital; however, if required or desirable, we may seek to obtain a credit '
          'facility, raise debt, or issue additional equity in private or public markets.')


def test_the_retained_irmd_quote_keeps_the_statement_caveat_and_citation_and_drops_the_stale_balance_and_page_number():
    item, = extract(DATA['excerpt'])
    value = item.liquidity_statements[0]
    assert value['statement'] == STATEMENT and value['quote'] == f'{STATEMENT} {CAVEAT}'
    assert 'December 31, 2025' not in value['quote'] and '$51.2' not in value['quote'] and '23 ' not in value['quote'] and 'milli on' not in value['quote']
    assert 'however, if required or desirable' in value['quote']  # the caveat travels with the statement
    ref = value['document_ref']
    assert ref['quote'] == value['quote'] and ref['url'] == DATA['url'] and ref['published_at'] == '2026-10-30' and ref['section'] == 'Liquidity statement'
    assert value['quote'] in DATA['excerpt']  # still verbatim
    assert item.summary.startswith('IRMD stated in its 10-Q filed 2026-10-30 (period ended 2026-09-30): “We believe')
    assert bound(item) is not None


def test_the_old_form_with_the_stale_balance_is_no_longer_accepted_by_the_binder(monkeypatch):
    monkeypatch.setattr(L, 'dated_to_period_end', lambda *a: True)  # the previous behaviour: any neighbour is quoted
    item, = extract(DATA['excerpt'])
    assert item.liquidity_statements[0]['quote'].startswith('As of December 31, 2025')
    monkeypatch.undo()
    assert bound(item) is None


@pytest.mark.parametrize('text,expected', [
    ('Our principal uses of cash are operating expenses and capital expenditures.', True),                       # no amount
    ('As of September 30, 2026, we had cash and cash equivalents of $63.3 million.', True),                    # dated to the period end
    ('As of December 31, 2025, we had cash and cash equivalents of $51.2 million.', False),                    # prior period
    ('We had cash and cash equivalents of $51.2 million.', False),                                              # undated amount
    ('As of September 30, 2026 we had $63.3 million, compared with $51.2 million as of December 31, 2025.', False),  # mixed dates
    ('Cash was $4 billion at September 30, 2026.', True),
])
def test_a_neighbour_that_states_an_amount_must_date_it_to_the_period_end(text, expected):
    # CONSTRUCTED sentences
    assert L.dated_to_period_end(text, PERIOD) is expected


def test_a_neighbour_dated_to_the_period_end_is_kept():
    # CONSTRUCTED: the current balance directly before the statement is quoted, with its date.
    text = f'Intro sentence. As of September 30, 2026, we had cash and cash equivalents of $63.3 million. {STATEMENT} {CAVEAT}'
    value = extract(text)[0].liquidity_statements[0]
    assert value['quote'].startswith('As of September 30, 2026, we had cash') and value['quote'].endswith('private or public markets.')
    assert bound(extract(text)[0]) is not None


def test_an_undated_amount_in_the_following_neighbour_is_left_out_but_the_statement_stays():
    # CONSTRUCTED
    text = f'{STATEMENT} Cash on hand was $63.3 million.'
    value = extract(text)[0].liquidity_statements[0]
    assert value['quote'] == STATEMENT


def test_a_page_number_is_removed_from_the_statement_only_when_it_is_a_short_bare_number():
    # CONSTRUCTED
    assert extract(f'Closing words of a page. 23 {STATEMENT}')[0].liquidity_statements[0]['statement'] == STATEMENT
    one = extract(f'Closing words of a page. 7 {STATEMENT}')[0].liquidity_statements[0]  # a one-digit marker too
    assert one['statement'] == STATEMENT and one['quote'] == f'Closing words of a page. 7 {STATEMENT}'
    odd = extract(f'Closing words of a page. 2026 {STATEMENT}')  # a four-digit number is not a page marker
    assert odd == [] or odd[0].liquidity_statements[0]['statement'].startswith('2026 ')


def test_a_kept_neighbour_before_a_page_number_keeps_the_marker_inside_the_verbatim_quote():
    # CONSTRUCTED: the neighbour has no amount, so it is kept; the quote stays verbatim including the marker.
    text = f'Our principal uses of cash are operating expenses. 23 {STATEMENT}'
    item, = extract(text)
    value = item.liquidity_statements[0]
    assert value['statement'] == STATEMENT and value['quote'] == f'Our principal uses of cash are operating expenses. 23 {STATEMENT}'
    assert value['quote'][value['statement_offset']:].startswith(STATEMENT) and bound(item) is not None


def test_tampering_with_the_neighbour_dates_is_rejected():
    item, = extract(f'Intro. As of September 30, 2026, we had cash of $63.3 million. {STATEMENT}')
    assert bound(item) is not None
    forged = item.model_copy(deep=True)
    v = forged.liquidity_statements[0]
    v['quote'] = v['quote'].replace('September 30, 2026', 'December 31, 2025')
    v['document_ref']['quote'] = v['quote']
    assert bound(forged) is None
