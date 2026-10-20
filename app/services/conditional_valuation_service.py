"""Server-owned annual EPS for explicit conditional scenarios; opt-in only."""
from datetime import datetime, timezone
import re

from app.config import settings
from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_client import get_company_fact_records_for_concept_units
from app.providers.sec_fact_policy import REPORTING_CURRENCIES
from app.services.issuer_identity import _load_directory, exact_issuer
from app.services.evidence_references import admit_evidence
from app.services.source_anchored_valuation import (
    _calendar, evaluate_source_anchored_scenario, evaluate_basic_source_anchored_scenario,
)
from app.services.earnings_recovery_scenario import (
    evaluate_earnings_recovery, evaluate_basic_earnings_recovery, MODE,
)
from app.services.conditional_valuation_math import ValuationContractError, _object, load_scenario

MAX_REQUEST_BYTES = 16_384
MODES = {MODE, 'evaluate_growth_scenario', 'solve_required_earnings_growth'}
CONCEPT_UNITS = (('EarningsPerShareDiluted', 'USD/shares'), ('EarningsPerShareBasic', 'USD/shares'),
                 *(('Assets', currency) for currency in REPORTING_CURRENCIES))


def _current_date():
    return datetime.now(timezone.utc).date()


def parse_scenario_request(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_REQUEST_BYTES:
        raise ValuationContractError('bounded request body required')
    try:
        payload = load_scenario(raw.decode('utf-8'))
    except UnicodeDecodeError as exc:
        raise ValuationContractError('UTF-8 JSON required') from exc
    _object(payload, {'ticker', 'assumptions'}, 'conditional scenario request')
    ticker, assumptions = payload['ticker'], payload['assumptions']
    if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z]{1,5}(?:\.[A-Z])?', ticker):
        raise ValuationContractError('exact supported ticker required')
    if not isinstance(assumptions, dict) or not isinstance(assumptions.get('mode'), str) or assumptions['mode'] not in MODES:
        raise ValuationContractError('explicit supported conditional mode required')
    basis = assumptions.get('eps_basis')
    if (not isinstance(basis, dict) or not isinstance(basis.get('share_basis'), str)
            or basis['share_basis'] not in ('basic', 'diluted')):
        raise ValuationContractError('explicit basic or diluted EPS basis required; no fallback')
    boundary = _calendar(assumptions.get('scenario_as_of'))
    if boundary != _current_date():
        raise ValuationContractError('this current-issuer endpoint requires today in UTC; historical identity is unsupported')
    return payload


def _gap(stage):
    return {'available': False, 'status': 'insufficient_conditional_scenario_evidence',
        'stage': stage, 'admitted': False, 'launch_ready': False,
        'scenario': None, 'source_claims': [], 'evidence_references': []}


def evaluate_requested_scenario(payload):
    """No caller CIK/evidence/approval, quote retrieval, model or persistence path.

    This is deliberately separate from /ask. Both feature and data-retrieval
    switches must be explicitly enabled by deployment configuration.
    """
    if settings.conditional_valuation_scenarios_enabled is not True:
        return _gap('feature_disabled')
    if settings.enable_data_retrieval is not True:
        return _gap('retrieval_disabled')
    try:
        # Recheck direct service callers as well as parsed HTTP requests.
        import json
        payload = parse_scenario_request(json.dumps(payload, allow_nan=False).encode())
    except (ValuationContractError, TypeError, ValueError):
        return _gap('request_contract')
    ticker, assumptions = payload['ticker'], payload['assumptions']
    share_basis = assumptions['eps_basis']['share_basis']
    concept = 'EarningsPerShareBasic' if share_basis == 'basic' else 'EarningsPerShareDiluted'
    boundary = _calendar(assumptions['scenario_as_of'])
    try:
        issuer = exact_issuer(ticker, _load_directory())
        cik = issuer.cik if issuer is not None and issuer.ticker == ticker else None
        if (not isinstance(cik, str) or not re.fullmatch(r'[0-9]{1,10}', cik) or int(cik) == 0):
            return _gap('issuer_identity')
        records = get_company_fact_records_for_concept_units(cik, concept_units=CONCEPT_UNITS,
            user_agent=settings.sec_user_agent)
        eligible = [row for row in records if row.cik.lstrip('0') == cik.lstrip('0')
            and row.form in ('10-K', '10-K/A')
            and _calendar(row.filed) <= boundary and _calendar(row.end) <= boundary]
        eps_rows = [row for row in eligible if row.concept == concept and row.unit == 'USD/shares']
        item = comparable_metric_evidence(eps_rows, ticker=ticker, expected_cik=cik,
            concepts=(concept,), metric_name=share_basis + ' EPS', unit='USD/shares')
        if item is None:
            return _gap('annual_' + share_basis + '_eps')
        current = item.verified_claims[0]
        annual_assets = [row for row in eligible if row.concept == 'Assets' and row.start is None
                         and row.unit in REPORTING_CURRENCIES]
        if not annual_assets or max(row.end for row in annual_assets) != current['period_end']:
            return _gap('latest_annual_reporting_period')
        # An exact source accession/currency anchor is required; no convenience
        # USD translation or missing currency may stand in for reporting currency.
        source_accession = current['document_ref']['reference_id'].split(':')[2]
        currencies = {row.unit for row in annual_assets if row.end == current['period_end']
            and row.accession == source_accession and row.filed == current['document_ref']['published_at']}
        if currencies != {'USD'}:
            return _gap('annual_reporting_currency')
        items, references = admit_evidence([item], evaluated_at=boundary.isoformat())[:2]
        evaluated = _current_date().isoformat()
        if share_basis == 'basic':
            evaluator = evaluate_basic_earnings_recovery if assumptions['mode'] == MODE else evaluate_basic_source_anchored_scenario
        else:
            evaluator = evaluate_earnings_recovery if assumptions['mode'] == MODE else evaluate_source_anchored_scenario
        result = evaluator(ticker, items, references, expected_cik=cik,
            assumptions=assumptions, evaluated_at=evaluated)
        if not result['available']:
            return {'available': False, 'status': 'insufficient_conditional_scenario_inputs',
                'stage': 'scenario_contract', 'admitted': False, 'launch_ready': False,
                'scenario': result, 'source_claims': [], 'evidence_references': []}
        return {'available': True, 'status': 'partial', 'classification': 'explicit_hypothetical_valuation_scenario',
            'admitted': False, 'launch_ready': False, 'scenario': result,
            'source_claims': item.verified_claims, 'evidence_references': references,
            'as_of': boundary.isoformat(), 'evaluated_at': evaluated,
            'market_price_observed': False, 'market_pe_verified': False,
            'source_selection': 'latest_available_annual_usd_gaap_' + share_basis + '_eps_with_same_filing_assets_currency_anchor',
            'limitations': ['Explicit hypothetical assumptions are not source observations or forecasts.',
                'EPS uses the explicitly requested ' + share_basis + ' basis; no basic/diluted substitution or dilution forecast is established.',
                'References support reported historical EPS only, not future EPS, prices or valuation multiples.',
                'Source consistency is not independent factual adjudication or quote/share/split compatibility.',
                'No portfolio, conversation, thesis snapshot or alert was written.']}
    except Exception:
        # Provider/producer failures must not expose credential-bearing errors,
        # raw source bodies or partially assembled claims in the API response.
        return _gap('source_unavailable')
