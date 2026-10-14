import pytest
from app.services.source_answer import is_source_answer_request, is_decision_monitoring_request
from app.services.verified_sec_metric_service import _requested_metrics


@pytest.mark.parametrize('question', [
    'Explain decision thresholds, evidence and uncertainty without inventing figures.',
    'Which valuation and operating assumptions make Invented Corp attractive or unattractive?',
    'What quantitative threshold should I monitor?',
])
def test_threshold_request_enters_verified_input_route(question):
    assert is_decision_monitoring_request(question)
    assert is_source_answer_request(question)
    assert {m[1] for m in _requested_metrics(question)} == {
        'revenue', 'operating income', 'net income', 'operating cash flow'}


def test_generic_valuation_question_is_not_reclassified():
    assert not is_decision_monitoring_request('Is Apple fairly valued?')
    assert not is_source_answer_request('Is Apple fairly valued?')


def test_frozen_pilot_disables_new_input_route_without_expanding_quota(monkeypatch):
    from app.config import settings
    from validation.pilot_policy import PILOT_SETTINGS
    assert PILOT_SETTINGS['decision_monitoring_inputs_enabled'] is False
    monkeypatch.setattr(settings, 'decision_monitoring_inputs_enabled', False)
    assert not is_source_answer_request('Explain decision thresholds, evidence and uncertainty.')
    # Explicit source requests retain their existing behavior.
    assert is_source_answer_request('Cite the revenue evidence.')
