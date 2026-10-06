"""Question-aware, SEC-backed issuer KPI evidence for the live router."""

from __future__ import annotations

import logging
import re

from ..schemas import RetrievedEvidence
from .issuer_kpi_evidence import extract_source_bound_kpis, kpi_as_evidence
from .official_document_discovery import discover_official_documents
from .providers import sec_provider
from .public_document_ingestion import PublicDocumentError, fetch_public_document
from .services_revenue_evidence import (
    extract_services_revenue_evidence, requests_services_revenue,
)
from .services_risk_evidence import (
    extract_services_risk_evidence,
)
from .issuer_risk_evidence import extract_issuer_risk_evidence, requested_risk_profile

logger = logging.getLogger(__name__)

# Cross-sector issuer-defined metrics. Matching is exact phrase/abbreviation
# based; broad nouns such as "users" or "sales" are intentionally excluded.
_KPI_ALIASES: dict[str, tuple[str, ...]] = {
    "annual recurring revenue": ("annual recurring revenue", "ARR"),
    "remaining performance obligations": (
        "current remaining performance obligation",
        "remaining performance obligations",
        "remaining performance obligation",
        "current RPO", "cRPO",
    ),
    "monthly active users": ("monthly active users", "MAU", "MAUs"),
    "daily active users": ("daily active users", "DAU", "DAUs"),
    "paid memberships": ("paid memberships", "paid members"),
    "paid subscribers": ("paid subscribers", "paying subscribers"),
    "net additions": ("net additions", "net adds"),
    "gross merchandise value": ("gross merchandise value", "GMV"),
    "gross bookings": ("gross bookings",),
    "comparable sales": ("comparable sales", "same-store sales", "same store sales"),
    "occupancy": ("occupancy rate", "occupancy"),
    "RevPAR": ("RevPAR", "revenue per available room"),
    "deliveries": ("total vehicle deliveries", "vehicle deliveries", "deliveries"),
    "production": ("vehicle production", "production volume"),
    "gross margin": ("gross margin",),
    "net retention rate": ("net retention rate", "net revenue retention", "NRR"),
}


def requested_issuer_kpi_aliases(question: str) -> dict[str, tuple[str, ...]]:
    """Return only KPI families explicitly named in the user's question."""
    if not isinstance(question, str) or not question.strip():
        return {}
    selected: dict[str, tuple[str, ...]] = {}
    for metric, aliases in _KPI_ALIASES.items():
        if any(re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                         question, re.IGNORECASE) for alias in aliases):
            selected[metric] = aliases
    return selected


def fetch_live_issuer_kpi_evidence(
    ticker: str,
    *,
    question: str,
    user_agent: str = "",
    max_documents: int = 2,
) -> list[RetrievedEvidence]:
    """Fetch bounded SEC documents and return only source-bound evidence."""
    if not isinstance(ticker, str) or not ticker.strip():
        return []
    aliases = requested_issuer_kpi_aliases(question)
    services_requested = ticker.upper().strip() == "AAPL" and requests_services_revenue(question)
    risk_requested = requested_risk_profile(ticker, question) is not None
    if (not aliases and not services_requested and not risk_requested) or not ticker.strip() or max_documents not in (1, 2, 3):
        return []
    forms = (["10-Q", "10-Q/A", "10-K", "10-K/A"] if services_requested or risk_requested
             else ["8-K", "8-K/A", "6-K", "6-K/A"])
    try:
        filings = sec_provider.fetch_recent_filings(
            ticker.upper().strip(), forms=forms,
            limit=max_documents, years_back=2, prefer_results=not (services_requested or risk_requested),
        ) or []
    except Exception as exc:
        logger.warning("issuer KPI filing discovery failed for %s: %r", ticker, exc)
        return []

    evidence: list[RetrievedEvidence] = []
    resolved_metrics: set[str] = set()
    fetched_documents = 0
    attempted_urls: set[str] = set()
    candidates_filings = list(filings[:max_documents])
    service_found = False
    risk_found = False
    for filing_index, filing in enumerate(candidates_filings):
        if fetched_documents >= max_documents:
            break
        url = getattr(filing, "url", None)
        published_at = getattr(filing, "timestamp", None)
        document_type = getattr(filing, "document_type", None)
        if document_type not in set(forms):
            title = str(getattr(filing, "title", "") or "")
            document_type = next(
                (form for form in sorted(forms, key=len, reverse=True) if form in title), None,
            )
        if not isinstance(url, str) or not published_at or not document_type or url in attempted_urls:
            continue
        attempted_urls.add(url)
        # Failed downloads also consume the bounded attempt budget.
        fetched_documents += 1
        try:
            document = fetch_public_document(
                url, user_agent=user_agent, publisher="SEC EDGAR",
                published_at=str(published_at), document_type=document_type,
                source_type="regulatory_filing", source_tier="primary",
                **({"sec_periodic_limits": True} if risk_requested and ticker.upper().strip() != "AAPL" else {}),
            )
        except PublicDocumentError as exc:
            logger.info(
                "issuer KPI document skipped for %s: %s; failure_kind=%s "
                "http_status=%s error_class=%s user_agent_configured=%s",
                ticker, exc, exc.failure_kind, exc.http_status, exc.error_class,
                bool(user_agent.strip()),
            )
            continue
        if services_requested or risk_requested:
            # Services tables are period-aware. Do not run the generic prose
            # extractor: it could promote a company-wide gross-margin figure.
            if services_requested and not service_found:
                service_evidence = extract_services_revenue_evidence(document, ticker=ticker)
                evidence.extend(service_evidence)
                service_found = bool(service_evidence)
            if risk_requested and not risk_found:
                risk_evidence = (extract_services_risk_evidence(document, ticker=ticker)
                                 if ticker.upper().strip() == "AAPL" else
                                 extract_issuer_risk_evidence(document, ticker=ticker, question=question))
                evidence.extend(risk_evidence)
                risk_found = bool(risk_evidence)
            if (not services_requested or service_found) and (not risk_requested or risk_found):
                break
            # A quarterly report can refer back to annual Risk Factors. Only
            # discover the annual fallback after the newest document had no
            # qualifying risk; keep it within the remaining document budget.
            if (risk_requested and not risk_found and filing_index == 0
                    and max_documents > 1 and document_type not in {"10-K", "10-K/A"}):
                try:
                    annual = sec_provider.fetch_recent_filings(
                        ticker.upper().strip(), forms=["10-K", "10-K/A"], limit=1,
                        years_back=2, prefer_results=False,
                    ) or []
                except Exception as exc:
                    logger.warning("Issuer risk annual discovery unavailable for %s: %r", ticker, exc)
                    annual = []
                if annual:
                    candidates_filings[filing_index + 1:] = annual[:1]
            continue
        remaining = {key: value for key, value in aliases.items() if key not in resolved_metrics}
        for kpi in extract_source_bound_kpis(
            document, ticker=ticker, metric_aliases=remaining,
        ):
            evidence.append(kpi_as_evidence(kpi, document))
            resolved_metrics.add(kpi.metric)
        if len(resolved_metrics) == len(aliases):
            break
        candidates = discover_official_documents(
            document, issuer_hosts=("www.sec.gov",), publisher="SEC EDGAR",
            published_at=str(published_at), limit=max_documents,
        )
        for candidate in candidates:
            if fetched_documents >= max_documents:
                break
            if candidate.url in attempted_urls:
                continue
            attempted_urls.add(candidate.url)
            fetched_documents += 1
            try:
                exhibit = fetch_public_document(
                    candidate.url, user_agent=user_agent,
                    publisher=candidate.publisher,
                    published_at=candidate.published_at,
                    document_type=candidate.document_type,
                    source_type=candidate.source_type,
                    source_tier=candidate.source_tier,
                )
            except PublicDocumentError as exc:
                logger.info(
                    "issuer KPI exhibit skipped for %s: %s; failure_kind=%s "
                    "http_status=%s error_class=%s user_agent_configured=%s",
                    ticker, exc, exc.failure_kind, exc.http_status, exc.error_class,
                    bool(user_agent.strip()),
                )
                continue
            remaining = {
                key: value for key, value in aliases.items() if key not in resolved_metrics
            }
            for kpi in extract_source_bound_kpis(
                exhibit, ticker=ticker, metric_aliases=remaining,
            ):
                evidence.append(kpi_as_evidence(kpi, exhibit))
                resolved_metrics.add(kpi.metric)
            if len(resolved_metrics) == len(aliases):
                break
    return evidence
