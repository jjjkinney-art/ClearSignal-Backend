"""Offline bridge from producer-consistent annual EPS to explicit assumptions.

No market retrieval, production wiring, source-price authorization or investment
policy. Source consistency is not independent factual adjudication.
"""
from copy import deepcopy
from datetime import date
from fractions import Fraction
from decimal import (Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN,
                     InvalidOperation, DivisionByZero, Overflow)
import re

from app.providers.sec_fact_policy import ANNUAL_FORM_PREFIXES
from app.services.financial_thesis_foundation import _rebuild
from validation.valuation_scenario import (
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


def _source_eps(ticker, cik, items, references, scenario_date):
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
        if not any(isinstance(row, dict) and row.get('metric') == 'us-gaap:EarningsPerShareDiluted'
                   for row in claims):
            continue
        rebuilt = _rebuild(item, ticker=ticker, cik=cik, name='diluted EPS',
            concepts=('EarningsPerShareDiluted',), expected_unit='USD/shares')
        if (rebuilt is None or getattr(item, 'availability_status', None) != 'available'
                or not isinstance(item.document_type, str)
                or item.document_type != rebuilt.document_type
                or not item.document_type.startswith(ANNUAL_FORM_PREFIXES)):
            raise ValuationContractError('EPS requires a reconstructed available annual diluted-EPS comparison; no quarterly annualization')
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
        raise ValuationContractError('one unambiguous annual diluted-EPS comparison required')
    rebuilt, reference_id = candidates[0]
    current = rebuilt.verified_claims[0]
    value = Decimal(str(current['raw_value']))
    if value <= 0:
        raise ValuationContractError('this positive-P/E scenario requires positive annual EPS')
    return {'value': format(value, 'f'), 'unit': 'USD/shares', 'reference_id': reference_id,
            'concept': current['metric'], 'period_start': current['period_start'],
            'period_end': current['period_end'], 'filed_at': current['document_ref']['published_at'],
            'document_ref': deepcopy(current['document_ref']),
            'period_basis': 'fiscal_year', 'document_type': rebuilt.document_type,
            'source_consistency_reconstructed': True,
            'independently_adjudicated': False}


def evaluate_source_anchored_scenario(ticker, items, references, *, expected_cik,
                                      assumptions, evaluated_at):
    """Keep the observed fiscal EPS separate from every hypothetical operand.

    No source observation may be asserted for price/exit multiple/return/growth.
    Share/split/earnings-scope compatibility remains an explicit user assertion.
    """
    try:
        if not isinstance(assumptions, dict):
            raise ValuationContractError('explicit scenario assumption object required')
        mode = assumptions.get('mode')
        if not isinstance(mode, str) or mode not in {'evaluate_growth_scenario', 'solve_required_earnings_growth'}:
            raise ValuationContractError('explicit supported scenario mode required')
        rate_key = 'eps_growth_rate' if mode == 'evaluate_growth_scenario' else 'annual_price_return_rate'
        _object(assumptions, {'mode', 'scenario_as_of', 'price', 'price_per_underlying_common_share',
                             'eps_basis', 'exit_pe', 'horizon', rate_key, 'distributions'}, 'assumptions')
        scenario_date, evaluated = _calendar(assumptions['scenario_as_of']), _calendar(evaluated_at)
        if not scenario_date <= evaluated <= date.today():
            raise ValuationContractError('scenario/evaluation dates cannot be in the future')
        if assumptions['price_per_underlying_common_share'] is not True:
            raise ValuationContractError('explicit underlying-common-share price assumption required; no ADR conversion')
        basis = assumptions['eps_basis']
        _basis(basis)
        if (basis['issuer'] != ticker or basis['currency'] != 'USD'
                or basis['share_basis'] != 'diluted' or basis['accounting'] != 'gaap'
                or basis['period_basis'] != 'fiscal_year'):
            raise ValuationContractError('annual USD GAAP diluted-EPS basis for the exact issuer required')
        for key in ('price', 'exit_pe', 'horizon', rate_key):
            _assumption(assumptions[key])
        _object(assumptions['exit_pe'], {'value', 'unit', 'provenance'}, 'exit_pe assumption')
        price = _operand(assumptions['price'], unit='USD/share')
        exit_multiple = _operand(assumptions['exit_pe'], unit='x')
        if price <= 0:
            raise ValuationContractError('explicit positive hypothetical price required')
        eps = _source_eps(ticker, expected_cik, items, references, scenario_date)
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
            entry_pe_derivation={'formula': 'assumed_price / reported_fiscal_diluted_eps',
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
            'Entry P/E is a rounded conditional ratio, not an observed market multiple.',
            'Source consistency reconstruction is not independent factual adjudication.']
        return result
    except (ValuationContractError, DecimalException) as exc:
        return {'available': False, 'status': 'insufficient_valuation_inputs',
                'classification': 'source_anchored_conditional_fiscal_eps_scenario',
                'reason': str(exc), 'launch_ready': False,
                'limitations': ['No calculation supplied; no market valuation, expected return or recommendation established.']}
