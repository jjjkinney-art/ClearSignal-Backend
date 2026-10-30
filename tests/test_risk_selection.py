"""Company-specific risks are chosen over boilerplate, and none is forced.

Quotes are from 10-K risk factors retained in ordinary run 2.
"""
from app.services.risk_selection import rejection, select_risks, specificity
from app.services.thesis_disclosures import _business_quote_rejection

PREAMBLE = ('The events and consequences discussed in these risk factors could, in circumstances we may or may not be '
            'able to accurately predict, recognize, or control, have a material adverse effect on our business.')
BELOW = ('Many of the risks discussed below also impact our customers, including third-party sellers, which could '
         'indirectly have a material adverse effect on us.')
BULLETS = ('Strategic Risks • Inability to effectively implement our business strategy or achieve our objectives; '
           '• Failure to keep pace with technological change and marketplace demand.')
HEADING = ('Risks Related to Artificial Intelligence, Our Data, and Our Information Technology Systems Our increasing '
           'use of artificial intelligence could adversely affect our business.')
HAZARDS = ('Factors that are hard to predict or are beyond our control, such as supply chain disruptions, raw material '
           'shortages, natural disasters, including hurricanes, other catastrophic events, political unrest, '
           'terrorism, or public health crises could damage or disrupt our operations.')
CONCENTRATION = ('In addition, because China-based sellers account for significant portions of our third-party seller '
                 'services and advertising revenues, trade restrictions could adversely affect our results.')
SOURCES = ('Some of the components we use in our technical infrastructure and our devices are available from only one '
           'or limited sources, and we may not be able to find replacement vendors on favorable terms.')
GENERIC = 'Any significant impairment of our intellectual property rights could harm our business and ability to compete.'


def test_boilerplate_forms_are_rejected_with_reasons():
    assert rejection(PREAMBLE) == 'risk_factor_preamble'
    assert rejection(BELOW) == 'risk_factor_preamble'
    assert rejection(BULLETS) == 'bullet_summary'
    assert rejection(HEADING) == 'run_in_heading'
    assert rejection(HAZARDS) == 'generic_hazard_list'
    for quote in (CONCENTRATION, SOURCES, GENERIC):
        assert rejection(quote) is None


def test_concrete_dependencies_outrank_named_terms_and_source_order():
    assert specificity(CONCENTRATION) > specificity(GENERIC)
    assert specificity(SOURCES) > specificity(GENERIC)
    candidates = [(0, GENERIC), (1, PREAMBLE), (2, SOURCES), (3, CONCENTRATION)]
    selected, reasons = select_risks(candidates, quote_of=lambda c: c[1], offset_of=lambda c: c[0])
    assert [c[1] for c in selected] == [CONCENTRATION, SOURCES]
    assert reasons == ['risk_factor_preamble']


def test_without_specific_signals_source_order_is_kept():
    first = 'Performance failure can occur from late shipments due to the inability to secure raw materials.'
    second = 'New laws or procurement requirements can significantly increase our costs of performance.'
    selected, _ = select_risks([(5, second), (1, first)], quote_of=lambda c: c[1], offset_of=lambda c: c[0])
    assert [c[1] for c in selected] == [first, second]


def test_nothing_is_forced_when_every_candidate_is_boilerplate():
    selected, reasons = select_risks([(0, PREAMBLE), (1, BULLETS), (2, HAZARDS)],
                                     quote_of=lambda c: c[1], offset_of=lambda c: c[0])
    assert selected == []
    assert sorted(reasons) == ['bullet_summary', 'generic_hazard_list', 'risk_factor_preamble']


def test_employee_programs_are_not_business_descriptions():
    assert _business_quote_rejection('Ingredion provides our employees with a variety of wellness programs and offers '
                                     'incentives for weight management and health club memberships.') \
        == 'internal_employee_activity'
    assert _business_quote_rejection('We sell refined corn oil (from germ) to packers of cooking oil and to producers '
                                     'of margarine, salad dressings and other foods.') is None
