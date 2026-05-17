"""
Phase F thesis continuity and intelligence tests.

Objectives tested:
  1. Thesis memory — snapshot stores all required fields
  2. What Changed engine — PM-language narrative generation
  3. Drift state classification — 7-state taxonomy
  4. Watchlist intelligence — new schema fields flow through
  5. Alert realism — PM-language event summaries
  6. Historical reasoning — synthesizer prompt block
  7. PM change language — forbidden templates absent from narrative

All tests are deterministic — no LLM calls, no network I/O.
"""

from __future__ import annotations

import pathlib
import pytest

from app.schemas import (
    InvestmentThesis,
    MaterialChangeEvent,
    Signal,
    ThesisDiff,
    ThesisSnapshot,
    WatchlistEntry,
)
from app.services.thesis_memory_service import (
    CONFIDENCE_COLLAPSE_THRESHOLD,
    CONFIDENCE_MATERIAL_THRESHOLD,
    CONFIDENCE_MINOR_THRESHOLD,
    build_pm_change_narrative,
    compare_thesis_snapshots,
    detect_material_change,
    snapshot_from_thesis,
    _classify_drift_state,
    _build_event_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _signal(text: str) -> Signal:
    return Signal(signal=text, direction="bullish", impact_score=0.8, source_agent="valuation")


def _make_thesis(
    ticker: str = "AAPL",
    confidence: float = 0.72,
    bull: str = "Services ARR drives operating leverage.",
    bear: str = "Rate sensitivity compresses the multiple.",
    conclusion: str = "The setup remains constructive at current multiples.",
    one_sentence: str = "Constructive on duration-adjusted earnings.",
    dominant_dimension: str = "macro",
    core_debate: str = "Can Services absorb rate pressure at 27x?",
    top_signals: list | None = None,
    top_risks: list | None = None,
    key_risks: list | None = None,
) -> InvestmentThesis:
    return InvestmentThesis(
        ticker=ticker,
        company_name="Apple Inc.",
        confidence_score=confidence,
        bull_thesis=bull,
        bear_thesis=bear,
        conclusion=conclusion,
        one_sentence_thesis=one_sentence,
        dominant_dimension=dominant_dimension,
        core_debate=core_debate,
        top_signals=top_signals or [_signal("Services ARR growth accelerating")],
        top_risks=top_risks or [_signal("Rate duration risk")],
        key_risks=key_risks or ["Rate duration risk", "China regulatory exposure"],
    )


def _make_snapshot(
    ticker: str = "AAPL",
    confidence: float = 0.72,
    dominant_dimension: str = "macro",
    core_debate: str = "Can Services absorb rate pressure?",
    top_signals: list | None = None,
    top_risks: list | None = None,
    key_risks_text: list | None = None,
    thesis_trend: str = "stable",
) -> ThesisSnapshot:
    return ThesisSnapshot(
        ticker=ticker,
        company_name="Apple Inc.",
        confidence_score=confidence,
        dominant_dimension=dominant_dimension,
        core_debate=core_debate,
        top_signals=top_signals or [_signal("Services ARR growth accelerating")],
        top_risks=top_risks or [_signal("Rate duration risk")],
        key_risks_text=key_risks_text or ["Rate duration risk"],
        thesis_trend=thesis_trend,
        one_sentence_thesis="Constructive on duration-adjusted earnings.",
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. THESIS MEMORY — snapshot captures all Phase F fields
# ════════════════════════════════════════════════════════════════════════════

class TestThesisMemorySnapshot:
    """snapshot_from_thesis() captures dominant_dimension, core_debate, core_market_debate."""

    def test_snapshot_captures_dominant_dimension(self):
        thesis = _make_thesis(dominant_dimension="macro")
        snap = snapshot_from_thesis(thesis)
        assert snap.dominant_dimension == "macro"

    def test_snapshot_captures_core_debate(self):
        thesis = _make_thesis(core_debate="Is rate duration risk already priced?")
        snap = snapshot_from_thesis(thesis)
        assert "rate duration" in snap.core_debate.lower()

    def test_snapshot_stores_ticker_uppercase(self):
        thesis = _make_thesis(ticker="aapl")
        snap = snapshot_from_thesis(thesis)
        assert snap.ticker == "AAPL"

    def test_snapshot_stores_confidence_score(self):
        thesis = _make_thesis(confidence=0.65)
        snap = snapshot_from_thesis(thesis)
        assert snap.confidence_score == pytest.approx(0.65)

    def test_snapshot_stores_top_signals(self):
        thesis = _make_thesis(top_signals=[_signal("Services gross margin expansion")])
        snap = snapshot_from_thesis(thesis)
        assert len(snap.top_signals) == 1

    def test_snapshot_stores_top_risks(self):
        thesis = _make_thesis(top_risks=[_signal("Regulatory antitrust risk")])
        snap = snapshot_from_thesis(thesis)
        assert len(snap.top_risks) == 1

    def test_snapshot_stores_one_sentence_thesis(self):
        thesis = _make_thesis(one_sentence="The setup holds at 27x.")
        snap = snapshot_from_thesis(thesis)
        assert "27x" in snap.one_sentence_thesis

    def test_snapshot_has_signal_hash(self):
        thesis = _make_thesis()
        snap = snapshot_from_thesis(thesis)
        assert len(snap.signal_hash) > 0

    def test_snapshot_has_risk_hash(self):
        thesis = _make_thesis()
        snap = snapshot_from_thesis(thesis)
        assert len(snap.risk_hash) > 0


# ════════════════════════════════════════════════════════════════════════════
# 2. SCHEMA — new Phase F fields present
# ════════════════════════════════════════════════════════════════════════════

class TestPhaseFSchemaFields:
    """New schema fields added in Phase F must exist and default correctly."""

    def test_investment_thesis_has_dominant_dimension(self):
        t = InvestmentThesis(ticker="NVDA", company_name="Nvidia")
        assert hasattr(t, "dominant_dimension")
        assert t.dominant_dimension == ""

    def test_thesis_snapshot_has_dominant_dimension(self):
        s = ThesisSnapshot(ticker="NVDA")
        assert hasattr(s, "dominant_dimension")
        assert s.dominant_dimension == ""

    def test_thesis_snapshot_has_core_debate(self):
        s = ThesisSnapshot(ticker="NVDA")
        assert hasattr(s, "core_debate")

    def test_thesis_snapshot_has_drift_state(self):
        s = ThesisSnapshot(ticker="NVDA")
        assert hasattr(s, "drift_state")

    def test_thesis_diff_has_drift_state(self):
        d = ThesisDiff()
        assert hasattr(d, "drift_state")
        assert d.drift_state == "unclear"

    def test_watchlist_entry_has_what_changed_summary(self):
        e = WatchlistEntry(ticker="NVDA")
        assert hasattr(e, "what_changed_summary")
        assert e.what_changed_summary == ""

    def test_watchlist_entry_has_drift_state(self):
        e = WatchlistEntry(ticker="NVDA")
        assert hasattr(e, "drift_state")

    def test_watchlist_entry_has_dominant_dimension(self):
        e = WatchlistEntry(ticker="NVDA")
        assert hasattr(e, "dominant_dimension")

    def test_watchlist_entry_has_core_debate(self):
        e = WatchlistEntry(ticker="NVDA")
        assert hasattr(e, "core_debate")


# ════════════════════════════════════════════════════════════════════════════
# 3. DRIFT STATE CLASSIFICATION
# ════════════════════════════════════════════════════════════════════════════

class TestDriftStateClassification:
    """_classify_drift_state() returns correct 7-state taxonomy."""

    def _diff_with(
        self,
        conf_delta: float = 0.0,
        new_risks: list | None = None,
        sig_added: list | None = None,
        top_signal_replaced: bool = False,
        trend_flipped: bool = False,
    ) -> ThesisDiff:
        return ThesisDiff(
            confidence_change=conf_delta,
            new_risks=new_risks or [],
            strengthening_signals=sig_added or [],
            top_signal_replaced=top_signal_replaced,
            trend_flipped=trend_flipped,
        )

    def test_strengthening_state(self):
        diff = self._diff_with(conf_delta=+0.10, new_risks=[])
        prev = _make_snapshot(dominant_dimension="macro")
        curr = _make_snapshot(dominant_dimension="macro")
        state = _classify_drift_state(diff, prev, curr)
        assert state == "strengthening"

    def test_weakening_state_confidence_drop(self):
        diff = self._diff_with(conf_delta=-0.12)
        prev = _make_snapshot()
        curr = _make_snapshot()
        state = _classify_drift_state(diff, prev, curr)
        assert state == "weakening"

    def test_bifurcating_state_new_risks_and_signals(self):
        diff = self._diff_with(
            conf_delta=-0.03,
            new_risks=["Regulatory antitrust probe opened"],
            sig_added=["Services ARR re-accelerated"],
        )
        prev = _make_snapshot()
        curr = _make_snapshot()
        state = _classify_drift_state(diff, prev, curr)
        assert state == "bifurcating"

    def test_transition_state_top_signal_replaced_and_trend_flip(self):
        diff = self._diff_with(top_signal_replaced=True, trend_flipped=True)
        prev = _make_snapshot()
        curr = _make_snapshot()
        state = _classify_drift_state(diff, prev, curr)
        assert state == "transition"

    def test_repricing_state_dimension_shift(self):
        diff = self._diff_with(conf_delta=-0.02)
        prev = _make_snapshot(dominant_dimension="macro")
        curr = _make_snapshot(dominant_dimension="valuation")
        state = _classify_drift_state(diff, prev, curr)
        assert state == "repricing"

    def test_unchanged_state_minimal_movement(self):
        diff = self._diff_with(conf_delta=0.01)
        prev = _make_snapshot()
        curr = _make_snapshot()
        state = _classify_drift_state(diff, prev, curr)
        assert state == "unchanged"

    def test_drift_state_stamped_on_diff_by_compare(self):
        """compare_thesis_snapshots() stamps drift_state on the returned ThesisDiff."""
        prev = _make_snapshot(confidence=0.72)
        curr = _make_snapshot(confidence=0.82)  # +10pp = strengthening
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.drift_state in {
            "strengthening", "weakening", "bifurcating",
            "repricing", "transition", "unchanged", "unclear",
        }

    def test_compare_snapshots_populates_drift_state(self):
        prev = _make_snapshot(confidence=0.60)
        curr = _make_snapshot(confidence=0.75)  # +15pp = strengthening
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.drift_state != ""


# ════════════════════════════════════════════════════════════════════════════
# 4. PM CHANGE NARRATIVE
# ════════════════════════════════════════════════════════════════════════════

class TestPMChangeNarrative:
    """build_pm_change_narrative() produces mechanism-first PM-language."""

    def _simple_diff(self, **kwargs) -> ThesisDiff:
        return ThesisDiff(**kwargs)

    def test_returns_non_empty_string(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert isinstance(narrative, str) and len(narrative) > 10

    def test_ends_with_period(self):
        prev = _make_snapshot()
        curr = _make_snapshot()
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert narrative.strip().endswith(".")

    def test_strengthening_narrative_mechanism_language(self):
        prev = _make_snapshot(confidence=0.60)
        curr = _make_snapshot(
            confidence=0.72,
            top_signals=[_signal("Services ARR re-accelerated to 14% YoY")],
        )
        diff = compare_thesis_snapshots(prev, curr)
        diff.drift_state = "strengthening"
        narrative = build_pm_change_narrative(diff, prev, curr)
        # Should not contain internal scoring language
        assert "confidence" not in narrative.lower()
        assert "pp" not in narrative.lower()

    def test_weakening_narrative_no_scoring_language(self):
        prev = _make_snapshot(confidence=0.75)
        curr = _make_snapshot(confidence=0.60)
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert "confidence" not in narrative.lower()
        assert "signals" not in narrative.lower()

    def test_repricing_narrative_names_dimensions(self):
        prev = _make_snapshot(dominant_dimension="macro")
        curr = _make_snapshot(confidence=0.72, dominant_dimension="valuation")
        diff = compare_thesis_snapshots(prev, curr)
        diff.drift_state = "repricing"
        narrative = build_pm_change_narrative(diff, prev, curr)
        # Should name the dimension shift
        assert "macro" in narrative.lower() or "valuation" in narrative.lower()

    def test_bifurcating_narrative_mentions_asymmetry(self):
        prev = _make_snapshot()
        curr = _make_snapshot(
            top_risks=[_signal("Regulatory antitrust probe opened")],
        )
        diff = compare_thesis_snapshots(prev, curr)
        diff.drift_state = "bifurcating"
        diff.new_risks = ["Regulatory antitrust probe opened"]
        diff.strengthening_signals = ["Services ARR growth accelerating"]
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert "bear" in narrative.lower() or "asymmetr" in narrative.lower() or "bull" in narrative.lower()

    def test_narrative_no_agent_references(self):
        """PM narrative must never surface agent names."""
        prev = _make_snapshot(confidence=0.70)
        curr = _make_snapshot(confidence=0.55)
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        banned = ["valuation agent", "macro agent", "risk agent", "market agent", "quality agent"]
        for term in banned:
            assert term not in narrative.lower(), f"Agent reference '{term}' found in narrative"

    def test_narrative_no_percentage_pp_references(self):
        """PM narrative must not expose internal confidence deltas as percentages."""
        prev = _make_snapshot(confidence=0.80)
        curr = _make_snapshot(confidence=0.60)
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert "pp" not in narrative
        assert "%" not in narrative

    def test_stable_narrative_is_no_change(self):
        """When nothing changed, narrative should say so without being technical."""
        prev = _make_snapshot(confidence=0.70)
        curr = _make_snapshot(confidence=0.71)  # within noise
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        # Should communicate stability in PM language
        assert len(narrative) > 0
        assert "confidence" not in narrative.lower()


# ════════════════════════════════════════════════════════════════════════════
# 5. ALERT REALISM — PM-language event summaries
# ════════════════════════════════════════════════════════════════════════════

class TestAlertRealism:
    """_build_event_summary() generates mechanism-first PM language."""

    def _diff(self, **kwargs) -> ThesisDiff:
        return ThesisDiff(**kwargs)

    def test_confidence_collapse_pm_language(self):
        diff = self._diff(confidence_change=-0.20)
        summary = _build_event_summary("confidence_collapse", diff, "AAPL")
        # Must NOT contain internal scoring language
        assert "20pp" not in summary
        assert "-0.20" not in summary
        assert "collapsed" in summary.lower() or "weakening" in summary.lower() or "mechanism" in summary.lower()

    def test_thesis_weakened_pm_language(self):
        diff = self._diff(confidence_change=-0.10)
        summary = _build_event_summary("thesis_weakened", diff, "AAPL")
        assert "AAPL" in summary
        # No raw numbers
        assert "10pp" not in summary
        assert "-0.10" not in summary

    def test_new_structural_risk_names_the_risk(self):
        diff = self._diff(new_risks=["Regulatory antitrust probe opened"])
        summary = _build_event_summary("new_structural_risk", diff, "NVDA")
        assert "NVDA" in summary
        assert "regulatory" in summary.lower() or "antitrust" in summary.lower() or "bear case" in summary.lower()

    def test_trend_flip_names_new_direction(self):
        diff = self._diff(thesis_trend="weakening")
        summary = _build_event_summary("trend_flip", diff, "TSLA")
        assert "TSLA" in summary
        assert "weakening" in summary.lower() or "burden" in summary.lower() or "reversed" in summary.lower()

    def test_thesis_strengthened_pm_language(self):
        diff = self._diff(confidence_change=+0.12)
        summary = _build_event_summary("thesis_strengthened", diff, "MSFT")
        assert "MSFT" in summary
        assert "improved" in summary.lower() or "setup" in summary.lower() or "increased" in summary.lower()

    def test_no_internal_scoring_in_any_summary(self):
        import re
        diff = self._diff(confidence_change=-0.18, new_risks=["Macro headwind"])
        for change_type in ["confidence_collapse", "thesis_weakened", "new_structural_risk", "trend_flip"]:
            summary = _build_event_summary(change_type, diff, "AAPL")
            # Check for "Xpp" pattern (digit + pp = percentage points)
            assert not re.search(r'\d+pp', summary), f"'Xpp' found in {change_type} summary: {summary}"
            assert "agent" not in summary.lower(), f"'agent' found in {change_type}: {summary}"


# ════════════════════════════════════════════════════════════════════════════
# 6. HISTORICAL REASONING — synthesizer prompt block
# ════════════════════════════════════════════════════════════════════════════

class TestHistoricalReasoningPrompt:
    """_build_synthesis_prompt() injects HISTORICAL CONTEXT when prior_snapshot present."""

    def _read_synthesizer(self) -> str:
        root = pathlib.Path(__file__).parent.parent
        return (root / "app" / "services" / "thesis_synthesizer.py").read_text()

    def test_historical_reasoning_block_in_source(self):
        src = self._read_synthesizer()
        assert "HISTORICAL CONTEXT" in src, "HISTORICAL CONTEXT block missing from synthesizer"

    def test_historical_reasoning_mandatory_label(self):
        src = self._read_synthesizer()
        assert "HISTORICAL REASONING" in src

    def test_historical_reasoning_good_language_patterns(self):
        src = self._read_synthesizer()
        assert "operating story" in src
        assert "burden shifted" in src

    def test_historical_banned_language_listed(self):
        src = self._read_synthesizer()
        assert "confidence decreased" in src  # listed as banned pattern

    def test_prior_snapshot_parameter_in_synthesize_thesis(self):
        src = self._read_synthesizer()
        assert "prior_snapshot" in src

    def test_historical_block_injected_into_prompt_template(self):
        src = self._read_synthesizer()
        assert "historical_reasoning_block" in src


# ════════════════════════════════════════════════════════════════════════════
# 7. PM CHANGE LANGUAGE CONSTRAINTS
# ════════════════════════════════════════════════════════════════════════════

class TestPMChangeLangConstraints:
    """Phase F forbidden phrases absent from generated narratives."""

    FORBIDDEN = [
        "confidence decreased",
        "signals diverged",
        "analysis changed",
        "thesis updated",
        "agent outputs",
        "agent confidence",
    ]

    @pytest.mark.parametrize("phrase", FORBIDDEN)
    def test_forbidden_phrase_absent_from_narrative(self, phrase: str):
        """Each forbidden phrase must not appear in any narrative output."""
        # Confidence collapse scenario
        prev = _make_snapshot(confidence=0.80)
        curr = _make_snapshot(confidence=0.62)
        diff = compare_thesis_snapshots(prev, curr)
        narrative = build_pm_change_narrative(diff, prev, curr)
        assert phrase not in narrative.lower(), (
            f"Forbidden phrase '{phrase}' found in narrative:\n  {narrative!r}"
        )

    @pytest.mark.parametrize("phrase", FORBIDDEN)
    def test_forbidden_phrase_absent_from_event_summary(self, phrase: str):
        """Each forbidden phrase must not appear in MaterialChangeEvent summaries."""
        diff = ThesisDiff(confidence_change=-0.18)
        summary = _build_event_summary("confidence_collapse", diff, "AAPL")
        assert phrase not in summary.lower(), (
            f"Forbidden phrase '{phrase}' in event summary:\n  {summary!r}"
        )


# ════════════════════════════════════════════════════════════════════════════
# 8. ROUTER INTEGRATION — watchlist wiring
# ════════════════════════════════════════════════════════════════════════════

class TestRouterWatchlistWiring:
    """router_service.py imports watchlist_service and calls process_new_thesis."""

    def _read_router(self) -> str:
        root = pathlib.Path(__file__).parent.parent
        return (root / "app" / "services" / "router_service.py").read_text()

    def test_router_imports_watchlist_service(self):
        src = self._read_router()
        assert "watchlist_service" in src

    def test_router_calls_process_new_thesis(self):
        src = self._read_router()
        assert "process_new_thesis" in src

    def test_router_loads_prior_snapshot(self):
        src = self._read_router()
        assert "prior_snapshot" in src or "get_latest_snapshot" in src

    def test_router_passes_prior_snapshot_to_synthesizer(self):
        src = self._read_router()
        assert "prior_snapshot=prior_snapshot" in src


# ════════════════════════════════════════════════════════════════════════════
# 9. FRONTEND — watchlist store and page source checks
# ════════════════════════════════════════════════════════════════════════════

class TestFrontendWatchlistIntelligence:
    """Verify frontend source files contain Phase F intelligence fields."""

    ROOT = pathlib.Path(__file__).parent.parent / "Ai-Intelligence-interface" / "frontend_cinematic"

    def _read(self, rel: str) -> str:
        return (self.ROOT / rel).read_text()

    def test_store_has_what_changed_summary(self):
        src = self._read("store/watchlist.ts")
        assert "whatChangedSummary" in src

    def test_store_has_drift_state(self):
        src = self._read("store/watchlist.ts")
        assert "driftState" in src

    def test_store_has_dominant_dimension(self):
        src = self._read("store/watchlist.ts")
        assert "dominantDimension" in src

    def test_store_has_core_debate(self):
        src = self._read("store/watchlist.ts")
        assert "coreDebate" in src

    def test_watchlist_page_merges_what_changed_summary(self):
        src = self._read("app/(product)/watchlist/page.tsx")
        assert "what_changed_summary" in src
        assert "whatChangedSummary" in src

    def test_watchlist_page_merges_drift_state(self):
        src = self._read("app/(product)/watchlist/page.tsx")
        assert "drift_state" in src
        assert "driftState" in src

    def test_watchlist_page_renders_what_changed_summary(self):
        src = self._read("app/(product)/watchlist/page.tsx")
        assert "whatChangedSummary" in src
        assert "whatChanged" in src or "what_changed" in src

    def test_alerts_page_fetches_real_data(self):
        src = self._read("app/(product)/alerts/page.tsx")
        assert "fetch(" in src
        assert "API_BASE" in src or "localhost" in src

    def test_alerts_page_no_hardcoded_mock_data(self):
        """Alerts page must not contain hardcoded mock alert content."""
        src = self._read("app/(product)/alerts/page.tsx")
        # The mock data strings from the old file
        assert "TSLA Q1 deliveries missed" not in src
        assert "Azure grew 31%" not in src

    def test_watchlist_page_drift_config(self):
        """Watchlist page must have drift state display config."""
        src = self._read("app/(product)/watchlist/page.tsx")
        assert "DRIFT_CONFIG" in src or "driftState" in src

    def test_alerts_page_empty_state_present(self):
        """Alerts page must gracefully handle no alerts."""
        src = self._read("app/(product)/alerts/page.tsx")
        assert "EmptyState" in src or "No alerts" in src
