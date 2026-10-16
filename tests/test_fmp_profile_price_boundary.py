"""Undated profile snapshots never become dated valuation observations."""
from copy import deepcopy

import pytest

from app.schemas import InvestmentThesis
from app.services.providers import fmp_provider as provider
from app.services.evidence_references import build_evidence_contract
from app.services.source_answer import apply_source_answer_gate
from validation.source_anchored_valuation import evaluate_source_anchored_scenario
from test_source_anchored_valuation import assumptions, TICKER, CIK

PROFILE = {'symbol': TICKER, 'companyName': 'Invented Components Inc.',
    'price': 173.25, 'mktCap': 1234567890, 'pe': 27.5, 'beta': 1.25,
    'currency': 'USD', 'sector': 'Industrials', 'industry': 'Components',
    'exchangeShortName': 'NASDAQ', 'description': 'Makes industrial components.',
    'ipoDate': '1980-12-12'}


def fetch(monkeypatch, payload=None, symbol=TICKER):
    calls = []
    monkeypatch.setattr(provider, '_get_api_key', lambda: 'TEST-ONLY')
    monkeypatch.setattr(provider, '_fetch_json', lambda url: calls.append(url) or
                        ([deepcopy(PROFILE)] if payload is None else payload))
    result = provider.fetch_company_profile(symbol)
    return result, calls


def test_profile_preserves_qualitative_context_without_snapshot_values_or_ipo_date(monkeypatch):
    items, calls = fetch(monkeypatch)
    item, = items
    assert len(calls) == 1 and '/profile/ZQXB?' in calls[0]
    assert 'Invented Components' in item.title and 'Company profile' in item.title
    assert 'Industrials' in item.summary and 'Makes industrial components.' in item.summary
    assert 'Listed exchange in profile: NASDAQ' in item.summary
    serialized = str(item.model_dump())
    assert all(value not in serialized for value in ('173.25', '1234567890', '27.5', '1.25', '1980-12-12'))
    assert 'Current price' not in serialized and 'Trailing P/E' not in serialized
    assert item.timestamp == '' and item.observed_at is None and item.retrieved_at is None
    assert item.verified_claims == [] and item.claim_type == 'unknown'
    refs, integrity = build_evidence_contract(items, evaluated_at='2026-10-16')
    assert refs[0]['published_at'] is None and refs[0]['observed_at'] is None
    assert refs[0]['freshness_status'] == 'unknown'
    assert refs[0]['document_type'] == 'Company profile'
    assert 'TEST-ONLY' not in str(refs) + str(integrity)


@pytest.mark.parametrize('field', ['price', 'mktCap', 'pe', 'beta'])
@pytest.mark.parametrize('bad', [True, 'bad', float('nan'), float('inf'), {}, []])
def test_unusable_snapshot_values_cannot_discard_usable_profile_or_leak_as_numbers(monkeypatch, field, bad):
    payload = deepcopy(PROFILE)
    payload[field] = bad
    items, calls = fetch(monkeypatch, [payload])
    item, = items
    assert len(calls) == 1 and item.timestamp == ''
    assert 'Makes industrial components.' in item.summary
    assert item.title == 'Invented Components Inc. (ZQXB) — Company profile'


@pytest.mark.parametrize('payload', [
    [], {}, [None], [PROFILE, PROFILE],
    [{**PROFILE, 'symbol': 'OTHER'}], [{k: v for k, v in PROFILE.items() if k != 'symbol'}],
    [{**PROFILE, 'symbol': True}],
])
def test_malformed_ambiguous_or_wrong_symbol_response_returns_no_profile(monkeypatch, payload):
    items, calls = fetch(monkeypatch, payload)
    assert items == [] and len(calls) == 1


@pytest.mark.parametrize('symbol', [None, True, '', 'ZQXB/OTHER', 'ZQXB?apikey=secret'])
def test_invalid_symbol_is_refused_before_fetch(monkeypatch, symbol):
    items, calls = fetch(monkeypatch, symbol=symbol)
    assert items == [] and calls == []


def test_case_normalization_keeps_exact_response_symbol_agreement(monkeypatch):
    items, calls = fetch(monkeypatch, [{**PROFILE, 'symbol': 'zqxb'}], symbol=' zqxb ')
    assert len(items) == 1 and '/profile/ZQXB?' in calls[0]


@pytest.mark.parametrize('extra', [
    {'currency': 'EUR'},
    {'currency': 'USD', 'timestamp': 1792108800},
    {'currency': 'USD', 'date': '2026-10-16', 'isAdr': True},
])
def test_currency_or_generic_date_fields_do_not_complete_a_trade_security_contract(monkeypatch, extra):
    items, _ = fetch(monkeypatch, [{**PROFILE, **extra}])
    item, = items
    assert item.timestamp == '' and item.observed_at is None
    assert '173.25' not in item.summary and '$' not in item.title


def test_profile_cannot_fill_eps_source_or_authorize_threshold_output(monkeypatch):
    items, _ = fetch(monkeypatch)
    refs, _ = build_evidence_contract(items, evaluated_at='2026-10-16')
    result = evaluate_source_anchored_scenario(TICKER, items, refs, expected_cik=CIK,
        assumptions=assumptions(), evaluated_at='2026-10-16')
    assert not result['available'] and 'EPS' in result['reason']
    thesis = InvestmentThesis(ticker=TICKER, company_name='Invented Components',
                              direct_answer='Current price is $173.25; buy below 20x.')
    gated = apply_source_answer_gate(thesis, 'Explain decision thresholds', items, references=refs)
    assert gated['status'] == 'insufficient_claim_evidence'
    assert '$173.25' not in thesis.direct_answer and thesis.confidence_score == 0


def test_malformed_optional_text_does_not_serialize_objects(monkeypatch):
    payload = {**PROFILE, 'companyName': {'secret': 'MUST-NOT-SERIALIZE'},
        'sector': ['MUST-NOT-SERIALIZE'], 'industry': 42,
        'description': {'data': 'MUST-NOT-SERIALIZE'}, 'exchangeShortName': None}
    items, _ = fetch(monkeypatch, [payload])
    item, = items
    assert 'MUST-NOT-SERIALIZE' not in str(item.model_dump())
    assert item.title.startswith(TICKER)
