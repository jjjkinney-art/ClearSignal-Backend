"""
Phase 12 — Slice 2: Forecast Feature Builder Tests.

Covers:
  T1  — build_company_forecast_features
  T4  — build_failure_mode_forecast_features
  All — build_company_forecast_features_for_all
  All — build_failure_mode_forecast_features_for_all

Safety invariants tested:
  - Null-session returns safe inert value (None / [])
  - Missing primary entity returns None
  - Sparse substrate (missing joined facets) returns non-None sparse dict
  - Deterministic output for identical substrate
  - No write-back to any source table
  - No forecast output (no p_positive / p_negative / p_neutral in result)
  - No price/advice field in result
  - No opaque embeddings (all feature keys are human-readable strings)
  - Dependency direction: forecast_feature_builder does NOT import similarity_feature_builder
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import sys
import types
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).parent.parent.parent


def _make_uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_analog(
    analog_id: Optional[str] = None,
    mechanism: str = "governance",
    concern_tags: list = None,
    quality_rating: str = "B+",
    outcome_summary: str = "resolved after board change",
    drawdown_pct: float = 0.12,
    time_to_recover_days: int = 90,
    valuation_regime: str = "growth",
    growth_phase: str = "late",
    macro_regime: str = "tightening",
    sector: str = "tech",
    business_model: str = "saas",
) -> MagicMock:
    a = MagicMock()
    a.id = analog_id or _make_uuid()
    a.mechanism = mechanism
    a.concern_tags = concern_tags if concern_tags is not None else ["governance"]
    a.quality_rating = quality_rating
    a.outcome_summary = outcome_summary
    a.drawdown_pct = drawdown_pct
    a.time_to_recover_days = time_to_recover_days
    a.valuation_regime = valuation_regime
    a.growth_phase = growth_phase
    a.macro_regime = macro_regime
    a.sector = sector
    a.business_model = business_model
    return a


def _mock_fm(
    fm_id: Optional[str] = None,
    ticker: str = "ACME",
    analog_id: Optional[str] = None,
    sequence_stage: int = 2,
    relevance_at_match: float = 0.8,
    matched_at: Optional[datetime] = None,
    stage_evidence: str = "stage 2 confirmed",
) -> MagicMock:
    fm = MagicMock()
    fm.id = fm_id or _make_uuid()
    fm.ticker = ticker
    fm.analog_id = analog_id or _make_uuid()
    fm.sequence_stage = sequence_stage
    fm.relevance_at_match = relevance_at_match
    fm.matched_at = matched_at or _now()
    fm.stage_evidence = stage_evidence
    return fm


def _mock_head(
    ticker: str = "ACME",
    stance: str = "bearish",
    conviction: float = 72.0,
    primary_concern: str = "governance",
    staleness_state: str = "fresh",
    row_version: int = 5,
    global_confidence: float = 0.71,
) -> MagicMock:
    h = MagicMock()
    h.ticker = ticker
    h.stance = stance
    h.conviction = conviction
    h.primary_concern = primary_concern
    h.staleness_state = staleness_state
    h.row_version = row_version
    h.global_confidence = global_confidence
    return h


def _mock_debate(
    current_lean: str = "bearish",
    version: int = 3,
    confidence: float = 0.68,
) -> MagicMock:
    d = MagicMock()
    d.current_lean = current_lean
    d.version = version
    d.confidence = confidence
    return d


def _mock_durability(
    conviction_trend: str = "declining",
    cycle_position: str = "late_cycle",
    horizon_hint: str = "tactical",
    catalyst_proximity_days: int = 30,
    analog_time_to_trough_days: int = 60,
) -> MagicMock:
    d = MagicMock()
    d.conviction_trend = conviction_trend
    d.cycle_position = cycle_position
    d.horizon_hint = horizon_hint
    d.catalyst_proximity_days = catalyst_proximity_days
    d.analog_time_to_trough_days = analog_time_to_trough_days
    return d


def _mock_thesis_version(
    tv_id: Optional[str] = None,
    ticker: str = "ACME",
    confidence_score: float = 0.65,
    directional_stance: str = "bearish",
    created_at: Optional[datetime] = None,
) -> MagicMock:
    tv = MagicMock()
    tv.id = tv_id or _make_uuid()
    tv.ticker = ticker
    tv.confidence_score = confidence_score
    tv.directional_stance = directional_stance
    tv.created_at = created_at or _now()
    return tv


def _mock_similarity_edge(
    candidate_key: str = "PEER",
    score: float = 0.72,
    target_type: str = "company",
    rank: int = 1,
) -> MagicMock:
    e = MagicMock()
    e.candidate_key = candidate_key
    e.score = score
    e.target_type = target_type
    e.rank = rank
    e.floor_passed = True
    e.expires_at = _now() + timedelta(days=1)
    return e


def _make_scalars_result(rows: list):
    """Return a mock that satisfies `(await session.execute(stmt)).scalars().all()`."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    result.scalar_one_or_none = MagicMock(return_value=rows[0] if rows else None)
    return result


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def import_module():
    """Import forecast_feature_builder fresh each test."""
    import importlib
    mod_path = "app.services.forecast_feature_builder"
    if mod_path in sys.modules:
        del sys.modules[mod_path]
    return importlib.import_module(mod_path)


# ---------------------------------------------------------------------------
# NULL-SESSION SAFETY
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    """All public async functions must return safe inert values when session is None."""

    @pytest.mark.asyncio
    async def test_build_company_features_null_session(self):
        from app.services.forecast_feature_builder import build_company_forecast_features
        result = await build_company_forecast_features(None, "ACME")
        assert result is None

    @pytest.mark.asyncio
    async def test_build_failure_mode_features_null_session(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features
        result = await build_failure_mode_forecast_features(None, _make_uuid())
        assert result is None

    @pytest.mark.asyncio
    async def test_build_company_for_all_null_session(self):
        from app.services.forecast_feature_builder import build_company_forecast_features_for_all
        result = await build_company_forecast_features_for_all(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_build_failure_mode_for_all_null_session(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features_for_all
        result = await build_failure_mode_forecast_features_for_all(None)
        assert result == []


# ---------------------------------------------------------------------------
# MISSING PRIMARY ENTITY
# ---------------------------------------------------------------------------

class TestMissingPrimaryEntity:
    """When the primary entity doesn't exist, builder returns None."""

    @pytest.mark.asyncio
    async def test_company_missing_head_returns_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        with patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=None)):
            result = await build_company_forecast_features(session, "MISSING")
        assert result is None

    @pytest.mark.asyncio
    async def test_failure_mode_missing_row_returns_none(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))
        result = await build_failure_mode_forecast_features(session, _make_uuid())
        assert result is None


# ---------------------------------------------------------------------------
# T1 COMPANY — HAPPY PATH
# ---------------------------------------------------------------------------

class TestCompanyFeatureHappyPath:
    """Company builder returns a well-formed feature dict on full substrate."""

    def _make_session(self, ticker: str = "ACME") -> AsyncMock:
        """Build a session mock that returns all necessary fixtures."""
        head = _mock_head(ticker=ticker)
        debate = _mock_debate()
        durability = _mock_durability()
        tv1 = _mock_thesis_version(ticker=ticker, confidence_score=0.70)
        tv2 = _mock_thesis_version(ticker=ticker, confidence_score=0.55)
        analog = _mock_analog()
        fm = _mock_fm(ticker=ticker, analog_id=analog.id)
        edge = _mock_similarity_edge(candidate_key="PEER1", target_type="company")

        session = AsyncMock()

        analog_result = MagicMock()
        analog_result.scalar_one_or_none = MagicMock(return_value=analog)

        call_count = [0]

        async def fake_execute(stmt):
            call_count[0] += 1
            # Try to detect which query is being made by inspecting stmt
            stmt_str = str(stmt).lower()
            if "thesisversion" in stmt_str or "thesis_version" in stmt_str:
                return _make_scalars_result([tv1, tv2])
            if "dossierfailuremode" in stmt_str or "dossier_failure_mode" in stmt_str:
                return _make_scalars_result([fm])
            if "historicalanalog" in stmt_str or "historical_analog" in stmt_str:
                return analog_result
            if "similarityedge" in stmt_str or "similarity_edge" in stmt_str:
                return _make_scalars_result([edge])
            return _make_scalars_result([])

        session.execute = AsyncMock(side_effect=fake_execute)
        return session, head, debate, durability

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        required_keys = {
            "entity_type", "entity_key", "analog_set", "analog_count",
            "similarity_peers", "similarity_peer_count", "similarity_avg_score",
            "thesis_trajectory", "debate_state", "regime_context", "durability",
            "source_versions", "staleness_indicators", "feature_schema",
        }
        assert required_keys.issubset(set(result.keys())), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    @pytest.mark.asyncio
    async def test_entity_type_and_key(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result["entity_type"] == "company"
        assert result["entity_key"] == "ACME"

    @pytest.mark.asyncio
    async def test_thesis_trajectory_rising_direction(self):
        """When confidence goes from 0.55 to 0.70, direction should be 'rising'."""
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        traj = result["thesis_trajectory"]
        assert traj["direction"] == "rising"
        assert traj["delta"] == pytest.approx(0.70 - 0.55, abs=1e-9)

    @pytest.mark.asyncio
    async def test_thesis_trajectory_falling_direction(self):
        """When confidence goes from 0.70 to 0.55, direction should be 'falling'."""
        from app.services.forecast_feature_builder import build_company_forecast_features

        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        tv1 = _mock_thesis_version(confidence_score=0.55)
        tv2 = _mock_thesis_version(confidence_score=0.70)

        async def fake_execute(stmt):
            stmt_str = str(stmt).lower()
            if "thesisversion" in stmt_str or "thesis_version" in stmt_str:
                return _make_scalars_result([tv1, tv2])
            return _make_scalars_result([])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result["thesis_trajectory"]["direction"] == "falling"

    @pytest.mark.asyncio
    async def test_analog_set_populated(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result["analog_count"] == len(result["analog_set"])
        if result["analog_count"] > 0:
            analog_entry = result["analog_set"][0]
            required_analog_keys = {
                "analog_id", "mechanism", "concern_tags", "quality_rating",
                "outcome_summary", "drawdown_pct", "time_to_recover_days",
                "valuation_regime", "growth_phase", "macro_regime",
                "relevance_weight", "resolution",
            }
            assert required_analog_keys.issubset(set(analog_entry.keys()))

    @pytest.mark.asyncio
    async def test_regime_context_from_durability(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        rc = result["regime_context"]
        assert rc["conviction_trend"] == "declining"
        assert rc["cycle_position"] == "late_cycle"
        assert rc["horizon_hint"] == "tactical"

    @pytest.mark.asyncio
    async def test_source_versions_present(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session, head, debate, durability = self._make_session()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        sv = result["source_versions"]
        assert "company_dossier_row_version" in sv
        assert "thesis_version_id" in sv
        assert "core_debate_version" in sv
        assert "feature_schema" in sv
        assert sv["company_dossier_row_version"] == 5  # from mock head


# ---------------------------------------------------------------------------
# T1 — SPARSE SUBSTRATE
# ---------------------------------------------------------------------------

class TestCompanyFeatureSparseSubstrate:
    """Builder returns non-None sparse dict when secondary facets are missing."""

    @pytest.mark.asyncio
    async def test_no_debate_returns_non_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))

        head = _mock_head()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=None)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=None)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        assert result["entity_type"] == "company"
        assert result["debate_state"]["current_lean"] == "balanced"

    @pytest.mark.asyncio
    async def test_no_thesis_versions_returns_non_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))

        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        traj = result["thesis_trajectory"]
        assert traj["confidence_current"] == 0.0
        assert traj["version_count"] == 0
        assert traj["direction"] == "flat"

    @pytest.mark.asyncio
    async def test_no_analogs_returns_non_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))

        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        assert result["analog_count"] == 0
        assert result["analog_set"] == []

    @pytest.mark.asyncio
    async def test_no_similarity_peers_returns_non_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))

        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        assert result["similarity_peer_count"] == 0
        assert result["similarity_avg_score"] == 0.0


# ---------------------------------------------------------------------------
# T4 FAILURE MODE — HAPPY PATH
# ---------------------------------------------------------------------------

class TestFailureModeFeatureHappyPath:
    """Failure mode builder returns well-formed feature dict on full substrate."""

    def _make_fm_session(self) -> tuple:
        fm_id = _make_uuid()
        analog_id = _make_uuid()
        fm = _mock_fm(fm_id=fm_id, ticker="ACME", analog_id=analog_id, sequence_stage=2)
        analog = _mock_analog(analog_id=analog_id, drawdown_pct=0.35)  # negative resolution
        edge = _mock_similarity_edge(candidate_key="PEER_FM", target_type="failure_mode")

        session = AsyncMock()

        analog_result = MagicMock()
        analog_result.scalar_one_or_none = MagicMock(return_value=analog)

        fm_result = MagicMock()
        fm_result.scalar_one_or_none = MagicMock(return_value=fm)

        call_count = [0]

        async def fake_execute(stmt):
            call_count[0] += 1
            stmt_str = str(stmt).lower()
            if "dossierfailuremode" in stmt_str or "dossier_failure_mode" in stmt_str:
                # Single-row lookup
                scalar_result = MagicMock()
                scalar_result.scalar_one_or_none = MagicMock(return_value=fm)
                scalars = MagicMock()
                scalars.all = MagicMock(return_value=[fm_id])
                scalar_result.scalars = MagicMock(return_value=scalars)
                return scalar_result
            if "historicalanalog" in stmt_str or "historical_analog" in stmt_str:
                return analog_result
            if "similarityedge" in stmt_str or "similarity_edge" in stmt_str:
                return _make_scalars_result([edge])
            return _make_scalars_result([])

        session.execute = AsyncMock(side_effect=fake_execute)
        return session, fm_id, fm, analog

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        session, fm_id, fm, analog = self._make_fm_session()
        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_failure_mode_forecast_features(session, fm_id)

        assert result is not None
        required_keys = {
            "entity_type", "entity_key", "failure_mode", "analog_set",
            "analog_count", "similarity_peers", "similarity_peer_count",
            "similarity_avg_score", "thesis_trajectory", "debate_state",
            "regime_context", "durability", "source_versions",
            "staleness_indicators", "feature_schema",
        }
        assert required_keys.issubset(set(result.keys())), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    @pytest.mark.asyncio
    async def test_entity_type_and_key(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        session, fm_id, fm, analog = self._make_fm_session()
        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_failure_mode_forecast_features(session, fm_id)

        assert result["entity_type"] == "failure_mode"
        assert result["entity_key"] == fm_id

    @pytest.mark.asyncio
    async def test_failure_mode_info_populated(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        session, fm_id, fm, analog = self._make_fm_session()
        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_failure_mode_forecast_features(session, fm_id)

        info = result["failure_mode"]
        assert info["ticker"] == "ACME"
        assert info["sequence_stage"] == 2
        assert info["relevance_at_match"] == pytest.approx(0.8, abs=1e-9)
        assert info["mechanism"] == "governance"

    @pytest.mark.asyncio
    async def test_analog_resolution_negative_for_high_drawdown(self):
        """drawdown_pct=0.35 → resolution='negative'."""
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        session, fm_id, fm, analog = self._make_fm_session()
        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_failure_mode_forecast_features(session, fm_id)

        assert result["analog_count"] >= 1
        resolutions = [a["resolution"] for a in result["analog_set"]]
        assert "negative" in resolutions


# ---------------------------------------------------------------------------
# T4 — SPARSE SUBSTRATE
# ---------------------------------------------------------------------------

class TestFailureModeFeatureSparseSubstrate:
    """Missing joined analog returns sparse dict, not None."""

    @pytest.mark.asyncio
    async def test_missing_analog_returns_sparse_non_none(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        fm_id = _make_uuid()
        fm = _mock_fm(fm_id=fm_id, ticker="ACME", analog_id=_make_uuid())

        fm_result = MagicMock()
        fm_result.scalar_one_or_none = MagicMock(return_value=fm)

        missing_analog_result = MagicMock()
        missing_analog_result.scalar_one_or_none = MagicMock(return_value=None)

        async def fake_execute(stmt):
            stmt_str = str(stmt).lower()
            if "historicalanalog" in stmt_str or "historical_analog" in stmt_str:
                return missing_analog_result
            if "dossierfailuremode" in stmt_str or "dossier_failure_mode" in stmt_str:
                return fm_result
            return _make_scalars_result([])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        head = _mock_head()
        debate = _mock_debate()
        durability = _mock_durability()
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result = await build_failure_mode_forecast_features(session, fm_id)

        assert result is not None
        assert result["analog_count"] == 0
        assert result["analog_set"] == []

    @pytest.mark.asyncio
    async def test_missing_company_context_returns_sparse_non_none(self):
        """No company_dossier head → failure mode features still built (sparse thesis/regime)."""
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features

        fm_id = _make_uuid()
        analog_id = _make_uuid()
        fm = _mock_fm(fm_id=fm_id, analog_id=analog_id)
        analog = _mock_analog(analog_id=analog_id)

        analog_result = MagicMock()
        analog_result.scalar_one_or_none = MagicMock(return_value=analog)

        fm_result = MagicMock()
        fm_result.scalar_one_or_none = MagicMock(return_value=fm)

        async def fake_execute(stmt):
            stmt_str = str(stmt).lower()
            if "historicalanalog" in stmt_str or "historical_analog" in stmt_str:
                return analog_result
            if "dossierfailuremode" in stmt_str or "dossier_failure_mode" in stmt_str:
                return fm_result
            return _make_scalars_result([])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        # No company head → build_company_forecast_features returns None
        with patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=None)):
            result = await build_failure_mode_forecast_features(session, fm_id)

        assert result is not None
        assert result["thesis_trajectory"]["direction"] == "unknown"
        assert result["debate_state"]["current_lean"] == "balanced"


# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Identical substrate must produce identical output."""

    @pytest.mark.asyncio
    async def test_company_features_deterministic(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        head = _mock_head(row_version=3)
        debate = _mock_debate(version=2)
        durability = _mock_durability()
        tv = _mock_thesis_version(confidence_score=0.60)

        async def fake_execute(stmt):
            stmt_str = str(stmt).lower()
            if "thesisversion" in stmt_str or "thesis_version" in stmt_str:
                return _make_scalars_result([tv])
            return _make_scalars_result([])

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=fake_execute)

        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result1 = await build_company_forecast_features(session, "ACME")

        session2 = AsyncMock()
        session2.execute = AsyncMock(side_effect=fake_execute)
        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=debate)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=durability)),
        ):
            result2 = await build_company_forecast_features(session2, "ACME")

        assert result1 is not None and result2 is not None
        assert result1["entity_key"] == result2["entity_key"]
        assert result1["analog_count"] == result2["analog_count"]
        assert result1["thesis_trajectory"]["delta"] == result2["thesis_trajectory"]["delta"]
        assert result1["source_versions"] == result2["source_versions"]


# ---------------------------------------------------------------------------
# ANALOG RESOLUTION INFERENCE
# ---------------------------------------------------------------------------

class TestAnalogResolutionInference:
    """_infer_analog_resolution rules are correct and human-readable."""

    def _get_infer(self):
        from app.services.forecast_feature_builder import _infer_analog_resolution
        return _infer_analog_resolution

    def test_high_drawdown_is_negative(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = 0.40; a.outcome_summary = ""
        assert fn(a) == "negative"

    def test_low_drawdown_is_positive(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = 0.03; a.outcome_summary = ""
        assert fn(a) == "positive"

    def test_mid_drawdown_is_neutral(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = 0.15; a.outcome_summary = ""
        assert fn(a) == "neutral"

    def test_no_drawdown_positive_keyword(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = None; a.outcome_summary = "risk resolved and equity recovered"
        assert fn(a) == "positive"

    def test_no_drawdown_negative_keyword(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = None; a.outcome_summary = "company filed for bankruptcy"
        assert fn(a) == "negative"

    def test_none_analog_is_unknown(self):
        fn = self._get_infer()
        assert fn(None) == "unknown"

    def test_no_drawdown_no_keyword_is_unknown(self):
        fn = self._get_infer()
        a = MagicMock(); a.drawdown_pct = None; a.outcome_summary = "management transition ongoing"
        assert fn(a) == "unknown"


# ---------------------------------------------------------------------------
# NO WRITE-BACK
# ---------------------------------------------------------------------------

class TestNoWriteBack:
    """Feature builder must not write to any source table."""

    def test_module_has_no_db_write_calls(self):
        """AST check: no session.execute calls with INSERT/UPDATE/DELETE."""
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        tree = ast.parse(src)

        write_methods = {"add", "delete", "merge", "flush", "commit", "execute_write"}
        found_writes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                attr = None
                if isinstance(func, ast.Attribute):
                    attr = func.attr
                elif isinstance(func, ast.Name):
                    attr = func.id
                if attr in write_methods:
                    found_writes.append(attr)

        assert found_writes == [], (
            f"forecast_feature_builder contains write calls: {found_writes}"
        )

    def test_no_upsert_import(self):
        """Module should not import forecast_repo.upsert_* in Slice 2."""
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        # upsert calls belong to Slice 5 (orchestration layer)
        assert "upsert_forecast_vector" not in src, (
            "forecast_feature_builder must not call upsert_forecast_vector in Slice 2"
        )


# ---------------------------------------------------------------------------
# NO FORECAST OUTPUT
# ---------------------------------------------------------------------------

class TestNoForecastOutput:
    """Feature object must not contain probability or advice fields."""

    FORBIDDEN_KEYS = {
        "p_positive", "p_negative", "p_neutral",
        "probability", "confidence_band_low", "confidence_band_high",
        "forecast_type", "why", "invalidators",
        # price / advice fields
        "price_target", "target_price", "buy", "sell",
        "recommendation", "investment_advice",
    }

    @pytest.mark.asyncio
    async def test_company_result_has_no_probability_keys(self):
        from app.services.forecast_feature_builder import build_company_forecast_features

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))
        head = _mock_head()

        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=None)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=None)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        flat_keys = set(result.keys())
        forbidden_present = flat_keys & self.FORBIDDEN_KEYS
        assert not forbidden_present, (
            f"Probability/advice keys found in company feature output: {forbidden_present}"
        )

    def test_source_has_no_price_advice_field_keys(self):
        """AST check: no price/advice names appear as dict keys or attribute names."""
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        tree = ast.parse(src)

        # Collect all string constants and attribute names from actual code (not docstrings)
        code_strings: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.s, str):
                code_strings.append(node.s)
            if isinstance(node, ast.Attribute):
                code_strings.append(node.attr)

        forbidden_field_names = {
            "price_target", "target_price", "investment_advice",
            "recommendation", "buy_signal", "sell_signal",
        }
        for name in forbidden_field_names:
            assert name not in code_strings, (
                f"Forbidden field name '{name}' found as a code-level string/attr "
                "in forecast_feature_builder.py"
            )


# ---------------------------------------------------------------------------
# NO OPAQUE EMBEDDINGS
# ---------------------------------------------------------------------------

class TestNoOpaqueEmbeddings:
    """All feature keys must be human-interpretable strings, not vector embeddings."""

    def test_module_has_no_embedding_imports(self):
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        embedding_signals = [
            "numpy", "torch", "sentence_transformers", "openai.embeddings",
            "faiss", "annoy", "embedding_vector",
        ]
        for sig in embedding_signals:
            assert sig not in src, (
                f"Embedding library reference '{sig}' found — forecast features must be "
                "human-readable, not opaque vectors"
            )


# ---------------------------------------------------------------------------
# DEPENDENCY DIRECTION
# ---------------------------------------------------------------------------

class TestDependencyDirection:
    """Phase 12 feature builder may import Phase 11, not the reverse."""

    def test_does_not_import_similarity_feature_builder(self):
        """forecast_feature_builder must not import similarity_feature_builder."""
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        assert "similarity_feature_builder" not in src, (
            "forecast_feature_builder must not import similarity_feature_builder — "
            "dependency direction: Phase 12 reads Phase 11 tables, not Phase 11 code"
        )

    def test_does_not_import_forecast_scorer(self):
        """Feature builder must not import the probability engine (Slice 12.3)."""
        src = (ROOT / "app/services/forecast_feature_builder.py").read_text()
        assert "forecast_scorer" not in src, (
            "forecast_feature_builder must not import forecast_scorer — "
            "probability computation belongs to Slice 12.3"
        )


# ---------------------------------------------------------------------------
# BATCH FUNCTIONS
# ---------------------------------------------------------------------------

class TestBatchFunctions:
    """Batch wrappers collect results and skip None entries."""

    @pytest.mark.asyncio
    async def test_build_company_for_all_skips_none(self):
        from app.services.forecast_feature_builder import build_company_forecast_features_for_all

        from app.db.models import CompanyDossier
        tickers_result = _make_scalars_result(["ACME", "PEER"])
        session = AsyncMock()
        session.execute = AsyncMock(return_value=tickers_result)

        call_args = []

        async def fake_build(s, ticker, **kwargs):
            call_args.append(ticker)
            if ticker == "PEER":
                return None  # simulate missing
            return {"entity_type": "company", "entity_key": ticker}

        with patch(
            "app.services.forecast_feature_builder.build_company_forecast_features",
            new=fake_build,
        ):
            result = await build_company_forecast_features_for_all(session)

        assert len(result) == 1
        assert result[0]["entity_key"] == "ACME"
        assert "PEER" in call_args

    @pytest.mark.asyncio
    async def test_build_failure_mode_for_all_skips_none(self):
        from app.services.forecast_feature_builder import build_failure_mode_forecast_features_for_all

        ids = [_make_uuid(), _make_uuid()]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result(ids))

        call_args = []

        async def fake_build(s, fm_id, **kwargs):
            call_args.append(fm_id)
            if fm_id == ids[1]:
                return None
            return {"entity_type": "failure_mode", "entity_key": fm_id}

        with patch(
            "app.services.forecast_feature_builder.build_failure_mode_forecast_features",
            new=fake_build,
        ):
            result = await build_failure_mode_forecast_features_for_all(session)

        assert len(result) == 1
        assert result[0]["entity_key"] == ids[0]

    @pytest.mark.asyncio
    async def test_batch_limit_respected(self):
        from app.services.forecast_feature_builder import build_company_forecast_features_for_all

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))

        # Should not raise even with empty result + limit
        result = await build_company_forecast_features_for_all(session, limit=5)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# FEATURE SCHEMA VERSION
# ---------------------------------------------------------------------------

class TestFeatureSchemaVersion:
    """feature_schema field must match the declared module constants."""

    def test_company_feature_version_constant(self):
        from app.services.forecast_feature_builder import COMPANY_FEATURE_VERSION
        assert isinstance(COMPANY_FEATURE_VERSION, int)
        assert COMPANY_FEATURE_VERSION >= 1

    def test_failure_mode_feature_version_constant(self):
        from app.services.forecast_feature_builder import FAILURE_MODE_FEATURE_VERSION
        assert isinstance(FAILURE_MODE_FEATURE_VERSION, int)
        assert FAILURE_MODE_FEATURE_VERSION >= 1

    @pytest.mark.asyncio
    async def test_company_result_includes_feature_schema(self):
        from app.services.forecast_feature_builder import (
            build_company_forecast_features,
            COMPANY_FEATURE_VERSION,
        )

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_make_scalars_result([]))
        head = _mock_head()

        with (
            patch("app.db.repositories.dossier_repo.get_head", new=AsyncMock(return_value=head)),
            patch("app.db.repositories.dossier_repo.get_debate", new=AsyncMock(return_value=None)),
            patch("app.db.repositories.dossier_repo.get_durability", new=AsyncMock(return_value=None)),
        ):
            result = await build_company_forecast_features(session, "ACME")

        assert result is not None
        assert result["feature_schema"] == COMPANY_FEATURE_VERSION
