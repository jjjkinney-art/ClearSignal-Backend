"""
Tests — Decision Read Service, Phase 13 · Slice 6.

All DB tests use SQLite in-memory via the standard async-session fixture.
Pure-read tests use synthetic row mocks — no DB required.

Covers:
  1.  get_decisions_for_ticker returns safe empty state for null session
  2.  get_decisions_for_ticker returns empty when no rows exist
  3.  get_decisions_for_ticker returns valid decisions after storage
  4.  get_decisions_for_ticker filters expired rows
  5.  get_decisions_for_ticker filters rows with empty decision_reason
  6.  get_decisions_for_ticker filters rows with empty evidence_summary
  7.  get_decisions_for_ticker filters zero-score rows
  8.  get_decisions_for_ticker filters unsupported candidate_type
  9.  get_decisions_for_user returns safe empty state for null session
  10. get_decisions_for_user returns decisions for a specific user
  11. get_top_decisions returns safe state for null session
  12. get_top_decisions returns top rows across tickers
  13. get_decision_facet_for_ticker returns safe empty facet for null session
  14. get_decision_facet_for_ticker returns correct top_bucket
  15. get_decision_facet_for_ticker returns correct type_counts
  16. get_decision_facet_for_ticker returns ≤3 decisions
  17. build_decision_status_snapshot returns safe state for null session
  18. build_decision_status_snapshot includes all 6 flags
  19. build_decision_status_snapshot counts rows correctly
  20. build_decision_status_snapshot sets db_available=True when session is live
  21. output shape — every decision item has all required fields
  22. disclaimer always present in every payload
  23. disclaimer always present on every decision item
  24. expired rows filtered out by _is_valid_priority
  25. empty evidence_summary fails _is_valid_priority
  26. zero decision_rank_score fails _is_valid_priority
  27. unsupported candidate_type fails _is_valid_priority
  28. valid row passes _is_valid_priority
  29. _format_priority derives headline from decision_reason
  30. _format_priority derives summary from first evidence item
  31. _format_priority maps candidate_type to source_type
  32. admin route GET /admin/decision-status — smoke test (no crash, has flags)
  33. admin route GET /admin/decision/{ticker} — smoke test (no crash, has disclaimer)
  34. AST: no write/add/flush calls in read service
  35. AST: no rebuild/ranking/explanation imports in read service
  36. AST: no delivery/notification/conviction imports in read service
  37. AST: no advice language in string constants
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC  = _ROOT / "app" / "services" / "decision_read_service.py"

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


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Seed helper — write one DecisionPriority row directly via repo
# ---------------------------------------------------------------------------

async def _seed_priority(
    db,
    *,
    ticker: str = "NVDA",
    candidate_type: str = "forecast_candidate",
    source_ref: str = "",
    decision_reason: str = "Signal strength is elevated for this ticker.",
    why_now: str = "The horizon is near-term and closing.",
    deprioritizers: list = None,
    evidence_summary: list = None,
    decision_rank_score: float = 0.65,
    decision_priority: str = "high",
    user_id: str = None,
    ttl_hours: int = 24,
) -> object:
    from app.db.repositories.decision_repo import upsert_decision_priority
    return await upsert_decision_priority(
        db,
        candidate_type      = candidate_type,
        entity_type         = "company",
        entity_key          = ticker,
        source_ref          = source_ref or f"src-{_uid()[:8]}",
        decision_priority   = decision_priority,
        decision_rank_score = decision_rank_score,
        attention_score     = 0.60,
        urgency_score       = 0.55,
        impact_score        = 0.65,
        confidence_score    = 0.70,
        uncertainty_score   = 0.85,
        decision_reason     = decision_reason,
        why_now             = why_now,
        deprioritizers      = deprioritizers if deprioritizers is not None else ["Low evidence count."],
        evidence_summary    = evidence_summary if evidence_summary is not None else ["Source: forecast_vector (id=fv-001)."],
        source_versions     = {"schema": "v1"},
        decision_schema     = 1,
        user_id             = user_id,
        ttl_hours           = ttl_hours,
    )


# ---------------------------------------------------------------------------
# Mock row for pure-read validation tests (no DB)
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, **kwargs):
        self._d = kwargs

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._d.get(name)


def _valid_row(**overrides) -> _Row:
    defaults = dict(
        candidate_type      = "forecast_candidate",
        entity_type         = "company",
        entity_key          = "NVDA",
        source_ref          = "fv-001",
        decision_priority   = "high",
        decision_rank_score = 0.65,
        decision_reason     = "Signal is significant.",
        why_now             = "Horizon is near-term.",
        deprioritizers      = ["Low evidence."],
        evidence_summary    = ["Source: forecast_vector."],
        expires_at          = _now() + timedelta(hours=24),
        built_at            = _now(),
    )
    defaults.update(overrides)
    return _Row(**defaults)


# ---------------------------------------------------------------------------
# 1–8. get_decisions_for_ticker
# ---------------------------------------------------------------------------

class TestGetDecisionsForTicker:
    @pytest.mark.asyncio
    async def test_null_session_safe_empty(self):
        from app.services.decision_read_service import get_decisions_for_ticker
        result = await get_decisions_for_ticker(None, "NVDA")
        assert result["has_decisions"] is False
        assert result["decisions"] == []
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        result = await get_decisions_for_ticker(db, "NVDA")
        assert result["has_decisions"] is False
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_returns_valid_decisions(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="AAPL")
        await db.commit()
        result = await get_decisions_for_ticker(db, "AAPL")
        assert result["has_decisions"] is True
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_filters_expired_rows(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="EXP", ttl_hours=-1)  # expired
        await db.commit()
        result = await get_decisions_for_ticker(db, "EXP")
        assert result["has_decisions"] is False

    @pytest.mark.asyncio
    async def test_filters_empty_decision_reason(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="NODEC", decision_reason="")
        await db.commit()
        result = await get_decisions_for_ticker(db, "NODEC")
        assert result["has_decisions"] is False

    @pytest.mark.asyncio
    async def test_filters_empty_evidence_summary(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="NOEV", evidence_summary=[])
        await db.commit()
        result = await get_decisions_for_ticker(db, "NOEV")
        assert result["has_decisions"] is False

    @pytest.mark.asyncio
    async def test_filters_zero_score_rows(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="ZERO", decision_rank_score=0.0)
        await db.commit()
        result = await get_decisions_for_ticker(db, "ZERO")
        assert result["has_decisions"] is False

    @pytest.mark.asyncio
    async def test_filters_unsupported_candidate_type(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="BAD", candidate_type="unknown_type")
        await db.commit()
        result = await get_decisions_for_ticker(db, "BAD")
        assert result["has_decisions"] is False


# ---------------------------------------------------------------------------
# 9–10. get_decisions_for_user
# ---------------------------------------------------------------------------

class TestGetDecisionsForUser:
    @pytest.mark.asyncio
    async def test_null_session_safe_empty(self):
        from app.services.decision_read_service import get_decisions_for_user
        result = await get_decisions_for_user(None, "user-001")
        assert result["has_decisions"] is False
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_returns_user_scoped_decisions(self, db):
        from app.services.decision_read_service import get_decisions_for_user
        uid = _uid()
        await _seed_priority(db, ticker="NVDA", user_id=uid)
        await db.commit()
        result = await get_decisions_for_user(db, uid)
        assert result["has_decisions"] is True
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_does_not_return_other_user_rows(self, db):
        from app.services.decision_read_service import get_decisions_for_user
        uid_a = _uid()
        uid_b = _uid()
        await _seed_priority(db, ticker="NVDA", user_id=uid_a)
        await db.commit()
        result = await get_decisions_for_user(db, uid_b)
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# 11–12. get_top_decisions
# ---------------------------------------------------------------------------

class TestGetTopDecisions:
    @pytest.mark.asyncio
    async def test_null_session_safe_state(self):
        from app.services.decision_read_service import get_top_decisions
        result = await get_top_decisions(None)
        assert result["has_decisions"] is False
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_returns_cross_ticker_decisions(self, db):
        from app.services.decision_read_service import get_top_decisions
        await _seed_priority(db, ticker="NVDA", source_ref="t1")
        await _seed_priority(db, ticker="AAPL", source_ref="t2")
        await db.commit()
        result = await get_top_decisions(db, limit=10)
        assert result["has_decisions"] is True
        assert result["count"] >= 2


# ---------------------------------------------------------------------------
# 13–16. get_decision_facet_for_ticker
# ---------------------------------------------------------------------------

class TestGetDecisionFacetForTicker:
    @pytest.mark.asyncio
    async def test_null_session_returns_empty_facet(self):
        from app.services.decision_read_service import get_decision_facet_for_ticker
        result = await get_decision_facet_for_ticker(None, "NVDA")
        assert result["has_decisions"] is False
        assert result["top_bucket"] == "none"
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_returns_correct_top_bucket(self, db):
        from app.services.decision_read_service import get_decision_facet_for_ticker
        await _seed_priority(db, ticker="BKTP", decision_priority="critical",
                              decision_rank_score=0.85, source_ref="bk1")
        await _seed_priority(db, ticker="BKTP", decision_priority="low",
                              decision_rank_score=0.25, source_ref="bk2")
        await db.commit()
        result = await get_decision_facet_for_ticker(db, "BKTP")
        assert result["top_bucket"] == "critical"

    @pytest.mark.asyncio
    async def test_type_counts_populated(self, db):
        from app.services.decision_read_service import get_decision_facet_for_ticker
        await _seed_priority(db, ticker="TC", candidate_type="forecast_candidate", source_ref="tc1")
        await _seed_priority(db, ticker="TC", candidate_type="risk_candidate", source_ref="tc2")
        await db.commit()
        result = await get_decision_facet_for_ticker(db, "TC")
        assert "forecast_candidate" in result["type_counts"]
        assert "risk_candidate" in result["type_counts"]

    @pytest.mark.asyncio
    async def test_decisions_capped_at_three(self, db):
        from app.services.decision_read_service import get_decision_facet_for_ticker
        for i in range(5):
            await _seed_priority(db, ticker="CAP", source_ref=f"cap-{i}")
        await db.commit()
        result = await get_decision_facet_for_ticker(db, "CAP")
        assert len(result["decisions"]) <= 3


# ---------------------------------------------------------------------------
# 17–20. build_decision_status_snapshot
# ---------------------------------------------------------------------------

class TestBuildDecisionStatusSnapshot:
    @pytest.mark.asyncio
    async def test_null_session_returns_safe_state(self):
        from app.services.decision_read_service import build_decision_status_snapshot
        result = await build_decision_status_snapshot(None)
        assert "flags" in result
        assert result["db_available"] is False
        assert "disclaimer" in result

    @pytest.mark.asyncio
    async def test_includes_all_six_flags(self):
        from app.services.decision_read_service import build_decision_status_snapshot
        result = await build_decision_status_snapshot(None)
        flags = result["flags"]
        assert "decision_build_enabled"       in flags
        assert "decision_scoring_enabled"     in flags
        assert "decision_delivery_enabled"    in flags
        assert "decision_shadow"              in flags
        assert "decision_targets_enabled"     in flags
        assert "decision_calibration_enabled" in flags

    @pytest.mark.asyncio
    async def test_counts_rows_correctly(self, db):
        from app.services.decision_read_service import build_decision_status_snapshot
        await _seed_priority(db, ticker="SNAP1", source_ref="s1")
        await _seed_priority(db, ticker="SNAP2", source_ref="s2")
        await db.commit()
        result = await build_decision_status_snapshot(db)
        assert result["counts"]["total"] >= 2

    @pytest.mark.asyncio
    async def test_db_available_true_when_live_session(self, db):
        from app.services.decision_read_service import build_decision_status_snapshot
        result = await build_decision_status_snapshot(db)
        assert result["db_available"] is True


# ---------------------------------------------------------------------------
# 21–23. Output shape — required fields
# ---------------------------------------------------------------------------

_REQUIRED_DECISION_FIELDS = {
    "ticker", "candidate_type", "priority_bucket", "decision_score",
    "headline", "summary", "why_important", "why_now", "evidence",
    "deprioritizers", "source_type", "source_id", "generated_at",
    "expires_at", "disclaimer",
}


class TestOutputShape:
    @pytest.mark.asyncio
    async def test_decision_item_has_all_required_fields(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="SHAPE")
        await db.commit()
        result = await get_decisions_for_ticker(db, "SHAPE")
        assert result["decisions"]
        item = result["decisions"][0]
        missing = _REQUIRED_DECISION_FIELDS - set(item.keys())
        assert not missing, f"Missing fields: {missing}"

    @pytest.mark.asyncio
    async def test_disclaimer_in_payload(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="DISC")
        await db.commit()
        result = await get_decisions_for_ticker(db, "DISC")
        assert result["disclaimer"]

    @pytest.mark.asyncio
    async def test_disclaimer_in_each_decision_item(self, db):
        from app.services.decision_read_service import get_decisions_for_ticker
        await _seed_priority(db, ticker="DISC2")
        await db.commit()
        result = await get_decisions_for_ticker(db, "DISC2")
        for item in result["decisions"]:
            assert item.get("disclaimer"), "disclaimer missing on decision item"


# ---------------------------------------------------------------------------
# 24–28. _is_valid_priority unit tests (pure, no DB)
# ---------------------------------------------------------------------------

class TestIsValidPriority:
    def test_valid_row_passes(self):
        from app.services.decision_read_service import _is_valid_priority
        assert _is_valid_priority(_valid_row()) is True

    def test_expired_fails(self):
        from app.services.decision_read_service import _is_valid_priority
        assert _is_valid_priority(_valid_row(expires_at=_now() - timedelta(hours=1))) is False

    def test_empty_evidence_fails(self):
        from app.services.decision_read_service import _is_valid_priority
        assert _is_valid_priority(_valid_row(evidence_summary=[])) is False

    def test_zero_score_fails(self):
        from app.services.decision_read_service import _is_valid_priority
        assert _is_valid_priority(_valid_row(decision_rank_score=0.0)) is False

    def test_unsupported_type_fails(self):
        from app.services.decision_read_service import _is_valid_priority
        assert _is_valid_priority(_valid_row(candidate_type="made_up")) is False


# ---------------------------------------------------------------------------
# 29–31. _format_priority unit tests (pure, no DB)
# ---------------------------------------------------------------------------

class TestFormatPriority:
    def test_headline_derived_from_decision_reason(self):
        from app.services.decision_read_service import _format_priority
        row = _valid_row(decision_reason="Signal is elevated. Secondary context follows.")
        result = _format_priority(row)
        assert result["headline"] == "Signal is elevated"

    def test_summary_from_first_evidence_item(self):
        from app.services.decision_read_service import _format_priority
        row = _valid_row(evidence_summary=["First evidence.", "Second evidence."])
        result = _format_priority(row)
        assert result["summary"] == "First evidence."

    def test_candidate_type_maps_to_source_type(self):
        from app.services.decision_read_service import _format_priority
        row = _valid_row(candidate_type="risk_candidate")
        result = _format_priority(row)
        assert result["source_type"] == "dossier_failure_mode"

    def test_similarity_maps_to_edge_source(self):
        from app.services.decision_read_service import _format_priority
        row = _valid_row(candidate_type="similarity_candidate")
        result = _format_priority(row)
        assert result["source_type"] == "similarity_edge"


# ---------------------------------------------------------------------------
# 32–33. Admin route smoke tests (TestClient, no live DB)
# ---------------------------------------------------------------------------

class TestAdminRoutes:
    """Smoke-test the admin routes by calling the handler functions directly.

    Importing app.api triggers router_service.py which uses `str | None` syntax
    (PEP 604) that Python 3.9 does not support.  We therefore test the handler
    implementations via the service layer instead of via TestClient to avoid
    that pre-existing compatibility issue.
    """

    @pytest.mark.asyncio
    async def test_admin_decision_status_handler(self):
        """Verify the status route function produces the expected shape."""
        from app.services.decision_read_service import build_decision_status_snapshot
        result = await build_decision_status_snapshot(None)
        assert "flags" in result
        assert "disclaimer" in result
        assert "db_available" in result
        # All six flag keys must be present
        for key in ("decision_build_enabled", "decision_scoring_enabled",
                    "decision_delivery_enabled", "decision_shadow",
                    "decision_targets_enabled", "decision_calibration_enabled"):
            assert key in result["flags"]

    @pytest.mark.asyncio
    async def test_admin_decision_ticker_handler(self):
        """Verify the ticker route function produces the expected shape."""
        from app.services.decision_read_service import get_decision_facet_for_ticker
        result = await get_decision_facet_for_ticker(None, "NVDA")
        assert "disclaimer" in result
        assert "has_decisions" in result
        assert "top_bucket" in result
        assert result["ticker"] == "NVDA"


# ---------------------------------------------------------------------------
# 34–37. AST safety
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_SVC.read_text(encoding="utf-8"))


def _get_docstring_values(tree: ast.AST) -> set:
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
    def test_no_write_calls_in_read_service(self):
        src = _SVC.read_text(encoding="utf-8")
        assert "session.add("   not in src, "Found session.add() in read service"
        assert ".flush("        not in src, "Found .flush() in read service"
        # update/delete are allowed in repo layer but must not appear here
        for forbidden in ("upsert_decision_priority", "add_decision_evidence",
                          "add_ranking_log", "delete_evidence_for_priority",
                          "delete_expired_priorities"):
            assert forbidden not in src, f"Read service must not call {forbidden!r}"

    def test_no_rebuild_or_ranking_imports(self):
        tree = _load_tree()
        forbidden = {
            "decision_candidate_builder",
            "decision_ranking_engine",
            "decision_explainability_service",
            "decision_invalidation_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Read service must not import {fw!r}"

    def test_no_delivery_notification_conviction_imports(self):
        tree = _load_tree()
        forbidden = {
            "delivery_service", "notification_service", "notification_repo",
            "conviction_modeler", "conviction", "recommendation",
            "forecast_delivery_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names  = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Read service must not import {fw!r}"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        docstring_values = _get_docstring_values(tree)
        banned_terms = [
            "buy", "sell", "hold", "overweight", "underweight",
            "recommend", "target price", "position size",
        ]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in docstring_values:
                    continue
                for term in banned_terms:
                    if term in val.lower():
                        offenders.append(repr(term) + " in " + repr(val[:80]))
        assert not offenders, "Advice language in string constants: " + str(offenders)
