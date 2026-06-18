"""
Tests — Scenario Portfolio Propagation, Phase 14 · Slice 7.

Covers:
  1.  direct holding impact
  2.  indirect exposure impact (cross-exposed ticker held)
  3.  concentration amplification (high weight → high modifier)
  4.  no holdings case (portfolio holds none of the affected tickers → score 0)
  5.  tenant isolation — user_a cannot see user_b portfolios
  6.  global isolation — user_id=None sees only global portfolios
  7.  no portfolio mutation (source propagation dict unchanged)
  8.  null session safety for all four public functions
  9.  portfolio_contexts list in output
  10. portfolio_impact_score in [0, 1]
  11. concentration_modifier in [0.5, 2.0]
  12. exposure chain direct entry (depth 0)
  13. exposure chain cross-exposed entry (depth 1)
  14. exposure chain empty when no holdings
  15. compute_concentration_modifier low weight
  16. compute_concentration_modifier elevated weight
  17. compute_concentration_modifier high weight
  18. compute_concentration_modifier no holdings
  19. compute_concentration_modifier empty positions
  20. held_tickers list reflects held tickers
  21. output dict has required portfolio context keys
  22. propagate_to_portfolio preserves all original propagation keys
  23. portfolio_impact_score rollup is max across contexts
  24. concentration_modifier rollup is max across contexts
  25. empty affected_portfolios in propagation → discover from user
  26. no portfolio writes (AST)
  27. no delivery imports (AST)
  28. no recommendation language in string constants (AST)
  29. no conviction/forecast/decision write-back (AST)
  30. shared failure-mode amplification (multiple affected holdings)
"""

from __future__ import annotations

import ast
import json
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_portfolio_propagation.py"

_REQUIRED_CONTEXT_KEYS = {
    "portfolio_id",
    "portfolio_impact_score",
    "held_tickers",
    "concentration_modifier",
    "exposure_chain",
}

_REQUIRED_PROPAGATION_KEYS = {
    "scenario_type", "scenario_name", "transmission_path",
    "direct_impacts", "indirect_impacts", "affected_entities",
    "affected_portfolios", "impact_confidence", "impact_uncertainty",
    "propagation_depth", "source_versions",
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
# Data helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _add_portfolio(session, *, user_id=None, name="Test Portfolio") -> str:
    from app.db.models import Portfolio
    pid = _uid()
    row = Portfolio(
        id=pid,
        user_id=user_id,
        name=name,
        is_default=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    return pid


def _add_position(session, portfolio_id: str, ticker: str, *, weight=None, active=True):
    from app.db.models import PortfolioPosition
    row = PortfolioPosition(
        id=_uid(),
        portfolio_id=portfolio_id,
        ticker=ticker.upper(),
        membership_class="owned",
        weight=weight,
        active=active,
        added_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)


def _add_cross_exposure(session, ticker_a: str, ticker_b: str, *, strength=0.75, etype="sector"):
    from app.db.models import CrossExposure
    row = CrossExposure(
        id=_uid(),
        ticker_a=ticker_a.upper(),
        ticker_b=ticker_b.upper(),
        shared_concerns=json.dumps([]),
        exposure_type=etype,
        strength=strength,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)


def _make_propagation(
    affected_tickers=None,
    affected_portfolios=None,
    confidence=0.70,
    scenario_type="company_scenario",
    primary_ticker="NVDA",
) -> dict:
    affected_tickers = affected_tickers or [primary_ticker]
    affected_portfolios = affected_portfolios or []
    return {
        "scenario_type":     scenario_type,
        "scenario_name":     f"{primary_ticker} {scenario_type}",
        "transmission_path": [{"step": 0, "cause": "assumption", "effect": f"{primary_ticker} changes", "channel": "direct"}],
        "direct_impacts": [{
            "entity_key":            primary_ticker,
            "entity_type":           "company",
            "impact_channel":        "direct",
            "transmission_strength": "strong",
            "depth":                 0,
        }],
        "indirect_impacts":    [],
        "affected_entities":   [
            {"entity_key": t, "entity_type": "company",
             "impact_channel": "direct", "transmission_strength": "strong", "depth": 0}
            for t in affected_tickers
        ],
        "affected_portfolios": affected_portfolios,
        "impact_confidence":   confidence,
        "impact_uncertainty":  0.25,
        "propagation_depth":   0,
        "source_versions":     {},
        "user_id":             None,
    }


# ---------------------------------------------------------------------------
# 1. Direct holding impact
# ---------------------------------------------------------------------------

class TestDirectHoldingImpact:
    @pytest.mark.asyncio
    async def test_direct_holding_produces_nonzero_score(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.20)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert ctx["portfolio_impact_score"] > 0.0

    @pytest.mark.asyncio
    async def test_held_tickers_contains_held_ticker(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.30)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert "NVDA" in ctx["held_tickers"]

    @pytest.mark.asyncio
    async def test_direct_holding_context_has_required_keys(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA")
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        missing = _REQUIRED_CONTEXT_KEYS - ctx.keys()
        assert not missing, f"Missing keys: {missing}"


# ---------------------------------------------------------------------------
# 2. Indirect exposure impact
# ---------------------------------------------------------------------------

class TestIndirectExposureImpact:
    @pytest.mark.asyncio
    async def test_cross_exposed_ticker_appears_in_chain(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.10)
        _add_position(db, pid, "AMD", weight=0.10)
        _add_cross_exposure(db, "NVDA", "AMD", strength=0.80)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        entity_keys = [e["entity_key"] for e in chain]
        assert "AMD" in entity_keys

    @pytest.mark.asyncio
    async def test_cross_exposed_entry_has_depth_one(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "AMD", weight=0.15)
        _add_cross_exposure(db, "NVDA", "AMD", strength=0.75)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        amd_entries = [e for e in chain if e["entity_key"] == "AMD"]
        assert any(e["depth"] == 1 for e in amd_entries)

    @pytest.mark.asyncio
    async def test_cross_exposed_channel_reflects_exposure_type(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "AMD")
        _add_cross_exposure(db, "NVDA", "AMD", strength=0.75, etype="supply_chain")
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        amd_entries = [e for e in chain if e["entity_key"] == "AMD"]
        assert any("supply_chain" in e.get("channel", "") for e in amd_entries)


# ---------------------------------------------------------------------------
# 3. Concentration amplification
# ---------------------------------------------------------------------------

class TestConcentrationAmplification:
    def _positions(self, weights: dict) -> list:
        return [{"ticker": t, "weight": w, "active": True} for t, w in weights.items()]

    def test_high_concentration_returns_max_modifier(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = self._positions({"NVDA": 0.60, "AAPL": 0.40})
        modifier = compute_concentration_modifier(positions, ["NVDA", "AAPL"])
        assert modifier == 2.0

    def test_elevated_concentration_returns_15_modifier(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = self._positions({"NVDA": 0.35, "AAPL": 0.65})
        modifier = compute_concentration_modifier(positions, ["NVDA"])
        assert modifier == 1.5

    def test_moderate_concentration_returns_10_modifier(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = self._positions({"NVDA": 0.20, "AAPL": 0.80})
        modifier = compute_concentration_modifier(positions, ["NVDA"])
        assert modifier == 1.0

    def test_low_concentration_returns_attenuated_modifier(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = self._positions({"NVDA": 0.05, "AAPL": 0.95})
        modifier = compute_concentration_modifier(positions, ["NVDA"])
        assert modifier == 0.5

    def test_amplification_in_portfolio_impact_score(self, db):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        high = [{"ticker": "NVDA", "weight": 0.60, "active": True},
                {"ticker": "AMD",  "weight": 0.40, "active": True}]
        low  = [{"ticker": "NVDA", "weight": 0.05, "active": True},
                {"ticker": "AMD",  "weight": 0.95, "active": True}]
        high_mod = compute_concentration_modifier(high, ["NVDA"])
        low_mod  = compute_concentration_modifier(low,  ["NVDA"])
        assert high_mod > low_mod

    @pytest.mark.asyncio
    async def test_high_concentration_raises_portfolio_score(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid_high = _add_portfolio(db, name="high-conc")
        pid_low  = _add_portfolio(db, name="low-conc")
        _add_position(db, pid_high, "NVDA", weight=0.60)
        _add_position(db, pid_high, "AAPL", weight=0.40)
        _add_position(db, pid_low,  "NVDA", weight=0.05)
        _add_position(db, pid_low,  "AAPL", weight=0.95)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"])
        ctx_high = await compute_portfolio_scenario_impact(db, propagation, pid_high)
        ctx_low  = await compute_portfolio_scenario_impact(db, propagation, pid_low)
        assert ctx_high["portfolio_impact_score"] > ctx_low["portfolio_impact_score"]


# ---------------------------------------------------------------------------
# 4. No holdings case
# ---------------------------------------------------------------------------

class TestNoHoldingsCase:
    @pytest.mark.asyncio
    async def test_empty_portfolio_score_is_zero(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert ctx["portfolio_impact_score"] == 0.0
        assert ctx["held_tickers"] == []

    @pytest.mark.asyncio
    async def test_no_matching_tickers_score_is_zero(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "TSLA", weight=0.50)
        _add_position(db, pid, "AAPL", weight=0.50)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA", "AMD"])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert ctx["portfolio_impact_score"] == 0.0
        assert ctx["held_tickers"] == []

    @pytest.mark.asyncio
    async def test_exposure_chain_empty_when_none_held(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "TSLA")
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        assert chain == []

    @pytest.mark.asyncio
    async def test_no_holdings_concentration_modifier_is_05(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
            _CONC_MODIFIER_NONE,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "TSLA")
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert ctx["concentration_modifier"] == _CONC_MODIFIER_NONE


# ---------------------------------------------------------------------------
# 5–6. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_portfolio_invisible_to_user_b(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid_a = _add_portfolio(db, user_id="user-a")
        _add_position(db, pid_a, "NVDA", weight=0.50)
        await db.commit()

        # Propagation mentions pid_a (which belongs to user-a)
        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid_a],
        )
        # user-b requests enrichment — should not see user-a's portfolio
        result = await propagate_to_portfolio(db, propagation, user_id="user-b")
        assert result["portfolio_contexts"] == []

    @pytest.mark.asyncio
    async def test_user_a_portfolio_visible_to_user_a(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid_a = _add_portfolio(db, user_id="user-a")
        _add_position(db, pid_a, "NVDA", weight=0.50)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid_a],
        )
        result = await propagate_to_portfolio(db, propagation, user_id="user-a")
        assert len(result["portfolio_contexts"]) == 1
        assert result["portfolio_contexts"][0]["portfolio_id"] == pid_a

    @pytest.mark.asyncio
    async def test_global_context_sees_only_global_portfolios(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid_global = _add_portfolio(db, user_id=None, name="global")
        pid_user   = _add_portfolio(db, user_id="user-a", name="user")
        _add_position(db, pid_global, "NVDA", weight=0.50)
        _add_position(db, pid_user,   "NVDA", weight=0.50)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid_global, pid_user],
        )
        result = await propagate_to_portfolio(db, propagation, user_id=None)
        context_ids = [c["portfolio_id"] for c in result["portfolio_contexts"]]
        assert pid_global in context_ids
        assert pid_user not in context_ids

    @pytest.mark.asyncio
    async def test_global_portfolio_user_context_returns_zero(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid_global = _add_portfolio(db, user_id=None, name="global-2")
        _add_position(db, pid_global, "NVDA", weight=0.50)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid_global],
        )
        # user-x cannot see global portfolio
        result = await propagate_to_portfolio(db, propagation, user_id="user-x")
        assert result["portfolio_contexts"] == []


# ---------------------------------------------------------------------------
# 7. No portfolio mutation
# ---------------------------------------------------------------------------

class TestNoPortfolioMutation:
    @pytest.mark.asyncio
    async def test_source_propagation_unchanged(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.30)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid],
        )
        original_keys = set(propagation.keys())
        original_conf = propagation["impact_confidence"]
        original_portfolios = list(propagation["affected_portfolios"])

        await propagate_to_portfolio(db, propagation)

        assert set(propagation.keys()) == original_keys
        assert propagation["impact_confidence"] == original_conf
        assert propagation["affected_portfolios"] == original_portfolios

    @pytest.mark.asyncio
    async def test_portfolio_context_keys_not_in_source(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid = _add_portfolio(db)
        await db.commit()

        propagation = _make_propagation(affected_portfolios=[pid])
        assert "portfolio_contexts" not in propagation
        await propagate_to_portfolio(db, propagation)
        assert "portfolio_contexts" not in propagation


# ---------------------------------------------------------------------------
# 8. Null session safety
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_compute_exposure_chain_null(self):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        result = await compute_exposure_chain(None, "NVDA", "port-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_compute_portfolio_impact_null(self):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        propagation = _make_propagation()
        ctx = await compute_portfolio_scenario_impact(None, propagation, "port-1")
        assert isinstance(ctx, dict)
        assert ctx["portfolio_impact_score"] == 0.0

    @pytest.mark.asyncio
    async def test_propagate_to_portfolio_null(self):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        propagation = _make_propagation()
        result = await propagate_to_portfolio(None, propagation)
        assert isinstance(result, dict)
        assert result["portfolio_contexts"] == []

    def test_compute_concentration_modifier_empty(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        assert compute_concentration_modifier([], ["NVDA"]) == 0.5
        assert compute_concentration_modifier(None, ["NVDA"]) == 0.5
        assert compute_concentration_modifier([{"ticker": "NVDA", "weight": 0.5, "active": True}], []) == 0.5


# ---------------------------------------------------------------------------
# Output shape / range tests
# ---------------------------------------------------------------------------

class TestOutputShape:
    @pytest.mark.asyncio
    async def test_portfolio_impact_score_in_range(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=1.0)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid], confidence=0.9)
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert 0.0 <= ctx["portfolio_impact_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_concentration_modifier_in_range(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.5)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid])
        ctx = await compute_portfolio_scenario_impact(db, propagation, pid)
        assert 0.5 <= ctx["concentration_modifier"] <= 2.0

    @pytest.mark.asyncio
    async def test_propagate_preserves_original_keys(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid = _add_portfolio(db)
        await db.commit()

        propagation = _make_propagation(affected_portfolios=[pid])
        result = await propagate_to_portfolio(db, propagation)
        for key in _REQUIRED_PROPAGATION_KEYS:
            assert key in result, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_propagate_adds_portfolio_context_keys(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.3)
        await db.commit()

        propagation = _make_propagation(affected_tickers=["NVDA"], affected_portfolios=[pid])
        result = await propagate_to_portfolio(db, propagation)
        assert "portfolio_contexts" in result
        assert "portfolio_impact_score" in result
        assert "concentration_modifier" in result

    @pytest.mark.asyncio
    async def test_rollup_score_is_max_across_contexts(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid1 = _add_portfolio(db, name="p1")
        pid2 = _add_portfolio(db, name="p2")
        _add_position(db, pid1, "NVDA", weight=0.60)
        _add_position(db, pid2, "NVDA", weight=0.10)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid1, pid2],
        )
        result = await propagate_to_portfolio(db, propagation)
        ctx_scores = [c["portfolio_impact_score"] for c in result["portfolio_contexts"]]
        assert result["portfolio_impact_score"] == max(ctx_scores)

    @pytest.mark.asyncio
    async def test_rollup_modifier_is_max_across_contexts(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid1 = _add_portfolio(db, name="q1")
        pid2 = _add_portfolio(db, name="q2")
        _add_position(db, pid1, "NVDA", weight=0.60)
        _add_position(db, pid2, "NVDA", weight=0.05)
        await db.commit()

        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[pid1, pid2],
        )
        result = await propagate_to_portfolio(db, propagation)
        ctx_mods = [c["concentration_modifier"] for c in result["portfolio_contexts"]]
        assert result["concentration_modifier"] == max(ctx_mods)


# ---------------------------------------------------------------------------
# Exposure chain specific tests
# ---------------------------------------------------------------------------

class TestExposureChain:
    @pytest.mark.asyncio
    async def test_direct_ticker_has_depth_zero(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.25)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        nvda_entries = [e for e in chain if e["entity_key"] == "NVDA"]
        assert any(e["depth"] == 0 for e in nvda_entries)

    @pytest.mark.asyncio
    async def test_chain_entry_has_required_keys(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.25)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        assert len(chain) > 0
        entry = chain[0]
        for key in ("entity_key", "depth", "channel", "weight_pct"):
            assert key in entry

    @pytest.mark.asyncio
    async def test_chain_empty_for_empty_portfolio(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        assert chain == []

    @pytest.mark.asyncio
    async def test_weight_pct_reflects_position_weight(self, db):
        from app.services.scenario_portfolio_propagation import compute_exposure_chain
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.35)
        await db.commit()

        chain = await compute_exposure_chain(db, "NVDA", pid)
        nvda_entries = [e for e in chain if e["entity_key"] == "NVDA"]
        assert any(abs(e["weight_pct"] - 0.35) < 1e-6 for e in nvda_entries)


# ---------------------------------------------------------------------------
# 25. Empty affected_portfolios — discover from user
# ---------------------------------------------------------------------------

class TestDiscoverFromUser:
    @pytest.mark.asyncio
    async def test_discovers_user_portfolio_when_affected_empty(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        pid = _add_portfolio(db, user_id="user-discover")
        _add_position(db, pid, "NVDA", weight=0.30)
        await db.commit()

        # Propagation has no affected_portfolios
        propagation = _make_propagation(
            affected_tickers=["NVDA"],
            affected_portfolios=[],
        )
        result = await propagate_to_portfolio(db, propagation, user_id="user-discover")
        context_ids = [c["portfolio_id"] for c in result["portfolio_contexts"]]
        assert pid in context_ids

    @pytest.mark.asyncio
    async def test_no_portfolios_contexts_empty(self, db):
        from app.services.scenario_portfolio_propagation import propagate_to_portfolio
        propagation = _make_propagation(affected_portfolios=[])
        result = await propagate_to_portfolio(db, propagation, user_id=None)
        assert result["portfolio_contexts"] == []


# ---------------------------------------------------------------------------
# 30. Shared failure-mode amplification
# ---------------------------------------------------------------------------

class TestFailureModeAmplification:
    @pytest.mark.asyncio
    async def test_multiple_held_tickers_raises_score(self, db):
        from app.services.scenario_portfolio_propagation import (
            compute_portfolio_scenario_impact,
        )
        pid = _add_portfolio(db)
        _add_position(db, pid, "NVDA", weight=0.25)
        _add_position(db, pid, "AMD",  weight=0.25)
        _add_position(db, pid, "TSLA", weight=0.50)
        await db.commit()

        single_hit = _make_propagation(affected_tickers=["NVDA"])
        multi_hit  = _make_propagation(affected_tickers=["NVDA", "AMD"])

        ctx_single = await compute_portfolio_scenario_impact(db, single_hit, pid)
        ctx_multi  = await compute_portfolio_scenario_impact(db, multi_hit,  pid)
        assert ctx_multi["portfolio_impact_score"] > ctx_single["portfolio_impact_score"]

    def test_multiple_high_weight_holdings_max_modifier(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = [
            {"ticker": "NVDA", "weight": 0.30, "active": True},
            {"ticker": "AMD",  "weight": 0.25, "active": True},
            {"ticker": "TSLA", "weight": 0.45, "active": True},
        ]
        modifier = compute_concentration_modifier(positions, ["NVDA", "AMD"])
        assert modifier >= 1.5


# ---------------------------------------------------------------------------
# Concentration modifier edge cases
# ---------------------------------------------------------------------------

class TestConcentrationModifierEdgeCases:
    def test_inactive_positions_excluded(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        positions = [
            {"ticker": "NVDA", "weight": 0.90, "active": False},  # inactive
            {"ticker": "AAPL", "weight": 0.10, "active": True},
        ]
        modifier = compute_concentration_modifier(positions, ["NVDA"])
        # NVDA is inactive, so effective weight = 0
        assert modifier == 0.5

    def test_orm_object_positions(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier

        class FakePos:
            def __init__(self, ticker, weight, active=True):
                self.ticker = ticker
                self.weight = weight
                self.active = active

        # 0.35 ≥ _CONC_ELEVATED (0.30) but < _CONC_HIGH (0.50) → modifier 1.5
        positions = [FakePos("NVDA", 0.35), FakePos("AAPL", 0.65)]
        modifier = compute_concentration_modifier(positions, ["NVDA"])
        assert modifier == 1.5

    def test_no_weight_uses_equal_weight(self):
        from app.services.scenario_portfolio_propagation import compute_concentration_modifier
        # 3 positions, no weight — equal = 1/3 each
        positions = [
            {"ticker": "NVDA", "weight": None, "active": True},
            {"ticker": "AAPL", "weight": None, "active": True},
            {"ticker": "AMD",  "weight": None, "active": True},
        ]
        # NVDA and AMD affected → weight ≈ 0.667, both affected → 2.0
        modifier = compute_concentration_modifier(positions, ["NVDA", "AMD"])
        assert modifier == 2.0


# ---------------------------------------------------------------------------
# AST safety checks
# ---------------------------------------------------------------------------

class TestASTSafety:
    def _src(self):
        return _SVC.read_text(encoding="utf-8")

    def _imports(self):
        tree = ast.parse(self._src())
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
                modules.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                modules.extend(a.name for a in node.names)
        return modules

    def _calls(self):
        tree = ast.parse(self._src())
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
        return calls

    def _string_constants(self):
        src  = self._src()
        tree = ast.parse(src)
        # Collect IDs of docstring nodes to exclude them
        docstring_ids = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Module)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    docstring_ids.add(id(node.body[0].value))
        constants = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_ids:
                    constants.append(node.value)
        return constants

    def test_no_delivery_imports(self):
        forbidden = ["delivery_service", "notification_service"]
        violations = [m for m in self._imports() if any(f in m for f in forbidden)]
        assert not violations, f"Delivery imports: {violations}"

    def test_no_conviction_imports(self):
        forbidden = ["conviction_engine", "conviction_modeler"]
        violations = [m for m in self._imports() if any(f in m for f in forbidden)]
        assert not violations, f"Conviction imports: {violations}"

    def test_no_forecast_imports(self):
        forbidden = ["forecast_engine", "forecast_service", "forecast_vector"]
        violations = [m for m in self._imports() if any(f in m for f in forbidden)]
        assert not violations, f"Forecast imports: {violations}"

    def test_no_decision_write_calls(self):
        forbidden_writes = {
            "upsert_decision_priority", "upsert_forecast_vector",
            "upsert_scenario_snapshot", "add_run_log",
        }
        violations = [c for c in self._calls() if c in forbidden_writes]
        assert not violations, f"Write calls: {violations}"

    def test_no_recommendation_language(self):
        _BANNED = [
            "buy", "sell", "hold",
            "overweight", "underweight",
            "recommend",
            "target price", "position size",
            "take a position", "place an order",
            "execute", "go long", "go short",
            "open a position", "close a position",
            "rebalance",
        ]
        violations = []
        for const in self._string_constants():
            lower = const.lower()
            for phrase in _BANNED:
                if phrase in lower:
                    violations.append((phrase, const[:80]))
                    break
        assert not violations, f"Banned language in constants: {violations}"

    def test_no_portfolio_write_calls(self):
        portfolio_writes = {
            "portfolio_create", "portfolio_update", "portfolio_delete",
            "position_add", "position_update", "position_remove",
        }
        violations = [c for c in self._calls() if c in portfolio_writes]
        assert not violations, f"Portfolio write calls: {violations}"
