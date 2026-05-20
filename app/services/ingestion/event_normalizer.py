"""
EventNormalizer — post-processing layer applied to all NormalizedEvents
after adapter-level normalization.

Responsibilities:
1. Assign EvidenceProvenance based on event category + source
2. Enhance tag extraction with Phase M tag vocabulary
3. Validate and repair timestamps
4. Set is_market_moving if not already set by adapter
5. Score event magnitude if missing

This runs synchronously immediately after adapter.normalize() and before
the event is handed to the deduplicator and pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ...schemas import EvidenceProvenance
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

# ── Market-moving keyword signals ─────────────────────────────────────────────
_MARKET_MOVING_KEYWORDS = frozenset([
    "fed", "fomc", "rate decision", "rate hike", "rate cut",
    "cpi", "ppi", "inflation", "nonfarm payroll", "gdp", "unemployment",
    "earnings beat", "earnings miss", "guidance raised", "guidance cut", "guidance lowered",
    "merger", "acquisition", "takeover", "sec investigation", "doj",
    "bankruptcy", "going private", "dividend cut", "dividend raised",
    "buyback", "stock split", "restatement", "accounting",
    "ceo", "cfo", "resignation", "replaced", "fired",
    "10-k", "10-q", "sec filing", "proxy", "annual report",
    "surprise", "above expectations", "below expectations",
])

# ── Phase M extended tag vocabulary ──────────────────────────────────────────
_EXTENDED_TAG_MAP: dict[str, list[str]] = {
    # Earnings
    "beat":              ["beat", "exceeded", "topped", "surpassed", "above estimates", "above consensus"],
    "miss":              ["missed", "fell short", "below estimates", "below consensus", "disappointed"],
    "in_line":           ["in line", "met estimates", "as expected", "consensus"],
    # Guidance
    "raised":            ["raised guidance", "increased outlook", "raised forecast", "raised full-year"],
    "lowered":           ["lowered guidance", "cut outlook", "reduced forecast", "cut full-year", "lowered full-year"],
    "maintained":        ["maintained guidance", "reiterated outlook", "unchanged guidance"],
    # Macro
    "hot_cpi":           ["above expectations", "inflation hotter", "core cpi"],
    "cool_cpi":          ["below expectations", "inflation cooled", "disinflation"],
    "rate_hike":         ["rate hike", "raised rates", "increased rates", "25bp", "50bp", "75bp"],
    "rate_cut":          ["rate cut", "reduced rates", "cut rates", "easing"],
    "fed_hold":          ["held rates", "unchanged rates", "pause", "on hold"],
    "jobs_strong":       ["nonfarm payrolls beat", "jobs added", "unemployment fell", "labor market strength"],
    "jobs_weak":         ["payrolls missed", "unemployment rose", "layoffs", "job cuts"],
    # Corporate actions
    "merger":            ["acquisition", "merger", "takeover", "deal", "acquired"],
    "buyback":           ["buyback", "share repurchase", "repurchase program"],
    "dividend":          ["dividend", "quarterly dividend", "special dividend"],
    "leadership_change": ["ceo", "cfo", "coo", "resignation", "departed", "appointed", "replaced", "fired"],
    # Regulatory
    "regulatory":        ["sec", "ftc", "doj", "investigation", "fine", "penalty", "subpoena", "lawsuit"],
    "sec_filing":        ["10-k", "10-q", "8-k", "annual report", "sec filing", "proxy statement"],
    # Sentiment
    "upgrade":           ["upgraded", "upgrade", "outperform", "buy rating", "overweight"],
    "downgrade":         ["downgraded", "downgrade", "underperform", "sell rating", "underweight"],
    "pt_raise":          ["raised price target", "increased price target", "higher pt"],
    "pt_cut":            ["cut price target", "lowered price target", "reduced pt"],
}

# ── Provenance derivation rules ───────────────────────────────────────────────
# (source_origin, evidence_type) per (category, source_keyword)
_PROVENANCE_RULES: list[tuple[str, str, str, str]] = [
    # (source_keyword_match, category_match, source_origin, evidence_type)
    ("sec", "",        "sec_filing",        "filing"),
    ("10-k", "",       "sec_filing",        "filing"),
    ("10-q", "",       "sec_filing",        "filing"),
    ("8-k",  "",       "sec_filing",        "filing"),
    ("edgar","",       "sec_filing",        "filing"),
    ("earnings", "",   "earnings_transcript","transcript"),
    ("transcript","",  "earnings_transcript","transcript"),
    ("cpi",  "",       "macro_release",     "macro"),
    ("ppi",  "",       "macro_release",     "macro"),
    ("fomc", "",       "fed_statement",     "macro"),
    ("fed",  "",       "fed_statement",     "macro"),
    ("treasury","",    "treasury_move",     "market_move"),
    ("yield","",       "treasury_move",     "market_move"),
    ("nonfarm","",     "macro_release",     "macro"),
    ("gdp",  "",       "macro_release",     "macro"),
    ("analyst","",     "analyst_revision",  "estimate"),
    ("bloomberg","",   "news_wire",         "market_move"),
    ("reuters","",     "news_wire",         "market_move"),
    ("",     EventCategory.MACRO.value,    "macro_release",  "macro"),
    ("",     EventCategory.EARNINGS.value, "earnings_transcript","transcript"),
    ("",     EventCategory.REGULATORY.value, "sec_filing",   "regulatory"),
]


def _derive_source_origin(event: NormalizedEvent) -> tuple[str, str]:
    """Return (source_origin, evidence_type) for the event."""
    source_lower = (event.source or "").lower()
    headline_lower = (event.headline or "").lower()
    category_val = event.category.value if event.category else ""
    combined = f"{source_lower} {headline_lower}"

    for kw, cat, origin, ev_type in _PROVENANCE_RULES:
        kw_match = (not kw) or (kw in combined)
        cat_match = (not cat) or (cat == category_val)
        if kw_match and cat_match:
            return origin, ev_type

    # Fallback: infer from category
    fallback_map = {
        EventCategory.EARNINGS.value:          ("earnings_transcript", "transcript"),
        EventCategory.GUIDANCE.value:          ("earnings_transcript", "guidance"),
        EventCategory.MACRO.value:             ("macro_release",       "macro"),
        EventCategory.NEWS.value:              ("news_wire",           "market_move"),
        EventCategory.ESTIMATE_REVISION.value: ("analyst_revision",    "estimate"),
        EventCategory.MARKET_PRICING.value:    ("market_pricing",      "market_move"),
        EventCategory.REGULATORY.value:        ("sec_filing",          "regulatory"),
        EventCategory.ANALYST_CALL.value:      ("analyst_revision",    "estimate"),
    }
    return fallback_map.get(category_val, ("news_wire", "market_move"))


def _build_citation_label(event: NormalizedEvent, source_origin: str) -> str:
    """Build a human-readable citation label for display in the UI."""
    try:
        date_str = (event.event_timestamp or "")[:10]  # YYYY-MM-DD
        ticker = event.ticker or ""

        label_map = {
            "earnings_transcript": f"{'Q? ' if not ticker else ''}{ticker + ' ' if ticker else ''}earnings call{', ' + date_str if date_str else ''}",
            "sec_filing":          f"{ticker + ' ' if ticker else ''}SEC filing{', ' + date_str if date_str else ''}",
            "macro_release":       f"{_macro_label(event.headline)}{', ' + date_str if date_str else ''}",
            "fed_statement":       f"FOMC statement{', ' + date_str if date_str else ''}",
            "treasury_move":       f"Treasury yield move{', ' + date_str if date_str else ''}",
            "analyst_revision":    f"Analyst revision{' — ' + ticker if ticker else ''}{', ' + date_str if date_str else ''}",
            "news_wire":           f"News report{', ' + date_str if date_str else ''}",
            "market_pricing":      f"Market pricing{', ' + date_str if date_str else ''}",
        }
        return label_map.get(source_origin, f"Source, {date_str}" if date_str else "Source")
    except Exception:
        return "Source"


def _macro_label(headline: str) -> str:
    hl = (headline or "").lower()
    if "cpi" in hl:
        return "CPI release"
    if "ppi" in hl:
        return "PPI release"
    if "fomc" in hl or "fed" in hl:
        return "Fed statement"
    if "nonfarm" in hl or "payroll" in hl:
        return "Jobs report"
    if "gdp" in hl:
        return "GDP release"
    if "treasury" in hl or "yield" in hl:
        return "Treasury move"
    return "Macro release"


def _source_confidence(reliability: Optional[SourceReliability]) -> float:
    """Map source reliability to confidence score."""
    if reliability == SourceReliability.HIGH:
        return 1.0
    if reliability == SourceReliability.MEDIUM:
        return 0.75
    return 0.55


def _extract_extended_tags(headline: str, body: str) -> list[str]:
    """Extract Phase M extended tag vocabulary from event text."""
    combined = f"{headline} {body}".lower()
    tags: list[str] = []
    for tag, keywords in _EXTENDED_TAG_MAP.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags


def _is_market_moving(event: NormalizedEvent) -> bool:
    """Heuristic market-moving detection if not already set by adapter."""
    if event.is_market_moving:
        return True
    combined = f"{event.headline} {event.body}".lower()
    return any(kw in combined for kw in _MARKET_MOVING_KEYWORDS)


def _ensure_timestamp(ts: str) -> str:
    """Ensure we have a valid ISO-8601 timestamp; fall back to UTC now."""
    if ts and len(ts) >= 10:
        return ts
    return datetime.now(timezone.utc).isoformat()


class EventNormalizer:
    """
    Post-adapter normalization layer.

    Takes a NormalizedEvent straight from an adapter and enriches it with:
    - EvidenceProvenance
    - Extended tag vocabulary
    - Market-moving flag validation
    - Timestamp repair
    """

    def normalize(self, event: NormalizedEvent) -> NormalizedEvent:
        """Enrich and validate a NormalizedEvent. Never raises. Returns event."""
        try:
            # Repair timestamps
            event.event_timestamp = _ensure_timestamp(event.event_timestamp)
            event.ingestion_timestamp = _ensure_timestamp(event.ingestion_timestamp)

            # Market-moving detection
            if not event.is_market_moving:
                event.is_market_moving = _is_market_moving(event)

            # Extended tags (add without duplicating)
            extended = _extract_extended_tags(event.headline, event.body)
            existing_tags = set(event.tags or [])
            for tag in extended:
                if tag not in existing_tags:
                    event.tags.append(tag)
                    existing_tags.add(tag)

            # Provenance
            source_origin, ev_type = _derive_source_origin(event)
            citation = _build_citation_label(event, source_origin)
            event.provenance = EvidenceProvenance(
                source_origin=source_origin,
                source_timestamp=event.event_timestamp,
                source_confidence=_source_confidence(event.source_reliability),
                evidence_type=ev_type,
                citation_label=citation,
            )

            return event
        except Exception as exc:
            logger.warning("EventNormalizer.normalize failed: %s", exc)
            return event


# Module-level singleton
_default_normalizer: Optional[EventNormalizer] = None


def get_default_normalizer() -> EventNormalizer:
    global _default_normalizer
    if _default_normalizer is None:
        _default_normalizer = EventNormalizer()
    return _default_normalizer
