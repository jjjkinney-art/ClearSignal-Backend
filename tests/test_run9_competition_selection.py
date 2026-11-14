"""Competition sentences that only describe a labour market are not competitive exposure.

Synthetic prose shaped like the two Run 9 / Run 4 sentences that exposed the gap.
"""
import pytest

from app.services.thesis_competition import _qualifies


@pytest.mark.parametrize('quote', [
    'We compete with other brokers and banks for front-office staff.',
    'We compete with other hospitals and clinics for medical staff.',
    'We compete with other firms for back-office staff in several regions.',
    'We also compete with other companies for talent in our largest markets.',
    'We compete with other employers for personnel with specialised skills.',
])
def test_competition_for_people_is_not_a_competitive_exposure(quote):
    assert not _qualifies(quote)


@pytest.mark.parametrize('quote', [
    # A sales channel the issuer names is a commercial relationship, not a labour market.
    'We also compete with other companies for distributors, leaders and consultants.',
    'We compete with other manufacturers for shelf space with independent dealers.',
    'We compete with other brokers and banks for clients in execution and clearing services.',
    'We compete with other staffing firms for business from large corporate customers.',
    'Our principal competitors are regional distributors of industrial fasteners.',
])
def test_product_market_and_channel_competition_still_qualifies(quote):
    assert _qualifies(quote)
