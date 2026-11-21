"""Iteration 2 of the Batch 2 guards: one test per diagnosed mechanism (ESCAPE_DIAGNOSIS.md in the validation folder).

1. annual (20-F) path labels; IFRS concepts; as-reported rebuild checked        (AUDC)
2. sign conflicts are not bypassed through inline extraction or as-reported      (inline 32 cases, as-reported 12 cases)
3. equivalence by meaning, scope, attribution, unit and period; no conflation    (ProfitLoss vs NetIncomeLoss)
4. mixed expense/result labels and restatement columns are unresolved            (A2, B03, B07)
5. a withheld measure does not discard the remaining verified comparisons        (NWBI)
6. pretax stays supplementary, never feeds a margin, unavailability is stated
Every assertion is on behaviour (what is kept, withheld, and why), not on whether a warning appears.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import settings
from app.integrity.fact_equivalence import equivalent, opposite_sign_rows, fact_key
from app.integrity.row_label_check import assess, binding_from_claim, judge_label, label_contradicts, UNAVAILABLE, UNRESOLVED, WITHHOLD
from app.providers.sec_client import SecFactRecord
from app.providers.sec_inline_facts import parse_inline_observations, parse_row_context, parse_row_labels
from app.services import as_reported_financials as ar
from app.services import evidence_outcomes as eo
from app.services.annual_filing_facts import extra_items
from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.evidence_outcomes import OutcomeNotes
from app.services.financial_thesis_foundation import _rebuild, build_financial_foundation, withhold_disputed_items
from app.services.operating_margin_assessment import operating_margin_assessment
from app.services.row_label_rows import label_rows_from_document
from test_batch2_guards import CIK, URL, cf, filing, label_row, notes_with_rows, rebuild_in, statement
from test_financial_thesis_foundation import reference

CIK_N = '320193'
OP, NET, PRO = 'OperatingIncomeLoss', 'NetIncomeLoss', 'ProfitLoss'
PRE = 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'


@pytest.fixture
def labels_on(monkeypatch):
    monkeypatch.setattr(settings, 'row_label_check_enabled', True)


@pytest.fixture
def sign_on(monkeypatch):
    monkeypatch.setattr(settings, 'sign_conflict_guard_enabled', True)


# --- 1. the annual (20-F) path ------------------------------------------------------------------------------------------------

IFRS_NS = 'http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'


def annual_doc(rows, *, unit='USD'):
    """A 20-F-like inline XBRL statement in the ifrs-full taxonomy. rows = [(label, concept, current, prior, sign)]."""
    def ctx(key, year):
        return (f'<xbrli:context id="{key}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier></xbrli:entity>'
                f'<xbrli:period><xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate></xbrli:period></xbrli:context>')
    body = ''.join(f'<tr><td>{label}</td>' + ''.join(
        f'<td><ix:nonFraction id="a{i}{k}" name="ifrs-full:{concept}" contextRef="{k}" unitRef="u" decimals="0" scale="0" format="ixt:num-dot-decimal"'
        f'{" sign=" + chr(34) + sign + chr(34) if sign else ""}>{shown}</ix:nonFraction></td>' for k, shown in (('c', cur), ('p', pri))) + '</tr>'
        for i, (label, concept, cur, pri, sign) in enumerate(rows))
    xml = ('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
           f'xmlns:ifrs-full="{IFRS_NS}" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">'
           f'<head/><body><ix:header><ix:resources>{ctx("c", 2025)}{ctx("p", 2024)}<xbrli:unit id="u"><xbrli:measure>iso4217:{unit}</xbrli:measure></xbrli:unit>'
           f'</ix:resources></ix:header><table>{body}</table></body></html>')
    concepts = tuple({r[1] for r in rows})
    facts = parse_inline_observations(xml, cik=CIK, concepts=concepts, taxonomies=('ifrs-full',), currencies='*')
    return SimpleNamespace(final_url='https://www.sec.gov/Archives/edgar/data/320193/000032019326000007/f20f.htm', content_hash='b' * 64, document_type='20-F',
                           inline_xbrl_facts=facts, inline_row_labels=tuple(sorted(parse_row_labels(xml, {f['fact_id'] for f in facts}).items())),
                           inline_row_context=tuple(sorted(parse_row_context(xml, {f['fact_id'] for f in facts}).items()))), xml


def test_the_annual_report_rows_are_bound_with_ifrs_taxonomy_currency_period_and_accession(labels_on):
    doc, _ = annual_doc([('OPERATING EXPENSES', 'ProfitLossFromOperatingActivities', '148', '599', '-')], unit='ILS')
    rows = label_rows_from_document(doc, cik=CIK, accession='0000320193-26-000007', form='20-F', taxonomies=('ifrs-full', 'us-gaap'), currencies='*')
    assert {(r['taxonomy'], r['concept'], r['unit'], r['end'], r['abs_value'], r['accession'], r['form'], r['content_hash']) for r in rows} == {
        ('ifrs-full', 'ProfitLossFromOperatingActivities', 'ILS', '2025-12-31', '148', '0000320193-26-000007', '20-F', 'b' * 64),
        ('ifrs-full', 'ProfitLossFromOperatingActivities', 'ILS', '2024-12-31', '599', '0000320193-26-000007', '20-F', 'b' * 64)}
    assert all(r['label'] == 'OPERATING EXPENSES' for r in rows)


def test_extra_items_records_the_annual_labels_in_the_request_notes_even_when_no_comparison_is_built(labels_on, monkeypatch):
    from app.services import annual_filing_facts as afacts
    monkeypatch.setattr(afacts, 'filing_comparisons', lambda document, ticker, cik: ([], []))
    doc, _ = annual_doc([('OPERATING EXPENSES', 'ProfitLossFromOperatingActivities', '148', '599', '-')])
    notes = OutcomeNotes()
    eo.bind_outcome_notes(lambda: extra_items(doc, 'AUD', CIK), notes, 'thesis_disclosures')()
    assert len(notes.row_labels) == 2 and {r['taxonomy'] for r in notes.row_labels} == {'ifrs-full'}


def as_reported_item(concept='ProfitLossFromOperatingActivities', current=-148, prior=-599, unit='USD'):
    def rec(**kw):
        base = dict(cik=CIK_N, taxonomy='ifrs-full', concept=concept, label=concept, unit=unit, value=1, start='2024-01-01', end='2024-12-31',
                    filed='2025-03-01', form='20-F', accession='0000320193-25-000001', filing_url=None)
        base.update(kw)
        base['filing_url'] = f"https://www.sec.gov/Archives/edgar/data/320193/{base['accession'].replace('-', '')}/{base['accession']}-index.htm"
        return SecFactRecord(**base)
    records = [rec(value=prior), rec(start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000320193-26-000007', value=current),
               rec(concept='Assets', start=None, end='2025-12-31', filed='2026-03-01', accession='0000320193-26-000007', value=999)]
    items, _ = ar.build_comparisons(records, ticker='AAPL', cik=CIK_N)
    return next(i for i in items if i.verified_claims[0]['metric'].endswith(concept))


def annual_row(label, concept='ProfitLossFromOperatingActivities', abs_value='148', end='2025-12-31', accession='0000320193-26-000007', **kw):
    return {'cik': CIK_N, 'taxonomy': 'ifrs-full', 'unit': 'USD', 'concept': concept, 'start': end[:4] + '-01-01', 'end': end, 'abs_value': abs_value, 'signed_value': '-' + abs_value,
            'label': label, 'accession': accession, 'form': '20-F', 'document_url': 'u', 'content_hash': 'b' * 64, 'fact_id': 'f', **kw}


def test_an_as_reported_figure_is_withheld_when_the_annual_reports_own_row_contradicts_it(labels_on, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True)
    item = as_reported_item()
    assert rebuild_in(OutcomeNotes(), item, 'operating income', ('OperatingIncomeLoss',), cik=CIK_N) is not None          # no retained label: nothing changes
    notes = notes_with_rows(annual_row('OPERATING EXPENSES'))
    assert rebuild_in(notes, item, 'operating income', ('OperatingIncomeLoss',), cik=CIK_N) is None
    assert notes.withheld_figures[0]['reason'] == 'row_label_disputed' and notes.withheld_figures[0]['concept'] == 'ProfitLossFromOperatingActivities'
    ok = notes_with_rows(annual_row('Profit from operating activities'))
    assert rebuild_in(ok, item, 'operating income', ('OperatingIncomeLoss',), cik=CIK_N) is not None and [c['status'] for c in ok.label_checks][0] == 'clear'


def test_the_sweep_removes_a_withheld_annual_comparison_and_the_explanation_that_quotes_it(labels_on, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True)
    item = as_reported_item()
    explanation = SimpleNamespace(verified_claims=[], period_explanations=[{'metrics': {'operating income': {'current': -148, 'prior': -599}}}])
    unrelated = SimpleNamespace(verified_claims=[], period_explanations=[{'metrics': {'revenue': {'current': 1, 'prior': 2}}}])
    with eo.request_scope():
        notes = notes_with_rows(annual_row('OPERATING EXPENSES'))
        eo.set_scope_notes(notes)
        kept = withhold_disputed_items([item, explanation, unrelated], ticker='AAPL', cik=CIK_N)
    assert kept == [unrelated]                                                    # the figure and what quotes it go; the unrelated explanation stays
    assert [r['measure'] for r in notes.withheld_figures] == ['operating income']


# --- 2. and 3. sign conflicts through any path; equivalence ---------------------------------------------------------------------

def index_row(concept, value, *, taxonomy='us-gaap', accession='0000999999-25-000001', form='10-Q', unit='USD', start='2026-04-01', end='2026-06-30', cik=CIK_N, filed='2025-08-01'):
    return {'cik': cik, 'taxonomy': taxonomy, 'concept': concept, 'unit': unit, 'start': start, 'end': end, 'value': value, 'accession': accession, 'form': form, 'filed': filed}


def with_index(*rows):
    notes = OutcomeNotes()
    notes.add_fact_index(rows)
    return notes


def inline_item(concept='NetIncomeLoss', shown='90'):
    doc = SimpleNamespace(requested_url=URL, final_url=URL, publisher='SEC EDGAR', published_at='2026-07-28', document_type='10-Q', extraction_method='html',
                          source_type='regulatory_filing', source_tier='primary', content_hash='a' * 64, inline_row_labels=(), inline_row_context=(),
                          inline_xbrl_facts=parse_inline_observations(statement([('Net income', concept, shown, '40', '')]), cik=CIK, concepts=(concept,)))
    from app.services import filing_metric_evidence as service
    return next(i for i in service.evidence_from_filing(doc, filing(), ticker='AAPL', cik=CIK) if i.verified_claims[0]['metric'].endswith(concept))


def test_an_inline_item_is_not_a_way_around_a_conflicting_company_facts_observation(sign_on):
    item = inline_item()
    assert rebuild_in(OutcomeNotes(), item, 'net income', (NET,), cik=CIK) is not None                     # nothing indexed: no conflict known
    conflict = with_index(index_row(NET, -90, accession='0000999999-25-000001'))
    assert rebuild_in(conflict, item, 'net income', (NET,), cik=CIK) is None
    [row] = conflict.withheld_figures
    assert row['reason'] == 'sign_conflict' and 'opposite signs' in row['text'] and 'Neither sign is assumed' in row['text']
    assert '10-Q filed 2025-08-01 (negative)' in row['text'] and 'none is inferred from another measure' in row['text']
    assert rebuild_in(with_index(index_row(NET, 90)), item, 'net income', (NET,), cik=CIK) is not None    # same sign in another filing: no conflict
    assert rebuild_in(with_index(index_row(NET, -91)), item, 'net income', (NET,), cik=CIK) is not None    # a different amount is a revision, not this conflict


def test_the_index_covers_every_period_not_only_the_pair_the_company_facts_builder_chose(sign_on):
    item = inline_item()                                           # displays Q2 2026 and Q2 2025
    prior_conflict = with_index(index_row(NET, -40, start='2025-04-01', end='2025-06-30'))
    assert rebuild_in(prior_conflict, item, 'net income', (NET,), cik=CIK) is None
    assert prior_conflict.withheld_figures[0]['text'].startswith('The prior period 2025-04-01 to 2025-06-30')


def test_an_as_reported_figure_is_checked_against_the_index_too(sign_on, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True)
    item = as_reported_item(concept='ProfitLoss', current=-200, prior=-100)
    assert rebuild_in(with_index(index_row('ProfitLoss', 200, taxonomy='ifrs-full', start='2025-01-01', end='2025-12-31')), item, 'net income', ('ProfitLoss',), cik=CIK_N) is None
    assert rebuild_in(with_index(index_row('ProfitLoss', 200, taxonomy='ifrs-full', start='2025-01-01', end='2025-12-31', unit='EUR')), item, 'net income', ('ProfitLoss',), cik=CIK_N) is not None


@pytest.mark.parametrize('a,b,expected', [
    ((('us-gaap', 'ProfitLoss')), ('ifrs-full', 'ProfitLoss'), True),                                       # the same fact under two taxonomies
    (('us-gaap', 'NetIncomeLoss'), ('ifrs-full', 'ProfitLossAttributableToOwnersOfParent'), True),         # parent-attributable on both sides
    (('us-gaap', 'NetIncomeLoss'), ('us-gaap', 'ProfitLoss'), False),                                        # parent-attributable vs TOTAL: never conflated
    (('us-gaap', 'NetIncomeLoss'), ('ifrs-full', 'ProfitLoss'), False),
    (('ifrs-full', 'ProfitLoss'), ('ifrs-full', 'ProfitLossAttributableToOwnersOfParent'), False),
    (('us-gaap', PRE), ('ifrs-full', 'ProfitLossBeforeTax'), True),
    (('us-gaap', OP), ('us-gaap', PRE), False),                                                              # operating vs pretax
    (('us-gaap', 'Revenues'), ('us-gaap', 'GrossProfit'), False),
])
def test_equivalence_follows_meaning_and_attribution_not_names(a, b, expected):
    assert equivalent(a, b) is expected


def test_equal_amounts_do_not_make_total_and_parent_income_the_same_fact(sign_on):
    claim = {'metric': 'us-gaap:NetIncomeLoss', 'unit': 'USD', 'period_start': '2026-04-01', 'period_end': '2026-06-30', 'raw_value': 90,
             'document_ref': {'reference_id': f'sec:{CIK_N}:0000320193-26-000001:us-gaap:NetIncomeLoss'}}
    binding = binding_from_claim(claim, CIK_N)
    index = with_index(index_row('ProfitLoss', -90)).fact_index                      # total net income with the opposite sign and the same amount
    assert opposite_sign_rows(index, binding) == []
    index = with_index(index_row('ProfitLossAttributableToOwnersOfParent', -90, taxonomy='ifrs-full')).fact_index
    assert len(opposite_sign_rows(index, binding)) == 1                               # the equivalent parent-attributable concept does conflict
    assert opposite_sign_rows(with_index(index_row(NET, -90, cik='999')).fact_index, binding) == []                   # another issuer
    assert opposite_sign_rows(with_index(index_row(NET, -90, end='2026-03-31')).fact_index, binding) == []            # another period
    assert opposite_sign_rows(with_index(index_row(NET, -90, accession='0000320193-26-000001')).fact_index, binding) == []   # the claim's own filing


def test_the_index_is_only_built_when_the_guard_is_on_and_is_distinct_from_no_context(monkeypatch):
    records = [SecFactRecord(cik=CIK_N, taxonomy='us-gaap', concept=NET, label='x', unit='USD', value=1, start='2026-04-01', end='2026-06-30', filed='2026-08-01',
                             form='10-Q', accession='0000320193-26-000001', filing_url='u')]
    notes = OutcomeNotes()
    eo.bind_outcome_notes(lambda: eo.note_fact_index(records), notes, 'sec_metrics')()
    assert notes.fact_index == {}                                                   # guard off: nothing is indexed
    monkeypatch.setattr(settings, 'sign_conflict_guard_enabled', True)
    eo.bind_outcome_notes(lambda: eo.note_fact_index(records), notes, 'sec_metrics')()
    assert len(notes.fact_index) == 1
    assert eo.fact_index() is None                                                   # outside any request: no context, not an empty index


def test_an_income_rebuild_outside_the_request_context_fails_closed_for_the_sign_check_too(sign_on):
    before = len(eo.CONTEXT_MISSING)
    assert _rebuild(inline_item(), ticker='AAPL', cik=CIK, name='net income', concepts=(NET,)) is None and len(eo.CONTEXT_MISSING) == before + 1


# --- 4. unresolved labels --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('concept,label,value,kw,expected', [
    (OP, 'Total operating expenses and operating loss', 5, {}, ('ambiguous', 'ambiguous_mixed_label')),
    (OP, 'Total operating expenses and operating loss', -5, {}, ('ambiguous', 'ambiguous_mixed_label')),
    (OP, 'Operating expenses and income from operations', 5, {}, ('ambiguous', 'ambiguous_mixed_label')),
    (NET, 'Total expenses and net income', 90, {}, ('ambiguous', 'ambiguous_mixed_label')),
    (OP, 'Operating expenses', 148, {'cells': ['Operating income']}, ('ambiguous', 'ambiguous_mixed_label')),         # another cell of the row names a result
    (OP, 'Operating expenses', 148, {'cells': ['Note 3']}, ('contradicted', 'expense_row')),
    (NET, 'Net loss', 8299000, {'restatement': True}, ('ambiguous', 'ambiguous_restatement_column')),
    (NET, 'Net loss', 8299000, {'restatement': False}, ('contradicted', 'loss_row_positive_value')),
    (OP, 'OPERATING EXPENSES', 148, {'restatement': True}, ('contradicted', 'expense_row')),                         # an expense row stays wrong in any table
    (NET, 'Net loss', -5114000, {'restatement': True}, ('consistent', None)),
    (NET, 'Net income (loss)', 8299000, {'restatement': True}, ('consistent', None)),
    ('ProfitLossFromOperatingActivities', 'OPERATING EXPENSES', 148, {}, ('contradicted', 'expense_row')),
    ('ProfitLossBeforeTax', 'Loss before tax', 7517, {}, ('contradicted', 'loss_row_positive_value')),
])
def test_unresolved_labels_are_not_contradictions(concept, label, value, kw, expected):
    assert judge_label(concept, label, value, **kw) == expected
    assert (label_contradicts(concept, label, value, **kw) is not None) == (expected[0] == 'contradicted')


def test_restatement_wording_in_the_enclosing_table_header_is_detected_and_cells_are_captured():
    restated = ('<table><tr><td></td><td>As previously reported</td><td>Adjustment</td><td>As restated</td></tr>'
                '<tr><td>Net Loss</td><td>(3,114)</td><td>11,413</td><td><ix:nonFraction id="t">8,299</ix:nonFraction></td></tr></table>')
    plain = '<table><tr><td></td><td>2026</td><td>2025</td></tr><tr><td>Net Loss</td><td>(3,114)</td><td><ix:nonFraction id="t">8,299</ix:nonFraction></td></tr></table>'
    assert parse_row_context(restated, {'t'})['t']['restatement'] is True and parse_row_context(plain, {'t'})['t']['restatement'] is False
    two = '<table><tr><td>Operating expenses</td><td>Operating income</td><td><ix:nonFraction id="t">1</ix:nonFraction></td></tr></table>'
    assert parse_row_context(two, {'t'})['t']['cells'] == ['Operating income']


def test_ambiguous_contradicted_and_unavailable_are_three_distinct_statuses_with_three_different_effects(labels_on):
    """Net income: only a contradiction withholds. (Operating income is stricter, see the unresolved-operating-income tests.)"""
    item = lambda: cf('NetIncomeLoss', 'net income', 90, 40)
    ambiguous = notes_with_rows(label_row('Total expenses and net income', concept='NetIncomeLoss', abs_value='90', cells=[], restatement=False))
    contradicted = notes_with_rows(label_row('Net loss', concept='NetIncomeLoss', abs_value='90'))
    unavailable = notes_with_rows()
    kept = [rebuild_in(n, item(), 'net income', ('NetIncomeLoss',)) is not None for n in (ambiguous, contradicted, unavailable)]
    cur = lambda n: [c['status'] for c in n.label_checks if '|2026-06-30|' in c['key']][0]
    assert (cur(ambiguous), cur(contradicted), cur(unavailable)) == ('ambiguous', 'contradicted', 'no_evidence')
    assert kept == [True, False, True]                                                          # only the contradiction withholds
    assert {'ambiguous'} == set(UNRESOLVED) and 'no_evidence' in UNAVAILABLE and 'contradicted' in WITHHOLD and 'ambiguous' not in WITHHOLD
    assert ambiguous.withheld_figures == [] and unavailable.withheld_figures == []


def test_a_restatement_column_keeps_a_legitimate_positive_restated_value(labels_on):
    row = label_row('Net loss', concept='NetIncomeLoss', abs_value='90', restatement=True)
    item = cf('NetIncomeLoss', 'net income', 90, 40)
    notes = notes_with_rows(row)
    assert rebuild_in(notes, item, 'net income', ('NetIncomeLoss',)) is not None
    assert [c['status'] for c in notes.label_checks if '|2026-06-30|' in c['key']] == ['ambiguous']


# --- 5. NWBI: a withheld measure does not take the other verified comparisons with it ------------------------------------------------

def test_withholding_one_core_measure_keeps_the_remaining_verified_comparisons(labels_on):
    items = [cf('NetIncomeLoss', 'net income', 90, 40), cf('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', 30, 20, ytd=True)]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    settings.row_label_check_enabled = False
    one_only = build_financial_foundation('AAPL', items[1:], refs[1:], expected_cik=CIK_N)
    assert one_only is None                                                                  # the two-comparison rule: unchanged
    settings.row_label_check_enabled = True
    notes = notes_with_rows(label_row('Net loss', concept='NetIncomeLoss', abs_value='90'))
    result = eo.bind_outcome_notes(lambda: build_financial_foundation('AAPL', items, refs, expected_cik=CIK_N), notes, None)()
    assert result is not None
    assert [r['claim'].split(' ')[1:3] for r in result['claims']] == [['operating', 'cash']]    # the cash-flow comparison stands, net income does not
    assert [r['measure'] for r in notes.withheld_figures] == ['net income']
    # an undisputed request is exactly as before: a lone comparison is not a foundation
    assert eo.bind_outcome_notes(lambda: build_financial_foundation('AAPL', items[1:], refs[1:], expected_cik=CIK_N), OutcomeNotes(), None)() is None


# --- 6. pretax is supplementary context only ------------------------------------------------------------------------------------------

def pretax_case(*, op_label):
    items = [cf('Revenues', 'revenue', 511781, 480000), cf('OperatingIncomeLoss', 'operating income', -148, -599), cf('NetIncomeLoss', 'net income', 90, 40),
             cf(PRE, 'pretax income', 149, 34240)]
    refs = [reference(item, f'E{i}') for i, item in enumerate(items, 1)]
    notes = notes_with_rows(label_row(op_label)) if op_label else OutcomeNotes()
    return items, refs, notes


def test_pretax_never_feeds_an_operating_margin():
    revenue, pretax = cf('Revenues', 'revenue', 511781, 480000), cf(PRE, 'pretax income', 149, 34240)
    refs = [reference(revenue, 'E1'), reference(pretax, 'E2')]
    assert operating_margin_assessment({'revenue': (revenue, 'E1'), 'pretax income': (pretax, 'E2')}, refs) is None
    assert operating_margin_assessment({'revenue': (revenue, 'E1'), 'operating income': (pretax, 'E2')}, refs) is None        # pretax cannot stand in either


def test_a_withheld_operating_income_leaves_pretax_as_supplementary_context_and_says_the_margin_is_unavailable(labels_on):
    items, refs, notes = pretax_case(op_label='OPERATING EXPENSES')
    result = eo.bind_outcome_notes(lambda: build_decision_monitoring('AAPL', items, refs, expected_cik=CIK_N), notes, None)()
    assert not any(row['kind'] == 'operating_margin_calculation' for row in result['foundation']['inferences'])
    kinds = {row['claim_kind'] for row in result['foundation']['claims']}
    assert 'supplementary_profitability_comparison' in kinds and 'reported_financial_comparison' in kinds
    assert not any('operating income' in row['claim'] for row in result['foundation']['claims'])
    text = result['answer']
    assert 'Operating income is unavailable' in text and 'no operating margin or margin benchmark has been calculated' in text.replace('No operating', 'no operating')
    assert 'not used to calculate any margin' in text and 'does not stand in for operating income' in text


def test_pretax_comparisons_are_labelled_supplementary_in_the_core_foundation_too(labels_on):
    items, refs, notes = pretax_case(op_label='OPERATING EXPENSES')
    result = eo.bind_outcome_notes(lambda: build_financial_foundation('AAPL', items, refs, expected_cik=CIK_N), notes, None)()
    assert next(r for r in result['claims'] if 'pretax' in r['claim'])['claim_kind'] == 'supplementary_profitability_comparison'
    assert 'Operating income and the operating margin are unavailable' in result['answer'] and 'not used to calculate any margin' in result['answer']


def test_with_the_guards_off_the_pretax_wording_is_unchanged():
    items, refs, notes = pretax_case(op_label=None)
    settings.row_label_check_enabled = False
    items = [i for i in items if 'operating income' not in i.title]
    result = build_decision_monitoring('AAPL', items, refs[:1] + refs[2:], expected_cik=CIK_N)
    assert result is not None and 'Operating income was not verified, so no operating margin or margin benchmark has been calculated.' in result['answer']
    assert 'unavailable' not in result['answer']


def test_every_as_reported_build_indexes_its_records_for_the_sign_check(sign_on):
    """The basis-replacement path builds comparisons without going through evidence_from_response; the index is fed where every build passes."""
    def rec(**kw):
        base = dict(cik=CIK_N, taxonomy='us-gaap', concept=NET, label=NET, unit='CAD', value=1, start='2024-01-01', end='2024-12-31', filed='2025-03-01', form='40-F',
                    accession='0000320193-25-000001', filing_url=None)
        base.update(kw)
        base['filing_url'] = f"https://www.sec.gov/Archives/edgar/data/320193/{base['accession'].replace('-', '')}/{base['accession']}-index.htm"
        return SecFactRecord(**base)
    original = rec(value=920, start='2025-01-01', end='2025-12-31', accession='0000320193-26-000001', filed='2026-03-01')
    flipped = rec(value=-920, start='2025-01-01', end='2025-12-31', accession='0009999999-99-000001', filed='2026-03-11')
    records = [rec(value=900), original, flipped, rec(concept='Assets', start=None, end='2025-12-31', filed='2026-03-11', accession='0009999999-99-000001', value=9)]
    notes = OutcomeNotes()
    eo.bind_outcome_notes(lambda: ar.build_comparisons(records, ticker='AAPL', cik=CIK_N), notes, 'sec_metrics')()
    key = fact_key(CIK_N, 'us-gaap', NET, 'CAD', '2025-01-01', '2025-12-31')
    assert {(r['accession'], r['value']) for r in notes.fact_index[key]} == {('0000320193-26-000001', 920), ('0009999999-99-000001', -920)}


# --- v2 finding: tax-expense wording inside a result label is not an expense line ------------------------------------------------------

@pytest.mark.parametrize('concept,label,value,expected', [
    (NET, 'Net (loss) income before income tax expense', 5, ('consistent', None)),
    (NET, 'Net (loss) income before income tax expense', -5, ('consistent', None)),
    (NET, 'Income before provision for income taxes', 5, ('consistent', None)),
    (NET, 'Earnings before income taxes', 5, ('consistent', None)),
    (OP, 'Operating income before income tax expense', 5, ('consistent', None)),
    (OP, 'Total operating expenses and income before income tax expense', 5, ('ambiguous', 'ambiguous_mixed_label')),     # a real expense word still counts
    (OP, 'OPERATING EXPENSES', 5, ('contradicted', 'expense_row')),
    (OP, 'Total costs and expenses', 5, ('contradicted', 'expense_row')),
    (OP, 'Total operating expenses and operating loss', 5, ('ambiguous', 'ambiguous_mixed_label')),
    (NET, 'Net loss before income tax expense', 5, ('contradicted', 'loss_row_positive_value')),                              # a loss-only label is still a loss row
])
def test_tax_expense_wording_does_not_make_a_result_label_mixed(concept, label, value, expected):
    assert judge_label(concept, label, value) == expected


# --- v3: ambiguous operating income is never "clear" and never feeds a margin or a baseline -------------------------------------------------

def op_notes(label, **extra):
    return notes_with_rows(label_row(label, **extra))


@pytest.mark.parametrize('label,extra,code', [
    ('Total operating expenses and operating loss', {}, 'ambiguous_mixed_label'),
    ('Operating expenses and income from operations', {}, 'ambiguous_mixed_label'),
    ('Operating loss', {'restatement': True, 'abs_value': '148'}, None),            # a loss label on a positive value inside a restatement table (value checked below)
])
def test_ambiguous_operating_income_is_unresolved_not_clear_and_not_used(labels_on, label, extra, code):
    positive = label == 'Operating loss'
    item = cf('OperatingIncomeLoss', 'operating income', 148 if positive else -148, 599 if positive else -599)
    notes = op_notes(label, **extra)
    assert rebuild_in(notes, item) is None                                                       # not used
    status = [c['status'] for c in notes.label_checks if '|2026-06-30|' in c['key']][0]
    assert status == 'ambiguous' and status != 'clear'
    [row] = notes.withheld_figures
    assert (row['reason'], row['status']) == ('row_label_unresolved', 'ambiguous') and row['reason'] != 'row_label_disputed'
    assert 'unresolved, not contradicted' in row['text'] and 'not used for an operating margin or a monitoring baseline' in row['text']
    assert 'No replacement figure is substituted' in row['text']


def test_contradicted_unresolved_and_unavailable_operating_income_have_three_different_reasons_and_outcomes(labels_on):
    item = lambda: cf('OperatingIncomeLoss', 'operating income', -148, -599)
    out = {}
    for name, notes in (('contradicted', op_notes('OPERATING EXPENSES')), ('unresolved', op_notes('Total operating expenses and operating loss')),
                        ('unavailable', notes_with_rows())):
        out[name] = (rebuild_in(notes, item()) is not None, [w['reason'] for w in notes.withheld_figures])
    assert out == {'contradicted': (False, ['row_label_disputed']), 'unresolved': (False, ['row_label_unresolved']), 'unavailable': (True, [])}


def test_unresolved_operating_income_feeds_no_margin_and_no_baseline_and_the_answer_says_so(labels_on):
    items, refs, _ = pretax_case(op_label=None)
    notes = op_notes('Total operating expenses and operating loss')
    result = eo.bind_outcome_notes(lambda: build_decision_monitoring('AAPL', items, refs, expected_cik=CIK_N), notes, None)()
    foundation = result['foundation']
    assert not any(row['kind'] == 'operating_margin_calculation' for row in foundation['inferences']) and result['benchmarks'] == []
    assert not any('operating income' in row['text'].lower() for row in foundation['inferences'])          # no monitoring baseline for it
    assert not any('operating income' in row['claim'] for row in foundation['claims'])
    text = result['answer']
    assert 'Operating income is unavailable: the evidence for it is unresolved' in text and 'not used to calculate any margin' in text
    assert 'disputed' not in text.split('Operating income is unavailable')[1].split('.')[0]


def test_unresolved_net_income_is_kept_and_reported_as_unresolved_not_clear(labels_on):
    notes = notes_with_rows(label_row('Total expenses and net income', concept='NetIncomeLoss', abs_value='90', cells=[], restatement=False))
    assert rebuild_in(notes, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',)) is not None
    assert notes.verification == {'net income': {'ambiguous'}}


# --- v3: an explicit verification-incomplete outcome ---------------------------------------------------------------------------------------

def answer_with(*claims):
    return {'status': 'attributed', 'claims': [{'claim_kind': 'reported_financial_comparison', 'reference_id': f'E{i}', 'claim': c} for i, c in enumerate(claims, 1)], 'unanswered_parts': []}


def reported_record(answer, notes):
    return next(r for r in eo.build_evidence_outcomes(answer, notes=notes, references=[{'id': 'E1', 'source': eo._SEC_FACT}, {'id': 'E2', 'source': eo._SEC_FACT}])
                if r['need'] == 'reported_financial_comparison' or r['need'] == 'reported_financials')


def test_figures_shown_without_row_evidence_are_reported_as_verification_incomplete(labels_on):
    notes = notes_with_rows()                                                                   # a document was not read: no label at all
    rebuild_in(notes, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',))
    answer = answer_with('AAPL net income attributable to parent increased 125.0% to $90 for the period 2026-04-01 to 2026-06-30, from $40 in the comparable prior-year period')
    record = reported_record(answer, notes)
    part = next(p for p in record['missing_parts'] if p['reason'] == 'verification_incomplete')
    assert part['state'] == 'unverified' and 'net income' in part['text'] and 'not a finding that they are wrong' in part['text']
    assert record['state'] == 'available' and record['detail']['verification'] == {'checked': [], 'unresolved': [], 'incomplete': ['net income']}
    block = eo.render_unknown_block([record])
    assert 'statement verification' in block and 'were not available in this request' in block


def test_a_completed_check_is_not_reported_as_incomplete_and_an_unshown_measure_is_not_mentioned(labels_on):
    notes = notes_with_rows(label_row('Net income', concept='NetIncomeLoss', abs_value='90'))
    rebuild_in(notes, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',))
    record = reported_record(answer_with('AAPL net income attributable to parent increased 125.0% to $90 for the period 2026-04-01 to 2026-06-30'), notes)
    assert record['detail']['verification'] == {'checked': ['net income'], 'unresolved': [], 'incomplete': []}
    assert not [p for p in record['missing_parts'] if p['reason'] == 'verification_incomplete']
    unseen = OutcomeNotes()
    rebuild_in(unseen, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',))
    record = reported_record(answer_with('AAPL revenue increased 10.0% to $5 for the period 2026-04-01 to 2026-06-30'), unseen)
    assert not [p for p in record['missing_parts'] if p['reason'] == 'verification_incomplete'] and 'verification' not in record['detail']


def test_with_the_row_label_check_off_no_verification_statement_exists():
    notes = OutcomeNotes()
    assert rebuild_in(notes, cf('NetIncomeLoss', 'net income', 90, 40), 'net income', ('NetIncomeLoss',)) is not None
    assert notes.verification == {} and eo.verification_summary(answer_with('AAPL net income rose'), notes) == {}
