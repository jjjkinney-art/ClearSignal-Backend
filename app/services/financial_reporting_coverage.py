"""Disclose a verified comparison's lag behind retrieved filing metadata."""
from datetime import date
import re

from .financial_thesis_foundation import CORE_METRICS, SUPPLEMENTARY_METRICS, _rebuild, financial_metric_label
from .thesis_disclosures import _business_issuer_url
from ..providers.sec_fact_policy import PERIODIC_FORMS


def _reference(item, index, references):
    if references is None:
        return f"E{index}"
    return next((ref['id'] for ref in references
        if re.fullmatch(r'E[1-9]\d*', str(ref.get('id', '')))
        and ref.get('title') == item.title.strip()[:300]
        and ref.get('source') == item.source.strip()[:120]
        and ref.get('url') == item.url
        and ref.get('published_at') == item.timestamp), None)


def reporting_coverage(ticker, material, selected, references=None):
    """Filing existence proves a coverage gap, never the missing financial values.

    Reuse the already retrieved inventory; no extra live fetch or historical
    backfill is performed. Only supported domestic and 20-F period families are compared.
    """
    if not any(getattr(item, 'verified_claims', []) for item in selected):
        return None, '', []
    from .providers.sec_provider import _load_ticker_cik_map
    try:
        cik = _load_ticker_cik_map().get(ticker)
    except Exception:
        return None, '', []
    if not isinstance(cik, str) or not cik.isdigit():
        return None, '', []
    inventory = []
    for index, item in enumerate(material, 1):
        if (item.source != 'SEC EDGAR' or item.claim_type != 'filing_metadata'
                or item.source_type != 'regulatory_filing' or item.source_tier != 'primary'
                or item.extraction_method != 'publisher_feed'
                or item.document_type not in PERIODIC_FORMS
                or item.freshness_status in {'unavailable', 'conflicting', 'superseded', 'stale'}
                or not _business_issuer_url(item.url, cik)):
            continue
        try:
            period = date.fromisoformat(item.reporting_period_end)
            filed = date.fromisoformat(item.timestamp)
        except (TypeError, ValueError):
            continue
        if not period <= filed <= date.today() or item.filed_at != item.timestamp:
            continue
        if not item.title.endswith(f'filed {item.timestamp} (period: {item.reporting_period_end})'):
            continue
        ref = _reference(item, index, references)
        if ref:
            inventory.append((period, filed, ref))
    if not inventory:
        return None, '', []
    latest, _, filing_ref = max(inventory)
    behind = []
    for name, concepts in {**CORE_METRICS, **SUPPLEMENTARY_METRICS}.items():
        for index, item in enumerate(material, 1):
            if not any(item is candidate for candidate in selected):
                continue
            rebuilt = _rebuild(item, ticker=ticker, cik=cik, name=name, concepts=concepts)
            if rebuilt is None or date.fromisoformat(rebuilt.reporting_period_end) >= latest:
                continue
            ref = _reference(item, index, references)
            if ref:
                label = financial_metric_label(name, rebuilt.verified_claims[0]['metric'].split(':')[-1])
                behind.append({'metric': label, 'comparison_period_end': rebuilt.reporting_period_end,
                               'reference_id': ref})
    if not behind:
        return None, '', []
    details = '; '.join(f"{row['metric']} ends {row['comparison_period_end']} [{row['reference_id']}]"
                        for row in behind)
    notice = (f'The retrieved filing inventory includes a report covering {latest.isoformat()} '
              f'[{filing_ref}], but these financial comparisons cover older periods: {details}. '
              'Figures and changes for the newer reporting period were not verified here. '
              'Filing discovery alone does not establish those figures.')
    return ({'latest_discovered_reporting_period': latest.isoformat(),
             'filing_reference_id': filing_ref, 'metrics_behind': behind}, notice,
            [f"latest-period {row['metric']}" for row in behind])
