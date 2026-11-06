"""A cause in the next sentence, and segment scope given by a table heading.

Excerpts are from 10-Qs retained in ordinary run 2 (INGR, NNBR); the negative
cases change one fact: the period, the segment, the direction or the figures.
"""
from app.services import current_period_explanation as cpe

Q2 = {'current_start': '2026-04-01', 'current_end': '2026-06-30', 'prior_start': '2025-04-01', 'prior_end': '2025-06-30'}
Q3 = {'current_start': '2026-07-01', 'current_end': '2026-09-30', 'prior_start': '2025-07-01', 'prior_end': '2025-09-30'}
SEGMENT = ('F&II–U.S./Canada operating income decreased 33 percent to $58 million for the second quarter of 2026 '
           'from $86 million for the second quarter of 2025.')
CAUSE = 'The decrease resulted primarily from production challenges at our Argo facility as well as softer volumes.'
CONSOLIDATED = 'Net income for the second quarter of 2026 decreased to $114 million from $196 million for the second quarter of 2025.'
METRICS = {'net income': {'current': 114000000, 'prior': 196000000}, 'revenue': {'current': 1850000000, 'prior': 1833000000}}


def test_the_next_sentence_explains_a_verified_change():
    assert cpe.following_cause(SEGMENT, CAUSE, Q2)
    assert cpe.internally_consistent(SEGMENT)
    assert cpe.segment_attribution(SEGMENT, METRICS, Q2, following=CAUSE)
    assert cpe.following_cause(CONSOLIDATED, 'The decrease was primarily due to lower gross profit.', Q2)


def test_ambiguous_or_mismatched_next_sentences_are_rejected():
    for following in (
            'The decrease for the six months ended June 30, 2026 resulted primarily from production challenges.',
            'The decrease in North America operating income was primarily due to lower volumes.',
            'The increase resulted primarily from higher volumes.',              # direction
            'Production challenges at our Argo facility reduced volumes.',        # no reference back
            'The decrease was significant.',                                      # no cause
            'The decrease in 2025 resulted primarily from production challenges.'):  # another year
        assert not cpe.following_cause(SEGMENT, following, Q2), following
    # A sentence that already states its own cause takes no second one.
    assert not cpe.following_cause(SEGMENT[:-1] + ', primarily due to volumes.', CAUSE, Q2)
    # Figures that do not agree cannot borrow a cause.
    wrong = SEGMENT.replace('33 percent', '20 percent')
    assert not cpe.internally_consistent(wrong)
    assert not cpe.segment_attribution(wrong, METRICS, Q2, following=CAUSE)


TABLE = ('MOBILE SOLUTIONS Three Months Ended September 30, 2026 2025 $ Change Net sales $ 68,177 $ 59,117 $ 9,060 '
         'Loss from operations $ (6,288) $ (2,854) $ (3,434) ')
SALES = ('Net sales increased by $9.1 million, or 15.3%, during the three months ended September 30, 2026, compared to '
         'the three months ended September 30, 2025, primarily due to higher volumes.')
LOSS = ('Loss from operations increased by $3.4 million or 120.3% during the three months ended September 30, 2026, '
        'compared to the same period in the prior year.')
LOSS_CAUSE = 'The increase was primarily due to higher costs from volume increases and increased labor costs.'


def test_table_heading_scopes_a_reconciled_narrative():
    [block] = cpe.table_blocks(TABLE + SALES, Q3)
    assert block['heading'] == 'MOBILE SOLUTIONS'
    assert block['rows']['net sales'] == (68177, 59117, 9060)
    assert block['rows']['loss from operations'] == (-6288, -2854, -3434)
    assert cpe.table_scoped(SALES, block, Q3)
    assert cpe.table_scoped(LOSS, block, Q3, following=LOSS_CAUSE)
    assert not cpe.table_scoped(LOSS, block, Q3)  # no cause anywhere


def test_table_scope_needs_the_same_period_row_and_figure():
    assert cpe.table_blocks(TABLE.replace('Three Months', 'Nine Months') + SALES, Q3) == []
    assert cpe.table_blocks(TABLE.replace('September 30, 2026', 'June 30, 2026') + SALES, Q3) == []
    [block] = cpe.table_blocks(TABLE + SALES, Q3)
    assert not cpe.table_scoped(SALES.replace('$9.1 million', '$9.6 million'), block, Q3)
    assert not cpe.table_scoped(SALES.replace('Net sales', 'Gross profit'), block, Q3)
    assert not cpe.table_scoped(SALES.replace('three months ended September 30, 2026', 'nine months ended '
                                              'September 30, 2026'), block, Q3)


def test_segment_table_discussion_is_never_a_consolidated_statement(monkeypatch):
    # The segment's $9.1 million change would be misread as the company's if it were.
    metrics = {'revenue': {'current': 131085000, 'prior': 121985000}}
    monkeypatch.setattr(cpe, '_metrics', lambda items: (dict(metrics), tuple(Q3.values())))
    value = cpe.explanation_value(TABLE + SALES, [], [], ticker='X', document_type='10-Q', filed_at='2026-10-28')
    assert value['statements'] == []
    [component] = value['components']
    assert component['basis'] == 'table-scoped segment attribution'
    assert component['scope_heading'] == 'MOBILE SOLUTIONS'
    assert 'for the segment its table is headed “MOBILE SOLUTIONS”' in cpe.render(value)
