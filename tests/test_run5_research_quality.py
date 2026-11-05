"""General causes of the run-5 research gaps, reproduced offline.

Run 5 (unseen cohort 2) is development evidence from here on. No rule names
an issuer; fixtures are invented or short passages of the retained filings.
"""
from app.services import verified_sec_metric_service as producer
from app.services.financial_thesis_foundation import CORE_METRICS
from test_verified_sec_metrics import _record

INCLUDING = 'RevenueFromContractWithCustomerIncludingAssessedTax'


def _pair(concept, current=120, prior=100, year=2026):
    return [_record(concept=concept, value=prior, start=f'{year - 1}-04-01', end=f'{year - 1}-06-30',
                    filed=f'{year - 1}-08-01', accession=f'0000320193-{(year - 1) % 100}-000001'),
            _record(concept=concept, value=current, start=f'{year}-04-01', end=f'{year}-06-30',
                    filed=f'{year}-08-01', accession=f'0000320193-{year % 100}-000001')]


def _revenue(monkeypatch, records):
    monkeypatch.setattr(producer, '_load_ticker_cik_map', lambda: {'AAPL': '320193'})
    monkeypatch.setattr(producer, 'get_company_fact_records_for_concept_units', lambda *a, **kw: records)
    items = producer.fetch_verified_metric_evidence('AAPL', question='Cite revenue trends')
    return [i for i in items if 'revenue' in i.summary.lower()]


def test_revenue_tagged_only_including_assessed_tax_is_a_revenue_comparison(monkeypatch):
    item, = _revenue(monkeypatch, _pair(INCLUDING))
    assert {c['metric'] for c in item.verified_claims} == {f'us-gaap:{INCLUDING}'}
    assert 'revenue from contracts with customers including assessed taxes increased 20.0%' in item.summary
    assert INCLUDING in CORE_METRICS['revenue']


def test_an_equal_period_tie_keeps_the_previously_selected_concept(monkeypatch):
    # Both concepts for the same periods: the earlier-configured concept wins,
    # values are never joined across concepts.
    item, = _revenue(monkeypatch, _pair('Revenues', 120, 100) + _pair(INCLUDING, 125, 104))
    assert {c['metric'] for c in item.verified_claims} == {'us-gaap:Revenues'}


def test_a_more_recent_including_pair_replaces_a_stale_preferred_pair(monkeypatch):
    item, = _revenue(monkeypatch, _pair('Revenues', year=2025) + _pair(INCLUDING, year=2026))
    assert item.reporting_period_end == '2026-06-30'
    assert {c['metric'] for c in item.verified_claims} == {f'us-gaap:{INCLUDING}'}


# -- explanations through operating-expense lines ---------------------------------

from app.services import current_period_explanation as cpe
from app.services import issuer_risk_evidence as ire
from app.services import risk_selection
from app.services.thesis_disclosures import _business_quote_rejection

PERIOD = {'current_start': '2026-04-01', 'current_end': '2026-06-30',
          'prior_start': '2025-04-01', 'prior_end': '2025-06-30'}
RD = ('Research and development expense decreased 45% to $14.8 million for the three months ended June 30, 2026 '
      'from $26.7 million for the three months ended June 30, 2025.')
RD_CAUSE = ('The decreased expenses in the three months ended June 30, 2026 primarily relate to a $4.5 million decrease '
            'in personnel related expenses, substantially due to a decrease in headcount due to the sale of our '
            'manufacturing operations in January 2026, a $3.1 million decrease in other research and development '
            'expenses, primarily attributable to a decrease in facility and depreciation expense due to the sale of '
            'our manufacturing operations in January 2026, and a $4.3 million decrease in expenses related to the '
            'timing of clinical trial activity and other items that are described elsewhere in this quarterly report.')
RD_METRICS = {'research and development expense': {'current': 14800000, 'prior': 26700000}}


def test_an_expense_line_statement_binds_only_when_it_reconciles():
    assert cpe.bind_statement(RD, RD_METRICS)['metric'] == 'research and development expense'
    assert cpe.bind_statement(RD, {'research and development expense': {'current': 15800000, 'prior': 26700000}}) is None
    assert cpe.bind_statement(RD.replace('decreased', 'increased'), RD_METRICS) is None


def test_a_long_cause_is_quoted_verbatim_up_to_a_clause_boundary():
    assert len(RD_CAUSE) > cpe.MAX_SENTENCE
    excerpt = cpe.cause_excerpt(RD_CAUSE)
    assert RD_CAUSE.startswith(excerpt) and len(excerpt) <= cpe.MAX_SENTENCE
    assert excerpt.endswith('January 2026') and 'primarily relate to' in excerpt
    assert cpe.following_cause(RD, RD_CAUSE, PERIOD)
    # A long sentence with no clause boundary within the limit is still refused.
    assert cpe.cause_excerpt('The decrease was primarily ' + 'due to lower costs ' * 40 + '.') is None


def test_a_labelled_bullet_is_quoted_from_its_own_statement():
    sentence = ('Financial highlights compared to the same periods in the prior fiscal year: • For the three months '
                'ended June 30, 2026, revenues increased 23.2% to $118.4 million.')
    assert sentence[next(cpe.clause_starts(sentence)):].startswith('For the three months ended June 30, 2026')


# -- risks and business descriptions ------------------------------------------------

HEADED = ('Risks Related to the Development of Our Product Candidates • Our business is highly dependent on the '
          'success of botensilimab and our combination therapy programs.')
HEADED_2 = ('Risks Related to the Development of Our Product Candidates Our business is highly dependent on the success '
            'of our clinical stage programs, including botensilimab and related combination therapy programs, which '
            'still require significant additional clinical development.')


def test_a_run_in_risk_section_heading_is_removed_verbatim():
    for quote in (HEADED, HEADED_2):
        heading = ire.RUN_IN_RISK_HEADING.match(quote)
        assert heading and quote[heading.end():].startswith('Our business is highly dependent')
    # Run 2 (GOOGL): the whole "Risks Specific to our Company" heading goes, never just "Risks".
    quote = 'Risks Specific to our Company We generate a significant portion of our revenues from advertising.'
    heading = ire.RUN_IN_RISK_HEADING.match(quote)
    assert heading and quote[heading.end():] == 'We generate a significant portion of our revenues from advertising.'
    # An ordinary risk sentence is untouched, and a capitalized product name is not a heading.
    assert not ire.RUN_IN_RISK_HEADING.match('Risks to our supply chain could reduce revenue from our largest customers.')
    assert not ire.RUN_IN_RISK_HEADING.match('Our business is highly dependent on the success of our products.')


def test_near_duplicate_risks_are_kept_once():
    first, second = HEADED.split('• ')[1], HEADED_2.split('Candidates ')[1]
    assert risk_selection.near_duplicate(first, second)
    assert not risk_selection.near_duplicate(first, 'A significant portion of our revenue comes from customers '
                                                    'in Peru, so local political changes could reduce our sales.')
    # Same wording, different risk: customer versus supplier concentration stays two risks.
    customers = ('We depend on a limited number of customers, and the loss of any of them would adversely '
                 'affect our business.')
    assert not risk_selection.near_duplicate(customers, customers.replace('customers', 'suppliers'))
    selected, reasons = risk_selection.select_risks([first, second], quote_of=lambda q: q, offset_of=lambda q: 0)
    assert len(selected) == 1 and 'near_duplicate' in reasons


def test_rights_and_non_dependence_statements_are_not_business_descriptions():
    assert _business_quote_rejection(
        'The Company’s business segments are not dependent upon any individual patents or related group of patents, '
        'nor upon any individual licenses or distribution rights.') == 'not_a_business_description'
    assert _business_quote_rejection(
        'We hold patents covering certain aspects of our rail welding and track monitoring technologies.') == \
        'not_a_business_description'
    # A description that mentions licences alongside what the business sells is kept.
    for kept in ('We provide software and related services to hospitals, including licenses to our clinical analytics '
                 'platform.',
                 'We sell rail products and provide track services to railroads, including products made under our own '
                 'patents.'):
        assert _business_quote_rejection(kept) is None


# -- revenue components through an exact member reconciliation ----------------------

from app.providers.sec_inline_facts import parse_inline_observations, parse_member_observations, validated_observation

_NS = ('xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
       'xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
       'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:us-gaap="http://fasb.org/us-gaap/2026" '
       'xmlns:srt="http://fasb.org/srt/2026" xmlns:abc="http://abc.example/2026" '
       'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"')


def _context(cid, start, end, member=None, extra_axis=False):
    segment = ''
    if member:
        segment = f'<xbrli:segment><xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">abc:{member}</xbrldi:explicitMember>'
        if extra_axis:
            segment += '<xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">abc:USMember</xbrldi:explicitMember>'
        segment += '</xbrli:segment>'
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000123'
            f'</xbrli:identifier>{segment}</xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate>'
            f'<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>')


def _fact(fid, cid, value):
    return (f'<ix:nonFraction id="{fid}" name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" '
            f'contextRef="{cid}" unitRef="usd" decimals="-3" scale="3" format="ixt:num-dot-decimal">{value}</ix:nonFraction>')


def _filing(royalty_prior='24,831'):
    periods = {'c': ('2026-04-01', '2026-06-30'), 'p': ('2025-04-01', '2025-06-30')}
    rows = {'c': [('Total', None, '34,518'), ('Roy', 'NonCashRoyaltyRevenueMember', '28,146'),
                  ('Pre', 'PreCommercialProductRevenueMember', '6,372')],
            'p': [('Total', None, '25,691'), ('Roy', 'NonCashRoyaltyRevenueMember', royalty_prior),
                  ('Rnd', 'ResearchAndDevelopmentRevenueMember', '334'), ('Oth', 'OtherMember', '526')]}
    contexts, facts = [], []
    for key, entries in rows.items():
        for name, member, value in entries:
            contexts.append(_context(f'{key}{name}', *periods[key], member))
            facts.append(_fact(f'f{key}{name}', f'{key}{name}', value))
    # A two-axis context is not a product-or-service disaggregation.
    contexts.append(_context('cGeo', *periods['c'], 'NonCashRoyaltyRevenueMember', extra_axis=True))
    facts.append(_fact('fcGeo', 'cGeo', '28,146'))
    return (f'<html {_NS}><body><ix:header><ix:resources>{"".join(contexts)}'
            '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            f'</ix:resources></ix:header>{"".join(facts)}</body></html>')


REV = ('RevenueFromContractWithCustomerExcludingAssessedTax',)
CURRENT, PRIOR = ('2026-04-01', '2026-06-30'), ('2025-04-01', '2025-06-30')
ROYALTY = ('Non-cash royalty revenue related to our agreement with GSK increased $3.3 million, to approximately '
           '$28.1 million for the three months ended June 30, 2026, from $24.8 million for the three months ended '
           'June 30, 2025, due to increased net sales of the partner’s vaccines containing our adjuvant.')


def _members(text):
    from app.providers.sec_inline_facts import validated_member_observation
    return [(amount, row) for row in parse_member_observations(text, cik='123', concepts=REV)
            if (amount := validated_member_observation(row, cik='123', concepts=REV)) is not None]


def test_member_facts_are_opt_in_and_never_consolidated():
    text = _filing()
    consolidated = parse_inline_observations(text, cik='123', concepts=REV)
    assert {row['fact_id'] for row in consolidated} == {'fcTotal', 'fpTotal'}
    members = parse_member_observations(text, cik='123', concepts=REV)
    assert {row['member'] for row in members} == {'NonCashRoyaltyRevenueMember', 'PreCommercialProductRevenueMember',
                                                  'ResearchAndDevelopmentRevenueMember', 'OtherMember'}
    assert 'fcGeo' not in {row['fact_id'] for row in members}       # two axes: not a disaggregation
    assert all(validated_observation(row, cik='123', concepts=REV) is None for row in members)


def test_a_revenue_component_needs_an_exact_reconciliation_in_both_periods():
    revenue = {'current': 34518000, 'prior': 25691000}
    components = cpe.revenue_components(_members(_filing()), revenue, CURRENT, PRIOR)
    assert components == {'non cash royalty revenue': {'current': 28146000, 'prior': 24831000}}
    assert cpe.bind_statement(ROYALTY, {'revenue': revenue, **components})['metric'] == 'non cash royalty revenue'
    # Members that do not sum to reported revenue in a period bind nothing.
    assert cpe.revenue_components(_members(_filing(royalty_prior='24,832')), revenue, CURRENT, PRIOR) == {}
    assert cpe.revenue_components(_members(_filing()), {'current': 34518000, 'prior': 25690000}, CURRENT, PRIOR) == {}
