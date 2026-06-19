"""
Tests — User Learning Profile Service, Phase 15 · Slice 7.

Covers:
  1.  service importable
  2.  all 5 public functions present
  3.  flag gate: all functions return empty profile when run_override=False
  4.  null-session: all functions return empty profile when session=None (flag=True)

  --- get_user_interest_profile ---
  5.  empty profile when no preferences exist
  6.  populated companies_of_interest when company_interest preferences exist
  7.  populated sectors_of_interest when sector_interest preferences exist
  8.  populated recurring_themes when theme_interest preferences exist
  9.  populated preferred_horizons when preferred_horizon preferences exist
  10. populated preferred_signal_types when preferred_signal_type preferences exist
  11. populated ignored_signal_types when ignored_signal_type preferences exist
  12. populated portfolio_sensitivities when portfolio_sensitivity preferences exist
  13. all seven dimensions populated in a single profile
  14. falsified preferences excluded from profile
  15. include_tentative=False filters tentative entries from lists
  16. include_tentative=False still counts tentative in confidence_summary totals
  17. confidence_summary: strong_count, moderate_count, tentative_count correct
  18. confidence_summary: mean_confidence is average of all entries
  19. evidence_summary: total_evidence_count reflects evidence_count fields
  20. evidence_summary: dimensions_with_evidence counts non-zero entries
  21. entries sorted by confidence descending within each dimension
  22. entries with equal confidence sorted by entity_key (determinism)
  23. profile_schema field present and equals 1
  24. generated_at field is an ISO-8601 string
  25. each entry has required keys: entity_key, affinity, confidence,
      signal_strength_label, evidence_count, status, dimension

  --- get_learned_priorities ---
  26. empty result when no strong/moderate preferences exist
  27. only strong preferences returned when min_strength='strong'
  28. strong + moderate returned when min_strength='moderate' (default)
  29. tentative entries excluded from priorities at default min_strength
  30. tentative entries included when min_strength='tentative'
  31. min_strength_applied field reflects the parameter
  32. high_priority_companies populated from company_interest dimension
  33. high_priority_sectors populated from sector_interest dimension
  34. portfolio_attention populated from portfolio_sensitivity dimension
  35. attention_signal_types from preferred_signal_type dimension
  36. flag off → all lists empty
  37. null session → all lists empty

  --- get_attention_preferences ---
  38. preferred_horizons populated
  39. preferred_signal_types populated
  40. ignored_signal_types populated
  41. empty when no attention-dimension preferences
  42. flag off → empty
  43. null session → empty

  --- get_personalization_context ---
  44. contains 'interests', 'priorities', 'attention' keys
  45. interests sub-dict has full profile shape
  46. priorities sub-dict has high_priority_companies key
  47. attention sub-dict has ignored_signal_types key
  48. flag off → empty sub-dicts
  49. null session → empty sub-dicts
  50. user_id propagated correctly through nested dicts

  --- summarize_user_learning_profile ---
  51. total_preferences = 0 when no preferences
  52. total_preferences correct with multiple preferences
  53. strong_preferences counts only strong entries
  54. most_engaged_company = highest-confidence company entity_key
  55. most_engaged_sector = highest-confidence sector entity_key
  56. top_signal_type = highest-confidence preferred_signal_type entity_key
  57. first_ignored_type populated from ignored_signal_types
  58. horizon_focus populated from preferred_horizons
  59. has_portfolio_sensitivity = False when no portfolio prefs
  60. has_portfolio_sensitivity = True when portfolio prefs exist
  61. flag off → all zero/None/False
  62. null session → all zero/None/False

  --- weak preference filtering ---
  63. tentative entries appear in full profile but not in priorities
  64. moderate entries appear in both full profile and priorities
  65. strong entries appear in full profile, priorities, and summary strong_count

  --- tenant isolation ---
  66. user A preferences invisible in user B's profile
  67. user B profile empty even when user A has many preferences

  --- read-only verification ---
  68. no writes to user_signal_event after profile call
  69. no writes to learned_preference after profile call
  70. no writes to relevance_adjustment_log after profile call

  --- AST safety ---
  71. no truth-table write imports in profile service
  72. no conviction / order / execution imports
  73. no banned advisory phrases in non-docstring string constants
  74. no upsert / insert / delete calls in the profile service source
  75. no relevance_adjustment_log writes
  76. no add_user_signal_event / upsert_learned_preference calls
  77. no add_relevance_adjustment_log calls
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

_ROOT = pathlib.Path(__file__).parent.parent.parent
_SVC_PATH = _ROOT / "app" / "services" / "user_learning_profile_service.py"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


@pytest_asyncio.fixture()
async def db(engine):
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _add_pref(
    session,
    *,
    user_id: str,
    dimension: str,
    entity_key: str,
    affinity: float = 0.8,
    confidence: float = 0.8,
    evidence_count: int = 8,
    status: str = "unresolved",
    signal_strength_label: str = "strong",
):
    from app.db.repositories.user_learning_repo import upsert_learned_preference
    return await upsert_learned_preference(
        session,
        user_id=user_id,
        dimension=dimension,
        entity_key=entity_key,
        affinity=affinity,
        confidence=confidence,
        evidence_count=evidence_count,
        status=status,
        signal_strength_label=signal_strength_label,
        belief_basis=f"test basis for {entity_key}",
        falsifier="inactivity",
    )


# ---------------------------------------------------------------------------
# 1–2. Import and presence
# ---------------------------------------------------------------------------

class TestImport:
    def test_service_importable(self):
        import app.services.user_learning_profile_service  # noqa: F401

    def test_all_public_functions_present(self):
        import app.services.user_learning_profile_service as svc
        for name in (
            "get_user_interest_profile",
            "get_learned_priorities",
            "get_attention_preferences",
            "get_personalization_context",
            "summarize_user_learning_profile",
        ):
            assert callable(getattr(svc, name, None)), f"Missing: {name}"


# ---------------------------------------------------------------------------
# 3. Flag gate
# ---------------------------------------------------------------------------

class TestFlagGate:
    @pytest.mark.asyncio
    async def test_interest_profile_flag_off(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        result = await get_user_interest_profile(db, user_id=_uid(), run_override=False)
        assert result["companies_of_interest"] == []
        assert result["confidence_summary"]["total_count"] == 0

    @pytest.mark.asyncio
    async def test_learned_priorities_flag_off(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        result = await get_learned_priorities(db, user_id=_uid(), run_override=False)
        assert result["high_priority_companies"] == []

    @pytest.mark.asyncio
    async def test_attention_preferences_flag_off(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        result = await get_attention_preferences(db, user_id=_uid(), run_override=False)
        assert result["preferred_horizons"] == []
        assert result["ignored_signal_types"] == []

    @pytest.mark.asyncio
    async def test_personalization_context_flag_off(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=False)
        assert result["interests"]["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_summarize_flag_off(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(db, user_id=_uid(), run_override=False)
        assert result["total_preferences"] == 0
        assert result["most_engaged_company"] is None


# ---------------------------------------------------------------------------
# 4. Null-session
# ---------------------------------------------------------------------------

class TestNullSession:
    @pytest.mark.asyncio
    async def test_interest_profile_null_session(self):
        from app.services.user_learning_profile_service import get_user_interest_profile
        result = await get_user_interest_profile(None, user_id=_uid(), run_override=True)
        assert result["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_learned_priorities_null_session(self):
        from app.services.user_learning_profile_service import get_learned_priorities
        result = await get_learned_priorities(None, user_id=_uid(), run_override=True)
        assert result["high_priority_companies"] == []

    @pytest.mark.asyncio
    async def test_attention_preferences_null_session(self):
        from app.services.user_learning_profile_service import get_attention_preferences
        result = await get_attention_preferences(None, user_id=_uid(), run_override=True)
        assert result["preferred_horizons"] == []

    @pytest.mark.asyncio
    async def test_personalization_context_null_session(self):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(None, user_id=_uid(), run_override=True)
        assert result["interests"]["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_summarize_null_session(self):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(None, user_id=_uid(), run_override=True)
        assert result["total_preferences"] == 0
        assert result["most_engaged_company"] is None


# ---------------------------------------------------------------------------
# 5–25. get_user_interest_profile
# ---------------------------------------------------------------------------

class TestGetUserInterestProfile:
    @pytest.mark.asyncio
    async def test_empty_profile_no_preferences(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        result = await get_user_interest_profile(db, user_id=_uid(), run_override=True)
        for key in ("companies_of_interest", "sectors_of_interest", "recurring_themes",
                    "preferred_horizons", "preferred_signal_types", "ignored_signal_types",
                    "portfolio_sensitivities"):
            assert result[key] == [], f"{key} should be empty"

    @pytest.mark.asyncio
    async def test_companies_of_interest_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["companies_of_interest"]) == 1
        assert result["companies_of_interest"][0]["entity_key"] == "AAPL"

    @pytest.mark.asyncio
    async def test_sectors_of_interest_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["sectors_of_interest"]) == 1
        assert result["sectors_of_interest"][0]["entity_key"] == "tech"

    @pytest.mark.asyncio
    async def test_recurring_themes_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="theme_interest", entity_key="ai_hardware")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["recurring_themes"]) == 1
        assert result["recurring_themes"][0]["entity_key"] == "ai_hardware"

    @pytest.mark.asyncio
    async def test_preferred_horizons_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_horizon", entity_key="long")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["preferred_horizons"]) == 1
        assert result["preferred_horizons"][0]["entity_key"] == "long"

    @pytest.mark.asyncio
    async def test_preferred_signal_types_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_signal_type", entity_key="earnings_beat")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["preferred_signal_types"]) == 1

    @pytest.mark.asyncio
    async def test_ignored_signal_types_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
                         affinity=-0.9, signal_strength_label="strong")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["ignored_signal_types"]) == 1
        assert result["ignored_signal_types"][0]["entity_key"] == "macro_noise"

    @pytest.mark.asyncio
    async def test_portfolio_sensitivities_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="portfolio_sensitivity", entity_key="MSFT")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["portfolio_sensitivities"]) == 1

    @pytest.mark.asyncio
    async def test_all_seven_dimensions_populated(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        for dim, key in [
            ("company_interest",      "AAPL"),
            ("sector_interest",       "tech"),
            ("theme_interest",        "ai_hardware"),
            ("preferred_horizon",     "long"),
            ("preferred_signal_type", "earnings_beat"),
            ("ignored_signal_type",   "macro_noise"),
            ("portfolio_sensitivity", "NVDA"),
        ]:
            await _add_pref(db, user_id=uid, dimension=dim, entity_key=key)
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        assert len(result["companies_of_interest"]) == 1
        assert len(result["sectors_of_interest"]) == 1
        assert len(result["recurring_themes"]) == 1
        assert len(result["preferred_horizons"]) == 1
        assert len(result["preferred_signal_types"]) == 1
        assert len(result["ignored_signal_types"]) == 1
        assert len(result["portfolio_sensitivities"]) == 1

    @pytest.mark.asyncio
    async def test_falsified_preferences_excluded(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         status="falsified")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         status="unresolved")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        keys = [e["entity_key"] for e in result["companies_of_interest"]]
        assert "AAPL" not in keys
        assert "NVDA" in keys

    @pytest.mark.asyncio
    async def test_include_tentative_false_filters_lists(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.9, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="IBM",
                         confidence=0.2, signal_strength_label="tentative")
        result = await get_user_interest_profile(db, user_id=uid, include_tentative=False,
                                                  run_override=True)
        keys = [e["entity_key"] for e in result["companies_of_interest"]]
        assert "AAPL" in keys
        assert "IBM" not in keys

    @pytest.mark.asyncio
    async def test_include_tentative_false_counts_all_in_confidence_summary(self, db):
        """Tentative entries filtered from lists but still counted in confidence_summary."""
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.9, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="IBM",
                         confidence=0.2, signal_strength_label="tentative")
        result = await get_user_interest_profile(db, user_id=uid, include_tentative=False,
                                                  run_override=True)
        # Both entries counted in summary totals
        assert result["confidence_summary"]["total_count"] == 2
        assert result["confidence_summary"]["tentative_count"] == 1

    @pytest.mark.asyncio
    async def test_confidence_summary_counts_correct(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         signal_strength_label="moderate")
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech",
                         signal_strength_label="tentative")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        cs = result["confidence_summary"]
        assert cs["strong_count"] == 1
        assert cs["moderate_count"] == 1
        assert cs["tentative_count"] == 1
        assert cs["total_count"] == 3

    @pytest.mark.asyncio
    async def test_confidence_summary_mean_confidence(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.8, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         confidence=0.4, signal_strength_label="moderate")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        cs = result["confidence_summary"]
        assert abs(cs["mean_confidence"] - 0.6) < 0.01

    @pytest.mark.asyncio
    async def test_evidence_summary_totals(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         evidence_count=8)
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech",
                         evidence_count=5)
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        ev = result["evidence_summary"]
        assert ev["total_evidence_count"] == 13
        assert ev["dimensions_with_evidence"] == 2

    @pytest.mark.asyncio
    async def test_evidence_summary_zero_evidence_not_counted(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         evidence_count=0)
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        ev = result["evidence_summary"]
        assert ev["dimensions_with_evidence"] == 0

    @pytest.mark.asyncio
    async def test_entries_sorted_by_confidence_descending(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="LOW",
                         confidence=0.3, signal_strength_label="tentative")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="HIGH",
                         confidence=0.9, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="MID",
                         confidence=0.6, signal_strength_label="moderate")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        entries = result["companies_of_interest"]
        confs = [e["confidence"] for e in entries]
        assert confs == sorted(confs, reverse=True)

    @pytest.mark.asyncio
    async def test_equal_confidence_sorted_by_entity_key(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="ZZZ",
                         confidence=0.7, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAA",
                         confidence=0.7, signal_strength_label="strong")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        keys = [e["entity_key"] for e in result["companies_of_interest"]]
        assert keys[0] == "AAA"  # alphabetically first at same confidence

    @pytest.mark.asyncio
    async def test_profile_schema_field(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        result = await get_user_interest_profile(db, user_id=_uid(), run_override=True)
        assert result["profile_schema"] == 1

    @pytest.mark.asyncio
    async def test_generated_at_is_iso_string(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        result = await get_user_interest_profile(db, user_id=_uid(), run_override=True)
        assert isinstance(result["generated_at"], str)
        # should parse as ISO-8601
        datetime.fromisoformat(result["generated_at"])

    @pytest.mark.asyncio
    async def test_entry_has_required_keys(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        result = await get_user_interest_profile(db, user_id=uid, run_override=True)
        entry = result["companies_of_interest"][0]
        for key in ("entity_key", "affinity", "confidence", "signal_strength_label",
                    "evidence_count", "status", "dimension"):
            assert key in entry, f"Missing key in PreferenceEntry: {key}"


# ---------------------------------------------------------------------------
# 26–37. get_learned_priorities
# ---------------------------------------------------------------------------

class TestGetLearnedPriorities:
    @pytest.mark.asyncio
    async def test_empty_when_no_qualifying_preferences(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.2, signal_strength_label="tentative")
        result = await get_learned_priorities(db, user_id=uid, run_override=True)
        assert result["high_priority_companies"] == []

    @pytest.mark.asyncio
    async def test_strong_only_when_min_strength_strong(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.9, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         confidence=0.5, signal_strength_label="moderate")
        result = await get_learned_priorities(db, user_id=uid, min_strength="strong", run_override=True)
        keys = [e["entity_key"] for e in result["high_priority_companies"]]
        assert "AAPL" in keys
        assert "NVDA" not in keys

    @pytest.mark.asyncio
    async def test_strong_and_moderate_at_default_min_strength(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         signal_strength_label="moderate")
        result = await get_learned_priorities(db, user_id=uid, run_override=True)
        keys = [e["entity_key"] for e in result["high_priority_companies"]]
        assert "AAPL" in keys
        assert "NVDA" in keys

    @pytest.mark.asyncio
    async def test_tentative_excluded_at_default(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         signal_strength_label="tentative")
        result = await get_learned_priorities(db, user_id=uid, run_override=True)
        assert result["high_priority_companies"] == []

    @pytest.mark.asyncio
    async def test_tentative_included_when_min_strength_tentative(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         signal_strength_label="tentative")
        result = await get_learned_priorities(db, user_id=uid, min_strength="tentative", run_override=True)
        assert len(result["high_priority_companies"]) == 1

    @pytest.mark.asyncio
    async def test_min_strength_applied_field(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        result = await get_learned_priorities(db, user_id=_uid(), min_strength="strong", run_override=True)
        assert result["min_strength_applied"] == "strong"

    @pytest.mark.asyncio
    async def test_portfolio_attention_from_portfolio_sensitivity(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="portfolio_sensitivity", entity_key="MSFT",
                         signal_strength_label="strong")
        result = await get_learned_priorities(db, user_id=uid, run_override=True)
        assert len(result["portfolio_attention"]) == 1
        assert result["portfolio_attention"][0]["entity_key"] == "MSFT"

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty_lists(self, db):
        from app.services.user_learning_profile_service import get_learned_priorities
        result = await get_learned_priorities(db, user_id=_uid(), run_override=False)
        assert result["high_priority_companies"] == []
        assert result["high_priority_sectors"] == []

    @pytest.mark.asyncio
    async def test_null_session_returns_empty_lists(self):
        from app.services.user_learning_profile_service import get_learned_priorities
        result = await get_learned_priorities(None, user_id=_uid(), run_override=True)
        assert result["high_priority_companies"] == []


# ---------------------------------------------------------------------------
# 38–43. get_attention_preferences
# ---------------------------------------------------------------------------

class TestGetAttentionPreferences:
    @pytest.mark.asyncio
    async def test_preferred_horizons_populated(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_horizon", entity_key="long")
        result = await get_attention_preferences(db, user_id=uid, run_override=True)
        assert len(result["preferred_horizons"]) == 1

    @pytest.mark.asyncio
    async def test_preferred_signal_types_populated(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_signal_type", entity_key="earnings_beat")
        result = await get_attention_preferences(db, user_id=uid, run_override=True)
        assert len(result["preferred_signal_types"]) == 1

    @pytest.mark.asyncio
    async def test_ignored_signal_types_populated(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
                         affinity=-0.9)
        result = await get_attention_preferences(db, user_id=uid, run_override=True)
        assert len(result["ignored_signal_types"]) == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_attention_prefs(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        uid = _uid()
        # Only company preferences — no horizon/signal_type
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        result = await get_attention_preferences(db, user_id=uid, run_override=True)
        assert result["preferred_horizons"] == []
        assert result["preferred_signal_types"] == []
        assert result["ignored_signal_types"] == []

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty(self, db):
        from app.services.user_learning_profile_service import get_attention_preferences
        result = await get_attention_preferences(db, user_id=_uid(), run_override=False)
        assert result["preferred_horizons"] == []
        assert result["ignored_signal_types"] == []

    @pytest.mark.asyncio
    async def test_null_session_returns_empty(self):
        from app.services.user_learning_profile_service import get_attention_preferences
        result = await get_attention_preferences(None, user_id=_uid(), run_override=True)
        assert result["preferred_horizons"] == []


# ---------------------------------------------------------------------------
# 44–50. get_personalization_context
# ---------------------------------------------------------------------------

class TestGetPersonalizationContext:
    @pytest.mark.asyncio
    async def test_contains_interests_priorities_attention_keys(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=True)
        assert "interests" in result
        assert "priorities" in result
        assert "attention" in result

    @pytest.mark.asyncio
    async def test_interests_has_full_profile_shape(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=True)
        interests = result["interests"]
        assert "companies_of_interest" in interests
        assert "confidence_summary" in interests
        assert "profile_schema" in interests

    @pytest.mark.asyncio
    async def test_priorities_has_high_priority_companies_key(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=True)
        assert "high_priority_companies" in result["priorities"]

    @pytest.mark.asyncio
    async def test_attention_has_ignored_signal_types_key(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=True)
        assert "ignored_signal_types" in result["attention"]

    @pytest.mark.asyncio
    async def test_flag_off_empty_sub_dicts(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(db, user_id=_uid(), run_override=False)
        assert result["interests"]["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_null_session_empty_sub_dicts(self):
        from app.services.user_learning_profile_service import get_personalization_context
        result = await get_personalization_context(None, user_id=_uid(), run_override=True)
        assert result["interests"]["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_user_id_propagated(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        uid = _uid()
        result = await get_personalization_context(db, user_id=uid, run_override=True)
        assert result["user_id"] == uid
        assert result["interests"]["user_id"] == uid
        assert result["priorities"]["user_id"] == uid
        assert result["attention"]["user_id"] == uid


# ---------------------------------------------------------------------------
# 51–62. summarize_user_learning_profile
# ---------------------------------------------------------------------------

class TestSummarizeUserLearningProfile:
    @pytest.mark.asyncio
    async def test_total_preferences_zero_when_none(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(db, user_id=_uid(), run_override=True)
        assert result["total_preferences"] == 0

    @pytest.mark.asyncio
    async def test_total_preferences_correct(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["total_preferences"] == 2

    @pytest.mark.asyncio
    async def test_strong_preferences_count(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         signal_strength_label="moderate")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["strong_preferences"] == 1

    @pytest.mark.asyncio
    async def test_most_engaged_company(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.9, signal_strength_label="strong")
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="NVDA",
                         confidence=0.5, signal_strength_label="moderate")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["most_engaged_company"] == "AAPL"

    @pytest.mark.asyncio
    async def test_most_engaged_sector(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="sector_interest", entity_key="tech",
                         confidence=0.8, signal_strength_label="strong")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["most_engaged_sector"] == "tech"

    @pytest.mark.asyncio
    async def test_top_signal_type(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_signal_type",
                         entity_key="earnings_beat", confidence=0.8,
                         signal_strength_label="strong")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["top_signal_type"] == "earnings_beat"

    @pytest.mark.asyncio
    async def test_first_ignored_type_populated(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="ignored_signal_type", entity_key="macro_noise",
                         affinity=-0.9, signal_strength_label="strong")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["first_ignored_type"] == "macro_noise"

    @pytest.mark.asyncio
    async def test_horizon_focus_populated(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="preferred_horizon", entity_key="long")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["horizon_focus"] == "long"

    @pytest.mark.asyncio
    async def test_no_portfolio_sensitivity(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(db, user_id=_uid(), run_override=True)
        assert result["has_portfolio_sensitivity"] is False

    @pytest.mark.asyncio
    async def test_has_portfolio_sensitivity(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="portfolio_sensitivity", entity_key="MSFT")
        result = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert result["has_portfolio_sensitivity"] is True

    @pytest.mark.asyncio
    async def test_flag_off_all_null_zero(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(db, user_id=_uid(), run_override=False)
        assert result["total_preferences"] == 0
        assert result["most_engaged_company"] is None
        assert result["has_portfolio_sensitivity"] is False

    @pytest.mark.asyncio
    async def test_null_session_all_null_zero(self):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        result = await summarize_user_learning_profile(None, user_id=_uid(), run_override=True)
        assert result["total_preferences"] == 0
        assert result["most_engaged_company"] is None


# ---------------------------------------------------------------------------
# 63–65. Weak preference filtering
# ---------------------------------------------------------------------------

class TestWeakPreferenceFiltering:
    @pytest.mark.asyncio
    async def test_tentative_in_full_profile_not_priorities(self, db):
        from app.services.user_learning_profile_service import (
            get_user_interest_profile, get_learned_priorities,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.2, signal_strength_label="tentative")
        profile = await get_user_interest_profile(db, user_id=uid, run_override=True)
        priorities = await get_learned_priorities(db, user_id=uid, run_override=True)
        assert len(profile["companies_of_interest"]) == 1  # in full profile
        assert priorities["high_priority_companies"] == []  # not in priorities

    @pytest.mark.asyncio
    async def test_moderate_in_both(self, db):
        from app.services.user_learning_profile_service import (
            get_user_interest_profile, get_learned_priorities,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.5, signal_strength_label="moderate")
        profile = await get_user_interest_profile(db, user_id=uid, run_override=True)
        priorities = await get_learned_priorities(db, user_id=uid, run_override=True)
        assert len(profile["companies_of_interest"]) == 1
        assert len(priorities["high_priority_companies"]) == 1

    @pytest.mark.asyncio
    async def test_strong_in_both_and_summary_strong_count(self, db):
        from app.services.user_learning_profile_service import (
            get_user_interest_profile, get_learned_priorities,
            summarize_user_learning_profile,
        )
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL",
                         confidence=0.9, signal_strength_label="strong")
        profile    = await get_user_interest_profile(db, user_id=uid, run_override=True)
        priorities = await get_learned_priorities(db, user_id=uid, run_override=True)
        summary    = await summarize_user_learning_profile(db, user_id=uid, run_override=True)
        assert len(profile["companies_of_interest"]) == 1
        assert len(priorities["high_priority_companies"]) == 1
        assert summary["strong_preferences"] == 1


# ---------------------------------------------------------------------------
# 66–67. Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_user_a_invisible_to_user_b(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        uid_a = _uid()
        uid_b = _uid()
        await _add_pref(db, user_id=uid_a, dimension="company_interest", entity_key="AAPL")
        result = await get_user_interest_profile(db, user_id=uid_b, run_override=True)
        assert result["companies_of_interest"] == []

    @pytest.mark.asyncio
    async def test_user_b_empty_when_user_a_has_preferences(self, db):
        from app.services.user_learning_profile_service import summarize_user_learning_profile
        uid_a = _uid()
        uid_b = _uid()
        for dim, key in [("company_interest", "AAPL"), ("sector_interest", "tech")]:
            await _add_pref(db, user_id=uid_a, dimension=dim, entity_key=key)
        result = await summarize_user_learning_profile(db, user_id=uid_b, run_override=True)
        assert result["total_preferences"] == 0
        assert result["most_engaged_company"] is None


# ---------------------------------------------------------------------------
# 68–70. Read-only verification
# ---------------------------------------------------------------------------

class TestReadOnly:
    @pytest.mark.asyncio
    async def test_no_new_signal_events_after_profile(self, db):
        from app.services.user_learning_profile_service import get_user_interest_profile
        from app.db.repositories.user_learning_repo import count_user_signal_events
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        count_before = await count_user_signal_events(db, user_id=uid)
        await get_user_interest_profile(db, user_id=uid, run_override=True)
        count_after = await count_user_signal_events(db, user_id=uid)
        assert count_before == count_after

    @pytest.mark.asyncio
    async def test_no_new_learned_preferences_after_profile(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        from app.db.repositories.user_learning_repo import count_learned_preferences
        uid = _uid()
        await _add_pref(db, user_id=uid, dimension="company_interest", entity_key="AAPL")
        count_before = await count_learned_preferences(db, user_id=uid)
        await get_personalization_context(db, user_id=uid, run_override=True)
        count_after = await count_learned_preferences(db, user_id=uid)
        assert count_before == count_after

    @pytest.mark.asyncio
    async def test_no_relevance_adjustment_logs_after_profile(self, db):
        from app.services.user_learning_profile_service import get_personalization_context
        from app.db.repositories.user_learning_repo import count_relevance_adjustment_logs
        uid = _uid()
        await get_personalization_context(db, user_id=uid, run_override=True)
        count = await count_relevance_adjustment_logs(db, user_id=uid)
        assert count == 0


# ---------------------------------------------------------------------------
# 71–77. AST safety
# ---------------------------------------------------------------------------

_BANNED_PHRASES = [
    "buy", "sell", "hold", "overweight", "underweight",
    "recommend", "target price", "position size",
    "take a position", "enter a trade", "exit a trade",
    "place an order", "execute", "short", "long position",
    "go long", "go short", "open a position", "close a position",
]

_WRITE_FUNCTIONS = {
    "add_user_signal_event",
    "upsert_learned_preference",
    "add_preference_evidence",
    "add_relevance_adjustment_log",
    "delete_learned_preference",
    "delete_expired_user_signal_events",
}

_TRUTH_WRITE_MODULES = {
    "forecast_repo", "similarity_repo", "decision_repo", "scenario_repo",
}


class TestASTSafety:
    def _load_tree(self):
        source = _SVC_PATH.read_text()
        return ast.parse(source), source

    def test_no_truth_write_module_imports(self):
        tree, _ = self._load_tree()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module += alias.name
                for bad in _TRUTH_WRITE_MODULES:
                    assert bad not in module, f"Found prohibited import: {bad!r}"

    def test_no_conviction_order_execution_imports(self):
        tree, _ = self._load_tree()
        forbidden = {"conviction", "order", "execution"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for f in forbidden:
                    assert f not in module, f"Forbidden import: {f}"

    def test_no_banned_advisory_phrases_in_string_constants(self):
        tree, _ = self._load_tree()
        docstring_ids: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Module):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    docstring_ids.add(id(node.body[0].value))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    docstring_ids.add(id(node.body[0].value))

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstring_ids:
                    continue
                lower = node.value.lower()
                for phrase in _BANNED_PHRASES:
                    assert phrase not in lower, (
                        f"Banned phrase {phrase!r} in constant: {node.value!r}"
                    )

    def test_no_write_function_calls(self):
        """Profile service must not call any repository write functions."""
        source = _SVC_PATH.read_text()
        for fn in _WRITE_FUNCTIONS:
            assert fn not in source, f"Found write function call: {fn!r}"

    def test_no_relevance_adjustment_log_writes(self):
        source = _SVC_PATH.read_text()
        assert "add_relevance_adjustment_log" not in source

    def test_no_source_table_mutation(self):
        source = _SVC_PATH.read_text()
        for bad in (
            "upsert_thesis", "upsert_conviction", "upsert_similarity_edge",
            "update_forecast_vector", "upsert_scenario_snapshot",
        ):
            assert bad not in source, f"Found prohibited write: {bad!r}"
