"""IFRS and as-reported-currency annual comparisons (default off, offline, retained SEC facts only).

Facts are retained Company Facts bodies for Fortis (CAD, us-gaap), BP and Marex (USD, ifrs-full) and Betterware
(MXN, ifrs-full) from pilot Runs 4, 8, 9 and 11, trimmed to the concepts used (tests/data). Figures are checked
against those same bodies by an independent lookup, never through the code under test. Nothing is converted.
"""
import copy
import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.config import Settings, settings
from app.integrity import sec_metric_evidence as sme
from app.providers import sec_client
from app.providers.sec_client import SecFactRecord
from app.services import as_reported_financials as ar
from app.services import evidence_outcomes as eo
from app.services import financial_thesis_foundation as foundation
from app.services import verified_sec_metric_service as service

ROOT = Path(__file__).resolve().parent.parent
FACTS = json.loads((ROOT / 'tests/data/company_facts_as_reported_retained_runs4_11.json').read_text())
TICKER = {'BP': 'BP', 'MRX': 'MRX', 'BWMX': 'BWMX', 'FORFF': 'FTS'}


class Reply:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def facts_get(monkeypatch):
    calls = []

    def install(key):
        def get(*args, **kwargs):
            calls.append(args)
            return Reply(FACTS[key])
        monkeypatch.setattr(sec_client.requests, 'get', get)
        return calls
    return install


def build(key, facts_get):
    facts_get(key)
    cik = str(FACTS[key]['cik'])
    return ar.fetch_as_reported_evidence(TICKER[key], cik)


def observation(key, taxonomy, concept, unit, end, value, accn):
    rows = FACTS[key]['facts'][taxonomy][concept]['units'][unit]
    return [o for o in rows if o['end'] == end and o['val'] == value and o['accn'] == accn]


def reconcile(key, evidence):
    """Every bound fact must equal a retained SEC observation: concept, unit, period, accession, form, filed, value."""
    checked = 0
    for item in evidence:
        for claim in item.verified_claims:
            taxonomy, concept = claim['metric'].split(':')
            accn = re.search(r':(\d{10}-\d{2}-\d{6}):', claim['document_ref']['reference_id']).group(1)
            rows = [o for o in observation(key, taxonomy, concept, claim['unit'], claim['period_end'], claim['raw_value'], accn)
                    if o['form'] == claim['source'] and o.get('start') == claim['period_start']
                    and o['filed'] == claim['document_ref']['published_at']]
            assert rows, (key, claim['metric'], claim['period_end'])
            checked += 1
    return checked


# --- the four retained issuers ----------------------------------------------------------------------

@pytest.mark.parametrize('key,expected,currency,basis', [
    ('BP', {'revenue', 'operating income', 'net income', 'operating cash flow'}, 'USD', 'IFRS'),
    ('MRX', {'revenue', 'net income', 'operating cash flow'}, 'USD', 'IFRS'),
    ('BWMX', {'revenue', 'net income', 'operating cash flow'}, 'MXN', 'IFRS'),
    ('FORFF', {'revenue', 'operating income', 'net income', 'operating cash flow'}, 'CAD', 'US-GAAP')])
def test_each_retained_issuer_yields_its_annual_comparisons_in_its_own_currency(facts_get, key, expected, currency, basis):
    evidence, withheld = build(key, facts_get)
    assert len(evidence) == len(expected)
    for item in evidence:
        for claim in item.verified_claims:
            assert claim['unit'] == claim['currency'] == currency
            assert claim['taxonomy'] in ar.BASES and claim['reporting_basis'] == basis
            assert claim['scope'] == 'consolidated' and claim['provenance'] == 'reported'
        assert 'no currency conversion was applied' in item.summary and f'Reported in {currency} under {basis}' in item.summary
        assert item.source_tier == 'primary' and item.claim_type == 'reported_fact'
    assert {w['metric'] for w in withheld} == set(ar.CORE) - expected
    assert all(w['reason'] == 'concept_not_reported' for w in withheld)
    assert reconcile(key, evidence) == 2 * len(expected)


def test_marex_and_betterware_say_why_operating_income_is_missing(facts_get):
    for key in ('MRX', 'BWMX'):
        _, withheld = build(key, facts_get)
        assert withheld == [{'metric': 'operating income', 'reason': 'concept_not_reported',
                             'concepts': ['ProfitLossFromOperatingActivities'], 'basis': 'IFRS',
                             'currency': 'USD' if key == 'MRX' else 'MXN'}]


def test_betterware_ignores_its_usd_translations_and_never_converts(facts_get):
    evidence, _ = build('BWMX', facts_get)
    text = ' '.join(item.summary for item in evidence)
    assert 'MXN' in text and '$' not in text and 'USD' not in text
    usd_rows = FACTS['BWMX']['facts']['ifrs-full']['RevenueFromContractsWithCustomers']['units']['USD']
    assert usd_rows  # the retained body does hold USD convenience figures for older periods
    assert all(claim['unit'] == 'MXN' for item in evidence for claim in item.verified_claims)


def test_bp_revenue_figures_equal_the_retained_total_revenue_concept_not_the_narrower_one(facts_get):
    evidence, _ = build('BP', facts_get)
    revenue = next(item for item in evidence if item.verified_claims[0]['metric'].endswith(':Revenue'))
    assert [c['raw_value'] for c in revenue.verified_claims] == [192549000000, 194629000000]
    assert 'RevenueFromContractsWithCustomers' not in json.dumps([i.verified_claims for i in evidence])


def test_fortis_uses_its_own_concepts_and_the_40f_annual_forms(facts_get):
    evidence, _ = build('FORFF', facts_get)
    assert {c['source'] for item in evidence for c in item.verified_claims} == {'40-F'}
    revenue = evidence[0]
    assert revenue.verified_claims[0]['metric'] == 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
    assert [c['raw_value'] for c in revenue.verified_claims] == [11900000000, 11243000000]
    assert revenue.verified_claims[0]['period'] == 'FY2025'


# --- compatible concepts, periods, bases and currencies only; ambiguity is withheld with a reason -------

def rec(**kw):
    base = dict(cik='1', taxonomy='ifrs-full', concept='Revenue', label='Revenue', unit='USD', value=100, start='2024-01-01',
                end='2024-12-31', filed='2025-03-01', form='20-F', accession='0000000001-25-000001', filing_url=None)
    base.update(kw)
    base['filing_url'] = (f"https://www.sec.gov/Archives/edgar/data/{int(base['cik'])}/"
                          f"{base['accession'].replace('-', '')}/{base['accession']}-index.htm")
    return SecFactRecord(**base)


def pair(**over):
    cur = rec(start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=120)
    prior = rec(**over)
    anchor = rec(concept='Assets', start=None, end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=999)
    return [cur, prior, anchor]


def evidence_of(records):
    return ar.build_comparisons(records, ticker='TST', cik='1')


def reason_for(records, metric='revenue'):
    return next(w['reason'] for w in evidence_of(records)[1] if w['metric'] == metric)


def test_a_clean_pair_builds_and_the_percentage_is_exact():
    evidence, withheld = evidence_of(pair())
    assert len(evidence) == 1 and 'increased 20.0%' in evidence[0].summary
    assert {w['metric'] for w in withheld} == {'operating income', 'net income', 'operating cash flow'}


@pytest.mark.parametrize('over,reason', [
    ({'unit': 'EUR'}, 'no_comparable_prior_year_period'),  # a different currency is never compared
    ({'concept': 'RevenueFromContractsWithCustomers'}, 'no_comparable_prior_year_period'),  # nor a different concept
    ({'taxonomy': 'us-gaap'}, 'no_comparable_prior_year_period'),  # nor another taxonomy
    ({'start': '2024-07-01'}, 'no_comparable_prior_year_period'),  # a half-year duration is not comparable
    ({'end': '2023-12-31', 'start': '2023-01-01'}, 'no_comparable_prior_year_period'),  # two years back
    ({'form': '6-K'}, 'no_comparable_prior_year_period'),  # interim filings are not compared
    ({'value': 0}, 'prior_value_zero'),
    ({'value': -5}, 'non_positive_value'),
])
def test_an_incompatible_or_unusable_prior_is_withheld_with_its_reason(over, reason):
    assert reason_for(pair(**over)) == reason


def test_a_non_positive_current_value_is_withheld_not_turned_into_a_percentage():
    records = pair()
    records[0] = rec(start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=-1)
    assert reason_for(records) == 'non_positive_value'


def test_conflicting_same_filing_observations_are_withheld_as_ambiguous():
    records = pair()
    records.append(rec(start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000002', value=121))
    assert reason_for(records) == 'ambiguous_current_observation'
    records = pair()
    records.append(rec(filed='2025-03-01', accession='0000000001-25-000002', value=101))
    assert reason_for(records) == 'ambiguous_prior_observation'


def test_a_restatement_in_a_later_filing_replaces_the_earlier_figure():
    records = pair()
    records.append(rec(filed='2026-03-01', accession='0000000001-26-000001', value=110))  # prior restated upward
    evidence, _ = evidence_of(records)
    assert 'increased 9.1%' in evidence[0].summary and evidence[0].verified_claims[1]['raw_value'] == 110


def test_two_equally_recent_bases_withhold_everything():
    records = pair() + [rec(taxonomy='us-gaap', concept='Assets', unit='CAD', start=None, end='2025-12-31', filed='2026-03-01',
                            accession='0000000001-26-000001', value=1)]
    evidence, withheld = evidence_of(records)
    assert evidence == [] and withheld == [{'metric': 'all', 'reason': 'ambiguous_basis_or_currency', 'concepts': []}]


def test_a_newer_basis_wins_over_older_translated_figures():
    records = pair() + [rec(unit='GBP', concept='Assets', start=None, end='2021-12-31', filed='2022-03-01')]
    evidence, _ = evidence_of(records)
    assert len(evidence) == 1 and evidence[0].verified_claims[0]['unit'] == 'USD'


def test_no_annual_facts_is_withheld_as_such():
    assert evidence_of([rec(form='6-K')]) == ([], [{'metric': 'all', 'reason': 'no_annual_facts', 'concepts': []}])
    assert evidence_of([]) == ([], [{'metric': 'all', 'reason': 'no_annual_facts', 'concepts': []}])


def test_a_comparison_far_older_than_the_latest_balance_sheet_is_withheld_as_stale():
    records = [rec(start='2022-01-01', end='2022-12-31', filed='2023-03-01', accession='0000000001-23-000001', value=130),
               rec(start='2021-01-01', end='2021-12-31', filed='2022-03-01', accession='0000000001-22-000001', value=100),
               rec(concept='Assets', start=None, end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=9)]
    assert reason_for(records) == 'stale_relative_to_latest_balance_sheet'


def test_alias_concepts_are_never_joined():
    cur = rec(concept='RevenueFromContractsWithCustomers', start='2025-01-01', end='2025-12-31', filed='2026-03-01',
              accession='0000000001-26-000001', value=80)
    prior = rec(concept='Revenue')  # a different concept in the prior year
    anchor = rec(concept='Assets', start=None, end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=9)
    assert reason_for([cur, prior, anchor]) == 'no_comparable_prior_year_period'


def test_the_as_of_boundary_excludes_later_filings(facts_get):
    facts_get('BP')
    cik = str(FACTS['BP']['cik'])
    evidence, _ = ar.fetch_as_reported_evidence('BP', cik, boundary=date(2025, 6, 30))
    assert all(c['period_end'] <= '2024-12-31' for item in evidence for c in item.verified_claims)


def test_a_pair_is_rejected_directly_when_unit_taxonomy_or_concept_differ():
    cur = rec(start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession='0000000001-26-000001', value=120)
    for over in ({'unit': 'EUR'}, {'taxonomy': 'us-gaap'}, {'concept': 'RevenueFromContractsWithCustomers'}, {'cik': '2'}):
        item, why = ar.evidence_from_pair(cur, rec(**over), ticker='T', expected_cik='1', metric_name='revenue')
        assert item is None and why == 'periods_not_comparable', over


# --- rebuild: the foundation re-derives every comparison from its two bound facts --------------------

def rebuilt(item, name, key='BP'):
    return ar.rebuild_as_reported(item, ticker=TICKER[key], cik=str(FACTS[key]['cik']), name=name)


def test_a_comparison_rebuilds_to_itself_and_every_tamper_is_rejected(facts_get):
    evidence, _ = build('BP', facts_get)
    item = next(i for i in evidence if i.verified_claims[0]['metric'].endswith(':Revenue'))
    assert rebuilt(item, 'revenue') == item
    assert rebuilt(item, 'net income') is None  # wrong measure for these concepts

    def tampered(path, value):
        clone = item.model_copy(deep=True)
        target = clone.verified_claims[0]
        keys = path.split('.')
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
        return clone
    for path, value in [('raw_value', 1), ('unit', 'EUR'), ('currency', 'EUR'), ('taxonomy', 'us-gaap'),
                        ('reporting_basis', 'US-GAAP'), ('metric', 'ifrs-full:Revenue2'), ('scope', 'segment'),
                        ('document_ref.reference_id', 'sec:313807:0000000000-00-000000:ifrs-full:Revenue'),
                        ('value_text', '$1'), ('period_end', '2025-11-30')]:
        assert rebuilt(tampered(path, value), 'revenue') is None, path
    wrong_summary = item.model_copy(update={'summary': item.summary.replace('1.1%', '9.9%')})
    assert rebuilt(wrong_summary, 'revenue') is None
    assert rebuilt(item, 'revenue', key='MRX') is None  # another issuer's CIK
    missing = item.model_copy(deep=True)
    del missing.verified_claims[0]['taxonomy']
    assert rebuilt(missing, 'revenue') is None


# --- the foundation uses them only with the flag on --------------------------------------------------

def foundation_rows(items, key):
    return foundation.build_financial_foundation(TICKER[key], items, None, expected_cik=str(FACTS[key]['cik']))


def test_the_foundation_shows_as_reported_comparisons_only_while_the_flag_is_on(facts_get, monkeypatch):
    evidence, _ = build('BP', facts_get)
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', False, raising=False)
    assert foundation_rows(evidence, 'BP') is None  # flag off: the items are not recognised
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    built = foundation_rows(evidence, 'BP')
    assert built is not None and len(built['claims']) == 4
    assert all('no currency conversion was applied' in row['claim'] for row in built['claims'])
    assert 'USD' in built['inferences'][0]['conditional_test'] or '$' in built['inferences'][0]['conditional_test']


def test_betterware_baselines_are_stated_in_mxn(facts_get, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    evidence, _ = build('BWMX', facts_get)
    built = foundation_rows(evidence, 'BWMX')
    baselines = [i['conditional_test'] for i in built['inferences'] if 'Historical baseline' in i['conditional_test']]
    assert built is not None and baselines and all('MXN' in b for b in baselines)
    assert '$' not in json.dumps(built['inferences'])


def test_comparisons_in_two_currencies_never_form_one_foundation(facts_get, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    evidence, _ = build('FORFF', facts_get)
    bp, _ = build('BP', facts_get)
    assert foundation.build_financial_foundation('FTS', evidence[:2] + bp[:2], None, expected_cik=str(FACTS['FORFF']['cik'])) is not None
    # another issuer's items fail identity and are ignored; only an explicit same-issuer mix reaches the unit guard
    mixed = [evidence[0], evidence[1].model_copy(deep=True)]
    for claim in mixed[1].verified_claims:
        claim['unit'] = claim['currency'] = 'USD'
    assert foundation_rows(mixed, 'FORFF') is None


# --- the service: flag off changes nothing, flag on reads only when the existing path found nothing ---

@pytest.fixture
def service_get(monkeypatch):
    def install(key, ticker):
        calls = []
        monkeypatch.setattr(service, '_load_ticker_cik_map', lambda: {ticker: str(FACTS[key]['cik']).zfill(10)})
        monkeypatch.setattr(service, 'facts_not_applicable', lambda cik: None)

        def get(*args, **kwargs):
            calls.append(args)
            return Reply(FACTS[key])
        monkeypatch.setattr(sec_client.requests, 'get', get)
        return calls
    return install


def test_flag_off_the_service_returns_nothing_for_these_issuers_and_makes_one_request(service_get, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', False, raising=False)
    calls = service_get('BP', 'BP')
    assert service.fetch_verified_metric_evidence('BP', question='What is the investment thesis for BP?') == []
    assert len(calls) == 1


def test_flag_on_the_service_returns_the_comparisons_with_one_extra_request(service_get, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    calls = service_get('BP', 'BP')
    items = service.fetch_verified_metric_evidence('BP', question='What is the investment thesis for BP?')
    assert len(items) == 4 and len(calls) == 2
    assert reconcile('BP', items) == 8


def test_flag_on_does_not_touch_an_issuer_the_existing_path_already_serves(service_get, monkeypatch):
    body = {'cik': 7, 'entityName': 'US-GAAP USD CO', 'facts': {'us-gaap': {}}}

    def entry(concept, rows, label):
        body['facts']['us-gaap'][concept] = {'label': label, 'units': {'USD': rows}}
    ob = lambda start, end, val, filed, accn: {'start': start, 'end': end, 'val': val, 'accn': accn, 'fy': 2025, 'fp': 'FY',
                                                'form': '10-K', 'filed': filed}
    entry('Revenues', [ob('2024-01-01', '2024-12-31', 100, '2025-02-01', '0000000007-25-000001'),
                       ob('2025-01-01', '2025-12-31', 120, '2026-02-01', '0000000007-26-000001')], 'Revenues')
    entry('OperatingIncomeLoss', [ob('2024-01-01', '2024-12-31', 10, '2025-02-01', '0000000007-25-000001'),
                                  ob('2025-01-01', '2025-12-31', 12, '2026-02-01', '0000000007-26-000001')], 'Operating income')
    entry('Assets', [dict(ob(None, '2025-12-31', 50, '2026-02-01', '0000000007-26-000001'), start=None)], 'Assets')
    FACTS['__usd__'] = body
    try:
        monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
        calls = service_get('__usd__', 'USDCO')
        items = service.fetch_verified_metric_evidence('USDCO', question='What is the investment thesis for USDCO?')
        assert items and len(calls) == 1
        assert all('taxonomy' not in claim for item in items for claim in item.verified_claims)
    finally:
        del FACTS['__usd__']


def test_a_failed_second_request_is_noted_and_returns_nothing(service_get, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    service_get('BP', 'BP')
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: (_ for _ in ()).throw(sec_client.requests.ConnectionError('x')))
    notes = eo.OutcomeNotes()
    items = eo.bind_outcome_notes(lambda: service.fetch_verified_metric_evidence('BP', question='x'), notes, 'sec_metrics')()
    assert items == [] and notes.facts_requests and notes.facts_requests[0]['ok'] is False


# --- outcome records say what happened -------------------------------------------------------------

def test_the_outcome_record_names_what_was_withheld_and_what_was_built_but_stale():
    notes = eo.OutcomeNotes()
    notes.add_as_reported_withheld([{'metric': 'operating income', 'reason': 'concept_not_reported'}],
                                   built=[{'title': 'T1', 'period_end': '2024-12-31'}])
    answer = {'status': 'partial', 'claims': [], 'unanswered_parts': ['investment thesis and its supporting/invalidation mechanisms']}
    row = next(r for r in eo.build_evidence_outcomes(answer, notes=notes, references=[{'id': 'E1', 'title': 'T1', 'freshness_status': 'stale'}])
               if r['need'] == 'reported_financials')
    assert (row['state'], row['reason']) == ('unsupported', 'as_reported_comparison_withheld')
    assert 'older than the freshness window' in row['user_text'] and 'operating income (concept not reported)' in row['user_text']
    assert row['detail']['stale_references'] == ['E1']
    plain = eo.OutcomeNotes()
    plain.add_as_reported_withheld([{'metric': 'revenue', 'reason': 'no_comparable_prior_year_period'}])
    row = next(r for r in eo.build_evidence_outcomes(answer, notes=plain) if r['need'] == 'reported_financials')
    assert 'no comparable prior year period' in row['user_text'] and 'freshness' not in row['user_text']


def test_a_late_as_reported_note_cannot_change_an_abandoned_outcome():
    notes = eo.OutcomeNotes()
    notes.mark_abandoned(['sec_metrics'])
    eo.bind_outcome_notes(lambda: eo.note_as_reported_withheld([{'metric': 'revenue', 'reason': 'x'}]), notes, 'sec_metrics')()
    assert notes.as_reported_withheld == []


# --- guards: the rest of the system is unchanged -----------------------------------------------------

def test_the_flag_is_default_off_and_no_pilot_profile_sets_it():
    assert Settings.model_fields['as_reported_financials_enabled'].default is False
    for path in (ROOT / 'validation').glob('*.py'):
        assert 'as_reported' not in path.read_text(), path.name


def test_value_rendering_of_existing_units_is_unchanged_and_other_units_still_raise():
    assert sme._value(1_500_000_000, 'USD') == '$1.5B' and sme._value(2_000_000, 'EUR') == '2M EUR'
    assert sme._value(3, 'shares') == '3 shares' and sme._value(1.5, 'USD/shares') == '$1.50 per share'
    assert sme._value(1_500_000_000, 'CAD') == '1.5B CAD'
    for bad in ('usd', 'CAD/shares', 'USDX', '', 'pure'):
        with pytest.raises(ValueError):
            sme._value(1, bad)


def test_us_gaap_parsing_defaults_are_unchanged():
    body = {'cik': 1, 'facts': {'us-gaap': {'Assets': {'label': 'A', 'units': {'USD': [
        {'end': '2025-12-31', 'val': 5, 'accn': '0000000001-26-000001', 'form': '10-K', 'filed': '2026-02-01'},
        {'end': '2025-12-31', 'val': 6, 'accn': '0000000001-26-000002', 'form': '40-F', 'filed': '2026-02-01'}]}}}}}
    rows = sec_client.parse_company_fact_records(body, concept='Assets', unit='USD')
    assert [(r.taxonomy, r.form) for r in rows] == [('us-gaap', '10-K')]
    both = sec_client.parse_company_fact_records(body, concept='Assets', unit='USD', forms=sec_client.AS_REPORTED_FORMS)
    assert [r.form for r in both] == ['10-K', '40-F']


def test_no_cohort_6_issuer_and_no_conversion_anywhere_in_the_module():
    source = (ROOT / 'app/services/as_reported_financials.py').read_text()
    cohort = '|'.join(['E' + 'RO', 'MG' + 'RT', 'MY' + 'GN', 'SU' + 'PV', 'FMS' + 'TW', 'FM' + 'ST', 'OP' + 'TT'])
    pattern = re.compile(r'\b(?:' + cohort + r')\b')
    for target in (ROOT / 'app/services/as_reported_financials.py', ROOT / 'tests/data/company_facts_as_reported_retained_runs4_11.json'):
        assert not pattern.search(target.read_text()), target.name
    for forbidden in ('exchange_rate', 'fx_rate', 'convert(', 'usd_rate', 'forex', 'requests.', 'urllib'):
        assert forbidden not in source, forbidden
