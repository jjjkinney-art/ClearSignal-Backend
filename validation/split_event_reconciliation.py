"""Offline listed-split factors under explicit calendar-basis assumptions.

Not a complete corporate-action feed, source EPS adjustment or valuation grant.
"""
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import re

from validation.dated_price import MAX_CAPTURE_BYTES, _instant, _pairs, _text
from validation.fmp_quote_capture import _Number
from validation.source_anchored_valuation import _calendar
from validation.valuation_scenario import ValuationContractError, _object

ENDPOINT = 'https://financialmodelingprep.com/stable/splits'
DOCUMENTATION = 'https://site.financialmodelingprep.com/developer/docs/stable/splits-company'
MAX_FACTOR_EVENTS = 128
MAX_RATIO_PART = 1_000_000


def _fraction(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def reconcile_listed_splits(body, receipt, *, expected_symbol, basis_assumption,
                             evaluated_at, retrieval_age_policy):
    """Never infer the EPS split-basis cutoff from its period end or filed date.

    Numerator/denominator describe new/old shares. Include only supplied events
    strictly after the assumed already-adjusted date and before the comparison
    date. Same-day comparison events require intraday/session evidence instead.
    """
    try:
        if (type(body) is not bytes or not 0 < len(body) <= MAX_CAPTURE_BYTES
                or not isinstance(expected_symbol, str)
                or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', expected_symbol)):
            raise ValuationContractError('bounded raw body and exact symbol required')
        _object(receipt, {'sha256', 'byte_length', 'endpoint', 'requested_symbol',
            'requested_limit', 'retrieved_at', 'status_code', 'content_type'}, 'split receipt')
        limit = receipt['requested_limit']
        if (receipt['endpoint'] != ENDPOINT or receipt['requested_symbol'] != expected_symbol
                or type(limit) is not int or not 1 <= limit <= 1000
                or type(receipt['status_code']) is not int or receipt['status_code'] != 200
                or receipt['content_type'] != 'application/json'
                or type(receipt['byte_length']) is not int or receipt['byte_length'] != len(body)
                or not isinstance(receipt['sha256'], str)
                or receipt['sha256'] != hashlib.sha256(body).hexdigest()):
            raise ValuationContractError('split receipt mismatch')
        _object(basis_assumption, {'already_adjusted_through', 'comparison_date', 'provenance'}, 'basis assumption')
        _object(basis_assumption['provenance'], {'kind', 'reference'}, 'basis provenance')
        if basis_assumption['provenance']['kind'] != 'user_assumption':
            raise ValuationContractError('explicit hypothetical basis assumptions required')
        _text(basis_assumption['provenance']['reference'], 'basis reference')
        first = _calendar(basis_assumption['already_adjusted_through'])
        last = _calendar(basis_assumption['comparison_date'])
        evaluated, retrieved = _instant(evaluated_at), _instant(receipt['retrieved_at'])
        if not first <= last <= evaluated.date() or not retrieved <= evaluated <= datetime.now(timezone.utc):
            raise ValuationContractError('basis/retrieval/evaluation chronology mismatch')
        _object(retrieval_age_policy, {'policy_id', 'max_age_seconds'}, 'retrieval age policy')
        _text(retrieval_age_policy['policy_id'], 'policy ID')
        maximum = retrieval_age_policy['max_age_seconds']
        if type(maximum) is not int or not 0 <= maximum <= 604800:
            raise ValuationContractError('explicit bounded retrieval tolerance required')
        if (evaluated - retrieved).total_seconds() > maximum:
            raise ValuationContractError('saved split retrieval exceeds supplied tolerance')
        def reject_constant(_):
            raise ValuationContractError('nonfinite JSON constant')
        rows = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
            parse_int=_Number, parse_float=_Number, parse_constant=reject_constant)
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValuationContractError('bounded split record list required')
        events, dates = [], set()
        for index, row in enumerate(rows):
            if (not isinstance(row, dict) or row.get('symbol') != expected_symbol
                    or row.get('splitType') != 'stock-split'):
                raise ValuationContractError('exact-symbol ordinary stock-split records required')
            day = _calendar(row.get('date'))
            if day in dates:
                raise ValuationContractError('same-date duplicate/conflicting events are ambiguous')
            dates.add(day)
            parts = []
            for key in ('numerator', 'denominator'):
                number = row.get(key)
                if (not isinstance(number, _Number) or not re.fullmatch(r'[1-9][0-9]{0,6}', number.text)
                        or int(number.text) > MAX_RATIO_PART):
                    raise ValuationContractError('bounded positive whole-number split components required')
                parts.append(int(number.text))
            factor = Fraction(*parts)
            events.append({'date': day.isoformat(), 'new_shares': str(parts[0]), 'old_shares': str(parts[1]),
                'new_shares_per_old_share': _fraction(factor),
                'role': 'already_in_assumed_basis' if day <= first else
                        'comparison_day_ambiguous' if day == last else
                        'listed_in_assumed_interval' if day < last else 'outside_assumed_interval',
                'fields': {key: f'/{index}/{key}' for key in
                           ('symbol', 'date', 'numerator', 'denominator', 'splitType')}})
        events.sort(key=lambda event: event['date'])
        applicable = [event for event in events if event['role'] == 'listed_in_assumed_interval']
        ambiguous = any(event['role'] == 'comparison_day_ambiguous' for event in events)
        if len(applicable) > MAX_FACTOR_EVENTS:
            raise ValuationContractError('factor event computational bound')
        result = {'mapped': True, 'status': 'partial', 'admitted': False, 'launch_ready': False,
            'classification': 'offline_listed_split_reconciliation', 'events': events,
            'raw_binding': dict(receipt), 'source_documentation': DOCUMENTATION,
            'basis_assumption': {'already_adjusted_through': first.isoformat(), 'comparison_date': last.isoformat(),
                'provenance': dict(basis_assumption['provenance'])},
            'supplied_retrieval_age_policy': dict(retrieval_age_policy),
            'requested_limit_reached': len(rows) == limit,
            'event_interval_completeness_verified': False, 'split_compatibility_verified': False,
            'eps_basis_verified': False, 'security_mapping_verified': False,
            'observation_reference_inspectable': False, 'independently_adjudicated': False,
            'unanswered_parts': ['complete relevant corporate-action interval, including non-split changes',
                'source-supported EPS already-adjusted basis and share-class identity',
                'market-calendar/intraday event effectiveness and source observation admission'],
            'limitations': ['The feed may be limited or incomplete even when fewer rows than requested are returned.',
                'A matching body/receipt is consistency, not proof the provider served these bytes.',
                'Calendar basis dates are hypothetical user assumptions, not filing-derived EPS split-basis facts.',
                'Numerator/denominator are new/old shares; the inverse factor is only conditional EPS scaling algebra.',
                'No EPS amount, quote price, P/E, conversion, recommendation or product evidence is changed.']}
        if not applicable or ambiguous:
            result.update(status='insufficient_corporate_action_evidence',
                factor_status='comparison_day_requires_effective_time' if ambiguous else 'no_applicable_events_does_not_establish_identity')
            return result
        factor = Fraction(1)
        for event in applicable:
            factor *= Fraction(int(event['new_shares']), int(event['old_shares']))
        result.update(factor_status='listed_events_only_conditional_on_assumed_basis',
            listed_event_share_factor=_fraction(factor), conditional_eps_multiplier=_fraction(1/factor),
            applied_event_dates=[event['date'] for event in applicable])
        return result
    except (ValuationContractError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        return {'mapped': False, 'status': 'insufficient_corporate_action_evidence',
            'admitted': False, 'launch_ready': False, 'classification': 'offline_listed_split_reconciliation',
            'reason': 'listed_split_reconciliation_rejected', 'diagnostic_type': type(exc).__name__}
