"""Offline consistency audit of an explicit normalized price capture.

No provider fetch, evidence admission, freshness policy approval or security-master
authority. A matching receipt proves byte consistency, not external authenticity.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

from validation.valuation_scenario import ValuationContractError, _number, _object

MAX_CAPTURE_BYTES = 65_536  # normalized JSON computational bound, not a transport change
SECURITY_KEYS = {'symbol', 'issuer_cik', 'listing_mic', 'security_id', 'share_class',
                 'instrument_type', 'currency', 'price_unit', 'split_basis'}


def _text(value, label, maximum=160):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValuationContractError(f'{label}: bounded explicit text required')


def _instant(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value)):
        raise ValuationContractError('timestamps require second-resolution UTC YYYY-MM-DDTHH:MM:SSZ')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValuationContractError('invalid calendar timestamp') from exc


def _public_reference(value):
    _text(value, 'source URL', 1000)
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme != 'https' or not host or parts.username or parts.password
                or parts.port is not None or parts.query or parts.fragment
                or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', host)
                or '.' not in host or host.endswith(('.local', '.internal', '.localhost'))
                or '%' in value or '\\' in value or any(c.isspace() for c in value)):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
    except ValueError as exc:
        raise ValuationContractError('credential-free HTTPS domain reference without query, fragment or port required') from exc


def _security(value):
    _object(value, SECURITY_KEYS, 'security binding')
    for key in SECURITY_KEYS:
        _text(value[key], key)
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', value['symbol']):
        raise ValuationContractError('exact normalized symbol required')
    if not re.fullmatch(r'[0-9]{10}', value['issuer_cik']) or int(value['issuer_cik']) == 0:
        raise ValuationContractError('explicit ten-digit issuer CIK required')
    if not re.fullmatch(r'[A-Z0-9]{4}', value['listing_mic']):
        raise ValuationContractError('explicit listing MIC required')
    if (value['instrument_type'] != 'underlying_common_share'
            or value['currency'] != 'USD' or value['price_unit'] != 'USD/share'):
        raise ValuationContractError('this first contract supports USD underlying common shares only; no FX/ADR conversion')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValuationContractError('duplicate JSON key')
        result[key] = value
    return result


def audit_dated_price_capture(body, receipt, *, expected_security, expected_source_url,
                              analysis_as_of, evaluated_at, freshness_policy):
    """Audit saved normalized bytes against separately supplied expected bindings.

    Freshness is relative to an explicit analysis instant, not a claim that an old
    quote is current today. Caller policy/security/receipt remain untrusted inputs
    pending independent source and policy review. Output cannot authorize EPS
    arithmetic, an evidence reference or a production answer.
    """
    try:
        if type(body) is not bytes or not 0 < len(body) <= MAX_CAPTURE_BYTES:
            raise ValuationContractError('nonempty normalized bytes within 65536-byte bound required')
        _object(receipt, {'sha256', 'byte_length', 'source_url', 'retrieved_at'}, 'receipt')
        if (type(receipt['byte_length']) is not int or receipt['byte_length'] != len(body)
                or not isinstance(receipt['sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', receipt['sha256'])
                or receipt['sha256'] != hashlib.sha256(body).hexdigest()):
            raise ValuationContractError('receipt hash/length mismatch')
        _public_reference(expected_source_url)
        if receipt['source_url'] != expected_source_url:
            raise ValuationContractError('receipt does not match expected source URL')
        _security(expected_security)
        _object(freshness_policy, {'policy_id', 'max_age_seconds'}, 'explicit freshness policy')
        _text(freshness_policy['policy_id'], 'freshness policy ID')
        maximum = freshness_policy['max_age_seconds']
        if type(maximum) is not int or not 0 <= maximum <= 604800:
            raise ValuationContractError('explicit freshness tolerance from 0 to 604800 seconds required (computational bound)')
        def reject_number(_):
            raise ValuationContractError('capture scalars require explicit strings, not JSON numbers')
        payload = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                             parse_int=reject_number, parse_float=reject_number,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValuationContractError('non-finite JSON number')))
        _object(payload, {'schema', 'security', 'observation', 'source_url'}, 'price capture')
        if payload['schema'] != 'dated-price-capture-v1' or payload['source_url'] != expected_source_url:
            raise ValuationContractError('schema/source URL mismatch')
        _security(payload['security'])
        if payload['security'] != expected_security:
            raise ValuationContractError('security/issuer/listing/share/currency/split binding mismatch')
        observation = payload['observation']
        _object(observation, {'value', 'kind', 'observed_at', 'session', 'source_field'}, 'price observation')
        if observation['kind'] not in ('last_trade', 'official_close'):
            raise ValuationContractError('explicit trade or official close required; bid/ask/profile unsupported')
        if observation['session'] != 'regular':
            raise ValuationContractError('explicit regular-session observation required')
        _text(observation['source_field'], 'source field')
        if _number(observation['value']) <= Decimal(0):
            raise ValuationContractError('positive finite decimal-string price required')
        observed = _instant(observation['observed_at'])
        retrieved = _instant(receipt['retrieved_at'])
        analysis, evaluated = _instant(analysis_as_of), _instant(evaluated_at)
        if not observed <= retrieved <= evaluated or not observed <= analysis <= evaluated:
            raise ValuationContractError('observation/retrieval/analysis/evaluation chronology mismatch')
        if evaluated > datetime.now(timezone.utc):
            raise ValuationContractError('evaluation cannot be in the future')
        age = int((analysis - observed).total_seconds())
        if age > maximum:
            raise ValuationContractError('observation exceeds supplied analysis-relative freshness tolerance')
        return {'contract_passed': True, 'admitted': False, 'launch_ready': False,
            'classification': 'offline_normalized_price_capture_audit',
            'security': deepcopy(payload['security']), 'observation': deepcopy(observation),
            'receipt': deepcopy(receipt), 'analysis_as_of': analysis_as_of, 'evaluated_at': evaluated_at,
            'analysis_relative_age_seconds': age, 'supplied_freshness_policy': deepcopy(freshness_policy),
            'independently_adjudicated': False, 'market_session_verified': False,
            'security_mapping_verified': False, 'eps_compatibility_verified': False,
            'limitations': [
                'Hash/length establish consistency of supplied normalized bytes and receipt, not source authenticity.',
                'No vendor response was parsed; a reviewed provider adapter and raw-to-normalized field binding remain required.',
                'Security mapping, split basis, session and freshness policy are supplied assertions pending review.',
                'Freshness is relative to analysis_as_of, not a statement that this observation is current today.',
                'No EPS basis, market multiple, valuation scenario, evidence admission or recommendation is authorized.']}
    except (ValuationContractError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        # Fixed diagnostic only: parser errors must not echo body values or URLs.
        return {'contract_passed': False, 'admitted': False, 'launch_ready': False,
                'classification': 'offline_normalized_price_capture_audit',
                'reason': 'price_capture_contract_rejected', 'diagnostic_type': type(exc).__name__}
