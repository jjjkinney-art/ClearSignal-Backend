"""
Tests — Decision Candidate Builder, Phase 13 · Slice 2.

Covers:
  1.  build_candidates returns [] when session is None (null-session safety)
  2.  build_candidates returns list when DB is empty (empty substrate)
  3.  Candidate envelope keys — all required keys present in every candidate
  4.  forecast_candidate — seeded forecast_vector produces a candidate
  5.  forecast_candidate — vector below signal floor (p_max < 0.5) is skipped
  6.  risk_candidate — seeded dossier_failure_mode produces a candidate
  7.  catalyst_candidate — open dossier_catalyst produces a candidate
  8.  catalyst_candidate — non-open catalyst (triggered) is excluded
  9.  watchlist_candidate — active watched_ticker produces a candidate
  10. watchlist_candidate — inactive watched_ticker is excluded
  11. portfolio_exposure_candidate — active position produces a candidate
  12. portfolio_exposure_candidate — inactive position is excluded
  13. delivery_transition_candidate — pending delivery_ledger row produces candidate
  14. delivery_transition_candidate — delivered row is excluded
  15. similarity_candidate — floor_passed edge produces a candidate
  16. targets filter — only matching ticker candidates returned
  17. tenant isolation — watchlist for user_id=A does not include user_id=B rows
  18. source_versions — populated on every candidate
  19. deterministic — same substrate returns same candidate count
  20. no DB writes — build_candidates makes no session.add() calls
  21. no decision_priority writes — no DecisionPriority rows after build_candidates
  22. ALL_CANDIDATE_TYPES completeness — 7 entries
  23. No forbidden imports — no conviction/recommendation/order/execution imports (AST)
  24. No advice language — no buy/sell/hold/recommend in string constants (AST)
  25. No source-table writes — no session.add or update() calls in module (AST)
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_candidate_builder.py"

# ---------------------------------------------------------------------------
# Required candidate envelope keys
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "candidate_type",
    "entity_type",
    "entity_id",
    "ticker",
    "source_type",
    "source_id",
    "headline",
    "summary",
    "evidence_refs",
    "urgency_inputs",
    "impact_inputs",
    "attention_inputs",
    "confidence_inputs",
    "uncertainty_inputs",
    "source_versions",
    "user_id",
}

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_forecast_vector(db, *, ticker="NVDA", p_pos=0.70, p_neg=0.20, p_neu=0.10,
                                 horizon="near_term", forecast_type="thesis_strengthening",
                                 user_id=None) -> object:
    from app.db.repositories import forecast_repo
    return await forecast_repo.upsert_forecast_vector(
        db,
        entity_type="company",
        entity_key=ticker,
        horizon=horizon,
        horizon_days=30,
        forecast_type=forecast_type,
        p_positive=p_pos,
        p_negative=p_neg,
        p_neutral=p_neu,
        confidence_band_low=0.55,
        confidence_band_high=0.85,
        why=f"{ticker} thesis strengthening signal",
        invalidators=["earnings miss", "regulatory change"],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={"company_dossier": "v1"},
        forecast_schema=1,
        user_id=user_id,
    )


async def _seed_failure_mode(db, *, ticker="NVDA", analog_id=None) -> object:
    analog_id = analog_id or _uid()
    from app.db.models import DossierFailureMode
    row = DossierFailureMode(
        id=_uid(),
        ticker=ticker,
        analog_id=analog_id,
        sequence_stage=2,
        stage_evidence="Stage 2 signals observed",
        relevance_at_match=0.75,
        matched_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_catalyst(db, *, ticker="NVDA", status="open", direction="bull_trigger") -> object:
    from app.db.models import DossierCatalyst
    row = DossierCatalyst(
        id=_uid(),
        ticker=ticker,
        statement=f"{ticker} Q3 earnings catalyst",
        direction=direction,
        specificity=0.80,
        expected_window="Q3 2026",
        status=status,
        conviction_weight=0.6,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_watchlist(db, *, ticker="NVDA", active=True, user_id=None) -> object:
    from app.db.models import WatchedTicker
    row = WatchedTicker(
        id=_uid(),
        user_id=user_id,
        ticker=ticker,
        company_name=f"{ticker} Corp",
        active=active,
        added_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_portfolio_and_position(db, *, ticker="NVDA", active=True,
                                        user_id=None, weight=0.15) -> tuple:
    from app.db.models import Portfolio, PortfolioPosition
    port = Portfolio(
        id=_uid(),
        user_id=user_id,
        name="Test Portfolio",
        is_default=False,
    )
    db.add(port)
    await db.flush()

    pos = PortfolioPosition(
        id=_uid(),
        portfolio_id=port.id,
        ticker=ticker,
        membership_class="owned",
        weight=weight,
        active=active,
    )
    db.add(pos)
    await db.flush()
    return port, pos


async def _seed_delivery(db, *, ticker="NVDA", status="pending") -> object:
    from app.db.models import DeliveryLedger
    row = DeliveryLedger(
        id=_uid(),
        content_key=_uid(),
        target_key=ticker,
        channel="in_app",
        content_hash=_uid(),
        status=status,
        attempts=1,
        canonical_severity="high",
        severity_rank=3,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_similarity_edge(db, *, query_key="NVDA", candidate_key="AMD",
                                  floor_passed=True, score=0.82, user_id=None) -> object:
    from app.db.repositories import similarity_repo
    return await similarity_repo.upsert_similarity_edge(
        db,
        target_type="company",
        query_key=query_key,
        candidate_key=candidate_key,
        score=score,
        rank=1,
        contributions=[{"feature": "sector", "shared_value": "semiconductors", "weight": 0.5, "partial_score": 0.4}],
        headline=f"{query_key} and {candidate_key} share semiconductor exposure",
        disanalogy="Different revenue mix",
        floor_passed=floor_passed,
        score_schema=1,
        user_id=user_id,
        ttl_hours=24,
    )


# ---------------------------------------------------------------------------
# 1. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty_list(self):
        from app.services.decision_candidate_builder import build_candidates
        result = await build_candidates(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_session_with_targets_returns_empty_list(self):
        from app.services.decision_candidate_builder import build_candidates
        result = await build_candidates(None, targets="NVDA,AAPL")
        assert result == []


# ---------------------------------------------------------------------------
# 2. Empty substrate
# ---------------------------------------------------------------------------

class TestEmptySubstrate:
    @pytest.mark.asyncio
    async def test_empty_db_returns_list(self, db):
        from app.services.decision_candidate_builder import build_candidates
        result = await build_candidates(db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_or_watchlist_only(self, db):
        from app.services.decision_candidate_builder import build_candidates
        result = await build_candidates(db)
        # No seeded data — should return []
        assert result == []


# ---------------------------------------------------------------------------
# 3. Candidate envelope shape
# ---------------------------------------------------------------------------

class TestCandidateEnvelope:
    @pytest.mark.asyncio
    async def test_all_required_keys_present(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await db.flush()

        result = await build_candidates(db)
        assert len(result) >= 1
        for candidate in result:
            missing = _REQUIRED_KEYS - set(candidate.keys())
            assert not missing, f"Candidate missing keys: {missing} | candidate_type={candidate.get('candidate_type')}"

    @pytest.mark.asyncio
    async def test_evidence_refs_is_list(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await db.flush()

        result = await build_candidates(db)
        for c in result:
            assert isinstance(c["evidence_refs"], list)

    @pytest.mark.asyncio
    async def test_score_input_dicts_are_dicts(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await db.flush()

        result = await build_candidates(db)
        for c in result:
            assert isinstance(c["urgency_inputs"], dict)
            assert isinstance(c["impact_inputs"], dict)
            assert isinstance(c["attention_inputs"], dict)
            assert isinstance(c["confidence_inputs"], dict)
            assert isinstance(c["uncertainty_inputs"], dict)


# ---------------------------------------------------------------------------
# 4–5. forecast_candidate
# ---------------------------------------------------------------------------

class TestForecastCandidates:
    @pytest.mark.asyncio
    async def test_seeded_vector_produces_forecast_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_FORECAST
        await _seed_forecast_vector(db, ticker="NVDA", p_pos=0.70, p_neg=0.20)
        await db.flush()

        result = await build_candidates(db)
        forecast_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_FORECAST]
        assert len(forecast_cands) == 1
        c = forecast_cands[0]
        assert c["entity_type"] == "company"
        assert c["source_type"] == "forecast_vector"
        assert "p_positive" in c["impact_inputs"]
        assert "horizon" in c["urgency_inputs"]

    @pytest.mark.asyncio
    async def test_weak_vector_below_floor_is_skipped(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_FORECAST
        # p_max = max(0.40, 0.35) = 0.40 < 0.50 floor → skipped
        await _seed_forecast_vector(db, ticker="NVDA", p_pos=0.40, p_neg=0.35, p_neu=0.25)
        await db.flush()

        result = await build_candidates(db)
        forecast_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_FORECAST]
        assert len(forecast_cands) == 0


# ---------------------------------------------------------------------------
# 6. risk_candidate
# ---------------------------------------------------------------------------

class TestRiskCandidates:
    @pytest.mark.asyncio
    async def test_seeded_failure_mode_produces_risk_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_RISK
        await _seed_failure_mode(db, ticker="NVDA")
        await db.flush()

        result = await build_candidates(db)
        risk_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_RISK]
        assert len(risk_cands) == 1
        c = risk_cands[0]
        assert c["entity_type"] == "failure_mode"
        assert c["source_type"] == "dossier_failure_mode"
        assert "sequence_stage" in c["urgency_inputs"]
        assert c["urgency_inputs"]["sequence_stage"] == 2


# ---------------------------------------------------------------------------
# 7–8. catalyst_candidate
# ---------------------------------------------------------------------------

class TestCatalystCandidates:
    @pytest.mark.asyncio
    async def test_open_catalyst_produces_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_CATALYST
        await _seed_catalyst(db, ticker="NVDA", status="open")
        await db.flush()

        result = await build_candidates(db)
        cat_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_CATALYST]
        assert len(cat_cands) == 1
        c = cat_cands[0]
        assert c["ticker"] == "NVDA"
        assert "specificity" in c["confidence_inputs"]

    @pytest.mark.asyncio
    async def test_triggered_catalyst_is_excluded(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_CATALYST
        await _seed_catalyst(db, ticker="NVDA", status="triggered")
        await db.flush()

        result = await build_candidates(db)
        cat_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_CATALYST]
        assert len(cat_cands) == 0


# ---------------------------------------------------------------------------
# 9–10. watchlist_candidate
# ---------------------------------------------------------------------------

class TestWatchlistCandidates:
    @pytest.mark.asyncio
    async def test_active_watchlist_produces_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_WATCHLIST
        await _seed_watchlist(db, ticker="NVDA", active=True)
        await db.flush()

        result = await build_candidates(db)
        wl_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_WATCHLIST]
        assert len(wl_cands) == 1
        c = wl_cands[0]
        assert c["ticker"] == "NVDA"
        assert c["source_type"] == "watched_tickers"

    @pytest.mark.asyncio
    async def test_inactive_watchlist_excluded(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_WATCHLIST
        await _seed_watchlist(db, ticker="NVDA", active=False)
        await db.flush()

        result = await build_candidates(db)
        wl_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_WATCHLIST]
        assert len(wl_cands) == 0


# ---------------------------------------------------------------------------
# 11–12. portfolio_exposure_candidate
# ---------------------------------------------------------------------------

class TestPortfolioExposureCandidates:
    @pytest.mark.asyncio
    async def test_active_position_produces_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_PORTFOLIO_EXPOSURE
        await _seed_portfolio_and_position(db, ticker="NVDA", active=True)
        await db.flush()

        result = await build_candidates(db)
        pe_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE]
        assert len(pe_cands) == 1
        c = pe_cands[0]
        assert c["ticker"] == "NVDA"
        assert c["entity_type"] == "portfolio"
        assert c["impact_inputs"]["weight"] == pytest.approx(0.15)

    @pytest.mark.asyncio
    async def test_inactive_position_excluded(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_PORTFOLIO_EXPOSURE
        await _seed_portfolio_and_position(db, ticker="NVDA", active=False)
        await db.flush()

        result = await build_candidates(db)
        pe_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_PORTFOLIO_EXPOSURE]
        assert len(pe_cands) == 0


# ---------------------------------------------------------------------------
# 13–14. delivery_transition_candidate
# ---------------------------------------------------------------------------

class TestDeliveryTransitionCandidates:
    @pytest.mark.asyncio
    async def test_pending_delivery_produces_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_DELIVERY_TRANSITION
        await _seed_delivery(db, ticker="NVDA", status="pending")
        await db.flush()

        result = await build_candidates(db)
        dt_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_DELIVERY_TRANSITION]
        assert len(dt_cands) == 1
        c = dt_cands[0]
        assert c["urgency_inputs"]["status"] == "pending"
        assert c["impact_inputs"]["canonical_severity"] == "high"

    @pytest.mark.asyncio
    async def test_delivered_status_excluded(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_DELIVERY_TRANSITION
        await _seed_delivery(db, ticker="NVDA", status="delivered")
        await db.flush()

        result = await build_candidates(db)
        dt_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_DELIVERY_TRANSITION]
        assert len(dt_cands) == 0


# ---------------------------------------------------------------------------
# 15. similarity_candidate
# ---------------------------------------------------------------------------

class TestSimilarityCandidates:
    @pytest.mark.asyncio
    async def test_floor_passed_edge_produces_candidate(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_SIMILARITY
        await _seed_similarity_edge(db, query_key="NVDA", candidate_key="AMD",
                                     floor_passed=True, score=0.82)
        await db.flush()

        result = await build_candidates(db)
        sim_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_SIMILARITY]
        assert len(sim_cands) == 1
        c = sim_cands[0]
        assert c["ticker"] == "NVDA"
        assert c["impact_inputs"]["score"] == pytest.approx(0.82)
        assert c["impact_inputs"]["candidate_key"] == "AMD"

    @pytest.mark.asyncio
    async def test_non_floor_passed_excluded(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_SIMILARITY
        await _seed_similarity_edge(db, query_key="NVDA", candidate_key="AMD",
                                     floor_passed=False, score=0.30)
        await db.flush()

        result = await build_candidates(db)
        sim_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_SIMILARITY]
        assert len(sim_cands) == 0


# ---------------------------------------------------------------------------
# 16. Targets filter
# ---------------------------------------------------------------------------

class TestTargetsFilter:
    @pytest.mark.asyncio
    async def test_targets_filter_includes_matching_ticker(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await _seed_watchlist(db, ticker="AAPL")
        await db.flush()

        result = await build_candidates(db, targets="NVDA")
        tickers = {c["ticker"] for c in result if c["ticker"]}
        assert "NVDA" in tickers
        assert "AAPL" not in tickers

    @pytest.mark.asyncio
    async def test_targets_filter_none_allows_all(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await _seed_watchlist(db, ticker="AAPL")
        await db.flush()

        result = await build_candidates(db, targets="")
        tickers = {c["ticker"] for c in result if c["ticker"]}
        assert "NVDA" in tickers
        assert "AAPL" in tickers

    @pytest.mark.asyncio
    async def test_targets_filter_multiple_tickers(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await _seed_watchlist(db, ticker="AAPL")
        await _seed_watchlist(db, ticker="MSFT")
        await db.flush()

        result = await build_candidates(db, targets="NVDA,AAPL")
        tickers = {c["ticker"] for c in result if c["ticker"]}
        assert "NVDA" in tickers
        assert "AAPL" in tickers
        assert "MSFT" not in tickers


# ---------------------------------------------------------------------------
# 17. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_watchlist_not_visible_to_user_b(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_WATCHLIST
        user_a = "user-a-" + _uid()
        user_b = "user-b-" + _uid()
        await _seed_watchlist(db, ticker="NVDA", active=True, user_id=user_a)
        await db.flush()

        result = await build_candidates(db, user_id=user_b)
        wl_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_WATCHLIST]
        assert len(wl_cands) == 0

    @pytest.mark.asyncio
    async def test_user_a_watchlist_visible_to_user_a(self, db):
        from app.services.decision_candidate_builder import build_candidates, CANDIDATE_TYPE_WATCHLIST
        user_a = "user-a-" + _uid()
        await _seed_watchlist(db, ticker="NVDA", active=True, user_id=user_a)
        await db.flush()

        result = await build_candidates(db, user_id=user_a)
        wl_cands = [c for c in result if c["candidate_type"] == CANDIDATE_TYPE_WATCHLIST]
        assert len(wl_cands) == 1


# ---------------------------------------------------------------------------
# 18. source_versions populated
# ---------------------------------------------------------------------------

class TestSourceVersions:
    @pytest.mark.asyncio
    async def test_source_versions_populated(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await db.flush()

        result = await build_candidates(db)
        for c in result:
            assert isinstance(c["source_versions"], dict), \
                f"Expected dict source_versions for {c['candidate_type']}"


# ---------------------------------------------------------------------------
# 19. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_substrate_returns_same_count(self, db):
        from app.services.decision_candidate_builder import build_candidates
        await _seed_watchlist(db, ticker="NVDA")
        await _seed_forecast_vector(db, ticker="NVDA", p_pos=0.70, p_neg=0.20)
        await db.flush()

        r1 = await build_candidates(db)
        r2 = await build_candidates(db)
        assert len(r1) == len(r2)


# ---------------------------------------------------------------------------
# 20–21. No DB writes
# ---------------------------------------------------------------------------

class TestNoDBWrites:
    @pytest.mark.asyncio
    async def test_build_candidates_writes_no_rows(self, db):
        from app.services.decision_candidate_builder import build_candidates
        from app.db.models import DecisionPriority, DecisionEvidence, DecisionRankingLog
        from sqlalchemy import select, func

        await _seed_watchlist(db, ticker="NVDA")
        await _seed_forecast_vector(db, ticker="NVDA", p_pos=0.70, p_neg=0.20)
        await db.flush()

        await build_candidates(db)

        # None of the three decision tables should have any rows after building candidates
        for Model, label in [
            (DecisionPriority, "decision_priority"),
            (DecisionEvidence, "decision_evidence"),
            (DecisionRankingLog, "decision_ranking_log"),
        ]:
            result = await db.execute(select(func.count()).select_from(Model))
            count = result.scalar()
            assert count == 0, f"Unexpected rows in {label} after build_candidates"


# ---------------------------------------------------------------------------
# 22. ALL_CANDIDATE_TYPES completeness
# ---------------------------------------------------------------------------

class TestAllCandidateTypes:
    def test_seven_candidate_types(self):
        from app.services.decision_candidate_builder import ALL_CANDIDATE_TYPES
        assert len(ALL_CANDIDATE_TYPES) == 7

    def test_expected_types_present(self):
        from app.services.decision_candidate_builder import (
            ALL_CANDIDATE_TYPES,
            CANDIDATE_TYPE_FORECAST,
            CANDIDATE_TYPE_RISK,
            CANDIDATE_TYPE_CATALYST,
            CANDIDATE_TYPE_WATCHLIST,
            CANDIDATE_TYPE_PORTFOLIO_EXPOSURE,
            CANDIDATE_TYPE_DELIVERY_TRANSITION,
            CANDIDATE_TYPE_SIMILARITY,
        )
        expected = {
            CANDIDATE_TYPE_FORECAST,
            CANDIDATE_TYPE_RISK,
            CANDIDATE_TYPE_CATALYST,
            CANDIDATE_TYPE_WATCHLIST,
            CANDIDATE_TYPE_PORTFOLIO_EXPOSURE,
            CANDIDATE_TYPE_DELIVERY_TRANSITION,
            CANDIDATE_TYPE_SIMILARITY,
        }
        assert set(ALL_CANDIDATE_TYPES) == expected


# ---------------------------------------------------------------------------
# 23–25. AST safety checks
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _get_docstring_values(tree: ast.AST) -> set:
    """Collect string values of module/function/class docstrings to exclude."""
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_conviction_or_recommendation_imports(self):
        tree = _load_tree()
        forbidden = {
            "conviction_modeler",
            "conviction",
            "recommendation",
            "order",
            "execution",
            "forecast_delivery_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for forbidden_word in forbidden:
                        assert forbidden_word not in part.lower(), \
                            f"Forbidden import {part!r} found in decision_candidate_builder.py"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        docstring_values = _get_docstring_values(tree)

        banned_terms = ["buy", "sell", "hold", "overweight", "underweight",
                        "recommend", "target price", "position size"]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in docstring_values:
                    continue
                for term in banned_terms:
                    if term in val.lower():
                        snippet = val[:60]
                        offenders.append(repr(term) + " in " + repr(snippet))
        assert not offenders, "Advice language in string constants: " + str(offenders)

    def test_no_session_add_to_source_tables(self):
        """Module must not call session.add() anywhere."""
        src = _SVC.read_text(encoding="utf-8")
        # Direct string check — the module makes no session.add() calls at all
        # (sub-builders are pure reads using session.execute + scalars)
        assert "session.add(" not in src, \
            "decision_candidate_builder.py must not call session.add()"

    def test_no_update_or_delete_calls(self):
        """Module must not call .update() or .delete() anywhere."""
        src = _SVC.read_text(encoding="utf-8")
        assert ".update(" not in src, "Found .update() in candidate builder — writes forbidden"
        assert ".delete(" not in src, "Found .delete() in candidate builder — writes forbidden"
