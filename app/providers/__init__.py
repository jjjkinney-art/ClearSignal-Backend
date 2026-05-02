"""
Provider package for external data integrations.

This package contains lightweight client modules for external data sources
that are used to enrich the AI analyst's grounding context with
real‑world evidence.  Each client handles HTTP requests, error
handling, normalization of responses, and graceful fallbacks.  By
centralizing API interactions here, the rest of the backend remains
decoupled from specific data provider implementations.
"""

from .sec_client import get_recent_filings, get_company_facts  # noqa: F401
from .fmp_client import (
    get_company_profile,
    get_market_snapshot,
    get_financial_context,
    get_recent_news,
)  # noqa: F401
from .retrieval_provider import get_public_context, get_document_context  # noqa: F401

__all__ = [
    "get_recent_filings",
    "get_company_facts",
    "get_company_profile",
    "get_market_snapshot",
    "get_financial_context",
    "get_recent_news",
    "get_public_context",
    "get_document_context",
]