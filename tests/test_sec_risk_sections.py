"""Authored heading layouts; never a live SEC coverage certification."""
import pytest

from app.services.sec_risk_sections import (
    RISK_START, complete_risk_window, find_risk_closing,
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
