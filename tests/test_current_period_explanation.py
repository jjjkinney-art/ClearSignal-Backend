"""Latest-period explanations are bound to the filing's own figures.

The sentences below are short excerpts from retained SEC filings (National
Presto 10-Q for the quarter ended 2026-07-05; Alphabet 10-Q for the quarter
ended 2026-09-30). No network access is used.
"""
from app.integrity.provenance import ClaimDocumentReference
from app.schemas import RetrievedEvidence
from app.services import current_period_explanation as cpe

NPK_METRICS = {'revenue': {'current': 146596000, 'prior': 120449000},
               'net income': {'current': 15862000, 'prior': 5152000}}
GOOGL_METRICS = {'revenue': {'current': 127577000000, 'prior': 102346000000},
                 'non-operating income (expense)': {'current': -8221000000, 'prior': 12759000000}}
NPK_CONSOLIDATED = ('On a consolidated basis, net sales increased by $26,147,000 (22%), gross profit '
                    'increased by $10,001,000 (54%), selling and general expenses decreased by $698,000 (7%).')
NPK_DEFENSE = ('Defense net sales increased by $27,144,000 from $99,813,000 to $126,957,000 or 27%, '
               "primarily reflecting an increase in shipments from the segment's backlog.")
NPK_HOUSEWARES = ('Housewares/Small Appliance net sales decreased by $1,263,000 from $20,346,000 to '
                  '$19,083,000, or 6%, which was attributable to a decrease in units shipped.')
GOOGL_REVENUE = ('Revenues were $127.6 billion, an increase of 25% year over year, primarily driven by an '
                 'increase in Google Cloud revenues of $15.6 billion, or 103%.')
GOOGL_OIE = ('OI&E, net decreased $21.0 billion from the three months ended September 30, 2025 to the three '
             'months ended September 30, 2026, primarily related to net unrealized losses in our marketable '
             'equity securities.')
URL = 'https://www.sec.gov/Archives/edgar/data/80172/000143774926027999/npk20260615_10q.htm'
HASH = 'a' * 64


def test_statements_bind_only_to_reconciling_figures():
    assert cpe.bind_statement(NPK_CONSOLIDATED, NPK_METRICS) == {'metric': 'revenue', 'basis': 'stated change'}
    assert cpe.bind_statement(GOOGL_REVENUE, GOOGL_METRICS) == {
        'metric': 'revenue', 'basis': 'stated level and growth rate'}
    assert cpe.bind_statement(GOOGL_OIE, GOOGL_METRICS) == {
        'metric': 'non-operating income (expense)', 'basis': 'stated change'}
    # Wrong direction, or an amount that does not reconcile, binds nothing.
    reversed_metrics = {'revenue': {'current': 120449000, 'prior': 146596000}}
    assert cpe.bind_statement(NPK_CONSOLIDATED, reversed_metrics) is None
    assert cpe.bind_statement(NPK_CONSOLIDATED.replace('26,147,000', '25,147,000'),
                              {'revenue': NPK_METRICS['revenue']}) is None
    assert cpe.bind_statement(GOOGL_REVENUE.replace('25%', '31%'), GOOGL_METRICS) is None


def test_components_need_consistent_figures_and_a_stated_cause():
    assert cpe.consistent_component(NPK_DEFENSE)
    assert cpe.consistent_component(NPK_HOUSEWARES)
    assert not cpe.consistent_component(NPK_DEFENSE.replace('$126,957,000', '$126,958,000'))
    assert not cpe.consistent_component(NPK_DEFENSE.split(', primarily')[0] + '.')


def test_bridge_only_when_net_and_operating_income_diverge():
    current, prior = ('2026-07-01', '2026-09-30'), ('2025-07-01', '2025-09-30')
    figures = {('current', 'OperatingIncomeLoss'): 40576, ('current', 'NonoperatingIncomeExpense'): -8221,
               ('current', 'IncomeTaxExpenseBenefit'): 5887, ('current', 'NetIncomeLoss'): 26468,
               ('prior', 'OperatingIncomeLoss'): 31228, ('prior', 'NonoperatingIncomeExpense'): 12759,
               ('prior', 'IncomeTaxExpenseBenefit'): 9008, ('prior', 'NetIncomeLoss'): 34979}

    def rows(values):
        return [(amount, {'concept': concept, 'start': (current if period == 'current' else prior)[0],
                          'end': (current if period == 'current' else prior)[1]})
                for (period, concept), amount in values.items()]

    bridge = cpe.earnings_bridge(rows(figures), current, prior)
    assert bridge['deltas']['NetIncomeLoss'] == -8511
    assert bridge['other_items'] == {'current': 26468 - (40576 - 8221 - 5887),
                                     'prior': 34979 - (31228 + 12759 - 9008)}
    # Same direction with a small non-operating change: no bridge.
    same_direction = {**figures, ('current', 'NetIncomeLoss'): 36000, ('current', 'NonoperatingIncomeExpense'): 12000}
    assert cpe.earnings_bridge(rows(same_direction), current, prior) is None
    # Same direction, but the non-operating change exceeds the operating change: bridge.
    material = {**figures, ('current', 'NetIncomeLoss'): 60000, ('current', 'NonoperatingIncomeExpense'): 30000}
    assert cpe.earnings_bridge(rows(material), current, prior)['deltas']['NonoperatingIncomeExpense'] == 30000 - 12759
    # An ambiguous duplicate fact is never resolved by picking one.
    duplicated = rows(figures) + [(1, {'concept': 'NetIncomeLoss', 'start': current[0], 'end': current[1]})]
    assert cpe.earnings_bridge(duplicated, current, prior) is None


def _value(monkeypatch, text, metrics):
    monkeypatch.setattr(cpe, '_metrics', lambda items: (metrics, ('2026-04-06', '2026-07-05',
                                                                  '2025-03-31', '2025-06-29')))
    return cpe.explanation_value(text, [], [], ticker='NPK', document_type='10-Q', filed_at='2026-08-14')


def test_explanation_keeps_the_latest_period_components(monkeypatch):
    later = 'For the first six months, Defense net sales increased by $5 from $1 to $6, primarily reflecting volume.'
    text = ' '.join([NPK_CONSOLIDATED, NPK_HOUSEWARES, NPK_DEFENSE,
                     'On a consolidated basis, year-to-date net sales increased.', later])
    value = _value(monkeypatch, text, NPK_METRICS)
    assert [s['metric'] for s in value['statements']] == ['revenue']
    assert [c['quote'] for c in value['components']] == [NPK_HOUSEWARES, NPK_DEFENSE]
    assert _value(monkeypatch, 'Net sales were stable.', NPK_METRICS) is None


def test_monitoring_criteria_restate_figures_and_attributions(monkeypatch):
    value = _value(monkeypatch, ' '.join([NPK_CONSOLIDATED, NPK_HOUSEWARES, NPK_DEFENSE]), NPK_METRICS)
    criteria = cpe.monitoring_criteria(value)
    assert criteria[0].startswith('Housewares/Small Appliance net sales: $19,083,000 versus $20,346,000 ')
    assert '“attributable to a decrease in units shipped”' in criteria[0]
    assert criteria[1].startswith('Defense net sales: $126,957,000 versus $99,813,000 ')
    # The consolidated statement states no cause, so it yields no driver test.
    assert len(criteria) == 2
    assert not any('%' in line.split('“')[0] for line in criteria)


def _item(value):
    value = dict(value)
    value['document_ref'] = ClaimDocumentReference(
        reference_id=f'document:{HASH}:current_period_explanation', title='NPK 10-Q', provider='SEC EDGAR',
        url=URL, published_at='2026-08-14', section=cpe.SECTION, content_hash=HASH,
        quote=value['statements'][0]['quote']).to_dict()
    return RetrievedEvidence(
        title='NPK latest-period change explanation', source='SEC EDGAR', summary=cpe.render(value),
        timestamp='2026-08-14', url=URL, relevance_score=0.97, source_type='regulatory_filing',
        source_tier='primary', claim_type='reported_fact', document_type='10-Q', filed_at='2026-08-14',
        section=cpe.SECTION, extraction_method='html', reporting_period_start='2026-04-06',
        reporting_period_end='2026-07-05', period_explanations=[value])


def test_bound_explanation_rechecks_every_stored_binding(monkeypatch):
    value = _value(monkeypatch, ' '.join([NPK_CONSOLIDATED, NPK_DEFENSE]), NPK_METRICS)
    item = _item(value)
    bound = cpe.bound_current_period_explanation(item, ticker='NPK', cik='80172')
    assert bound and bound['quote'] == NPK_CONSOLIDATED
    assert 'Management stated: “' + NPK_DEFENSE + '”' in item.summary
    assert cpe.bound_current_period_explanation(item, ticker='NPK', cik='80173') is None
    for tamper in (lambda v: v['statements'][0].update(quote=NPK_CONSOLIDATED.replace('22%', '29%')),
                   lambda v: v['components'][0].update(quote=NPK_DEFENSE.replace('$99,813,000', '$99,000,000')),
                   lambda v: v['metrics']['revenue'].update(current=146000000)):
        changed = _item(value)
        tamper(changed.period_explanations[0])
        assert cpe.bound_current_period_explanation(changed, ticker='NPK', cik='80172') is None
    edited = _item(value)
    edited.summary = edited.summary.replace('Management stated', 'Management confirmed', 1)
    assert cpe.bound_current_period_explanation(edited, ticker='NPK', cik='80172') is None


def test_results_discussion_quotes_are_bounded():
    reference = dict(reference_id=f'document:{HASH}:current_period_explanation', title='NPK 10-Q',
                     provider='SEC EDGAR', url=URL, section=cpe.SECTION, content_hash=HASH)
    assert ClaimDocumentReference(**reference, quote='x' * 900).quote
    try:
        ClaimDocumentReference(**reference, quote='x' * 901)
    except ValueError:
        pass
    else:
        raise AssertionError('an over-long quote must be refused, not truncated')
