"""
Retrieval provider for public and document‑backed context.

This module defines thin abstractions for fetching current public
information and document‑backed research.  The functions here are
intended as hooks that can be plugged into search APIs, knowledge
bases, or other retrieval systems.  For now they delegate to the
Financial Modeling Prep press releases endpoint for public news and
return placeholders for document context.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .fmp_client import get_recent_news
from ..config import settings

logger = logging.getLogger(__name__)


def get_public_context(symbol: str, limit: int = 3) -> Optional[List[str]]:
    """Fetch recent public news or press releases for a company.

    Uses the FMP client to retrieve the latest press releases.  Returns a
    list of formatted strings combining the title and date.  Returns
    ``None`` if no news is available or retrieval fails.
    """
    api_key = getattr(settings, "fmp_api_key", "")
    news = get_recent_news(symbol, api_key=api_key, limit=limit)
    if not news:
        return None
    return [f"{item['title']} ({item['date']})" for item in news]


def get_document_context(query: str, limit: int = 3) -> Optional[List[str]]:
    """Placeholder for document‑backed retrieval.

    This function is a stub that returns ``None``.  It is defined to
    preserve the interface for future integration with document stores
    or search services.  When implemented, it should return a list of
    context strings relevant to the query.
    """
    # Future implementation could query a vector store or search API.
    logger.debug(f"Document context retrieval not implemented for query: {query}")
    return None
