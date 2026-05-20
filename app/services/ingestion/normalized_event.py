"""Normalized event schema for all ingestion adapters."""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
import uuid

class EventCategory(str, Enum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    MACRO = "macro"
    NEWS = "news"
    ESTIMATE_REVISION = "estimate_revision"
    MARKET_PRICING = "market_pricing"
    REGULATORY = "regulatory"
    ANALYST_CALL = "analyst_call"

class SourceReliability(str, Enum):
    HIGH = "high"       # SEC filings, official earnings releases
    MEDIUM = "medium"   # Established news wires (Bloomberg, Reuters)
    LOW = "low"         # Unverified news, social signals

class NormalizedEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: Optional[str] = Field(default=None)     # None for macro events
    category: EventCategory
    headline: str
    body: str = Field(default="")
    source: str                                      # "earnings_call" | "sec_10k" | "bloomberg_news" | ...
    source_reliability: SourceReliability = Field(default=SourceReliability.MEDIUM)
    event_timestamp: str                             # ISO-8601 when event occurred
    ingestion_timestamp: str                         # ISO-8601 when ingested
    raw_payload: Dict[str, Any] = Field(default_factory=dict)  # original data
    # Enrichment fields (set by adapters)
    is_market_moving: bool = Field(default=False)
    sentiment: Optional[str] = Field(default=None)  # positive | negative | neutral
    magnitude: Optional[float] = Field(default=None) # 0.0-1.0 estimated impact magnitude
    tags: list[str] = Field(default_factory=list)    # ["beat", "guidance_raised", "miss", etc.]
    # Phase M — evidence provenance (set by EventNormalizer post-processing)
    provenance: Optional[Any] = Field(default=None)  # EvidenceProvenance; typed as Any to avoid circular import
