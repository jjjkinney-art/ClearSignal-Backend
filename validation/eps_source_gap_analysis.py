"""Bounded offline EPS source-candidate diagnostics; no application admission."""
from datetime import date, datetime, timezone
import hashlib
import json
import math

FACTS_LIMIT = 16_777_216
ISSUER_CIKS = {'ASML': '937966', 'NPK': '80172', 'ACHC': '1520697'}
SOURCES_BY_ISSUER = {ticker: 'https://data.sec.gov/api/xbrl/companyfacts/CIK' + cik.zfill(10) + '.json'
                     for ticker, cik in ISSUER_CIKS.items()}


def validate_analysis_date(value):
    try:
        if (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value
                or date.fromisoformat(value) > datetime.now(timezone.utc).date()):
            raise ValueError
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('explicit canonical nonfuture UTC analysis date required') from None


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON keys refused')
        value[key] = item
    return value


def _float(text):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError('nonfinite JSON numbers refused')
    return number


def _constant(_):
    raise ValueError('nonfinite JSON constants refused')


def analyze_eps_facts(body, *, issuer, analysis_as_of):
    """Report annual candidates at a fixed date, without identity/price authority.

    ACHC is permitted for offline retained-file compatibility only. The capture
    wire's independent immutable source list contains ASML and NPK, not ACHC.
    """
    from app.providers.sec_client import parse_company_fact_records
    from app.integrity.sec_metric_evidence import comparable_metric_evidence
    from app.providers.sec_fact_policy import REPORTING_CURRENCIES
    boundary = validate_analysis_date(analysis_as_of)
    if type(body) is not bytes or not 0 < len(body) <= FACTS_LIMIT or issuer not in ISSUER_CIKS:
        raise ValueError('bounded known-issuer facts input required')
    data = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_float=_float, parse_constant=_constant)
    if (type(data) is not dict or type(data.get('facts')) is not dict
            or not isinstance(data.get('cik'), (str, int)) or isinstance(data['cik'], bool)
            or not str(data['cik']).isascii() or not str(data['cik']).isdigit()
            or not 1 <= len(str(data['cik'])) <= 10
            or str(data['cik']).lstrip('0') != ISSUER_CIKS[issuer]):
        raise ValueError('unexpected facts identity or structure')

    def eligible(row):
        if row.cik.lstrip('0') != ISSUER_CIKS[issuer] or row.form not in ('10-K', '10-K/A', '20-F', '20-F/A'):
            return False
        filed, end = date.fromisoformat(row.filed), date.fromisoformat(row.end)
        if filed.isoformat() != row.filed or end.isoformat() != row.end:
            raise ValueError('noncanonical source dates refused')
        return filed <= boundary and end <= boundary

    assets = [row for currency in REPORTING_CURRENCIES
              for row in parse_company_fact_records(data, concept='Assets', unit=currency)
              if eligible(row) and row.start is None]
    latest_assets_end = max((row.end for row in assets), default=None)
    diagnostics = []
    for basis, concept in (('basic', 'EarningsPerShareBasic'), ('diluted', 'EarningsPerShareDiluted')):
        for currency in REPORTING_CURRENCIES:
            unit = currency + '/shares'
            parsed = parse_company_fact_records(data, concept=concept, unit=unit)
            annual = [row for row in parsed if eligible(row)]
            comparison = comparable_metric_evidence(annual, ticker=issuer, expected_cik=ISSUER_CIKS[issuer],
                concepts=(concept,), metric_name=basis + ' EPS', unit=unit)
            result = {'concept': 'us-gaap:' + concept, 'share_basis': basis, 'currency': currency,
                'unit': unit, 'parsed_records': len(parsed), 'annual_asof_records': len(annual),
                'comparison_selected': comparison is not None,
                'candidate_contract_qualified': False, 'gap': 'annual_comparison_unavailable',
                'selected_comparison': None}
            if comparison:
                current, prior = comparison.verified_claims
                accession = current['document_ref']['reference_id'].split(':')[2]
                anchors = [row for row in assets if row.end == current['period_end']
                    and row.accession == accession and row.filed == current['document_ref']['published_at']]
                gap = ('latest_annual_reporting_period' if latest_assets_end != current['period_end'] else
                    'annual_reporting_form' if anchors and {row.form for row in anchors} != {current['source']} else
                    'annual_reporting_currency' if {row.unit for row in anchors} != {currency} else None)
                result.update(candidate_contract_qualified=gap is None, gap=gap,
                    selected_comparison={'current_value': str(current['raw_value']),
                        'prior_value': str(prior['raw_value']), 'unit': unit, 'currency': currency,
                        'period_start': current['period_start'], 'period_end': current['period_end'],
                        'prior_period_start': prior['period_start'], 'prior_period_end': prior['period_end'],
                        'form': current['source'], 'filed_at': current['document_ref']['published_at'],
                        'accession': accession, 'filing_index_url': current['document_ref']['url']})
            diagnostics.append(result)
    return {'purpose': 'offline_eps_source_candidate_diagnostics', 'issuer': issuer,
        'expected_cik': ISSUER_CIKS[issuer], 'claimed_source_url': SOURCES_BY_ISSUER[issuer],
        'analysis_as_of': analysis_as_of, 'body_bytes': len(body),
        'body_sha256': hashlib.sha256(body).hexdigest(), 'latest_annual_assets_end': latest_assets_end,
        'identity_basis': 'frozen_registry_cik_not_current_directory',
        'admitted_evidence': False, 'source_origin_independently_verified': False,
        'launch_ready': False, 'model_calls': 0, 'candidates': diagnostics,
        'limitations': ['Candidates are not admitted application evidence or completed answers.',
            'The current ticker mapping, instrument/class/split basis and market price are unverified.',
            'Only explicit US-GAAP USD/EUR basic/diluted annual concepts are evaluated; no IFRS or FX substitution.',
            'Values use the existing producer numeric representation; this is not independent factual adjudication.']}
