"""
SQLAlchemy ORM models — 9 tables.

Phase 9A: initial schema
Phase 9B: user_id added to thesis_versions, memory_entries, personalized_insights;
          debounce_visible added to thesis_deltas for material feed deduplication.

Tables
------
1.  thesis_versions       — Snapshot of InvestmentThesis per analysis call
2.  thesis_deltas         — Computed diff between consecutive thesis versions
3.  ticker_memory         — Per-ticker aggregate state (one row per ticker)
4.  memory_entries        — Individual memory items / analysis events
5.  concern_tags          — Canonical concern-tag mention counts per ticker
6.  theme_clusters        — Cross-ticker theme groupings
7.  cross_exposures       — Pairwise ticker relationship strengths
8.  personalized_insights — Derived insights from pattern analysis
9.  briefing_sessions     — Daily-briefing session records (Phase 9B infrastructure)

All primary keys are UUID strings (no dependency on DB-side uuid generation
so the same schema works for both PostgreSQL and SQLite).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


def _now() -> datetime:
    """UTC-aware now, compatible with both Python 3.9 and 3.11+."""
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# JSON column — use native JSON on PostgreSQL, Text on SQLite
# ---------------------------------------------------------------------------
try:
    from sqlalchemy.dialects.postgresql import JSONB as _JSON_TYPE
except Exception:  # pragma: no cover
    from sqlalchemy import JSON as _JSON_TYPE  # type: ignore[assignment]


def _json_col(**kwargs):
    """Return a JSON/JSONB column compatible with both PostgreSQL and SQLite."""
    try:
        from sqlalchemy.dialects.postgresql import JSONB
        return Column(JSONB, **kwargs)
    except Exception:  # pragma: no cover
        from sqlalchemy import JSON
        return Column(JSON, **kwargs)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# 1. thesis_versions
# ---------------------------------------------------------------------------

class ThesisVersion(Base):
    """Snapshot of the InvestmentThesis produced for one /ask call."""

    __tablename__ = "thesis_versions"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)
    company_name = Column(String(200), nullable=False)
    session_id = Column(String(200), nullable=False, default="", index=True)
    question = Column(Text, nullable=False, default="")

    # Core thesis fields (mirrors InvestmentThesis schema)
    directional_stance = Column(String(50), nullable=False, default="")
    confidence_score = Column(Float, nullable=False, default=0.0)
    bull_thesis = Column(Text, nullable=False, default="")
    bear_thesis = Column(Text, nullable=False, default="")
    verdict_rationale = Column(Text, nullable=False, default="")
    direct_answer = Column(Text, nullable=False, default="")
    why_not = Column(Text, nullable=False, default="")
    conclusion = Column(Text, nullable=False, default="")

    # Structured fields stored as JSON
    key_drivers = Column(Text, nullable=False, default="[]")     # JSON list
    key_risks = Column(Text, nullable=False, default="[]")       # JSON list
    macro_sensitivity = Column(Text, nullable=False, default="{}") # JSON object
    threshold_zones = Column(Text, nullable=False, default="{}") # JSON object

    # Phase 9B: identity columns (NULL = anonymous / not yet wired)
    user_id = Column(String(64), nullable=True, default=None)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 2. thesis_deltas
# ---------------------------------------------------------------------------

class ThesisDelta(Base):
    """Computed diff between two consecutive ThesisVersion rows for the same ticker."""

    __tablename__ = "thesis_deltas"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)

    from_version_id = Column(String(36), nullable=False)   # FK thesis_versions.id
    to_version_id = Column(String(36), nullable=False)     # FK thesis_versions.id

    # Scalar diffs
    stance_changed = Column(Boolean, nullable=False, default=False)
    conviction_delta = Column(Float, nullable=False, default=0.0)  # signed

    # Text similarity (Jaccard on word sets)
    bull_thesis_similarity = Column(Float, nullable=False, default=1.0)
    bear_thesis_similarity = Column(Float, nullable=False, default=1.0)

    # Magnitude classification: "minor" | "moderate" | "material"
    magnitude = Column(String(20), nullable=False, default="minor")

    # JSON list of field names that changed
    changed_fields = Column(Text, nullable=False, default="[]")

    # Phase 9B: debounce flag — False for the weaker of two material deltas
    # on the same (ticker, UTC calendar day).  Excluded from the feed.
    debounce_visible = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 3. ticker_memory
# ---------------------------------------------------------------------------

class TickerMemory(Base):
    """Per-ticker aggregate state — one row per ticker, upserted on each analysis."""

    __tablename__ = "ticker_memory"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, unique=True, index=True)
    company_name = Column(String(200), nullable=False, default="")

    # Running counters
    total_queries = Column(Integer, nullable=False, default=0)
    version_count = Column(Integer, nullable=False, default=0)

    # Latest state snapshot
    last_query_at = Column(DateTime(timezone=True), nullable=True)
    last_stance = Column(String(50), nullable=False, default="")
    last_confidence = Column(Float, nullable=False, default=0.0)
    dominant_concern = Column(String(100), nullable=False, default="")

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# 4. memory_entries
# ---------------------------------------------------------------------------

class MemoryEntry(Base):
    """Individual memory items — one row per notable event per ticker."""

    __tablename__ = "memory_entries"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)
    session_id = Column(String(200), nullable=False, default="")

    # entry_type: "analysis" | "concern_flag" | "threshold_alert" | "stance_shift"
    entry_type = Column(String(50), nullable=False, default="analysis")
    content = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")  # JSON object

    # Phase 9B: identity
    user_id = Column(String(64), nullable=True, default=None)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 5. concern_tags
# ---------------------------------------------------------------------------

class ConcernTag(Base):
    """Canonical concern-tag mention counts per ticker — upserted on each analysis."""

    __tablename__ = "concern_tags"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)
    tag_name = Column(String(100), nullable=False)   # e.g. "cre_credit_risk"
    mention_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("ticker", "tag_name", name="uq_concern_ticker_tag"),
    )


# ---------------------------------------------------------------------------
# 6. theme_clusters
# ---------------------------------------------------------------------------

class ThemeCluster(Base):
    """Cross-ticker theme groupings derived from shared concern patterns."""

    __tablename__ = "theme_clusters"

    id = Column(String(36), primary_key=True, default=_uuid)
    cluster_label = Column(String(200), nullable=False, index=True)

    # JSON lists / objects
    tickers = Column(Text, nullable=False, default="[]")          # JSON list of tickers
    concern_overlap = Column(Text, nullable=False, default="{}")  # JSON map concern→count

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# 7. cross_exposures
# ---------------------------------------------------------------------------

class CrossExposure(Base):
    """Pairwise ticker relationship strengths based on shared risk factors."""

    __tablename__ = "cross_exposures"

    id = Column(String(36), primary_key=True, default=_uuid)
    ticker_a = Column(String(20), nullable=False, index=True)
    ticker_b = Column(String(20), nullable=False, index=True)

    shared_concerns = Column(Text, nullable=False, default="[]")  # JSON list
    # exposure_type: "sector" | "macro" | "supply_chain" | "thematic"
    exposure_type = Column(String(50), nullable=False, default="thematic")
    strength = Column(Float, nullable=False, default=0.0)  # 0–1

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("ticker_a", "ticker_b", name="uq_cross_exposure_pair"),
    )


# ---------------------------------------------------------------------------
# 8. personalized_insights
# ---------------------------------------------------------------------------

class PersonalizedInsight(Base):
    """Derived insights surfaced from pattern analysis for a session."""

    __tablename__ = "personalized_insights"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(200), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)

    # insight_type: "stance_shift" | "conviction_trend" | "recurring_concern" | "watchlist_alert"
    insight_type = Column(String(50), nullable=False, default="")
    insight_text = Column(Text, nullable=False, default="")
    supporting_data = Column(Text, nullable=False, default="{}")  # JSON

    # Phase 9B: identity
    user_id = Column(String(64), nullable=True, default=None)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 9. briefing_sessions
# ---------------------------------------------------------------------------

class BriefingSession(Base):
    """Daily-briefing session records — infrastructure only (Phase 9B surfaces)."""

    __tablename__ = "briefing_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_date = Column(Date, nullable=False, index=True)
    session_id = Column(String(200), nullable=False, default="")

    tickers_covered = Column(Text, nullable=False, default="[]")  # JSON list
    # status: "pending" | "generated" | "delivered"
    status = Column(String(20), nullable=False, default="pending")
    metadata_json = Column(Text, nullable=False, default="{}")  # JSON

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
