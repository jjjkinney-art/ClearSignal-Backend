"""Review findings (owner adjudication 2026-11-20): an evidence-gap explanation states what the run recorded.

Two reviewed answers said "no comparison of a current and a prior-period figure on the same basis could be built" when comparisons had been built (one: then rejected as
stale; the other: three verified comparisons, only revenue failed because the prior-year value was zero). The sentence was a catch-all that never read the pair builder's
result. Now the builder reports the rule that stopped each concept, retrieval records it, and the explanation is chosen from what was recorded. With the new flag on, the
verified comparisons survive a threshold question that cannot calculate a margin. Offline; all inputs are constructed or retained development data.
"""
import pytest

from app.config import Settings, settings
from app.integrity.sec_metric_evidence import comparable_metric_evidence, explain_no_comparable_metric
from app.providers.sec_client import SecFactRecord
from app.services import evidence_outcomes as eo
from app.services.decision_monitoring_evidence import build_decision_monitoring
from app.services.evidence_outcomes import OutcomeNotes, build_evidence_outcomes
from app.services.source_answer import apply_source_answer_gate
from test_financial_thesis_foundation import evidence, reference

CIK, TICKER = '320193', 'AAPL'
SEC = 'SEC EDGAR — structured XBRL fact'


def rec(concept, start, end, value, *, filed=None, form='10-Q', accession='0000320193-25-000001'):
    return SecFactRecord(cik=CIK, taxonomy='us-gaap', concept=concept, label=concept, unit='USD', value=value, start=start, end=end, filed=filed or end[:4] + '-08-01',
                         form=form, accession=accession,
                         filing_url=f'https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace("-", "")}/{accession}-index.htm')


def run(records, concept='OperatingIncomeLoss'):
    kwargs = dict(ticker=TICKER, expected_cik=CIK, concepts=(concept,), metric_name='operating income')
    return comparable_metric_evidence(records, **kwargs), explain_no_comparable_metric(records, **kwargs)


# --- the builder says why it stopped, and its result is unchanged -------------------------------------------------

GOOD = [rec('OperatingIncomeLoss', '2024-04-01', '2024-06-30', -5, accession='0000320193-24-000001'), rec('OperatingIncomeLoss', '2025-04-01', '2025-06-30', -9)]


@pytest.mark.parametrize('label,records,reason', [
    ('a valid pair', GOOD, None),
    ('prior-year value zero', [rec('OperatingIncomeLoss', '2024-04-01', '2024-06-30', 0, accession='0000320193-24-000001'), GOOD[1]], 'prior_value_zero'),
    ('no prior-year observation', [GOOD[1]], 'no_prior_year_observation'),
    ('prior observation of another length', [rec('OperatingIncomeLoss', '2024-01-01', '2024-06-30', -5, accession='0000320193-24-000001'), GOOD[1]], 'no_prior_year_observation'),
    ('no record of the concept', [rec('Revenues', '2025-04-01', '2025-06-30', 5)], 'no_records'),
    ('no period fits the form', [rec('OperatingIncomeLoss', '2025-06-20', '2025-06-30', -9)], 'no_period_fits_form'),
    ('conflicting prior observations', [rec('OperatingIncomeLoss', '2024-04-01', '2024-06-30', -5, accession='0000320193-24-000001'),
                                         rec('OperatingIncomeLoss', '2024-04-01', '2024-06-30', -6, accession='0000320193-24-000002'), GOOD[1]], 'ambiguous_prior_period'),
    ('conflicting current observations', [GOOD[0], rec('OperatingIncomeLoss', '2025-04-01', '2025-06-30', -9, accession='0000320193-25-000001'),
                                           rec('OperatingIncomeLoss', '2025-04-01', '2025-06-30', -10, accession='0000320193-25-000002')], 'ambiguous_current_period'),
    ('annual and quarterly in the latest period', [rec('OperatingIncomeLoss', '2024-04-01', '2024-06-30', -5, accession='0000320193-24-000001'), GOOD[1],
                                                    rec('OperatingIncomeLoss', '2024-07-01', '2025-06-30', -30, form='10-K')], 'mixed_period_families'),
])
def test_the_builder_names_the_rule_that_stopped_the_pair(label, records, reason):
    evidence_item, got = run(records)
    assert got == reason
    assert (evidence_item is None) == (reason is not None)     # the reason exists exactly when no comparison is returned: the public result is unchanged


def test_an_unrecognised_unit_or_missing_identity_is_an_invalid_request():
    assert explain_no_comparable_metric(GOOD, ticker=TICKER, expected_cik=CIK, concepts=('OperatingIncomeLoss',), metric_name='x', unit='XYZ') == 'invalid_request'
    assert comparable_metric_evidence(GOOD, ticker='', expected_cik=CIK, concepts=('OperatingIncomeLoss',), metric_name='x') is None


# --- the explanation comes from the recorded outcome ---------------------------------------------------------------

def facts_row(**extra):
    return {'cik': CIK, 'ok': True, 'taxonomies': {'us-gaap': 304}, 'currencies': {'us-gaap': ['USD']}, 'requested': ['Revenues'], 'present': ['OperatingIncomeLoss'],
            'with_records': ['OperatingIncomeLoss'], 'requested_currencies': {}, **extra}


def notes_with(outcomes=(), **facts):
    notes = OutcomeNotes()
    notes.facts_requests.append(facts_row(**facts))
    for row in outcomes:
        notes.add_pair_outcome(row)
    return notes


def built(measure, concept, end):
    return {'measure': measure, 'concept': concept, 'status': 'built', 'reason': None, 'period_end': end}


def stopped(measure, concept, reason):
    return {'measure': measure, 'concept': concept, 'status': 'none', 'reason': reason, 'period_end': None}


def threshold_declined():
    return {'status': 'insufficient_claim_evidence', 'claims': [], 'missing_threshold_inputs': ['x'],
            'unanswered_parts': ['numerical decision thresholds', 'valuation and expected returns', 'quantified earnings impact']}


def sec_refs(n, *, freshness, end):
    return [{'id': f'E{i}', 'source': SEC, 'freshness_status': freshness, 'reporting_period_end': end} for i in range(1, n + 1)]


def rows(answer, notes, references):
    return {row['need']: row for row in build_evidence_outcomes(answer, notes=notes, references=references)}


OLD_SENTENCE = 'no comparison of a current and a prior-period figure on the same basis could be built from it'


def test_b006_like_comparisons_built_but_stale_say_so_and_do_not_claim_none_could_be_built():
    notes = notes_with([built('operating income', 'OperatingIncomeLoss', '2018-10-31'), built('net income', 'NetIncomeLoss', '2018-10-31'),
                        built('operating cash flow', 'NetCashProvidedByUsedInOperatingActivities', '2018-10-31'), stopped('revenue', 'Revenues', 'no_records')],
                       taxonomies={'us-gaap': 304, 'ifrs-full': 147}, currencies={'us-gaap': ['CAD', 'USD'], 'ifrs-full': ['CAD', 'USD']})
    got = rows(threshold_declined(), notes, sec_refs(3, freshness='stale', end='2018-10-31'))
    money = got['reported_financials']
    assert (money['state'], money['reason'], money['tried']) == ('unsupported', 'comparisons_stale', True)
    assert OLD_SENTENCE not in money['user_text'] and 'No comparison' not in money['user_text']
    assert '3 comparison(s) of a current and a prior-period figure were built' in money['user_text']
    assert 'ended 2018-10-31' in money['user_text'] and '550-day freshness window' in money['user_text']
    assert 'IFRS-tagged facts (147 concepts, reported in CAD, USD)' in money['user_text'] and 'does not read in this version' in money['user_text']
    assert money['detail']['latest_period_end'] == '2018-10-31' and money['detail']['freshness_window_days'] == 550
    assert got['decision_inputs']['reason'] == 'comparisons_stale'


def test_the_ifrs_sentence_is_only_said_when_the_response_holds_ifrs_facts_and_only_for_threshold_answers():
    notes = notes_with([built('net income', 'NetIncomeLoss', '2018-10-31')])
    text = rows(threshold_declined(), notes, sec_refs(1, freshness='stale', end='2018-10-31'))['reported_financials']['user_text']
    assert 'IFRS' not in text


def test_b012_like_valid_comparisons_not_used_for_a_threshold_say_why_and_are_not_thresholds():
    notes = notes_with([built('operating income', 'OperatingIncomeLoss', '2026-06-30'), built('net income', 'NetIncomeLoss', '2026-06-30'),
                        built('operating cash flow', 'NetCashProvidedByUsedInOperatingActivities', '2026-06-30'),
                        stopped('revenue', 'Revenues', 'prior_value_zero'), stopped('revenue', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'prior_value_zero'),
                        stopped('revenue', 'RevenuesNetOfInterestExpense', 'no_records')])
    got = rows(threshold_declined(), notes, sec_refs(3, freshness='current', end='2026-06-30'))
    money = got['reported_financials']
    assert (money['state'], money['reason']) == ('unsupported', 'comparisons_not_used_for_threshold')
    assert OLD_SENTENCE not in money['user_text']
    assert 'operating income, net income, operating cash flow' in money['user_text']
    assert 'the prior-year revenue figure is zero, so no revenue comparison could be expressed' in money['user_text']
    assert 'not investment thresholds' in money['user_text'] and money['detail']['revenue_reason'] == 'prior_value_zero'
    assert got['decision_inputs']['reason'] == 'comparisons_not_used_for_threshold'


def test_without_a_recorded_revenue_outcome_the_threshold_explanation_does_not_invent_a_cause():
    notes = notes_with([built('operating income', 'OperatingIncomeLoss', '2026-06-30')])
    text = rows(threshold_declined(), notes, sec_refs(1, freshness='current', end='2026-06-30'))['reported_financials']['user_text']
    assert 'no verified revenue comparison is available' in text and 'is zero' not in text


def test_when_every_measure_was_stopped_the_explanation_lists_each_recorded_rule():
    notes = notes_with([stopped('revenue', 'Revenues', 'no_records'), stopped('operating income', 'OperatingIncomeLoss', 'no_prior_year_observation'),
                        stopped('net income', 'NetIncomeLoss', 'no_prior_year_observation'), stopped('net income', 'ProfitLoss', 'no_records'),
                        stopped('operating cash flow', 'NetCashProvidedByUsedInOperatingActivities', 'prior_value_zero')])
    money = rows(threshold_declined(), notes, [])['reported_financials']
    assert (money['state'], money['reason']) == ('unsupported', 'no_same_period_pair')
    assert money['user_text'] == ('Company-facts data was retrieved, but no comparison of a current and a prior-period figure could be built: '
                                  'revenue: the company-facts data holds no figures for it; operating income: no figure for the same period one year earlier was found; '
                                  'net income: no figure for the same period one year earlier was found; '
                                  'operating cash flow: its prior-year figure is zero, so a change cannot be expressed.')


def test_a_comparison_set_aside_against_the_issuers_latest_period_is_said_to_be():
    notes = notes_with([{'measure': 'net income', 'concept': None, 'status': 'dropped', 'reason': 'older_than_issuer_latest_period', 'period_end': '2019-01-31'}])
    money = rows(threshold_declined(), notes, [])['reported_financials']
    assert money['reason'] == 'comparisons_stale' and 'comparisons were built for net income' in money['user_text'] and '550 days older' in money['user_text']


def test_nothing_recorded_means_the_run_says_it_did_not_record_why():
    money = rows(threshold_declined(), notes_with(), [])['reported_financials']
    assert (money['state'], money['reason'], money['tried']) == ('not_attempted', 'not_recorded', True)
    assert 'did not record why' in money['user_text'] and OLD_SENTENCE not in money['user_text']


def test_with_the_retention_flag_on_the_margin_clause_is_not_claimed(monkeypatch):
    monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', True)
    notes = notes_with([built('operating income', 'OperatingIncomeLoss', '2026-06-30')])
    money = rows(threshold_declined(), notes, sec_refs(1, freshness='current', end='2026-06-30'))['reported_financials']
    assert money['reason'] == 'comparisons_not_used' and 'operating-margin' not in money['user_text']


def test_the_reasons_are_valid_record_reasons():
    for reason in ('comparisons_stale', 'comparisons_not_used_for_threshold', 'comparisons_not_used'):
        assert reason in eo.REASONS['unsupported']


# --- retaining valid comparisons when no margin can be calculated (flag) ------------------------------------------

def b012_like():
    items = [evidence('OperatingIncomeLoss', 'operating income', current=-1739890, prior=-478146),
             evidence('NetIncomeLoss', 'net income', current=-2179349, prior=-805767),
             evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', current=-832030, prior=-771366, ytd=True)]
    return items, [reference(item, f'E{i}') for i, item in enumerate(items, 1)]


def test_the_flag_is_off_by_default_and_the_default_behaviour_is_unchanged():
    assert Settings.model_fields['threshold_comparisons_retained_enabled'].default is False
    items, refs = b012_like()
    assert build_decision_monitoring(TICKER, items, refs, expected_cik=CIK) is None       # operating income verified, no revenue: all comparisons discarded, as before


def test_with_the_flag_on_verified_comparisons_survive_without_a_margin_or_a_threshold(monkeypatch):
    monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', True)
    items, refs = b012_like()
    result = build_decision_monitoring(TICKER, items, refs, expected_cik=CIK)
    assert result is not None and result['benchmarks'] == []
    assert len(result['foundation']['claims']) == 3
    assert all(row['claim_kind'] == 'reported_financial_comparison' for row in result['foundation']['claims'])
    assert result['unanswered_parts'] == ['operating margin', 'revenue']
    answer = result['answer']
    assert 'No operating margin or margin benchmark has been calculated' in answer and 'no verified revenue comparison is available' in answer
    assert 'not benchmarks or thresholds' in answer and 'do not determine whether the stock is attractive or unattractive' in answer
    assert 'Monitoring criteria' not in answer and 'Historical baseline, not an investment threshold' not in answer
    assert 'Operating income was not verified' not in answer        # operating income WAS verified; the old sentence would be false here
    assert all(f'[E{i}]' in answer for i in (1, 2, 3))


def test_the_retained_text_names_the_recorded_revenue_rule_inside_the_request(monkeypatch):
    monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', True)
    notes = OutcomeNotes()
    notes.add_pair_outcome(stopped('revenue', 'Revenues', 'prior_value_zero'))
    items, refs = b012_like()
    result = eo.bind_outcome_notes(lambda: build_decision_monitoring(TICKER, items, refs, expected_cik=CIK), notes)()
    assert 'the prior-year revenue figure is zero, so no revenue comparison could be expressed' in result['answer']


def test_one_comparison_alone_is_still_not_a_foundation_with_the_flag_on(monkeypatch):
    monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', True)
    items, refs = b012_like()
    assert build_decision_monitoring(TICKER, items[:1], refs[:1], expected_cik=CIK) is None


def test_a_calculable_margin_still_builds_the_benchmark_with_the_flag_on(monkeypatch):
    monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', True)
    items = [evidence('Revenues', 'revenue', current=100, prior=80), evidence('OperatingIncomeLoss', 'operating income', current=10, prior=8)]
    result = build_decision_monitoring(TICKER, items, [reference(i, f'E{n}') for n, i in enumerate(items, 1)], expected_cik=CIK)
    assert [b['metric'] for b in result['benchmarks']] == ['operating margin']


def test_the_gate_with_the_flag_delivers_a_partial_answer_with_the_comparison_claims(monkeypatch):
    from app.schemas import InvestmentThesis
    from app.services.providers import sec_provider
    monkeypatch.setattr(sec_provider, '_load_ticker_cik_map', lambda: {TICKER: CIK})
    items, refs = b012_like()
    for flag, status in ((False, 'insufficient_claim_evidence'), (True, 'partial')):
        monkeypatch.setattr(settings, 'threshold_comparisons_retained_enabled', flag)
        thesis = InvestmentThesis(ticker=TICKER, company_name='Apple', bull_thesis='Buy at 30x')
        result = apply_source_answer_gate(thesis, 'Explain decision thresholds', items, references=refs)
        assert result['status'] == status
        assert len(result['claims']) == (3 if flag else 0)
        assert not thesis.decision_thresholds and thesis.confidence_score == 0
        if flag:
            assert result['monitoring_benchmarks'] == [] and 'valuation decision boundaries' in result['unanswered_parts']
