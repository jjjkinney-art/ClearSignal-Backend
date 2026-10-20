"""Explicit reported annual EPS research; no assumptions, price or thresholds."""
from datetime import date, datetime, timezone
import re

from app.integrity.sec_metric_evidence import comparable_metric_evidence
from app.providers.sec_fact_policy import REPORTING_CURRENCIES


def annual_eps_request(question):
    text = question or ''
    if (not re.search(r'\b(?:annual|fiscal[- ]year)\b', text, re.I)
            or not re.search(r'\b(?:eps|earnings per share)\b', text, re.I)
            or re.search(r'\b(?:ifrs|adr|ads|preferred|adjusted|non[- ]?gaap|pro[- ]?forma|ttm|trailing|quarterly|forecast|forward|next|expected|target|risk|risks|thesis|valuation|threshold|thresholds|attractive|unattractive|buy|sell|price|return|returns)\b', text, re.I)):
        return None
    if re.search(r'\b(?:19|20)\d{2}\b', text):
        return None  # A specifically requested historical fiscal year needs its own selector.
    bases = tuple(b for b in ('basic', 'diluted') if re.search(r'\b'+b+r'\b', text, re.I))
    if not bases:
        return None  # No implicit choice of share basis.
    from .verified_sec_metric_service import _requested_metrics
    if any(m[1] != 'diluted EPS' for m in _requested_metrics(text, include_defaults=False)):
        return None  # Existing multipart monetary/operating views retain their route.
    currencies = tuple(c for c in REPORTING_CURRENCIES if re.search(r'\b'+c+r'\b', text, re.I))
    return {'bases': bases, 'currencies': currencies,
            'unsupported_currency': bool(re.search(r'\b(?:GBP|CAD|AUD|NZD|JPY|CHF|CNY|HKD|INR)\b|[£¥]', text, re.I))}


def select_annual_eps(records, *, ticker, cik, basis, currency, boundary):
    """Same-filing annual EPS/Assets contract, with no other-basis fallback."""
    concept = 'EarningsPerShareBasic' if basis == 'basic' else 'EarningsPerShareDiluted'
    eligible = [r for r in records if r.cik.lstrip('0') == cik.lstrip('0')
        and r.form in ('10-K', '10-K/A', '20-F', '20-F/A')
        and date.fromisoformat(r.filed) <= boundary and date.fromisoformat(r.end) <= boundary]
    item = comparable_metric_evidence([r for r in eligible if r.concept == concept and r.unit == currency+'/shares'],
        ticker=ticker, expected_cik=cik, concepts=(concept,), metric_name=basis+' EPS', unit=currency+'/shares')
    if item is None:
        return None
    current = item.verified_claims[0]
    assets = [r for r in eligible if r.concept == 'Assets' and r.start is None and r.unit in REPORTING_CURRENCIES]
    if not assets or max(r.end for r in assets) != current['period_end']:
        return None
    accession = current['document_ref']['reference_id'].split(':')[2]
    anchors = [r for r in assets if r.end == current['period_end'] and r.accession == accession
               and r.filed == current['document_ref']['published_at']]
    if {r.form for r in anchors} != {current['source']} or {r.unit for r in anchors} != {currency}:
        return None
    return item


def fetch_annual_eps(ticker, cik, request, boundary, fetcher, user_agent):
    boundary = boundary or datetime.now(timezone.utc).date()
    if boundary > datetime.now(timezone.utc).date() or len(request['currencies']) > 1 or request['unsupported_currency']:
        return []
    pairs = tuple((('EarningsPerShareBasic' if b == 'basic' else 'EarningsPerShareDiluted'), c+'/shares')
                  for b in request['bases'] for c in REPORTING_CURRENCIES)
    pairs += tuple(('Assets', c) for c in REPORTING_CURRENCIES)
    records = fetcher(cik, concept_units=pairs, user_agent=user_agent)
    anchors = [r for r in records if r.cik.lstrip('0') == cik.lstrip('0') and r.concept == 'Assets'
        and r.start is None and r.unit in REPORTING_CURRENCIES
        and r.form in ('10-K', '10-K/A', '20-F', '20-F/A')
        and date.fromisoformat(r.filed) <= boundary and date.fromisoformat(r.end) <= boundary]
    end = max((r.end for r in anchors), default=None)
    currencies = {r.unit for r in anchors if r.end == end}
    if len(currencies) != 1:
        return []
    currency = next(iter(currencies))
    if request['currencies'] and currency not in request['currencies']:
        return []
    return [item for b in request['bases'] if (item := select_annual_eps(records,
        ticker=ticker, cik=cik, basis=b, currency=currency, boundary=boundary)) is not None]


def build_annual_eps_answer(ticker, question, items, references):
    """Rebuild literal per-share facts and unique citations before rendering."""
    request = annual_eps_request(question)
    if request is None:
        return None
    from .providers.sec_provider import _load_ticker_cik_map
    from .source_anchored_valuation import _annual_eps_context
    from .conditional_valuation_math import ValuationContractError
    try:
        cik = _load_ticker_cik_map().get(ticker)
    except Exception:
        cik = None
    selected, claims, gaps = [], [], []
    for basis in request['bases']:
        candidates = []
        for item in items:
            for currency in REPORTING_CURRENCIES:
                if request['currencies'] and request['currencies'] != (currency,):
                    continue
                if request['unsupported_currency']:
                    continue
                try:
                    context = _annual_eps_context(ticker, cik, [item], references,
                        datetime.now(timezone.utc).date(), share_basis=basis, currency=currency)
                except ValuationContractError:
                    continue
                candidates.append((item, context['reference_id']))
        # Conflicting or duplicate candidates cannot be resolved by order.
        if len(candidates) != 1:
            gaps.append('annual '+basis+' EPS')
            continue
        item, reference_id = candidates[0]
        selected.append(item)
        claims.append({'claim': item.summary, 'reference_id': reference_id, 'claim_kind': 'reported_financial_comparison'})
    answer = '\n\n'.join(f"{i}. {c['claim']} [{c['reference_id']}]" for i,c in enumerate(claims, 1))
    if not claims:
        answer = 'No source-bound annual EPS comparison qualified for the explicitly requested share basis and reporting currency.'
    if gaps:
        answer += '\n\nUnverified requested parts: '+ '; '.join(gaps)+'.'
    answer += ('\n\nThese are dated reported annual EPS comparisons, not current TTM or forward EPS. '
        'Basic and diluted EPS are distinct; no substitution, FX or ADR conversion is performed. '
        'Market price, share/split compatibility, future earnings, valuation boundaries and expected returns remain unverified.')
    return {'answer': answer, 'claims': claims, 'selected_items': selected, 'unanswered_parts': gaps,
            'status': ('partial' if gaps else 'attributed') if claims else 'insufficient_claim_evidence'}
