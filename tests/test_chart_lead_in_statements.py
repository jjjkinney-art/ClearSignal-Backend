"""A chart lead-in run into a management statement no longer hides the statement.

The text is an excerpt of a retained SEC filing (Northwest Bancshares 10-Q for the quarter ended
2026-09-30), where the MD&A paragraph reads "... reconciliation of net income ... (dollars in thousands):
Net income for the quarter ... was $51 million ..." with the section heading in front. No network access.
"""
import pytest

from app.services import current_period_explanation as cpe

PERIOD = ('2026-07-01', '2026-09-30', '2025-07-01', '2025-09-30')
METRICS = {'net income': {'current': 50719000, 'prior': 3167000}}
HEADING = 'Comparison of Operating Results for the Quarters Ended September 30, 2026 and 2025 '
LEAD_IN = ('The following chart provides a reconciliation of net income from the quarter ended September 30, 2025 '
           'to the quarter ended September 30, 2026 (dollars in thousands): ')
STATEMENT = ('Net income for the quarter ended September 30, 2026 was $51 million, or $0.34 per diluted share, '
             'an increase of $48 million, from net income of $3 million, or $0.02 per diluted share, for the '
             'quarter ended September 30, 2025.')
CAUSE = ('This increase in net income resulted primarily from a decrease in noninterest expense of $25 million, '
         'which was driven by the decrease in acquisition expense of $31 million, and a decrease in provision for '
         'credit losses of $22 million, primarily driven by the Day 1 initial provision from the Penns Woods '
         'acquisition of $20.6 million in the prior year.')


def value(monkeypatch, text):
    monkeypatch.setattr(cpe, '_metrics', lambda items: (dict(METRICS), PERIOD))
    return cpe.explanation_value(text, [], [], ticker='NWBI', document_type='10-Q', filed_at='2026-11-05')


def test_the_statement_after_a_chart_lead_in_binds_and_is_quoted_from_its_own_start(monkeypatch):
    result = value(monkeypatch, HEADING + LEAD_IN + STATEMENT + ' ' + CAUSE)
    (statement,) = result['statements']
    assert statement['metric'] == 'net income' and statement['quote'] == STATEMENT   # verbatim, lead-in dropped
    # The attribution is management's own, for this change and this period.
    assert statement['cause_quote'] == CAUSE
    assert result['period']['current_end'] == '2026-09-30'


def test_the_lead_in_alone_never_binds_and_without_it_nothing_changes(monkeypatch):
    assert value(monkeypatch, HEADING + LEAD_IN.rstrip(': ') + '.') is None
    plain = value(monkeypatch, STATEMENT + ' ' + CAUSE)
    assert plain['statements'][0]['quote'] == STATEMENT and plain['statements'][0]['cause_quote'] == CAUSE


@pytest.mark.parametrize('lead_in', [
    'The following table presents segment results for the Retail segment (dollars in thousands): ',
    'The following table presents adjusted non-GAAP results (dollars in thousands): ',
    'The following chart shows results excluding merger costs (dollars in thousands): ',
    'The following table presents results by region (dollars in thousands): ',
])
def test_a_lead_in_that_scopes_or_qualifies_the_statement_is_not_dropped(monkeypatch, lead_in):
    # The post-colon start is never offered, so a scoped or adjusted figure is never presented as the
    # bare consolidated statement. Whatever binds keeps the lead-in in its verbatim quote.
    assert list(cpe.clause_starts(lead_in + STATEMENT)) == [0]
    result = value(monkeypatch, HEADING + lead_in + STATEMENT + ' ' + CAUSE)
    assert result is None or all(statement['quote'] != STATEMENT and statement['quote'].startswith(lead_in.strip()[:20])
                                 for statement in result['statements'])


def test_the_cause_rules_are_unchanged_by_the_lead_in_rule(monkeypatch):
    # A cause that names another period still binds no cause.
    other_period = CAUSE.replace('in the prior year', 'for the nine months ended September 30, 2026')
    result = value(monkeypatch, HEADING + LEAD_IN + STATEMENT + ' ' + other_period)
    assert 'cause_quote' not in result['statements'][0]
    # Nor does a sentence that does not refer back to the change.
    unrelated = 'Noninterest expense decreased primarily because of lower acquisition expense.'
    assert 'cause_quote' not in value(monkeypatch, HEADING + LEAD_IN + STATEMENT + ' ' + unrelated)['statements'][0]
    # Reconciliation is exactly what it was: a stated change that does not match falls back to the
    # (reconciling) stated levels, with or without the lead-in, and nothing else is accepted.
    wrong_change = STATEMENT.replace('$48 million', '$40 million')
    with_lead_in = value(monkeypatch, HEADING + LEAD_IN + wrong_change)['statements'][0]
    without = value(monkeypatch, wrong_change)['statements'][0]
    assert with_lead_in['basis'] == without['basis'] == 'stated current and prior levels'
    assert with_lead_in['quote'] == without['quote'] == wrong_change
    assert value(monkeypatch, HEADING + LEAD_IN + STATEMENT.replace('$51 million', '$61 million').replace(
        '$48 million', '$58 million')) is None
