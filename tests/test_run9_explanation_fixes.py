"""Run 9 explanation fixes. Synthetic prose shaped like retained 10-Q text; no network.

Covers: spaced-parenthesis table cells, genuine headings (and prose left alone),
cross-references as causes, and fiscal-quarter naming established from the filing.
"""
import re

from app.integrity.provenance import ClaimDocumentReference
from app.schemas import RetrievedEvidence
from app.services import current_period_explanation as cpe

URL = 'https://www.sec.gov/Archives/edgar/data/21535/000002153526000040/synthetic-20260926.htm'
HASH = 'b' * 64
PERIOD = ('2026-06-28', '2026-09-26', '2025-06-29', '2025-09-27')
PERIOD_DICT = dict(zip(('current_start', 'current_end', 'prior_start', 'prior_end'), PERIOD))
METRICS = {'revenue': {'current': 173000000, 'prior': 126200000}}
TABLE_ROWS = ('Research and development (14.8 )% (17.8 )% (17.2 )% (20.8 )% '
              'Selling, general and administrative (18.9 )% (25.2 )% (22.8 )% (27.7 )% '
              'Income (loss) from operations 7.4 % (7.7 )% 0.4 % (16.4 )% ')
HEADING = 'Third Quarter of Fiscal 2026 Compared to Third Quarter of Fiscal 2025 Net Sales '
DRIVER = ('Net sales for the third quarter of fiscal 2026 increased compared to the same period in fiscal 2025, '
          'primarily driven by stronger demand across several applications and end markets.')
LEAD = ('The following table summarizes operating data as a percentage of net sales: Three Months Ended '
        'Nine Months Ended September 26, September 27, September 26, September 27, 2026 2025 2026 2025 '
        'Net sales 100.0 % 100.0 % 100.0 % 100.0 % Gross margin 45.5 % 43.8 % 45.7 % 43.7 % ')
SALES = 'Our consolidated net sales increased 37.0% to $173.0 million in 2026, compared to $126.2 million in 2025. '
OBSERVATIONS = [(1, {'concept': 'OperatingIncomeLoss', 'start': PERIOD[0], 'end': PERIOD[1]}),
                (1, {'concept': 'OperatingIncomeLoss', 'start': '2025-12-28', 'end': PERIOD[1]})]


def text(heading=HEADING):
    return LEAD + TABLE_ROWS + heading + SALES + DRIVER + ' Meanwhile, demand in other markets was stable.'


def value(monkeypatch, body, observations=OBSERVATIONS):
    monkeypatch.setattr(cpe, '_metrics', lambda items: (dict(METRICS), PERIOD))
    return cpe.explanation_value(body, observations, [], ticker='SYNT', document_type='10-Q', filed_at='2026-10-29')


def quotes(result):
    return [row['quote'] for row in result['statements'] + result['components']]


# --- table cells ---------------------------------------------------------------------------------

def test_spaced_parenthesis_cells_count_as_table_cells():
    for cells in ('(14.8 )% (17.8 )% (17.2 )% ', '$ (313.1 ) $ 53.2 $ (323.1 ) ', '(62.3 %) 9.6 % (23.3 %) ',
                  '$ 1,234 $ 2,345 $ 3,456 '):
        assert cpe._NUMBER_RUN.search(cells), cells
    assert not cpe._NUMBER_RUN.search('We hired 3 people in 2026 and 5 more later in the year.')


def test_a_narrative_sentence_is_split_from_a_spaced_parenthesis_table():
    body = text()
    plain = [s for _, s in cpe.sentences(body)]
    split = [s for _, s in cpe.sentences(body, split_tables=True)]
    assert any('(14.8 )%' in s and 'Our consolidated net sales' in s for s in plain)
    assert not any('(14.8 )%' in s and 'Our consolidated net sales' in s for s in split)
    assert any(s.endswith('in 2025.') and '(' not in s for s in split)


# --- headings --------------------------------------------------------------------------------------

def test_a_title_case_heading_with_function_words_is_removed_once():
    sentence = HEADING + SALES.strip()
    start = next(cpe.clause_starts(sentence))
    assert sentence[start:].startswith('Our consolidated net sales increased 37.0%')


def test_a_repeated_heading_is_not_left_behind():
    sentence = ('Three Months Ended June 30, 2026 Compared to Three Months Ended June 30, 2025 Revenues Revenues were '
                '$5.0 billion for the three months ended June 30, 2026, an increase of $1.3 billion compared to '
                '$3.7 billion for the three months ended June 30, 2025.')
    quote = sentence[next(cpe.clause_starts(sentence)):]
    assert quote.startswith('Revenues were $5.0 billion') and 'Revenues Revenues' not in quote


def test_prose_is_never_stripped_as_a_heading():
    for sentence in ('Revenue and income grew in the third quarter of fiscal 2026 compared to the prior period.',
                     'Results Rose Sharply Net sales were $10 million because of volume.',
                     'Management noted that Revenues Revenues were affected by timing.',
                     'Results Due To Volume Net sales were $10 million.'):
        assert list(cpe.clause_starts(sentence)) == [0], sentence


# --- cross-references --------------------------------------------------------------------------------

def test_a_cross_reference_is_not_a_cause():
    for sentence in ('As a result of the factors set forth above, our net income was $12.1 million.',
                     'These decreases were driven by the factors discussed above in “ Net income from operations ”.',
                     'Net sales declined, primarily due to the items described below.'):
        assert cpe.cause_match(sentence) is None, sentence
    for sentence in ('Net sales declined, primarily due to lower unit volume.',
                     'Net sales declined primarily due to the factors affecting our largest customer.'):
        assert cpe.cause_match(sentence), sentence
    previous = ('Net income decreased by $366.3 million and $401.3 million during the three and nine months '
                'ended September 30, 2026 when compared to the same periods in 2025.')
    period = {'current_start': '2026-07-01', 'current_end': '2026-09-30',
              'prior_start': '2025-07-01', 'prior_end': '2025-09-30'}
    assert not cpe.following_cause(previous, 'These decreases were driven by the factors discussed above.', period)
    assert cpe.following_cause(previous, 'These decreases were driven by higher legal reserves.', period)


# --- fiscal quarters -----------------------------------------------------------------------------------

def test_the_actual_driver_is_recovered_and_the_table_fragment_is_not_quoted(monkeypatch):
    result = value(monkeypatch, text())
    assert result['period']['fiscal_quarter']['ordinal'] == 'third'
    assert quotes(result) == [DRIVER]
    assert not any('(14.8' in q or 'factors set forth' in q for q in quotes(result))


def test_without_the_filings_own_comparison_heading_no_fiscal_naming_is_bound(monkeypatch):
    result = value(monkeypatch, text('Net Sales '))
    assert 'fiscal_quarter' not in result['period']
    assert not any('primarily driven' in q for q in quotes(result))


def test_ambiguous_or_inconsistent_naming_binds_nothing(monkeypatch):
    two = text() + 'Third Quarter of Fiscal 2027 Compared to Third Quarter of Fiscal 2026 Net Sales '
    assert 'fiscal_quarter' not in value(monkeypatch, two)['period']
    far = text().replace('Fiscal 2026 Compared to Third Quarter of Fiscal 2025', 'Fiscal 2030 Compared to Third Quarter of Fiscal 2029')
    assert 'fiscal_quarter' not in value(monkeypatch, far)['period']
    # No year-to-date context ending on the quarter's last day: the quarter number is unknown.
    assert 'fiscal_quarter' not in value(monkeypatch, text(), OBSERVATIONS[:1])['period']
    # A year-to-date span that implies a different quarter than the heading names.
    first_half = [OBSERVATIONS[0], (1, {'concept': 'OperatingIncomeLoss', 'start': '2026-03-29', 'end': PERIOD[1]})]
    assert 'fiscal_quarter' not in value(monkeypatch, text(), first_half)['period']


def _item(result):
    result = dict(result)
    result['document_ref'] = ClaimDocumentReference(
        reference_id=f'document:{HASH}:current_period_explanation', title='SYNT 10-Q', provider='SEC EDGAR',
        url=URL, published_at='2026-10-29', section=cpe.SECTION, content_hash=HASH,
        quote=result['statements'][0]['quote']).to_dict()
    return RetrievedEvidence(
        title='SYNT latest-period change explanation', source='SEC EDGAR', summary=cpe.render(result),
        timestamp='2026-10-29', url=URL, relevance_score=0.97, source_type='regulatory_filing',
        source_tier='primary', claim_type='reported_fact', document_type='10-Q', filed_at='2026-10-29',
        section=cpe.SECTION, extraction_method='html', reporting_period_start=PERIOD[0],
        reporting_period_end=PERIOD[1], period_explanations=[result])


def test_the_fiscal_naming_is_rechecked_when_the_explanation_is_bound(monkeypatch):
    result = value(monkeypatch, text())
    assert cpe.bound_current_period_explanation(_item(result), ticker='SYNT', cik='21535')
    for tamper in (lambda p: p['fiscal_quarter'].update(fiscal_year=2027),
                   lambda p: p['fiscal_quarter'].update(ordinal='second'),
                   lambda p: p['fiscal_quarter'].update(year_to_date_start='2025-01-01'),
                   lambda p: p['fiscal_quarter'].update(heading_quote='Third Quarter of Fiscal 2026'),
                   lambda p: p.update(fiscal_quarter={'ordinal': 'third'})):
        item = _item(result)
        tamper(item.period_explanations[0]['period'])
        assert cpe.bound_current_period_explanation(item, ticker='SYNT', cik='21535') is None
    # Naming that was never established cannot be smuggled in afterwards.
    plain = value(monkeypatch, text('Net Sales '))
    forged = _item(plain)
    forged.period_explanations[0]['period']['fiscal_quarter'] = result['period']['fiscal_quarter']
    assert cpe.bound_current_period_explanation(forged, ticker='SYNT', cik='21535') is None


def test_a_calendar_quarter_is_still_named_as_before():
    names = [p.pattern for p in cpe.current_period_patterns(
        {'current_start': '2026-07-01', 'current_end': '2026-09-30', 'prior_start': '2025-07-01', 'prior_end': '2025-09-30'})]
    assert any('third' in n for n in names) and not any('fiscal' in n for n in names)
