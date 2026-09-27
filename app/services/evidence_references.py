"""Safe, presentation-ready references for retrieved evidence.

The analysis pipeline may use provider request URLs containing credentials.
Those URLs are never serialized. Only explicit public evidence URLs, or the
legacy ``[Source: https://...]`` marker used by NewsAPI evidence, are accepted.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit


_LEGACY_SOURCE_RE = re.compile(r"\[Source:\s*(https?://[^\]\s]+)\]", re.IGNORECASE)
_SENSITIVE_QUERY_KEYS = {
    "api_key", "apikey", "api-key", "key", "token", "access_token",
    "authorization", "auth", "secret",
}


def _safe_public_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if any(key.lower() in _SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
        return None
    return candidate


def _evidence_url(item: object) -> str | None:
    explicit = _safe_public_url(getattr(item, "url", None))
    if explicit:
        return explicit
    summary = getattr(item, "summary", "")
    if not isinstance(summary, str):
        return None
    match = _LEGACY_SOURCE_RE.search(summary)
    return _safe_public_url(match.group(1)) if match else None


def build_evidence_references(items: Iterable[object]) -> list[dict]:
    """Return bounded, non-secret evidence metadata in retrieval order."""
    references: list[dict] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for item in items:
        title = str(getattr(item, "title", "") or "Untitled evidence").strip()
        source = str(getattr(item, "source", "") or "Unknown source").strip()
        published_at = str(getattr(item, "timestamp", "") or "").strip()
        url = _evidence_url(item)
        identity = (title, source, published_at, url)
        if identity in seen:
            continue
        seen.add(identity)
        references.append({
            "title": title[:300],
            "source": source[:120],
            "published_at": published_at[:40] or None,
            "url": url,
            "inspectable": bool(url),
        })
    return references
