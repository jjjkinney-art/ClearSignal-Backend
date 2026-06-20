"""
SQLAlchemy ORM models — 56 tables.

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
Phase 16 · Slice 1: Accounts & Identity (tables 32–35) — users, user_profiles,
          user_settings, audit_log; plus forward-compat org_id column on portfolios.
          Additive and inert — no auth behavior until later Phase 16 slices.
Phase 17 · Slice 1: Billing Schema (tables 36–38) — subscriptions, stripe_events,
          entitlement_cache; plus plan and plan_updated_at columns on users.
          Additive and inert — STRIPE_ENABLED=false throughout build slices.
Phase 12 · Slice 1: Forecasting Engine (tables 41–43) — forecast_vector,
          forecast_evidence, forecast_calibration_log.
          Additive and inert — all forecast_* flags default false/inert.

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

Portfolio Intelligence (Phase 10D · Slice 1)
29. portfolios             — User-authored portfolio head (one per named collection)
30. portfolio_positions    — Per-portfolio position rows
31. portfolio_insights     — System-derived portfolio-level insights

Accounts & Identity (Phase 16 · Slice 1)
32. users                  — Canonical identity record (one per Supabase account)
33. user_profiles          — Display + onboarding state (1:1 with users)
34. user_settings          — Briefing/delivery/UI preferences (1:1 with users)
35. audit_log              — Append-only mutation trail; NEVER updated or deleted

Billing (Phase 17 · Slice 1)
36. subscriptions          — One row per Stripe subscription lifecycle event
37. stripe_events          — Webhook idempotency table; dedup by stripe_event_id
38. entitlement_cache      — Per-user resolved plan limits (1h TTL)

Forecasting Engine (Phase 12 · Slice 1)
41. forecast_vector        — Probability distribution per entity/horizon/forecast_type
42. forecast_evidence      — Normalised evidence rows backing each forecast_vector
43. forecast_calibration_log — Immutable outcome records for Brier-score calibration

Personal Experience (Phase 18 · Slice 1)
54. personal_experience_cursor  — User view state per entity (upsert on unique key)
55. personal_experience_event   — Append-only surfacing log (what was shown and why)
56. personal_brief_snapshot     — One brief per user per day (upsert on unique key)

All primary keys are UUID strings (no dependency on DB-side uuid generation
so the same schema works for both PostgreSQL and SQLite).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
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

    # Phase 16 · Slice 1: forward-compat Teams anchor (spec §8.2).
    # Nullable placeholder; no organizations table in Phase 16.
    org_id = Column(String(36), nullable=True, default=None)

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


# ===========================================================================
# Phase 11 · Slice 1 — Similarity Engine (tables 39–40)
#
# Two DERIVED/CACHE tables only.  No source table is modified.
# Both tables are disposable — they can be dropped and rebuilt from substrate
# at any time without losing primary facts.
#
# Design principles from PHASE_11_SIMILARITY_ENGINE_SPEC.md:
#   - SP-1: no write-back to any source table (enforced by application test)
#   - SP-2: scoring kernel reused from evidence_engine.py (not stored here)
#   - SP-3: similarity_build_enabled=false → tables are inert until flag flips
#   - SP-4: edges are descriptive only; never read by forecasting paths
#   - Soft references via entity_key / source_versions; no DDL FK constraints
# ===========================================================================


# ---------------------------------------------------------------------------
# 39. similarity_feature_vector  (per-entity typed feature cache)
# ---------------------------------------------------------------------------

class SimilarityFeatureVector(Base):
    """Typed feature cache for one (target_type, entity_key, user_id) triple.

    This is a DERIVED table — built by the feature builder (Phase 11 Slice 2)
    by projecting the dossier facets, historical-analog fingerprint, cross-
    exposure edges, and portfolio substrate into typed feature representations.

    It is NEVER a source of primary facts and must not be read by any
    forecasting, conviction-scoring, or entitlement path.

    target_type valid values:
        company | thesis | catalyst | failure_mode | regime | portfolio

    entity_key: one of ticker / portfolio_id / catalyst_id / thesis_version_id

    categorical: JSON map of discrete features
        {sector, business_model, valuation_regime, growth_phase, macro_regime,
         moat_composite, debate_lean, catalyst_direction, ...}

    tag_set: JSON list for Jaccard similarity
        concern_tags, mechanisms, shared_concerns, moat axes present

    numeric: JSON map of bounded scalars [0, 1]
        conviction, durability_score, specificity, sequence_stage_norm, ...

    text_anchor: one human-readable sentence naming this entity's setup.
        Used only for explanation rendering; never scored.

    source_versions: JSON map {table: row_version/version} for staleness.
        Mismatch with live substrate values triggers a rebuild.

    vector_schema: bumped when feature taxonomy changes → global recompute.
    """

    __tablename__ = "similarity_feature_vector"

    id = Column(String(36), primary_key=True, default=_uuid)

    # target_type: company | thesis | catalyst | failure_mode | regime | portfolio
    target_type = Column(String(20),  nullable=False)
    # entity_key: ticker | portfolio_id | catalyst_id | thesis_version_id
    entity_key  = Column(String(200), nullable=False)

    # Typed feature representations
    categorical = _json_col(nullable=False, default=dict)
    tag_set     = _json_col(nullable=False, default=list)
    numeric     = _json_col(nullable=False, default=dict)

    # Human-readable anchor for explanation rendering (never scored)
    text_anchor = Column(Text, nullable=False, default="")

    # Provenance: {table: row_version} for staleness detection
    source_versions = _json_col(nullable=False, default=dict)

    # Invalidation key — bumped when feature taxonomy changes
    vector_schema = Column(Integer, nullable=False, default=1)

    # user_id: identity scoping (Phase 16).
    # NULL = shared global library (historical_analogs, etc.)
    user_id = Column(String(36), nullable=True, default=None, index=True)

    built_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint(
            "target_type", "entity_key", "user_id",
            name="uq_sfv_target_type_entity_key_user",
        ),
    )


# ---------------------------------------------------------------------------
# 40. similarity_edge  (scored, explained resemblance relation — TTL cache)
# ---------------------------------------------------------------------------

class SimilarityEdge(Base):
    """Scored, explained resemblance relation between two entities (TTL cache).

    This is a DERIVED table — written by the ranker (Phase 11 Slice 3) after
    scoring two SimilarityFeatureVectors.  It expires by TTL and is rebuilt
    by the loop.

    It is NEVER authoritative and must not be read by forecasting paths.
    Dropping the table degrades latency, never correctness.

    contributions: JSON list of {feature, shared_value, weight, partial_score}.
        MUST be non-empty for every above-floor edge (the orphan-score invariant).
        Orphan scores (empty contributions, floor_passed=True) must never persist.

    disanalogy: the strongest dissimilarity — the honesty tax.
        Every above-floor edge must name how the two entities differ.

    floor_passed: False = weak/none result.  Stored for diagnostic coverage;
        never delivered to a user surface as a resemblance.

    score_schema: bumped when scoring formula or weight profile changes;
        edges with a stale schema must be recomputed before serving.
    """

    __tablename__ = "similarity_edge"

    id = Column(String(36), primary_key=True, default=_uuid)

    # target_type: company | thesis | catalyst | failure_mode | regime | portfolio
    target_type   = Column(String(20),  nullable=False)
    query_key     = Column(String(200), nullable=False)
    candidate_key = Column(String(200), nullable=False)

    # Composite score [0, 1]
    score = Column(Float,   nullable=False, default=0.0)
    # Rank within the query's result set at materialisation time
    rank  = Column(Integer, nullable=False, default=0)

    # Explanation — MUST be non-empty for floor_passed=True edges
    contributions = _json_col(nullable=False, default=list)
    # Rendered one-sentence "why similar"
    headline      = Column(Text, nullable=False, default="")
    # Strongest dissimilarity — the honesty tax
    disanalogy    = Column(Text, nullable=False, default="")

    # Whether this edge cleared the relevance floor
    floor_passed = Column(Boolean, nullable=False, default=False)

    # Invalidation key — bumped when scoring formula or weight profile changes
    score_schema = Column(Integer, nullable=False, default=1)

    # user_id: identity scoping (Phase 16)
    user_id = Column(String(36), nullable=True, default=None)

    # TTL materialisation
    built_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint(
            "target_type", "query_key", "candidate_key", "user_id",
            name="uq_similarity_edge_type_query_candidate_user",
        ),
    )


# ===========================================================================
# Phase 16 · Slice 1 — Accounts & Identity (tables 32–35)
#
# Additive and inert: tables exist but no auth behavior is wired until
# later Phase 16 slices.  No existing table is modified (except a
# forward-compat org_id column added to portfolios above).
#
# Conventions carried from all prior tables:
#   - UUID string PKs (VARCHAR(36)), no DB-side uuid generation
#   - created_at / updated_at using _now()
#   - user_id VARCHAR(36) (matches users.id; soft FK, no DDL constraint)
#   - null-session safety enforced in the repository layer (account_repo.py)
#   - No password column anywhere — Supabase is the sole credential custodian
# ===========================================================================


# ---------------------------------------------------------------------------
# 32. users  (canonical identity record — one per Supabase account)
# ---------------------------------------------------------------------------

class User(Base):
    """Canonical identity record — one row per Supabase user account.

    `email` is case-folded at write time; the UNIQUE constraint on the DB
    column provides the hard dedup backstop.

    `account_type` carries the plan/role discriminator:
        individual | team_member | institutional | system

    `stripe_customer_id` is a nullable forward-compat placeholder (spec §8.1)
    — never written in Phase 16 build slices.

    `auth_subject` is the Supabase JWT 'sub' claim and the binding between
    this row and the identity provider.  NULL until Slice 3 wires Supabase.

    The system user (SYSTEM_DEFAULT_USER_ID) has `account_type='system'`
    and `email='system@clearsignal.internal'`.
    """

    __tablename__ = "users"

    id                 = Column(String(36),  primary_key=True, default=_uuid)
    email              = Column(String(320), nullable=False, unique=True)
    email_verified     = Column(Boolean,     nullable=False, default=False)
    # account_type: individual | team_member | institutional | system
    account_type       = Column(String(20),  nullable=False, default="individual")
    is_active          = Column(Boolean,     nullable=False, default=True)
    # Forward-compat Stripe placeholder — nullable, never written in Phase 16.
    stripe_customer_id = Column(String(64),  nullable=True,  default=None, unique=True)
    # Supabase JWT 'sub' claim — NULL until Slice 3.
    auth_subject       = Column(String(255), nullable=True,  default=None, unique=True)
    last_sign_in_at    = Column(DateTime(timezone=True), nullable=True, default=None)
    # Phase 17 · Slice 1: denormalised billing plan cache.
    # Authoritative source is subscriptions.plan_name; this column exists for
    # fast reads and observability only.  Updated on every subscription event.
    # plan ∈ {free, pro, teams, institutional, system}
    plan               = Column(String(20),  nullable=False, default="free")
    plan_updated_at    = Column(DateTime(timezone=True), nullable=True, default=None)
    created_at         = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at         = Column(DateTime(timezone=True), nullable=False, default=_now,
                                onupdate=_now)


# ---------------------------------------------------------------------------
# 33. user_profiles  (display + onboarding state — 1:1 with users)
# ---------------------------------------------------------------------------

class UserProfile(Base):
    """Display metadata and onboarding state for one user.

    `user_id` is the primary key — strict 1:1 with users.  Created on
    first sign-in (or on system-user seed); never deleted.

    `onboarding_step` drives the spec §7 sign-up wizard:
        pending | watchlist | portfolio | briefing | complete
    """

    __tablename__ = "user_profiles"

    # PK is user_id — 1:1 with users
    user_id                 = Column(String(36),  primary_key=True)
    display_name            = Column(String(200), nullable=True,  default=None)
    timezone                = Column(String(64),  nullable=False, default="UTC")
    locale                  = Column(String(10),  nullable=False, default="en")
    # onboarding_step: pending | watchlist | portfolio | briefing | complete
    onboarding_step         = Column(String(30),  nullable=False, default="pending")
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True, default=None)
    created_at              = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at              = Column(DateTime(timezone=True), nullable=False, default=_now,
                                     onupdate=_now)


# ---------------------------------------------------------------------------
# 34. user_settings  (briefing + delivery + UI preferences — 1:1 with users)
# ---------------------------------------------------------------------------

class UserSettings(Base):
    """Per-user briefing delivery and UI preferences.

    `user_id` is the primary key — strict 1:1 with users.  Created on
    first sign-in with safe defaults (mirrors system-wide settings defaults).

    `briefing_time_utc` is the UTC hour (0–23) for daily briefing delivery.
    `theme` ∈ {light, dark, system}.
    `delivery_channel` ∈ {in_app, email, push}.
    """

    __tablename__ = "user_settings"

    # PK is user_id — 1:1 with users
    user_id              = Column(String(36),  primary_key=True)
    # UTC hour for the daily briefing (0–23)
    briefing_time_utc    = Column(Integer,     nullable=False, default=7)
    quiet_hours_start    = Column(Integer,     nullable=False, default=22)
    quiet_hours_end      = Column(Integer,     nullable=False, default=7)
    # delivery_channel: in_app | email | push
    delivery_channel     = Column(String(40),  nullable=False, default="in_app")
    digest_enabled       = Column(Boolean,     nullable=False, default=True)
    # theme: light | dark | system
    theme                = Column(String(20),  nullable=False, default="system")
    created_at           = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at           = Column(DateTime(timezone=True), nullable=False, default=_now,
                                  onupdate=_now)


# ---------------------------------------------------------------------------
# 35. audit_log  (append-only mutation trail — NO UPDATE OR DELETE)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    """Immutable audit record for every user-scoped mutation.

    This table has NO update or delete path in any repository.  It is the
    compliance trail: who did what, to what resource, from which IP.

    `user_id` is the actor (may be the system user UUID).
    `resource` is the entity type (e.g. 'portfolio', 'watchlist', 'user').
    `resource_id` is the entity PK.
    `action` ∈ {create, update, delete, import, export, login, logout}.

    Analogous to dossier_revision and job_runs: append-only, immutable,
    permanent.  A write failure MUST NOT block the underlying user action
    (non-fatal, non-transactional audit writes per spec §6.6).
    """

    __tablename__ = "audit_log"

    id          = Column(String(36),  primary_key=True, default=_uuid)
    # user_id: the actor; may be the system user UUID
    user_id     = Column(String(36),  nullable=True,  default=None)
    # resource: entity type (e.g. 'portfolio', 'watchlist', 'user')
    resource    = Column(String(60),  nullable=False, default="")
    resource_id = Column(String(200), nullable=True,  default=None)
    # action: create | update | delete | import | export | login | logout
    action      = Column(String(40),  nullable=False, default="")
    ip_address  = Column(String(45),  nullable=True,  default=None)  # IPv4 or IPv6
    user_agent  = Column(Text,        nullable=True,  default=None)
    # created_at is immutable — this row is never updated
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Phase 17 · Slice 1: Billing Schema
# ---------------------------------------------------------------------------

# 36. subscriptions  (one row per Stripe subscription lifecycle event)
# ---------------------------------------------------------------------------

class Subscription(Base):
    """One row per Stripe subscription lifecycle event.

    Retains historical rows (status='canceled'/'lapsed') for compliance.
    Application invariant (not enforced by DB): at most one row per user_id
    where status IN ('active', 'trialing', 'past_due', 'paused').

    status ∈ {active, trialing, past_due, canceled, paused, lapsed}
    plan_name ∈ {free, pro, teams, institutional}
    billing_interval ∈ {month, year, custom}

    stripe_subscription_id is UNIQUE — the idempotency key for webhook updates.
    Webhooks are the only path that writes billing state; no HTTP route
    mutates plan_name or status directly.

    grace_period_ends_at is set by invoice.payment_failed handler (now + 3d).
    Entitlements remain at the paid level while past_due and within grace.
    """

    __tablename__ = "subscriptions"

    id                     = Column(String(36), primary_key=True, default=_uuid)
    # user_id: the subscriber (soft FK → users.id)
    user_id                = Column(String(36), nullable=False)
    # org_id: Teams billing anchor (soft FK → organizations.id, Phase 18+)
    org_id                 = Column(String(36), nullable=True,  default=None)
    # Stripe binding
    stripe_subscription_id = Column(String(64), nullable=False, unique=True)
    stripe_customer_id     = Column(String(64), nullable=False)
    stripe_price_id        = Column(String(64), nullable=False)
    # plan_name: free | pro | teams | institutional
    plan_name              = Column(String(20), nullable=False)
    # billing_interval: month | year | custom
    billing_interval       = Column(String(10), nullable=False, default="month")
    # status: active | trialing | past_due | canceled | paused | lapsed
    status                 = Column(String(20), nullable=False)
    trial_ends_at          = Column(DateTime(timezone=True), nullable=True,  default=None)
    current_period_start   = Column(DateTime(timezone=True), nullable=False)
    current_period_end     = Column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end   = Column(Boolean,    nullable=False, default=False)
    canceled_at            = Column(DateTime(timezone=True), nullable=True,  default=None)
    grace_period_ends_at   = Column(DateTime(timezone=True), nullable=True,  default=None)
    # seat_count: relevant for Syndicate (Teams) seat billing
    seat_count             = Column(Integer,    nullable=False, default=1)
    created_at             = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at             = Column(DateTime(timezone=True), nullable=False, default=_now,
                                    onupdate=_now)


# ---------------------------------------------------------------------------
# 37. stripe_events  (webhook idempotency table)
# ---------------------------------------------------------------------------

class StripeEvent(Base):
    """Idempotency record for every received Stripe webhook event.

    stripe_event_id (evt_*) is UNIQUE and serves as the global dedup key.
    The webhook handler checks this column before processing any event;
    a second delivery of the same event returns 200 without re-applying.

    NO raw payload is stored — Stripe event payloads may contain PII
    (email, billing address, card last-4).  Retrieve the full event from
    Stripe's dashboard or API by stripe_event_id for debugging.

    processing_status ∈ {pending, ok, error, skipped}
    error_detail is populated only when processing_status='error'.
    Handler errors update this row but never return 5xx — Stripe must not
    re-deliver an event whose side effects may have partially applied.
    """

    __tablename__ = "stripe_events"

    id                = Column(String(36), primary_key=True, default=_uuid)
    # stripe_event_id: evt_* — the global dedup key
    stripe_event_id   = Column(String(64), nullable=False, unique=True)
    event_type        = Column(String(80), nullable=False)
    # processing_status: pending | ok | error | skipped
    processing_status = Column(String(20), nullable=False, default="pending")
    error_detail      = Column(Text,       nullable=True,  default=None)
    processed_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 38. entitlement_cache  (per-user resolved plan limits, 1h TTL)
# ---------------------------------------------------------------------------

class EntitlementCache(Base):
    """Cached resolved entitlements for one user.

    PK is user_id — one row per user.  Invalidated (deleted) on every
    subscription lifecycle event.  Cache miss triggers a live recompute
    from the subscriptions table; DB failure falls open to the free tier.

    dossier_monthly_limit = -1 means unlimited.
    features_json: JSON text object of boolean feature flags per spec §3.3.

    expires_at: the cache row is stale after this timestamp (TTL = 1h).
    Callers must check expires_at > now() before trusting the cached values.
    """

    __tablename__ = "entitlement_cache"

    # PK is user_id — one row per user
    user_id               = Column(String(36), primary_key=True)
    plan_name             = Column(String(20), nullable=False)
    plan_status           = Column(String(20), nullable=False)
    # resource limits: -1 = unlimited
    watchlist_limit       = Column(Integer,    nullable=False)
    portfolio_limit       = Column(Integer,    nullable=False)
    position_limit        = Column(Integer,    nullable=False)
    dossier_monthly_limit = Column(Integer,    nullable=False)
    # features_json: serialised boolean feature flags (JSON text)
    features_json         = Column(Text,       nullable=False, default="{}")
    # trial_days_remaining: NULL when not in trial
    trial_days_remaining  = Column(Integer,    nullable=True,  default=None)
    computed_at           = Column(DateTime(timezone=True), nullable=False)
    # expires_at: row is stale after this timestamp (TTL = 1h)
    expires_at            = Column(DateTime(timezone=True), nullable=False)


# ===========================================================================
# Phase 12 · Slice 1 — Forecasting Engine (tables 41–43)
#
# Additive and inert: tables exist but no forecasting behavior is wired until
# later Phase 12 slices.  No existing table is modified.
#
# Design principles from the Phase 12 spec (§3):
#   - Three derived/analytics tables; disposable caches with no FK constraints
#     into source tables.
#   - No target-price, buy/sell, or recommendation field exists anywhere.
#   - forecast_calibration_log is append-only (no UPDATE ever issued).
#   - JSON columns via _json_col() for JSONB/SQLite compatibility.
#   - All six forecast_* flags default inert in config.py.
#   - SP-4 extension: forecasting never writes to source tables; similarity
#     never imports from forecasting.
# ===========================================================================


# ---------------------------------------------------------------------------
# 41. forecast_vector  (probability distribution — TTL cache)
# ---------------------------------------------------------------------------

class ForecastVector(Base):
    """Probability distribution over thesis-relevant outcomes for one entity.

    One row per (entity_type, entity_key, horizon, forecast_type, user_id).

    entity_type ∈ {company, thesis, failure_mode, portfolio}
    horizon     ∈ {near_term, medium_term, long_term}
    forecast_type ∈ {thesis_strengthening, thesis_weakening, risk_emergence,
                     catalyst_realization, similarity_outcome, regime_transition}

    Probability invariant (enforced by the probability engine before upsert):
        p_positive + p_negative + p_neutral ≈ 1.0  (within 0.001)

    Explainability invariant (enforced by the builder before upsert):
        why must be non-empty.
        invalidators must be a non-empty JSON list.
        At least one of analog_basis or similarity_basis must be non-empty.

    No target-price, buy/sell, or recommendation field exists here.
    This is a DERIVED cache — dropping forecast_vector degrades latency,
    never correctness.
    """

    __tablename__ = "forecast_vector"

    id = Column(String(36), primary_key=True, default=_uuid)

    # entity_type: company | thesis | failure_mode | portfolio
    entity_type = Column(String(20),  nullable=False)
    # entity_key: ticker | thesis_id | failure_mode_id | portfolio_id
    entity_key  = Column(String(200), nullable=False)

    # Horizon
    # horizon: near_term | medium_term | long_term
    horizon      = Column(String(20), nullable=False)
    # horizon_days: 30 | 90 | 180
    horizon_days = Column(Integer,    nullable=False, default=30)

    # forecast_type: thesis_strengthening | thesis_weakening | risk_emergence |
    #   catalyst_realization | similarity_outcome | regime_transition
    forecast_type = Column(String(50), nullable=False)

    # Probability distribution — enforced to sum ≈ 1.0 by the probability engine
    p_positive = Column(Float, nullable=False, default=0.33)
    p_negative = Column(Float, nullable=False, default=0.33)
    p_neutral  = Column(Float, nullable=False, default=0.34)

    # 80% confidence interval on p_positive
    confidence_band_low  = Column(Float, nullable=False, default=0.0)
    confidence_band_high = Column(Float, nullable=False, default=1.0)

    # Explainability — MUST be non-empty before storage
    # why: dominant probability driver, human-readable prose
    why          = Column(Text, nullable=False, default="")
    # invalidators: JSON list of named invalidation conditions
    invalidators = _json_col(nullable=False, default=list)

    # Evidence provenance — at least one must be non-empty
    # analog_basis: JSON list of historical_analog IDs
    analog_basis     = _json_col(nullable=False, default=list)
    # similarity_basis: JSON list of similarity_edge IDs
    similarity_basis = _json_col(nullable=False, default=list)

    # evidence_summary: JSON list of top-N condensed evidence items
    evidence_summary = _json_col(nullable=False, default=list)

    # source_versions: {table: row_version} provenance for staleness detection
    source_versions = _json_col(nullable=False, default=dict)

    # Invalidation key — bumped when probability formula or weight config changes
    forecast_schema = Column(Integer, nullable=False, default=1)

    # user_id: identity scoping (Phase 16). NULL = global.
    user_id = Column(String(36), nullable=True, default=None, index=True)

    # TTL materialisation
    built_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_key", "horizon", "forecast_type", "user_id",
            name="uq_forecast_vector_entity_horizon_type_user",
        ),
    )


# ---------------------------------------------------------------------------
# 42. forecast_evidence  (normalised evidence rows per forecast_vector)
# ---------------------------------------------------------------------------

class ForecastEvidence(Base):
    """One piece of evidence backing a ForecastVector.

    Normalised out of forecast_vector so evidence items are queryable
    independently for explainability, audit, and calibration diagnostics.

    source_type ∈ {historical_analog, similarity_edge, thesis_version,
                   watchlist_signal, portfolio_exposure, failure_mode_stage}

    direction ∈ {bullish, bearish, neutral}  (relative to the thesis)

    contribution: signed probability shift. Negative = bearish on p_positive.
    weight:       this item's weight in the ensemble [0, 1].
    description:  human-readable statement — MUST be non-empty.

    No unique constraint — one forecast_vector can have many evidence rows.
    """

    __tablename__ = "forecast_evidence"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to forecast_vector.id — no CASCADE
    forecast_id = Column(String(36), nullable=False, index=True)

    # source_type: historical_analog | similarity_edge | thesis_version |
    #   watchlist_signal | portfolio_exposure | failure_mode_stage
    source_type = Column(String(50),  nullable=False)
    # source_id: primary key of the source row
    source_id   = Column(String(200), nullable=False)

    # direction: bullish | bearish | neutral
    direction = Column(String(20), nullable=False, default="neutral")

    # Signed probability shift caused by this evidence item
    contribution = Column(Float, nullable=False, default=0.0)

    # Weight in the ensemble [0, 1]
    weight = Column(Float, nullable=False, default=0.0)

    # Human-readable statement — MUST be non-empty
    description = Column(Text, nullable=False, default="")

    # Denormalised for query convenience
    entity_type = Column(String(20),  nullable=False, default="")
    entity_key  = Column(String(200), nullable=False, default="")

    # user_id: identity scoping (Phase 16). NULL = global.
    user_id = Column(String(36), nullable=True, default=None)

    built_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 43. forecast_calibration_log  (immutable Brier-score records)
# ---------------------------------------------------------------------------

class ForecastCalibrationLog(Base):
    """Immutable outcome record used to compute Brier scores and calibration curves.

    This table has NO update or delete path in any service or repository.
    Each evaluation creates a new row. Calibration trends are computed over
    the set of rows with evaluated_at within a rolling window.

    Analogous to dossier_revision, job_runs, and audit_log: append-only,
    immutable, permanent.

    actual_outcome ∈ {positive, negative, neutral, unknown, inconclusive}

    brier_score = (p_positive_at_forecast - outcome_indicator)²
      where outcome_indicator = 1.0 if positive, 0.0 if negative.
      NULL when actual_outcome is neutral / unknown / inconclusive.

    evaluation_source ∈ {thesis_state_change, risk_event_observed,
                         watchlist_resolved, manual_review}
    """

    __tablename__ = "forecast_calibration_log"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to forecast_vector.id — denormalised to survive vector expiry
    forecast_id = Column(String(36), nullable=False, index=True)

    # Denormalised from the forecast_vector row at evaluation time
    entity_type   = Column(String(20),  nullable=False, default="")
    entity_key    = Column(String(200), nullable=False, default="")
    horizon       = Column(String(20),  nullable=False, default="")
    forecast_type = Column(String(50),  nullable=False, default="")

    # Snapshot of probabilities at the time of the original forecast
    p_positive_at_forecast = Column(Float, nullable=False, default=0.0)
    p_negative_at_forecast = Column(Float, nullable=False, default=0.0)
    p_neutral_at_forecast  = Column(Float, nullable=False, default=0.0)

    # Observed outcome
    # actual_outcome: positive | negative | neutral | unknown | inconclusive
    actual_outcome = Column(String(50), nullable=False, default="unknown")

    # Brier score: NULL when actual_outcome not binary (neutral/unknown/inconclusive)
    brier_score = Column(Float, nullable=True, default=None)

    # evaluation_source: thesis_state_change | risk_event_observed |
    #   watchlist_resolved | manual_review
    evaluation_source = Column(String(50), nullable=False, default="manual_review")

    # When the outcome was observed — immutable after write
    evaluated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # Optional operator notes
    evaluator_notes = Column(Text, nullable=True, default=None)

    # user_id: identity scoping (Phase 16). NULL = global.
    user_id = Column(String(36), nullable=True, default=None)

    # created_at is immutable — this row is NEVER updated
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 44. decision_priority  (Phase 13 · Slice 1 — Decision Intelligence)
# ---------------------------------------------------------------------------

class DecisionPriority(Base):
    """Priority ranking for one attention candidate, per user scope.

    One row per (candidate_type, entity_type, entity_key, source_ref, user_id).

    Phase 13 Decision Intelligence PRIORITIZES information; it does not make
    investment decisions. There is no buy/sell/hold, position-size, target-price,
    trade, or execution column anywhere on this table — the no-advice boundary is
    structural (spec §0). This is a DERIVED cache: dropping decision_priority
    degrades latency, never correctness.

    candidate_type ∈ {forecast, risk, catalyst, watchlist_item,
                      portfolio_exposure, thesis_transition, similarity_match}
    entity_type    ∈ {company, thesis, failure_mode, portfolio}
    decision_priority (bucket) ∈ {critical, high, medium, low, informational}

    Score invariant (enforced by the scoring engine before upsert — Phase 13
    Slice 3): all five component scores and decision_rank_score ∈ [0, 1]; the
    bucket is consistent with decision_rank_score thresholds.

    Explainability invariant (enforced by the builder before upsert — Phase 13
    Slice 5): decision_reason and why_now non-empty; deprioritizers a non-empty
    JSON list; at least one evidence_summary item. A priority that cannot
    explain itself is never stored.

    user_id NULL = global / intrinsic tier (holder-independent). A non-NULL
    user_id is the portfolio-adjusted tier for one user (Phase 13 Slice 7).
    """

    __tablename__ = "decision_priority"

    id = Column(String(36), primary_key=True, default=_uuid)

    # candidate_type: forecast | risk | catalyst | watchlist_item |
    #   portfolio_exposure | thesis_transition | similarity_match
    candidate_type = Column(String(30), nullable=False)

    # entity_type: company | thesis | failure_mode | portfolio
    entity_type = Column(String(20),  nullable=False)
    # entity_key: ticker | thesis_id | failure_mode_id | portfolio_id
    entity_key  = Column(String(200), nullable=False)

    # source_ref: id of the originating artifact (forecast_vector.id,
    #   similarity_edge.id, watchlist row key, etc.)
    source_ref  = Column(String(200), nullable=False, default="")

    # decision_priority: bucket label — critical | high | medium | low | informational
    decision_priority = Column(String(20), nullable=False, default="informational")
    # Continuous [0,1] score used for ordering within and across buckets
    decision_rank_score = Column(Float, nullable=False, default=0.0)

    # Five component scores, each [0,1]
    attention_score   = Column(Float, nullable=False, default=0.0)
    urgency_score     = Column(Float, nullable=False, default=0.0)
    impact_score      = Column(Float, nullable=False, default=0.0)  # portfolio-aware (Slice 7)
    confidence_score  = Column(Float, nullable=False, default=0.0)
    uncertainty_score = Column(Float, nullable=False, default=0.0)

    # Explainability — MUST be non-empty before storage
    # decision_reason: dominant-factor prose ("why important")
    decision_reason = Column(Text, nullable=False, default="")
    # why_now: urgency-driver prose ("why now")
    why_now         = Column(Text, nullable=False, default="")
    # deprioritizers: JSON list of named conditions that would lower this priority
    deprioritizers  = _json_col(nullable=False, default=list)

    # evidence_summary: JSON list of top-N condensed evidence items
    evidence_summary = _json_col(nullable=False, default=list)

    # source_versions: {table: row_version} provenance for staleness detection
    source_versions  = _json_col(nullable=False, default=dict)

    # Invalidation key — bumped when scoring formula / weights / thresholds change
    decision_schema = Column(Integer, nullable=False, default=1)

    # user_id: identity scope (Phase 16). NULL = global / intrinsic tier.
    user_id = Column(String(36), nullable=True, default=None, index=True)

    # TTL materialisation
    built_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint(
            "candidate_type", "entity_type", "entity_key", "source_ref", "user_id",
            name="uq_decision_priority_candidate_entity_source_user",
        ),
    )


# ---------------------------------------------------------------------------
# 45. decision_evidence  (normalised evidence rows per decision_priority)
# ---------------------------------------------------------------------------

class DecisionEvidence(Base):
    """One contributing upstream signal backing a DecisionPriority.

    Normalised out of decision_priority so evidence items are queryable
    independently for explainability and audit. Mirrors forecast_evidence.

    source_type ∈ {forecast_vector, similarity_edge, historical_analog,
                   thesis_version, watchlist_signal, portfolio_exposure,
                   delivery_transition, calibration_log}

    dimension ∈ {attention, urgency, impact, confidence, uncertainty}
      — which component score this evidence fed.

    contribution: signed contribution to that dimension.
    weight:       weight in the dimension aggregate [0, 1].
    description:  human-readable statement — MUST be non-empty.

    No unique constraint — one priority has many evidence rows.
    """

    __tablename__ = "decision_evidence"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to decision_priority.id — no CASCADE
    priority_id = Column(String(36), nullable=False, index=True)

    # source_type: forecast_vector | similarity_edge | historical_analog |
    #   thesis_version | watchlist_signal | portfolio_exposure |
    #   delivery_transition | calibration_log
    source_type = Column(String(40),  nullable=False)
    # source_id: primary key of the source row
    source_id   = Column(String(200), nullable=False)

    # dimension: attention | urgency | impact | confidence | uncertainty
    dimension = Column(String(20), nullable=False, default="attention")

    # Signed contribution to the dimension aggregate
    contribution = Column(Float, nullable=False, default=0.0)

    # Weight in the dimension aggregate [0, 1]
    weight = Column(Float, nullable=False, default=0.0)

    # Human-readable statement — MUST be non-empty
    description = Column(Text, nullable=False, default="")

    # Denormalised for query convenience
    entity_type = Column(String(20),  nullable=False, default="")
    entity_key  = Column(String(200), nullable=False, default="")

    # user_id: identity scoping (Phase 16). NULL = global.
    user_id = Column(String(36), nullable=True, default=None)

    built_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# ---------------------------------------------------------------------------
# 46. decision_ranking_log  (immutable append-only ranking snapshots)
# ---------------------------------------------------------------------------

class DecisionRankingLog(Base):
    """Immutable ranking snapshot used for drift and stability validation.

    This table has NO update or delete path in any service or repository.
    Each snapshot (and each later outcome attribution) creates a NEW row.
    Modelled on forecast_calibration_log: append-only, immutable, permanent.

    snapshot_reason ∈ {scheduled, rebuild, transition, manual_review}

    realized_significance ∈ {material, immaterial, unknown} — filled later by
    appending a NEW row keyed to the same priority_id (never by updating an
    existing row). Used by Phase 13 Slice 9 calibration to measure whether
    high-priority items turned out to matter (rank-order agreement), NOT a
    Brier score.
    """

    __tablename__ = "decision_ranking_log"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to decision_priority.id — denormalised to survive priority expiry
    priority_id = Column(String(36), nullable=False, index=True)

    # Denormalised from the priority row at snapshot time
    candidate_type = Column(String(30),  nullable=False, default="")
    entity_type    = Column(String(20),  nullable=False, default="")
    entity_key     = Column(String(200), nullable=False, default="")

    # user_id: identity scope (Phase 16). NULL = global.
    user_id = Column(String(36), nullable=True, default=None, index=True)

    # Bucket + score at snapshot time
    decision_priority   = Column(String(20), nullable=False, default="informational")
    decision_rank_score = Column(Float,      nullable=False, default=0.0)
    # Ordinal position within the user's ranked set at snapshot time
    rank_position = Column(Integer, nullable=False, default=0)

    # snapshot_reason: scheduled | rebuild | transition | manual_review
    snapshot_reason = Column(String(40), nullable=False, default="scheduled")

    # realized_significance: material | immaterial | unknown (filled later, append-only)
    realized_significance = Column(String(20), nullable=True, default=None)

    # When this snapshot / outcome was recorded — immutable
    evaluated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # created_at is immutable — this row is NEVER updated
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


# =============================================================================
# Phase 14 — Scenario Engine  (Tables 47–49)
# =============================================================================
#
# The Scenario Engine answers "What happens if X changes?" — it produces
# conditional analyses, NOT predictions and NOT recommendations (SP-6 /
# spec §0). There are no buy/sell/hold, position_size, target_price, trade,
# or execution fields anywhere in these three tables.
#
# All three tables are DERIVED/ANALYTICS and additive:
#   - scenario_snapshot (47): one row per evaluated conditional scenario.
#   - scenario_evidence (48): normalised evidence rows per snapshot.
#   - scenario_run_log  (49): immutable run / shadow / outcome log.
#
# - JSON columns via _json_col() for JSONB/SQLite compatibility.
# - Null-session contract: every repository function returns an inert value
#   (None / [] / 0) when session is None.


# 47. scenario_snapshot  (Phase 14 · Slice 1 — Scenario Engine)
# -----------------------------------------------------------------------------

class ScenarioSnapshot(Base):
    """One evaluated conditional scenario per (type, entity, key, user) tuple.

    Stores the transmission mechanism, impact/plausibility bands, the five
    mandatory explanation fields (what_changed / why_it_matters /
    transmission_path / evidence / invalidators), and the affected upstream
    artefact sets.

    SAFETY: No column holds a buy/sell/hold verdict, recommended size, target
    price, execution instruction, or predicted-return value (spec §0 / SP-6).
    This is a DERIVED cache: dropping scenario_snapshot and rebuilding from
    the intelligence substrate yields the same rows.

    scenario_type ∈ {macro, company, sector, catalyst, failure_mode, portfolio}
    entity_type   ∈ {company, sector, macro, portfolio}
    scenario_impact ∈ {significant_positive, moderate_positive, neutral,
                        moderate_negative, significant_negative, ambiguous}
    plausibility_band ∈ {remote, plausible, likely_conditional}

    Explainability gate (enforced in Slice 14.4 before upsert):
      what_changed, why_it_matters, transmission_path non-empty;
      invalidators non-empty (≥1 falsifiable condition);
      ≥1 scenario_evidence row.
    """

    __tablename__ = "scenario_snapshot"

    id              = Column(String(36), primary_key=True, default=_uuid)

    # scenario_type: macro | company | sector | catalyst | failure_mode | portfolio
    scenario_type   = Column(String(30), nullable=False)
    # entity_type: company | sector | macro | portfolio
    entity_type     = Column(String(20), nullable=False)
    # entity_key: ticker | sector_id | macro_key | portfolio_id
    entity_key      = Column(String(200), nullable=False)
    # scenario_key: stable identity of the condition ("the if")
    scenario_key    = Column(String(200), nullable=False, default="")

    # condition: human-readable description of the triggering change
    condition       = Column(Text, nullable=False, default="")

    # transmission_path: ordered list of cause→effect steps — MUST be non-empty
    transmission_path = _json_col(nullable=False, default=list)

    # scenario_impact: qualitative directional band — NOT a price/return target
    scenario_impact = Column(String(30), nullable=False, default="ambiguous")

    # plausibility_band: conditional framing — NOT a probability of occurrence
    plausibility_band = Column(String(30), nullable=False, default="plausible")

    # Confidence/uncertainty carried from upstream signals [0,1]
    confidence_score  = Column(Float, nullable=False, default=0.0)
    uncertainty_score = Column(Float, nullable=False, default=0.0)

    # Affected upstream artefact sets (soft references)
    affected_entities  = _json_col(nullable=False, default=list)
    affected_forecasts = _json_col(nullable=False, default=list)
    affected_decisions = _json_col(nullable=False, default=list)

    # The five mandatory explanation fields
    what_changed     = Column(Text, nullable=False, default="")
    why_it_matters   = Column(Text, nullable=False, default="")
    # transmission_path (above) is explanation field 3
    evidence_summary = _json_col(nullable=False, default=list)
    invalidators     = _json_col(nullable=False, default=list)

    # Provenance: {table: row_version} for staleness detection
    source_versions  = _json_col(nullable=False, default=dict)

    # Invalidation key — bumped when evaluation model / weights change
    scenario_schema  = Column(Integer, nullable=False, default=1)

    # user_id: identity scoping (Phase 16). NULL = global / intrinsic tier.
    user_id          = Column(String(36), nullable=True, default=None)

    # TTL materialisation
    built_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    expires_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: _now() + timedelta(hours=72))

    __table_args__ = (
        UniqueConstraint(
            "scenario_type", "entity_type", "entity_key", "scenario_key", "user_id",
            name="uq_scenario_snapshot_type_entity_key_user",
        ),
        Index("ix_ss_entity",          "entity_type",     "entity_key"),
        Index("ix_ss_scenario_type",   "scenario_type"),
        Index("ix_ss_plausibility",    "plausibility_band"),
        Index("ix_ss_user_id",         "user_id"),
        Index("ix_ss_expires_at",      "expires_at"),
        Index("ix_ss_scenario_schema", "scenario_schema"),
        Index("ix_ss_scenario_key",    "scenario_key"),
    )


# 48. scenario_evidence  (normalised evidence rows per scenario_snapshot)
# -----------------------------------------------------------------------------

class ScenarioEvidence(Base):
    """One contributing upstream signal backing a ScenarioSnapshot.

    Normalised out of scenario_snapshot so evidence items are queryable
    independently for explainability and audit.

    source_phase ∈ {memory, similarity, forecast, decision, portfolio,
                     cross_exposure, dossier, watchlist}
    """

    __tablename__ = "scenario_evidence"

    id          = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to scenario_snapshot.id — no CASCADE
    scenario_id = Column(String(36), nullable=False)

    # source_phase: which upstream phase/substrate this evidence comes from
    source_phase = Column(String(30), nullable=False, default="")

    # source_ref: primary key or stable identifier of the upstream artefact
    source_ref   = Column(String(200), nullable=False, default="")

    # captured_value: the cited upstream value at build time (read-only copy)
    captured_value = _json_col(nullable=False, default=dict)

    # Denormalised for query convenience
    entity_type  = Column(String(20), nullable=False, default="")
    entity_key   = Column(String(200), nullable=False, default="")

    # user_id: identity scoping. NULL = global.
    user_id      = Column(String(36), nullable=True, default=None)

    captured_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_se_scenario_id", "scenario_id"),
        Index("ix_se_source",      "source_phase", "source_ref"),
        Index("ix_se_entity",      "entity_type",  "entity_key"),
        Index("ix_se_user_id",     "user_id"),
    )


# 49. scenario_run_log  (immutable append-only run / shadow / outcome log)
# -----------------------------------------------------------------------------

class ScenarioRunLog(Base):
    """Immutable run / shadow / calibration-outcome log for the Scenario Engine.

    This table has NO UPDATE or DELETE path in any service or repository.
    Each run, shadow-journal entry, or calibration outcome creates a NEW row.
    Modelled on DecisionRankingLog and ForecastCalibrationLog: append-only.

    run_reason    ∈ {assembly, shadow, calibration_outcome}
    realized_state ∈ {materialized, invalidated, unresolved} — nullable;
      only set on calibration_outcome rows; never mutated after insert.
    """

    __tablename__ = "scenario_run_log"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to scenario_snapshot.id — nullable for run-level rows
    scenario_id   = Column(String(36), nullable=True, default=None)

    # Denormalised from the snapshot row at log time (survives snapshot expiry)
    scenario_type = Column(String(30), nullable=False, default="")
    entity_type   = Column(String(20), nullable=False, default="")
    entity_key    = Column(String(200), nullable=False, default="")

    # user_id: identity scoping. NULL = global.
    user_id       = Column(String(36), nullable=True, default=None)

    # run_reason: assembly | shadow | calibration_outcome
    run_reason    = Column(String(30), nullable=False, default="assembly")

    # snapshot_reason: transition/journal classification
    snapshot_reason = Column(String(60), nullable=False, default="")

    # realized_state: materialized | invalidated | unresolved (calibration only)
    realized_state = Column(String(20), nullable=True, default=None)

    # Ordinal surface position at shadow-journal time
    rank_position  = Column(Integer, nullable=True, default=None)

    # When this run / outcome was recorded — immutable
    evaluated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # created_at is immutable — this row is NEVER updated
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_srl_scenario_id",  "scenario_id"),
        Index("ix_srl_entity",       "entity_type",   "entity_key"),
        Index("ix_srl_user_id",      "user_id"),
        Index("ix_srl_evaluated_at", "evaluated_at"),
        Index("ix_srl_scenario_type","scenario_type",  "evaluated_at"),
        Index("ix_srl_run_reason",   "run_reason"),
    )


# ---------------------------------------------------------------------------
# Phase 15 — User Learning & Personalization  (tables 50–53)
# ---------------------------------------------------------------------------


class UserSignalEvent(Base):
    """Append-only raw behavioral event stream — Phase 15 · table 50.

    Each row records one user interaction. Insert-only; never updated or deleted
    except by the retention sweep. user_id is mandatory (anonymous events are not
    learned — principle #2).

    surface_was_personalized + pre_personalization_rank are the anti-feedback-loop
    fields (risk R2): the learning pass uses the unbiased pre-personalization rank
    rather than the served rank to avoid reinforcing whatever was already on top.

    SP-7 invariants: no advice, no truth-write path, no conviction/order/execution.
    """

    __tablename__ = "user_signal_event"

    id      = Column(String(36), primary_key=True, default=_uuid)

    # user_id: NULL not permitted — anonymous behavior is not learned
    user_id = Column(String(36), nullable=False)

    # signal_type: watchlist_add | watchlist_remove | search_query | search_click |
    #   analysis_open | section_expand | alert_open | alert_act | alert_dismiss |
    #   alert_mute | forecast_view | horizon_toggle | scenario_expand |
    #   scenario_dismiss | portfolio_view | explicit_pref_set | explicit_pref_unset
    signal_type = Column(String(40), nullable=False, default="")

    # polarity: positive | negative | neutral
    polarity = Column(String(10), nullable=False, default="neutral")

    # entity_type: company | sector | theme | signal_type | horizon
    entity_type = Column(String(20), nullable=False, default="")

    # entity_key: ticker / sector_id / theme_key / signal_type_name / horizon_band
    entity_key = Column(String(200), nullable=False, default="")

    # source_surface: which UI surface emitted the event
    source_surface = Column(String(60), nullable=False, default="")

    # surface_was_personalized: whether this surface was already personalized
    surface_was_personalized = Column(Boolean, nullable=False, default=False)

    # pre_personalization_rank: the item's rank before any personalization
    pre_personalization_rank = Column(Integer, nullable=True, default=None)

    # interaction_weight: normalized magnitude [0, 1]
    interaction_weight = Column(Float, nullable=False, default=1.0)

    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_use_user_occurred",    "user_id", "occurred_at"),
        Index("ix_use_user_entity",      "user_id", "entity_type", "entity_key"),
        Index("ix_use_user_signal_type", "user_id", "signal_type"),
        Index("ix_use_polarity",         "polarity"),
    )


class LearnedPreference(Base):
    """Current-state evidence-backed belief per (user_id, dimension, entity_key) — table 51.

    One row per user/dimension/entity triple. Status-mutable (decay, falsification).
    The inference pass upserts this row; no other write path exists.

    The four mandatory explainability fields (SP-7g):
      1. belief_basis           — why we believe this
      2. preference_evidence rows (#52) — the contributing events (external)
      3. signal_strength_label + confidence — signal strength
      4. falsifier              — what would overturn this belief

    A preference missing any of these is rejected at the gate and never set active.
    """

    __tablename__ = "learned_preference"

    id      = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), nullable=False)

    # dimension: sector_interest | company_interest | theme_interest |
    #   preferred_horizon | preferred_signal_type | ignored_signal_type |
    #   portfolio_sensitivity
    dimension  = Column(String(30), nullable=False, default="")

    # entity_key: the specific sector / company / theme / horizon / signal-type
    entity_key = Column(String(200), nullable=False, default="")

    # affinity: signed strength [-1, 1]
    affinity = Column(Float, nullable=False, default=0.0)

    # confidence: evidence quality [0, 1]
    confidence = Column(Float, nullable=False, default=0.0)

    # evidence_count: number of contributing events
    evidence_count = Column(Integer, nullable=False, default=0)

    # status: active | unresolved | decayed | falsified | explicit
    status = Column(String(15), nullable=False, default="unresolved")

    # Explainability field 1: why we believe this
    belief_basis = Column(Text, nullable=False, default="")

    # Explainability field 3: signal strength label
    #   strong | moderate | tentative
    signal_strength_label = Column(String(10), nullable=False, default="tentative")

    # Explainability field 4: what would overturn this belief
    falsifier = Column(Text, nullable=False, default="")

    first_observed_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_reinforced_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    # preference_schema: bumped when inference model changes (invalidation key)
    preference_schema = Column(Integer, nullable=False, default=1)

    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_lp_user_id",         "user_id"),
        Index("ix_lp_user_dimension",  "user_id", "dimension"),
        Index("ix_lp_user_entity",     "user_id", "entity_key"),
        Index("ix_lp_status",          "status"),
        Index("ix_lp_dimension_entity","dimension", "entity_key"),
        Index("ix_lp_last_reinforced", "last_reinforced_at"),
        UniqueConstraint("user_id", "dimension", "entity_key",
                         name="uq_learned_preference_user_dim_entity"),
    )


class PreferenceEvidence(Base):
    """Normalized evidence rows backing each learned preference — table 52.

    Explainability field 2. Insert-only. Soft FKs to learned_preference and
    user_signal_event (no CASCADE — evidence outlives decay or retention sweeps).

    Every active/explicit preference must have >= MIN_EVENTS[dimension] resolvable
    rows here — checked by the explainability gate (SP-7g, §10.4).
    """

    __tablename__ = "preference_evidence"

    id = Column(String(36), primary_key=True, default=_uuid)

    # Soft FK to learned_preference.id — no CASCADE
    preference_id   = Column(String(36), nullable=False)

    # Soft FK to user_signal_event.id — no CASCADE
    signal_event_id = Column(String(36), nullable=False)

    # contribution: decay-scaled impact on affinity
    contribution = Column(Float, nullable=False, default=0.0)

    # source: mirrors the learning source category (§3 of spec)
    source = Column(String(30), nullable=False, default="")

    observed_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_pe_preference_id",   "preference_id"),
        Index("ix_pe_signal_event_id", "signal_event_id"),
        Index("ix_pe_observed_at",     "observed_at"),
    )


class RelevanceAdjustmentLog(Base):
    """Append-only shadow journal of relevance adjustments — table 53.

    The Phase 15 analogue of scenario_run_log. Insert-only; run_reason=shadow
    until Stage 5 sign-off.

    intrinsic_rank: truth-order position (read-only input from truth layer)
    adjusted_rank:  the rank personalization would assign
    prominence_tier: pinned | normal | muted  (NEVER hidden — SP-7d)
    floor_applied:   True when the relevance floor clamped this item

    Both ranks are persisted so shadow validation can confirm no safety-critical
    item was pushed below its floor. The item's underlying score is NOT stored
    here — Phase 15 never has it to write.
    """

    __tablename__ = "relevance_adjustment_log"

    id      = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), nullable=False)

    # surface: feed | alert_digest | watchlist
    surface = Column(String(40), nullable=False, default="")

    # run_reason: shadow | delivery  (shadow until Stage 5 sign-off)
    run_reason = Column(String(15), nullable=False, default="shadow")

    # item_ref: the truth item being repositioned
    item_ref = Column(String(200), nullable=False, default="")

    # intrinsic_rank: truth-order position — read-only input, never modified
    intrinsic_rank = Column(Integer, nullable=False, default=0)

    # adjusted_rank: the rank personalization would assign
    adjusted_rank = Column(Integer, nullable=False, default=0)

    # relevance_weight: bounded ± W_MAX applied weight
    relevance_weight = Column(Float, nullable=False, default=0.0)

    # prominence_tier: pinned | normal | muted  (NEVER hidden — SP-7d)
    prominence_tier = Column(String(10), nullable=False, default="normal")

    # floor_applied: True when the relevance floor clamped this item (SP-7d)
    floor_applied = Column(Boolean, nullable=False, default=False)

    evaluated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_ral_user_id",    "user_id"),
        Index("ix_ral_user_surface","user_id", "surface"),
        Index("ix_ral_run_reason", "run_reason"),
        Index("ix_ral_evaluated_at","evaluated_at"),
        Index("ix_ral_item_ref",   "item_ref"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Phase 18 — Personal Experience Layer  (tables 54–56)
# ═══════════════════════════════════════════════════════════════════════════


class PersonalExperienceCursor(Base):
    """User view state per entity — Phase 18 · table 54.

    Upsert keyed on (user_id, entity_type, entity_key). Tracks when the user
    last saw an entity and what the entity state looked like at that time.
    Enables novelty scoring and revisit detection.

    Phase 18 never writes to any truth table. This cursor is the only
    mutable Phase 18 table (view_count increments, last_seen_at updates).
    """

    __tablename__ = "personal_experience_cursor"

    id         = Column(String(36), primary_key=True, default=_uuid)
    user_id    = Column(String(36), nullable=False)

    entity_type     = Column(String(30), nullable=False, default="")
    entity_key      = Column(String(64), nullable=False, default="")

    last_seen_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_state_hash = Column(String(64), nullable=False, default="")
    view_count      = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_key",
                         name="uq_pec_user_entity"),
        Index("ix_pec_user_id",          "user_id"),
        Index("ix_pec_user_entity_type", "user_id", "entity_type"),
        Index("ix_pec_last_seen_at",     "last_seen_at"),
    )


class PersonalExperienceEvent(Base):
    """Append-only surfacing log — Phase 18 · table 55.

    INSERT-ONLY. Records what was surfaced (or blocked) and all 7 scoring
    dimensions at the time of surfacing. run_reason=shadow until Stage 5
    sign-off.

    explanation_valid=False marks items that failed the explainability gate
    (blocked from surfacing but still logged for calibration).

    Phase 18 never writes to any truth table. This event log is one of only
    two Phase 18 write targets (the other is personal_experience_cursor).
    """

    __tablename__ = "personal_experience_event"

    id      = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), nullable=False)

    surface     = Column(String(30), nullable=False, default="")
    item_ref    = Column(String(128), nullable=False, default="")
    entity_type = Column(String(30), nullable=False, default="")
    entity_key  = Column(String(64), nullable=False, default="")

    experience_score    = Column(Float, nullable=False, default=0.0)
    attention_priority  = Column(Float, nullable=False, default=0.0)
    personal_relevance  = Column(Float, nullable=False, default=0.0)
    recency_score       = Column(Float, nullable=False, default=0.0)
    novelty_score       = Column(Float, nullable=False, default=0.0)
    revisit_score       = Column(Float, nullable=False, default=0.0)
    memory_relevance    = Column(Float, nullable=False, default=0.0)
    portfolio_relevance = Column(Float, nullable=False, default=0.0)

    explanation_text  = Column(Text, nullable=False, default="")
    explanation_valid = Column(Boolean, nullable=False, default=False)

    run_reason  = Column(String(15), nullable=False, default="shadow")
    surfaced_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_pee_user_id",      "user_id"),
        Index("ix_pee_user_surface", "user_id", "surface"),
        Index("ix_pee_run_reason",   "run_reason"),
        Index("ix_pee_surfaced_at",  "surfaced_at"),
        Index("ix_pee_item_ref",     "item_ref"),
    )


class PersonalBriefSnapshot(Base):
    """Daily brief metadata — Phase 18 · table 56.

    One brief per user per day. Upsert keyed on (user_id, brief_date).
    run_reason=shadow until Stage 5 sign-off.

    Phase 18 never writes to any truth table.
    """

    __tablename__ = "personal_brief_snapshot"

    id      = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), nullable=False)

    brief_date         = Column(Date, nullable=False)
    brief_schema       = Column(Integer, nullable=False, default=1)
    items_surfaced     = Column(Integer, nullable=False, default=0)
    items_blocked      = Column(Integer, nullable=False, default=0)
    top_attention_item = Column(String(128), nullable=False, default="")
    run_reason         = Column(String(15), nullable=False, default="shadow")
    generated_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    created_at         = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("user_id", "brief_date",
                         name="uq_pbs_user_brief_date"),
        Index("ix_pbs_user_id",         "user_id"),
        Index("ix_pbs_user_brief_date", "user_id", "brief_date"),
        Index("ix_pbs_run_reason",      "run_reason"),
    )
