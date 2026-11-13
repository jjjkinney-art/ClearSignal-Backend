"""An answer built on a foreign issuer's annual filing says when SEC lists later reports that were not read.

Defect (offline-review/DEFECT_STALE_ANNUAL_FOREIGN_20261113.md): with the as-reported flag on, Fortis, BP, Marex
and Betterware answers present fiscal 2025 comparisons with no word that the issuer has since filed 6-K reports for
up to three later quarters. Listings are trimmed copies of the retained SEC submissions bodies from pilot Runs 4, 8,
9 and 11; Company Facts are the retained trimmed copies already used by the as-reported tests.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.providers import sec_client
from app.services import annual_filing_facts as af
from app.services import as_reported_financials as ar
from app.services.providers import sec_provider

DATA = Path(__file__).resolve().parent / 'data'
LISTINGS = json.loads((DATA / 'sec_submissions_foreign_listing_retained_runs4_11.json').read_text())
FACTS = json.loads((DATA / 'company_facts_as_reported_retained_runs4_11.json').read_text())


def scratch_with(*keys):
    scratch = af.Scratch()
    for key in keys:
        af.bind_scratch(lambda k=key: af.note_filing_list(LISTINGS[k]['cik'], LISTINGS[k]['recent']), scratch)()
    return scratch


def fortis_items():
    records = sec_client.as_reported_records_from_facts(FACTS['FORFF'], str(FACTS['FORFF']['cik']), specs=ar.requested_specs())
    items = ar.build_comparisons(records, ticker='FTS', cik=str(FACTS['FORFF']['cik']))[0]
    for item in items:
        item.freshness_status = 'current'
    return items


def annual_item(key, form, end, accession='0000000000-26-000001'):
    """A stand-in for an annual comparison item: only the fields the notice reads (form, issuer URL, period)."""
    cik = LISTINGS[key]['cik']
    return SimpleNamespace(source_type='regulatory_filing', document_type=form, reporting_period_end=end,
                           freshness_status='current', verified_claims=[{'metric': 'x'}],
                           url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/doc.htm")


# --- the reproduced cases -----------------------------------------------------------------------------

def test_fortis_answer_names_the_three_later_quarters_and_the_latest_filings():
    found = af.later_reports(fortis_items(), scratch_with('FORFF'))
    assert len(found) == 1
    row = found[0]
    assert row['annual_period_end'] == '2025-12-31'
    assert row['periods'] == ['2026-03-31', '2026-06-30', '2026-09-30']
    assert [(r['accession'], r['document'], r['filed']) for r in row['latest']] == [
        ('0001666175-26-000044', 'form6k-q32026investorprese.htm', '2026-11-03'),
        ('0001666175-26-000042', 'a2026q3form6k.htm', '2026-11-03')]


@pytest.mark.parametrize('key,form,periods,latest', [
    ('BP', '20-F', ['2026-03-31', '2026-06-30', '2026-09-30'], [('0000313807-26-000018', 'a30092026bp6kq3.htm')]),
    ('MRX', '20-F', ['2026-03-31', '2026-06-30', '2026-09-30'], [('0001997464-26-000075', 'earningsrelease-6kfilingxc.htm')]),
    ('BWMX', '20-F', ['2026-06-30'], [('0001213900-26-105780', 'ea0306957-6k_betterware.htm')]),
])
def test_other_retained_foreign_issuers(key, form, periods, latest):
    found = af.later_reports([annual_item(key, form, '2025-12-31')], scratch_with(key))
    assert found[0]['periods'] == periods
    assert [(r['accession'], r['document']) for r in found[0]['latest']] == latest


# --- rows that must not count -------------------------------------------------------------------------

def test_report_dates_after_the_filing_date_are_schedules_not_periods():
    # Fortis fortis6knomrd.htm (filed 2026-02-18, report 2026-05-07); Marex magnum notice (filed 2026-06-18,
    # report 2026-12-31) and its Q1 cover page (filed 2026-03-26, report 2026-03-31).
    for key in ('FORFF', 'MRX'):
        found = af.later_reports([annual_item(key, '20-F', '2025-12-31')], scratch_with(key))
        documents = {r['document'] for r in found[0]['latest']}
        assert not documents & {'fortis6knomrd.htm', 'magnum-form6xknoticeofsche.htm', 'a6kfiling-coverpagesq126ea.htm'}
    assert '2026-12-31' not in af.later_reports([annual_item('MRX', '20-F', '2025-12-31')], scratch_with('MRX'))[0]['periods']


def test_same_day_and_mid_month_report_dates_do_not_count():
    # AudioCodes's 6-Ks all carry their filing date as the report date: nothing says which period they cover.
    assert af.later_reports([annual_item('AUDC', '20-F', '2025-12-31')], scratch_with('AUDC')) == []
    # Fortis 2026-09-10 filings report 2026-09-09: not a month end.
    periods = af.later_reports(fortis_items(), scratch_with('FORFF'))[0]['periods']
    assert '2026-09-09' not in periods


def test_periods_must_be_whole_quarters_after_the_annual_year_end():
    listing = {'form': ['6-K', '6-K'], 'filingDate': ['2026-08-10', '2026-05-10'],
               'reportDate': ['2026-07-31', '2026-03-31'], 'accessionNumber': ['a', 'b'], 'primaryDocument': ['x', 'y']}
    scratch = af.Scratch()
    af.bind_scratch(lambda: af.note_filing_list(LISTINGS['BWMX']['cik'], listing), scratch)()
    found = af.later_reports([annual_item('BWMX', '20-F', '2025-12-31')], scratch)
    assert found[0]['periods'] == ['2026-03-31']  # 2026-07-31 is seven months on, not a quarter end for this issuer


def test_a_later_annual_filing_counts_as_a_later_report():
    # If the answer rests on FY2024 while SEC lists the FY2025 annual, that is also undisclosed staleness.
    found = af.later_reports([annual_item('BWMX', '20-F', '2024-12-31')], scratch_with('BWMX'))
    assert '2025-12-31' in found[0]['periods'] and found[0]['periods'][-1] == '2026-06-30'
    notice = af.later_reports_notice(found)
    assert 'cover the fiscal year ended 2024-12-31' in notice


def test_no_notice_without_a_foreign_annual_item_for_that_issuer():
    scratch = scratch_with('FORFF')
    assert af.later_reports([annual_item('FORFF', '10-K', '2025-12-31')], scratch) == []
    assert af.later_reports([annual_item('BP', '20-F', '2025-12-31')], scratch) == []  # listing is Fortis's only
    stale = annual_item('FORFF', '40-F', '2025-12-31')
    stale.freshness_status = 'stale'
    assert af.later_reports([stale], scratch) == []
    assert af.later_reports(fortis_items(), None) == []
    assert af.later_reports(fortis_items(), af.Scratch()) == []


# --- what the answer says ----------------------------------------------------------------------------

def test_notice_states_the_year_the_periods_and_that_nothing_was_read():
    notice = af.later_reports_notice(af.later_reports(fortis_items(), scratch_with('FORFF')))
    assert notice.startswith('Later reports not read: The financial figures in this answer cover the fiscal year ended 2025-12-31.')
    assert 'shows filings for 3 later report periods, ending 2026-03-31, 2026-06-30 and 2026-09-30' in notice
    assert 'accession 0001666175-26-000042, document a2026q3form6k.htm' in notice
    assert 'were not read, so nothing after 2025-12-31 is reflected and these figures may be out of date' in notice
    assert 'does not know what those filings contain' in notice
    for word in ('revenue', 'income', 'increased', 'decreased', 'results show'):
        assert word not in notice.lower()


def test_singular_wording_for_one_period():
    notice = af.later_reports_notice(af.later_reports([annual_item('BWMX', '20-F', '2025-12-31')], scratch_with('BWMX')))
    assert 'filings for 1 later report period, ending 2026-06-30.' in notice


def test_apply_marks_the_answer_partial_adds_the_gap_and_is_idempotent():
    found = af.later_reports(fortis_items(), scratch_with('FORFF'))
    thesis = SimpleNamespace(direct_answer='Body.', conclusion='')
    answer = af.apply_later_reports_notice(thesis, {'status': 'attributed', 'unanswered_parts': ['valuation']}, found)
    assert answer['status'] == 'partial'
    assert answer['unanswered_parts'] == ['valuation', 'results after 2025-12-31 (later filings listed by SEC but not read)']
    assert thesis.direct_answer.startswith('Later reports not read:') and thesis.direct_answer.endswith('\n\nBody.')
    assert thesis.conclusion.startswith('Later reports not read:')
    again = af.apply_later_reports_notice(thesis, answer, found)
    assert again['unanswered_parts'] == answer['unanswered_parts']
    assert thesis.direct_answer.count('Later reports not read:') == 1
    insufficient = af.apply_later_reports_notice(SimpleNamespace(direct_answer='x', conclusion='y'),
                                                 {'status': 'insufficient_claim_evidence'}, found)
    assert insufficient['status'] == 'insufficient_claim_evidence'


def test_nothing_changes_without_findings_or_a_source_answer():
    thesis = SimpleNamespace(direct_answer='Body.', conclusion='C.')
    answer = {'status': 'attributed', 'unanswered_parts': []}
    assert af.apply_later_reports_notice(thesis, answer, []) is answer
    assert af.apply_later_reports_notice(thesis, None, af.later_reports(fortis_items(), scratch_with('FORFF'))) is None
    assert thesis.direct_answer == 'Body.'


# --- flags and requests ------------------------------------------------------------------------------

def test_the_notice_follows_the_as_reported_flag(monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', False, raising=False)
    assert af.later_reports_enabled() is False
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    assert af.later_reports_enabled() is True


def test_without_a_scratch_the_listing_is_not_kept():
    af.note_filing_list(LISTINGS['FORFF']['cik'], LISTINGS['FORFF']['recent'])  # no active scratch: a no-op


def test_listing_capture_makes_no_additional_request(monkeypatch):
    calls = []
    body = {'name': 'Fortis Inc.', 'cik': '1666175', 'filings': {'recent': {
        **LISTINGS['FORFF']['recent'], 'items': [''] * len(LISTINGS['FORFF']['recent']['form'])}}}
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'FTS': '0001666175'})
    monkeypatch.setattr(sec_provider, '_fetch_json', lambda url, timeout=10: calls.append(url) or json.loads(json.dumps(body)))
    without = sec_provider._fetch_by_cik('FTS', ['40-F'], 5, 2, as_of='2026-11-13')
    scratch = af.Scratch()
    with_scratch = af.bind_scratch(lambda: sec_provider._fetch_by_cik('FTS', ['40-F'], 5, 2, as_of='2026-11-13'), scratch)()
    assert len(calls) == 2 and calls[0] == calls[1]  # one GET per call, with or without the scratch
    assert [e.url for e in without] == [e.url for e in with_scratch]
    assert len(scratch.listings['1666175']) == len(LISTINGS['FORFF']['recent']['form'])
