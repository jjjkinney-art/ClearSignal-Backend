"""Management's stated driver of a revenue change in a 20-F (Embraer, FY2025): two general defects, one fix each.

Defect record: DEFECT_MISSED_MANAGEMENT_DRIVER_20261113.md (diagnostic D1 batch B, EMBJ:core_thesis). The retained input is the
byte-exact Embraer 20-F (accession 0001628280-26-021824, sha256 3522143b...d939) from the diagnostic ledger, gzipped in
tests/data. Cases marked CONSTRUCTED are invented text that isolates one rule. Model-assisted: the model that made the fixes
also wrote these tests.

Cause 1 (window): results_section_bounds picked the longest span between ANY "Item 5. Operating and Financial Review" and the next
"Item 6. Directors", so a quoted cross-reference in Items 3/4 opened a span and another closed it, and the real Item 5 (which
holds the driver sentences) was never read. Fix: opt-in reject_cross_references, enabled on the annual-facts path only.
Cause 2 (sentence): the revenue sentence was fused to the flattened results table before it (no full stop), and the cause
sentence opens "This was primarily due to ...", which the back-reference rule did not accept. Fix: opt-in annual_tables (a
"Year Ended" heading inside the table text) and bare_demonstrative, both enabled for the 20-F reader only.
"""
import gzip
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.services import annual_filing_facts as afacts
from app.services import current_period_explanation as cpe
from app.services import public_document_ingestion as pdi
from app.services import sec_risk_sections as sections

DATA = Path(__file__).resolve().parent / 'data'
URL = 'https://www.sec.gov/Archives/edgar/data/1355444/000162828026021824/erj-20251231.htm'
SHA = '3522143bb34937112024b07da0fbd15ba954295829e02a3f61ec99f87b41d939'
REVENUE = ('Our revenue increased US$1,182.8 million, or 18.5%, to US$7,577.5 million in 2025 from US$6,394.7 million in 2024.')
DRIVER = ('This was primarily due to the increase in deliveries in Commercial and Executive Aviation, despite the supply chain '
          'shortage which has been affecting the aeronautical industry; and higher revenues in Services & Support and Defense & Security.')


@pytest.fixture(scope='module')
def body():
    data = gzip.open(DATA / 'embraer_20f_2025_retained_d1.html.gz').read()
    assert hashlib.sha256(data).hexdigest() == SHA
    return data


@pytest.fixture(scope='module')
def fetched(body):
    """The retained 20-F through the same single fetch the request already makes; every request is counted."""
    calls, patch = [], pytest.MonkeyPatch()

    class Response:
        status_code, headers, encoding = 200, {'Content-Type': 'text/html'}, 'utf-8'

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=65536):
            yield body

        def close(self):
            pass

    patch.setattr(pdi.requests, 'get', lambda url, *a, **k: calls.append(url) or Response())
    try:
        doc = pdi.fetch_public_document(
            URL, publisher='SEC EDGAR', published_at='2026-03-30', document_type='20-F', source_type='regulatory_filing',
            source_tier='primary', sec_periodic_limits=True, preserve_sec_business=True, extract_tables=False,
            **{**afacts.fetch_options(), 'inline_fact_cik': '1355444'})
    finally:
        patch.undo()
    assert len(calls) == 1
    return doc


@pytest.fixture(scope='module')
def comparisons(fetched):
    items, _ = afacts.filing_comparisons(fetched, 'EMBJ', '1355444')
    return items


def explain(doc, items):
    return cpe.extract_annual_foreign_explanation(doc, items, ticker='EMBJ', cik='1355444')


def revenue_statement(item):
    return next((s for s in item.period_explanations[0]['statements'] if s['metric'] == 'revenue'), None)


# --- cause 1: the results window ---------------------------------------------------------------------------------------------

def test_before_the_window_is_two_quoted_cross_references_after_it_is_the_real_item_5(body):
    parser = pdi._HTMLTextExtractor()
    parser.feed(body.decode('utf-8', 'replace'))
    full = parser.normalized_visible_text(preserve_sec_risk=True)
    start, end = sections.results_section_bounds(full, form='20-F')
    assert full[start - 6:start + 40].startswith('“Item 5') or 'see “Item 5' in full[start - 12:start + 8]  # BEFORE: a quoted reference
    assert REVENUE not in full[start:end] and DRIVER not in full[start:end]  # the real discussion was never read
    start, end = sections.results_section_bounds(full, form='20-F', reject_cross_references=True)
    assert full[start:start + 80].startswith('Item 5. OPERATING AND FINANCIAL REVIEW AND PROSPECTS')
    assert REVENUE in full[start:end] and DRIVER in full[start:end] and full[end:end + 30].startswith('Item 6.')
    assert end - start < 100_000


def test_constructed_references_toc_and_a_real_closing_heading_followed_by_a_page_number():
    # CONSTRUCTED: TOC row, quoted references in earlier items, the real heading, then a real closing heading with a page number.
    toc = 'Item 5. OPERATING AND FINANCIAL REVIEW AND PROSPECTS 62 A. Operating Results 63 Item 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES 86 A. '
    early = (' For tax see “Item 5 . Operating And Financial Review And Prospects—A. Operating Results—Tax.” ' + 'x ' * 4000
             + 'see “Item 6 . Directors, Senior Management And Employees and “Item 3” ')
    real = ' Item 5. OPERATING AND FINANCIAL REVIEW AND PROSPECTS This discussion ' + 'y ' * 1500 + ' Item 6. DIRECTORS, SENIOR MANAGEMENT AND EMPLOYEES 86 A. Directors '
    text = toc + early + real
    old = sections.results_section_bounds(text, form='20-F')
    new = sections.results_section_bounds(text, form='20-F', reject_cross_references=True)
    assert 'x x' in text[old[0]:old[1]] and 'y y' not in text[old[0]:old[1]]  # default: the span from the quoted reference wins
    assert text[new[0]:new[0] + 40].startswith('Item 5. OPERATING') and 'y y' in text[new[0]:new[1]] and 'x x' not in text[new[0]:new[1]]
    assert text[new[1]:new[1] + 7] == 'Item 6.'


def test_existing_callers_and_the_page_number_rule_are_unchanged():
    assert sections.rejected_risk_heading('Item 6. DIRECTORS 86 A. Directors', len('Item 6. DIRECTORS')) is True
    assert sections.rejected_risk_heading('Item 6. DIRECTORS 86 A. Directors', len('Item 6. DIRECTORS'), page_numbers=False) is False
    assert sections.rejected_risk_heading('Item 5 Prospects—A. Operating', len('Item 5 Prospects'), page_numbers=False) is True
    assert sections.rejected_risk_heading('x', 0, start=None) is False
    text = 'Item 2. Management’s Discussion and Analysis ' + 'a ' * 50 + 'Item 3. Quantitative and Qualitative Disclosures'
    assert sections.results_section_bounds(text, form='10-Q') == sections.results_section_bounds(text, form='10-Q', reject_cross_references=False)


# --- cause 2: the sentence ---------------------------------------------------------------------------------------------------

def test_a_narrative_sentence_after_an_annual_table_is_split_only_when_asked():
    # CONSTRUCTED: a flattened annual table longer than MAX_TABLE_CHARS, then the narrative sentence.
    rows = ' '.join(f'Line{i} {100 + i}.5 {90 + i}.5 {80 + i}.5' for i in range(220))
    text = ('Results of Operations For the Year Ended December 31, 2025 2024 2023 (in US$ millions) ' + rows
            + ' Total 7,577.5 6,394.7 5,268.5 Our revenue increased US$1,182.8 million, or 18.5%, to US$7,577.5 million in 2025 from US$6,394.7 million in 2024.')
    assert len(text) > cpe.MAX_TABLE_CHARS + 500
    plain = [s for _, s in cpe.sentences(text, split_tables=True)]
    annual = [s for _, s in cpe.sentences(text, split_tables=True, annual_tables=True)]
    assert len(plain) == 1 and len(annual) == 2 and annual[1].startswith('Our revenue increased')
    # a table with no year heading is never split by this option
    other = text.replace('For the Year Ended', 'For the period shown')
    assert len(list(cpe.sentences(other, split_tables=True, annual_tables=True))) == 1


def test_a_bare_this_was_cause_binds_only_when_the_option_is_on():
    # CONSTRUCTED sentences, real shapes.
    period = {'current_start': '2025-01-01', 'current_end': '2025-12-31', 'prior_start': '2024-01-01', 'prior_end': '2024-12-31'}
    sentence = 'Our revenue increased US$10.0 million, or 10.0%, to US$110.0 million in 2025 from US$100.0 million in 2024.'
    for cause in ('This was primarily due to higher deliveries.', 'This is mainly attributable to higher volumes.'):
        assert cpe.following_cause(sentence, cause, period) is False
        assert cpe.following_cause(sentence, cause, period, bare_demonstrative=True) is True
    for refused in ('This was reported in the table above.', 'This was primarily due to the factors discussed above.',
                    'This was, in our Services segment, primarily due to higher volumes.',
                    'This was primarily due to higher deliveries in 2023.', 'It was primarily due to higher deliveries.',
                    'Primarily due to higher deliveries.'):
        assert cpe.following_cause(sentence, refused, period, bare_demonstrative=True) is False, refused


# --- the retained 20-F: before and after ---------------------------------------------------------------------------------------

def test_after_the_fix_revenue_carries_managements_own_driver_with_its_citation(fetched, comparisons):
    assert len(comparisons) == 4
    items = explain(fetched, comparisons)
    assert len(items) == 1
    item = items[0]
    statement = revenue_statement(item)
    assert statement['quote'] == REVENUE and statement['cause_quote'] == DRIVER
    assert REVENUE in fetched.results_text and DRIVER in fetched.results_text  # verbatim, from the document the request fetched
    ref = item.period_explanations[0]['document_ref']
    assert ref['url'] == URL and ref['content_hash'] == fetched.content_hash and ref['section'] == cpe.SECTION
    assert ref['quote'] in fetched.results_text
    assert f'“{REVENUE}” and “{DRIVER}”' in item.summary
    assert item.period_explanations[0]['metrics']['revenue'] == {'current': 7577500000, 'prior': 6394700000}
    assert cpe.bound_current_period_explanation(item, ticker='EMBJ', cik='1355444') is not None


def test_other_measures_are_not_given_a_cause_the_filing_does_not_state(fetched, comparisons):
    item = explain(fetched, comparisons)[0]
    by_metric = {s['metric']: s for s in item.period_explanations[0]['statements']}
    assert set(by_metric) == {'revenue', 'operating income', 'operating cash flow'}
    assert 'cause_quote' not in by_metric['operating income'] and 'cause_quote' not in by_metric['operating cash flow']
    assert 'gives the change without a stated cause' in item.summary and 'profit for the year' in item.summary


def test_the_stored_value_rebuilds_and_dropping_the_option_flag_is_rejected(fetched, comparisons):
    item = explain(fetched, comparisons)[0]
    assert item.period_explanations[0]['annual_tables'] is True
    forged = item.model_copy(deep=True)
    forged.period_explanations[0].pop('annual_tables')
    assert cpe.bound_current_period_explanation(forged, ticker='EMBJ', cik='1355444') is None
    forged = item.model_copy(deep=True)
    forged.period_explanations[0]['statements'][0]['cause_quote'] = DRIVER.replace('increase in deliveries', 'decline in costs')
    assert cpe.bound_current_period_explanation(forged, ticker='EMBJ', cik='1355444') is None


def test_without_the_two_options_the_driver_is_not_delivered(fetched, comparisons):
    # BEFORE (engine options off, as every other caller runs it): the revenue sentence is fused to the table, no statement.
    observations = [(amount, row) for row in fetched.inline_xbrl_facts
                    if (amount := cpe.validated_observation(row, cik='1355444', concepts=cpe.EXPLANATION_CONCEPTS,
                                                            taxonomies=('us-gaap', 'ifrs-full'))) is not None]
    off = cpe.explanation_value(fetched.results_text, observations, comparisons, ticker='EMBJ', document_type='20-F',
                                filed_at='2026-03-30', level_cause=True)
    assert 'annual_tables' not in off and not [s for s in off['statements'] if s['metric'] == 'revenue']
    assert not [s for s in off['statements'] if s.get('cause_quote') == DRIVER]


# --- negative cases: the filing does not support a management attribution ---------------------------------------------------------

def variant(doc, old, new):
    assert doc.results_text.count(old) == 1
    return replace(doc, results_text=doc.results_text.replace(old, new))


@pytest.mark.parametrize('replacement,why', [
    ('This was reported in the table above.', 'no cause is stated'),
    ('This was primarily due to the factors discussed above.', 'a cross-reference states no cause of its own'),
    ('This was primarily due to the increase in deliveries in 2023, as in prior years.', 'the cause names another period'),
    ('This was, in the Services & Support segment, primarily due to higher volumes.', 'a new scope is introduced before the cause'),
    ('Analysts attribute this to the supply chain.', 'no causal connective management owns'),
])
def test_the_revenue_change_is_delivered_without_a_driver_when_the_filing_does_not_attribute_one(fetched, comparisons, replacement, why):
    items = explain(variant(fetched, DRIVER, replacement), comparisons)
    assert len(items) == 1, why
    statement = revenue_statement(items[0])
    assert statement is not None and statement['quote'] == REVENUE and 'cause_quote' not in statement, why
    assert replacement not in items[0].summary and DRIVER not in items[0].summary
    assert 'For revenue' in items[0].summary and 'gives the change without a stated cause' in items[0].summary


def test_an_unrelated_sentence_between_the_change_and_the_cause_breaks_the_link(fetched, comparisons):
    # The cause must be the sentence IMMEDIATELY after the statement it explains.
    items = explain(variant(fetched, DRIVER, 'Deliveries are shown in the table below. ' + DRIVER), comparisons)
    assert 'cause_quote' not in revenue_statement(items[0])
