"""
Retrieval + Memory + Expectation Intelligence Tests
=====================================================

Part 8 of the Retrieval + Memory + Expectation Intelligence phase.

Tests:
  Part 1  — Retrieval tagging: _classify_evidence_tags, _weight_sort_evidence
  Part 2  — Memory persistence: save_snapshot, load_latest_snapshot, compute_and_save_diff
  Part 3  — Expectation regime classification: _classify_expectation_regime
  Part 4  — Temporal change quality: _classify_expectation_shift_severity
  Part 5  — Catalyst calendar: CatalystContext schema, field validation
  Part 6  — Synthesis validator: validate_thesis, all 6 checks
  Part 7  — Stance migration: drift state + stance change tracking
  Schema  — New InvestmentThesis fields present and correct type
"""

from __future__ import annotations

import pathlib
import tempfile
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_evidence(text: str, title: str = "", timestamp: str = "2026-05-15", source: str = "Test"):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title or text[:60],
        source=source,
        summary=text,
        timestamp=timestamp,
        relevance_score=0.80,
    )


def _make_thesis(**kwargs):
    """Build a minimal InvestmentThesis with valid required fields."""
    from app.schemas import InvestmentThesis
    defaults = dict(
        ticker="TEST",
        company_name="Test Corp",
        bull_thesis="Bull case with pricing power + operating leverage = margin expansion.",
        bear_thesis="Higher rates + lean inventory + cost inflation = EPS compression risk.",
        key_drivers=["Pricing power", "Operating leverage", "Capital allocation", "Balance sheet"],
        key_risks=["Rate sensitivity exposure", "Demand deceleration", "Execution risk", "Regulatory"],
        valuation_view="At ~25x forward earnings, the stock prices in 15% EPS growth.",
        conclusion="Test Corp remains high quality but the market already prices in execution — add on dips.",
        confidence_score=0.68,
        one_sentence_thesis="Test Corp's recurring revenue mix offsets cyclicality.",
        core_debate="Is margin expansion sustainable at current revenue growth?",
        dominant_driver="Operating leverage from subscription mix",
        directional_stance="Hold",
    )
    defaults.update(kwargs)
    return InvestmentThesis(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — Retrieval tagging
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrievalTagging:
    """Part 1: _classify_evidence_tags assigns correct intelligence tags."""

    def test_recent_evidence_gets_recent_change_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("The company raised guidance last quarter.", timestamp="2026-05-20")
        tagged = _classify_evidence_tags([ev])
        assert "recent_change" in tagged[0].retrieval_tags

    def test_stale_evidence_no_recent_change_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Annual report overview.", timestamp="2024-01-01")
        tagged = _classify_evidence_tags([ev])
        assert "recent_change" not in tagged[0].retrieval_tags

    def test_estimate_revision_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Analysts raised estimates following the beat — upward revision of 8%.")
        tagged = _classify_evidence_tags([ev])
        assert "estimate_revision" in tagged[0].retrieval_tags

    def test_tone_shift_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Management tone shifted more cautious in the conference call.")
        tagged = _classify_evidence_tags([ev])
        assert "tone_shift" in tagged[0].retrieval_tags

    def test_execution_signal_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Revenue beat consensus estimates by 4% — above consensus for third consecutive quarter.")
        tagged = _classify_evidence_tags([ev])
        assert "execution_signal" in tagged[0].retrieval_tags

    def test_macro_transition_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("The Fed pivot and rate cut cycle now affects valuation regime.")
        tagged = _classify_evidence_tags([ev])
        assert "macro_transition" in tagged[0].retrieval_tags

    def test_sentiment_regime_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Three analysts issued upgrades following the earnings print.")
        tagged = _classify_evidence_tags([ev])
        assert "sentiment_regime" in tagged[0].retrieval_tags

    def test_balance_sheet_event_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("The company announced a $5B share repurchase and buyback acceleration.")
        tagged = _classify_evidence_tags([ev])
        assert "balance_sheet_event" in tagged[0].retrieval_tags

    def test_valuation_regime_tag(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("Multiple expansion drove 15% of the return — historically expensive vs sector.")
        tagged = _classify_evidence_tags([ev])
        assert "valuation_regime" in tagged[0].retrieval_tags

    def test_generic_evidence_gets_low_weight(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence("The company is a leading provider of enterprise software solutions.", timestamp="2020-01-01")
        tagged = _classify_evidence_tags([ev])
        # No actionable tags → weight below baseline
        assert tagged[0].retrieval_weight < 1.0, (
            f"Generic evidence should get weight <1.0; got {tagged[0].retrieval_weight}"
        )

    def test_high_value_evidence_gets_boosted_weight(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        ev = _make_evidence(
            "Analysts raised estimates after management tone shifted more optimistic. "
            "Revenue beat expectations and guidance was raised.",
            timestamp="2026-05-10",
        )
        tagged = _classify_evidence_tags([ev])
        assert tagged[0].retrieval_weight > 1.5, (
            f"High-value evidence should get weight >1.5; got {tagged[0].retrieval_weight}"
        )

    def test_weight_sort_puts_high_value_first(self):
        from app.services.conviction_modeler import _weight_sort_evidence
        generic = _make_evidence("General company overview.", timestamp="2020-01-01")
        actionable = _make_evidence(
            "Raised estimate after earnings beat — above consensus.", timestamp="2026-05-15"
        )
        sorted_ev = _weight_sort_evidence([generic, actionable])
        assert sorted_ev[0].retrieval_weight > sorted_ev[1].retrieval_weight, (
            "High-weight evidence should be sorted first"
        )

    def test_weight_cap_at_3(self):
        from app.services.conviction_modeler import _classify_evidence_tags
        # Evidence hitting all tags
        ev = _make_evidence(
            "Estimate revision upward after earnings beat. Management tone shifted optimistic. "
            "Rate cut cycle and macro transition. Buyback announced. Upgrade issued.",
            timestamp="2026-05-20",
        )
        tagged = _classify_evidence_tags([ev])
        assert tagged[0].retrieval_weight <= 3.0


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — Memory persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryPersistence:
    """Part 2: File-based snapshot save/load/diff."""

    def _make_snapshot(self, ticker: str = "TEST", conf: float = 0.70) -> "ThesisSnapshot":
        from app.schemas import ThesisSnapshot
        return ThesisSnapshot(
            ticker=ticker,
            company_name="Test Corp",
            confidence_score=conf,
            one_sentence_thesis="The thesis holds at current multiples.",
            bull_thesis="Strong moat with pricing power.",
            bear_thesis="Rate sensitivity is non-trivial.",
        )

    def test_save_and_load_roundtrip(self):
        from app.services.thesis_memory_service import save_snapshot, load_latest_snapshot
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = pathlib.Path(tmpdir)
            snap = self._make_snapshot("RND1", conf=0.72)
            save_snapshot(snap, memory_dir=mem_dir)
            loaded = load_latest_snapshot("RND1", memory_dir=mem_dir)
            assert loaded is not None
            assert abs(loaded.confidence_score - 0.72) < 0.001
            assert loaded.ticker == "RND1"

    def test_load_latest_returns_none_when_no_history(self):
        from app.services.thesis_memory_service import load_latest_snapshot
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_latest_snapshot("NOTEXIST", memory_dir=pathlib.Path(tmpdir))
            assert result is None

    def test_multiple_saves_load_latest(self):
        from app.services.thesis_memory_service import save_snapshot, load_latest_snapshot
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = pathlib.Path(tmpdir)
            for conf in [0.60, 0.65, 0.72]:
                snap = self._make_snapshot("MULTI", conf=conf)
                save_snapshot(snap, memory_dir=mem_dir)
            latest = load_latest_snapshot("MULTI", memory_dir=mem_dir)
            assert latest is not None
            assert abs(latest.confidence_score - 0.72) < 0.001

    def test_load_snapshot_history_returns_ordered(self):
        from app.services.thesis_memory_service import save_snapshot, load_snapshot_history
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = pathlib.Path(tmpdir)
            for conf in [0.55, 0.62, 0.70]:
                snap = self._make_snapshot("ORD", conf=conf)
                save_snapshot(snap, memory_dir=mem_dir)
            history = load_snapshot_history("ORD", limit=10, memory_dir=mem_dir)
            assert len(history) == 3
            # Oldest first
            assert history[0].confidence_score < history[2].confidence_score

    def test_compute_and_save_diff_no_prior(self):
        from app.services.thesis_memory_service import compute_and_save_diff
        thesis = _make_thesis(ticker="NOHIST")
        with tempfile.TemporaryDirectory() as tmpdir:
            snap, diff = compute_and_save_diff(thesis, memory_dir=pathlib.Path(tmpdir))
            assert snap is not None
            assert diff is None  # No prior snapshot

    def test_compute_and_save_diff_with_prior(self):
        from app.services.thesis_memory_service import (
            save_snapshot, snapshot_from_thesis, compute_and_save_diff
        )
        thesis_v1 = _make_thesis(ticker="DIFF", confidence_score=0.60)
        thesis_v2 = _make_thesis(ticker="DIFF", confidence_score=0.75)
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = pathlib.Path(tmpdir)
            # Save v1 first
            snap_v1 = snapshot_from_thesis(thesis_v1)
            save_snapshot(snap_v1, memory_dir=mem_dir)
            # Now save v2 and get diff
            snap_v2, diff = compute_and_save_diff(thesis_v2, memory_dir=mem_dir)
            assert diff is not None
            # Confidence improved
            assert diff.confidence_change > 0.10

    def test_prune_respects_max_limit(self):
        from app.services.thesis_memory_service import (
            save_snapshot, load_snapshot_history, _MAX_SNAPSHOTS_PER_TICKER
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = pathlib.Path(tmpdir)
            for i in range(_MAX_SNAPSHOTS_PER_TICKER + 5):
                snap = self._make_snapshot("PRUNE", conf=0.50 + i * 0.01)
                save_snapshot(snap, memory_dir=mem_dir)
            history = load_snapshot_history("PRUNE", limit=100, memory_dir=mem_dir)
            assert len(history) <= _MAX_SNAPSHOTS_PER_TICKER


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 — Expectation regime classification
# ─────────────────────────────────────────────────────────────────────────────

class TestExpectationRegime:
    """Part 3: _classify_expectation_regime maps fragility + stance to regime."""

    def test_cheap_regime_at_low_fragility(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.15)
        assert regime == "cheap"

    def test_attractive_regime_at_moderate_fragility(self):
        """Phase 3: fragility=0.40 is now 'attractive' (below updated fair_thresh=0.42)."""
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.40)
        assert regime == "attractive", (
            f"Expected 'attractive' at fragility=0.40 (below fair_thresh≈0.42 with default durability). "
            f"Got {regime!r}. Phase 3 raised _REGIME_FAIR from 0.32→0.36 and added _REGIME_ATTRACTIVE=0.20."
        )

    def test_fair_regime_at_moderate_fragility(self):
        """fragility=0.45 lands above fair_thresh≈0.42, below stretched_thresh≈0.56."""
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.45)
        assert regime == "fair", (
            f"Expected 'fair' at fragility=0.45; got {regime!r}."
        )

    def test_stretched_regime_at_elevated_fragility(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.62)
        assert regime == "stretched"

    def test_euphoric_regime_at_high_fragility(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        regime = _classify_expectation_regime(expectation_fragility=0.80)
        assert regime == "euphoric"

    def test_bubble_regime_at_extreme_fragility(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        # Use durability_score=0.0 so dur_adj=0 and bubble_thresh=0.86 (raw threshold, Phase 3 tightened)
        regime = _classify_expectation_regime(expectation_fragility=0.93, durability_score=0.0)
        assert regime == "bubble"

    def test_durability_shifts_stretched_threshold(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        # With high durability, a stock at fragility=0.55 may still be "fair"
        # (durability shifts the threshold up by up to 0.12)
        regime_low_dur  = _classify_expectation_regime(0.55, durability_score=0.10)
        regime_high_dur = _classify_expectation_regime(0.55, durability_score=0.90)
        # High durability business should not be penalized as severely
        assert regime_low_dur in ("stretched", "euphoric")
        assert regime_high_dur in ("fair", "stretched")

    def test_valuation_stance_overrides_bubble(self):
        from app.services.conviction_modeler import _classify_expectation_regime
        # Even at moderate fragility, "bubble" valuation_stance → bubble regime
        regime = _classify_expectation_regime(0.40, valuation_stance="bubble")
        assert regime == "bubble"

    def test_all_outputs_are_valid_vocabulary(self):
        """Phase 3: 'attractive' is now a valid regime label between 'cheap' and 'fair'."""
        from app.services.conviction_modeler import _classify_expectation_regime
        valid = {"cheap", "attractive", "fair", "stretched", "euphoric", "bubble"}
        for frag in [0.05, 0.20, 0.40, 0.55, 0.65, 0.75, 0.85, 0.95]:
            result = _classify_expectation_regime(frag)
            assert result in valid, f"Invalid regime {result!r} for frag={frag}"


# ─────────────────────────────────────────────────────────────────────────────
# PART 4 — Temporal change quality (expectation shift severity)
# ─────────────────────────────────────────────────────────────────────────────

class TestExpectationShiftSeverity:
    """Part 4: _classify_expectation_shift_severity detects revision direction."""

    def test_no_shift_returns_none(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        evidence = [_make_evidence("The company operates in enterprise software.")]
        result = _classify_expectation_shift_severity(evidence)
        assert result == "none"

    def test_single_positive_revision_returns_minor(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        ev = _make_evidence("Analysts raised estimates after the beat — upward revision.")
        result = _classify_expectation_shift_severity([ev])
        assert result in ("minor", "moderate")

    def test_multiple_positive_revisions_returns_significant(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        evidence = [
            _make_evidence("Estimate raised — beat consensus."),
            _make_evidence("Price target raised after above consensus results."),
            _make_evidence("Upward revision following guidance raise."),
            _make_evidence("Raised guidance — above consensus again."),
            _make_evidence("PT raised; revised higher for FY26."),
        ]
        result = _classify_expectation_shift_severity(evidence)
        assert result in ("significant", "major"), f"Expected significant+; got {result!r}"

    def test_negative_revision_signals_detected(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        ev = _make_evidence("Analysts lowered estimates after the miss — downward revision.")
        result = _classify_expectation_shift_severity([ev])
        assert result != "none"

    def test_tone_shift_amplifies_severity(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        evidence = [
            _make_evidence("Management tone shifted cautious in recent call."),
            _make_evidence("Lowered estimate following guidance cut."),
            _make_evidence("Changed language — more conservative guidance tone."),
        ]
        result = _classify_expectation_shift_severity(evidence)
        assert result in ("moderate", "significant", "major")

    def test_all_valid_output_values(self):
        from app.services.conviction_modeler import _classify_expectation_shift_severity
        valid = {"none", "minor", "moderate", "significant", "major"}
        ev = [_make_evidence("Generic evidence text with no specific signals.")]
        result = _classify_expectation_shift_severity(ev)
        assert result in valid


# ─────────────────────────────────────────────────────────────────────────────
# PART 5 — Catalyst Calendar schema
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalystCalendarSchema:
    """Part 5: CatalystContext schema is well-formed and embeds correctly."""

    def test_catalyst_context_exists(self):
        from app.schemas import CatalystContext
        assert CatalystContext is not None

    def test_catalyst_context_fields(self):
        from app.schemas import CatalystContext
        cc = CatalystContext(
            primary_catalyst="Q2 earnings call — gross margin guidance is the key variable",
            catalyst_type="earnings",
            event_window="Within 2-3 weeks",
            asymmetry_window="Setup skewed to downside — guidance cut reprices ~12%",
            what_resolves_the_debate="Gross margin above 72% confirms Services mix durability",
            time_horizon="tactical",
            time_horizon_rationale="Binary event within 2 weeks",
        )
        assert cc.catalyst_type == "earnings"
        assert cc.time_horizon == "tactical"
        assert "72%" in cc.what_resolves_the_debate

    def test_catalyst_context_default_time_horizon(self):
        from app.schemas import CatalystContext
        cc = CatalystContext()
        assert cc.time_horizon == "structural"

    def test_catalyst_calendar_on_investment_thesis(self):
        from app.schemas import InvestmentThesis, CatalystContext
        cc = CatalystContext(
            primary_catalyst="Upcoming earnings event",
            catalyst_type="earnings",
            time_horizon="tactical",
        )
        thesis = _make_thesis(catalyst_calendar=cc)
        assert thesis.catalyst_calendar is not None
        assert thesis.catalyst_calendar.catalyst_type == "earnings"

    def test_catalyst_calendar_defaults_to_none(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert thesis.catalyst_calendar is None

    def test_catalyst_calendar_survives_model_dump(self):
        from app.schemas import InvestmentThesis, CatalystContext
        cc = CatalystContext(primary_catalyst="Earnings", time_horizon="tactical")
        thesis = _make_thesis(catalyst_calendar=cc)
        dumped = thesis.model_dump()
        assert dumped["catalyst_calendar"] is not None
        assert dumped["catalyst_calendar"]["time_horizon"] == "tactical"


# ─────────────────────────────────────────────────────────────────────────────
# PART 6 — Synthesis validator
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthesisValidator:
    """Part 6: validate_thesis detects violations deterministically."""

    def test_clean_thesis_passes_all_checks(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis()
        result = validate_thesis(thesis)
        # Our default thesis has compound risk in bear_thesis and no repetitions
        assert not result.has_hard_violations, (
            f"Clean thesis should have no hard violations; got: "
            f"{[v.check_id for v in result.hard_violations]}"
        )

    def test_signal_repetition_detected(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            bull_thesis="Renewal rates remain robust and membership renewal accelerates.",
            bear_thesis="Renewal rates risk from competitive pressure. Higher rates + cost = compression.",
        )
        result = validate_thesis(thesis)
        # "renewal rates" appears in both bull and bear
        ids = [v.check_id for v in result.violations]
        assert any("REPEAT" in vid or "RENEWAL" in vid for vid in ids), (
            f"Expected repetition violation; got: {ids}"
        )

    def test_missing_compound_risk_detected(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            bear_thesis="Rate pressure is a risk. Cost inflation is also a concern. Multiple compression possible.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "MISSING_COMPOUND_RISK" in ids, (
            f"Expected MISSING_COMPOUND_RISK; got: {ids}"
        )

    def test_compound_risk_passes(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            bear_thesis="Higher rates + lean inventory + cost inflation = compounded margin pressure that the bull case understates.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "MISSING_COMPOUND_RISK" not in ids

    def test_tactical_without_catalyst_reference_detected(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            directional_stance="Tactical",
            bear_thesis="Higher rates + macro headwinds = muted upside, limited downside.",
            directional_stance_reasoning="Short-term setup with asymmetric upside.",
            conclusion="The setup is asymmetric without full structural conviction.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "TACTICAL_MISSING_CATALYST" in ids, (
            f"Expected TACTICAL_MISSING_CATALYST; got: {ids}"
        )

    def test_tactical_with_earnings_reference_passes(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            directional_stance="Tactical",
            bear_thesis="Higher rates + macro headwinds = muted upside.",
            directional_stance_reasoning="Short-term asymmetry ahead of the earnings catalyst event.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "TACTICAL_MISSING_CATALYST" not in ids

    def test_evolution_without_expectation_framing_warns(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            thesis_evolution="The company continues to execute well in its core markets.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "EVOLUTION_NO_EXPECTATION_FRAMING" in ids

    def test_evolution_with_consensus_framing_passes(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            thesis_evolution="Consensus expectations expanded after the guidance raise — estimates revised higher.",
        )
        result = validate_thesis(thesis)
        ids = [v.check_id for v in result.violations]
        assert "EVOLUTION_NO_EXPECTATION_FRAMING" not in ids

    def test_validation_result_checks_run_count(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis()
        result = validate_thesis(thesis)
        assert result.checks_run == 6  # 6 checks defined

    def test_retry_prompt_addendum_non_empty_on_hard_violation(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis(
            bear_thesis="Rate pressure is concerning. Cost inflation. No compound interaction here.",
        )
        result = validate_thesis(thesis)
        if result.has_hard_violations:
            addendum = result.retry_prompt_addendum
            assert len(addendum) > 50
            assert "SYNTHESIS CORRECTION" in addendum

    def test_retry_prompt_addendum_empty_when_clean(self):
        from app.services.synthesis_validator import validate_thesis
        thesis = _make_thesis()
        result = validate_thesis(thesis)
        # If no hard violations, addendum should be empty
        if not result.has_hard_violations:
            assert result.retry_prompt_addendum == ""

    def test_summarize_validation_format(self):
        from app.services.synthesis_validator import validate_thesis, summarize_validation
        thesis = _make_thesis()
        result = validate_thesis(thesis)
        summary = summarize_validation(result)
        assert isinstance(summary, str)
        assert len(summary) > 5


# ─────────────────────────────────────────────────────────────────────────────
# PART 7 — Stance migration tracking
# ─────────────────────────────────────────────────────────────────────────────

class TestStanceMigration:
    """Part 7: ThesisDiff correctly captures stance-level drift states."""

    def _make_snapshot_with_conf(self, conf: float, **kwargs) -> "ThesisSnapshot":
        from app.schemas import ThesisSnapshot
        return ThesisSnapshot(
            ticker="TRACK",
            company_name="Track Corp",
            confidence_score=conf,
            one_sentence_thesis=kwargs.get("thesis", "Core thesis holds."),
            dominant_dimension=kwargs.get("dim", "valuation"),
            thesis_trend=kwargs.get("trend", "unclear"),
        )

    def test_confidence_improvement_maps_to_strengthening(self):
        from app.services.thesis_memory_service import compare_thesis_snapshots
        prev = self._make_snapshot_with_conf(0.55)
        curr = self._make_snapshot_with_conf(0.70)
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.confidence_change > 0.10
        assert diff.thesis_trend in ("strengthening", "inflecting")

    def test_confidence_collapse_maps_to_weakening(self):
        from app.services.thesis_memory_service import compare_thesis_snapshots
        prev = self._make_snapshot_with_conf(0.75)
        curr = self._make_snapshot_with_conf(0.55)
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.confidence_change < -0.10
        assert diff.thesis_trend == "weakening"

    def test_stable_thesis_produces_stable_or_unclear(self):
        from app.services.thesis_memory_service import compare_thesis_snapshots
        prev = self._make_snapshot_with_conf(0.68)
        curr = self._make_snapshot_with_conf(0.69)
        diff = compare_thesis_snapshots(prev, curr)
        assert diff.thesis_trend in ("stable", "unclear", "strengthening")

    def test_dimension_change_produces_repricing_drift(self):
        from app.services.thesis_memory_service import compare_thesis_snapshots, _classify_drift_state
        prev = self._make_snapshot_with_conf(0.68, dim="valuation")
        curr = self._make_snapshot_with_conf(0.66, dim="macro")
        diff = compare_thesis_snapshots(prev, curr)
        drift = _classify_drift_state(diff, prev, curr)
        # Dimension changed without material confidence move → repricing
        assert drift in ("repricing", "unchanged", "unclear")

    def test_drift_state_vocabulary(self):
        from app.services.thesis_memory_service import compare_thesis_snapshots
        valid = {"strengthening", "weakening", "bifurcating", "repricing", "transition", "unchanged", "unclear"}
        for conf_delta in [-0.20, -0.10, 0.0, 0.05, 0.15]:
            prev = self._make_snapshot_with_conf(0.65)
            curr = self._make_snapshot_with_conf(0.65 + conf_delta)
            diff = compare_thesis_snapshots(prev, curr)
            assert diff.drift_state in valid, f"Invalid drift_state {diff.drift_state!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Schema presence tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaNewFields:
    """Verify all new schema fields are present with correct types and defaults."""

    def test_expectation_regime_field_exists(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert hasattr(thesis, "expectation_regime")

    def test_expectation_regime_default_is_fair(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert thesis.expectation_regime == "fair"

    def test_expectation_shift_severity_field_exists(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert hasattr(thesis, "expectation_shift_severity")

    def test_expectation_shift_severity_default_is_none(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert thesis.expectation_shift_severity == "none"

    def test_catalyst_calendar_field_exists(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis()
        assert hasattr(thesis, "catalyst_calendar")
        assert thesis.catalyst_calendar is None

    def test_retrieved_evidence_has_retrieval_tags(self):
        from app.schemas import RetrievedEvidence
        ev = RetrievedEvidence(
            title="Test", source="Test", summary="Test", timestamp="2026-05-01"
        )
        assert hasattr(ev, "retrieval_tags")
        assert ev.retrieval_tags == []

    def test_retrieved_evidence_has_retrieval_weight(self):
        from app.schemas import RetrievedEvidence
        ev = RetrievedEvidence(
            title="Test", source="Test", summary="Test", timestamp="2026-05-01"
        )
        assert hasattr(ev, "retrieval_weight")
        assert ev.retrieval_weight == 1.0

    def test_new_fields_survive_model_dump(self):
        from app.schemas import InvestmentThesis
        thesis = _make_thesis(
            expectation_regime="stretched",
            expectation_shift_severity="moderate",
        )
        dumped = thesis.model_dump()
        assert dumped["expectation_regime"] == "stretched"
        assert dumped["expectation_shift_severity"] == "moderate"
        assert "catalyst_calendar" in dumped

    def test_conviction_result_has_expectation_regime(self):
        """ConvictionResult dataclass has expectation_regime field."""
        from app.services.conviction_modeler import ConvictionResult, ConvictionDimensions
        dims = ConvictionDimensions()
        # ConvictionResult should have expectation_regime with default
        cr = ConvictionResult(
            final_score=0.68,
            dimensions=dims,
            confidence_reasoning="test",
            what_increases_conviction="test",
        )
        assert hasattr(cr, "expectation_regime")
        assert cr.expectation_regime == "fair"

    def test_conviction_result_has_expectation_shift_severity(self):
        from app.services.conviction_modeler import ConvictionResult, ConvictionDimensions
        dims = ConvictionDimensions()
        cr = ConvictionResult(
            final_score=0.68,
            dimensions=dims,
            confidence_reasoning="test",
            what_increases_conviction="test",
        )
        assert hasattr(cr, "expectation_shift_severity")
        assert cr.expectation_shift_severity == "none"
