"""
Tests for Phase 10B Slice 8 — Morning Brief v1 Retirement.

Covers:
  - GET /morning-brief returns Option-B deprecation JSON (not v1 output)
  - GET /morning-brief/v2 still returns valid v2 output
  - generate_morning_brief (v1) emits DeprecationWarning when called directly
  - generate_morning_brief_v2 (v2) does NOT emit DeprecationWarning
  - Legacy callers of generate_morning_brief still receive a valid MorningBrief
  - loop_producers references generate_morning_brief_v2, not v1
  - No production endpoint calls generate_morning_brief (v1) anymore

Note: Tests that would import app.api directly use source inspection instead
to avoid the pre-existing Python 3.9 str|None incompatibility in router_service.py
that prevents app.api from loading under Python 3.9.
"""

from __future__ import annotations

import ast
import inspect
import re
import warnings
from pathlib import Path

import pytest

from app.services.morning_brief_service import (
    MorningBrief,
    generate_morning_brief,
    generate_morning_brief_v2,
)

# Path to app/api.py for source-based assertions
_API_SRC = Path(__file__).parent.parent.parent / "app" / "api.py"


# ---------------------------------------------------------------------------
# Minimal fixture helpers
# ---------------------------------------------------------------------------

def _wl_entry(ticker: str = "AAPL"):
    from app.schemas import WatchlistEntry
    return WatchlistEntry(
        ticker=ticker,
        company_name=ticker,
        added_at="2026-01-01T00:00:00+00:00",
    )


def _material_change(ticker: str = "AAPL"):
    from app.schemas import MaterialChangeEvent
    return MaterialChangeEvent(
        ticker=ticker,
        change_type="thesis_update",
        change_category="thesis_broke",
        severity="high",
        materiality_score=0.8,
        summary="Thesis broke.",
        thesis_trend_changed=True,
        timestamp="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# TestDeprecatedV1EndpointSource
#
# Verifies the /morning-brief endpoint returns Option-B deprecation JSON by
# inspecting the source of app/api.py — avoiding the broken import chain
# caused by the pre-existing str|None Python 3.9 issue in router_service.py.
# ---------------------------------------------------------------------------

class TestDeprecatedV1EndpointSource:
    """GET /morning-brief handler returns Option-B deprecation JSON."""

    def _handler_source(self) -> str:
        """Extract the source of the get_morning_brief handler from api.py."""
        src = _API_SRC.read_text()
        # Isolate the handler by finding the function after @router.get("/morning-brief"
        # (not /morning-brief/v2)
        pattern = re.compile(
            r'@router\.get\(\s*["\']\/morning-brief["\'],.*?'
            r'async def get_morning_brief\(\).*?(?=\n@router|\nclass |\Z)',
            re.DOTALL,
        )
        m = pattern.search(src)
        assert m is not None, "Could not locate get_morning_brief handler in api.py"
        return m.group(0)

    def test_handler_returns_deprecated_true(self):
        src = self._handler_source()
        assert '"deprecated": True' in src or '"deprecated"' in src and "True" in src

    def test_handler_returns_redirect_to_v2(self):
        src = self._handler_source()
        assert "/morning-brief/v2" in src

    def test_handler_returns_message_field(self):
        src = self._handler_source()
        assert '"message"' in src

    def test_handler_does_not_import_v1(self):
        """The handler must not import or call generate_morning_brief (v1)."""
        src = self._handler_source()
        # Should not contain a call or import of the bare v1 function name
        assert "from .services.morning_brief_service import generate_morning_brief" not in src
        assert "generate_morning_brief(" not in src.replace("generate_morning_brief_v2", "")

    def test_v1_route_still_present(self):
        """Route /morning-brief must remain registered (clients need the deprecation response)."""
        src = _API_SRC.read_text()
        assert '"/morning-brief"' in src

    def test_v2_route_still_present(self):
        src = _API_SRC.read_text()
        assert '"/morning-brief/v2"' in src


# ---------------------------------------------------------------------------
# TestV2FunctionUnchanged
# ---------------------------------------------------------------------------

class TestV2FunctionUnchanged:
    """generate_morning_brief_v2 is callable and returns valid output."""

    def test_v2_empty_watchlist_returns_dict_compatible(self):
        result = generate_morning_brief_v2(watchlist_entries=[])
        dumped = result.model_dump()
        required = {
            "generated_at", "reference_date", "ticker_count",
            "regime_headline", "narrative_shifts", "debate_shifts",
            "priority_alerts", "attention_required", "watchlist_drift",
        }
        assert required.issubset(dumped.keys())

    def test_v2_with_entries_returns_valid_brief(self):
        result = generate_morning_brief_v2(
            watchlist_entries=[_wl_entry("NVDA")],
            recent_material_changes=[_material_change("NVDA")],
        )
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert "deprecated" not in dumped

    def test_v2_ticker_count_correct(self):
        entries = [_wl_entry("AAPL"), _wl_entry("MSFT")]
        result = generate_morning_brief_v2(watchlist_entries=entries)
        assert result.ticker_count == 2


# ---------------------------------------------------------------------------
# TestDeprecationWarning
# ---------------------------------------------------------------------------

class TestDeprecationWarning:
    """generate_morning_brief emits DeprecationWarning; v2 does not."""

    def test_v1_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            generate_morning_brief(
                watchlist_entries=[],
                recent_material_changes=[],
                recent_alerts=[],
            )
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1

    def test_v1_warning_mentions_v2(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            generate_morning_brief(
                watchlist_entries=[],
                recent_material_changes=[],
                recent_alerts=[],
            )
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        msg = str(dep_warnings[0].message) if dep_warnings else ""
        assert "v2" in msg.lower() or "generate_morning_brief_v2" in msg

    def test_v2_does_not_emit_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            generate_morning_brief_v2(watchlist_entries=[])
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(dep_warnings) == 0


# ---------------------------------------------------------------------------
# TestLegacyCallerOutput
# ---------------------------------------------------------------------------

class TestLegacyCallerOutput:
    """Legacy callers of generate_morning_brief still receive valid MorningBrief output."""

    def test_legacy_empty_watchlist_returns_morning_brief(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = generate_morning_brief(
                watchlist_entries=[],
                recent_material_changes=[],
                recent_alerts=[],
            )
        assert isinstance(result, MorningBrief)

    def test_legacy_with_entries_returns_valid_brief(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = generate_morning_brief(
                watchlist_entries=[_wl_entry("NVDA")],
                recent_material_changes=[_material_change("NVDA")],
                recent_alerts=[],
            )
        assert isinstance(result, MorningBrief)
        assert result.ticker_count == 1
        assert isinstance(result.brief_text, str)
        assert len(result.brief_text) > 0

    def test_legacy_brief_has_all_fields(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = generate_morning_brief(
                watchlist_entries=[_wl_entry()],
                recent_material_changes=[_material_change()],
                recent_alerts=[],
            )
        for field in ("brief_text", "top_movers", "attention_required",
                      "debate_shifts", "market_regime_note", "generated_at", "reference_date"):
            assert hasattr(result, field)

    def test_legacy_brief_text_is_string(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = generate_morning_brief(
                watchlist_entries=[_wl_entry("MSFT")],
                recent_material_changes=[_material_change("MSFT")],
                recent_alerts=[],
            )
        assert isinstance(result.brief_text, str)

    def test_legacy_no_raise_on_none_changes(self):
        """v1 must not raise even when passed empty optional args."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = generate_morning_brief(
                watchlist_entries=[_wl_entry("TSLA")],
                recent_material_changes=[],
                recent_alerts=[],
            )
        assert isinstance(result, MorningBrief)


# ---------------------------------------------------------------------------
# TestLoopProducerUsesV2
# ---------------------------------------------------------------------------

class TestLoopProducerUsesV2:
    """loop_producers references generate_morning_brief_v2, never v1."""

    def test_loop_producers_imports_v2(self):
        """The lazy accessor in loop_producers must return v2."""
        import app.services.loop_producers as producers
        fn = producers._get_brief_fn()
        assert fn is generate_morning_brief_v2

    def test_loop_producers_source_references_v2(self):
        import app.services.loop_producers as producers
        src = inspect.getsource(producers)
        assert "generate_morning_brief_v2" in src

    def test_loop_producers_source_no_bare_v1(self):
        """No bare v1 reference outside comments or v2-suffixed lines."""
        import app.services.loop_producers as producers
        src = inspect.getsource(producers)
        lines_with_v1 = [
            line for line in src.splitlines()
            if "generate_morning_brief" in line
            and "_v2" not in line
            and not line.strip().startswith("#")
        ]
        assert len(lines_with_v1) == 0, (
            f"Unexpected v1 references in loop_producers:\n" +
            "\n".join(lines_with_v1)
        )

    def test_produce_morning_brief_calls_v2(self):
        import app.services.loop_producers as producers
        src = inspect.getsource(producers.produce_morning_brief)
        assert "generate_morning_brief_v2" in src or "_get_brief_fn" in src


# ---------------------------------------------------------------------------
# TestNoProductionV1References
# ---------------------------------------------------------------------------

class TestNoProductionV1References:
    """No production endpoint calls generate_morning_brief (v1)."""

    def test_api_source_v1_endpoint_no_v1_import(self):
        """The /morning-brief handler in api.py must not import v1 function."""
        src = _API_SRC.read_text()
        # Find the handler section (after /morning-brief route, before /morning-brief/v2)
        # The route for /morning-brief v2 starts its own section
        v1_section_end = src.find('"/morning-brief/v2"')
        v1_section = src[:v1_section_end] if v1_section_end != -1 else src
        # The generate_morning_brief bare import must not appear after the route decorator
        route_start = v1_section.rfind('"/morning-brief"')
        handler_block = v1_section[route_start:] if route_start != -1 else ""
        assert "import generate_morning_brief" not in handler_block.replace("generate_morning_brief_v2", "")

    def test_v1_function_still_importable(self):
        """v1 function must remain importable so legacy callers don't get ImportError."""
        from app.services.morning_brief_service import generate_morning_brief
        assert callable(generate_morning_brief)

    def test_v2_is_canonical_export(self):
        """generate_morning_brief_v2 exists and is callable."""
        from app.services.morning_brief_service import generate_morning_brief_v2
        assert callable(generate_morning_brief_v2)

    def test_morning_brief_v2_schema_importable(self):
        """MorningBriefV2 schema must remain importable."""
        from app.schemas import MorningBriefV2
        assert MorningBriefV2 is not None

    def test_morning_brief_v1_model_still_importable(self):
        """MorningBrief (v1 output model) must remain importable for legacy callers."""
        from app.services.morning_brief_service import MorningBrief
        assert MorningBrief is not None
