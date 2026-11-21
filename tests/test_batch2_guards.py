"""Batch 2 review findings (expense row tagged as operating income; pretax sign across filings; later-filings notice).

Each guard is default off and developed on constructed fixtures only; nothing here reads a retained filing. The checks:
* a row label that contradicts the meaning of the tag withholds the figure on EVERY path (Company Facts and inline), no replacement is supplied;
* the same period reported with the same amount and opposite signs in different filings is a conflict that is recorded, never resolved;
* the later-filings notice may cover decision-monitoring answers that display dated reported figures, behind its own flag.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.integrity.row_label_check import label_contradicts, normalize_amount
from app.integrity.sec_metric_evidence import comparable_metric_evidence, explain_no_comparable_metric
from app.providers.sec_client import SecFactRecord
from app.providers.sec_inline_facts import parse_inline_observations, parse_row_labels
from app.services import annual_filing_facts as afacts
from app.services import evidence_outcomes as eo
from app.services import filing_metric_evidence as service
from app.services.evidence_outcomes import OutcomeNotes, build_evidence_outcomes, render_unknown_block
from app.services.financial_thesis_foundation import CORE_METRICS, _rebuild, build_financial_foundation
from app.services.providers.sec_provider import _make_evidence
from test_financial_thesis_foundation import evidence, reference

CIK = '0000320193'
URL = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/company.htm'
CONCEPTS = tuple(c for aliases in CORE_METRICS.values() for c in aliases)


# --- fixtures -----------------------------------------------------------------------------------------------------

def statement(rows):
    """A one-table inline XBRL document. rows = [(label, concept, current, prior, sign)]; amounts as displayed."""
    def context(key, year):
        return (f'<xbrli:context id="{key}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier>'
                f'</xbrli:entity><xbrli:period><xbrli:startDate>{year}-04-01</xbrli:startDate><xbrli:endDate>{year}-06-30</xbrli:endDate>'
                '</xbrli:period></xbrli:context>')

    def fact(i, key, concept, shown, sign):
        sign_attr = f' sign="{sign}"' if sign else ''
        return (f'<ix:nonFraction id="f{i}{key}" name="us-gaap:{concept}" contextRef="{key}" unitRef="usd" decimals="0" scale="0"'
                f' format="ixt:num-dot-decimal"{sign_attr}>{shown}</ix:nonFraction>')
    body = ''.join(f'<tr><td>{label}</td><td>$</td><td>{fact(i, "current", concept, cur, sign)}</td><td>{fact(i, "prior", concept, pri, sign)}</td></tr>'
                   for i, (label, concept, cur, pri, sign) in enumerate(rows))
    return ('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:us-gaap="http://fasb.org/us-gaap/2026" '
            'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">'
            f'<head/><body><ix:header><ix:resources>{context("current", 2026)}{context("prior", 2025)}'
            '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header>'
            f'<table>{body}</table></body></html>')


# expense-row-like: no operating-income subtotal is presented; a small expense line is the row tagged OperatingIncomeLoss.
EXPENSE_ROW_LIKE = [('Revenue', 'Revenues', '511,781', '480,000', ''),
               ('OPERATING EXPENSES', 'OperatingIncomeLoss', '148', '599', '-'),
               ('NET INCOME (LOSS)', 'NetIncomeLoss', '90', '40', '')]


def document(xml, with_labels=True):
    facts = parse_inline_observations(xml, cik=CIK, concepts=CONCEPTS)
    labels = tuple(sorted(parse_row_labels(xml, {f['fact_id'] for f in facts}).items())) if with_labels else ()
    return SimpleNamespace(requested_url=URL, final_url=URL, publisher='SEC EDGAR', published_at='2026-07-28', document_type='10-Q',
                           extraction_method='html', source_type='regulatory_filing', source_tier='primary', content_hash='a' * 64,
                           inline_xbrl_facts=facts, inline_row_labels=labels)


def filing():
    return _make_evidence('Company', '10-Q', '2026-07-28', '2026-06-30', URL)


@pytest.fixture
def row_check(monkeypatch):
    monkeypatch.setattr(settings, 'row_label_check_enabled', True)


# --- the parser and the rule --------------------------------------------------------------------------------------

def test_a_fact_gets_the_first_lettered_cell_of_its_own_row():
    xml = statement(EXPENSE_ROW_LIKE)
    facts = parse_inline_observations(xml, cik=CIK, concepts=CONCEPTS)
    labels = parse_row_labels(xml, {f['fact_id'] for f in facts})
    by_concept = {f['concept']: labels[f['fact_id']] for f in facts}
    assert by_concept == {'Revenues': 'Revenue', 'OperatingIncomeLoss': 'OPERATING EXPENSES', 'NetIncomeLoss': 'NET INCOME (LOSS)'}


def test_a_fact_outside_a_table_row_has_no_label_and_malformed_input_gives_none():
    xml = statement(EXPENSE_ROW_LIKE).replace('<table>', '<p>').replace('</table>', '</p>').replace('<tr>', '<span>').replace('</tr>', '</span>')
    assert parse_row_labels(xml, {'f0current'}) == {}
    assert parse_row_labels('<<<', {'x'}) == {} and parse_row_labels(None, {'x'}) == {} and parse_row_labels('<tr><td>A</td></tr>', set()) == {}


@pytest.mark.parametrize('concept,label,value,expected', [
    ('OperatingIncomeLoss', 'OPERATING EXPENSES', -148, 'expense_row'),
    ('OperatingIncomeLoss', 'Total costs and expenses', -5, 'expense_row'),
    ('OperatingIncomeLoss', 'Operating income (loss)', -148, None),
    ('OperatingIncomeLoss', 'Loss from operations', -148, None),
    ('OperatingIncomeLoss', 'Income from operations', 20, None),
    ('OperatingIncomeLoss', 'Operating profit', 20, None),
    ('OperatingIncomeLoss', 'Total operating expenses and operating loss', -5, None),    # names a result: not an expense-only row
    ('NetIncomeLoss', 'Net loss', 7517, 'loss_row_positive_value'),
    ('NetIncomeLoss', 'Net loss', -7517, None),
    ('NetIncomeLoss', 'Net income', -7517, None),                                          # negative income is ordinary presentation
    ('NetIncomeLoss', 'Net income (loss)', 7517, None),
    ('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest', 'Loss before taxes on income', 7517, 'loss_row_positive_value'),
    ('IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest', 'Loss before taxes on income', -7517, None),
    ('Revenues', 'Operating expenses', 5, None),                                           # only income-natural concepts are checked
    ('OperatingIncomeLoss', None, -5, None), ('OperatingIncomeLoss', '  ', -5, None),
])
def test_the_label_rule_flags_only_a_contradiction(concept, label, value, expected):
    assert label_contradicts(concept, label, value) == expected


def test_amounts_compare_by_magnitude_whatever_their_formatting():
    assert normalize_amount(Decimal('-148.0')) == normalize_amount(148) == '148'
    assert normalize_amount('x') is None


# --- recording labels from the retained filing ---------------------------------------------------------------------

def record_labels(doc):
    notes = OutcomeNotes()
    eo.bind_outcome_notes(lambda: service.evidence_from_filing(doc, filing(), ticker='AAPL', cik=CIK), notes, 'filing_metrics')()
    return notes


def test_the_retained_filing_records_the_label_of_each_core_fact(row_check):
    notes = record_labels(document(statement(EXPENSE_ROW_LIKE)))
    got = {(r['concept'], r['end'], r['abs_value']): r['label'] for r in notes.row_labels}
    assert got[('OperatingIncomeLoss', '2026-06-30', '148')] == 'OPERATING EXPENSES' and got[('OperatingIncomeLoss', '2025-06-30', '599')] == 'OPERATING EXPENSES'


def test_without_labels_or_notes_nothing_is_recorded_and_the_items_are_the_same():
    plain = service.evidence_from_filing(document(statement(EXPENSE_ROW_LIKE), with_labels=False), filing(), ticker='AAPL', cik=CIK)
    labelled = service.evidence_from_filing(document(statement(EXPENSE_ROW_LIKE)), filing(), ticker='AAPL', cik=CIK)
    assert [i.summary for i in plain] == [i.summary for i in labelled] and plain
    assert record_labels(document(statement(EXPENSE_ROW_LIKE), with_labels=False)).row_labels == []


# --- the guard withholds the figure on both paths ------------------------------------------------------------------

def cf(concept, name, current, prior, ytd=False):
    """The Company Facts path: records with no filer row label to inspect, for the same periods as the constructed filing."""
    records = []
    for year, amount in ((2025, prior), (2026, current)):
        accession = f'0000320193-{str(year)[-2:]}-000001'
        records.append(SecFactRecord(cik='320193', taxonomy='us-gaap', concept=concept, label=concept, unit='USD', value=amount,
                                     start=f"{year}-{'01' if ytd else '04'}-01", end=f'{year}-06-30', filed=f'{year}-08-01', form='10-Q', accession=accession,
                                     filing_url=f'https://www.sec.gov/Archives/edgar/data/320193/{accession.replace("-", "")}/{accession}-index.htm'))
    return comparable_metric_evidence(records, ticker='AAPL', expected_cik='320193', concepts=(concept,), metric_name=name)


def cf_operating_income(current=-148, prior=-599):
    return cf('OperatingIncomeLoss', 'operating income', current, prior)


def with_labels(doc):
    notes = OutcomeNotes()
    notes.add_row_labels(record_labels(doc).row_labels)
    return notes


def rebuild_in(notes, item, name='operating income', concepts=('OperatingIncomeLoss',), cik='320193'):
    return eo.bind_outcome_notes(lambda: _rebuild(item, ticker='AAPL', cik=cik, name=name, concepts=concepts), notes, None)()


def test_a_company_facts_figure_is_withheld_when_the_retained_row_label_contradicts_it(row_check):
    notes = with_labels(document(statement(EXPENSE_ROW_LIKE)))
    item = cf_operating_income()
    assert rebuild_in(OutcomeNotes(), item) is not None                      # no retained label: nothing to check, nothing changes
    assert rebuild_in(notes, item) is None                                   # the Company Facts path
    [row] = notes.withheld_figures
    assert (row['measure'], row['reason'], row['code'], row['label']) == ('operating income', 'row_label_disputed', 'expense_row', 'OPERATING EXPENSES')
    assert 'No replacement figure is substituted' in row['text'] and 'No operating margin that depends on it is calculated' in row['text']
    assert '“OPERATING EXPENSES”' in row['text']


def test_the_inline_figure_is_withheld_too(row_check):
    notes = with_labels(document(statement(EXPENSE_ROW_LIKE)))
    inline = next(i for i in service.evidence_from_filing(document(statement(EXPENSE_ROW_LIKE)), filing(), ticker='AAPL', cik=CIK)
                  if i.verified_claims[0]['metric'] == 'us-gaap:OperatingIncomeLoss')
    assert rebuild_in(OutcomeNotes(), inline, cik=CIK) is not None and rebuild_in(notes, inline, cik=CIK) is None


def test_other_measures_and_unmatched_amounts_are_untouched(row_check):
    notes = with_labels(document(statement(EXPENSE_ROW_LIKE)))
    assert rebuild_in(notes, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',)) is not None
    assert rebuild_in(notes, cf_operating_income(current=-150, prior=-600)) is not None       # other amounts are other facts
    assert notes.withheld_figures == []


def test_the_flag_off_changes_nothing_even_with_labels_present():
    notes = with_labels_flag_off = OutcomeNotes()
    notes.add_row_labels([{'concept': 'OperatingIncomeLoss', 'start': '2025-04-01', 'end': '2025-06-30', 'abs_value': '599', 'label': 'OPERATING EXPENSES'},
                          {'concept': 'OperatingIncomeLoss', 'start': '2024-04-01', 'end': '2024-06-30', 'abs_value': '599', 'label': 'OPERATING EXPENSES'}])
    assert rebuild_in(notes, cf_operating_income(current=-148, prior=-599)) is not None and notes.withheld_figures == []


def test_a_disputed_operating_income_removes_the_margin_and_no_other_figure_replaces_it(row_check):
    revenue, net = cf('Revenues', 'revenue', 511781, 480000), cf('NetIncomeLoss', 'net income', 90, 40)
    cash = cf('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', -30, -20, ytd=True)
    items = [revenue, cf_operating_income(), net, cash]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    plain = build_financial_foundation('AAPL', items, refs, expected_cik='320193')
    assert any(row['kind'] == 'operating_margin_calculation' for row in plain['inferences'])            # the defect: a margin from an expense row
    notes = with_labels(document(statement(EXPENSE_ROW_LIKE)))
    guarded = eo.bind_outcome_notes(lambda: build_financial_foundation('AAPL', items, refs, expected_cik='320193'), notes, None)()
    assert not any(row['kind'] == 'operating_margin_calculation' for row in guarded['inferences'])
    assert 'operating income' in guarded['unanswered_parts'] and not any('operating income' in row['claim'] for row in guarded['claims'])
    assert any('revenue' in row['claim'] for row in guarded['claims'])                                  # other verified measures stay
    assert [r['reason'] for r in notes.withheld_figures] == ['row_label_disputed']


def test_the_answer_says_the_figure_was_withheld_and_why(row_check):
    notes = with_labels(document(statement(EXPENSE_ROW_LIKE)))
    rebuild_in(notes, cf_operating_income())
    delivered = {'status': 'attributed', 'claims': [{'claim_kind': 'reported_financial_comparison', 'reference_id': 'E1', 'claim': 'x'}], 'unanswered_parts': []}
    record = next(r for r in build_evidence_outcomes(delivered, notes=notes, references=[{'id': 'E1', 'source': eo._SEC_FACT}]) if r['need'] == 'reported_financials')
    assert record['state'] == 'available' and record['missing_parts'][0]['reason'] == 'row_label_disputed'
    text = render_unknown_block([record])
    assert 'also missing: operating income' in text and 'OPERATING EXPENSES' in text and 'No replacement figure' in text
    none_delivered = {'status': 'insufficient_claim_evidence', 'claims': [], 'unanswered_parts': ['operating income']}
    notes.facts_requests.append({'cik': '320193', 'ok': True, 'taxonomies': {'us-gaap': 5}, 'currencies': {'us-gaap': ['USD']}, 'requested': [], 'present': ['OperatingIncomeLoss'],
                                 'with_records': ['OperatingIncomeLoss'], 'requested_currencies': {}})
    record = next(r for r in build_evidence_outcomes(none_delivered, notes=notes, references=[]) if r['need'] == 'reported_financials')
    assert (record['state'], record['reason']) == ('unsupported', 'row_label_disputed') and 'OPERATING EXPENSES' in record['user_text']


# --- cross-filing sign disagreement --------------------------------------------------------------------------------

def annual(concept, start, end, value, *, filed, form='20-F', accession):
    return SecFactRecord(cik='320193', taxonomy='us-gaap', concept=concept, label=concept, unit='USD', value=value, start=start, end=end, filed=filed,
                         form=form, accession=accession, filing_url=f'https://www.sec.gov/Archives/edgar/data/320193/{accession.replace("-", "")}/{accession}-index.htm')


PRETAX = 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'


def sign_flip_like(*, earlier_sign=-1, amend_later=False):
    """FY2024 reported negative in the FY2024 filing and positive (same amount) in the FY2025 filing; FY2025 positive."""
    return [annual(PRETAX, '2024-01-01', '2024-12-31', earlier_sign * 6912, filed='2025-03-10', accession='0000320193-25-000010'),
            annual(PRETAX, '2024-01-01', '2024-12-31', 6912, filed='2026-03-10', accession='0000320193-26-000010', form='20-F/A' if amend_later else '20-F'),
            annual(PRETAX, '2025-01-01', '2025-12-31', 7517, filed='2026-03-10', accession='0000320193-26-000010', form='20-F/A' if amend_later else '20-F')]


def build(records):
    kwargs = dict(ticker='AAPL', expected_cik='320193', concepts=(PRETAX,), metric_name='pretax income')
    detail = {}
    return comparable_metric_evidence(records, **kwargs), explain_no_comparable_metric(records, detail=detail, **kwargs), detail


def test_by_default_the_latest_filed_sign_is_followed_as_before():
    item, reason, detail = build(sign_flip_like())
    assert item is not None and reason is None and detail == {}


@pytest.fixture
def sign_guard(monkeypatch):
    monkeypatch.setattr(settings, 'sign_conflict_guard_enabled', True)


def test_with_the_guard_a_sign_disagreement_stops_the_comparison_and_prefers_neither_filing(sign_guard):
    item, reason, detail = build(sign_flip_like())
    assert item is None and reason == 'sign_conflict'
    [conflict] = detail['sign_conflicts']
    assert (conflict['role'], conflict['period_start'], conflict['period_end'], conflict['scope'], conflict['unit']) == ('prior', '2024-01-01', '2024-12-31', 'consolidated', 'USD')
    assert [(o['filed'], o['sign']) for o in conflict['observations']] == [('2025-03-10', '-'), ('2026-03-10', '+')]
    assert conflict['resolved'] is False and conflict['amendment_among_them'] is False


def test_amendment_evidence_is_reported_but_does_not_decide_which_sign_is_right(sign_guard):
    item, reason, detail = build(sign_flip_like(amend_later=True))
    assert item is None and reason == 'sign_conflict' and detail['sign_conflicts'][0]['amendment_among_them'] is True


@pytest.mark.parametrize('label,records', [
    ('the same sign in both filings', sign_flip_like(earlier_sign=1)),
    ('a restatement to a different amount', [annual(PRETAX, '2024-01-01', '2024-12-31', -6000, filed='2025-03-10', accession='0000320193-25-000010')] + sign_flip_like()[1:]),
    ('a different duration with the same end date', [annual(PRETAX, '2024-07-01', '2024-12-31', -6912, filed='2025-03-10', accession='0000320193-25-000010', form='10-Q')] + sign_flip_like()[1:]),
])
def test_only_equal_magnitude_opposite_sign_in_the_same_period_is_a_conflict(sign_guard, label, records):
    item, reason, detail = build(records)
    assert reason != 'sign_conflict' and 'sign_conflicts' not in detail


def test_the_sign_is_not_inferred_from_net_income_and_net_income_is_not_consulted(sign_guard):
    net = [annual('NetIncomeLoss', '2025-01-01', '2025-12-31', -7517, filed='2026-03-10', accession='0000320193-26-000010'),
           annual('NetIncomeLoss', '2024-01-01', '2024-12-31', -6912, filed='2026-03-10', accession='0000320193-26-000010')]
    item, reason, detail = build(sign_flip_like() + net)
    assert item is None and reason == 'sign_conflict'          # still withheld: a loss-making net income does not choose the pretax sign


def test_the_conflict_is_recorded_for_the_answer_with_the_filings_and_no_resolution(sign_guard):
    from app.services import verified_sec_metric_service as service_
    notes = OutcomeNotes()
    eo.bind_outcome_notes(lambda: service_._note_pair_outcome(comparable_metric_evidence, sign_flip_like(), 'AAPL', '320193', PRETAX, 'pretax income', 'USD', None),
                          notes, 'sec_metrics')()
    [row] = notes.withheld_figures
    assert row['reason'] == 'sign_conflict' and row['measure'] == 'pretax income'
    for needle in ('opposite signs', '20-F filed 2025-03-10 (negative)', '20-F filed 2026-03-10 (positive)', 'Neither sign is assumed',
                   'none is inferred from another measure', 'None of these filings is marked as an amendment'):
        assert needle in row['text']
    assert notes.pair_outcomes[0]['reason'] == 'sign_conflict' and notes.pair_outcomes[0]['detail']['sign_conflicts']


def test_the_new_reasons_are_record_reasons_and_the_flags_default_off():
    assert {'row_label_disputed', 'sign_conflict'} <= set(eo.REASONS['unsupported'])
    for flag in ('row_label_check_enabled', 'sign_conflict_guard_enabled', 'threshold_later_reports_notice_enabled', 'threshold_comparisons_retained_enabled'):
        assert Settings.model_fields[flag].default is False


# --- the later-filings warning on threshold answers ----------------------------------------------------------------

def test_a_threshold_answer_that_shows_dated_figures_is_covered_but_one_that_shows_none_is_not():
    shown = {'claims': [{'claim_kind': 'reported_financial_comparison', 'reference_id': 'E1'}]}
    assert afacts.displays_dated_figures(shown) is True
    assert afacts.displays_dated_figures({'claims': []}) is False and afacts.displays_dated_figures(None) is False
    assert afacts.displays_dated_figures({'claims': [{'claim_kind': 'issuer_going_concern_disclosure'}]}) is False


def test_the_threshold_notice_flag_is_off_by_default_and_read_live(monkeypatch):
    assert afacts.threshold_notice_enabled() is False
    monkeypatch.setattr(settings, 'threshold_later_reports_notice_enabled', True)
    assert afacts.threshold_notice_enabled() is True
