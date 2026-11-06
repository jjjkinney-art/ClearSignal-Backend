"""Explanations that state causes, bound to the current period and scope.

Excerpts are from SEC filings retained in ordinary run 2 (NNBR, INGR, AMZN,
MAN, GOOGL 10-Qs). Each rule is general; no issuer is named in the code.
"""
from app.services import current_period_explanation as cpe

Q3 = {'current_start': '2026-07-01', 'current_end': '2026-09-30', 'prior_start': '2025-07-01', 'prior_end': '2025-09-30'}
Q2 = {'current_start': '2026-04-01', 'current_end': '2026-06-30', 'prior_start': '2025-04-01', 'prior_end': '2025-06-30'}
NNBR = {'revenue': {'current': 131085000, 'prior': 103911000}}
NNBR_FIGURES = ('Third Quarter Results Net sales for the three months ended September 30, 2026 were $131.1 million, '
                'an increase of 26.2% compared to the same period in 2025.')
NNBR_CAUSE = ('Net sales increased by $27.2 million, or 26.2%, during the three months ended September 30, 2026, '
              'compared to the three months ended September 30, 2025, primarily due to higher selling prices, '
              'reflecting the pass-through of increased raw material costs to customers, higher volumes, and '
              'favorable foreign exchange effects.')
INGR = {'revenue': {'current': 1850000000, 'prior': 1833000000},
        'net income': {'current': 114000000, 'prior': 196000000}}
AMZN = {'revenue': {'current': 200606000000, 'prior': 167702000000},
        'non-operating income (expense)': {'current': 53396000000, 'prior': 1686000000},
        'other income (expense), net': {'current': 53415000000, 'prior': 1117000000}}
AMZN_DEFINITION = ('Other income (expense), net was $1.1 billion and $53.4 billion during Q2 2025 and Q2 2026, and '
                   '$3.9 billion and $69.1 billion for the six months ended June 30, 2025 and 2026.')
AMZN_CAUSE = ('The net gain of $53.4 billion in Q2 2026 and $69.1 billion for the six months ended June 30, 2026 is '
              'primarily from upward adjustments for observable changes in price relating to our nonvoting '
              'preferred stock in Anthropic.')


def test_a_causal_statement_is_preferred_and_headings_are_trimmed(monkeypatch):
    monkeypatch.setattr(cpe, '_metrics', lambda items: (dict(NNBR), tuple(Q3.values())))
    value = cpe.explanation_value(f'{NNBR_FIGURES} {NNBR_CAUSE}', [], [], ticker='NNBR', document_type='10-Q',
                                  filed_at='2026-10-28')
    assert [s['quote'] for s in value['statements']] == [NNBR_CAUSE]
    assert list(cpe.clause_starts(NNBR_FIGURES))[0] == NNBR_FIGURES.index('Net sales')
    assert cpe.bind_statement(NNBR_FIGURES[NNBR_FIGURES.index('Net sales'):], NNBR)['metric'] == 'revenue'


def test_percent_and_to_from_wording_reconcile():
    assert cpe.bind_statement('Net sales increased 1 percent to $1,850 million for the second quarter of 2026 '
                              'compared to $1,833 million for the second quarter of 2025.', INGR) == {
        'metric': 'revenue', 'basis': 'stated current and prior levels'}
    assert cpe.bind_statement('Net income attributable to Ingredion for the second quarter of 2026 decreased to '
                              '$114 million from $196 million for the second quarter of 2025.', INGR) == {
        'metric': 'net income', 'basis': 'stated current and prior levels'}


def test_an_ownership_label_is_not_a_cause():
    assert cpe.cause_match('Net income attributable to Ingredion decreased to $114 million.') is None
    assert cpe.cause_match('The decrease was attributable to lower volumes.') is not None


def test_another_period_is_never_attributed_to_the_current_one():
    ytd = ('Operating income decreased 29 percent to $391 million for year-to-date 2026 from $547 million for '
           'year-to-date 2025, which included lower gross profit due to higher manufacturing costs.')
    metrics = {'operating income': {'current': 188000000, 'prior': 271000000}}
    assert cpe.bind_statement(ytd, metrics) is None
    assert cpe.bind_attribution(ytd, metrics, Q2) is None


def test_an_amount_shared_by_two_line_items_needs_the_filings_own_definition():
    # 53.4 billion matches total non-operating income and the other-income line at stated precision.
    assert cpe.bind_attribution(AMZN_CAUSE, AMZN, Q2) is None
    assert cpe.defines_levels(AMZN_DEFINITION, AMZN, Q2) == 'other income (expense), net'
    assert cpe.bind_attribution(AMZN_CAUSE, AMZN, Q2, defined='other income (expense), net') == {
        'metric': 'other income (expense), net', 'basis': 'stated period amount with attribution'}
    # Without the current period named, nothing binds.
    assert cpe.bind_attribution(AMZN_CAUSE.replace('Q2 2026', 'the period'), AMZN, Q2,
                                defined='other income (expense), net') is None


def test_period_matched_direction_and_segment_attributions():
    metrics = {'revenue': {'current': 4900, 'prior': 4500}, 'operating income': {'current': 112, 'prior': -25},
               'operating margin': {'current': 230, 'prior': -56}}
    margin = ('Operating profit margin increased in the second quarter of 2026 primarily due to the negative impact '
              'of impairment in the prior year.')
    assert cpe.bind_attribution(margin, metrics, Q2) == {'metric': 'operating margin', 'basis': 'period-matched attribution'}
    assert cpe.bind_attribution(margin.replace('increased', 'decreased'), metrics, Q2) is None
    region = ('During the second quarter of 2026 compared to the second quarter of 2025, we experienced a 14.4% '
              'revenue increase in the Americas, primarily driven by an increase in demand for our staffing services.')
    assert cpe.segment_attribution(region, metrics, Q2)
    assert not cpe.segment_attribution(region.replace('second quarter of 2026', 'first half of 2026'), metrics, Q2)
    assert list(cpe.clause_starts('24 PART 1 ' + region))[0] == len('24 PART 1 ')


def test_scope_and_metric_must_be_in_the_explained_clause():
    metrics = {'revenue': {'current': 1, 'prior': 2}}
    cost = ('The increase in other cost of revenues from the three months ended September 30, 2025 to the three '
            'months ended September 30, 2026 was primarily due to content acquisition costs, largely for YouTube.')
    assert not cpe.segment_attribution(cost, metrics, Q3)
    tac = ('The TAC rate decreased from 20.1% to 20.0% from the three months ended September 30, 2025 to the three '
           'months ended September 30, 2026, primarily due to a revenue mix shift in the Network.')
    assert not cpe.segment_attribution(tac, metrics, Q3)


def test_repeated_headings_are_removed_whole():
    google = ('Google Cloud Google Cloud revenues increased $15.6 billion from the three months ended September 30, '
              '2025 to the three months ended September 30, 2026, primarily driven by growth in Google Cloud Platform.')
    assert google[list(cpe.clause_starts(google))[0]:].startswith('Google Cloud revenues increased')
    heading = 'Other Income (Expense), Net ' + AMZN_DEFINITION
    assert heading[list(cpe.clause_starts(heading))[0]:] == AMZN_DEFINITION
    plain = 'Google Cloud revenues increased $15.6 billion.'
    assert list(cpe.clause_starts(plain)) == [0]


def test_material_same_direction_non_operating_swings_get_a_bridge():
    current, prior = ('2026-04-01', '2026-06-30'), ('2025-04-01', '2025-06-30')
    figures = {('current', 'OperatingIncomeLoss'): 27461, ('current', 'NonoperatingIncomeExpense'): 53396,
               ('current', 'IncomeTaxExpenseBenefit'): 18285, ('current', 'NetIncomeLoss'): 62561,
               ('prior', 'OperatingIncomeLoss'): 19171, ('prior', 'NonoperatingIncomeExpense'): 1686,
               ('prior', 'IncomeTaxExpenseBenefit'): 2753, ('prior', 'NetIncomeLoss'): 18093}
    rows = [(amount, {'concept': concept, 'start': (current if p == 'current' else prior)[0],
                      'end': (current if p == 'current' else prior)[1]}) for (p, concept), amount in figures.items()]
    bridge = cpe.earnings_bridge(rows, current, prior)
    assert bridge['deltas']['NonoperatingIncomeExpense'] == 51710
    value = {'period': dict(Q2, current_start=current[0]), 'document_type': '10-Q', 'filed_at': '2026-07-31',
             'bridge': bridge, 'statements': [], 'components': []}
    rendered = cpe.render(value)
    assert 'Net income moved $0.0M while operating income moved $0.0M: non-operating income (expense) went from' in rendered
    assert 'The filing states no cause for these changes in this period' in rendered
    assert 'Its change exceeded the change in operating income' in cpe.monitoring_criteria(value)[0]
