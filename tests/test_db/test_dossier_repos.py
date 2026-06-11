"""
Phase 9G · Phase 0 — Company Dossier repository tests.

All 9 repository modules exercised against an in-memory SQLite session
via the shared db_session fixture from conftest.py.

Coverage targets per task spec:
  * get_or_create head (idempotency)
  * upsert debate (create, update, optimistic-concurrency conflict)
  * upsert moat dimension (create, update, axis uniqueness, pending_flip toggle)
  * append / transition catalyst (lifecycle state machine)
  * write variant (JSON round-trip, optimistic conflict)
  * write durability (overwrite semantics, nullable signals)
  * upsert failure mode (create, stage advance, unique pair)
  * append revision (immutable — no update path exposed)
  * append / query evidence refs
  * session=None null-object for each public function
  * get_full_dossier assembles all facets in one call
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# HEAD — get_or_create / upsert_head / get_head
# ===========================================================================

@pytest.mark.asyncio
async def test_get_or_create_head_creates_on_first_call(db_session):
    """First call creates a head row; second call returns the same row."""
    from app.db.repositories.dossier_repo import get_or_create_head, get_head

    row = await get_or_create_head(db_session, "NVDA", company_name="NVIDIA", session_id="s1")
    assert row is not None
    assert row.ticker == "NVDA"
    assert row.company_name == "NVIDIA"
    assert row.row_version == 0  # fresh default

    row2 = await get_or_create_head(db_session, "NVDA", company_name="NVIDIA", session_id="s1")
    assert row2.id == row.id  # same row returned


@pytest.mark.asyncio
async def test_get_or_create_head_normalises_ticker(db_session):
    """Lowercase input is normalised to uppercase."""
    from app.db.repositories.dossier_repo import get_or_create_head

    row = await get_or_create_head(db_session, "nvda", session_id="s1")
    assert row.ticker == "NVDA"


@pytest.mark.asyncio
async def test_upsert_head_creates_and_updates(db_session):
    """upsert_head creates the row then updates it on second call."""
    from app.db.repositories.dossier_repo import upsert_head, get_head

    row = await upsert_head(
        db_session, "AAPL",
        company_name="Apple Inc.", stance="bullish", conviction=0.72,
        global_confidence=0.68, session_id="s1",
    )
    assert row is not None
    assert row.stance == "bullish"
    assert abs(row.conviction - 0.72) < 0.001
    assert row.row_version == 0  # first write creates with row_version=0

    # Second upsert bumps row_version
    row2 = await upsert_head(
        db_session, "AAPL",
        stance="neutral", conviction=0.55, session_id="s2",
    )
    assert row2.stance == "neutral"
    assert row2.row_version == 1  # bumped on update

    fetched = await get_head(db_session, "AAPL")
    assert fetched.row_version == 1


@pytest.mark.asyncio
async def test_get_head_returns_none_for_unknown_ticker(db_session):
    from app.db.repositories.dossier_repo import get_head
    assert await get_head(db_session, "ZZZZZ") is None


@pytest.mark.asyncio
async def test_head_null_session():
    """session=None → None without raising."""
    from app.db.repositories.dossier_repo import get_head, get_or_create_head, upsert_head
    assert await get_head(None, "NVDA") is None
    assert await get_or_create_head(None, "NVDA") is None
    assert await upsert_head(None, "NVDA", session_id="s") is None


# ===========================================================================
# DEBATE — write_debate / get_debate / update_debate_lean
# ===========================================================================

@pytest.mark.asyncio
async def test_write_debate_creates_and_updates(db_session):
    from app.db.repositories.dossier_repo import write_debate, get_debate

    row = await write_debate(
        db_session, "NVDA",
        question="Is Blackwell capex-cycle sustainable?",
        bull_pole="Sovereign AI underpins demand through 2027.",
        bear_pole="Hyperscaler digestion begins H2 2025.",
        current_lean="bull", resolution_signal="3 qtrs >20% YoY DC growth.",
        version=1, confidence=0.71, session_id="s1",
    )
    assert row is not None
    assert row.version == 1
    assert row.current_lean == "bull"

    # Update to version 2 without expect_version check
    row2 = await write_debate(
        db_session, "NVDA",
        question="Is Blackwell capex-cycle sustainable?",
        bull_pole="Sovereign AI underpins demand through 2027.",
        bear_pole="Digestion accelerating — MI300X share gaining.",
        current_lean="bear", resolution_signal="DC revenue <$25B",
        version=2, confidence=0.75, session_id="s2",
    )
    assert row2.version == 2
    assert row2.current_lean == "bear"

    fetched = await get_debate(db_session, "NVDA")
    assert fetched.version == 2


@pytest.mark.asyncio
async def test_write_debate_optimistic_conflict(db_session):
    """expect_version mismatch → returns None (caller must re-read)."""
    from app.db.repositories.dossier_repo import write_debate

    await write_debate(db_session, "MSFT", version=1, session_id="s1")

    # expect_version=0 but current is 1 → conflict
    result = await write_debate(
        db_session, "MSFT",
        version=2, session_id="s2", expect_version=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_write_debate_expect_version_match(db_session):
    """expect_version matching current → write succeeds."""
    from app.db.repositories.dossier_repo import write_debate

    await write_debate(db_session, "JPM", version=1, session_id="s1")

    result = await write_debate(
        db_session, "JPM",
        version=2, session_id="s2", expect_version=1,
    )
    assert result is not None
    assert result.version == 2


@pytest.mark.asyncio
async def test_update_debate_lean(db_session):
    """Non-versioning lean update does not change version."""
    from app.db.repositories.dossier_repo import write_debate, update_debate_lean, get_debate

    await write_debate(db_session, "GS", current_lean="balanced", version=1, session_id="s")
    await update_debate_lean(db_session, "GS", lean="bear", session_id="s2")

    row = await get_debate(db_session, "GS")
    assert row.current_lean == "bear"
    assert row.version == 1  # version must not change


@pytest.mark.asyncio
async def test_update_debate_lean_noop_when_no_row(db_session):
    """update_debate_lean returns None gracefully when no debate row exists."""
    from app.db.repositories.dossier_repo import update_debate_lean
    result = await update_debate_lean(db_session, "UNKNOWN", lean="bull")
    assert result is None


@pytest.mark.asyncio
async def test_debate_null_session():
    from app.db.repositories.dossier_repo import get_debate, write_debate, update_debate_lean
    assert await get_debate(None, "NVDA") is None
    assert await write_debate(None, "NVDA", version=1, session_id="s") is None
    assert await update_debate_lean(None, "NVDA", lean="bull") is None


# ===========================================================================
# MOAT — upsert_dimension / set_pending_flip / get_dimensions
# ===========================================================================

@pytest.mark.asyncio
async def test_upsert_dimension_creates_multiple_axes(db_session):
    """Multiple axes per ticker are stored independently."""
    from app.db.repositories.dossier_repo import upsert_dimension, get_dimensions

    axes = ["ecosystem_lockin", "switching_costs", "supply_chain_control"]
    for axis in axes:
        await upsert_dimension(
            db_session, "NVDA", axis,
            strength="strong", trend="stable", version=1, confidence=0.7,
            session_id="s",
        )
    rows = await get_dimensions(db_session, "NVDA")
    assert len(rows) == 3
    stored_axes = {r.axis for r in rows}
    assert stored_axes == set(axes)


@pytest.mark.asyncio
async def test_upsert_dimension_updates_in_place(db_session):
    """Second upsert of same axis updates the row, not inserts a new one."""
    from app.db.repositories.dossier_repo import upsert_dimension, get_dimensions

    await upsert_dimension(db_session, "AAPL", "ecosystem_lockin",
                           strength="strong", trend="stable", version=1, session_id="s")
    await upsert_dimension(db_session, "AAPL", "ecosystem_lockin",
                           strength="moderate", trend="weakening", version=2, session_id="s2")

    rows = await get_dimensions(db_session, "AAPL")
    assert len(rows) == 1  # still one row
    assert rows[0].strength == "moderate"
    assert rows[0].trend == "weakening"
    assert rows[0].version == 2


@pytest.mark.asyncio
async def test_upsert_dimension_optimistic_conflict(db_session):
    """expect_version mismatch on moat upsert → returns None."""
    from app.db.repositories.dossier_repo import upsert_dimension

    await upsert_dimension(db_session, "TSLA", "network_effects",
                           version=1, session_id="s")
    result = await upsert_dimension(db_session, "TSLA", "network_effects",
                                    version=2, session_id="s2", expect_version=0)
    assert result is None


@pytest.mark.asyncio
async def test_set_pending_flip_toggle(db_session):
    """pending_flip toggles without bumping version."""
    from app.db.repositories.dossier_repo import upsert_dimension, set_pending_flip, get_dimensions

    await upsert_dimension(db_session, "NVDA", "supply_chain_control",
                           pending_flip=False, version=1, session_id="s")
    await set_pending_flip(db_session, "NVDA", "supply_chain_control", True, session_id="s2")

    rows = await get_dimensions(db_session, "NVDA")
    assert rows[0].pending_flip is True
    assert rows[0].version == 1  # version unchanged

    await set_pending_flip(db_session, "NVDA", "supply_chain_control", False, session_id="s3")
    rows = await get_dimensions(db_session, "NVDA")
    assert rows[0].pending_flip is False


@pytest.mark.asyncio
async def test_set_pending_flip_noop_unknown_axis(db_session):
    from app.db.repositories.dossier_repo import set_pending_flip
    result = await set_pending_flip(db_session, "NVDA", "nonexistent_axis", True)
    assert result is None


@pytest.mark.asyncio
async def test_moat_null_session():
    from app.db.repositories.dossier_repo import get_dimensions, upsert_dimension, set_pending_flip
    assert await get_dimensions(None, "NVDA") == []
    assert await upsert_dimension(None, "NVDA", "axis", session_id="s") is None
    assert await set_pending_flip(None, "NVDA", "axis", True) is None


# ===========================================================================
# CATALYST — append_catalyst / transition_catalyst / list_catalysts
# ===========================================================================

@pytest.mark.asyncio
async def test_append_catalyst_and_list(db_session):
    """Multiple catalysts can be appended and listed."""
    from app.db.repositories.dossier_repo import append_catalyst, list_catalysts

    c1 = await append_catalyst(
        db_session, "NVDA",
        statement="DC revenue exceeds $28B", direction="bull_trigger",
        specificity=0.82, expected_window="Q1-2026", conviction_weight=0.75,
        session_id="s",
    )
    c2 = await append_catalyst(
        db_session, "NVDA",
        statement="BIS H20 restriction expanded", direction="bear_trigger",
        specificity=0.90, expected_window="H1-2026", conviction_weight=0.80,
        session_id="s",
    )
    assert c1 is not None
    assert c2 is not None
    assert c1.id != c2.id

    all_cats = await list_catalysts(db_session, "NVDA")
    assert len(all_cats) == 2

    open_cats = await list_catalysts(db_session, "NVDA", status="open")
    assert len(open_cats) == 2


@pytest.mark.asyncio
async def test_catalyst_lifecycle_transitions(db_session):
    """open → triggered and open → invalidated are valid transitions."""
    from app.db.repositories.dossier_repo import append_catalyst, transition_catalyst, list_catalysts

    c1 = await append_catalyst(db_session, "NVDA", statement="Bull trigger",
                                direction="bull_trigger", session_id="s")
    c2 = await append_catalyst(db_session, "NVDA", statement="Bear trigger",
                                direction="bear_trigger", session_id="s")

    t1 = await transition_catalyst(db_session, c1.id, "triggered", session_id="s2")
    assert t1 is not None
    assert t1.status == "triggered"
    assert t1.resolved_at is not None

    t2 = await transition_catalyst(db_session, c2.id, "invalidated", session_id="s2")
    assert t2 is not None
    assert t2.status == "invalidated"

    # Only open remain in open filter
    open_cats = await list_catalysts(db_session, "NVDA", status="open")
    assert len(open_cats) == 0


@pytest.mark.asyncio
async def test_catalyst_invalid_transition_rejected(db_session):
    """triggered → open is not a valid transition; returns None."""
    from app.db.repositories.dossier_repo import append_catalyst, transition_catalyst

    cat = await append_catalyst(db_session, "JPM", statement="Rate hike",
                                 direction="bear_trigger", session_id="s")
    await transition_catalyst(db_session, cat.id, "triggered", session_id="s")

    # triggered → open is not in _VALID_TRANSITIONS["triggered"]
    result = await transition_catalyst(db_session, cat.id, "open", session_id="s")
    assert result is None


@pytest.mark.asyncio
async def test_catalyst_transition_unknown_id(db_session):
    from app.db.repositories.dossier_repo import transition_catalyst
    result = await transition_catalyst(db_session, _id(), "triggered")
    assert result is None


@pytest.mark.asyncio
async def test_catalyst_null_session():
    from app.db.repositories.dossier_repo import list_catalysts, append_catalyst, transition_catalyst
    assert await list_catalysts(None, "NVDA") == []
    assert await append_catalyst(None, "NVDA", statement="x", session_id="s") is None
    assert await transition_catalyst(None, _id(), "triggered") is None


# ===========================================================================
# VARIANT — write_variant / get_variant
# ===========================================================================

@pytest.mark.asyncio
async def test_write_variant_roundtrip(db_session):
    """Divergences JSON list survives a write/read round-trip."""
    from app.db.repositories.dossier_repo import write_variant, get_variant

    divs = [
        {"dimension": "competitive_risk", "direction": "more_bearish", "conviction": 0.68},
        {"dimension": "valuation", "direction": "more_bearish", "conviction": 0.55},
    ]
    row = await write_variant(db_session, "NVDA", divergences=divs,
                               version=1, confidence=0.62, session_id="s")
    assert row is not None
    assert isinstance(row.divergences, list)
    assert len(row.divergences) == 2

    fetched = await get_variant(db_session, "NVDA")
    assert fetched.divergences[0]["direction"] == "more_bearish"


@pytest.mark.asyncio
async def test_write_variant_update(db_session):
    """Second write replaces divergences and bumps version."""
    from app.db.repositories.dossier_repo import write_variant, get_variant

    await write_variant(db_session, "AAPL", divergences=[], version=1, session_id="s")
    new_divs = [{"dimension": "regulatory", "direction": "more_bearish", "conviction": 0.60}]
    await write_variant(db_session, "AAPL", divergences=new_divs, version=2, session_id="s2")

    fetched = await get_variant(db_session, "AAPL")
    assert fetched.version == 2
    assert len(fetched.divergences) == 1


@pytest.mark.asyncio
async def test_write_variant_optimistic_conflict(db_session):
    """Stale expect_version on variant write → None."""
    from app.db.repositories.dossier_repo import write_variant

    await write_variant(db_session, "META", divergences=[], version=1, session_id="s")
    result = await write_variant(db_session, "META", divergences=[], version=2,
                                  session_id="s", expect_version=0)
    assert result is None


@pytest.mark.asyncio
async def test_variant_null_session():
    from app.db.repositories.dossier_repo import get_variant, write_variant
    assert await get_variant(None, "NVDA") is None
    assert await write_variant(None, "NVDA", divergences=[], session_id="s") is None


# ===========================================================================
# DURABILITY — write_durability / get_durability
# ===========================================================================

@pytest.mark.asyncio
async def test_write_durability_creates_and_overwrites(db_session):
    """Durability signals are overwritten on each write (no versioning)."""
    from app.db.repositories.dossier_repo import write_durability, get_durability

    row = await write_durability(
        db_session, "NVDA",
        cycle_position="mid", catalyst_proximity_days=45,
        analog_time_to_trough_days=570,
        conviction_trend="stable", horizon_hint="investment", session_id="s",
    )
    assert row is not None
    assert row.cycle_position == "mid"
    assert row.catalyst_proximity_days == 45

    # Overwrite
    row2 = await write_durability(
        db_session, "NVDA",
        cycle_position="late", catalyst_proximity_days=None,
        analog_time_to_trough_days=None,
        conviction_trend="falling", horizon_hint="trade", session_id="s2",
    )
    assert row2.cycle_position == "late"
    assert row2.catalyst_proximity_days is None

    fetched = await get_durability(db_session, "NVDA")
    assert fetched.cycle_position == "late"
    assert fetched.conviction_trend == "falling"


@pytest.mark.asyncio
async def test_write_durability_nullable_signals(db_session):
    """Both integer signal columns can be NULL without error."""
    from app.db.repositories.dossier_repo import write_durability

    row = await write_durability(
        db_session, "COST",
        cycle_position="unknown", session_id="s",
    )
    assert row is not None
    assert row.catalyst_proximity_days is None
    assert row.analog_time_to_trough_days is None


@pytest.mark.asyncio
async def test_durability_null_session():
    from app.db.repositories.dossier_repo import get_durability, write_durability
    assert await get_durability(None, "NVDA") is None
    assert await write_durability(None, "NVDA", session_id="s") is None


# ===========================================================================
# FAILURE MODE — upsert_failure_mode / list_failure_modes
# ===========================================================================

@pytest.mark.asyncio
async def test_upsert_failure_mode_creates_and_advances_stage(db_session):
    """Second upsert with same analog_id updates stage in place."""
    from app.db.repositories.dossier_repo import upsert_failure_mode, list_failure_modes

    analog_id = _id()
    row = await upsert_failure_mode(
        db_session, "NVDA", analog_id,
        sequence_stage=1,
        stage_evidence="Architecture dismissal pattern in management commentary.",
        relevance_at_match=0.52, session_id="s",
    )
    assert row is not None
    assert row.sequence_stage == 1

    # Stage advance
    row2 = await upsert_failure_mode(
        db_session, "NVDA", analog_id,
        sequence_stage=2,
        stage_evidence="Revenue deceleration matches Stage 2 of Intel 2019 sequence.",
        relevance_at_match=0.61, session_id="s2",
    )
    assert row2.sequence_stage == 2

    modes = await list_failure_modes(db_session, "NVDA")
    assert len(modes) == 1  # still one row (upserted, not duplicated)
    assert modes[0].sequence_stage == 2


@pytest.mark.asyncio
async def test_upsert_failure_mode_multiple_analogs(db_session):
    """Multiple analog_ids are stored as separate rows per ticker."""
    from app.db.repositories.dossier_repo import upsert_failure_mode, list_failure_modes

    for _ in range(3):
        await upsert_failure_mode(
            db_session, "NVDA", _id(),
            sequence_stage=1, session_id="s",
        )
    modes = await list_failure_modes(db_session, "NVDA")
    assert len(modes) == 3


@pytest.mark.asyncio
async def test_failure_mode_null_session():
    from app.db.repositories.dossier_repo import list_failure_modes, upsert_failure_mode
    assert await list_failure_modes(None, "NVDA") == []
    assert await upsert_failure_mode(None, "NVDA", _id(), session_id="s") is None


# ===========================================================================
# REVISION — append / get_timeline  (append-only: no update/delete exposed)
# ===========================================================================

@pytest.mark.asyncio
async def test_append_revision_creates_rows(db_session):
    """Multiple revisions for same ticker/facet are all stored."""
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline

    vid = _id()
    await append_revision(db_session, "NVDA", "core_debate",
                           prev_version=None, new_version=1,
                           change_summary="Initial debate captured.",
                           diff_json={"created": True}, confidence=0.72,
                           source_version_id=vid, session_id="s1")
    await append_revision(db_session, "NVDA", "moat_dimension",
                           prev_version=1, new_version=2,
                           change_summary="Ecosystem axis weakening.",
                           diff_json={"trend": "weakening"}, confidence=0.68,
                           source_version_id=vid, session_id="s2")
    await append_revision(db_session, "NVDA", "catalyst",
                           prev_version=None, new_version=1,
                           change_summary="New catalyst added.",
                           diff_json={}, confidence=0.61,
                           session_id="s3")

    all_revs = await get_timeline(db_session, "NVDA")
    assert len(all_revs) == 3

    debate_revs = await get_timeline(db_session, "NVDA", facet="core_debate")
    assert len(debate_revs) == 1
    assert debate_revs[0]["change_summary"] == "Initial debate captured."


@pytest.mark.asyncio
async def test_append_revision_diff_json_roundtrip(db_session):
    """diff_json is returned as a dict (not a string)."""
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline

    diff = {"before": {"lean": "balanced"}, "after": {"lean": "bear"}}
    await append_revision(db_session, "AAPL", "core_debate",
                           prev_version=1, new_version=2,
                           change_summary="Lean flipped.", diff_json=diff,
                           confidence=0.76, session_id="s")

    timeline = await get_timeline(db_session, "AAPL", facet="core_debate")
    assert isinstance(timeline[0]["diff_json"], dict)
    assert timeline[0]["diff_json"]["after"]["lean"] == "bear"


@pytest.mark.asyncio
async def test_append_revision_first_create_null_prev_version(db_session):
    """First-create revision rows have prev_version=None."""
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline

    await append_revision(db_session, "TSLA", "head",
                           prev_version=None, new_version=1,
                           change_summary="Head created.", diff_json={},
                           session_id="s")
    timeline = await get_timeline(db_session, "TSLA")
    assert timeline[0]["prev_version"] is None


@pytest.mark.asyncio
async def test_get_timeline_limit(db_session):
    """get_timeline respects the limit parameter."""
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline

    for i in range(1, 6):
        await append_revision(db_session, "GS", "catalyst",
                               prev_version=i - 1 if i > 1 else None,
                               new_version=i, diff_json={}, session_id="s")

    limited = await get_timeline(db_session, "GS", limit=3)
    assert len(limited) == 3


@pytest.mark.asyncio
async def test_revision_null_session():
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline
    assert await append_revision(None, "NVDA", "head", new_version=1, session_id="s") is None
    assert await get_timeline(None, "NVDA") == []


# ===========================================================================
# EVIDENCE REFS — append / get_evidence_refs
# ===========================================================================

@pytest.mark.asyncio
async def test_append_and_get_evidence_refs(db_session):
    """Evidence refs are stored and queryable by ticker and facet."""
    from app.db.repositories.dossier_revision_repo import append_evidence_ref, get_evidence_refs

    source_id = _id()
    await append_evidence_ref(db_session, "NVDA", "core_debate", "hash_abc123",
                               source_type="thesis_version", source_id=source_id,
                               session_id="s")
    await append_evidence_ref(db_session, "NVDA", "moat_dimension", "hash_def456",
                               source_type="analog", source_id=_id(), session_id="s")
    await append_evidence_ref(db_session, "NVDA", "catalyst", "hash_ghi789",
                               source_type="inferred", source_id=None, session_id="s")

    all_refs = await get_evidence_refs(db_session, "NVDA")
    assert len(all_refs) == 3

    debate_refs = await get_evidence_refs(db_session, "NVDA", facet="core_debate")
    assert len(debate_refs) == 1
    assert debate_refs[0].source_type == "thesis_version"
    assert debate_refs[0].source_id == source_id


@pytest.mark.asyncio
async def test_evidence_ref_inferred_has_null_source_id(db_session):
    """Inferred claims have source_id=None."""
    from app.db.repositories.dossier_revision_repo import append_evidence_ref, get_evidence_refs

    await append_evidence_ref(db_session, "COST", "head", "hash_inf",
                               source_type="inferred", source_id=None, session_id="s")
    refs = await get_evidence_refs(db_session, "COST")
    assert refs[0].source_id is None
    assert refs[0].source_type == "inferred"


@pytest.mark.asyncio
async def test_evidence_ref_null_session():
    from app.db.repositories.dossier_revision_repo import append_evidence_ref, get_evidence_refs
    assert await append_evidence_ref(None, "NVDA", "head", "hash", session_id="s") is None
    assert await get_evidence_refs(None, "NVDA") == []


# ===========================================================================
# GET FULL DOSSIER
# ===========================================================================

@pytest.mark.asyncio
async def test_get_full_dossier_empty_ticker_returns_defaults(db_session):
    """get_full_dossier returns the empty default shape for unknown tickers."""
    from app.db.repositories.dossier_repo import get_full_dossier

    dossier = await get_full_dossier(db_session, "ZZZZZ")
    assert dossier["head"] is None
    assert dossier["debate"] is None
    assert dossier["dimensions"] == []
    assert dossier["catalysts"] == []
    assert dossier["variant"] is None
    assert dossier["durability"] is None
    assert dossier["failure_modes"] == []


@pytest.mark.asyncio
async def test_get_full_dossier_assembles_all_facets(db_session):
    """get_full_dossier returns populated dicts for a ticker with all facets."""
    from app.db.repositories.dossier_repo import (
        upsert_head, write_debate, upsert_dimension, append_catalyst,
        write_variant, write_durability, upsert_failure_mode, get_full_dossier,
    )

    ticker = "NVDA"
    await upsert_head(db_session, ticker, stance="bullish", session_id="s")
    await write_debate(db_session, ticker, question="Q?", version=1, session_id="s")
    await upsert_dimension(db_session, ticker, "ecosystem_lockin",
                           strength="strong", version=1, session_id="s")
    await upsert_dimension(db_session, ticker, "switching_costs",
                           strength="moderate", version=1, session_id="s")
    await append_catalyst(db_session, ticker, statement="Catalyst A",
                           direction="bull_trigger", session_id="s")
    await write_variant(db_session, ticker, divergences=[], version=1, session_id="s")
    await write_durability(db_session, ticker, cycle_position="mid", session_id="s")
    await upsert_failure_mode(db_session, ticker, _id(), sequence_stage=1, session_id="s")

    dossier = await get_full_dossier(db_session, ticker)
    assert dossier["head"].ticker == ticker
    assert dossier["head"].stance == "bullish"
    assert dossier["debate"].question == "Q?"
    assert len(dossier["dimensions"]) == 2
    assert len(dossier["catalysts"]) == 1
    assert dossier["variant"] is not None
    assert dossier["durability"].cycle_position == "mid"
    assert len(dossier["failure_modes"]) == 1


@pytest.mark.asyncio
async def test_get_full_dossier_null_session():
    from app.db.repositories.dossier_repo import get_full_dossier
    result = await get_full_dossier(None, "NVDA")
    assert result == {
        "head": None, "debate": None, "dimensions": [],
        "catalysts": [], "variant": None, "durability": None, "failure_modes": [],
    }


# ===========================================================================
# TRANSACTION ROLLBACK SAFETY
# ===========================================================================

@pytest.mark.asyncio
async def test_rollback_does_not_persist_partial_writes(db_session):
    """After explicit rollback, partially-written rows are not queryable."""
    from app.db.repositories.dossier_repo import upsert_head, get_head

    await upsert_head(db_session, "BAC", stance="bullish", session_id="s")
    # Explicitly rollback before commit — simulate a mid-transaction failure
    await db_session.rollback()

    # The head row written before rollback should not exist
    fetched = await get_head(db_session, "BAC")
    assert fetched is None


@pytest.mark.asyncio
async def test_revision_append_is_atomic_within_flush(db_session):
    """Multiple revision rows appended in one flush are all visible or none."""
    from app.db.repositories.dossier_revision_repo import append_revision, get_timeline

    # Write two revisions, then check both are visible
    await append_revision(db_session, "WMT", "head",
                           prev_version=None, new_version=1,
                           diff_json={}, session_id="s")
    await append_revision(db_session, "WMT", "catalyst",
                           prev_version=None, new_version=1,
                           diff_json={}, session_id="s")

    timeline = await get_timeline(db_session, "WMT")
    assert len(timeline) == 2


# ===========================================================================
# TICKER NORMALISATION EDGE CASES
# ===========================================================================

@pytest.mark.asyncio
async def test_ticker_normalised_consistently(db_session):
    """Lowercase and mixed-case tickers map to the same canonical row."""
    from app.db.repositories.dossier_repo import get_or_create_head

    row1 = await get_or_create_head(db_session, "nvda", session_id="s")
    row2 = await get_or_create_head(db_session, "Nvda", session_id="s")
    row3 = await get_or_create_head(db_session, "NVDA", session_id="s")

    # All three must resolve to the same DB row
    assert row1.id == row2.id == row3.id
    assert row1.ticker == "NVDA"
