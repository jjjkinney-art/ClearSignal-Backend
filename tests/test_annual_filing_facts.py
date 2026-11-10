"""Annual comparisons and management explanations from a 20-F the request already fetched (default off).

Fixtures are trimmed copies of the retained Betterware (Run 4, MXN, IFRS) and Marex (Run 9, USD, IFRS) 20-F
documents: the real inline XBRL contexts, units and facts, and the real results-discussion sentences, verbatim.
Company Facts is the retained body from tests/data. Nothing here touches the network: any request is counted, and
the whole chain is asserted to make exactly the one document fetch the request already made.
"""
import copy
import json
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.providers import sec_inline_facts as inline
from app.services import annual_filing_facts as afacts
from app.services import as_reported_financials as ar
from app.services import current_period_explanation as cpe
from app.services import evidence_outcomes as eo
from app.services import financial_thesis_foundation as foundation
from app.services import public_document_ingestion as pdi
from app.services.evidence_references import admit_evidence

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'tests' / 'data'
FACTS = json.loads((DATA / 'company_facts_as_reported_retained_runs4_11.json').read_text())
CASES = {
    'BWMX': dict(file='annual_20f_betterware_trimmed_retained_run4.html', cik='1788257', ticker='BWMX', filed='2026-04-30',
                 url='https://www.sec.gov/Archives/edgar/data/1788257/000121390026050248/ea0287740-20f_betterware.htm'),
    'MRX': dict(file='annual_20f_marex_trimmed_retained_run9.html', cik='1997464', ticker='MRX', filed='2026-03-25',
                url='https://www.sec.gov/Archives/edgar/data/1997464/000199746426000018/mar-20251231.htm'),
}
NOW = '2026-11-10T00:00:00+00:00'


@pytest.fixture
def requests_made(monkeypatch):
    calls = []

    def install(case, text=None):
        calls.clear()
        body = text.encode() if text is not None else (DATA / CASES[case]['file']).read_bytes()

        class Response:
            status_code, headers, encoding = 200, {'Content-Type': 'text/html'}, 'utf-8'

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                yield body

            def close(self):
                pass

        def get(url, *args, **kwargs):
            calls.append(url)
            return Response()
        monkeypatch.setattr(pdi.requests, 'get', get)
        return calls
    return install


def fetch(case, calls, **kwargs):
    c = CASES[case]
    options = {**afacts.fetch_options(), 'inline_fact_cik': c['cik']}
    return pdi.fetch_public_document(
        c['url'], publisher='SEC EDGAR', published_at=c['filed'], document_type='20-F', source_type='regulatory_filing',
        source_tier='primary', sec_periodic_limits=True, preserve_sec_business=True, extract_tables=False,
        **{**options, **kwargs})


def document(case, requests_made, text=None):
    calls = requests_made(case, text)
    doc = fetch(case, calls)
    assert len(calls) == 1  # the one fetch the request already makes; this module adds none
    return doc


# --- the single fetch keeps the inline facts and the results window --------------------------------

def test_the_same_fetch_keeps_inline_facts_and_the_results_window(requests_made):
    doc = document('MRX', requests_made)
    assert len(doc.inline_xbrl_facts) == 12 and doc.results_text.startswith('Item 5. Operating and Financial Review')
    assert 'Item 6' not in doc.results_text and 'Net cash from operating activities was $667.5m' in doc.results_text
    assert doc.results_text_start > 0 and doc.document_type == '20-F'


def test_without_the_options_the_document_is_exactly_what_it_was(requests_made):
    calls = requests_made('MRX')
    c = CASES['MRX']
    plain = pdi.fetch_public_document(c['url'], publisher='SEC EDGAR', published_at=c['filed'], document_type='20-F',
                                      source_type='regulatory_filing', source_tier='primary', sec_periodic_limits=True,
                                      preserve_sec_business=True, extract_tables=False, inline_fact_cik=c['cik'],
                                      inline_fact_concepts=afacts.INLINE_CONCEPTS)
    assert plain.inline_xbrl_facts == () and plain.results_text == '' and plain.results_text_start == 0
    assert len(calls) == 1


def test_the_default_parser_still_reads_only_us_gaap_usd_and_the_opt_in_reads_ifrs(requests_made):
    text = (DATA / CASES['BWMX']['file']).read_text()
    concepts = afacts.INLINE_CONCEPTS
    assert inline.parse_inline_observations(text, cik='1788257', concepts=concepts) == ()
    assert inline.parse_inline_observations(text, cik='1788257', concepts=concepts, taxonomies=('ifrs-full',)) == ()
    assert inline.parse_inline_observations(text, cik='1788257', concepts=concepts, taxonomies=('ifrs-full',), currencies=('USD',)) == ()
    observations = inline.parse_inline_observations(text, cik='1788257', concepts=concepts, taxonomies=('ifrs-full',), currencies='*')
    assert len(observations) == 12 and {o['unit'] for o in observations} == {'MXN'}
    assert inline.validated_observation(observations[0], cik='1788257', concepts=concepts) is None  # default rejects it


# --- Betterware: annual comparisons verified before they are shown ---------------------------------

def betterware(requests_made):
    doc = document('BWMX', requests_made)
    return doc, *afacts.extra_items(doc, 'BWMX', '1788257')


def test_betterware_gets_fy2025_comparisons_in_mxn_from_its_own_filing(requests_made):
    doc, comparisons, explanations, withheld = betterware(requests_made)
    assert len(comparisons) == 3 and explanations == []
    by = {ar.CORE and afacts.metric_name(i): i for i in comparisons}
    assert set(by) == {'revenue', 'net income', 'operating cash flow'}
    revenue = by['revenue']
    assert [c['raw_value'] for c in revenue.verified_claims] == [14243015000, 14100758000]
    assert 'increased 1.0% to 14.2B MXN' in revenue.summary and 'Reported in MXN under IFRS' in revenue.summary
    assert {w['metric'] for w in withheld} == {'operating income'}
    assert all(i.reporting_period_end == '2025-12-31' and i.timestamp == '2026-04-30' for i in comparisons)


def test_each_claim_is_bound_to_its_exact_fact_and_context_in_the_document(requests_made):
    doc, comparisons, *_ = betterware(requests_made)
    for item in comparisons:
        for claim in item.verified_claims:
            proof, ref = claim['inline_binding'], claim['document_ref']
            assert proof['document_url'] == doc.final_url == ref['url'] and proof['content_hash'] == doc.content_hash == ref['content_hash']
            assert ref['reference_id'].endswith(f":{proof['content_hash']}:{proof['fact_id']}") and ref['quote'] == proof['literal']
            assert ref['section'] == f"Inline XBRL context {proof['context_id']}"
            assert proof['accession'] == '0001213900-26-050248' and proof['form'] == '20-F'
            # concept, period, currency, scale, sign and basis, each checked against the filing's own markup
            assert claim['taxonomy'] == 'ifrs-full' and claim['reporting_basis'] == 'IFRS' and claim['unit'] == claim['currency'] == 'MXN'
            assert proof['scale'] == 3 and proof['sign'] == ''
            literal = Decimal(proof['literal'].replace(',', ''))
            assert Decimal(str(claim['raw_value'])) == literal * Decimal(10) ** proof['scale']
            markup = (DATA / CASES['BWMX']['file']).read_text()
            fact = re.search(rf'<ix:nonFraction[^>]*\bid="{proof["fact_id"]}"[^>]*>', markup).group(0)
            assert f'name="ifrs-full:{proof["concept"]}"' in fact and f'contextRef="{proof["context_id"]}"' in fact
            assert 'scale="3"' in fact and 'sign=' not in fact and 'unitRef="mxn"' in fact


def test_betterware_filing_figures_agree_with_the_retained_company_facts_where_they_overlap(requests_made):
    _, comparisons, *_ = betterware(requests_made)
    facts = FACTS['BWMX']['facts']['ifrs-full']
    for item in comparisons:
        for claim in item.verified_claims:
            if claim['period_end'] != '2024-12-31':
                continue
            rows = [o for o in facts[claim['metric'].split(':')[1]]['units']['MXN'] if o['end'] == '2024-12-31' and o['val'] == claim['raw_value']]
            assert rows, claim['metric']  # the prior-year figure in the filing equals a retained Company Facts observation


@pytest.mark.parametrize('field,value', [('scale', 6), ('sign', '-'), ('unit', 'USD'), ('literal', '14,243,016'),
                                         ('context_id', 'c5'), ('fact_id', 'ixv-1'), ('content_hash', 'f' * 64),
                                         ('accession', '0000000000-00-000000'), ('concept', 'ProfitLoss'),
                                         ('start', '2025-02-01'), ('concept_namespace', 'http://fasb.org/us-gaap/2025')])
def test_any_altered_proof_makes_the_comparison_unrebuildable(requests_made, field, value):
    _, comparisons, *_ = betterware(requests_made)
    item = next(i for i in comparisons if afacts.metric_name(i) == 'revenue')
    assert ar.rebuild_as_reported(item, ticker='BWMX', cik='1788257', name='revenue') == item
    forged = item.model_copy(deep=True)
    forged.verified_claims[0]['inline_binding'][field] = value
    assert ar.rebuild_as_reported(forged, ticker='BWMX', cik='1788257', name='revenue') is None


@pytest.mark.parametrize('field,value', [('raw_value', 14243016000), ('unit', 'USD'), ('currency', 'USD'), ('taxonomy', 'us-gaap'),
                                         ('reporting_basis', 'US-GAAP'), ('period_end', '2025-11-30'), ('scope', 'segment'),
                                         ('value_text', '14,243,015,001 MXN')])
def test_altered_claim_fields_are_rejected_too(requests_made, field, value):
    _, comparisons, *_ = betterware(requests_made)
    item = next(i for i in comparisons if afacts.metric_name(i) == 'revenue')
    forged = item.model_copy(deep=True)
    forged.verified_claims[0][field] = value
    assert ar.rebuild_as_reported(forged, ticker='BWMX', cik='1788257', name='revenue') is None


def records_with(requests_made, change):
    doc = document('BWMX', requests_made)
    records = afacts.records_from_document(doc, '1788257')
    return [change(r) for r in records]


def test_a_negative_sign_a_second_currency_and_a_short_period_are_not_compared(requests_made):
    base = afacts.records_from_document(document('BWMX', requests_made), '1788257')
    revenue_now = next(r for r in base if r.concept == 'Revenue' and r.end == '2025-12-31')
    revenue_rows = [r for r in base if r.concept in ('Revenue', 'RevenueFromContractsWithCustomers') and r.end == '2025-12-31']
    negative = [replace(r, value=-r.value) if r in revenue_rows else r for r in base]
    items, withheld = ar.build_comparisons(negative, ticker='BWMX', cik='1788257')
    assert 'revenue' not in {afacts.metric_name(i) for i in items}
    assert next(w for w in withheld if w['metric'] == 'revenue')['reason'] == 'non_positive_value'
    other_currency = [replace(r, unit='USD') if r in revenue_rows else r for r in base]
    items, withheld = ar.build_comparisons(other_currency, ticker='BWMX', cik='1788257')
    assert 'revenue' not in {afacts.metric_name(i) for i in items}
    short = [replace(r, start='2025-07-01') if r in revenue_rows else r for r in base]
    items, withheld = ar.build_comparisons(short, ticker='BWMX', cik='1788257')
    # Revenue's latest valid annual period would now be FY2024, older than the other measures: withheld, not mixed.
    assert 'revenue' not in {afacts.metric_name(i) for i in items}
    assert next(w for w in withheld if w['metric'] == 'revenue')['reason'] == 'older_period_than_other_measures'
    assert {i.reporting_period_end for i in items} == {'2025-12-31'}


def test_a_record_whose_markup_names_another_taxonomy_is_not_bound(requests_made):
    base = afacts.records_from_document(document('BWMX', requests_made), '1788257')
    record = next(r for r in base if r.concept == 'Revenue')
    assert ar._bind(record, ticker='BWMX', expected_cik='1788257') is not None
    claimed_gaap = replace(record, taxonomy='us-gaap')  # claims US-GAAP while its own markup names ifrs-full
    assert ar._bind(claimed_gaap, ticker='BWMX', expected_cik='1788257') is None
    forged_proof = {**record.inline_binding, 'concept_namespace': 'http://fasb.org/us-gaap/2025'}
    assert ar._bind(replace(record, inline_binding=forged_proof), ticker='BWMX', expected_cik='1788257') is None


def test_a_filing_that_is_not_a_20f_or_not_from_sec_yields_nothing(requests_made):
    doc = document('BWMX', requests_made)
    assert afacts.records_from_document(replace(doc, document_type='10-K'), '1788257') == []
    assert afacts.records_from_document(replace(doc, publisher='Someone'), '1788257') == []
    assert afacts.records_from_document(replace(doc, source_tier='unverified'), '1788257') == []
    assert afacts.records_from_document(doc, '999') == []
    future = replace(doc, published_at='2099-01-01')
    assert afacts.records_from_document(future, '1788257') == []


# --- the existing freshness rule applies to the filing-derived facts --------------------------------

def test_current_filing_facts_are_admitted_and_shown_and_old_ones_are_withheld_by_the_same_rule(requests_made, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    _, comparisons, *_ = betterware(requests_made)
    admitted, refs, _ = admit_evidence(comparisons, evaluated_at=NOW)
    assert {r['freshness_status'] for r in refs} == {'current'}
    shown = foundation.build_financial_foundation('BWMX', admitted, refs, expected_cik='1788257')
    assert shown is not None and len(shown['claims']) == 3
    assert all('MXN' in c['claim'] for c in shown['claims'])
    _, fresh_comparisons, *_ = betterware(requests_made)  # admission annotates items, so evaluate new ones
    later, refs, _ = admit_evidence(fresh_comparisons, evaluated_at='2029-06-01T00:00:00+00:00')
    assert {r['freshness_status'] for r in refs} == {'stale'}
    assert foundation.build_financial_foundation('BWMX', later, refs, expected_cik='1788257') is None


# --- Company Facts and the filing: conflicts are withheld and stated --------------------------------

def company_items(case='BWMX'):
    records = __import__('app.providers.sec_client', fromlist=['x']).as_reported_records_from_facts(
        FACTS[case], str(FACTS[case]['cik']), specs=ar.requested_specs())
    return ar.build_comparisons(records, ticker=case, cik=str(FACTS[case]['cik']))[0]


def reconcile_with(requests_made, facts):
    doc = document('BWMX', requests_made)
    comparisons, _, _ = afacts.extra_items(doc, 'BWMX', '1788257')
    scratch = afacts.Scratch()
    scratch.set(facts)
    results = {'thesis_disclosures': list(comparisons), 'sec_metrics': company_items()}
    return afacts.reconcile(results, scratch), results, comparisons


def test_agreement_keeps_the_newer_filing_period_and_drops_the_older_comparisons(requests_made):
    withheld, results, comparisons = reconcile_with(requests_made, FACTS['BWMX'])
    assert withheld == []
    assert results['sec_metrics'] == []  # the FY2024 Company Facts comparisons are superseded by FY2025 from the filing
    assert {afacts.metric_name(i) for i in results['thesis_disclosures']} == {'revenue', 'net income', 'operating cash flow'}


def test_disagreement_for_the_same_period_and_basis_withholds_the_measure_and_states_the_conflict(requests_made):
    changed = copy.deepcopy(FACTS['BWMX'])
    rows = changed['facts']['ifrs-full']['Revenue']['units']['MXN']
    for row in rows:
        if row['end'] == '2024-12-31':
            row['val'] += 1
    withheld, results, _ = reconcile_with(requests_made, changed)
    assert len(withheld) == 1 and withheld[0]['metric'] == 'revenue' and withheld[0]['reason'] == 'filing_company_facts_conflict'
    conflict = withheld[0]['conflicts'][0]
    assert conflict['period_end'] == '2024-12-31' and conflict['unit'] == 'MXN' and conflict['reporting_basis'] == 'IFRS'
    assert conflict['filing_value'] == 14100758000 and conflict['company_facts_value'] == 14100758001
    assert 'revenue' not in {afacts.metric_name(i) for i in results['thesis_disclosures'] + results['sec_metrics']}
    assert {afacts.metric_name(i) for i in results['thesis_disclosures']} == {'net income', 'operating cash flow'}


def test_a_conflict_also_drops_the_filings_explanations_and_reaches_the_outcome_record(requests_made):
    doc = document('MRX', requests_made)
    comparisons, explanations, _ = afacts.extra_items(doc, 'MRX', '1997464')
    changed = copy.deepcopy(FACTS['MRX'])
    for row in changed['facts']['ifrs-full']['Revenue']['units']['USD']:
        if row['end'] == '2024-12-31':
            row['val'] += 1
    scratch = afacts.Scratch()
    scratch.set(changed)
    results = {'thesis_disclosures': comparisons + explanations, 'sec_metrics': []}
    withheld = afacts.reconcile(results, scratch)
    assert withheld[0]['metric'] == 'revenue' and results['thesis_disclosures']
    assert not [i for i in results['thesis_disclosures'] if i.period_explanations]
    notes = eo.OutcomeNotes()
    notes.add_as_reported_withheld(withheld)
    answer = {'status': 'partial', 'claims': [], 'unanswered_parts': ['investment thesis and its supporting/invalidation mechanisms']}
    row = next(r for r in eo.build_evidence_outcomes(answer, notes=notes) if r['need'] == 'reported_financials')
    assert row['reason'] == 'as_reported_comparison_withheld' and 'filing company facts conflict' in row['user_text']


def test_a_period_absent_from_company_facts_is_not_a_conflict(requests_made):
    withheld, results, _ = reconcile_with(requests_made, {'cik': 1788257, 'facts': {}})
    assert withheld == [] and len(results['thesis_disclosures']) == 3


def test_equal_periods_keep_the_existing_comparison_and_drop_the_duplicate(requests_made):
    doc = document('MRX', requests_made)
    comparisons, _, _ = afacts.extra_items(doc, 'MRX', '1997464')
    existing = company_items('MRX')
    scratch = afacts.Scratch()
    scratch.set(FACTS['MRX'])
    results = {'thesis_disclosures': list(comparisons), 'sec_metrics': list(existing)}
    assert afacts.reconcile(results, scratch) == []
    assert results['sec_metrics'] == existing and not [i for i in results['thesis_disclosures'] if afacts.is_filing_item(i)]


# --- Marex: management's stated explanations, kept apart from interpretation -----------------------

def marex(requests_made):
    doc = document('MRX', requests_made)
    comparisons, explanations, withheld = afacts.extra_items(doc, 'MRX', '1997464')
    return doc, comparisons, explanations, withheld


def test_marex_reconciles_to_its_filing_and_company_facts(requests_made):
    _, comparisons, _, withheld = marex(requests_made)
    assert {afacts.metric_name(i) for i in comparisons} == {'revenue', 'net income', 'operating cash flow'}
    assert [w['metric'] for w in withheld] == ['operating income']
    facts = FACTS['MRX']['facts']['ifrs-full']
    for item in comparisons:
        for claim in item.verified_claims:
            assert any(o['end'] == claim['period_end'] and o['val'] == claim['raw_value']
                       for o in facts[claim['metric'].split(':')[1]]['units']['USD'])


def test_the_operating_cash_flow_cause_is_management_stated_and_quoted_exactly(requests_made):
    doc, _, explanations, _ = marex(requests_made)
    assert len(explanations) == 1
    value = explanations[0].period_explanations[0]
    statement = next(s for s in value['statements'] if s['metric'] == 'operating cash flow')
    assert statement['basis'] == 'stated current and prior levels'
    assert statement['quote'] in doc.results_text and statement['cause_quote'] in doc.results_text
    assert statement['cause_quote'].startswith('The decrease was due primarily to an increase in net stock borrowing and lending')
    text = explanations[0].summary
    assert text.count('Management stated') == 2 and 'not independently established causes' in text


def test_a_movement_management_does_not_explain_is_said_to_be_unexplained(requests_made):
    _, _, explanations, _ = marex(requests_made)
    summary = explanations[0].summary
    assert 'For revenue the quoted statement gives the change without a stated cause; its driver remains unverified.' in summary
    assert 'No management statement was bound for profit for the year; its driver remains unverified.' in summary
    # The revenue statement is shown verbatim; its contributing factors are management's words, not a bound cause.
    assert 'with growth across all operating segments and contributions from acquisitions' in summary


def test_when_management_gives_no_explanation_at_all_every_metric_is_said_to_be_unexplained(requests_made):
    text = (DATA / CASES['MRX']['file']).read_text()
    text = text.replace('The decrease was due primarily to an increase in net stock borrowing and lending and trade and other payables, '
                        'offset by an increase in equity instruments, debt securities and net repurchase and reverse repurchase '
                        'agreements.', 'The figures are shown in the table above.')
    doc = document('MRX', requests_made, text=text)
    _, explanations, _ = afacts.extra_items(doc, 'MRX', '1997464')
    summary = explanations[0].summary
    assert 'No management statement was bound for profit for the year' in summary
    assert 'operating cash flow' in summary.split('For revenue')[1] or 'operating cash flow' in summary
    assert 'The decrease was due primarily' not in summary


def test_the_explanation_rebuilds_and_every_tamper_is_rejected(requests_made):
    doc, comparisons, explanations, _ = marex(requests_made)
    item = explanations[0]
    assert cpe.bound_current_period_explanation(item, ticker='MRX', cik='1997464') is not None
    for mutate in (lambda v: v['statements'][1].update(cause_quote='The decrease was due primarily to growth.'),
                   lambda v: v['statements'][1].update(quote=v['statements'][1]['quote'].replace('$667.5m', '$668.5m')),
                   lambda v: v['metrics']['operating cash flow'].update(current=1),
                   lambda v: v.update(level_cause=False),
                   lambda v: v['statements'].pop(1)):
        forged = item.model_copy(deep=True)
        mutate(forged.period_explanations[0])
        assert cpe.bound_current_period_explanation(forged, ticker='MRX', cik='1997464') is None


def test_a_non_us_dollar_filing_gets_no_explanations_rather_than_mislabelled_ones(requests_made):
    doc = document('BWMX', requests_made)
    comparisons, _, _ = afacts.filing_comparisons(doc, 'BWMX', '1788257') + ([],)
    assert cpe.extract_annual_foreign_explanation(doc, comparisons, ticker='BWMX', cik='1788257') == []
    assert 'primarily driven by higher net revenue generated by Jafra' in doc.results_text  # management did explain it, in MXN


def test_explanations_are_withheld_when_any_comparison_is_not_in_us_dollars(requests_made):
    doc, comparisons, *_ = marex(requests_made)
    assert cpe.extract_annual_foreign_explanation(doc, comparisons, ticker='MRX', cik='1997464')
    forged = [i.model_copy(deep=True) for i in comparisons]
    for claim in forged[0].verified_claims:
        claim['unit'] = claim['currency'] = 'MXN'
    assert cpe.extract_annual_foreign_explanation(doc, forged, ticker='MRX', cik='1997464') == []


def test_only_a_20f_with_a_results_window_is_explained(requests_made):
    doc, comparisons, *_ = marex(requests_made)
    assert cpe.extract_annual_foreign_explanation(replace(doc, document_type='10-K'), comparisons, ticker='MRX', cik='1997464') == []
    assert cpe.extract_annual_foreign_explanation(replace(doc, results_text=''), comparisons, ticker='MRX', cik='1997464') == []


def test_the_existing_engine_is_unchanged_unless_the_level_cause_option_is_given(requests_made):
    doc, comparisons, *_ = marex(requests_made)
    observations = []
    off = cpe.explanation_value(doc.results_text, observations, comparisons, ticker='MRX', document_type='20-F',
                                filed_at='2026-03-25')
    assert 'level_cause' not in off and not [s for s in off['statements'] if s['metric'] == 'operating cash flow']
    assert cpe._amounts('revenue was $5 million and $1.5 billion and $2 thousand') == [
        (Decimal('5000000'), Decimal('500000')), (Decimal('1500000000'), Decimal('50000000')), (Decimal('2000'), Decimal('500'))]
    assert cpe._amounts('$ 429.4 m') == [(Decimal('429400000.0'), Decimal('50000'))]


# --- flags, requests and wiring ---------------------------------------------------------------------

def test_both_flags_are_default_off_and_both_are_required(monkeypatch):
    assert Settings.model_fields['annual_filing_facts_enabled'].default is False
    assert Settings.model_fields['as_reported_financials_enabled'].default is False
    for filing, as_reported, expected in ((False, False, False), (True, False, False), (False, True, False), (True, True, True)):
        monkeypatch.setattr(settings, 'annual_filing_facts_enabled', filing, raising=False)
        monkeypatch.setattr(settings, 'as_reported_financials_enabled', as_reported, raising=False)
        assert afacts.enabled() is expected


def test_no_pilot_profile_sets_the_flag_and_the_module_has_no_network_import():
    for path in (ROOT / 'validation').glob('*.py'):
        assert 'annual_filing' not in path.read_text(), path.name
    source = (ROOT / 'app/services/annual_filing_facts.py').read_text()
    for forbidden in ('import requests', 'urllib', 'import socket', 'httpx', 'fetch_public_document', 'fetch_recent'):
        assert forbidden not in source, forbidden
    cohort = '|'.join(['E' + 'RO', 'MG' + 'RT', 'MY' + 'GN', 'SU' + 'PV', 'FMS' + 'TW', 'FM' + 'ST', 'OP' + 'TT'])
    pattern = re.compile(r'\b(?:' + cohort + r')\b')
    for target in (ROOT / 'app/services/annual_filing_facts.py', *DATA.glob('annual_20f_*_trimmed_*.html')):
        assert not pattern.search(target.read_text()), target.name


def test_the_outcome_record_says_the_20f_was_read_and_why_explanations_were_not_attempted():
    answer = {'status': 'partial', 'claims': [], 'unanswered_parts': ['investment thesis and its supporting/invalidation mechanisms']}
    notes = eo.OutcomeNotes()
    notes.add_annual_filing_read({'form': '20-F', 'currencies': ['USD']})
    rows = {r['need']: r for r in eo.build_evidence_outcomes(answer, notes=notes)}
    assert (rows['change_drivers']['state'], rows['change_drivers']['reason'], rows['change_drivers']['tried']) == (
        'unsupported', 'selection_rules_not_met', True)
    assert 'was read' in rows['liquidity_going_concern']['user_text'] and 'does not read' not in rows['liquidity_going_concern']['user_text']
    notes = eo.OutcomeNotes()
    notes.add_annual_filing_read({'form': '20-F', 'currencies': ['MXN']})
    row = next(r for r in eo.build_evidence_outcomes(answer, notes=notes) if r['need'] == 'change_drivers')
    assert (row['reason'], row['tried']) == ('non_usd_reporting', True) and 'US dollar filings' in row['user_text']
    plain = eo.OutcomeNotes()
    plain.add_selected('thesis_disclosures', '20-F')
    plain.mark_completed('thesis_disclosures')
    plain.add_listed(['20-F', '6-K'])
    row = next(r for r in eo.build_evidence_outcomes(answer, notes=plain) if r['need'] == 'change_drivers')
    assert row['reason'] == 'annual_form_not_read' and row['tried'] is False  # unchanged without the new path


def test_a_late_filing_note_cannot_change_an_abandoned_outcome():
    notes = eo.OutcomeNotes()
    notes.mark_abandoned(['thesis_disclosures'])
    eo.bind_outcome_notes(lambda: eo.note_annual_filing_read('20-F', {'USD'}), notes, 'thesis_disclosures')()
    assert notes.annual_filing_read is None
