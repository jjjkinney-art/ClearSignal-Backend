"""Offline raw quote/profile/SEC-EPS consistency, not valuation authorization."""
from decimal import DecimalException
import hashlib
import json
import re

from validation.dated_price import MAX_CAPTURE_BYTES, _instant, _pairs, _text
from validation.fmp_quote_capture import _Number, map_fmp_quote_capture
from validation.source_anchored_valuation import _source_eps
from validation.valuation_scenario import ValuationContractError, _object

PROFILE_ENDPOINT = 'https://financialmodelingprep.com/stable/profile'
PROFILE_DOCUMENTATION = 'https://site.financialmodelingprep.com/developer/docs/stable/profile-symbol'


def _profile(body, receipt, symbol, cik, analysis, evaluated, policy):
    if type(body) is not bytes or not 0 < len(body) <= MAX_CAPTURE_BYTES:
        raise ValuationContractError('bounded profile bytes required')
    _object(receipt, {'sha256', 'byte_length', 'endpoint', 'requested_symbol',
                      'retrieved_at', 'status_code', 'content_type'}, 'profile receipt')
    if (receipt['endpoint'] != PROFILE_ENDPOINT or receipt['requested_symbol'] != symbol
            or type(receipt['status_code']) is not int or receipt['status_code'] != 200
            or receipt['content_type'] != 'application/json'
            or type(receipt['byte_length']) is not int or receipt['byte_length'] != len(body)
            or not isinstance(receipt['sha256'], str)
            or receipt['sha256'] != hashlib.sha256(body).hexdigest()):
        raise ValuationContractError('profile receipt mismatch')
    _object(policy, {'policy_id', 'max_age_seconds'}, 'profile retrieval-age policy')
    _text(policy['policy_id'], 'profile policy ID')
    maximum = policy['max_age_seconds']
    if type(maximum) is not int or not 0 <= maximum <= 604800:
        raise ValuationContractError('explicit bounded profile retrieval-age tolerance required')
    retrieved = _instant(receipt['retrieved_at'])
    if not retrieved <= analysis <= evaluated:
        raise ValuationContractError('profile must have been retrieved by analysis time')
    age = int((analysis - retrieved).total_seconds())
    if age > maximum:
        raise ValuationContractError('profile retrieval age exceeds supplied tolerance')
    def reject_constant(_):
        raise ValuationContractError('nonfinite JSON constant')
    data = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_int=_Number, parse_float=_Number, parse_constant=reject_constant)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValuationContractError('one profile required')
    row = data[0]
    if row.get('symbol') != symbol or row.get('cik') != cik or row.get('currency') != 'USD':
        raise ValuationContractError('profile symbol/CIK/USD mismatch')
    exchange, isin = row.get('exchange'), row.get('isin')
    if (not isinstance(exchange, str) or not re.fullmatch(r'[A-Z][A-Z0-9 .-]{0,31}', exchange)
            or exchange != exchange.strip()
            or not isinstance(isin, str) or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', isin)):
        raise ValuationContractError('bounded provider exchange and explicit ISIN shape required')
    if (any(row.get(key) is not False for key in ('isAdr', 'isEtf', 'isFund'))
            or row.get('isActivelyTrading') is not True):
        raise ValuationContractError('explicit active/non-ADR/non-fund provider flags required')
    return {'symbol': symbol, 'provider_cik': cik, 'provider_currency': 'USD',
        'provider_exchange_label': exchange, 'provider_isin': isin,
        'provider_flags': {key: row[key] for key in ('isAdr', 'isEtf', 'isFund', 'isActivelyTrading')},
        'retrieval_age_seconds': age, 'source_observation_time': None,
        'raw_binding': {**dict(receipt), 'fields': {key: '/0/' + key for key in
            ('symbol', 'cik', 'currency', 'exchange', 'isin', 'isAdr', 'isEtf', 'isFund', 'isActivelyTrading')}},
        'source_documentation': PROFILE_DOCUMENTATION}


def assess_quote_eps_binding(quote_body, quote_receipt, profile_body, profile_receipt,
                             items, references, *, expected_symbol, expected_cik,
                             analysis_as_of, evaluated_at, quote_freshness_policy,
                             profile_retrieval_policy):
    """Rebuild all three inputs; never accept a caller's already-passing report.

    A symbol/CIK/currency agreement is narrower than security/EPS compatibility.
    In particular, non-ADR/non-fund flags do not establish a common-share class.
    """
    stage = 'expected_issuer'
    try:
        if (not isinstance(expected_cik, str) or not re.fullmatch(r'[0-9]{10}', expected_cik)
                or int(expected_cik) == 0):
            raise ValuationContractError('exact ten-digit expected CIK required')
        stage = 'quote_capture'
        quote = map_fmp_quote_capture(quote_body, quote_receipt, expected_symbol=expected_symbol,
            analysis_as_of=analysis_as_of, evaluated_at=evaluated_at,
            freshness_policy=quote_freshness_policy)
        if not quote['mapped']:
            raise ValuationContractError('quote rejected')
        stage = 'profile_capture'
        analysis, evaluated = _instant(analysis_as_of), _instant(evaluated_at)
        profile = _profile(profile_body, profile_receipt, expected_symbol, expected_cik,
                           analysis, evaluated, profile_retrieval_policy)
        stage = 'quote_profile_exchange'
        if profile['provider_exchange_label'] != quote['candidate']['provider_exchange_label']:
            raise ValuationContractError('provider exchange labels disagree')
        stage = 'sec_eps'
        # Annual EPS remains historical USD diluted EPS. No quarterly annualizing,
        # currency conversion, concept substitution or unbound reference fallback.
        eps = _source_eps(expected_symbol, expected_cik, items, references, analysis.date())
        return {'binding_passed': True, 'status': 'partial', 'admitted': False, 'launch_ready': False,
            'classification': 'offline_quote_profile_eps_consistency',
            'quote': quote, 'profile': profile, 'source_eps': eps,
            'checks': {'exact_symbol': True, 'exact_expected_cik': True,
                'provider_exchange_labels_agree': True, 'provider_currency_matches_eps_currency': True,
                'annual_diluted_eps_reconstructed': True},
            'profile_retrieval_policy': dict(profile_retrieval_policy),
            'security_mapping_verified': False, 'eps_compatibility_verified': False,
            'market_pe_verified': False, 'independently_adjudicated': False,
            'unanswered_parts': ['independent source authenticity and expected-issuer mapping review',
                'profile effective date and historical listing/identifier mapping',
                'share class and common-share price unit', 'split/corporate-action and EPS earnings-scope compatibility',
                'trade/close semantics, session and approved freshness policy',
                'inspectable quote observation and approved price-to-EPS calculation'],
            'limitations': [
                'Provider CIK/currency and reconstructed SEC EPS agree; this is consistency, not independent adjudication.',
                'Profile retrieval time does not establish when its mapping was effective or source-fresh.',
                'Provider ISIN is bound text with structural validation only; checksum and security mapping are unverified.',
                'Non-ADR/non-fund flags do not prove an underlying common share or a particular share class.',
                'Fiscal-year EPS is not current TTM or forward EPS; filing dates have no intraday availability proof.',
                'No ratio, return, growth assumption, evidence admission or investment threshold is calculated.']}
    except (ValuationContractError, DecimalException, UnicodeDecodeError,
            json.JSONDecodeError, RecursionError) as exc:
        return {'binding_passed': False, 'status': 'insufficient_valuation_inputs',
            'admitted': False, 'launch_ready': False,
            'classification': 'offline_quote_profile_eps_consistency',
            'reason': 'quote_profile_eps_binding_rejected', 'stage': stage,
            'diagnostic_type': type(exc).__name__}
