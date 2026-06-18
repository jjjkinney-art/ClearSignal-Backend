"""
Tests — Scenario Seed Builder, Phase 14 · Slice 2.

Covers:
  1.  null-session safety — build_seeds returns [] when session is None
  2.  empty substrate — build_seeds returns [] (not an exception) on empty DB
  3.  seed envelope keys — all required keys present in every seed
  4.  company_scenario — forecast_vector (company type) produces a seed
  5.  company_scenario — vector below signal floor (p_max < 0.5) is skipped
  6.  macro_scenario — forecast_vector (macro type) produces a seed
  7.  sector_scenario — forecast_vector (sector type) produces a seed
  8.  catalyst_scenario — open dossier_catalyst produces a seed
  9.  catalyst_scenario — non-open (triggered) catalyst is excluded
  10. failure_mode_scenario — dossier_failure_mode produces a seed
  11. portfolio_scenario — portfolio with active positions produces a seed
  12. portfolio_scenario — portfolio with no active positions produces no seed
  13. sparse substrate — missing secondary data produces seed, not exception
  14. deterministic — same substrate yields same seed count
  15. target filter restricts by ticker
  16. target filter empty means all tickers eligible
  17. seed_types kwarg restricts which sub-builders run
  18. no DB writes — source-table row counts unchanged after build_seeds
  19. no scenario_snapshot writes — ScenarioSnapshot count unchanged
  20. no scenario_run_log writes — ScenarioRunLog count unchanged
  21. seed has no advice language (AST — no buy/sell/hold/target_price)
  22. no conviction/recommendation imports (AST)
  23. no forecast write-back (AST — no write functions imported)
  24. no decision write-back (AST — no decision write functions)
  25. no scenario_repo import (AST — seeds must not touch snapshot table)
  26. ALL_SEED_TYPES completeness — 6 entries
  27. tenant isolation — user_id scoping is respected
  28. affected_tickers list is present and is a list
  29. affected_portfolios list is present and is a list
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_seed_builder.py"

_REQUIRED_SEED_KEYS = {
    "scenario_type",
    "entity_type",
    "entity_id",
    "ticker",
    "scenario_name",
    "changed_assumption",
    "source_type",
    "source_id",
    "affected_tickers",
    "affected_portfolios",
    "evidence_refs",
    "transmission_inputs",
    "impact_inputs",
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


async def _seed_forecast_vector(
    db, *, ticker="NVDA", entity_type="company",
    p_pos=0.70, p_neg=0.20, p_neu=0.10,
    horizon="near_term", forecast_type="thesis_strengthening",
    user_id=None,
) -> object:
    from app.db.repositories import forecast_repo
    return await forecast_repo.upsert_forecast_vector(
        db,
        entity_type=entity_type,
        entity_key=ticker,
        horizon=horizon,
        horizon_days=30,
        forecast_type=forecast_type,
        p_positive=p_pos,
        p_negative=p_neg,
        p_neutral=p_neu,
        confidence_band_low=0.55,
        confidence_band_high=0.85,
        why=f"{ticker} {entity_type} signal",
        invalidators=["macro reversal"],
        analog_basis=[],
        similarity_basis=[],
        evidence_summary=[],
        source_versions={"source": "v1"},
        forecast_schema=1,
        user_id=user_id,
    )


async def _seed_catalyst(
    db, *, ticker="NVDA", status="open", direction="bull_trigger",
    user_id=None,
) -> object:
    from app.db.models import DossierCatalyst
    row = DossierCatalyst(
        id=_uid(),
        ticker=ticker,
        statement=f"{ticker} catalyst event",
        direction=direction,
        specificity=0.80,
        expected_window="Q3 2026",
        status=status,
        conviction_weight=0.6,
        user_id=user_id,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_failure_mode(db, *, ticker="NVDA", user_id=None) -> object:
    from app.db.models import DossierFailureMode
    row = DossierFailureMode(
        id=_uid(),
        ticker=ticker,
        analog_id=_uid(),
        sequence_stage=2,
        stage_evidence="Stage 2 signals observed",
        relevance_at_match=0.75,
        matched_at=_now(),
        user_id=user_id,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_portfolio_and_position(
    db, *, ticker="NVDA", active=True, user_id=None, weight=0.15,
) -> tuple:
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


# ---------------------------------------------------------------------------
# 1. Null-session safety
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_session_is_none(self):
        from app.services.scenario_seed_builder import build_seeds
        result = await build_seeds(None)
        assert result == []


# ---------------------------------------------------------------------------
# 2. Empty substrate
# ---------------------------------------------------------------------------

class TestEmptySubstrate:
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_empty_db(self, db):
        from app.services.scenario_seed_builder import build_seeds
        result = await build_seeds(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_exception_on_empty_db(self, db):
        from app.services.scenario_seed_builder import build_seeds
        try:
            result = await build_seeds(db)
            assert isinstance(result, list)
        except Exception as exc:
            pytest.fail(f"build_seeds raised on empty DB: {exc}")


# ---------------------------------------------------------------------------
# 3. Seed envelope keys
# ---------------------------------------------------------------------------

class TestSeedEnvelopeKeys:
    @pytest.mark.asyncio
    async def test_all_required_keys_present(self, db):
        from app.services.scenario_seed_builder import build_seeds
        await _seed_forecast_vector(db, ticker="NVDA")
        await db.commit()
        seeds = await build_seeds(db)
        assert seeds, "Expected at least one seed"
        for seed in seeds:
            missing = _REQUIRED_SEED_KEYS - seed.keys()
            assert not missing, f"Seed missing keys: {missing}\n  seed={seed}"


# ---------------------------------------------------------------------------
# 4. company_scenario — produced from company ForecastVector
# ---------------------------------------------------------------------------

class TestCompanySeed:
    @pytest.mark.asyncio
    async def test_company_seed_produced(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        assert any(s["scenario_type"] == SEED_TYPE_COMPANY for s in seeds)

    @pytest.mark.asyncio
    async def test_company_seed_has_correct_entity_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="AAPL", entity_type="company")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        company_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_COMPANY]
        assert all(s["entity_type"] == "company" for s in company_seeds)

    @pytest.mark.asyncio
    async def test_company_seed_ticker_matches_source(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="TSLA", entity_type="company", p_pos=0.80)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        tickers = [s["ticker"] for s in seeds if s["scenario_type"] == SEED_TYPE_COMPANY]
        assert "TSLA" in tickers

    # 5. Signal floor
    @pytest.mark.asyncio
    async def test_below_signal_floor_skipped(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        # p_max = max(0.30, 0.25) = 0.30 < floor 0.50
        await _seed_forecast_vector(db, ticker="WEAK", entity_type="company",
                                     p_pos=0.30, p_neg=0.25, p_neu=0.45)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        company_tickers = [s["ticker"] for s in seeds if s["scenario_type"] == SEED_TYPE_COMPANY]
        assert "WEAK" not in company_tickers


# ---------------------------------------------------------------------------
# 6. macro_scenario
# ---------------------------------------------------------------------------

class TestMacroSeed:
    @pytest.mark.asyncio
    async def test_macro_seed_produced(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_MACRO
        await _seed_forecast_vector(db, ticker="RATES", entity_type="macro", p_pos=0.65)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_MACRO,))
        assert any(s["scenario_type"] == SEED_TYPE_MACRO for s in seeds)

    @pytest.mark.asyncio
    async def test_macro_seed_entity_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_MACRO
        await _seed_forecast_vector(db, ticker="INFLATION", entity_type="macro", p_pos=0.70)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_MACRO,))
        macro_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_MACRO]
        assert all(s["entity_type"] == "macro" for s in macro_seeds)

    @pytest.mark.asyncio
    async def test_macro_seed_ticker_is_empty(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_MACRO
        await _seed_forecast_vector(db, ticker="GDP", entity_type="macro", p_pos=0.68)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_MACRO,))
        macro_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_MACRO]
        assert all(s["ticker"] == "" for s in macro_seeds)


# ---------------------------------------------------------------------------
# 7. sector_scenario
# ---------------------------------------------------------------------------

class TestSectorSeed:
    @pytest.mark.asyncio
    async def test_sector_seed_produced(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_SECTOR
        await _seed_forecast_vector(db, ticker="SEMIS", entity_type="sector", p_pos=0.60)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_SECTOR,))
        assert any(s["scenario_type"] == SEED_TYPE_SECTOR for s in seeds)

    @pytest.mark.asyncio
    async def test_sector_seed_entity_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_SECTOR
        await _seed_forecast_vector(db, ticker="ENERGY", entity_type="sector", p_neg=0.65,
                                     p_pos=0.20, p_neu=0.15)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_SECTOR,))
        sector_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_SECTOR]
        assert all(s["entity_type"] == "sector" for s in sector_seeds)


# ---------------------------------------------------------------------------
# 8–9. catalyst_scenario
# ---------------------------------------------------------------------------

class TestCatalystSeed:
    @pytest.mark.asyncio
    async def test_open_catalyst_produces_seed(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_CATALYST
        await _seed_catalyst(db, ticker="NVDA", status="open")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_CATALYST,))
        assert any(s["scenario_type"] == SEED_TYPE_CATALYST for s in seeds)

    @pytest.mark.asyncio
    async def test_triggered_catalyst_excluded(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_CATALYST
        await _seed_catalyst(db, ticker="NVDA", status="triggered")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_CATALYST,))
        assert not any(s["scenario_type"] == SEED_TYPE_CATALYST for s in seeds)

    @pytest.mark.asyncio
    async def test_catalyst_seed_source_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_CATALYST
        await _seed_catalyst(db, ticker="AAPL", status="open")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_CATALYST,))
        catalyst_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_CATALYST]
        assert all(s["source_type"] == "dossier_catalyst" for s in catalyst_seeds)


# ---------------------------------------------------------------------------
# 10. failure_mode_scenario
# ---------------------------------------------------------------------------

class TestFailureModeSeed:
    @pytest.mark.asyncio
    async def test_failure_mode_produces_seed(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_FAILURE_MODE
        await _seed_failure_mode(db, ticker="NVDA")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_FAILURE_MODE,))
        assert any(s["scenario_type"] == SEED_TYPE_FAILURE_MODE for s in seeds)

    @pytest.mark.asyncio
    async def test_failure_mode_source_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_FAILURE_MODE
        await _seed_failure_mode(db, ticker="TSLA")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_FAILURE_MODE,))
        fm_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_FAILURE_MODE]
        assert all(s["source_type"] == "dossier_failure_mode" for s in fm_seeds)


# ---------------------------------------------------------------------------
# 11–12. portfolio_scenario
# ---------------------------------------------------------------------------

class TestPortfolioSeed:
    @pytest.mark.asyncio
    async def test_portfolio_with_positions_produces_seed(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_PORTFOLIO
        await _seed_portfolio_and_position(db, ticker="NVDA", active=True)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_PORTFOLIO,))
        assert any(s["scenario_type"] == SEED_TYPE_PORTFOLIO for s in seeds)

    @pytest.mark.asyncio
    async def test_portfolio_seed_affected_tickers(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_PORTFOLIO
        await _seed_portfolio_and_position(db, ticker="NVDA", active=True)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_PORTFOLIO,))
        port_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_PORTFOLIO]
        assert all("NVDA" in s["affected_tickers"] for s in port_seeds)

    @pytest.mark.asyncio
    async def test_portfolio_without_active_positions_produces_no_seed(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_PORTFOLIO
        # Inactive position
        await _seed_portfolio_and_position(db, ticker="NVDA", active=False)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_PORTFOLIO,))
        assert not any(s["scenario_type"] == SEED_TYPE_PORTFOLIO for s in seeds)

    @pytest.mark.asyncio
    async def test_portfolio_seed_entity_type(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_PORTFOLIO
        await _seed_portfolio_and_position(db, ticker="AAPL", active=True)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_PORTFOLIO,))
        port_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_PORTFOLIO]
        assert all(s["entity_type"] == "portfolio" for s in port_seeds)


# ---------------------------------------------------------------------------
# 13. Sparse substrate — no exception when secondary data is absent
# ---------------------------------------------------------------------------

class TestSparseSubstrate:
    @pytest.mark.asyncio
    async def test_company_seed_no_exception_without_similarity_data(self, db):
        """No similarity or cross-exposure data → sparse seed, not exception."""
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await db.commit()
        try:
            seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
            assert isinstance(seeds, list)
            assert len(seeds) >= 1
        except Exception as exc:
            pytest.fail(f"build_seeds raised on sparse company substrate: {exc}")

    @pytest.mark.asyncio
    async def test_catalyst_seed_no_exception_without_cross_exposure(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_CATALYST
        await _seed_catalyst(db, ticker="NVDA", status="open")
        await db.commit()
        try:
            seeds = await build_seeds(db, seed_types=(SEED_TYPE_CATALYST,))
            assert isinstance(seeds, list)
        except Exception as exc:
            pytest.fail(f"build_seeds raised on sparse catalyst substrate: {exc}")

    @pytest.mark.asyncio
    async def test_affected_tickers_is_list_when_no_secondary_data(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        for seed in seeds:
            assert isinstance(seed["affected_tickers"], list)
            assert isinstance(seed["affected_portfolios"], list)


# ---------------------------------------------------------------------------
# 14. Deterministic output
# ---------------------------------------------------------------------------

class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_substrate_same_seed_count(self, db):
        from app.services.scenario_seed_builder import build_seeds
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_catalyst(db, ticker="AAPL", status="open")
        await db.commit()
        seeds_a = await build_seeds(db)
        seeds_b = await build_seeds(db)
        assert len(seeds_a) == len(seeds_b)


# ---------------------------------------------------------------------------
# 15–16. Target filter
# ---------------------------------------------------------------------------

class TestTargetFilter:
    @pytest.mark.asyncio
    async def test_target_filter_restricts_to_ticker(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_forecast_vector(db, ticker="AAPL", entity_type="company")
        await db.commit()
        seeds = await build_seeds(db, targets="NVDA", seed_types=(SEED_TYPE_COMPANY,))
        company_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_COMPANY]
        tickers = {s["ticker"] for s in company_seeds}
        assert tickers.issubset({"NVDA", ""})

    @pytest.mark.asyncio
    async def test_target_filter_excludes_non_matching_ticker(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="AAPL", entity_type="company")
        await db.commit()
        seeds = await build_seeds(db, targets="NVDA", seed_types=(SEED_TYPE_COMPANY,))
        aapl_seeds = [s for s in seeds if s.get("ticker") == "AAPL"]
        assert aapl_seeds == []

    @pytest.mark.asyncio
    async def test_empty_target_means_all_eligible(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_forecast_vector(db, ticker="AAPL", entity_type="company")
        await db.commit()
        seeds_all   = await build_seeds(db, targets="",   seed_types=(SEED_TYPE_COMPANY,))
        seeds_none  = await build_seeds(db, targets=None, seed_types=(SEED_TYPE_COMPANY,))
        assert len(seeds_all) == len(seeds_none)
        assert len(seeds_all) >= 2


# ---------------------------------------------------------------------------
# 17. seed_types kwarg
# ---------------------------------------------------------------------------

class TestSeedTypesFilter:
    @pytest.mark.asyncio
    async def test_seed_types_restricts_sub_builders(self, db):
        from app.services.scenario_seed_builder import (
            build_seeds, SEED_TYPE_COMPANY, SEED_TYPE_CATALYST,
        )
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_catalyst(db, ticker="NVDA", status="open")
        await db.commit()
        company_only = await build_seeds(db, seed_types=(SEED_TYPE_COMPANY,))
        catalyst_only = await build_seeds(db, seed_types=(SEED_TYPE_CATALYST,))
        assert all(s["scenario_type"] == SEED_TYPE_COMPANY  for s in company_only)
        assert all(s["scenario_type"] == SEED_TYPE_CATALYST for s in catalyst_only)


# ---------------------------------------------------------------------------
# 18–20. No DB writes
# ---------------------------------------------------------------------------

class TestNoDbWrites:
    async def _row_counts(self, db):
        from app.db.models import (
            ForecastVector, DecisionPriority, DossierCatalyst,
            ScenarioSnapshot, ScenarioRunLog, ScenarioEvidence,
        )
        counts = {}
        for model in (ForecastVector, DecisionPriority, DossierCatalyst,
                      ScenarioSnapshot, ScenarioRunLog, ScenarioEvidence):
            n = (await db.execute(
                select(func.count()).select_from(model)
            )).scalar_one()
            counts[model.__tablename__] = n
        return counts

    @pytest.mark.asyncio
    async def test_source_table_counts_unchanged(self, db):
        from app.services.scenario_seed_builder import build_seeds
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_catalyst(db, ticker="NVDA", status="open")
        await db.commit()

        before = await self._row_counts(db)
        await build_seeds(db)
        after = await self._row_counts(db)

        assert before == after, (
            f"Row counts changed after build_seeds: {before} → {after}"
        )

    @pytest.mark.asyncio
    async def test_no_scenario_snapshot_written(self, db):
        from app.services.scenario_seed_builder import build_seeds
        from app.db.models import ScenarioSnapshot
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await db.commit()
        await build_seeds(db)
        n = (await db.execute(
            select(func.count()).select_from(ScenarioSnapshot)
        )).scalar_one()
        assert n == 0

    @pytest.mark.asyncio
    async def test_no_scenario_run_log_written(self, db):
        from app.services.scenario_seed_builder import build_seeds
        from app.db.models import ScenarioRunLog
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await db.commit()
        await build_seeds(db)
        n = (await db.execute(
            select(func.count()).select_from(ScenarioRunLog)
        )).scalar_one()
        assert n == 0


# ---------------------------------------------------------------------------
# 21. No advice language (AST)
# ---------------------------------------------------------------------------

class TestNoAdviceLanguage:
    def _load_src(self):
        return _SVC.read_text(encoding="utf-8")

    def _non_docstring_constants(self):
        """Walk all string constants, skipping module/class/function docstrings."""
        tree = ast.parse(self._load_src())
        docstring_ids: set = set()
        for node in ast.walk(tree):
            # First statement of a module/class/function body that is a bare Expr(Constant)
            body = None
            if isinstance(node, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                inner = body[0].value
                if isinstance(inner, ast.Constant):
                    docstring_ids.add(id(inner))

        constants = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_ids:
                    constants.append(node.value)
        return constants

    def test_no_buy_in_string_constants(self):
        for val in self._non_docstring_constants():
            low = val.lower()
            for term in ("buy ", " buy", "sell ", " sell", "hold ", " hold"):
                assert term not in low, (
                    f"Advice term {term!r} found in non-docstring string constant: {val!r}"
                )

    def test_no_target_price_in_string_constants(self):
        src = self._load_src()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                low = node.value.lower()
                for term in ("target_price", "price_target", "position_size"):
                    assert term not in low, (
                        f"Forbidden term {term!r} in string constant: {node.value!r}"
                    )

    def test_no_recommendation_language(self):
        src = self._load_src().lower()
        # Check identifiers and attribute names — not inside the module docstring
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert "recommend" not in node.id.lower(), (
                    f"'recommend' found in identifier: {node.id}"
                )


# ---------------------------------------------------------------------------
# 22. No conviction/recommendation imports (AST)
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    def _imports(self):
        src = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        return imported

    def test_no_conviction_imports(self):
        forbidden = [
            "conviction_engine", "conviction_modeler",
            "recommendation", "stance_engine",
            "order_engine", "execution_engine",
        ]
        imported = self._imports()
        violations = [n for n in imported if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Forbidden imports in scenario_seed_builder: {violations}"

    def test_no_scenario_repo_import(self):
        """Seed builder must not import scenario_repo — seeds are inputs, not writes."""
        imported = self._imports()
        violations = [n for n in imported if "scenario_repo" in n.lower()]
        assert not violations, (
            f"scenario_repo imported in scenario_seed_builder: {violations}"
        )


# ---------------------------------------------------------------------------
# 23. No forecast write-back (AST)
# ---------------------------------------------------------------------------

class TestNoForecastWriteback:
    def test_no_forecast_write_functions_called(self):
        src = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        write_fns = {
            "upsert_forecast_vector", "add_forecast_evidence",
            "add_calibration_log", "delete_forecast_vector",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in write_fns, (
                        f"Forecast write function {node.func.attr!r} called in seed builder"
                    )
                elif isinstance(node.func, ast.Name):
                    assert node.func.id not in write_fns, (
                        f"Forecast write function {node.func.id!r} called in seed builder"
                    )


# ---------------------------------------------------------------------------
# 24. No decision write-back (AST)
# ---------------------------------------------------------------------------

class TestNoDecisionWriteback:
    def test_no_decision_write_functions_called(self):
        src = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        write_fns = {
            "upsert_decision_priority", "add_decision_evidence",
            "add_ranking_log", "delete_decision_priority",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in write_fns, (
                        f"Decision write function {node.func.attr!r} called in seed builder"
                    )
                elif isinstance(node.func, ast.Name):
                    assert node.func.id not in write_fns, (
                        f"Decision write function {node.func.id!r} called in seed builder"
                    )


# ---------------------------------------------------------------------------
# 25. No scenario_repo import already covered in 22 — add AST check on writes
# ---------------------------------------------------------------------------

class TestNoScenarioRepoUsage:
    def test_no_scenario_repo_import_in_ast(self):
        """scenario_repo must not be imported anywhere in the module (AST check)."""
        src = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                full = node.module or ""
                assert "scenario_repo" not in full, (
                    f"scenario_repo imported via 'from {full} import ...'"
                )
                for alias in node.names:
                    assert "scenario_repo" not in alias.name, (
                        f"scenario_repo imported as alias: {alias.name}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert "scenario_repo" not in alias.name, (
                        f"scenario_repo imported: {alias.name}"
                    )


# ---------------------------------------------------------------------------
# 26. ALL_SEED_TYPES completeness
# ---------------------------------------------------------------------------

class TestSeedTypesCompleteness:
    def test_all_seed_types_has_six_entries(self):
        from app.services.scenario_seed_builder import ALL_SEED_TYPES
        assert len(ALL_SEED_TYPES) == 6, (
            f"Expected 6 seed types, found {len(ALL_SEED_TYPES)}: {ALL_SEED_TYPES}"
        )

    def test_all_seed_types_has_expected_values(self):
        from app.services.scenario_seed_builder import (
            ALL_SEED_TYPES,
            SEED_TYPE_COMPANY, SEED_TYPE_MACRO, SEED_TYPE_SECTOR,
            SEED_TYPE_CATALYST, SEED_TYPE_FAILURE_MODE, SEED_TYPE_PORTFOLIO,
        )
        expected = {
            SEED_TYPE_COMPANY, SEED_TYPE_MACRO, SEED_TYPE_SECTOR,
            SEED_TYPE_CATALYST, SEED_TYPE_FAILURE_MODE, SEED_TYPE_PORTFOLIO,
        }
        assert set(ALL_SEED_TYPES) == expected


# ---------------------------------------------------------------------------
# 27. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_forecast_not_in_user_b_seeds(self, db):
        """ForecastVectors scoped to user-A must not appear in user-B seeds."""
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        uid_a = "user-aaa"
        uid_b = "user-bbb"
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company",
                                     user_id=uid_a)
        await db.commit()
        seeds_b = await build_seeds(db, user_id=uid_b,
                                     seed_types=(SEED_TYPE_COMPANY,))
        nvda_seeds = [s for s in seeds_b if s["ticker"] == "NVDA"]
        assert nvda_seeds == [], (
            f"user-B should not see user-A's NVDA seed, found: {nvda_seeds}"
        )

    @pytest.mark.asyncio
    async def test_user_id_passthrough(self, db):
        """Seeds include the user_id that was passed to build_seeds."""
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_COMPANY
        uid = "user-xyz"
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company",
                                     user_id=uid)
        await db.commit()
        seeds = await build_seeds(db, user_id=uid, seed_types=(SEED_TYPE_COMPANY,))
        for seed in seeds:
            assert seed["user_id"] == uid, (
                f"Expected user_id={uid!r}, got {seed['user_id']!r}"
            )


# ---------------------------------------------------------------------------
# 28–29. affected_tickers and affected_portfolios always lists
# ---------------------------------------------------------------------------

class TestAffectedLists:
    @pytest.mark.asyncio
    async def test_all_seeds_have_list_affected_tickers(self, db):
        from app.services.scenario_seed_builder import build_seeds
        await _seed_forecast_vector(db, ticker="NVDA", entity_type="company")
        await _seed_catalyst(db, ticker="AAPL", status="open")
        await _seed_failure_mode(db, ticker="TSLA")
        await _seed_portfolio_and_position(db, ticker="MSFT", active=True)
        await db.commit()
        seeds = await build_seeds(db)
        for seed in seeds:
            assert isinstance(seed["affected_tickers"], list), (
                f"affected_tickers is not a list in {seed['scenario_type']} seed"
            )
            assert isinstance(seed["affected_portfolios"], list), (
                f"affected_portfolios is not a list in {seed['scenario_type']} seed"
            )

    @pytest.mark.asyncio
    async def test_portfolio_seed_affected_portfolios_not_empty(self, db):
        from app.services.scenario_seed_builder import build_seeds, SEED_TYPE_PORTFOLIO
        await _seed_portfolio_and_position(db, ticker="NVDA", active=True)
        await db.commit()
        seeds = await build_seeds(db, seed_types=(SEED_TYPE_PORTFOLIO,))
        port_seeds = [s for s in seeds if s["scenario_type"] == SEED_TYPE_PORTFOLIO]
        assert all(len(s["affected_portfolios"]) > 0 for s in port_seeds)
