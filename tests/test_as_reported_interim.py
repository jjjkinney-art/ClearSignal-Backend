"""A filer in a currency other than USD/EUR that also files 10-Qs (for example a Canadian 10-K filer in CAD) is compared on its
latest quarter or year-to-date period when that is later than its latest annual period. Same selection as the USD/EUR path
(newest period, shortest duration), same currency, same taxonomy, bound to the 10-Q, nothing converted. Development finding:
three of 45 non-USD US-GAAP issuers had a newer 10-Q period than the annual figure shown."""
import pytest

from app.providers.sec_client import SecFactRecord
from app.services import as_reported_financials as ar


def rec(**kw):
    base = dict(cik='1', taxonomy='us-gaap', concept='Revenues', label='Revenues', unit='CAD', value=100, start='2024-01-01', end='2024-12-31',
                filed='2025-03-01', form='10-K', accession='0000000001-25-000001', filing_url=None)
    base.update(kw)
    base['filing_url'] = (f"https://www.sec.gov/Archives/edgar/data/{int(base['cik'])}/{base['accession'].replace('-', '')}/{base['accession']}-index.htm")
    return SecFactRecord(**base)


def annual(concept='Revenues', cur=120, prior=100):
    return [rec(concept=concept, value=cur, start='2025-01-01', end='2025-12-31', filed='2026-02-15', accession='0000000001-26-000001'),
            rec(concept=concept, value=prior, start='2024-01-01', end='2024-12-31', filed='2025-02-15', accession='0000000001-25-000001'),
            rec(concept='Assets', value=999, start=None, end='2025-12-31', filed='2026-02-15', accession='0000000001-26-000001')]


def quarter(concept='Revenues', cur=40, prior=30, end='2026-03-31', start='2026-01-01', pend='2025-03-31', pstart='2025-01-01', accn='0000000001-26-000010', paccn='0000000001-25-000010', form='10-Q', filed='2026-05-05', pfiled='2025-05-05'):
    return [rec(concept=concept, value=cur, start=start, end=end, filed=filed, accession=accn, form=form),
            rec(concept=concept, value=prior, start=pstart, end=pend, filed=pfiled, accession=paccn, form=form)]


def build(annual_records, interim_records=()):
    return ar.build_comparisons(annual_records, ticker='T', cik='1', interim=interim_records)


def test_annual_only_callers_are_unchanged():
    evidence, _ = build(annual())
    assert len(evidence) == 1 and 'for the period 2025-01-01 to 2025-12-31' in evidence[0].summary and evidence[0].document_type == '10-K'


def test_a_later_quarter_replaces_the_annual_figure_in_the_same_currency_and_is_bound_to_the_10q():
    evidence, _ = build(annual(), quarter())
    item = evidence[0]
    assert item.document_type == '10-Q' and item.reporting_period_end == '2026-03-31' and 'increased 33.3% to 40 CAD' in item.summary
    assert 'for the period 2026-01-01 to 2026-03-31, from 30 CAD in the comparable prior-year period 2025-01-01 to 2025-03-31' in item.summary
    current, prior = item.verified_claims
    assert (current['unit'], prior['unit']) == ('CAD', 'CAD') and current['source'] == prior['source'] == '10-Q'
    assert current['period'] == 'quarter ended 2026-03-31' and current['document_ref']['reference_id'] == 'sec:1:0000000001-26-000010:us-gaap:Revenues'
    assert ar.rebuild_as_reported(item, ticker='T', cik='1', name='revenue') == item


def test_a_year_to_date_period_is_labelled_as_such():
    ytd = quarter(concept='NetCashProvidedByUsedInOperatingActivities', start='2026-01-01', end='2026-09-30', pstart='2025-01-01', pend='2025-09-30', cur=900, prior=800)
    evidence, _ = build(annual(concept='NetCashProvidedByUsedInOperatingActivities'), ytd)
    assert evidence[0].verified_claims[0]['period'] == 'year-to-date period 2026-01-01 to 2026-09-30' and 'increased 12.5%' in evidence[0].summary


def test_the_shortest_duration_at_the_latest_end_is_used():
    both = quarter(cur=40, prior=30, start='2026-04-01', end='2026-06-30', pstart='2025-04-01', pend='2025-06-30', filed='2026-08-05', pfiled='2025-08-05') + [
        rec(value=75, start='2026-01-01', end='2026-06-30', filed='2026-08-05', accession='0000000001-26-000010', form='10-Q'),
        rec(value=60, start='2025-01-01', end='2025-06-30', filed='2025-08-05', accession='0000000001-25-000010', form='10-Q')]
    evidence, _ = build(annual(), both)
    assert 'for the period 2026-04-01 to 2026-06-30' in evidence[0].summary


def test_no_prior_year_interim_period_falls_back_to_the_annual_comparison():
    only_current = quarter()[:1]
    evidence, _ = build(annual(), only_current)
    assert evidence[0].document_type == '10-K' and evidence[0].reporting_period_end == '2025-12-31'


def test_a_different_currency_or_taxonomy_or_a_non_10q_form_is_never_used():
    for over in ({'unit': 'USD'}, {'taxonomy': 'ifrs-full'}, {'form': '6-K'}, {'form': '10-K'}):
        shifted = [rec(concept=r.concept, value=r.value, start=r.start, end=r.end, filed=r.filed, accession=r.accession, **{'form': over.get('form', '10-Q'), 'unit': over.get('unit', 'CAD'), 'taxonomy': over.get('taxonomy', 'us-gaap')}) for r in quarter()]
        evidence, _ = build(annual(), shifted)
        assert evidence[0].reporting_period_end == '2025-12-31', over


def test_conflicting_observations_of_the_latest_quarter_are_not_resolved_by_choosing():
    conflict = quarter() + [rec(value=41, start='2026-01-01', end='2026-03-31', filed='2026-05-05', accession='0000000001-26-000011', form='10-Q')]
    evidence, _ = build(annual(), conflict)
    assert evidence[0].reporting_period_end == '2025-12-31'


def test_a_loss_in_a_quarter_is_worded_without_a_percentage():
    q = quarter(concept='NetIncomeLoss', cur=-40, prior=-5)
    evidence, _ = build(annual(concept='NetIncomeLoss'), q)
    assert 'was a loss in both periods; the loss widened by 35 CAD; signed amounts: -40 CAD' in evidence[0].summary and '%' not in evidence[0].summary


def test_measures_with_different_latest_periods_are_not_shown_together():
    records = annual() + annual(concept='NetIncomeLoss')
    evidence, withheld = build(records, quarter())  # only revenue has a later quarter
    assert [e.verified_claims[0]['metric'] for e in evidence] == ['us-gaap:Revenues']
    assert {'older_period_than_other_measures'} == {w['reason'] for w in withheld if w['metric'] == 'net income'}


def test_the_as_of_boundary_excludes_a_later_filing():
    from datetime import date
    data = {'cik': 1, 'facts': {'us-gaap': {'Revenues': {'label': 'r', 'units': {'CAD': [
        {'start': r.start, 'end': r.end, 'val': r.value, 'accn': r.accession, 'fy': 2026, 'fp': 'Q1', 'form': r.form, 'filed': r.filed} for r in quarter() + annual()[:2]]}}}}}
    evidence, _ = ar.evidence_from_response(data, 'T', '1', boundary=date(2026, 3, 1))
    assert evidence and evidence[0].reporting_period_end == '2025-12-31'
    evidence, _ = ar.evidence_from_response(data, 'T', '1', boundary=date(2026, 6, 1))
    assert evidence[0].reporting_period_end == '2026-03-31'


# --- the timing gap is stated where interim results cannot be read ----------------------------------------

@pytest.mark.parametrize('form,stated', [('20-F', True), ('40-F', True), ('10-K', False), ('10-Q', False)])
def test_a_foreign_annual_comparison_says_interim_results_are_not_read_and_others_do_not(form, stated):
    cur = rec(value=120, start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', form=form)
    prior = rec(value=100, start='2024-01-01', end='2024-12-31', filed='2025-03-01', accession='0000000001-25-000001', form=form)
    if form == '10-Q':
        cur = rec(value=120, start='2026-01-01', end='2026-03-31', filed='2026-05-05', accession='0000000001-26-000002', form=form)
        prior = rec(value=100, start='2025-01-01', end='2025-03-31', filed='2025-05-05', accession='0000000001-25-000002', form=form)
    item, why = ar.evidence_from_pair(cur, prior, ticker='T', expected_cik='1', metric_name='revenue')
    assert why is None and (ar.TIMING_NOTE in item.summary) is stated
    if stated:
        assert item.summary.endswith('interim results published on Form 6-K are not read in this version.')
    assert ar.rebuild_as_reported(item, ticker='T', cik='1', name='revenue') == item
