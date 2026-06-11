"""
Phase 9G · Phase 0 — Company Dossier ORM model tests.

Validates that all 9 dossier tables:
  - can be created in an in-memory SQLite DB via Base.metadata.create_all
  - accept round-trip writes and reads
  - enforce their UNIQUE constraints
  - store JSON columns correctly

Uses the db_session fixture (SQLite in-memory) from conftest.py.
No extraction or injection logic is tested here — Slice 1 is schema only.
"""

from __future__ import annotations

import json
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


# ---------------------------------------------------------------------------
# 11. CompanyDossier (head)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_company_dossier_roundtrip(db_session):
    """Create a CompanyDossier head row and read it back."""
    from app.db.models import CompanyDossier
    from sqlalchemy import select

    row = CompanyDossier(
        id=_id(),
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        latest_version_id=_id(),
        stance="bullish",
        conviction=0.72,
        primary_concern="competitive_displacement",
        prior_as_of=_now(),
        schema_version=1,
        global_confidence=0.68,
        staleness_state="fresh",
        last_full_update_at=_now(),
        analysis_count=3,
        row_version=0,
        user_id=None,
        session_id="sess-001",
        created_at=_now(),
        updated_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(CompanyDossier).where(CompanyDossier.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.ticker == "NVDA"
    assert fetched.stance == "bullish"
    assert abs(fetched.conviction - 0.72) < 0.001
    assert fetched.analysis_count == 3
    assert fetched.row_version == 0
    assert fetched.staleness_state == "fresh"
    assert fetched.user_id is None


@pytest.mark.asyncio
async def test_company_dossier_unique_ticker(db_session):
    """Two CompanyDossier rows with the same ticker must raise IntegrityError."""
    from app.db.models import CompanyDossier

    kwargs = dict(company_name="X", session_id="s", created_at=_now(), updated_at=_now())
    db_session.add(CompanyDossier(id=_id(), ticker="AAPL", **kwargs))
    db_session.add(CompanyDossier(id=_id(), ticker="AAPL", **kwargs))  # duplicate
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# 12. DossierCoreDebate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_core_debate_roundtrip(db_session):
    """Create a DossierCoreDebate and verify all fields survive the trip."""
    from app.db.models import DossierCoreDebate
    from sqlalchemy import select

    row = DossierCoreDebate(
        id=_id(),
        ticker="NVDA",
        question="Is AI-infrastructure capex a multi-year structural build or a pull-forward?",
        bull_pole="Blackwell cycle drives sustained hyperscaler capex through 2027.",
        bear_pole="Hyperscaler digestion begins H2 2025; capex rationalises.",
        current_lean="bear",
        resolution_signal="Three consecutive quarters of >20% YoY datacenter revenue growth.",
        version=1,
        confidence=0.71,
        session_id="sess-001",
        first_seen_at=_now(),
        updated_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DossierCoreDebate).where(DossierCoreDebate.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.current_lean == "bear"
    assert fetched.version == 1
    assert abs(fetched.confidence - 0.71) < 0.001
    assert "pull-forward" in fetched.question


@pytest.mark.asyncio
async def test_dossier_core_debate_unique_ticker(db_session):
    """UNIQUE(ticker) on dossier_core_debate is enforced."""
    from app.db.models import DossierCoreDebate

    kwargs = dict(session_id="s", first_seen_at=_now(), updated_at=_now())
    db_session.add(DossierCoreDebate(id=_id(), ticker="MSFT", **kwargs))
    db_session.add(DossierCoreDebate(id=_id(), ticker="MSFT", **kwargs))  # duplicate
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# 13. DossierMoatDimension
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_moat_dimension_roundtrip(db_session):
    """Multiple axes per ticker; verify all fields and hysteresis state."""
    from app.db.models import DossierMoatDimension
    from sqlalchemy import select

    axes = [
        ("ecosystem_lockin", "strong",   "stable",     False),
        ("supply_chain_control", "moderate", "weakening", True),
        ("switching_costs", "strong",    "stable",     False),
    ]
    for axis, strength, trend, pending in axes:
        db_session.add(DossierMoatDimension(
            id=_id(), ticker="NVDA", axis=axis,
            strength=strength, trend=trend,
            rationale=f"{axis} rationale",
            vulnerability=f"{axis} vulnerability",
            version=1, confidence=0.65,
            pending_flip=pending,
            session_id="s", last_changed_at=_now(),
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(DossierMoatDimension).where(DossierMoatDimension.ticker == "NVDA")
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    pending_rows = [r for r in rows if r.pending_flip]
    assert len(pending_rows) == 1
    assert pending_rows[0].axis == "supply_chain_control"


@pytest.mark.asyncio
async def test_dossier_moat_unique_ticker_axis(db_session):
    """UNIQUE(ticker, axis) is enforced — two rows for same axis must fail."""
    from app.db.models import DossierMoatDimension

    kwargs = dict(session_id="s", last_changed_at=_now())
    db_session.add(DossierMoatDimension(
        id=_id(), ticker="AAPL", axis="ecosystem_lockin", **kwargs))
    db_session.add(DossierMoatDimension(
        id=_id(), ticker="AAPL", axis="ecosystem_lockin", **kwargs))  # duplicate axis
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_dossier_moat_different_tickers_same_axis(db_session):
    """Same axis on different tickers is allowed (not a constraint violation)."""
    from app.db.models import DossierMoatDimension

    kwargs = dict(axis="ecosystem_lockin", session_id="s", last_changed_at=_now())
    db_session.add(DossierMoatDimension(id=_id(), ticker="AAPL", **kwargs))
    db_session.add(DossierMoatDimension(id=_id(), ticker="MSFT", **kwargs))
    await db_session.flush()  # must not raise


# ---------------------------------------------------------------------------
# 14. DossierCatalyst
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_catalyst_roundtrip_and_lifecycle(db_session):
    """Multiple catalysts per ticker; test status field and resolved_at."""
    from app.db.models import DossierCatalyst
    from sqlalchemy import select

    cats = [
        ("DC revenue >$28B", "bull_trigger", "open",        None,   0.65, 0.9),
        ("BIS H20 expansion",  "bear_trigger", "triggered",  _now(), 0.55, 0.8),
        ("AMD MI300 share 20%", "bear_trigger", "invalidated", _now(), 0.60, 0.7),
    ]
    version_id = _id()
    for stmt, direction, status, resolved_at, spec, weight in cats:
        db_session.add(DossierCatalyst(
            id=_id(), ticker="NVDA",
            statement=stmt, direction=direction,
            specificity=spec, expected_window="Q1-2026",
            status=status, conviction_weight=weight,
            source_version_id=version_id,
            session_id="s",
            created_at=_now(), resolved_at=resolved_at,
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(DossierCatalyst).where(DossierCatalyst.ticker == "NVDA")
    )
    rows = result.scalars().all()
    assert len(rows) == 3

    open_rows = [r for r in rows if r.status == "open"]
    assert len(open_rows) == 1
    assert open_rows[0].resolved_at is None

    triggered = [r for r in rows if r.status == "triggered"]
    assert len(triggered) == 1
    assert triggered[0].resolved_at is not None


@pytest.mark.asyncio
async def test_dossier_catalyst_no_unique_constraint(db_session):
    """Multiple open catalysts for the same ticker are allowed."""
    from app.db.models import DossierCatalyst

    kwargs = dict(ticker="JPM", direction="bull_trigger", status="open",
                  session_id="s", created_at=_now())
    db_session.add(DossierCatalyst(
        id=_id(), statement="Loan growth accelerates", **kwargs))
    db_session.add(DossierCatalyst(
        id=_id(), statement="NIM expands on rate hold", **kwargs))
    await db_session.flush()  # must not raise — no unique constraint on catalysts


# ---------------------------------------------------------------------------
# 15. DossierVariant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_variant_roundtrip(db_session):
    """Divergences stored as JSON list survive the round-trip."""
    from app.db.models import DossierVariant
    from sqlalchemy import select

    divergences = [
        {
            "dimension": "competitive_risk",
            "consensus_view": "ecosystem lock-in is permanent",
            "clearsignal_view": "lock-in is cycle-dependent",
            "direction": "more_bearish",
            "conviction": 0.68,
        },
        {
            "dimension": "valuation",
            "consensus_view": "justified at 30x forward",
            "clearsignal_view": "multiple vulnerable if datacenter decelerates",
            "direction": "more_bearish",
            "conviction": 0.55,
        },
    ]
    row = DossierVariant(
        id=_id(), ticker="NVDA",
        divergences=divergences,
        version=1, confidence=0.62,
        session_id="s", updated_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DossierVariant).where(DossierVariant.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert isinstance(fetched.divergences, list)
    assert len(fetched.divergences) == 2
    assert fetched.divergences[0]["direction"] == "more_bearish"
    assert fetched.version == 1


# ---------------------------------------------------------------------------
# 16. DossierDurability
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_durability_roundtrip(db_session):
    """Raw durability signals stored and retrieved correctly."""
    from app.db.models import DossierDurability
    from sqlalchemy import select

    row = DossierDurability(
        id=_id(), ticker="NVDA",
        cycle_position="mid",
        catalyst_proximity_days=45,
        analog_time_to_trough_days=570,   # from Intel 2019 analog
        conviction_trend="stable",
        horizon_hint="investment",
        session_id="s", updated_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DossierDurability).where(DossierDurability.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.cycle_position == "mid"
    assert fetched.catalyst_proximity_days == 45
    assert fetched.analog_time_to_trough_days == 570
    assert fetched.horizon_hint == "investment"


@pytest.mark.asyncio
async def test_dossier_durability_nullable_signals(db_session):
    """Integer signals can be NULL (unknown) without violating the schema."""
    from app.db.models import DossierDurability

    row = DossierDurability(
        id=_id(), ticker="AAPL",
        cycle_position="unknown",
        catalyst_proximity_days=None,
        analog_time_to_trough_days=None,
        conviction_trend="rising",
        horizon_hint="investment",
        session_id="s", updated_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()  # must not raise


# ---------------------------------------------------------------------------
# 17. DossierFailureMode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_failure_mode_roundtrip(db_session):
    """Failure-mode match stored and read back with stage and evidence."""
    from app.db.models import DossierFailureMode
    from sqlalchemy import select

    analog_id = _id()
    row = DossierFailureMode(
        id=_id(), ticker="NVDA",
        analog_id=analog_id,
        sequence_stage=2,
        stage_evidence=(
            "Management commentary minimising AMD MI300X progress "
            "matches Stage 2 (architecture-dismissal) of Intel 2019 sequence."
        ),
        relevance_at_match=0.52,
        session_id="s", matched_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DossierFailureMode).where(DossierFailureMode.ticker == "NVDA")
    )
    fetched = result.scalar_one()
    assert fetched.analog_id == analog_id
    assert fetched.sequence_stage == 2
    assert abs(fetched.relevance_at_match - 0.52) < 0.001


@pytest.mark.asyncio
async def test_dossier_failure_mode_unique_ticker_analog(db_session):
    """UNIQUE(ticker, analog_id) prevents duplicate failure-mode entries."""
    from app.db.models import DossierFailureMode

    analog_id = _id()
    kwargs = dict(ticker="NVDA", analog_id=analog_id,
                  session_id="s", matched_at=_now())
    db_session.add(DossierFailureMode(id=_id(), **kwargs))
    db_session.add(DossierFailureMode(id=_id(), **kwargs))  # duplicate
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_dossier_failure_mode_multiple_analogs(db_session):
    """One ticker can match multiple analogs (different analog_ids allowed)."""
    from app.db.models import DossierFailureMode

    kwargs = dict(ticker="NVDA", session_id="s", matched_at=_now())
    db_session.add(DossierFailureMode(id=_id(), analog_id=_id(), **kwargs))
    db_session.add(DossierFailureMode(id=_id(), analog_id=_id(), **kwargs))
    await db_session.flush()  # must not raise


# ---------------------------------------------------------------------------
# 18. DossierRevision (append-only audit log)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_revision_append(db_session):
    """Multiple revision rows per ticker are allowed; ordered by created_at."""
    from app.db.models import DossierRevision
    from sqlalchemy import select
    import time

    version_id = _id()
    revisions = [
        ("core_debate",    None, 1, "Initial debate captured.",  0.72),
        ("moat_dimension", 1,    2, "Ecosystem axis weakening.", 0.68),
        ("catalyst",       None, 1, "New bull catalyst added.",  0.61),
    ]
    for facet, prev_v, new_v, summary, conf in revisions:
        db_session.add(DossierRevision(
            id=_id(), ticker="NVDA", facet=facet,
            prev_version=prev_v, new_version=new_v,
            change_summary=summary,
            diff_json={"facet": facet, "new_version": new_v},
            confidence=conf,
            source_version_id=version_id,
            session_id="s", created_at=_now(),
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(DossierRevision).where(DossierRevision.ticker == "NVDA")
    )
    rows = result.scalars().all()
    assert len(rows) == 3
    # first-create rows have NULL prev_version
    first_creates = [r for r in rows if r.prev_version is None]
    assert len(first_creates) == 2


@pytest.mark.asyncio
async def test_dossier_revision_diff_json_is_dict(db_session):
    """diff_json column persists a dict and returns a dict (not a string)."""
    from app.db.models import DossierRevision
    from sqlalchemy import select

    diff = {"before": {"current_lean": "balanced"}, "after": {"current_lean": "bear"}}
    row = DossierRevision(
        id=_id(), ticker="AAPL", facet="core_debate",
        prev_version=1, new_version=2,
        change_summary="Lean flipped to bear.",
        diff_json=diff,
        confidence=0.76,
        session_id="s", created_at=_now(),
    )
    db_session.add(row)
    await db_session.flush()

    result = await db_session.execute(
        select(DossierRevision).where(DossierRevision.ticker == "AAPL")
    )
    fetched = result.scalar_one()
    assert isinstance(fetched.diff_json, dict)
    assert fetched.diff_json["after"]["current_lean"] == "bear"


# ---------------------------------------------------------------------------
# 19. DossierEvidenceRef
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dossier_evidence_ref_roundtrip(db_session):
    """Evidence refs stored and queried by ticker + facet."""
    from app.db.models import DossierEvidenceRef
    from sqlalchemy import select

    source_id = _id()
    refs = [
        ("core_debate",    "abc123", "thesis_version", source_id),
        ("moat_dimension", "def456", "analog",         source_id),
        ("catalyst",       "ghi789", "inferred",       None),
    ]
    for facet, claim_hash, source_type, sid in refs:
        db_session.add(DossierEvidenceRef(
            id=_id(), ticker="NVDA",
            facet=facet, claim_hash=claim_hash,
            source_type=source_type, source_id=sid,
            session_id="s", as_of=_now(),
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(DossierEvidenceRef).where(DossierEvidenceRef.ticker == "NVDA")
    )
    rows = result.scalars().all()
    assert len(rows) == 3

    inferred = [r for r in rows if r.source_type == "inferred"]
    assert len(inferred) == 1
    assert inferred[0].source_id is None

    sourced = [r for r in rows if r.source_type != "inferred"]
    assert len(sourced) == 2
    for r in sourced:
        assert r.source_id is not None


# ---------------------------------------------------------------------------
# 20. Cross-table smoke test — all 9 dossier tables accept writes together
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_dossier_tables_exist(db_session):
    """Smoke: create one row in each of the 9 dossier tables without error."""
    from app.db.models import (
        CompanyDossier, DossierCoreDebate, DossierMoatDimension,
        DossierCatalyst, DossierVariant, DossierDurability,
        DossierFailureMode, DossierRevision, DossierEvidenceRef,
    )

    ticker = "GLD"
    now = _now()

    head = CompanyDossier(
        id=_id(), ticker=ticker, company_name="Gold ETF",
        session_id="smoke", created_at=now, updated_at=now,
    )
    debate = DossierCoreDebate(
        id=_id(), ticker=ticker,
        session_id="smoke", first_seen_at=now, updated_at=now,
    )
    moat = DossierMoatDimension(
        id=_id(), ticker=ticker, axis="ecosystem_lockin",
        session_id="smoke", last_changed_at=now,
    )
    catalyst = DossierCatalyst(
        id=_id(), ticker=ticker,
        statement="Fed rate cut", direction="bull_trigger",
        session_id="smoke", created_at=now,
    )
    variant = DossierVariant(
        id=_id(), ticker=ticker, divergences=[],
        session_id="smoke", updated_at=now,
    )
    durability = DossierDurability(
        id=_id(), ticker=ticker,
        session_id="smoke", updated_at=now,
    )
    failure = DossierFailureMode(
        id=_id(), ticker=ticker, analog_id=_id(),
        session_id="smoke", matched_at=now,
    )
    revision = DossierRevision(
        id=_id(), ticker=ticker, facet="head",
        new_version=1, diff_json={},
        session_id="smoke", created_at=now,
    )
    evidence = DossierEvidenceRef(
        id=_id(), ticker=ticker, facet="head",
        claim_hash="smoke_hash", source_type="inferred",
        session_id="smoke", as_of=now,
    )

    for obj in [head, debate, moat, catalyst, variant,
                durability, failure, revision, evidence]:
        db_session.add(obj)

    await db_session.flush()
    # If we reach here, all 9 dossier tables exist and accept writes.
