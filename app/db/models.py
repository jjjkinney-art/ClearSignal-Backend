"""
SQLAlchemy ORM models — 19 tables.

Phase 9A: initial schema (tables 1–9)
Phase 9B: user_id added to thesis_versions, memory_entries, personalized_insights;
          debounce_visible added to thesis_deltas for material feed deduplication.
Phase 9F: historical_analogs (table 10) — Historical Evidence Engine.
Phase 9G · Phase 0: Company Dossier (tables 11–19) — canonical per-ticker
          company intelligence object. Read before synthesis (injection),
          written after synthesis (extraction). No behavior wired in this slice.

Tables
------
1.  thesis_versions        — Snapshot of InvestmentThesis per analysis call
2.  thesis_deltas          — Computed diff between consecutive thesis versions
3.  ticker_memory          — Per-ticker aggregate state (one row per ticker)
4.  memory_entries         — Individual memory items / analysis events
5.  concern_tags           — Canonical concern-tag mention counts per ticker
6.  theme_clusters         — Cross-ticker theme groupings
7.  cross_exposures        — Pairwise ticker relationship strengths
8.  personalized_insights  — Derived insights from pattern analysis
9.  briefing_sessions      — Daily-briefing session records (Phase 9B infrastructure)
10. historical_analogs     — Curated historical analog library (Phase 9F)

Company Dossier (Phase 9G · Phase 0)
11. company_dossier        — Head: single row per ticker; injection entry-point
12. dossier_core_debate    — The one defining investment question (versioned)
13. dossier_moat_dimension — Structured competitive-advantage model (per axis)
14. dossier_catalyst       — Falsifiable bull/bear triggers with lifecycle state
15. dossier_variant        — Where ClearSignal diverges from consensus (versioned)
16. dossier_durability     — Raw signals feeding the Durability Score (Phase 9G-5)
17. dossier_failure_mode   — Active failure-pattern matches (links to analogs)
18. dossier_revision       — Append-only audit log; NEVER updated or deleted
19. dossier_evidence_ref   — Per-claim provenance spine (sourced vs inferred)

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
    """Return a JSON column compatible with both PostgreSQL (JSONB in migrations) and SQLite.

    Uses SQLAlchemy's base JSON type so the ORM layer works with both engines.
    PostgreSQL production databases define the column as JSONB in the SQL migration
    (003_historical_evidence.sql), giving full JSONB semantics there.  The ORM
    only needs a type that can read/write the column — JSON suffices for both.
    """
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


# ---------------------------------------------------------------------------
# 10. historical_analogs  (Phase 9F — Historical Evidence Engine)
# ---------------------------------------------------------------------------

class HistoricalAnalog(Base):
    """Curated historical analog instance for the Evidence Engine.

    Each row represents one (company or sector) × (episode) × (mechanism)
    combination.  Rows are seeded from app/db/data/historical_analogs.json
    and are read-only at runtime — the scoring / retrieval engine in
    app/evidence_engine.py operates on the in-memory list returned by the repo.
    """

    __tablename__ = "historical_analogs"

    id              = Column(String(36), primary_key=True, default=_uuid)

    # Identity
    label           = Column(String(200), nullable=False, unique=True)
    episode         = Column(String(200), nullable=False, default="")
    entity_ticker   = Column(String(20),  nullable=True)
    sector          = Column(String(60),  nullable=False, default="")
    business_model  = Column(String(60),  nullable=False, default="")
    quality_rating  = Column(String(20),  nullable=False, default="moderate")

    # Setup fingerprint (matched against SetupFingerprint)
    mechanism           = Column(String(60),  nullable=False, index=True)
    concern_tags        = _json_col(nullable=False, default=list)  # List[str]
    valuation_regime    = Column(String(40),  nullable=False, default="")
    growth_phase        = Column(String(40),  nullable=False, default="")
    macro_regime        = Column(String(40),  nullable=False, default="")

    # Outcome payload
    event_start          = Column(Date,    nullable=True)
    event_end            = Column(Date,    nullable=True)
    drawdown_pct         = Column(Float,   nullable=True)
    time_to_trough_days  = Column(Integer, nullable=True)
    time_to_recover_days = Column(Integer, nullable=True)
    outcome_summary      = Column(Text,    nullable=False, default="")
    reaction_series      = _json_col(nullable=False, default=list)  # Phase 9G: [{t, px_rel}]

    # Credibility anchors
    why_relevant     = Column(Text,        nullable=False, default="")
    disanalogy       = Column(Text,        nullable=False)  # NOT NULL: trivia guard
    base_rate_note   = Column(Text,        nullable=False, default="")
    data_confidence  = Column(String(20),  nullable=False, default="moderate")
    source_note      = Column(String(400), nullable=False, default="")

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ===========================================================================
# Phase 9G · Phase 0 — Company Dossier (tables 11–19)
#
# The dossier is the canonical per-ticker company-intelligence object.
# It is READ before synthesis (injection) and WRITTEN after synthesis
# (extraction).  No extraction or injection logic lives here — this module
# contains only the ORM definitions (Slice 1).
#
# Conventions carried from existing tables:
#   - UUID string PKs (no DB-side generation)
#   - user_id nullable VARCHAR(64) for multi-tenant forward compat
#   - session_id non-nullable VARCHAR(200) defaulting to ""
#   - Soft foreign keys (no FK constraints) to thesis_versions /
#     historical_analogs so dossier lifecycle is independent
#   - JSON columns use _json_col() for JSONB/SQLite compat
# ===========================================================================


# ---------------------------------------------------------------------------
# 11. company_dossier  (head — single row per ticker)
# ---------------------------------------------------------------------------

class CompanyDossier(Base):
    """Head row for the Company Dossier — one per ticker.

    This is the only table the injection path must read to decide whether a
    dossier exists for a ticker.  It carries a small cache of the most recent
    thesis conclusion (prior_thesis_state) so injection never needs a join
    against thesis_versions on the hot path.

    row_version is incremented on every write for optimistic-concurrency
    control — writers supply the current value and lose if it has moved.
    """

    __tablename__ = "company_dossier"

    id           = Column(String(36), primary_key=True, default=_uuid)

    # Identity
    ticker       = Column(String(20),  nullable=False, unique=True, index=True)
    company_name = Column(String(200), nullable=False, default="")

    # Prior-thesis-state cache (denormalised — soft FK to thesis_versions.id)
    latest_version_id = Column(String(36), nullable=True, default=None)
    stance            = Column(String(50),  nullable=False, default="")
    conviction        = Column(Float,       nullable=False, default=0.0)
    primary_concern   = Column(String(200), nullable=False, default="")
    prior_as_of       = Column(DateTime(timezone=True), nullable=True, default=None)

    # Dossier meta
    schema_version      = Column(Integer, nullable=False, default=1)
    global_confidence   = Column(Float,   nullable=False, default=0.0)
    # staleness_state: fresh | aging | stale
    staleness_state     = Column(String(20), nullable=False, default="fresh")
    last_full_update_at = Column(DateTime(timezone=True), nullable=True, default=None)
    analysis_count      = Column(Integer, nullable=False, default=0)
    # Optimistic-concurrency lock — bump on every write
    row_version         = Column(Integer, nullable=False, default=0)

    # Identity / audit
    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        onupdate=_now)


# ---------------------------------------------------------------------------
# 12. dossier_core_debate  (the one defining question — single row per ticker)
# ---------------------------------------------------------------------------

class DossierCoreDebate(Base):
    """The single central debate that defines the investment thesis.

    `version` increments only on a *material* reframing (semantic shift +
    corroborating thesis delta + high confidence) — see spec §3.4.
    `current_lean` is a non-versioning field that absorbs minor sentiment
    swings without cutting a new version.
    """

    __tablename__ = "dossier_core_debate"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, unique=True, index=True)

    # Debate framing
    question          = Column(Text,        nullable=False, default="")
    bull_pole         = Column(Text,        nullable=False, default="")
    bear_pole         = Column(Text,        nullable=False, default="")
    # current_lean: bull | bear | balanced
    current_lean      = Column(String(20),  nullable=False, default="balanced")
    resolution_signal = Column(Text,        nullable=False, default="")

    # Versioning / confidence
    version    = Column(Integer, nullable=False, default=1)
    confidence = Column(Float,   nullable=False, default=0.0)

    user_id      = Column(String(64),  nullable=True,  default=None)
    session_id   = Column(String(200), nullable=False, default="")
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now,
                           onupdate=_now)


# ---------------------------------------------------------------------------
# 13. dossier_moat_dimension  (one row per ticker × axis — bounded at ~6 axes)
# ---------------------------------------------------------------------------

class DossierMoatDimension(Base):
    """One competitive-advantage axis for a ticker.

    `pending_flip` is the hysteresis state: set to True when a single
    synthesis disagrees with the current strength/trend; the flip only
    commits when a *second* agreeing synthesis arrives (or when extraction
    confidence ≥ τ_high on the first).  This prevents single-synthesis
    oscillation from corrupting the moat model.

    Valid `axis` values (fixed taxonomy, extensible via migration):
        ecosystem_lockin | supply_chain_control | switching_costs |
        network_effects  | regulatory_ip        | management_execution
    """

    __tablename__ = "dossier_moat_dimension"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)
    # axis: see taxonomy in docstring
    axis   = Column(String(60), nullable=False)

    # Dimension state
    # strength: strong | moderate | weak | absent
    strength      = Column(String(20), nullable=False, default="moderate")
    # trend: strengthening | stable | weakening
    trend         = Column(String(20), nullable=False, default="stable")
    rationale     = Column(Text,       nullable=False, default="")
    vulnerability = Column(Text,       nullable=False, default="")

    # Versioning / hysteresis
    version      = Column(Integer, nullable=False, default=1)
    confidence   = Column(Float,   nullable=False, default=0.0)
    pending_flip = Column(Boolean, nullable=False, default=False)

    user_id         = Column(String(64),  nullable=True,  default=None)
    session_id      = Column(String(200), nullable=False, default="")
    last_changed_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("ticker", "axis", name="uq_dossier_moat_ticker_axis"),
    )


# ---------------------------------------------------------------------------
# 14. dossier_catalyst  (per-catalyst lifecycle — multiple per ticker)
# ---------------------------------------------------------------------------

class DossierCatalyst(Base):
    """A falsifiable catalyst with a lifecycle.

    The `id` is stable across analyses so hit/miss history can be tracked.
    Catalysts are NEVER deleted — only lifecycle-transitioned:
        open → triggered | invalidated | expired

    `specificity` is the extraction confidence that the statement is
    concrete/falsifiable.  Catalysts below 0.50 are discarded by the
    extraction service (Slice 3) and never written here.
    """

    __tablename__ = "dossier_catalyst"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)

    statement         = Column(Text,        nullable=False, default="")
    # direction: bull_trigger | bear_trigger
    direction         = Column(String(20),  nullable=False, default="bull_trigger")
    specificity       = Column(Float,       nullable=False, default=0.0)
    expected_window   = Column(String(100), nullable=False, default="")
    # status: open | triggered | invalidated | expired
    status            = Column(String(20),  nullable=False, default="open", index=True)
    conviction_weight = Column(Float,       nullable=False, default=0.0)

    # Soft FK to thesis_versions.id that introduced this catalyst
    source_version_id = Column(String(36), nullable=True, default=None)

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    resolved_at = Column(DateTime(timezone=True), nullable=True,  default=None)


# ---------------------------------------------------------------------------
# 15. dossier_variant  (consensus-divergence map — single row per ticker)
# ---------------------------------------------------------------------------

class DossierVariant(Base):
    """Where ClearSignal diverges from implied consensus.

    `divergences` is a JSON list of objects:
        {dimension, consensus_view, clearsignal_view, direction, conviction}
    Bounded at 2–3 entries; stored as JSON because the list is render-only
    and never queried element-by-element.
    """

    __tablename__ = "dossier_variant"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, unique=True, index=True)

    divergences = _json_col(nullable=False, default=list)

    version    = Column(Integer, nullable=False, default=1)
    confidence = Column(Float,   nullable=False, default=0.0)

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        onupdate=_now)


# ---------------------------------------------------------------------------
# 16. dossier_durability  (raw signals — single row per ticker)
# ---------------------------------------------------------------------------

class DossierDurability(Base):
    """Raw durability signals — never pre-scored.

    Signals are stored as raw values so the Durability Score formula
    (Phase 9G Sprint 4) can evolve without a migration.  The score is
    always computed at read-time as a pure function of these fields.

    `conviction_trend` mirrors investment-memory direction:
        rising | falling | stable | volatile
    `cycle_position`: early | mid | late | unknown
    `horizon_hint`: trade | investment | secular
    """

    __tablename__ = "dossier_durability"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, unique=True, index=True)

    # cycle_position: early | mid | late | unknown
    cycle_position             = Column(String(20), nullable=False, default="unknown")
    catalyst_proximity_days    = Column(Integer,    nullable=True,  default=None)
    analog_time_to_trough_days = Column(Integer,    nullable=True,  default=None)
    # mirrors investment-memory: rising | falling | stable | volatile
    conviction_trend           = Column(String(20), nullable=False, default="stable")
    # horizon_hint: trade | investment | secular
    horizon_hint               = Column(String(20), nullable=False, default="investment")

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        onupdate=_now)


# ---------------------------------------------------------------------------
# 17. dossier_failure_mode  (active failure-pattern analog links)
# ---------------------------------------------------------------------------

class DossierFailureMode(Base):
    """Active failure-sequence match for a ticker.

    `analog_id` is a soft FK to historical_analogs.id — no CASCADE constraint
    so the dossier lifecycle is independent of the evidence library.
    `sequence_stage` is updated by the extraction service as stage signals
    progress (e.g. Stage 2 → Stage 3 of the Intel displacement sequence).
    """

    __tablename__ = "dossier_failure_mode"

    id        = Column(String(36), primary_key=True, default=_uuid)
    ticker    = Column(String(20), nullable=False, index=True)
    # Soft FK to historical_analogs.id
    analog_id = Column(String(36), nullable=False, index=True)

    sequence_stage     = Column(Integer, nullable=False, default=1)
    stage_evidence     = Column(Text,    nullable=False, default="")
    # Snapshot of relevance_score at match time — live score can drift
    relevance_at_match = Column(Float,   nullable=False, default=0.0)

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    matched_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("ticker", "analog_id", name="uq_dossier_failure_ticker_analog"),
    )


# ---------------------------------------------------------------------------
# 18. dossier_revision  (append-only causal audit log)
# ---------------------------------------------------------------------------

class DossierRevision(Base):
    """Immutable audit record for every material dossier change.

    This table has NO update or delete path in any repository.  It is the
    complete causal trail: *what* changed, *why* (source_version_id), and
    *how confident* the extraction was.

    `facet` valid values:
        core_debate | moat_dimension | catalyst | variant |
        durability  | failure_mode   | head
    """

    __tablename__ = "dossier_revision"

    id     = Column(String(36), primary_key=True, default=_uuid)
    ticker = Column(String(20), nullable=False, index=True)
    # facet: see docstring for valid values
    facet  = Column(String(40), nullable=False)

    # Change record
    prev_version    = Column(Integer, nullable=True,  default=None)  # NULL on first-create
    new_version     = Column(Integer, nullable=False, default=1)
    change_summary  = Column(Text,    nullable=False, default="")
    diff_json       = _json_col(nullable=False, default=dict)
    confidence      = Column(Float,   nullable=False, default=0.0)

    # Soft FK to thesis_versions.id that caused this revision
    source_version_id = Column(String(36), nullable=True, default=None)

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    # created_at is immutable — this row is never updated
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 19. dossier_evidence_ref  (per-claim provenance spine)
# ---------------------------------------------------------------------------

class DossierEvidenceRef(Base):
    """Provenance record linking a dossier claim to its source.

    Every facet value written by the extraction service must produce at least
    one evidence_ref row in the same transaction.  Claims without a harder
    source are written with source_type='inferred' — the frontend renders
    inferred claims distinctly from sourced ones.

    `claim_hash` is a stable identifier for the specific claim (e.g.
    SHA-256 of ticker + facet + normalised claim text) so refs survive
    prose rewording while the underlying fact stays the same.

    `source_type` valid values:
        thesis_version | analog | filing | financial_data | inferred
    """

    __tablename__ = "dossier_evidence_ref"

    id         = Column(String(36), primary_key=True, default=_uuid)
    ticker     = Column(String(20), nullable=False, index=True)
    facet      = Column(String(40), nullable=False)
    claim_hash = Column(String(64), nullable=False)

    # source_type: thesis_version | analog | filing | financial_data | inferred
    source_type = Column(String(30), nullable=False, default="inferred")
    # source_id FK value where applicable; NULL for inferred claims
    source_id   = Column(String(36), nullable=True, default=None)

    user_id    = Column(String(64),  nullable=True,  default=None)
    session_id = Column(String(200), nullable=False, default="")
    as_of      = Column(DateTime(timezone=True), nullable=False, default=_now)
