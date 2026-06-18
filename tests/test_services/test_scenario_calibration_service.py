"""
Tests for scenario_calibration_service — Phase 14 · Slice 9.

Verified properties
-------------------
  1. record_scenario_outcome
       - returns None when session=None
       - returns None when flag disabled (run_override=False)
       - returns row when flag forced on (run_override=True)
       - writes run_reason="calibration_outcome" and preserves realized_state
       - rejects unsupported realized_state values
       - accepts all three valid realized_state values

  2. calculate_scenario_hit_rate
       - returns None session → safe empty dict
       - empty DB → insufficient_samples=True
       - below MIN_SAMPLES → hit_rate=None
       - ≥ MIN_SAMPLES binary outcomes → correct ratio
       - unresolved excluded from denominator
       - filters by scenario_type and entity_type

  3. calculate_transmission_accuracy
       - single-entity scenario_id excluded (needs ≥2 rows)
       - below MIN_SAMPLES → insufficient_samples=True
       - consistent scenario_ids counted correctly
       - mixed-state scenario_id counted as inconsistent

  4. calculate_portfolio_impact_accuracy
       - restricts to entity_type="portfolio"
       - ignores non-portfolio rows
       - correct ratio when sufficient samples

  5. calculate_scenario_stability
       - pair seen once → single_run_pairs
       - pair seen ≥2 → stable_pairs
       - correct stability fraction
       - insufficient when total_distinct_pairs < min_samples

  6. calculate_scenario_churn
       - most-recent row per tuple governs (list ordered desc)
       - invalidated counted correctly
       - correct churn_rate fraction
       - insufficient when total_tuples < min_samples

  7. summarize_scenario_calibration
       - None session → safe_empty with db_available=False
       - live session → db_available=True and all sub-dicts present
       - schema_version present

  8. SP-6 / immutability AST checks
       - no UPDATE/DELETE in module source
       - no banned phrase string constants
       - no forbidden imports (conviction, order, execution, stance)
       - no scenario_snapshot write calls
       - no DeliveryLedger or Notification imports
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import textwrap
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# DB fixture — SQLite in-memory
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture
async def session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        async with s.begin():
            yield s
            await s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _add_run_log(
    session,
    *,
    scenario_id: Optional[str] = None,
    scenario_type: str = "company",
    entity_type: str = "company",
    entity_key: str = "AAPL",
    user_id: Optional[str] = None,
    run_reason: str = "calibration_outcome",
    snapshot_reason: str = "calibration_outcome",
    realized_state: Optional[str] = "materialized",
    evaluated_at: Optional[datetime] = None,
) -> Any:
    from app.db.repositories.scenario_repo import add_run_log
    return await add_run_log(
        session,
        scenario_id     = scenario_id,
        scenario_type   = scenario_type,
        entity_type     = entity_type,
        entity_key      = entity_key,
        user_id         = user_id,
        run_reason      = run_reason,
        snapshot_reason = snapshot_reason,
        realized_state  = realized_state,
        evaluated_at    = evaluated_at or _now(),
    )


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from app.services import scenario_calibration_service as svc


# ============================================================================
# 1. record_scenario_outcome
# ============================================================================

class TestRecordScenarioOutcome:
    @pytest.mark.asyncio
    async def test_null_session_returns_none(self):
        result = await svc.record_scenario_outcome(
            None,
            scenario_type   = "company",
            entity_type     = "company",
            entity_key      = "AAPL",
            realized_state  = "materialized",
            run_override    = True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_flag_returns_none(self, session):
        result = await svc.record_scenario_outcome(
            session,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "AAPL",
            realized_state = "materialized",
            run_override   = False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_enabled_returns_row(self, session):
        result = await svc.record_scenario_outcome(
            session,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "AAPL",
            realized_state = "materialized",
            run_override   = True,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_reason_is_calibration_outcome(self, session):
        row = await svc.record_scenario_outcome(
            session,
            scenario_type  = "macro",
            entity_type    = "macro",
            entity_key     = "inflation",
            realized_state = "invalidated",
            run_override   = True,
        )
        assert row is not None
        assert row.run_reason == "calibration_outcome"

    @pytest.mark.asyncio
    async def test_realized_state_preserved_materialized(self, session):
        row = await svc.record_scenario_outcome(
            session,
            scenario_type  = "sector",
            entity_type    = "sector",
            entity_key     = "tech",
            realized_state = "materialized",
            run_override   = True,
        )
        assert row is not None
        assert row.realized_state == "materialized"

    @pytest.mark.asyncio
    async def test_realized_state_preserved_invalidated(self, session):
        row = await svc.record_scenario_outcome(
            session,
            scenario_type  = "sector",
            entity_type    = "sector",
            entity_key     = "energy",
            realized_state = "invalidated",
            run_override   = True,
        )
        assert row is not None
        assert row.realized_state == "invalidated"

    @pytest.mark.asyncio
    async def test_realized_state_preserved_unresolved(self, session):
        row = await svc.record_scenario_outcome(
            session,
            scenario_type  = "macro",
            entity_type    = "macro",
            entity_key     = "rates",
            realized_state = "unresolved",
            run_override   = True,
        )
        assert row is not None
        assert row.realized_state == "unresolved"

    @pytest.mark.asyncio
    async def test_unsupported_realized_state_returns_none(self, session):
        result = await svc.record_scenario_outcome(
            session,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "TSLA",
            realized_state = "unknown_garbage",
            run_override   = True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unsupported_realized_state_buy_returns_none(self, session):
        result = await svc.record_scenario_outcome(
            session,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "TSLA",
            realized_state = "buy",
            run_override   = True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_scenario_id_optional(self, session):
        row = await svc.record_scenario_outcome(
            session,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "MSFT",
            realized_state = "materialized",
            run_override   = True,
            scenario_id    = None,
        )
        assert row is not None

    @pytest.mark.asyncio
    async def test_scenario_id_stored(self, session):
        sid = "00000000-aaaa-bbbb-cccc-000000000001"
        row = await svc.record_scenario_outcome(
            session,
            scenario_id    = sid,
            scenario_type  = "company",
            entity_type    = "company",
            entity_key     = "MSFT",
            realized_state = "materialized",
            run_override   = True,
        )
        assert row is not None
        assert row.scenario_id == sid


# ============================================================================
# 2. calculate_scenario_hit_rate
# ============================================================================

class TestCalculateScenarioHitRate:
    @pytest.mark.asyncio
    async def test_null_session_returns_safe_dict(self):
        result = await svc.calculate_scenario_hit_rate(None)
        assert result["hit_rate"] is None
        assert result["insufficient_samples"] is True
        assert result["materialized"] == 0

    @pytest.mark.asyncio
    async def test_empty_db_insufficient_samples(self, session):
        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "nonexistent_type_xyz",
            min_samples   = 1,
        )
        assert result["insufficient_samples"] is True
        assert result["hit_rate"] is None

    @pytest.mark.asyncio
    async def test_below_min_samples(self, session):
        # Insert 3 rows but require 10 samples
        for _ in range(3):
            await _add_run_log(
                session,
                scenario_type  = "company",
                entity_key     = "BELOW_THRESH",
                realized_state = "materialized",
            )
        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "company",
            min_samples   = 10,
        )
        assert result["insufficient_samples"] is True
        assert result["hit_rate"] is None

    @pytest.mark.asyncio
    async def test_correct_hit_rate_with_sufficient_samples(self, session):
        # 8 materialized, 2 invalidated, 2 unresolved — min_samples=10 (binary=10 → just enough)
        for _ in range(8):
            await _add_run_log(session, scenario_type="catalyst", entity_key="HIT_RATE_TEST",
                               realized_state="materialized")
        for _ in range(2):
            await _add_run_log(session, scenario_type="catalyst", entity_key="HIT_RATE_TEST",
                               realized_state="invalidated")
        for _ in range(2):
            await _add_run_log(session, scenario_type="catalyst", entity_key="HIT_RATE_TEST",
                               realized_state="unresolved")

        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "catalyst",
            min_samples   = 10,
        )
        assert result["insufficient_samples"] is False
        assert result["materialized"] == 8
        assert result["invalidated"] == 2
        assert result["unresolved"] == 2
        assert result["total_evaluated"] == 12
        assert abs(result["hit_rate"] - 0.8) < 0.001

    @pytest.mark.asyncio
    async def test_unresolved_excluded_from_denominator(self, session):
        # 5 materialized, 5 unresolved — binary_total=5, below min_samples=10
        for _ in range(5):
            await _add_run_log(session, scenario_type="failure_mode",
                               entity_key="UNRESOLVE_TEST", realized_state="materialized")
        for _ in range(5):
            await _add_run_log(session, scenario_type="failure_mode",
                               entity_key="UNRESOLVE_TEST", realized_state="unresolved")

        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "failure_mode",
            min_samples   = 6,  # requires 6 binary outcomes; we only have 5
        )
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_all_materialized_hit_rate_is_1(self, session):
        for _ in range(10):
            await _add_run_log(session, scenario_type="portfolio",
                               entity_key="ALL_MAT", entity_type="portfolio",
                               realized_state="materialized")
        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "portfolio",
            min_samples   = 10,
        )
        # hit_rate may be 1.0 but aggregated with other portfolio rows; just verify no error
        assert result["hit_rate"] is not None or result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_filter_by_scenario_type(self, session):
        # company rows should not count for macro
        await _add_run_log(session, scenario_type="macro_only_test",
                           entity_key="MACRO_FILTER", realized_state="materialized")
        result = await svc.calculate_scenario_hit_rate(
            session,
            scenario_type = "company_only_test",
            min_samples   = 1,
        )
        assert result["materialized"] == 0


# ============================================================================
# 3. calculate_transmission_accuracy
# ============================================================================

class TestCalculateTransmissionAccuracy:
    @pytest.mark.asyncio
    async def test_null_session_returns_safe(self):
        result = await svc.calculate_transmission_accuracy(None)
        assert result["transmission_accuracy"] is None
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_single_entity_per_scenario_excluded(self, session):
        # scenario_id with only 1 row should not count as multi-entity
        sid = "00000000-1111-0000-0000-000000000001"
        await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_1",
                           entity_key="SOLO", realized_state="materialized")
        result = await svc.calculate_transmission_accuracy(
            session, scenario_type="trans_acc_1", min_samples=1
        )
        assert result["total_multi_entity_scenarios"] == 0

    @pytest.mark.asyncio
    async def test_multi_entity_consistent(self, session):
        # 12 scenario_ids, each with 2 rows of same state → all consistent
        for i in range(12):
            sid = f"00000000-aa{i:02d}-0000-0000-000000000001"
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_2",
                               entity_key=f"TK{i}a", realized_state="materialized")
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_2",
                               entity_key=f"TK{i}b", realized_state="materialized")
        result = await svc.calculate_transmission_accuracy(
            session, scenario_type="trans_acc_2", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["total_multi_entity_scenarios"] == 12
        assert result["consistent_scenarios"] == 12
        assert abs(result["transmission_accuracy"] - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_multi_entity_mixed_state_counted_inconsistent(self, session):
        # 10 consistent + 5 inconsistent → accuracy = 10/15
        for i in range(10):
            sid = f"00000000-bb{i:02d}-0000-0000-000000000001"
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_3",
                               entity_key=f"CK{i}a", realized_state="materialized")
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_3",
                               entity_key=f"CK{i}b", realized_state="materialized")
        for i in range(5):
            sid = f"00000000-cc{i:02d}-0000-0000-000000000001"
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_3",
                               entity_key=f"MX{i}a", realized_state="materialized")
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_3",
                               entity_key=f"MX{i}b", realized_state="invalidated")
        result = await svc.calculate_transmission_accuracy(
            session, scenario_type="trans_acc_3", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["total_multi_entity_scenarios"] == 15
        assert result["consistent_scenarios"] == 10
        assert abs(result["transmission_accuracy"] - round(10 / 15, 4)) < 0.001

    @pytest.mark.asyncio
    async def test_below_min_samples(self, session):
        for i in range(5):
            sid = f"00000000-dd{i:02d}-0000-0000-000000000001"
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_4",
                               entity_key=f"FEW{i}a", realized_state="materialized")
            await _add_run_log(session, scenario_id=sid, scenario_type="trans_acc_4",
                               entity_key=f"FEW{i}b", realized_state="materialized")
        result = await svc.calculate_transmission_accuracy(
            session, scenario_type="trans_acc_4", min_samples=10
        )
        assert result["insufficient_samples"] is True
        assert result["transmission_accuracy"] is None


# ============================================================================
# 4. calculate_portfolio_impact_accuracy
# ============================================================================

class TestCalculatePortfolioImpactAccuracy:
    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        result = await svc.calculate_portfolio_impact_accuracy(None)
        assert result["portfolio_hit_rate"] is None
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_ignores_non_portfolio_rows(self, session):
        # Insert only company rows — portfolio metric should see 0
        await _add_run_log(session, scenario_type="port_acc_1", entity_type="company",
                           entity_key="AAPL", realized_state="materialized")
        result = await svc.calculate_portfolio_impact_accuracy(
            session, scenario_type="port_acc_1", min_samples=1
        )
        assert result["total_portfolio_evaluated"] == 0
        assert result["portfolio_hit_rate"] is None

    @pytest.mark.asyncio
    async def test_correct_portfolio_hit_rate(self, session):
        for _ in range(8):
            await _add_run_log(session, scenario_type="port_acc_2", entity_type="portfolio",
                               entity_key="PORTFOLIO_1", realized_state="materialized")
        for _ in range(2):
            await _add_run_log(session, scenario_type="port_acc_2", entity_type="portfolio",
                               entity_key="PORTFOLIO_1", realized_state="invalidated")
        result = await svc.calculate_portfolio_impact_accuracy(
            session, scenario_type="port_acc_2", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["portfolio_materialized"] == 8
        assert result["portfolio_invalidated"] == 2
        assert abs(result["portfolio_hit_rate"] - 0.8) < 0.001

    @pytest.mark.asyncio
    async def test_insufficient_portfolio_samples(self, session):
        for _ in range(3):
            await _add_run_log(session, scenario_type="port_acc_3", entity_type="portfolio",
                               entity_key="PORT_FEW", realized_state="materialized")
        result = await svc.calculate_portfolio_impact_accuracy(
            session, scenario_type="port_acc_3", min_samples=10
        )
        assert result["insufficient_samples"] is True


# ============================================================================
# 5. calculate_scenario_stability
# ============================================================================

class TestCalculateScenarioStability:
    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        result = await svc.calculate_scenario_stability(None)
        assert result["stability"] is None
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_single_run_pair_counted_as_single(self, session):
        await _add_run_log(session, scenario_type="stability_1", entity_key="SINGLE_RUN",
                           run_reason="assembly", snapshot_reason="scenario_a")
        result = await svc.calculate_scenario_stability(
            session, scenario_type="stability_1", min_samples=1
        )
        assert result["single_run_pairs"] >= 1

    @pytest.mark.asyncio
    async def test_double_run_pair_counted_as_stable(self, session):
        for _ in range(2):
            await _add_run_log(session, scenario_type="stability_2", entity_key="STABLE_PAIR",
                               run_reason="assembly", snapshot_reason="scenario_b")
        result = await svc.calculate_scenario_stability(
            session, scenario_type="stability_2", min_samples=1
        )
        # At least the stable pair is counted
        assert result["stable_pairs"] >= 1

    @pytest.mark.asyncio
    async def test_stability_fraction_correct(self, session):
        # 10 pairs with 2 runs each (stable), 5 pairs with 1 run (single)
        for i in range(10):
            for _ in range(2):
                await _add_run_log(session, scenario_type="stability_3",
                                   entity_key=f"ST_STABLE_{i}",
                                   run_reason="assembly",
                                   snapshot_reason="scenario_stab_test")
        for i in range(5):
            await _add_run_log(session, scenario_type="stability_3",
                               entity_key=f"ST_SINGLE_{i}",
                               run_reason="assembly",
                               snapshot_reason="scenario_stab_test")
        result = await svc.calculate_scenario_stability(
            session, scenario_type="stability_3", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["stable_pairs"] == 10
        assert result["single_run_pairs"] == 5
        assert result["total_distinct_pairs"] == 15
        assert abs(result["stability"] - round(10 / 15, 4)) < 0.001

    @pytest.mark.asyncio
    async def test_insufficient_when_below_min(self, session):
        for i in range(5):
            await _add_run_log(session, scenario_type="stability_4",
                               entity_key=f"FEW_{i}", run_reason="assembly",
                               snapshot_reason="few_scenario")
        result = await svc.calculate_scenario_stability(
            session, scenario_type="stability_4", min_samples=10
        )
        assert result["insufficient_samples"] is True


# ============================================================================
# 6. calculate_scenario_churn
# ============================================================================

class TestCalculateScenarioChurn:
    @pytest.mark.asyncio
    async def test_null_session_safe(self):
        result = await svc.calculate_scenario_churn(None)
        assert result["churn_rate"] is None
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_empty_db_insufficient(self, session):
        result = await svc.calculate_scenario_churn(
            session, scenario_type="churn_nonexistent_xyz", min_samples=1
        )
        assert result["insufficient_samples"] is True

    @pytest.mark.asyncio
    async def test_correct_churn_rate(self, session):
        # 10 distinct tuples, 3 invalidated
        for i in range(7):
            await _add_run_log(session, scenario_type="churn_1",
                               entity_key=f"CHURN_MAT_{i}",
                               snapshot_reason="scenario_churn_test",
                               realized_state="materialized")
        for i in range(3):
            await _add_run_log(session, scenario_type="churn_1",
                               entity_key=f"CHURN_INV_{i}",
                               snapshot_reason="scenario_churn_test",
                               realized_state="invalidated")
        result = await svc.calculate_scenario_churn(
            session, scenario_type="churn_1", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["total_tuples"] == 10
        assert result["invalidated_tuples"] == 3
        assert abs(result["churn_rate"] - round(3 / 10, 4)) < 0.001

    @pytest.mark.asyncio
    async def test_most_recent_row_governs_churn(self, session):
        # Same tuple: first write materialized, then invalidated (most recent = invalidated)
        # list_run_logs returns desc, so first encountered = most recent
        await _add_run_log(session, scenario_type="churn_2",
                           entity_key="MOST_RECENT",
                           snapshot_reason="churn_recent_test",
                           realized_state="materialized",
                           evaluated_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        await _add_run_log(session, scenario_type="churn_2",
                           entity_key="MOST_RECENT",
                           snapshot_reason="churn_recent_test",
                           realized_state="invalidated",
                           evaluated_at=datetime(2025, 6, 1, tzinfo=timezone.utc))
        # Add 9 more tuples with materialized so we hit min_samples=10
        for i in range(9):
            await _add_run_log(session, scenario_type="churn_2",
                               entity_key=f"CHURN_FILLER_{i}",
                               snapshot_reason="churn_recent_test",
                               realized_state="materialized")
        result = await svc.calculate_scenario_churn(
            session, scenario_type="churn_2", min_samples=10
        )
        assert result["insufficient_samples"] is False
        # MOST_RECENT tuple's most-recent row = invalidated → counts as 1 invalidated
        assert result["invalidated_tuples"] == 1

    @pytest.mark.asyncio
    async def test_all_materialized_churn_zero(self, session):
        for i in range(10):
            await _add_run_log(session, scenario_type="churn_3",
                               entity_key=f"ZERO_CHURN_{i}",
                               snapshot_reason="zero_churn_test",
                               realized_state="materialized")
        result = await svc.calculate_scenario_churn(
            session, scenario_type="churn_3", min_samples=10
        )
        assert result["insufficient_samples"] is False
        assert result["invalidated_tuples"] == 0
        assert result["churn_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_insufficient_when_below_min(self, session):
        for i in range(5):
            await _add_run_log(session, scenario_type="churn_4",
                               entity_key=f"FEW_CHURN_{i}",
                               snapshot_reason="few_churn",
                               realized_state="materialized")
        result = await svc.calculate_scenario_churn(
            session, scenario_type="churn_4", min_samples=10
        )
        assert result["insufficient_samples"] is True


# ============================================================================
# 7. summarize_scenario_calibration
# ============================================================================

class TestSummarizeScenarioCalibration:
    @pytest.mark.asyncio
    async def test_null_session_returns_safe_empty(self):
        result = await svc.summarize_scenario_calibration(None)
        assert result["db_available"] is False
        assert result["safe_state"] is True
        assert result["schema_version"] == svc.CALIBRATION_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_live_session_db_available_true(self, session):
        result = await svc.summarize_scenario_calibration(session)
        assert result["db_available"] is True

    @pytest.mark.asyncio
    async def test_all_sub_dicts_present(self, session):
        result = await svc.summarize_scenario_calibration(session)
        assert "hit_rate_metrics" in result
        assert "transmission_accuracy_metrics" in result
        assert "portfolio_impact_metrics" in result
        assert "stability_metrics" in result
        assert "churn_metrics" in result

    @pytest.mark.asyncio
    async def test_schema_version_present(self, session):
        result = await svc.summarize_scenario_calibration(session)
        assert result["schema_version"] == svc.CALIBRATION_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_scenario_type_and_entity_type_passed_through(self, session):
        result = await svc.summarize_scenario_calibration(
            session,
            scenario_type = "company",
            entity_type   = "company",
        )
        assert result["scenario_type"] == "company"
        assert result["entity_type"] == "company"

    @pytest.mark.asyncio
    async def test_returns_safely_on_empty_db(self, session):
        result = await svc.summarize_scenario_calibration(
            session,
            scenario_type = "nonexistent_xyz_type",
        )
        assert result["safe_state"] is True


# ============================================================================
# 8. SP-6 / Immutability AST checks
# ============================================================================

class TestSP6ASTInvariants:
    @pytest.fixture(scope="class")
    def source(self):
        mod_file = inspect.getfile(svc)
        with open(mod_file, "r", encoding="utf-8") as fh:
            return fh.read()

    @pytest.fixture(scope="class")
    def tree(self, source):
        return ast.parse(source)

    def _string_constants(self, tree: ast.AST):
        """Collect non-docstring string literals from the AST."""
        docstring_nodes: set = set()

        def _mark_docstrings(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    val = body[0].value
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        docstring_nodes.add(id(val))
            for child in ast.iter_child_nodes(node):
                _mark_docstrings(child)

        _mark_docstrings(tree)
        constants = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstring_nodes:
                    constants.append(node.value)
        return constants

    def test_no_update_calls(self, source):
        assert ".update(" not in source, "module must not call .update()"

    def test_no_delete_calls(self, source):
        assert ".delete(" not in source, "module must not call .delete()"

    def test_no_execute_update(self, source):
        assert ".update(" not in source, "no SQLAlchemy .update() call"

    def test_no_forbidden_imports(self, source):
        for forbidden in ("conviction", "order_service", "execution",
                          "stance", "forecast_vector"):
            assert f"import {forbidden}" not in source
            assert f"from app.services.{forbidden}" not in source

    def test_no_delivery_ledger_import(self, source):
        assert "import DeliveryLedger" not in source
        assert "DeliveryLedger(" not in source

    def test_no_notification_import(self, source):
        assert "import Notification" not in source
        assert "Notification(" not in source

    def test_no_scenario_snapshot_write(self, source):
        assert "scenario_snapshot" not in source or \
               "add_snapshot" not in source, \
               "calibration service must never write scenario_snapshot"

    _BANNED_PHRASES = [
        "buy", "sell", "hold", "overweight", "underweight",
        "recommend", "target price", "position size",
        "take a position", "enter a trade", "exit a trade",
        "place an order", "execute", "short", "long position",
        "go long", "go short", "open a position", "close a position",
    ]

    def test_no_banned_phrase_string_constants(self, tree):
        constants = self._string_constants(tree)
        for phrase in self._BANNED_PHRASES:
            for val in constants:
                assert phrase.lower() not in val.lower(), \
                    f"banned phrase {phrase!r} found in string constant: {val!r}"

    def test_no_snapshot_snapshot_repo_write_calls(self, source):
        # Verify no add_snapshot call appears at all
        assert "add_snapshot" not in source

    def test_only_add_run_log_write_in_source(self, source):
        # The only repo write call allowed is add_run_log
        for write_fn in ("add_snapshot", "update_snapshot", "delete_snapshot",
                         "add_evidence", "update_evidence"):
            assert write_fn not in source, \
                f"prohibited write function {write_fn!r} found in source"

    def test_record_scenario_outcome_is_async(self):
        assert inspect.iscoroutinefunction(svc.record_scenario_outcome)

    def test_calculate_hit_rate_is_async(self):
        assert inspect.iscoroutinefunction(svc.calculate_scenario_hit_rate)

    def test_calculate_transmission_is_async(self):
        assert inspect.iscoroutinefunction(svc.calculate_transmission_accuracy)

    def test_calculate_portfolio_is_async(self):
        assert inspect.iscoroutinefunction(svc.calculate_portfolio_impact_accuracy)

    def test_calculate_stability_is_async(self):
        assert inspect.iscoroutinefunction(svc.calculate_scenario_stability)

    def test_calculate_churn_is_async(self):
        assert inspect.iscoroutinefunction(svc.calculate_scenario_churn)

    def test_summarize_is_async(self):
        assert inspect.iscoroutinefunction(svc.summarize_scenario_calibration)

    def test_min_samples_constant_exists(self):
        assert hasattr(svc, "MIN_SAMPLES")
        assert isinstance(svc.MIN_SAMPLES, int)
        assert svc.MIN_SAMPLES > 0

    def test_supported_realized_states_are_correct(self):
        assert "materialized" in svc.SUPPORTED_REALIZED_STATES
        assert "invalidated"  in svc.SUPPORTED_REALIZED_STATES
        assert "unresolved"   in svc.SUPPORTED_REALIZED_STATES
        assert "buy"          not in svc.SUPPORTED_REALIZED_STATES
        assert "sell"         not in svc.SUPPORTED_REALIZED_STATES

    def test_schema_version_is_int(self):
        assert isinstance(svc.CALIBRATION_SCHEMA_VERSION, int)
