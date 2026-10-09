"""One latest domestic filing as a bounded fallback for core financial facts."""
from datetime import date
import logging

from ..config import settings
from ..integrity.sec_metric_evidence import comparable_metric_evidence
from ..providers.sec_client import SecFactRecord
from ..providers.sec_inline_facts import validated_observation
from .financial_thesis_foundation import CORE_METRICS, _rebuild
from .providers import sec_provider
from .public_document_ingestion import fetch_public_document
from .thesis_disclosures import _business_issuer_url, requests_thesis_disclosures

logger = logging.getLogger(__name__)


def requests_filing_metrics(ticker, question):
    if requests_thesis_disclosures(ticker, question):
        return True
    from .verified_sec_metric_service import _requested_metrics
    from .live_issuer_kpi_service import requested_issuer_kpi_aliases
    import re
    if (requested_issuer_kpi_aliases(question)
            or re.search(r'\b(?:services|segments?|app store|icloud|apple music|digital content)\b', question, re.I)):
        return False
    core = {c for aliases in CORE_METRICS.values() for c in aliases}
    return any(unit == 'USD' and kind == 'duration' and set(concepts) & core
               for concepts, _, _, unit, kind in _requested_metrics(question, include_defaults=False))


def evidence_from_filing(document, filing, *, ticker, cik):
    """Compare only consolidated facts from the same admitted filing body."""
    if (document.final_url != filing.url or document.requested_url != filing.url
            or not _business_issuer_url(document.final_url, cik)
            or document.publisher != 'SEC EDGAR' or document.source_type != 'regulatory_filing'
            or document.source_tier != 'primary' or document.extraction_method != 'html'
            or document.document_type != filing.document_type
            or document.published_at != filing.timestamp
            or filing.document_type not in {'10-K', '10-Q', '10-K/A', '10-Q/A'}):
        return []
    try:
        latest = date.fromisoformat(filing.reporting_period_end)
        if not latest <= date.fromisoformat(filing.timestamp) <= date.today():
            return []
    except (TypeError, ValueError):
        return []
    compact = filing.url.split('/')[-2]
    accession = f'{compact[:10]}-{compact[10:12]}-{compact[12:]}'
    concepts = tuple(concept for group in CORE_METRICS.values() for concept in group)
    records = []
    for observation in document.inline_xbrl_facts:
        amount = validated_observation(observation, cik=cik, concepts=concepts)
        if amount is None or observation['end'] > filing.reporting_period_end:
            continue
        proof = {**observation, 'content_hash': document.content_hash,
            'document_url': document.final_url, 'filed': filing.timestamp,
            'form': filing.document_type, 'accession': accession}
        records.append(SecFactRecord(cik=cik, taxonomy='us-gaap', concept=observation['concept'],
            label=observation['concept'], unit='USD', value=amount,
            start=observation['start'], end=observation['end'], filed=filing.timestamp,
            form=filing.document_type, accession=accession, filing_url=document.final_url,
            inline_binding=proof))
    evidence = []
    for name, aliases in CORE_METRICS.items():
        for concept in aliases:
            item = comparable_metric_evidence(records, ticker=ticker, expected_cik=cik,
                                              concepts=(concept,), metric_name=name)
            if item and len(item.verified_claims) == 2 and item.reporting_period_end == latest.isoformat():
                evidence.append(item)
                break
    return evidence


def fetch_latest_filing_metrics(ticker, *, question, as_of=None):
    """Runs alongside Company Facts inside the router's existing 10s ceiling.

    At most one primary document, no ticker overrides, no historical backfill,
    no arithmetic substitute for absent standard operating-income facts.
    """
    if as_of or not requests_filing_metrics(ticker, question):
        return []
    try:
        cik = sec_provider._load_ticker_cik_map().get(ticker)
        if not isinstance(cik, str) or not cik.isdigit():
            return []
        filings = sec_provider.fetch_recent_filings(ticker,
            forms=['10-K', '10-Q', '10-K/A', '10-Q/A'], limit=2) or []
        valid = []
        for item in filings:
            if (item.source != 'SEC EDGAR' or item.claim_type != 'filing_metadata'
                    or item.source_type != 'regulatory_filing' or item.source_tier != 'primary'
                    or item.extraction_method != 'publisher_feed'
                    or not _business_issuer_url(item.url, cik)):
                continue
            try:
                if date.fromisoformat(item.reporting_period_end) <= date.fromisoformat(item.timestamp) <= date.today():
                    valid.append(item)
            except (TypeError, ValueError):
                continue
        if not valid:
            return []
        filing = max(valid, key=lambda item: (item.reporting_period_end, item.timestamp))
        document = fetch_public_document(filing.url, user_agent=settings.sec_user_agent,
            publisher='SEC EDGAR', published_at=filing.timestamp, document_type=filing.document_type,
            source_type='regulatory_filing', source_tier='primary', sec_periodic_limits=True,
            extract_tables=False, inline_fact_cik=cik,
            inline_fact_concepts=tuple(c for group in CORE_METRICS.values() for c in group))
        items = evidence_from_filing(document, filing, ticker=ticker, cik=cik)
        (logger.info if items else logger.warning)(
            'Latest filing metrics %s: period=%s observations=%d comparisons=%d',
            ticker, filing.reporting_period_end, len(document.inline_xbrl_facts), len(items))
        if requests_thesis_disclosures(ticker, question):
            return items
        from .verified_sec_metric_service import _requested_metrics
        requested = {f'us-gaap:{concept}' for concepts, _, _, _, _ in
                     _requested_metrics(question, include_defaults=False) for concept in concepts}
        return [item for item in items if item.verified_claims[0]['metric'] in requested]
    except Exception as exc:
        logger.warning('Latest filing metrics unavailable for %s: %s', ticker, type(exc).__name__)
        return []


def merge_latest_filing_metrics(company_facts, filing_facts, *, ticker):
    """Replace older same-concept comparisons; keep same-period conflicts visible.

    Do not let an alternative revenue/net-income concept silently replace an
    existing metric. Missing aliases remain separate semantic observations.
    """
    if not filing_facts:
        return list(company_facts)
    try:
        cik = sec_provider._load_ticker_cik_map().get(ticker)
    except Exception:
        return list(company_facts)
    if not isinstance(cik, str) or not cik.isdigit():
        return list(company_facts)
    output = list(company_facts)
    for candidate in filing_facts:
        for name, concepts in CORE_METRICS.items():
            checked = _rebuild(candidate, ticker=ticker, cik=cik, name=name, concepts=concepts)
            if checked is None:
                continue
            same_metric = [(old, _rebuild(old, ticker=ticker, cik=cik, name=name, concepts=concepts))
                           for old in output]
            same_metric = [(old, rebuilt) for old, rebuilt in same_metric if rebuilt is not None]
            if same_metric and any(old.verified_claims[0]['metric'] != candidate.verified_claims[0]['metric']
                                   for old, _ in same_metric):
                break
            latest_old = max((rebuilt.reporting_period_end for _, rebuilt in same_metric), default='')
            if candidate.reporting_period_end < latest_old:
                break
            if candidate.reporting_period_end > latest_old:
                removed = {id(old) for old, _ in same_metric}
                output = [old for old in output if id(old) not in removed]
            elif same_metric:
                # Equivalent observations need one canonical evidence reference.
                def signature(item):
                    return [(c['metric'], c['period_start'], c['period_end'], c['raw_value'])
                            for c in item.verified_claims]
                if all(signature(old) == signature(candidate) for old, _ in same_metric):
                    break
            output.append(candidate)
            break
    return output
