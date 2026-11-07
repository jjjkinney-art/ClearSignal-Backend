"""Company-specific risks are chosen over boilerplate, and none is forced.

Quotes are from 10-K risk factors retained in ordinary run 2.
"""
from app.services.risk_selection import qualifies, rejection, select_risks, specificity
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
    assert sorted(reasons) == ['not_company_specific', 'risk_factor_preamble']


def test_without_a_specific_signal_nothing_is_presented():
    first = 'Performance failure can occur from late shipments due to the inability to secure raw materials.'
    second = 'New laws or procurement requirements can significantly increase our costs of performance.'
    selected, reasons = select_risks([(5, second), (1, first)], quote_of=lambda c: c[1], offset_of=lambda c: c[0])
    assert selected == [] and reasons == ['not_company_specific', 'not_company_specific']


def test_statutes_acronyms_and_named_places_in_macro_text_do_not_qualify():
    fcpa = ('In addition, we could be adversely affected by violations of the Foreign Corrupt Practices Act and similar '
            'worldwide anti-bribery laws.')
    dso = 'If our clients become unable to pay amounts owed to us, then our DSO will increase.'
    war = ('The military conflicts (including the ongoing war between Russia and Ukraine), and related sanctions, '
           'could adversely affect our business.')
    tax = ('For example, the Indian tax authority has asserted that tax applies to cloud services fees paid to Amazon '
           'in the U.S. We are contesting this position.')
    assert not qualifies(fcpa) and not qualifies(dso) and not qualifies(war)
    assert qualifies(tax) and qualifies(CONCENTRATION) and qualifies(SOURCES)


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


import pytest  # noqa: E402


@pytest.mark.parametrize('quote, reason', [
    ('We conduct substantially all of our operations through our indirect, wholly-owned subsidiaries in the United States.', 'corporate_structure'),
    ('The Corporation’s success is largely dependent on the performance of the Corporation’s management and executive officers.', 'generic_key_person'),
    ('If any such risks actually occur, our business could be materially adversely affected.', 'risk_factor_preamble'),
    ('The occurrence of any of the foregoing risks may have a material adverse effect on us.', 'risk_factor_preamble'),
])
def test_structure_key_person_and_summary_sentences_are_not_company_risks(quote, reason):
    from app.services.risk_selection import rejection
    assert rejection(quote) == reason


def test_a_dependence_on_a_named_partner_or_customers_still_qualifies():
    from app.services.risk_selection import qualifies, rejection
    for quote in ('The Company and TCCC have extensive commercial arrangements and, as a result, the Company’s future performance is substantially dependent on the success of its relationship with TCCC.',
                  'We depend on a limited number of customers for a substantial portion of our revenue.'):
        assert rejection(quote) is None and qualifies(quote)


TERMS = frozenset({'bottler', 'aluminum', 'clinical'})


def test_a_plain_language_risk_needs_the_filing_term_and_a_stated_exposure():
    from app.services.risk_selection import plain_exposure
    exposed = 'If we are unable to maintain good relationships with our existing bottlers, our business could suffer.'
    assert plain_exposure(exposed, terms=TERMS)
    # A business term alone, with no consequence or no first-person exposure, does not qualify.
    assert not plain_exposure('Our products are sold through bottlers in many countries.', terms=TERMS)
    assert not plain_exposure('Bottlers could suffer in some markets.', terms=TERMS)
    # A stated exposure with no term of this filing does not qualify either.
    assert not plain_exposure('If we are unable to retain staff, our business could suffer.', terms=TERMS)
    # A macro hazard still needs a concrete dependency, whatever else it mentions.
    assert not plain_exposure('Tariffs on aluminum could adversely affect our margins.', terms=TERMS)


def test_a_heading_is_context_for_the_passage_and_never_enough_alone():
    from app.services.risk_selection import plain_exposure
    passage = 'Changes in government regulation could adversely affect our business.'
    heading = 'Government Regulation and Litigation Risks'
    assert plain_exposure(passage, heading=heading) and not plain_exposure(passage)
    # The heading's topic is not in the passage, or the passage states no consequence.
    assert not plain_exposure('Our staff could suffer in some years, and our plans could be harmed.', heading=heading)
    assert not plain_exposure('Changes in government regulation occur in many markets.', heading=heading)


def test_a_headed_risk_comes_before_an_unheaded_one_and_the_limit_holds():
    headed = (2, 'Changes in government regulation could adversely affect our business.', 'Government Regulation Risks')
    plain = (1, 'If we are unable to keep our bottlers, our business could suffer.', None)
    other = (3, 'Our aluminum supply could be reduced, and our margins could suffer.', None)
    selected, _ = select_risks([plain, other, headed], quote_of=lambda c: c[1], offset_of=lambda c: c[0],
                               heading_of=lambda c: c[2], terms=TERMS)
    assert [row[0] for row in selected] == [2, 1]


def test_business_terms_drop_words_common_to_any_business_section():
    from app.services.risk_selection import business_terms
    text = 'bottlers bottlers bottlers could could could customers customers customers aluminum'
    assert business_terms(text) == frozenset({'bottler'})
