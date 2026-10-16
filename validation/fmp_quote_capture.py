"""Offline FMP stable-quote bytes to a source-bound, unadmitted candidate.

No HTTP, credentials, evidence admission, security-master lookup or EPS pricing.
The provider quote timestamp is not relabeled as a last-trade/close timestamp.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from validation.dated_price import MAX_CAPTURE_BYTES, _instant, _pairs, _text
from validation.valuation_scenario import ValuationContractError, _number, _object

ENDPOINT = 'https://financialmodelingprep.com/stable/quote'
DOCUMENTATION = 'https://site.financialmodelingprep.com/developer/docs/stable/quote'
FIELD_GUIDE = ('https://site.financialmodelingprep.com/education/index-articles/'
               'instant-stock-intelligence-a-comprehensive-guide-to-fmps-quote-api')


class _Number:
    """Retain JSON numeric token text without binary-float conversion."""
    def __init__(self, text):
        if len(text) > 66:
            raise ValuationContractError('numeric token bound')
        self.text = text


def map_fmp_quote_capture(body, receipt, *, expected_symbol, analysis_as_of,
                          evaluated_at, freshness_policy):
    """Map one saved stable quote, retaining all unresolved security semantics.

    Hash/receipt and field bindings support replay, not authentication. No caller
    hint can upgrade the candidate into a trade, currency or verified security.
    """
    try:
        if type(body) is not bytes or not 0 < len(body) <= MAX_CAPTURE_BYTES:
            raise ValuationContractError('bounded saved response bytes required')
        if not isinstance(expected_symbol, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', expected_symbol):
            raise ValuationContractError('exact expected symbol required')
        _object(receipt, {'sha256', 'byte_length', 'endpoint', 'requested_symbol',
                          'retrieved_at', 'status_code', 'content_type'}, 'raw quote receipt')
        if (receipt['endpoint'] != ENDPOINT or receipt['requested_symbol'] != expected_symbol
                or type(receipt['status_code']) is not int or receipt['status_code'] != 200
                or receipt['content_type'] != 'application/json'
                or type(receipt['byte_length']) is not int or receipt['byte_length'] != len(body)
                or not isinstance(receipt['sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', receipt['sha256'])
                or receipt['sha256'] != hashlib.sha256(body).hexdigest()):
            raise ValuationContractError('raw response receipt mismatch')
        _object(freshness_policy, {'policy_id', 'max_age_seconds'}, 'explicit freshness policy')
        _text(freshness_policy['policy_id'], 'policy ID')
        maximum = freshness_policy['max_age_seconds']
        if type(maximum) is not int or not 0 <= maximum <= 604800:
            raise ValuationContractError('explicit bounded freshness tolerance required')
        def reject_constant(_):
            raise ValuationContractError('nonfinite JSON constant')
        data = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_int=_Number, parse_float=_Number, parse_constant=reject_constant)
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise ValuationContractError('one unambiguous quote record required')
        row = data[0]
        if row.get('symbol') != expected_symbol:
            raise ValuationContractError('returned symbol mismatch')
        exchange = row.get('exchange')
        if (not isinstance(exchange, str) or not re.fullmatch(r'[A-Z][A-Z0-9 .-]{0,31}', exchange)
                or exchange != exchange.strip()):
            raise ValuationContractError('explicit provider exchange label required')
        price, stamp = row.get('price'), row.get('timestamp')
        if (not isinstance(price, _Number) or _number(price.text) <= 0
                or not isinstance(stamp, _Number) or not re.fullmatch(r'[1-9][0-9]{0,9}', stamp.text)):
            raise ValuationContractError('positive numeric price and integer Unix seconds required')
        observed = datetime.fromtimestamp(int(stamp.text), timezone.utc)
        retrieved, analysis, evaluated = (_instant(receipt['retrieved_at']),
                                          _instant(analysis_as_of), _instant(evaluated_at))
        if (not observed <= retrieved <= evaluated or not observed <= analysis <= evaluated
                or evaluated > datetime.now(timezone.utc)):
            raise ValuationContractError('quote chronology mismatch')
        age = int((analysis - observed).total_seconds())
        if age > maximum:
            raise ValuationContractError('quote exceeds supplied analysis-relative tolerance')
        # Never serialize arbitrary vendor extras, free text or request URLs.
        return {'mapped': True, 'admitted': False, 'launch_ready': False,
            'classification': 'offline_fmp_quote_candidate',
            'candidate': {'symbol': expected_symbol, 'provider_exchange_label': exchange,
                'price_value': price.text, 'provider_quoted_at': observed.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'timestamp_semantics': 'provider_quote_time', 'timestamp_raw_unix_seconds': stamp.text,
                'currency': None, 'price_unit': None, 'issuer_cik': None, 'listing_mic': None,
                'security_id': None, 'share_class': None, 'split_basis': None,
                'instrument_type': None, 'trade_or_close_kind': None, 'session': None},
            'raw_binding': {'sha256': receipt['sha256'], 'byte_length': len(body),
                'endpoint': ENDPOINT, 'requested_symbol': expected_symbol,
                'retrieved_at': receipt['retrieved_at'], 'status_code': 200, 'content_type': 'application/json',
                'fields': {'symbol': '/0/symbol', 'provider_exchange_label': '/0/exchange',
                           'price_value': '/0/price', 'provider_quoted_at': '/0/timestamp'}},
            'source_documentation': [DOCUMENTATION, FIELD_GUIDE],
            'observation_reference_inspectable': False,
            'analysis_as_of': analysis_as_of, 'evaluated_at': evaluated_at,
            'analysis_relative_age_seconds': age,
            'supplied_freshness_policy': dict(freshness_policy),
            'unanswered_parts': ['independently reviewed issuer/listing/security/share-class mapping',
                'source-supported currency and price unit', 'split and corporate-action basis',
                'trade/official-close semantics and session policy', 'price-to-EPS compatibility'],
            'limitations': [
                'A saved body/receipt match is not proof that FMP served these bytes.',
                'Documentation describes a schema; its URL is not an inspectable quote observation.',
                'Exchange text is not a MIC or an issuer/security identity mapping.',
                'The timestamp dates quoted data, not a certified last trade or official close.',
                'Missing semantics stay missing even if optional raw fields assert them.',
                'The supplied tolerance is not an approved market freshness policy; retrospective age is not current today.',
                'No admitted normalized capture, market multiple, EPS calculation or recommendation is produced.']}
    except (ValuationContractError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        return {'mapped': False, 'admitted': False, 'launch_ready': False,
                'classification': 'offline_fmp_quote_candidate',
                'reason': 'fmp_quote_capture_rejected', 'diagnostic_type': type(exc).__name__}
