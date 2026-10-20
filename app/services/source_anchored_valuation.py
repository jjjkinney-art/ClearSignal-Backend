"""Pure bridge from producer-consistent annual EPS to explicit assumptions.

No market retrieval, source-price authorization or investment
policy. Source consistency is not independent factual adjudication.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from fractions import Fraction
from decimal import (Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN,
                     InvalidOperation, DivisionByZero, Overflow)
import re

from app.providers.sec_fact_policy import ANNUAL_FORM_PREFIXES, REPORTING_CURRENCIES
from app.services.financial_thesis_foundation import _rebuild
from app.services.conditional_valuation_math import (
    ValuationContractError, _object, _operand, _basis, evaluate_scenario,
)


def _calendar(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValuationContractError('explicit ISO calendar dates required') from exc


def _assumption(value):
    if (not isinstance(value, dict) or not isinstance(value.get('provenance'), dict)
            or value['provenance'].get('kind') != 'user_assumption'):
        raise ValuationContractError('scenario operands must be explicit user assumptions, not source-price assertions')


def _annual_eps_context(ticker, cik, items, references, scenario_date, *, share_basis="diluted", currency="USD"):
    """Reconstruct signed annual EPS as source context, not positive-P/E authority."""
    if not isinstance(share_basis, str) or share_basis not in ('basic', 'diluted'):
        raise ValuationContractError('explicit supported source share basis required')
    if not isinstance(currency, str) or currency not in REPORTING_CURRENCIES:
        raise ValuationContractError('explicit supported reporting currency required')
    unit = currency + '/shares'
    concept = 'EarningsPerShareBasic' if share_basis == 'basic' else 'EarningsPerShareDiluted'
    if (not isinstance(cik, str) or not cik.isdigit() or int(cik) == 0
            or not isinstance(references, list) or not references
            or not all(isinstance(ref, dict) for ref in references)):
        raise ValuationContractError('trusted issuer CIK and admitted response references required')
    if not isinstance(items, (list, tuple)):
        raise ValuationContractError('producer evidence items must be a list or tuple')
    candidates = []
    for item in items:
        claims = getattr(item, 'verified_claims', [])
        if not isinstance(claims, list):
            raise ValuationContractError('source claims require the producer comparison contract')
        if not any(isinstance(row, dict) and row.get('metric') == 'us-gaap:' + concept
                   for row in claims):
            continue
        rebuilt = _rebuild(item, ticker=ticker, cik=cik, name=share_basis + ' EPS',
            concepts=(concept,), expected_unit=unit)
        if (rebuilt is None or getattr(item, 'availability_status', None) != 'available'
                or not isinstance(item.document_type, str)
                or item.document_type != rebuilt.document_type
                or not item.document_type.startswith(ANNUAL_FORM_PREFIXES)):
            raise ValuationContractError('EPS requires a reconstructed available annual comparison of the requested share basis; no quarterly annualization')
        current = rebuilt.verified_claims[0]
        if any(_calendar(row['document_ref']['published_at']) > scenario_date
               or _calendar(row['period_end']) > scenario_date for row in rebuilt.verified_claims):
            raise ValuationContractError('EPS evidence was not available by the scenario date')
        matches = [ref for ref in references
            if ref.get('title') == item.title.strip()[:300]
            and ref.get('source') == item.source.strip()[:120]
            and ref.get('url') == item.url and ref.get('published_at') == item.timestamp]
        if len(matches) != 1:
            raise ValuationContractError('EPS needs one exact admitted response reference')
        ref = matches[0]
        if (not re.fullmatch(r'E[1-9]\d*', str(ref.get('id', '')))
                or sum(r.get('id') == ref['id'] for r in references) != 1
                or ref.get('claim_type') != 'reported_fact'
                or ref.get('source_type') != 'regulatory_filing' or ref.get('source_tier') != 'primary'
                or ref.get('document_type') != item.document_type
                or ref.get('extraction_method') != 'structured_xbrl'
                or ref.get('filed_at') != item.timestamp
                or ref.get('reporting_period_start') != current['period_start']
                or ref.get('reporting_period_end') != current['period_end']
                or not isinstance(ref.get('freshness_status'), (str, type(None)))
                or ref.get('freshness_status') in {'stale', 'conflicting', 'superseded', 'unavailable'}):
            raise ValuationContractError('EPS reference is ambiguous or unavailable')
        candidates.append((rebuilt, ref['id']))
    if not candidates or len({repr(row[0].verified_claims) for row in candidates}) != 1:
        raise ValuationContractError('one unambiguous annual comparison of the requested EPS share basis required')
    rebuilt, reference_id = candidates[0]
    current = rebuilt.verified_claims[0]
    value = Decimal(str(current['raw_value']))
    return {'value': format(value, 'f'), 'unit': unit, 'currency': currency, 'reference_id': reference_id,
            'concept': current['metric'], 'share_basis': share_basis, 'period_start': current['period_start'],
            'period_end': current['period_end'], 'filed_at': current['document_ref']['published_at'],
            'document_ref': deepcopy(current['document_ref']),
            'period_basis': 'fiscal_year', 'document_type': rebuilt.document_type,
            'source_consistency_reconstructed': True,
            'independently_adjudicated': False}


def _source_eps(ticker, cik, items, references, scenario_date, *, share_basis="diluted", currency="USD"):
    """Keep the existing positive-P/E bridge and quote-binding contract strict."""
    eps = _annual_eps_context(ticker, cik, items, references, scenario_date, share_basis=share_basis, currency=currency)
    if Decimal(eps['value']) <= 0:
        raise ValuationContractError('this positive-P/E scenario requires positive annual EPS')
    return eps


def evaluate_source_anchored_scenario(ticker, items, references, *, expected_cik,
                                      assumptions, evaluated_at):
    """Original diluted-EPS entry point; basic EPS never satisfies it."""
    return evaluate_explicit_annual_eps_scenario(ticker, items, references, expected_cik=expected_cik,
        assumptions=assumptions, evaluated_at=evaluated_at, share_basis='diluted', currency='USD')


def evaluate_basic_source_anchored_scenario(ticker, items, references, *, expected_cik,
                                            assumptions, evaluated_at):
    """Separate explicit basic-EPS hypothesis; never conversion to diluted EPS."""
    return evaluate_explicit_annual_eps_scenario(ticker, items, references, expected_cik=expected_cik,
        assumptions=assumptions, evaluated_at=evaluated_at, share_basis='basic', currency='USD')


def evaluate_explicit_annual_eps_scenario(ticker, items, references, *, expected_cik,
                                      assumptions, evaluated_at, share_basis, currency):
    """Keep the observed fiscal EPS separate from every hypothetical operand.

    No source observation may be asserted for price/exit multiple/return/growth.
    Share/split/earnings-scope compatibility remains an explicit user assertion.
    """
    try:
        if not isinstance(currency, str) or currency not in REPORTING_CURRENCIES:
            raise ValuationContractError('explicit supported reporting currency required')
        if not isinstance(assumptions, dict):
            raise ValuationContractError('explicit scenario assumption object required')
        mode = assumptions.get('mode')
        if not isinstance(mode, str) or mode not in {'evaluate_growth_scenario', 'solve_required_earnings_growth'}:
            raise ValuationContractError('explicit supported scenario mode required')
        rate_key = 'eps_growth_rate' if mode == 'evaluate_growth_scenario' else 'annual_price_return_rate'
        _object(assumptions, {'mode', 'scenario_as_of', 'price', 'price_per_underlying_common_share',
                             'eps_basis', 'exit_pe', 'horizon', rate_key, 'distributions'}, 'assumptions')
        scenario_date, evaluated = _calendar(assumptions['scenario_as_of']), _calendar(evaluated_at)
        if not scenario_date <= evaluated <= datetime.now(timezone.utc).date():
            raise ValuationContractError('scenario/evaluation dates cannot be in the future')
        if assumptions['price_per_underlying_common_share'] is not True:
            raise ValuationContractError('explicit underlying-common-share price assumption required; no ADR conversion')
        basis = assumptions['eps_basis']
        _basis(basis)
        if (basis['issuer'] != ticker or basis['currency'] != currency
                or basis['share_basis'] != share_basis or basis['accounting'] != 'gaap'
                or basis['period_basis'] != 'fiscal_year'
                or ((share_basis == 'basic' or currency == 'EUR') and basis['earnings_scope'] != 'total_operations')):
            raise ValuationContractError('annual same-currency GAAP EPS basis must match the explicitly selected source share basis and issuer')
        for key in ('price', 'exit_pe', 'horizon', rate_key):
            _assumption(assumptions[key])
        _object(assumptions['exit_pe'], {'value', 'unit', 'provenance'}, 'exit_pe assumption')
        price = _operand(assumptions['price'], unit=currency + '/share')
        exit_multiple = _operand(assumptions['exit_pe'], unit='x')
        if price <= 0:
            raise ValuationContractError('explicit positive hypothetical price required')
        eps = _source_eps(ticker, expected_cik, items, references, scenario_date, share_basis=share_basis, currency=currency)
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999,
                                  Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow])):
            entry_pe = price / Decimal(eps['value'])
        if (entry_pe == exit_multiple
                and Fraction(price) / Fraction(Decimal(eps['value'])) != Fraction(exit_multiple)):
            raise ValuationContractError('entry-ratio difference from exit multiple was lost at 50-digit precision')
        payload = {'mode': mode, 'distributions': assumptions['distributions'],
            'entry_pe': {'value': format(entry_pe, 'f'), 'unit': 'x', 'eps_basis': deepcopy(basis),
                'provenance': {'kind': 'user_assumption',
                    'reference': 'Scenario ratio derived from explicitly assumed price and historical fiscal EPS ' + eps['reference_id']}},
            'exit_pe': {**deepcopy(assumptions['exit_pe']), 'eps_basis': deepcopy(basis)},
            'horizon': deepcopy(assumptions['horizon']), rate_key: deepcopy(assumptions[rate_key])}
        result = evaluate_scenario(payload)
        if not result['available']:
            raise ValuationContractError(result['reason'])
        result.update(classification='source_anchored_conditional_fiscal_eps_scenario',
            status='partial', launch_ready=False, source_eps=eps,
            supplied_assumptions=deepcopy(assumptions),
            entry_pe_derivation={'formula': 'assumed_price / reported_fiscal_' + share_basis + '_eps',
                'value': format(entry_pe, 'f'), 'unit': 'x', 'price_status': 'user_assumption',
                'eps_reference_ids': [eps['reference_id']], 'precision_digits': 50,
                'rounding': 'ROUND_HALF_EVEN', 'market_pe_verified': False},
            basis_verification={'issuer_currency_concept_period': 'producer_consistency_reconstructed',
                'earnings_scope_and_split_basis': 'user_assertions_not_independently_verified'},
            unanswered_parts=['observed market price and security/share-basis verification',
                              'independently supported future earnings and exit valuation',
                              'expected total returns and investment attractiveness'])
        result['limitations'] += [
            'The source anchor is a historical fiscal year, not current TTM or forward EPS.',
            'The price is hypothetical; no market observation or price freshness is verified.',
            'Split/security conversion and earnings-scope compatibility remain user assertions.',
            'The requested EPS basis is ' + share_basis + '; no basic/diluted substitution or dilution forecast is established.',
            'Entry P/E is a rounded conditional ratio, not an observed market multiple.',
            'Source consistency reconstruction is not independent factual adjudication.']
        return result
    except (ValuationContractError, DecimalException) as exc:
        return {'available': False, 'status': 'insufficient_valuation_inputs',
                'classification': 'source_anchored_conditional_fiscal_eps_scenario',
                'reason': str(exc), 'launch_ready': False,
                'limitations': ['No calculation supplied; no market valuation, expected return or recommendation established.']}
