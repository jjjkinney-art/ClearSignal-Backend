"""General causes of the run-4 research gaps, reproduced offline.

Excerpts are short passages from retained SEC filings of the run-4 cohort
(now exposed development evidence): Southern Copper and Las Vegas Sands 10-Qs
for the quarter ended 2026-09-30, and risk/business sentences from 10-Ks. No
network access is used; no rule names an issuer.
"""
import json

import pytest

from app.providers import sec_client
from app.services import current_period_explanation as cpe
from app.services import issuer_risk_evidence as ire
from app.services import risk_selection
from app.services import sec_risk_sections as sections
from app.services.financial_thesis_foundation import SECTOR_GAPS, SECTOR_METRICS, SECTOR_SIGNATURES, issuer_sector
from app.services.providers import sec_provider
from app.services.thesis_disclosures import _business_quote_rejection

PERIOD = {'current_start': '2026-07-01', 'current_end': '2026-09-30',
          'prior_start': '2025-07-01', 'prior_end': '2025-09-30'}

# A results table flattened into text, then the narrative sentence after it.
COPPER_TABLE = ('Earnings : The table below highlights key financial and operational data (in millions): '
                'Three months ended September 30, 2026 2025 Variance % Change Copper price LME 6.41 4.44 1.97 44.4 % '
                'Pounds of copper sold 514.3 516.5 (2.3) (0.4) % Net sales $ 4,696.6 $ 3,377.3 $ 1,319.3 39.1 % '
                'Operating income $ 2,815.1 $ 1,768.8 $ 1,046.4 59.2 % Net income attributable to SCC $ 1,801.8 '
                '$ 1,107.6 $ 694.1 62.7 % Earnings per share $ 2.15 $ 1.32 $ 0.83 62.7 % Cash dividends paid $ 1.10 '
                '$ 0.80 $ 0.30 37.5 % Stock dividends paid $ 2.13 $ 1.00 $ 1.13 113.0 % Cash dividends declared '
                '$ 1.20 $ 0.80 $ 0.40 50.0 % Shares outstanding 803.1 805.4 (2.3) (0.3) % Average shares 803.2 '
                '805.6 (2.4) (0.3) % ')
COPPER_STATEMENT = ('Net sales in the third quarter of 2026 totaled $4,696.6 million, which represented a 39.1% '
                    'increase compared to the figure recorded in the same period in 2025.')
COPPER_CAUSE = ('This increase was primarily driven by an increase in the sales volumes of zinc (+0.8%) and higher '
                'prices for copper (LME, +44.4%; COMEX, +34.2%), molybdenum (+35.5%), silver (+58.7%), and zinc (+35.9%).')
COPPER_METRICS = {'revenue': {'current': 4696600000, 'prior': 3377300000}}

RESORT_TABLE = ('Three Months Ended September 30, 2026 2025 Dollar Change Percent Change (Dollars in millions) '
                'Casino $ 2,370 $ 2,506 $ (136) (5.4) % Rooms 376 374 2 0.5 % Mall 202 199 3 1.5 % '
                'Total net revenues $ 3,216 $ 3,331 $ (115) (3.5) %')
RESORT_CAUSE = ('Consolidated net revenues decreased due to a $142 million decrease at Marina Bay Sands, '
                'partially offset by a $27 million increase at our Macao operations.')
RESORT_METRICS = {'revenue': {'current': 3216000000, 'prior': 3331000000}}


def test_a_narrative_sentence_run_onto_a_flattened_table_is_split_off():
    text = COPPER_TABLE + COPPER_STATEMENT + ' ' + COPPER_CAUSE
    parts = [sentence for _, sentence in cpe.sentences(text)]
    assert COPPER_STATEMENT in parts and COPPER_CAUSE in parts
    # Offsets still address the source text exactly.
    assert all(text[offset:offset + len(sentence)] == sentence for offset, sentence in cpe.sentences(text))
    # Ordinary prose with figures is never split.
    assert [s for _, s in cpe.sentences(COPPER_STATEMENT)] == [COPPER_STATEMENT]


def test_a_stated_level_with_an_article_rate_binds_only_when_it_reconciles():
    assert cpe.bind_statement(COPPER_STATEMENT, COPPER_METRICS) == {
        'metric': 'revenue', 'basis': 'stated level and growth rate'}
    assert cpe.bind_statement(COPPER_STATEMENT.replace('39.1%', '45.1%'), COPPER_METRICS) is None
    assert cpe.bind_statement(COPPER_STATEMENT, {'revenue': {'current': 3377300000, 'prior': 4696600000}}) is None


def test_a_cause_after_a_current_period_table_binds_when_its_parts_net_to_the_change():
    assert cpe.bind_table_narrative(RESORT_CAUSE, RESORT_METRICS, RESORT_TABLE, PERIOD) == {
        'metric': 'revenue', 'basis': 'table-anchored attribution'}
    # Parts that do not net to the reported change, a table for another period,
    # a row that does not reconcile, or the wrong direction bind nothing.
    assert cpe.bind_table_narrative(RESORT_CAUSE.replace('$142', '$152'), RESORT_METRICS, RESORT_TABLE, PERIOD) is None
    assert cpe.bind_table_narrative(RESORT_CAUSE, RESORT_METRICS, RESORT_TABLE.replace('2026', '2024', 1), PERIOD) is None
    assert cpe.bind_table_narrative(RESORT_CAUSE, RESORT_METRICS, RESORT_TABLE.replace('3,216', '3,219'), PERIOD) is None
    assert cpe.bind_table_narrative(RESORT_CAUSE, {'revenue': {'current': 3331000000, 'prior': 3216000000}},
                                    RESORT_TABLE.replace('$ 3,216 $ 3,331', '$ 3,331 $ 3,216'), PERIOD) is None
    assert cpe.bind_table_narrative(RESORT_CAUSE.replace('due to', 'alongside'), RESORT_METRICS, RESORT_TABLE, PERIOD) is None


def test_explanation_gate_accepts_issuers_without_a_revenue_line():
    class Item:
        def __init__(self, metric, current, prior):
            claim = {'metric': metric, 'period_start': '2026-04-01', 'period_end': '2026-06-30'}
            self.verified_claims = [dict(claim, raw_value=current),
                                    dict(claim, raw_value=prior, period_start='2025-04-01', period_end='2025-06-30')]
    statement = ('Net income for the three months ended June 30, 2026 increased $1.0 million to $9.1 million, '
                 'primarily due to higher net interest income.')
    value = cpe.explanation_value(statement, [], [Item('us-gaap:NetIncomeLoss', 9078000, 8078000)],
                                  ticker='BANK', document_type='10-Q', filed_at='2026-08-07')
    assert value and value['statements'][0]['metric'] == 'net income'
    assert cpe.explanation_value(statement, [], [], ticker='BANK', document_type='10-Q', filed_at='2026-08-07') is None


@pytest.mark.parametrize('heading', ['ITEM 1A. — RISK FACTORS', 'Item 1A. Risk Factors', 'ITEM 1A — RISK FACTORS'])
def test_item_headings_with_a_period_and_a_dash(heading):
    assert sections.RISK_START.search(heading)
    assert sections.RISK_END.search('ITEM 1B. — UNRESOLVED STAFF COMMENTS None.')
    assert sections.BUSINESS_START.search('ITEM 1. — BUSINESS Our Company')


def test_results_section_is_the_longest_span_not_the_table_of_contents():
    text = ('Item 2. Management’s Discussion and Analysis 30 Item 3. Quantitative and Qualitative Disclosures 50 '
            + 'x ' * 50 + 'Item 2. Management’s Discussion and Analysis of Financial Condition '
            + 'Results discussion. ' * 40 + 'Item 3. Quantitative and Qualitative Disclosures About Market Risk')
    start, end = sections.results_section_bounds(text, form='10-Q')
    assert text[start:].startswith('Item 2. Management’s Discussion and Analysis of Financial Condition')
    assert text[end:].startswith('Item 3. Quantitative')
    assert sections.results_section_bounds(text, form='8-K') is None


@pytest.mark.parametrize('quote,reason', [
    ('Blackstone offers a wide range of learning and professional development opportunities, both formally and '
     'informally, to help employees advance their careers and maximize the value they can add to the global firm.',
     'internal_employee_activity'),
    ('We also offer employee well-being programs that provide information, tools and resources, including '
     'connections to mental health support.', 'internal_employee_activity'),
    ('We provide data privacy training at onboarding to new employees and at least annually to existing employees.',
     'internal_employee_activity'),
    ('We offer, free of charge, downloads of our annual, quarterly and current reports, as soon as they can be '
     'reasonably made available following electronic or physical filing with the SEC.', 'filing_availability'),
    ('We offer employee benefits administration software to customers through subscription contracts.', None),
    ('We provide professional development courses to teachers in public school districts.', None),
    ('We sell our products directly to consumers through our website and retail stores.', None),
])
def test_business_descriptions_exclude_human_capital_and_filing_availability(quote, reason):
    assert _business_quote_rejection(quote) == reason


@pytest.mark.parametrize('quote', [
    'Our financial performance is highly dependent on the price of copper and the other metals we produce.',
    'A significant portion of our operations is conducted in Peru.',
    'We are primarily dependent upon our Asia properties for all of our cash flow.',
    'Our business operations and lending activities are concentrated in South Florida, and we are more sensitive '
    'to adverse changes in the local economy than our more geographically diversified competitors.',
])
def test_a_stated_dependency_or_concentration_is_admitted_and_company_specific(quote):
    scope = 'Commodity prices' if 'price' in quote else 'Operating concentration'
    profile = ire.IssuerRiskProfile('1', scope, ire._TOPICS[scope])
    assert ire.risk_quote_rejections(quote, profile) == ()
    assert risk_selection.qualifies(quote) and risk_selection.specificity(quote) >= 3
    # The topic is reachable from the thesis question that requests it.
    assert ire._has_topic_scope(f'What operating risk affects {scope}?', profile)


def test_generic_risks_and_run_in_section_headings_stay_unspecific():
    generic = ('General Risk Factors Failure to maintain the integrity of our information and information systems '
               'could adversely affect our business.')
    assert risk_selection.specificity(generic) == 0 and not risk_selection.qualifies(generic)
    profile = ire.IssuerRiskProfile('1', 'Operating concentration', ire._TOPICS['Operating concentration'])
    assert ire.risk_quote_rejections('Our operations are conducted in several countries.', profile)


@pytest.mark.parametrize('reported,accepted', [(1901637, True), ('0001901637', True), ('0001901638', False), ('', False)])
def test_company_facts_identity_compares_cik_values(monkeypatch, reported, accepted):
    body = {'cik': reported, 'facts': {'us-gaap': {'NetIncomeLoss': {'label': 'Net income', 'units': {'USD': [
        {'start': '2026-04-01', 'end': '2026-06-30', 'val': 9078000, 'accn': '0001562762-26-000090',
         'form': '10-Q', 'filed': '2026-08-07'}]}}}}}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(json.dumps(body))
    monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: Response())
    records = sec_client.get_company_fact_records_for_concept_units(
        '0001901637', concept_units=(('NetIncomeLoss', 'USD'),))
    assert bool(records) is accepted
    assert all(record.cik == '1901637' for record in records)


def test_business_type_comes_from_the_recorded_industry_code(monkeypatch):
    monkeypatch.setattr(sec_provider, '_issuer_sic', {'0001901637': '6022', '0000059558': '6311',
                                                       '0001393818': '6282', '0001001838': '3330'})
    assert issuer_sector('0001901637') == 'bank'
    assert issuer_sector('59558') == 'insurer'
    assert issuer_sector('1393818') == 'asset manager'
    assert issuer_sector('1001838') is None and issuer_sector(None) is None
    # Each measured business type has a signature pair among its own measures,
    # and every type states what standard facts cannot supply.
    for sector, (first, second) in SECTOR_SIGNATURES.items():
        assert {first, second} <= set(SECTOR_METRICS[sector])
    assert set(SECTOR_GAPS) == set(SECTOR_METRICS)
