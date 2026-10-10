"""Authored heading layouts; never a live SEC coverage certification."""
import pytest

from app.services.sec_risk_sections import (
    RISK_START, complete_risk_window, find_risk_closing, complete_business_window,
)


@pytest.mark.parametrize('opening', [
    'Item 1A. Ri sk Factors', 'Ite m 1A – Risk Factors',
    'I tem 1 A. R isk Fac tors', 'ITEM 1A. RISK FACTORS',
])
@pytest.mark.parametrize('closing', [
    'Ite m 1B. Unres olved Staff Com ments',
    'Item 1 C. Cy bersecurity', 'Item 2. Pro perties',
])
def test_split_heading_words_preserve_original_span(opening, closing):
    text = opening + ' Authored narrative. ' + closing
    window = complete_risk_window(text)
    assert window == (0, len(text))
    assert RISK_START.search(text).group() == opening


@pytest.mark.parametrize('reference', [
    'See Ite m 1B. Unres olved Staff Comments',
    '“Ite m 1B. Unres olved Staff Comments”',
    'Ite m 1B. Unres olved Staff Comments 31',
])
def test_closing_reference_cannot_substitute_for_section_boundary(reference):
    text = 'Item 1A. Ri sk Factors Authored narrative. ' + reference
    assert complete_risk_window(text) is None
    text += ' Authored narrative. Item 1C. Cybersecurity'
    closing = find_risk_closing(text, RISK_START.search(text).end())
    assert closing.group() == 'Item 1C. Cybersecurity'
    assert complete_risk_window(text) == (0, len(text))


def test_reference_scan_limit_still_fails_closed():
    text = 'Item 1A. Ri sk Factors ' + 'See Item 1B. Unresolved Staff Comments. ' * 64
    text += 'Item 1C. Cybersecurity'
    assert complete_risk_window(text) is None


@pytest.mark.parametrize('opening', ['Item 11A. Risk Factors', 'Item 1A. Risk Forecasts',
                                     'Item 1A. Risk Factorial', 'Item 1A. Other Factors'])
def test_unrelated_labels_do_not_become_risk_headings(opening):
    assert complete_risk_window(opening + ' Authored narrative. Item 1B. Unresolved Staff Comments') is None


@pytest.mark.parametrize('closing', [
    'Item 1B.Unresolved Staff Comments', 'Item 1C:Cybersecurity',
    'Item 2—Properties', 'Ite m 1B.Unres olved Staff Com ments',
    'Item 1B Unresolved Staff Comments',
])
def test_compact_closing_separator_preserves_explicit_boundary(closing):
    text = 'Item 1A. Risk Factors Authored narrative. ' + closing
    assert complete_risk_window(text) == (0, len(text))
    assert find_risk_closing(text, RISK_START.search(text).end()).group() == closing


@pytest.mark.parametrize('closing', [
    'See Item 1B.Unresolved Staff Comments',
    '“Item 1C:Cybersecurity”', 'Item 2—Properties 42',
    'Item 1BUnresolved Staff Comments', 'Item 2Properties',
])
def test_compact_closing_does_not_admit_references_or_joined_labels(closing):
    text = 'Item 1A. Risk Factors Authored narrative. ' + closing
    assert complete_risk_window(text) is None


@pytest.mark.parametrize('separator', [' . ', ': ', ' .\u00a0'])
def test_punctuated_toc_rows_cannot_open_business_or_risk_sections(separator):
    toc = (f'Item 1. Business{separator}1 Overview 1 Business segments 1 '
           f'Item 1A. Risk Factors{separator}9 Item 1B. Unresolved Staff Comments{separator}20 ')
    assert complete_business_window(toc) is None
    assert complete_risk_window(toc) is None
    business = 'We manufacture specialized components and distribute products through independent dealers.'
    risk = 'Supply chain disruptions could adversely affect our ability to deliver products.'
    text = toc + f'Item 1. Business Overview. {business} Item 1A. Risk Factors {risk} Item 1B. Unresolved Staff Comments'
    window = complete_business_window(text)
    assert window and business in text[window[0]:window[1]]
    assert 'Business segments' not in text[window[0]:window[1]]
    risk_window = complete_risk_window(text)
    assert risk_window and risk in text[risk_window[0]:risk_window[1]]


def test_punctuated_toc_closing_cannot_truncate_actual_risk_section():
    text = ('Item 1A. Risk Factors Authored opening narrative. '
            'Item 1B. Unresolved Staff Comments . 20 '
            'Authored remaining risk narrative. Item 1C. Cybersecurity')
    assert complete_risk_window(text) == (0, len(text))


def test_punctuation_followed_by_prose_does_not_reject_actual_heading():
    text = ('Item 1. Business . We manufacture specialized components for independent dealers. '
            'Item 1A. Risk Factors: Supply chain disruptions could impair deliveries. '
            'Item 1B. Unresolved Staff Comments')
    assert complete_business_window(text) is not None
    assert complete_risk_window(text) is not None
