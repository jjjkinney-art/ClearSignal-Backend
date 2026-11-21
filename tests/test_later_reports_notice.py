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


# The annual filing each retained answer cites (filing dates from the same retained listings).
ANNUAL_FILED = {'FORFF': '2026-02-12', 'BP': '2026-03-06', 'MRX': '2026-03-25', 'BWMX': '2026-04-30', 'AUDC': '2026-03-30'}


def annual_item(key, form, end, accession='0000000000-26-000001', filed=None):
    """A stand-in for an annual comparison item: only the fields the notice reads (form, issuer URL, period, filed)."""
    cik = LISTINGS[key]['cik']
    return SimpleNamespace(source_type='regulatory_filing', document_type=form, reporting_period_end=end,
                           filed_at=filed or ANNUAL_FILED[key],
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


@pytest.mark.parametrize('key,form,periods,latest,unidentified', [
    ('BP', '20-F', ['2026-03-31', '2026-06-30', '2026-09-30'], [('0000313807-26-000018', 'a30092026bp6kq3.htm')],
     ['a9499b.htm', 'a4317b.htm', 'a02november2026.htm']),
    ('MRX', '20-F', ['2026-03-31', '2026-06-30', '2026-09-30'], [('0001997464-26-000075', 'earningsrelease-6kfilingxc.htm')], []),
    ('BWMX', '20-F', ['2026-06-30'], [('0001213900-26-105780', 'ea0306957-6k_betterware.htm')], ['ea0308695-6k_betterware.htm']),
])
def test_other_retained_foreign_issuers(key, form, periods, latest, unidentified):
    found = af.later_reports([annual_item(key, form, '2025-12-31')], scratch_with(key))
    assert found[0]['periods'] == periods
    assert [(r['accession'], r['document']) for r in found[0]['latest']] == latest
    assert [r['document'] for r in found[0]['unidentified']] == unidentified      # carry a report date that identifies no period
    assert found[0]['undated'] == []                                               # none lacks a report date altogether


def test_fortis_has_no_unidentified_filing_after_its_latest_dated_one():
    row = af.later_reports(fortis_items(), scratch_with('FORFF'))[0]
    assert row['unidentified'] == [] and row['undated'] == []


def test_betterware_latest_dated_filing_is_not_called_the_latest_filing():
    # Second defect (offline-review/DEFECT_LATER_REPORTS_WORDING_20261113.md): a 6-K filed 2026-10-22 gives no
    # report period, so 2026-06-30 must not be presented as the latest period the issuer has reported.
    notice = af.later_reports_notice(af.later_reports([annual_item('BWMX', '20-F', '2025-12-31')], scratch_with('BWMX')))
    assert 'latest period' not in notice
    assert 'shows filings with later report dates: 2026-06-30. The filing dated 2026-06-30: Form 6-K filed 2026-10-01' in notice
    # The list DOES carry a report date for that 6-K (2026-10-22, the filing date); the notice must say it identifies no period,
    # never that the filing gives no report date (corrected after review of the retained listings, 2026-11-20).
    assert ('It also lists 1 Form 6-K filing made after 2026-10-01 whose list report date (2026-10-22) does not identify a '
            'completed financial period (not a quarter end before the filing date), so the period covered, if any, is not stated '
            '(most recent: Form 6-K filed 2026-10-22 (accession 0001213900-26-111757, document ea0308695-6k_betterware.htm)).') in notice
    assert 'does not give a later report date' not in notice


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
    # AudioCodes's 6-Ks all carry their filing date as the report date: none is a dated later period.
    found = af.later_reports([annual_item('AUDC', '20-F', '2025-12-31')], scratch_with('AUDC'))
    assert found[0]['periods'] == [] and found[0]['latest'] == []
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
    assert [r['document'] for r in found[0]['unidentified']] == ['x']  # its report date identifies no period: never counted as one, never called missing


def test_a_later_annual_filing_counts_as_a_later_report():
    # If the answer rests on FY2024 while SEC lists the FY2025 annual, that is also undisclosed staleness.
    found = af.later_reports([annual_item('BWMX', '20-F', '2024-12-31', filed='2025-04-30')], scratch_with('BWMX'))
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

def test_notice_states_the_year_the_report_dates_and_that_nothing_was_read():
    notice = af.later_reports_notice(af.later_reports(fortis_items(), scratch_with('FORFF')))
    assert notice.startswith('Later filings not read: The financial figures in this answer cover the fiscal year ended 2025-12-31.')
    assert 'shows filings with later report dates: 2026-03-31, 2026-06-30 and 2026-09-30.' in notice
    assert 'The filings dated 2026-09-30: Form 6-K filed 2026-11-03 (accession 0001666175-26-000044' in notice
    assert 'accession 0001666175-26-000042, document a2026q3form6k.htm' in notice
    assert 'None of these filings was read, so nothing after 2025-12-31 is reflected and these figures may be out of date' in notice
    assert 'does not know what those filings contain' in notice
    for word in ('revenue', 'income', 'increased', 'decreased', 'results', 'report period', 'latest period', 'quarter'):
        assert word not in notice.lower()


def test_audiocodes_gets_a_notice_from_filings_whose_report_dates_identify_no_period():
    notice = af.later_reports_notice(af.later_reports([annual_item('AUDC', '20-F', '2025-12-31')], scratch_with('AUDC')))
    found = af.later_reports([annual_item('AUDC', '20-F', '2025-12-31')], scratch_with('AUDC'))
    dates = sorted({r['report'] for r in found[0]['unidentified']})
    assert (f"SEC's filing list for this issuer shows 8 Form 6-K filings made after 2026-03-30 whose list report dates ({af._and(dates)}) "
            'do not identify a completed financial period (not a quarter end before the filing date), so the period covered, if any, is not '
            'stated (most recent: Form 6-K filed 2026-11-05 (accession 0001185185-26-005190, document audltd6k110426.htm)).') in notice
    assert 'later report dates' not in notice and 'do not give a later report date' not in notice


def test_undated_filings_before_the_annual_filing_are_not_counted():
    # The 6-K filed the same day as AudioCodes's 20-F (2026-03-30) and earlier ones are not later filings.
    found = af.later_reports([annual_item('AUDC', '20-F', '2025-12-31')], scratch_with('AUDC'))
    assert all(r['filed'] > '2026-03-30' for r in found[0]['unidentified'])
    assert af.later_reports([annual_item('AUDC', '20-F', '2025-12-31', filed='2026-11-05')], scratch_with('AUDC')) == []


def test_apply_marks_the_answer_partial_adds_the_gap_and_is_idempotent():
    found = af.later_reports(fortis_items(), scratch_with('FORFF'))
    thesis = SimpleNamespace(direct_answer='Body.', conclusion='')
    answer = af.apply_later_reports_notice(thesis, {'status': 'attributed', 'unanswered_parts': ['valuation']}, found)
    assert answer['status'] == 'partial'
    assert answer['unanswered_parts'] == ['valuation', 'anything after 2025-12-31 (later SEC filings listed but not read)']
    assert thesis.direct_answer.startswith('Later filings not read:') and thesis.direct_answer.endswith('\n\nBody.')
    assert thesis.conclusion.startswith('Later filings not read:')
    again = af.apply_later_reports_notice(thesis, answer, found)
    assert again['unanswered_parts'] == answer['unanswered_parts']
    assert thesis.direct_answer.count('Later filings not read:') == 1
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


# --- review item a reviewed item (2026-11-20): list metadata versus verified financial periods ----------------------------------

def synthetic_scratch(cik, rows):
    """rows: (form, filed, report) triples as SEC's filing list would carry them; report '' means no report date."""
    listing = {'form': [r[0] for r in rows], 'filingDate': [r[1] for r in rows], 'reportDate': [r[2] for r in rows],
               'accessionNumber': [f'0000000000-26-{i:06d}' for i, _ in enumerate(rows, 1)], 'primaryDocument': [f'doc{i}.htm' for i, _ in enumerate(rows, 1)]}
    scratch = af.Scratch()
    af.bind_scratch(lambda: af.note_filing_list(cik, listing), scratch)()
    return scratch


def synthetic_annual(cik, end='2025-01-31', filed='2025-06-02'):
    return SimpleNamespace(source_type='regulatory_filing', document_type='20-F', reporting_period_end=end, filed_at=filed, freshness_status='current',
                           verified_claims=[{'metric': 'x'}], url=f'https://www.sec.gov/Archives/edgar/data/{cik}/000000000025000001/doc.htm')


B005_LIKE = [('6-K', '2026-08-03', '2026-08-03'), ('6-K', '2026-08-24', '2026-08-24'), ('6-K', '2026-09-11', '2026-09-11'),
             ('6-K', '2026-09-14', '2026-09-14'), ('6-K', '2026-09-29', '2026-09-29')]


def test_six_ks_that_carry_report_dates_are_never_described_as_giving_none():
    notice = af.later_reports_notice(af.later_reports([synthetic_annual('900001')], synthetic_scratch('900001', B005_LIKE)))
    for phrase in ('do not give a later report date', 'does not give a later report date', 'no report date'):
        assert phrase not in notice
    assert 'whose list report dates (2026-08-03, 2026-08-24, 2026-09-11, 2026-09-14 and 2026-09-29) do not identify a completed financial period' in notice
    assert 'cover the fiscal year ended 2025-01-31' in notice


def test_the_notice_separates_list_metadata_from_periods_verified_inside_documents():
    notice = af.later_reports_notice(af.later_reports([synthetic_annual('900001')], synthetic_scratch('900001', B005_LIKE)))
    assert "Report dates in SEC's filing list are metadata entered by the filer, not financial periods verified inside the documents." in notice
    assert 'None of these filings was read' in notice


def test_an_entry_with_no_report_date_is_the_only_kind_called_undated():
    rows = [('6-K', '2026-08-03', ''), ('6-K', '2026-09-11', '2026-09-11')]
    found = af.later_reports([synthetic_annual('900002')], synthetic_scratch('900002', rows))[0]
    assert [r['document'] for r in found['undated']] == ['doc1.htm'] and [r['document'] for r in found['unidentified']] == ['doc2.htm']
    notice = af.later_reports_notice([found])
    assert 'that carry no report date in the list, so the period covered, if any, is not stated' in notice
    assert 'whose list report date (2026-09-11) does not identify a completed financial period' in notice


def test_a_real_quarter_end_report_date_is_still_a_dated_period_and_still_metadata():
    rows = [('6-K', '2026-05-12', '2026-04-30'), ('6-K', '2026-05-20', '2026-04-30')]       # not whole quarters after the year end: not a period
    found = af.later_reports([synthetic_annual('900003', end='2025-12-31', filed='2026-03-31')], synthetic_scratch('900003', [('6-K', '2026-05-12', '2026-03-31')] + rows[:0]))[0]
    assert found['periods'] == ['2026-03-31'] and found['unidentified'] == [] and found['undated'] == []
    notice = af.later_reports_notice([found])
    assert 'shows filings with later report dates: 2026-03-31.' in notice and 'metadata entered by the filer' in notice
