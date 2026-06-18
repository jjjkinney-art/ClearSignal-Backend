"""
Tests — Scenario Read Service, Phase 14 · Slice 6.

Covers:
  1.  empty state — null session returns safe payload
  2.  empty state — no rows returns has_scenarios=False
  3.  populated state — valid snapshot returned
  4.  expired filtering — expired rows excluded
  5.  missing explanation filtering — empty what_changed excluded
  6.  missing evidence filtering — empty evidence_summary excluded
  7.  missing transmission path filtering — empty transmission_path excluded
  8.  unsupported type filtering — unsupported scenario_type excluded
  9.  ticker facet shape — all required keys present
  10. ticker facet top_plausibility reflects best band
  11. ticker facet top_confidence reflects best score
  12. ticker facet type_counts correct
  13. status snapshot shape — all required keys present
  14. status snapshot db_available=False for null session
  15. status snapshot db_available=True for live session
  16. status snapshot counts reflect stored rows
  17. null session safety — get_scenarios_for_ticker
  18. null session safety — get_scenarios_for_user
  19. null session safety — get_top_scenarios
  20. null session safety — get_scenario_facet_for_ticker
  21. null session safety — build_scenario_status_snapshot
  22. no rebuild imports (AST)
  23. no propagation imports (AST)
  24. no delivery imports (AST)
  25. no write function calls (AST)
  26. disclaimer present in all outputs
  27. disclaimer is fixed string
  28. output dict has required scenario keys
  29. confidence field in [0, 1]
  30. uncertainty field in [0, 1]
  31. get_scenarios_for_user empty user_id returns empty payload
  32. get_top_scenarios with scenario_type filter
  33. admin route smoke test — scenario-status returns dict
  34. admin route smoke test — scenario/{ticker} returns dict
  35. _is_valid_snapshot rejects None
  36. _is_valid_snapshot rejects expired row
  37. _is_valid_snapshot rejects missing what_changed
  38. _is_valid_snapshot rejects empty evidence_summary
  39. _is_valid_snapshot rejects empty transmission_path
  40. _is_valid_snapshot rejects unsupported scenario_type
"""

from __future__ import annotations

import ast
import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "scenario_read_service.py"

_REQUIRED_SCENARIO_KEYS = {
    "ticker", "scenario_type", "scenario_name", "changed_assumption",
    "affected_tickers", "affected_portfolios", "impact_summary",
    "transmission_path", "evidence", "invalidators",
    "confidence", "uncertainty", "generated_at", "expires_at", "disclaimer",
}

_REQUIRED_FACET_KEYS = {
    "ticker", "has_scenarios", "top_plausibility",
    "top_confidence", "type_counts", "scenarios", "disclaimer",
}

_REQUIRED_STATUS_KEYS = {
    "flags", "counts", "db_available", "safe_state", "disclaimer",
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
# Snapshot row helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _future(hours: int = 48) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _past(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _make_snapshot(
    db_session,
    *,
    snapshot_id: str = "",
    scenario_type: str = "company_scenario",
    entity_type: str = "company",
    entity_key: str = "NVDA",
    scenario_key: str = "NVDA company scenario",
    condition: str = "If NVDA forecast strengthens",
    what_changed: str = "NVDA forecast conditionally strengthens.",
    why_it_matters: str = "This affects 3 entities.",
    transmission_path=None,
    evidence_summary=None,
    invalidators=None,
    affected_entities=None,
    confidence_score: float = 0.72,
    uncertainty_score: float = 0.25,
    plausibility_band: str = "plausible",
    scenario_impact: str = "moderate_positive",
    expires_at=None,
    scenario_schema: int = 1,
    user_id=None,
):
    from app.db.models import ScenarioSnapshot

    tp  = transmission_path  if transmission_path  is not None else [{"step": 0, "cause": "a", "effect": "b", "channel": "direct"}]
    ev  = evidence_summary   if evidence_summary   is not None else ["Source: forecast_vector (id=fv-1)."]
    inv = invalidators        if invalidators        is not None else ["Invalidated if assumption does not materialise."]
    ae  = affected_entities   if affected_entities   is not None else [{"entity_key": entity_key, "entity_type": entity_type, "depth": 0}]

    row = ScenarioSnapshot(
        id               = snapshot_id or _uid(),
        scenario_type    = scenario_type,
        entity_type      = entity_type,
        entity_key       = entity_key,
        scenario_key     = scenario_key,
        condition        = condition,
        transmission_path= json.dumps(tp),
        scenario_impact  = scenario_impact,
        plausibility_band= plausibility_band,
        confidence_score = confidence_score,
        uncertainty_score= uncertainty_score,
        affected_entities = json.dumps(ae),
        affected_forecasts= json.dumps([]),
        affected_decisions= json.dumps([]),
        what_changed     = what_changed,
        why_it_matters   = why_it_matters,
        evidence_summary = json.dumps(ev),
        invalidators     = json.dumps(inv),
        source_versions  = json.dumps({}),
        scenario_schema  = scenario_schema,
        user_id          = user_id,
        built_at         = datetime.now(timezone.utc),
        expires_at       = expires_at or _future(48),
    )
    db_session.add(row)
    return row


# ---------------------------------------------------------------------------
# 1–2. Empty state
# ---------------------------------------------------------------------------

class TestEmptyState:
    @pytest.mark.asyncio
    async def test_null_session_get_ticker_safe_empty(self):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        result = await get_scenarios_for_ticker(None, "NVDA")
        assert result["has_scenarios"] is False
        assert result["scenarios"] == []
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_empty_db_has_no_scenarios(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        result = await get_scenarios_for_ticker(db, "NVDA")
        assert result["has_scenarios"] is False
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# 3. Populated state
# ---------------------------------------------------------------------------

class TestPopulatedState:
    @pytest.mark.asyncio
    async def test_valid_row_returned(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db)
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        assert result["has_scenarios"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_scenario_dict_has_required_keys(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db)
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        scenario = result["scenarios"][0]
        missing = _REQUIRED_SCENARIO_KEYS - scenario.keys()
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, confidence_score=0.72)
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        s = result["scenarios"][0]
        assert 0.0 <= s["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_uncertainty_in_range(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, uncertainty_score=0.25)
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        s = result["scenarios"][0]
        assert 0.0 <= s["uncertainty"] <= 1.0

    @pytest.mark.asyncio
    async def test_disclaimer_in_scenario_item(self, db):
        from app.services.scenario_read_service import (
            get_scenarios_for_ticker, _DISCLAIMER,
        )
        _make_snapshot(db)
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        s = result["scenarios"][0]
        assert s["disclaimer"] == _DISCLAIMER


# ---------------------------------------------------------------------------
# 4–8. Read filters
# ---------------------------------------------------------------------------

class TestReadFilters:
    @pytest.mark.asyncio
    async def test_expired_row_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="AAPL", expires_at=_past(1))
        await db.commit()
        result = await get_scenarios_for_ticker(db, "AAPL")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_missing_what_changed_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="AAPL", what_changed="")
        await db.commit()
        result = await get_scenarios_for_ticker(db, "AAPL")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_whitespace_what_changed_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="AAPL", what_changed="   ")
        await db.commit()
        result = await get_scenarios_for_ticker(db, "AAPL")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_empty_evidence_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="MSFT", evidence_summary=[])
        await db.commit()
        result = await get_scenarios_for_ticker(db, "MSFT")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_empty_transmission_path_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="TSLA", transmission_path=[])
        await db.commit()
        result = await get_scenarios_for_ticker(db, "TSLA")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_unsupported_type_excluded(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        _make_snapshot(db, entity_key="AMD", scenario_type="alien_scenario")
        await db.commit()
        result = await get_scenarios_for_ticker(db, "AMD")
        assert result["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_valid_passes_all_filters(self, db):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        # One invalid + one valid for same ticker
        _make_snapshot(db, entity_key="NVDA", expires_at=_past(1))    # expired
        _make_snapshot(db, entity_key="NVDA")                          # valid
        await db.commit()
        result = await get_scenarios_for_ticker(db, "NVDA")
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# 9–12. Ticker facet
# ---------------------------------------------------------------------------

class TestTickerFacet:
    @pytest.mark.asyncio
    async def test_facet_has_required_keys(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        result = await get_scenario_facet_for_ticker(db, "NVDA")
        missing = _REQUIRED_FACET_KEYS - result.keys()
        assert not missing, f"Missing: {missing}"

    @pytest.mark.asyncio
    async def test_facet_empty_when_no_rows(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        result = await get_scenario_facet_for_ticker(db, "ZZZZZ")
        assert result["has_scenarios"] is False
        assert result["top_plausibility"] == "none"

    @pytest.mark.asyncio
    async def test_facet_top_plausibility_reflects_best_band(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        _make_snapshot(db, entity_key="NVDA", plausibility_band="remote",
                       scenario_key="remote-scenario")
        _make_snapshot(db, entity_key="NVDA", plausibility_band="likely_conditional",
                       scenario_key="likely-scenario")
        await db.commit()
        result = await get_scenario_facet_for_ticker(db, "NVDA")
        assert result["top_plausibility"] == "likely_conditional"

    @pytest.mark.asyncio
    async def test_facet_top_confidence_reflects_max(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        _make_snapshot(db, entity_key="NVDA", confidence_score=0.55,
                       scenario_key="low-conf")
        _make_snapshot(db, entity_key="NVDA", confidence_score=0.82,
                       scenario_key="high-conf")
        await db.commit()
        result = await get_scenario_facet_for_ticker(db, "NVDA")
        assert result["top_confidence"] >= 0.82

    @pytest.mark.asyncio
    async def test_facet_type_counts(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        _make_snapshot(db, entity_key="NVDA", scenario_type="company_scenario",
                       scenario_key="co-1")
        _make_snapshot(db, entity_key="NVDA", scenario_type="catalyst_scenario",
                       scenario_key="cat-1")
        await db.commit()
        result = await get_scenario_facet_for_ticker(db, "NVDA")
        assert result["type_counts"].get("company_scenario", 0) >= 1
        assert result["type_counts"].get("catalyst_scenario", 0) >= 1

    @pytest.mark.asyncio
    async def test_facet_at_most_three_scenarios(self, db):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        for i in range(5):
            _make_snapshot(db, entity_key="NVDA",
                           scenario_key=f"scenario-{i}",
                           confidence_score=0.5 + i * 0.05)
        await db.commit()
        result = await get_scenario_facet_for_ticker(db, "NVDA")
        assert len(result["scenarios"]) <= 3

    @pytest.mark.asyncio
    async def test_null_session_facet_safe(self):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        result = await get_scenario_facet_for_ticker(None, "NVDA")
        assert result["has_scenarios"] is False
        assert result["disclaimer"]


# ---------------------------------------------------------------------------
# 13–16. Status snapshot
# ---------------------------------------------------------------------------

class TestStatusSnapshot:
    @pytest.mark.asyncio
    async def test_status_has_required_keys(self, db):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        result = await build_scenario_status_snapshot(db)
        missing = _REQUIRED_STATUS_KEYS - result.keys()
        assert not missing, f"Missing: {missing}"

    @pytest.mark.asyncio
    async def test_status_null_session_db_available_false(self):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        result = await build_scenario_status_snapshot(None)
        assert result["db_available"] is False
        assert "flags" in result
        assert "counts" in result

    @pytest.mark.asyncio
    async def test_status_live_session_db_available_true(self, db):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        result = await build_scenario_status_snapshot(db)
        assert result["db_available"] is True

    @pytest.mark.asyncio
    async def test_status_counts_reflect_stored_rows(self, db):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        _make_snapshot(db, entity_key="NVDA")
        _make_snapshot(db, entity_key="AAPL", scenario_key="aapl-scenario")
        await db.commit()
        result = await build_scenario_status_snapshot(db)
        assert result["counts"]["total"] >= 2

    @pytest.mark.asyncio
    async def test_status_has_flags_keys(self, db):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        result = await build_scenario_status_snapshot(db)
        flags = result["flags"]
        for key in ("scenario_build_enabled", "scenario_shadow",
                    "scenario_delivery_enabled"):
            assert key in flags, f"Missing flag: {key}"

    @pytest.mark.asyncio
    async def test_status_disclaimer_present(self, db):
        from app.services.scenario_read_service import (
            build_scenario_status_snapshot, _DISCLAIMER,
        )
        result = await build_scenario_status_snapshot(db)
        assert result["disclaimer"] == _DISCLAIMER


# ---------------------------------------------------------------------------
# 17–21. Null session safety for all functions
# ---------------------------------------------------------------------------

class TestNullSessionSafety:
    @pytest.mark.asyncio
    async def test_get_scenarios_for_ticker_null(self):
        from app.services.scenario_read_service import get_scenarios_for_ticker
        r = await get_scenarios_for_ticker(None, "NVDA")
        assert isinstance(r, dict)
        assert r["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_get_scenarios_for_user_null(self):
        from app.services.scenario_read_service import get_scenarios_for_user
        r = await get_scenarios_for_user(None, "user-1")
        assert isinstance(r, dict)
        assert r["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_get_scenarios_for_user_empty_user(self, db):
        from app.services.scenario_read_service import get_scenarios_for_user
        r = await get_scenarios_for_user(db, "")
        assert r["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_get_top_scenarios_null(self):
        from app.services.scenario_read_service import get_top_scenarios
        r = await get_top_scenarios(None)
        assert isinstance(r, dict)
        assert r["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_get_scenario_facet_null(self):
        from app.services.scenario_read_service import get_scenario_facet_for_ticker
        r = await get_scenario_facet_for_ticker(None, "NVDA")
        assert isinstance(r, dict)
        assert r["has_scenarios"] is False

    @pytest.mark.asyncio
    async def test_build_status_null(self):
        from app.services.scenario_read_service import build_scenario_status_snapshot
        r = await build_scenario_status_snapshot(None)
        assert isinstance(r, dict)
        assert r["db_available"] is False


# ---------------------------------------------------------------------------
# 26–27. Disclaimer invariant
# ---------------------------------------------------------------------------

class TestDisclaimerInvariant:
    @pytest.mark.asyncio
    async def test_disclaimer_in_ticker_payload(self, db):
        from app.services.scenario_read_service import (
            get_scenarios_for_ticker, _DISCLAIMER,
        )
        result = await get_scenarios_for_ticker(db, "ZZZZZ")
        assert result["disclaimer"] == _DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_in_user_payload(self):
        from app.services.scenario_read_service import (
            get_scenarios_for_user, _DISCLAIMER,
        )
        result = await get_scenarios_for_user(None, "user-x")
        assert result["disclaimer"] == _DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_in_top_scenarios(self):
        from app.services.scenario_read_service import (
            get_top_scenarios, _DISCLAIMER,
        )
        result = await get_top_scenarios(None)
        assert result["disclaimer"] == _DISCLAIMER

    @pytest.mark.asyncio
    async def test_disclaimer_in_status_snapshot(self):
        from app.services.scenario_read_service import (
            build_scenario_status_snapshot, _DISCLAIMER,
        )
        result = await build_scenario_status_snapshot(None)
        assert result["disclaimer"] == _DISCLAIMER


# ---------------------------------------------------------------------------
# 32. get_top_scenarios scenario_type filter
# ---------------------------------------------------------------------------

class TestTopScenariosFilter:
    @pytest.mark.asyncio
    async def test_top_scenarios_type_filter(self, db):
        from app.services.scenario_read_service import get_top_scenarios
        _make_snapshot(db, entity_key="NVDA", scenario_type="company_scenario",
                       scenario_key="co-1")
        _make_snapshot(db, entity_key="RATES", scenario_type="macro_scenario",
                       scenario_key="macro-1", entity_type="macro")
        await db.commit()
        result = await get_top_scenarios(db, scenario_type="macro_scenario")
        for s in result["scenarios"]:
            assert s["scenario_type"] == "macro_scenario"

    @pytest.mark.asyncio
    async def test_top_scenarios_empty_db(self, db):
        from app.services.scenario_read_service import get_top_scenarios
        result = await get_top_scenarios(db)
        assert result["has_scenarios"] is False


# ---------------------------------------------------------------------------
# 33–34. Admin route smoke tests
# ---------------------------------------------------------------------------

class TestAdminRoutes:
    _API = _ROOT / "app" / "api.py"

    def _api_src(self):
        return self._API.read_text(encoding="utf-8")

    def test_admin_scenario_status_route_defined(self):
        src = self._api_src()
        assert "/admin/scenario-status" in src, \
            "GET /admin/scenario-status not found in app/api.py"

    def test_admin_scenario_status_calls_observability(self):
        src = self._api_src()
        # Slice 14.10 updated the route to use the richer observability service
        assert "build_scenario_observability_snapshot" in src, \
            "build_scenario_observability_snapshot not referenced in app/api.py"

    def test_admin_scenario_ticker_route_defined(self):
        src = self._api_src()
        assert "/admin/scenario/{ticker}" in src, \
            "GET /admin/scenario/{ticker} not found in app/api.py"

    def test_admin_scenario_ticker_calls_facet(self):
        src = self._api_src()
        assert "get_scenario_facet_for_ticker" in src, \
            "get_scenario_facet_for_ticker not referenced in app/api.py"


# ---------------------------------------------------------------------------
# 35–40. _is_valid_snapshot unit tests
# ---------------------------------------------------------------------------

class TestIsValidSnapshot:
    def _row(self, **overrides):
        class FakeRow:
            scenario_type    = "company_scenario"
            expires_at       = datetime.now(timezone.utc) + timedelta(hours=48)
            what_changed     = "Changed assumption text."
            evidence_summary = json.dumps(["Source: fv."])
            transmission_path= json.dumps([{"step": 0}])

        for k, v in overrides.items():
            setattr(FakeRow, k, v)
        return FakeRow()

    def test_valid_row_passes(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(self._row()) is True

    def test_none_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(None) is False

    def test_expired_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        row = self._row(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        assert _is_valid_snapshot(row) is False

    def test_missing_what_changed_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(self._row(what_changed="")) is False

    def test_empty_evidence_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(self._row(evidence_summary=json.dumps([]))) is False

    def test_empty_transmission_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(self._row(transmission_path=json.dumps([]))) is False

    def test_unsupported_type_fails(self):
        from app.services.scenario_read_service import _is_valid_snapshot
        assert _is_valid_snapshot(self._row(scenario_type="unknown_type")) is False


# ---------------------------------------------------------------------------
# AST safety checks
# ---------------------------------------------------------------------------

class TestASTSafety:
    def _imports(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        return imported

    def _calls(self):
        src  = _SVC.read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.append(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.append(node.func.id)
        return calls

    def test_no_rebuild_imports(self):
        forbidden = ["scenario_invalidation_service", "scenario_seed_builder"]
        violations = [n for n in self._imports()
                      if any(f in n for f in forbidden)]
        assert not violations, f"Rebuild imports: {violations}"

    def test_no_propagation_imports(self):
        forbidden = ["scenario_propagation_engine"]
        violations = [n for n in self._imports()
                      if any(f in n for f in forbidden)]
        assert not violations, f"Propagation imports: {violations}"

    def test_no_explainability_imports(self):
        forbidden = ["scenario_explainability_service"]
        violations = [n for n in self._imports()
                      if any(f in n for f in forbidden)]
        assert not violations, f"Explainability imports: {violations}"

    def test_no_delivery_imports(self):
        forbidden = ["delivery_service", "notification_service",
                     "conviction_engine"]
        violations = [n for n in self._imports()
                      if any(f in n.lower() for f in forbidden)]
        assert not violations, f"Delivery imports: {violations}"

    def test_no_write_calls(self):
        write_fns = {
            "upsert_scenario_snapshot", "add_scenario_evidence", "add_run_log",
            "upsert_forecast_vector", "upsert_decision_priority",
            "delete_scenario_snapshot",
        }
        violations = [c for c in self._calls() if c in write_fns]
        assert not violations, f"Write calls: {violations}"

    def test_no_build_seeds_call(self):
        violations = [c for c in self._calls() if c == "build_seeds"]
        assert not violations, "build_seeds called from read service"

    def test_no_propagate_call(self):
        violations = [c for c in self._calls()
                      if c in ("propagate_scenario", "propagate_all")]
        assert not violations, "Propagation called from read service"
