"""Evidence outcome records: one honest record per evidence need, default off.

Offline only. Facts and filing-list inputs are trimmed copies of response bodies retained from pilot
Runs 4, 5, 8, 9 and 11 (tests/data), passed through the real SEC clients with the network replaced; the
source_answer dictionaries are the shapes the gate produced for those cases in offline replays. What
this establishes: how the retained responses are classified and that nothing is hidden or changed. It
does not establish source ranking, conflict policy or any coverage of unfamiliar companies.
"""
import copy
import json
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.providers import sec_client
from app.services import evidence_outcomes as eo
from app.services.evidence_outcomes import (
    NEEDS, REASONS, STATES, OutcomeNotes, apply_evidence_outcomes, bind_outcome_notes,
    build_evidence_outcomes, explain_part, part_need,
)
from app.services.source_answer import evidence_gaps
from app.services.sec_registration_only import registration_only_evidence

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'tests' / 'data'
FACTS = json.loads((DATA / 'company_facts_trimmed_retained_runs4_11.json').read_text())
SUBMISSIONS = json.loads((DATA / 'sec_submissions_operating_retained_runs8_11.json').read_text())
VBREY = json.loads((DATA / 'sec_submissions_registration_only_retained_run10.json').read_text())
IFCNF = json.loads((DATA / 'sec_submissions_registration_only_blank_sic_retained_run11.json').read_text())
CONCEPTS = ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'OperatingIncomeLoss',
            'NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities')
CONCEPT_UNITS = tuple((concept, 'USD') for concept in CONCEPTS)
THESIS = 'investment thesis and its supporting/invalidation mechanisms'


class Thesis:
    def __init__(self, text='Original answer.'):
        self.direct_answer = text
        self.conclusion = text


class Reply:
    def __init__(self, body=None, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = sec_client.requests.HTTPError(f'{self.status_code} error')
            error.response = self
            raise error

    def json(self):
        return self._body


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError('network used')

    monkeypatch.setattr(sec_client.requests, 'get', refuse)
    return calls


def facts_through_client(monkeypatch, label=None, *, reply=None, error=None):
    """Run the real facts client against a trimmed retained body (or a failure), with notes bound."""
    body = FACTS[label] if label else None
    cik = str(body['cik']) if body else '1234567'
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: _respond(body, reply, error))
    notes = OutcomeNotes()
    run = bind_outcome_notes(lambda: sec_client.get_company_fact_records_for_concept_units(
        cik, concept_units=CONCEPT_UNITS), notes)
    return run(), notes


def _respond(body, reply, error):
    if error is not None:
        raise error
    return reply if reply is not None else Reply(body)


def with_forms(notes, key):
    notes.add_listed(SUBMISSIONS[key]['filings']['recent']['form'])
    return notes


def thesis_answer(**extra):
    return {'status': 'insufficient_claim_evidence', 'reason': 'x', 'claims': [],
            'unanswered_parts': [THESIS], **extra}


def by_need(records):
    return {row['need']: row for row in records}


def claim(kind, reference='E1', text='A claim.'):
    return {'claim': text, 'reference_id': reference, 'claim_kind': kind}


def ref(reference='E1', freshness='current', end='2026-06-30'):
    return {'id': reference, 'freshness_status': freshness, 'reporting_period_end': end}


# --- 3 FORFF: financials unsupported (CAD), nothing read, never "no disclosure qualified" -------------

def test_forff_core_says_the_data_is_cad_and_that_no_filing_was_read(monkeypatch):
    records, notes = facts_through_client(monkeypatch, 'FORFF (Run 11, us-gaap, CAD)')
    assert records == []  # the client's own result is unchanged: no USD figures
    with_forms(notes, 'FORFF (40-F, XBRL-flagged)')
    rows = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))
    money = rows['reported_financials']
    assert (money['state'], money['reason']) == ('unsupported', 'non_usd_reporting')
    assert money['detail']['currencies'] == ['CAD'] and money['tried'] is True
    for need in ('change_drivers', 'business_description', 'risk_disclosures', 'liquidity_going_concern'):
        assert (rows[need]['state'], rows[need]['reason'], rows[need]['tried']) == (
            'unsupported', 'annual_form_not_read', False), need
        assert 'No filing was read' in rows[need]['user_text']
        assert 'qualified' not in rows[need]['user_text']


FORFF_OLD_TEXT = ('This run did not establish a source-supported investment thesis, its supporting mechanisms, or '
                  'what would invalidate it. No source-bound operating-risk disclosure qualified for this broad '
                  'question. Filing discovery alone cannot establish the investment case; these parts remain unverified.')


def test_the_unread_risk_sentences_are_corrected_only_when_no_filing_was_read(monkeypatch):
    monkeypatch.setattr(eo, 'apply_evidence_outcomes', eo.apply_evidence_outcomes)
    from app import config
    monkeypatch.setattr(config.settings, 'evidence_outcomes_enabled', True, raising=False)
    _, notes = facts_through_client(monkeypatch, 'FORFF (Run 11, us-gaap, CAD)')
    with_forms(notes, 'FORFF (40-F, XBRL-flagged)')
    thesis = Thesis(FORFF_OLD_TEXT)
    out = apply_evidence_outcomes(thesis, thesis_answer(), notes=notes)
    assert 'qualified' not in thesis.direct_answer and 'qualified' not in thesis.conclusion
    assert 'What remains unknown' in thesis.direct_answer and 'CAD' in thesis.direct_answer
    assert len(out['evidence_outcomes']) == 5
    # A filing that WAS read and yielded nothing keeps the original wording.
    read = OutcomeNotes()
    read.add_listed(['10-K'])
    read.add_selected('thesis_disclosures', '10-K')
    kept = Thesis(FORFF_OLD_TEXT)
    apply_evidence_outcomes(kept, thesis_answer(), notes=read)
    assert 'No source-bound operating-risk disclosure qualified' in kept.direct_answer


# --- 4, 5 IFRS and non-USD issuers ---------------------------------------------------------------------

def test_bp_is_ifrs_and_its_annual_report_was_too_large(monkeypatch):
    records, notes = facts_through_client(monkeypatch, 'BP (Run 8, ifrs-full only)')
    assert records == []
    with_forms(notes, 'BP (20-F, IFRS, older pages)')
    gaps = evidence_gaps([], 0, ['thesis_disclosures'], ['thesis_disclosures'], {'thesis_disclosures': '20-F'})
    rows = by_need(build_evidence_outcomes(thesis_answer(evidence_gaps=gaps), notes=notes))
    assert (rows['reported_financials']['state'], rows['reported_financials']['reason']) == ('unsupported', 'ifrs_taxonomy')
    risk = rows['risk_disclosures']
    assert (risk['state'], risk['reason'], risk['tried']) == ('failed', 'filing_too_large', True)
    assert 'larger than the size limit' in risk['user_text']


def test_a_read_failure_noted_by_the_filing_task_is_recorded_without_a_scope(monkeypatch):
    _, notes = facts_through_client(monkeypatch, 'BP (Run 8, ifrs-full only)')
    bind_outcome_notes(lambda: (eo.note_filing_selected('thesis_disclosures', '20-F'),
                                eo.note_filing_read_failure('thesis_disclosures', True)), notes)()
    risk = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['risk_disclosures']
    assert (risk['state'], risk['reason']) == ('failed', 'filing_too_large')


@pytest.mark.parametrize('label,currency', [('MRX (Run 9, ifrs-full only)', None),
                                            ('BWMX (Run 4, ifrs-full, MXN)', 'MXN')])
def test_ifrs_issuers_are_unsupported_not_absent(monkeypatch, label, currency):
    records, notes = facts_through_client(monkeypatch, label)
    assert records == []
    row = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['reported_financials']
    assert (row['state'], row['reason'], row['tried']) == ('unsupported', 'ifrs_taxonomy', True)
    if currency:
        assert currency in row['detail']['currencies']


def test_the_disclosure_only_answer_reason_alone_is_enough_for_ifrs():
    answer = thesis_answer(business_context_coverage={}, financial_analysis={
        'status': 'not_established', 'reason': 'ifrs_taxonomy_not_supported', 'observed_taxonomies': {'ifrs-full': 5}})
    row = by_need(build_evidence_outcomes(answer))['reported_financials']
    assert (row['state'], row['reason']) == ('unsupported', 'ifrs_taxonomy')


# --- 6 confirmed absence is stated about the filing list only -----------------------------------------

@pytest.mark.parametrize('body,cik', [(VBREY, '0001000377'), (IFCNF, '0002035057')], ids=['VBREY', 'IFCNF'])
def test_registration_only_entities_are_unavailable_on_the_filing_list_alone(body, cik):
    evidence = registration_only_evidence(copy.deepcopy(body), cik)
    answer = thesis_answer(evidence_not_applicable=[{'task': 'sec_metrics', 'reason': 'r', 'evidence': evidence}])
    rows = build_evidence_outcomes(answer)
    assert {row['state'] for row in rows} == {'unavailable'}
    assert {row['reason'] for row in rows} == {'registration_only_filing_list'}
    money = by_need(rows)['reported_financials']
    assert money['detail'] == {'company_facts_queried': False}
    assert 'filing list alone' in money['user_text'] and 'was not queried' in money['user_text']


# --- 7 a failed request or a bare 404 is never absence -----------------------------------------------

@pytest.mark.parametrize('status', [404, 403, 429, 500])
def test_http_failures_are_failed_with_their_status_never_unavailable(monkeypatch, status):
    records, notes = facts_through_client(monkeypatch, reply=Reply(status=status))
    assert records == []  # production behaviour unchanged: the failure is still swallowed
    row = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['reported_financials']
    assert (row['state'], row['reason']) == ('failed', 'facts_retrieval_failed')
    assert row['detail']['http_status'] == status
    assert row['state'] != 'unavailable'
    for phrase in ('does not exist', 'not applicable', 'confirmed', 'verified', 'has no ', 'none exist'):
        assert phrase not in row['user_text']
    assert 'not evidence that no data exists' in row['user_text']


def test_a_transport_error_is_failed(monkeypatch):
    _, notes = facts_through_client(monkeypatch, error=sec_client.requests.ConnectionError('reset'))
    row = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['reported_financials']
    assert (row['state'], row['reason'], row['detail']['error_class']) == (
        'failed', 'facts_retrieval_failed', 'ConnectionError')


def test_a_response_for_another_cik_is_failed_not_empty(monkeypatch):
    body = copy.deepcopy(FACTS['GALT (Run 11, us-gaap, no revenue concept)'])
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: Reply(body))
    notes = OutcomeNotes()
    out = bind_outcome_notes(lambda: sec_client.get_company_fact_records_for_concept_units(
        '999', concept_units=CONCEPT_UNITS), notes)()
    assert out == []
    row = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['reported_financials']
    assert (row['state'], row['detail']['error_class']) == ('failed', 'cik_mismatch')


def test_a_listing_failure_is_failed_and_not_a_missing_filing():
    notes = OutcomeNotes()
    bind_outcome_notes(lambda: eo.note_filing_list_failure(Reply(status=503)), notes)()
    notes.list_failures[:] = [{'error_class': 'HTTPError', 'http_status': 503}]
    row = by_need(build_evidence_outcomes(thesis_answer(), notes=notes))['risk_disclosures']
    assert (row['state'], row['reason'], row['tried']) == ('failed', 'filing_list_failed', False)
    assert 'not evidence that no filing exists' in row['user_text']


def test_a_lost_time_budget_is_failed():
    gaps = evidence_gaps(['sec_metrics'], 0)
    row = by_need(build_evidence_outcomes(thesis_answer(evidence_gaps=gaps)))['reported_financials']
    assert (row['state'], row['reason']) == ('failed', 'time_limit')


# --- 8, 9 threshold builder declined; revenue absent from GALT's returned facts -----------------------

def threshold_declined():
    return {'status': 'insufficient_claim_evidence', 'claims': [], 'missing_threshold_inputs': ['x'],
            'unanswered_parts': ['numerical decision thresholds', 'valuation and expected returns',
                                 'quantified earnings impact']}


@pytest.mark.parametrize('label', ['GALT (Run 11, us-gaap, no revenue concept)', 'TWST (Run 5, us-gaap)',
                                   'FSTR (Run 5, us-gaap)'])
def test_threshold_inputs_are_unsupported_when_facts_exist_but_no_pair_could_be_built(monkeypatch, label):
    _, notes = facts_through_client(monkeypatch, label)
    rows = by_need(build_evidence_outcomes(threshold_declined(), notes=notes))
    assert set(rows) == {'reported_financials', 'change_drivers', 'decision_inputs'}
    for need in ('reported_financials', 'decision_inputs'):
        assert rows[need]['state'] == 'unsupported' and rows[need]['tried'] is True
    assert rows['decision_inputs']['reason'] in {'no_same_period_pair', 'ifrs_taxonomy', 'non_usd_reporting'}


def test_galt_core_delivers_financials_but_reports_revenue_absent_from_the_returned_facts(monkeypatch):
    _, notes = facts_through_client(monkeypatch, 'GALT (Run 11, us-gaap, no revenue concept)')
    answer = thesis_answer(business_context_coverage={}, claims=[
        claim('reported_financial_comparison', 'E1', 'Operating loss widened.')])
    money = by_need(build_evidence_outcomes(answer, notes=notes, references=[ref()]))['reported_financials']
    assert money['state'] == 'available'
    assert money['missing_parts'] == [{'part': 'revenue', 'state': 'unavailable',
                                       'reason': 'concept_absent_from_returned_facts'}]
    thesis = Thesis()
    from app import config
    config.settings.evidence_outcomes_enabled = True
    try:
        apply_evidence_outcomes(thesis, answer, notes=notes, references=[ref()])
    finally:
        config.settings.evidence_outcomes_enabled = False
    assert 'also missing: revenue' in thesis.direct_answer
    assert 'describes that response only' in thesis.direct_answer


def test_a_monitoring_answer_names_what_it_never_attempted():
    answer = {'status': 'partial', 'claims': [], 'monitoring_benchmarks': [{}], 'missing_threshold_inputs': ['x']}
    rows = by_need(build_evidence_outcomes(answer))
    assert (rows['decision_inputs']['state'], rows['decision_inputs']['reason']) == ('not_attempted', 'no_provider')


# --- 10 unresolved identity: nothing requested --------------------------------------------------------

def test_an_unresolved_identity_requests_nothing_and_attempts_every_need(no_network):
    rows = build_evidence_outcomes(thesis_answer(), identity_resolved=False)
    assert [row['need'] for row in rows] == [n for n in NEEDS if n != 'decision_inputs']
    assert {(row['state'], row['reason'], row['tried']) for row in rows} == {
        ('not_attempted', 'identity_unresolved', False)}
    assert not no_network


def test_a_gate_answer_with_unresolved_identity_is_not_attempted(no_network):
    rows = build_evidence_outcomes({'status': 'unresolved_company_identity', 'claims': []})
    assert {(r['state'], r['reason']) for r in rows} == {('not_attempted', 'identity_unresolved')}
    assert not no_network


def test_the_identity_gap_answer_gains_the_field_only_with_the_flag(monkeypatch):
    from app import config
    base = {'status': 'unresolved_company_identity', 'claims': []}
    assert eo.identity_gap_source_answer(dict(base)) == base
    monkeypatch.setattr(config.settings, 'evidence_outcomes_enabled', True, raising=False)
    out = eo.identity_gap_source_answer(dict(base))
    assert {r['reason'] for r in out['evidence_outcomes']} == {'identity_unresolved'}


# --- 13, 14 freshness and conflicting evidence --------------------------------------------------------

def test_stale_evidence_is_available_with_its_freshness_and_date():
    answer = thesis_answer(business_context_coverage={}, claims=[claim('reported_financial_comparison')])
    row = by_need(build_evidence_outcomes(answer, references=[ref(freshness='stale', end='2025-03-31')]))['reported_financials']
    assert (row['state'], row['freshness'], row['as_of']) == ('available', 'stale', '2025-03-31')


def test_unknown_references_never_read_as_current():
    answer = thesis_answer(business_context_coverage={}, claims=[claim('reported_financial_comparison', 'E9')])
    assert by_need(build_evidence_outcomes(answer, references=[ref()]))['reported_financials']['freshness'] == 'unknown'


def test_conflicting_blocked_evidence_is_unsupported_and_states_no_figure():
    references = [ref('E1', 'conflicting')]
    integrity = {'admission': {'blocked_reference_ids': ['E1']}}
    row = by_need(build_evidence_outcomes(thesis_answer(), references=references, integrity=integrity))['reported_financials']
    assert (row['state'], row['reason']) == ('unsupported', 'conflicting_evidence')
    assert 'no figure is stated as fact' in row['user_text']
    # Only blocked, conflicting references count.
    assert by_need(build_evidence_outcomes(thesis_answer(), references=references, integrity={}))[
        'reported_financials']['reason'] != 'conflicting_evidence'


# --- 11 invariants over every fixture ----------------------------------------------------------------

def all_cases(monkeypatch):
    cases = []
    for label in FACTS:
        _, notes = facts_through_client(monkeypatch, label)
        for key in ('FORFF (40-F, XBRL-flagged)', 'BP (20-F, IFRS, older pages)', 'GALT (operating pharma)'):
            copy_notes = OutcomeNotes()
            copy_notes.facts_requests = list(notes.facts_requests)
            with_forms(copy_notes, key)
            cases.append((f'{label}|{key}', thesis_answer(), copy_notes))
        cases.append((f'{label}|threshold', threshold_declined(), notes))
    cases.append(('registration', thesis_answer(evidence_not_applicable=[{
        'task': 'sec_metrics', 'reason': 'r', 'evidence': registration_only_evidence(copy.deepcopy(VBREY), '0001000377')}]), None))
    cases.append(('delivered', thesis_answer(business_context_coverage={}, claims=[
        claim('reported_financial_comparison', 'E1'), claim('issuer_disclosed_risk', 'E2'),
        claim('issuer_business_description', 'E3'), claim('issuer_going_concern_disclosure', 'E4'),
        claim('issuer_current_period_explanation', 'E5')]), None))
    return cases


def test_every_applicable_need_has_exactly_one_closed_vocabulary_record(monkeypatch):
    references = [ref(f'E{i}') for i in range(1, 6)]
    for name, answer, notes in all_cases(monkeypatch):
        rows = build_evidence_outcomes(answer, notes=notes, references=references)
        needs = [row['need'] for row in rows]
        assert len(needs) == len(set(needs)) and set(needs) <= set(NEEDS), name
        for row in rows:
            assert row['state'] in STATES and row['reason'] in REASONS[row['state']], (name, row)
            assert row['user_text'].strip(), (name, row)
            assert (row['state'] == 'available') == bool(row['reference_ids']), (name, row)
            assert all(any(r['id'] == i for r in references) for i in row['reference_ids']), (name, row)
            if row['state'] != 'available':
                assert row['as_of'] is None and row['freshness'] is None, (name, row)
        states = {row['state'] for row in rows}
        # A verified absence never sits beside a failed attempt for the same answer.
        assert not ({'unavailable'} <= states and 'failed' in states
                    and any(r['reason'] == 'registration_only_filing_list' for r in rows)), name


def test_available_means_a_bound_claim_of_that_need_exists():
    answer = thesis_answer(business_context_coverage={}, claims=[claim('issuer_disclosed_risk', 'E2')])
    rows = by_need(build_evidence_outcomes(answer, references=[ref('E2')]))
    assert rows['risk_disclosures']['state'] == 'available' and rows['risk_disclosures']['reference_ids'] == ['E2']
    assert rows['business_description']['state'] != 'available'


# --- 12 every unanswered part is explained, or is interpretation rather than evidence ---------------

def test_every_unanswered_part_has_missing_evidence_text_or_is_marked_interpretation(monkeypatch):
    parts = ['financial performance and reported comparisons', 'monitoring baselines', 'valuation and expected returns',
             'business model and competitive position', 'competitive position', 'issuer-disclosed operating-risk mechanisms',
             'risk materiality, likelihood and effect on the investment case', 'business model completeness',
             'operating income', 'revenue', 'operating risk', 'numerical decision thresholds', 'quantified earnings impact',
             'evidence from the annual report (Form 20-F)', 'deposits, loan growth and credit quality', THESIS]
    explained = 0
    for name, answer, notes in all_cases(monkeypatch):
        if name == 'delivered':
            continue
        rows = build_evidence_outcomes(answer, notes=notes)
        needs = {row['need'] for row in rows}
        for part in parts:
            need = part_need(part)
            if need is None:
                assert part == THESIS, part  # interpretation, not an evidence need
                continue
            applicable = need == 'filing' or need in needs
            if not applicable:
                continue  # the part belongs to an answer kind this record does not cover
            text = explain_part(part, rows)
            assert text and text.strip(), (name, part)
            explained += 1
    assert explained > 100


def test_the_thesis_part_is_not_an_evidence_need():
    assert part_need(THESIS) is None


# --- 1, 2 flag off changes nothing; flag on adds the field and block only ----------------------------

def test_flag_off_returns_the_same_object_and_touches_nothing():
    assert Settings.model_fields['evidence_outcomes_enabled'].default is False
    answer = thesis_answer()
    thesis = Thesis()
    assert apply_evidence_outcomes(thesis, answer) is answer
    assert thesis.direct_answer == thesis.conclusion == 'Original answer.' and 'evidence_outcomes' not in answer


def test_the_clients_return_the_same_results_with_and_without_notes(monkeypatch):
    plain = []
    for label in FACTS:
        monkeypatch.setattr(sec_client.requests, 'get', lambda *a, _l=label, **k: Reply(FACTS[_l]))
        cik = str(FACTS[label]['cik'])
        a = sec_client.get_company_fact_records_for_concept_units(cik, concept_units=CONCEPT_UNITS)
        b = bind_outcome_notes(lambda: sec_client.get_company_fact_records_for_concept_units(
            cik, concept_units=CONCEPT_UNITS), OutcomeNotes())()
        assert a == b, label
        plain.append(a)
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: Reply(status=404))
    assert sec_client.get_company_fact_records_for_concept_units('1', concept_units=CONCEPT_UNITS) == []


def test_flag_on_only_adds_the_field_and_the_block(monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, 'evidence_outcomes_enabled', True, raising=False)
    answer = thesis_answer(business_context_coverage={}, claims=[
        claim('reported_financial_comparison', 'E1', 'One.'), claim('issuer_disclosed_risk', 'E2', 'Two.')],
        unanswered_parts=['valuation and expected returns', THESIS])
    before = copy.deepcopy(answer)
    thesis = Thesis('Body [E1] [E2].')
    out = apply_evidence_outcomes(thesis, answer, references=[ref('E1'), ref('E2')])
    assert {k: v for k, v in out.items() if k != 'evidence_outcomes'} == before and answer == before
    assert thesis.direct_answer.startswith('Body [E1] [E2].\n\nWhat remains unknown\n')
    again = thesis.direct_answer
    apply_evidence_outcomes(thesis, answer, references=[ref('E1'), ref('E2')])
    assert thesis.direct_answer == again  # applying twice (the router does) adds nothing


def test_the_filing_list_hook_records_forms_and_failures_without_changing_results(monkeypatch):
    from app.services.providers import sec_provider
    forms = SUBMISSIONS['FORFF (40-F, XBRL-flagged)']
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {'FTS': '0001666175'})
    monkeypatch.setattr(sec_provider, '_fetch_json', lambda url, timeout=10: copy.deepcopy(forms))
    notes = OutcomeNotes()
    bound = bind_outcome_notes(lambda: sec_provider.fetch_recent_filings('FTS', forms=['10-K', '20-F'], limit=1), notes)
    plain = sec_provider.fetch_recent_filings('FTS', forms=['10-K', '20-F'], limit=1)
    assert bound() == plain == []
    assert {'40-F', '6-K'} <= notes.listed_forms

    def boom(url, timeout=10):
        raise sec_provider.HTTPError(url, 503, 'unavailable', None, None)

    monkeypatch.setattr(sec_provider, '_fetch_json', boom)
    failing = OutcomeNotes()
    assert bind_outcome_notes(lambda: sec_provider.fetch_recent_filings('FTS', forms=['10-K']), failing)() == []
    assert failing.list_failures and failing.list_failures[0]['http_status'] == 503


# --- 15 guards ---------------------------------------------------------------------------------------

COHORT_6 = ['E' + 'RO', 'MG' + 'RT', 'MY' + 'GN', 'SU' + 'PV', 'FMS' + 'TW', 'FM' + 'ST', 'OP' + 'TT']


def test_the_flag_is_default_off_and_no_pilot_profile_sets_it():
    assert Settings.model_fields['evidence_outcomes_enabled'].default is False
    for path in (ROOT / 'validation').glob('*.py'):
        assert 'evidence_outcomes' not in path.read_text(), path.name


def test_no_cohort_6_issuer_appears_in_the_module_fixtures_or_this_test():
    pattern = re.compile(r'\b(?:' + '|'.join(COHORT_6) + r')\b')
    for path in (ROOT / 'app/services/evidence_outcomes.py', DATA / 'company_facts_trimmed_retained_runs4_11.json',
                 Path(__file__)):
        text = path.read_text()
        if path == Path(__file__):
            text = text.replace("COHORT_6 = ['E' + 'RO'", '')
        assert not pattern.search(text), path.name


def test_the_module_makes_no_network_call_and_imports_no_client():
    source = (ROOT / 'app/services/evidence_outcomes.py').read_text()
    for forbidden in ('import requests', 'urllib', 'import socket', 'httpx', 'aiohttp', 'fetch_', 'openai', 'anthropic'):
        assert forbidden not in source, forbidden
