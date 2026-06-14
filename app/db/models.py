"""
SQLAlchemy ORM models — 28 tables.

Phase 9A: initial schema (tables 1–9)
Phase 9B: user_id added to thesis_versions, memory_entries, personalized_insights;
          debounce_visible added to thesis_deltas for material feed deduplication.
Phase 9F: historical_analogs (table 10) — Historical Evidence Engine.
Phase 9G · Phase 0: Company Dossier (tables 11–19) — canonical per-ticker
          company intelligence object. Read before synthesis (injection),
          written after synthesis (extraction). No behavior wired in this slice.
Phase 10A · Slice 1: Continuous Intelligence Loop (tables 20–24) — scheduled_jobs,
          job_locks, job_runs, delivery_ledger, notifications; plus two additive
          columns on briefing_sessions (content_hash, delivery_channel).
Phase 10B · Slice 2: DB Watchlist Membership (table 25) — watched_tickers;
          DB-backed add/remove/list for the global watchlist.

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

Continuous Intelligence Loop (Phase 10A · Slice 1)
20. scheduled_jobs         — Current-state job head with state machine + lease fields
21. job_locks              — Single-flight lease table (loop_lock_service exclusive owner)
22. job_runs               — Append-only execution audit; NEVER updated or deleted
23. delivery_ledger        — Pending/delivered artifact records; UNIQUE(content_key) dedup
24. notifications          — In-app channel sink; frontend polls GET /notifications
25. watched_tickers        — DB-backed watchlist membership (Phase 10B · Slice 2)

Briefing & Delivery (Phase 10C · Slice 2)
26. user_delivery_prefs    — Per-user/channel delivery preferences (additive, inert)
27. digest_batches         — Per-user/channel/bucket digest accumulator (additive, inert)
28. delivery_ledger_archive — Append-only aged-out delivery rows (additive, inert)
    plus two additive nullable columns on delivery_ledger (canonical_severity, severity_rank)

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
    """Daily-briefing session records — infrastructure only (Phase 9B surfaces).

    Phase 10A · Slice 1 adds two nullable columns that complete the loop's
    generation→delivery ladder:
      content_hash     — stable hash of the generated content (dedup key input)
      delivery_channel — channel to which this session was delivered ("in_app", etc.)
    Both columns are nullable so existing rows require no migration rewrite.
    """

    __tablename__ = "briefing_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_date = Column(Date, nullable=False, index=True)
    session_id = Column(String(200), nullable=False, default="")

    tickers_covered = Column(Text, nullable=False, default="[]")  # JSON list
    # status: "pending" | "generated" | "delivered"
    status = Column(String(20), nullable=False, default="pending")
    metadata_json = Column(Text, nullable=False, default="{}")  # JSON

    # Phase 10A: loop delivery columns (nullable — no rewrite of existing rows)
    content_hash     = Column(String(64), nullable=True, default=None)
    delivery_channel = Column(String(40), nullable=True, default=None)

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


# ===========================================================================
# Phase 10A · Slice 1 — Continuous Intelligence Loop (tables 20–24)
#
# The loop is the scheduler/heartbeat that transforms ClearSignal from a
# pull-mode tool into a continuous intelligence system.  Slice 1 is schema
# only: tables are inert without the later driver, lock service, and
# producer bindings.
#
# Design principles from the Phase 10A spec (§1–§6):
#   - Jobs are rows with state machines, not coroutines (DB = source of truth)
#   - Lease-based locking with fence tokens (not mutexes) for zombie safety
#   - Two idempotency layers: work_key (execution) + content_key (delivery)
#   - job_runs is append-only — same discipline as dossier_revision
#   - No FK constraints into thesis_versions/dossier_revision/ticker_memory
#     (loop reads them as dirty signals; lifecycle stays independent)
#   - JSON columns use _json_col() for JSONB/SQLite compat
# ===========================================================================


# ---------------------------------------------------------------------------
# 20. scheduled_jobs  (current-state job head — one row per job instance)
# ---------------------------------------------------------------------------

class ScheduledJob(Base):
    """Current-state head for one scheduled job instance.

    `state` machine:
        scheduled → claimed → running → succeeded | failed | skipped_stale | dead_letter

    UNIQUE(job_type, target_key, period_bucket) is the enqueue-idempotency and
    drift-coalescing constraint: two drift signals for the same (target, bucket)
    collapse to one row (spec §5.3).

    `fence_token` is incremented on each claim so zombie writers from dead
    holders can be rejected by the lock service (spec §4.4).
    """

    __tablename__ = "scheduled_jobs"

    id            = Column(String(36),  primary_key=True, default=_uuid)

    # Job identity
    job_type      = Column(String(60),  nullable=False)
    target_key    = Column(String(200), nullable=False)  # user_id, ticker, portfolio_id
    # period_bucket: ISO date or "drift" for one-shot drift jobs
    period_bucket = Column(String(40),  nullable=False)

    # State machine
    # state: scheduled | claimed | running | succeeded | failed | skipped_stale | dead_letter
    state         = Column(String(20),  nullable=False, default="scheduled", index=True)

    # Scheduling
    next_run_utc      = Column(DateTime(timezone=True), nullable=True, default=None)
    cadence           = Column(String(40), nullable=True, default=None)  # NULL = drift-only
    catch_up_window_s = Column(Integer,    nullable=False, default=3600)

    # Execution control
    attempts     = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)

    # Lease — NULL when job is not currently claimed
    holder_id         = Column(String(200), nullable=True, default=None)
    lease_expires_utc = Column(DateTime(timezone=True), nullable=True, default=None)
    # fence_token: monotonic counter, incremented on each claim
    fence_token       = Column(Integer, nullable=False, default=0)

    payload_json      = _json_col(nullable=False, default=dict)
    last_generated_at = Column(DateTime(timezone=True), nullable=True, default=None)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now,
                        onupdate=_now)

    __table_args__ = (
        UniqueConstraint("job_type", "target_key", "period_bucket",
                         name="uq_scheduled_job"),
    )


# ---------------------------------------------------------------------------
# 21. job_locks  (single-flight lease table)
# ---------------------------------------------------------------------------

class JobLock(Base):
    """Single-flight lease record — exclusively managed by loop_lock_service.

    One row per named lock.  Acquire = atomic conditional UPSERT that checks
    the current holder/expiry before writing (spec §4.2).

    Namespace convention: "loop:tick", "loop:job:{job_id}".

    `fence_token` is monotonically incremented on each successful acquire so
    the lock service can reject late writes from zombie holders whose leases
    were reclaimed.
    """

    __tablename__ = "job_locks"

    lock_name         = Column(String(200), primary_key=True)
    holder_id         = Column(String(200), nullable=False)
    acquired_utc      = Column(DateTime(timezone=True), nullable=False, default=_now)
    lease_expires_utc = Column(DateTime(timezone=True), nullable=False)
    # monotonic: incremented on each new acquire for zombie-write detection
    fence_token       = Column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# 22. job_runs  (append-only execution audit — NO UPDATE OR DELETE)
# ---------------------------------------------------------------------------

class JobRun(Base):
    """Immutable audit record for one job execution attempt.

    This table has NO update or delete path in any repository.  It is:
      1. The forensics layer: full causal trail of what ran, when, and why.
      2. The idempotency-lookup source: before invoking a producer the scheduler
         checks for a succeeded row with a matching work_key — if found, the
         execution short-circuits (spec §3.1).

    Analogous to dossier_revision: append-only, immutable, permanent.

    `outcome` valid values:
        running | succeeded | failed | skipped_stale | short_circuited | dead_letter
    """

    __tablename__ = "job_runs"

    id            = Column(String(36),  primary_key=True, default=_uuid)

    # Soft FK to scheduled_jobs.id — no CASCADE (job may be dead-lettered)
    job_id        = Column(String(36),  nullable=False, index=True)
    # work_key = hash(job_type, target_key, period_bucket) — idempotency key
    work_key      = Column(String(64),  nullable=False, index=True)

    # Denormalised from the job row (survives job dead-letter / future cleanup)
    job_type      = Column(String(60),  nullable=False)
    target_key    = Column(String(200), nullable=False)
    period_bucket = Column(String(40),  nullable=False)

    # Timing
    started_utc  = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_utc = Column(DateTime(timezone=True), nullable=True,  default=None)

    # Outcome — running until the execution completes
    # outcome: running | succeeded | failed | skipped_stale | short_circuited | dead_letter
    outcome         = Column(String(30),  nullable=False, default="running")
    spent_llm_calls = Column(Integer,     nullable=False, default=0)
    drift_hit       = Column(Boolean,     nullable=False, default=False)
    error           = Column(Text,        nullable=True,  default=None)

    # Lease identity (who ran this; fence proof for zombie detection)
    holder_id   = Column(String(200), nullable=False)
    fence_token = Column(Integer,     nullable=False, default=0)


# ---------------------------------------------------------------------------
# 23. delivery_ledger  (pending/delivered artifact records with dedup)
# ---------------------------------------------------------------------------

class DeliveryLedger(Base):
    """Current-state delivery record with duplicate-delivery hard stop.

    `content_key` UNIQUE constraint is the DB-layer guarantee that the same
    generated artifact is never delivered twice, regardless of retry count
    or concurrent delivery_flush invocations (spec §3.2).

    content_key = hash(target_key, channel, content_hash, period_bucket)

    `status` values: pending | delivered | failed | suppressed | deferred
    """

    __tablename__ = "delivery_ledger"

    id           = Column(String(36),  primary_key=True, default=_uuid)
    # content_key = hash(target_key, channel, content_hash, period_bucket)
    content_key  = Column(String(64),  nullable=False, unique=True)

    target_key   = Column(String(200), nullable=False)
    # channel: in_app | email | push  (10C adds email/push)
    channel      = Column(String(40),  nullable=False, default="in_app")
    content_hash = Column(String(64),  nullable=False)
    # artifact_ref: pointer to the source artifact (e.g. briefing_sessions.id)
    artifact_ref = Column(String(200), nullable=True, default=None)

    # status: pending | delivered | failed | suppressed | deferred
    status       = Column(String(20),  nullable=False, default="pending", index=True)
    attempts     = Column(Integer,     nullable=False, default=0)
    # not_before_utc: set by quiet hours, frequency cap, or mute guardrails
    not_before_utc = Column(DateTime(timezone=True), nullable=True, default=None)

    # Phase 10C · Slice 2: additive canonical-severity columns (nullable — no rewrite).
    # canonical_severity ∈ {critical|high|medium|low|info} (severity_model);
    # severity_rank is its numeric rank (0..4). Written by Slice 3+ ranking.
    canonical_severity = Column(String(20), nullable=True, default=None, index=True)
    severity_rank      = Column(Integer,    nullable=True, default=None)

    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    delivered_at = Column(DateTime(timezone=True), nullable=True,  default=None)


# ---------------------------------------------------------------------------
# 24. notifications  (in-app channel sink)
# ---------------------------------------------------------------------------

class Notification(Base):
    """In-app notification row — the sink for the in-app delivery channel.

    Frontend polls GET /notifications to build the inbox.  `read_at` is NULL
    until the user views the notification; the inbox sorts unread rows first.

    `kind` valid values (extensible):
        daily_brief | watchlist_alert | dossier_update | system

    Phase 10C adds email/push as additional channel types in loop_delivery_service;
    those channels do not write a notifications row (this table is in-app only).
    """

    __tablename__ = "notifications"

    id         = Column(String(36),  primary_key=True, default=_uuid)
    user_id    = Column(String(64),  nullable=False, index=True)
    # kind: daily_brief | watchlist_alert | dossier_update | system
    kind       = Column(String(60),  nullable=False, default="")
    body_json  = _json_col(nullable=False, default=dict)
    read_at    = Column(DateTime(timezone=True), nullable=True,  default=None)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 25. watched_tickers  (DB-backed watchlist membership — Phase 10B · Slice 2)
# ---------------------------------------------------------------------------

class WatchedTicker(Base):
    """One row per (user_id, ticker) pair that is on the watchlist.

    user_id is NULL for the global (single-user) watchlist that the current
    product uses.  Multi-user support wires in non-null user_id in a later
    slice; NULL rows are the only rows written today.

    active=False means soft-deleted (removed from watchlist).  Re-adding the
    same ticker reactivates the existing row rather than inserting a new one.

    company_name and added_at are the only metadata columns here; all thesis
    metadata (latest_thesis_trend, snapshot_count, etc.) remains in the flat
    file index.json until a dedicated migration moves it to DB.
    """

    __tablename__ = "watched_tickers"

    id           = Column(String(36),   primary_key=True, default=_uuid)
    user_id      = Column(String(64),   nullable=True,  default=None, index=True)
    ticker       = Column(String(20),   nullable=False, index=True)
    company_name = Column(String(200),  nullable=False, default="")
    active       = Column(Boolean,      nullable=False, default=True, index=True)
    added_at     = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at   = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 26. user_delivery_prefs  (per-user, per-channel delivery preferences — 10C·S2)
# ---------------------------------------------------------------------------

class UserDeliveryPref(Base):
    """Per-user, per-channel delivery preferences.

    user_id is NULL for the global (single-user) preference set, mirroring
    watched_tickers.  An ABSENT row means "use system defaults" — and the
    column defaults here mirror the existing settings.delivery_* globals so an
    absent row and a default row behave identically (safe defaults; spec §5.5).

    Phase 10C · Slice 2 — schema only.  No delivery code reads these yet;
    Slice 7 wires per-user preference resolution at the delivery boundary.

    min_severity is a CANONICAL severity (severity_model): critical|high|medium|low|info.
    """

    __tablename__ = "user_delivery_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_user_delivery_prefs_user_channel"),
    )

    id                = Column(String(36),  primary_key=True, default=_uuid)
    user_id           = Column(String(64),  nullable=True,  default=None, index=True)
    channel           = Column(String(40),  nullable=False, default="in_app", index=True)
    enabled           = Column(Boolean,     nullable=False, default=True)
    # min_severity: canonical severity floor; "info" matches delivery_severity_floor
    min_severity      = Column(String(20),  nullable=False, default="info")
    quiet_hours_start = Column(Integer,     nullable=False, default=22)
    quiet_hours_end   = Column(Integer,     nullable=False, default=7)
    timezone          = Column(String(64),  nullable=False, default="UTC")
    daily_cap         = Column(Integer,     nullable=False, default=20)
    mute_until        = Column(DateTime(timezone=True), nullable=True, default=None)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at        = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 27. digest_batches  (per-user/channel/bucket digest accumulator — 10C·S2)
# ---------------------------------------------------------------------------

class DigestBatch(Base):
    """One digest batch per (user_id, channel, period_bucket).

    The future §4.5 graceful-overflow sink: when alert volume would breach the
    daily cap, lower-severity changes accumulate here into one digest item.
    UNIQUE(user_id, channel, period_bucket) is the append-idempotency constraint
    (a second change in the bucket updates the row, never inserts a duplicate).

    Phase 10C · Slice 2 — schema only.  No batching logic exists yet (Slice 5).

    status: open | rendered | delivered.
    """

    __tablename__ = "digest_batches"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "channel", "period_bucket",
            name="uq_digest_batches_user_channel_bucket",
        ),
    )

    id            = Column(String(36),  primary_key=True, default=_uuid)
    user_id       = Column(String(64),  nullable=True,  default=None, index=True)
    channel       = Column(String(40),  nullable=False, default="in_app")
    period_bucket = Column(String(40),  nullable=False, index=True)
    status        = Column(String(20),  nullable=False, default="open", index=True)
    item_count    = Column(Integer,     nullable=False, default=0)
    payload_json  = _json_col(nullable=False, default=dict)
    content_key   = Column(String(64),  nullable=True,  default=None, index=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 28. delivery_ledger_archive  (append-only aged-out delivery rows — 10C·S2)
# ---------------------------------------------------------------------------

class DeliveryLedgerArchive(Base):
    """Append-only archive of aged-out delivery_ledger rows.

    Mirrors the job_runs / dossier_revision audit discipline: NEVER updated or
    deleted in any repository.  Preserves the delivery audit trail when live
    ledger rows are rolled up (future Slice 10 archival job).

    Phase 10C · Slice 2 — schema only.  No archival logic runs yet beyond the
    minimal archive_delivery helper (which is unused by any delivery path).
    """

    __tablename__ = "delivery_ledger_archive"

    id                   = Column(String(36),  primary_key=True, default=_uuid)
    original_delivery_id = Column(String(36),  nullable=True, default=None, index=True)
    user_id              = Column(String(64),  nullable=True, default=None, index=True)
    channel              = Column(String(40),  nullable=False, default="in_app")
    target_key           = Column(String(200), nullable=True, default=None)
    status               = Column(String(20),  nullable=True, default=None)
    payload_json         = _json_col(nullable=False, default=dict)
    content_key          = Column(String(64),  nullable=True, default=None, index=True)
    archived_at          = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)


# ---------------------------------------------------------------------------
# 29. portfolios  (user-authored portfolio head — Phase 10D · Slice 1)
# ---------------------------------------------------------------------------

class Portfolio(Base):
    """User-authored portfolio — one row per named collection.

    user_id is NULL for the global (single-user) portfolio, mirroring
    watched_tickers and user_delivery_prefs.  Multi-user wires in non-null
    user_id in a later slice; NULL rows are the only rows written today.

    is_default=True marks the auto-created watchlist-mirror portfolio
    (Slice 2).  A user may have at most one default portfolio.

    All intelligence (exposure clusters, insights, health metrics) is derived
    from this row's associated positions — this head row carries no analytical
    state itself.
    """

    __tablename__ = "portfolios"

    id          = Column(String(36),  primary_key=True, default=_uuid)
    user_id     = Column(String(64),  nullable=True,  default=None, index=True)
    name        = Column(String(200), nullable=False, default="My Portfolio")
    description = Column(Text,        nullable=True,  default=None)
    is_default  = Column(Boolean,     nullable=False, default=False)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at  = Column(DateTime(timezone=True), nullable=False, default=_now,
                         onupdate=_now)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_portfolios_user_name"),
    )


# ---------------------------------------------------------------------------
# 30. portfolio_positions  (per-portfolio position rows — Phase 10D · Slice 1)
# ---------------------------------------------------------------------------

class PortfolioPosition(Base):
    """One position row per (portfolio_id, ticker) pair.

    membership_class indicates how the user relates to this ticker:
      owned     — held in a brokerage account
      watchlist — on the WatchedTicker watchlist, not yet owned
      on_radar  — tracking but not on the watchlist

    Financial fields (weight, cost_basis, shares) are ALL user-supplied.
    The system NEVER fetches or derives them from external APIs (spec §1.3).

    active=False is a soft-delete.  Re-adding the same ticker reactivates
    the existing row rather than inserting a duplicate, mirroring the
    watchlist_repo.ticker_add idempotency discipline.

    UNIQUE(portfolio_id, ticker) is the append-idempotency constraint.
    """

    __tablename__ = "portfolio_positions"

    id               = Column(String(36),  primary_key=True, default=_uuid)
    portfolio_id     = Column(String(36),  nullable=False, index=True)
    ticker           = Column(String(20),  nullable=False, index=True)
    # membership_class: owned | watchlist | on_radar
    membership_class = Column(String(20),  nullable=False, default="watchlist")
    # Financial fields: ALL user-supplied; nullable; never derived externally.
    weight           = Column(Float,       nullable=True,  default=None)
    cost_basis       = Column(Float,       nullable=True,  default=None)
    shares           = Column(Float,       nullable=True,  default=None)
    notes            = Column(Text,        nullable=True,  default=None)
    active           = Column(Boolean,     nullable=False, default=True)
    added_at         = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at       = Column(DateTime(timezone=True), nullable=False, default=_now,
                              onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "ticker",
            name="uq_portfolio_positions_portfolio_ticker",
        ),
    )


# ---------------------------------------------------------------------------
# 31. portfolio_insights  (system-derived insights — Phase 10D · Slice 1)
# ---------------------------------------------------------------------------

class PortfolioInsight(Base):
    """System-derived portfolio-level insight — one row per content_key.

    insight_type is a closed enum from spec §3.1:
      concentration_breach | cluster_concentration | high_correlation_pair |
      propagated_catalyst | failure_contagion | macro_sensitivity_cluster |
      thesis_divergence | coverage_gap

    body_json holds the rendered template prose + structured metadata.
    It is populated by Slice 5 (insight generation); this schema row is
    inert until that slice lands.

    content_key = sha256(portfolio_id + insight_type + cluster_label +
                         period_bucket) — the §3.4 generation-side dedup
    (7-day bucket).  UNIQUE constraint is the hard stop.

    severity/severity_rank use the canonical severity_model.py ladder:
      critical=4 | high=3 | medium=2 | low=1 | info=0

    rank_score is stamped by Slice 6 (portfolio-relevance ranking) using
    the §3.3 formula.  Default 0.0 until Slice 6 lands.

    last_delivered_at is stamped by the Slice 7 delivery path; NULL means
    never delivered (feeds the novelty_factor in §3.3).
    """

    __tablename__ = "portfolio_insights"

    id                   = Column(String(36),  primary_key=True, default=_uuid)
    portfolio_id         = Column(String(36),  nullable=False, index=True)
    # insight_type: closed enum, see docstring above.
    insight_type         = Column(String(60),  nullable=False, default="")
    cluster_label        = Column(String(200), nullable=False, default="")
    member_tickers       = Column(Text,        nullable=False, default="[]")   # JSON array
    cluster_weight       = Column(Float,       nullable=True,  default=None)
    # Canonical severity (severity_model.py).
    severity             = Column(String(20),  nullable=False, default="info")
    severity_rank        = Column(Integer,     nullable=False, default=0)
    rank_score           = Column(Float,       nullable=False, default=0.0)
    body_json            = Column(Text,        nullable=False, default="{}")   # JSON
    # Freshness bound: min(updated_at) of contributing cross_exposure edges.
    cross_exposure_as_of = Column(DateTime(timezone=True), nullable=True, default=None)
    stale_input          = Column(Boolean,     nullable=False, default=False)
    # §3.4 dedup key — UNIQUE hard stop.
    content_key          = Column(String(64),  nullable=False, default="", unique=True)
    created_at           = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at           = Column(DateTime(timezone=True), nullable=False, default=_now,
                                  onupdate=_now)
    last_delivered_at    = Column(DateTime(timezone=True), nullable=True, default=None)
