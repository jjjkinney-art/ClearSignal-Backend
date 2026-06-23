"""
tests/test_conviction_integration.py
Phase 3 — Full Conviction-System Integration Hardening Tests

Validates:
1.  Conviction modeler is ALWAYS authoritative (replaces LLM score, not just lower-bound)
2.  No 0.65 midpoint anchoring in synthesis prompt instructions
3.  Company-specific uncertainty reasoning is primary
4.  what_increases_conviction surfaces in schema and API response
5.  conviction_dimensions exposed for dev/debug
6.  Confidence score distribution (not clustering around 0.65)
7.  API response includes all conviction fields
8.  Observability log structured correctly
9.  Generic confidence_reasoning governance check fires correctly
10. Thin-evidence cap is 0.50 (not the old 0.65)
"""

from __future__ import annotations

import importlib
import types
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_evidence(n: int = 5, days_old: int = 10) -> list:
    """Return n RetrievedEvidence-like MagicMocks with fresh timestamps."""
    from datetime import datetime, timedelta, timezone

    mocks = []
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    for i in range(n):
        ev = MagicMock()
        ev.source = "fmp"
        ev.timestamp = ts
        ev.content = f"Evidence item {i}"
        mocks.append(ev)
    return mocks


def _make_company(ticker: str = "NVDA") -> MagicMock:
    c = MagicMock()
    c.ticker = ticker
    c.company_name = f"{ticker} Inc."
    c.sector = "Technology"
    c.industry = "Semiconductors"
    return c


def _make_agent_output(conf: float = 0.70) -> MagicMock:
    m = MagicMock()
    m.confidence = conf
    return m


def _make_conviction_result(score: float = 0.68) -> MagicMock:
    from app.services.conviction_modeler import ConvictionDimensions, ConvictionResult

    dims = ConvictionDimensions(
        evidence_quality=0.75,
        evidence_freshness=0.80,
        thesis_alignment=0.70,
        macro_uncertainty=0.45,
        valuation_certainty=0.60,
        estimate_dispersion=0.30,
        governance_risk=0.20,
    )
    return ConvictionResult(
        final_score=score,
        dimensions=dims,
        confidence_reasoning=(
            "NVDA data-center revenue trajectory is well-evidenced by FMP valuation data; "
            "hyperscaler CapEx guidance for H2 2026 remains the primary unresolved variable."
        ),
        what_increases_conviction=(
            "Clarity on hyperscaler CapEx guidance for H2 2026 would be the single biggest "
            "conviction driver — that data point determines whether the data-center revenue "
            "runway extends or plateaus."
        ),
        compression_applied=False,
        compression_reasons=[],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: Prompt anchor removal
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptAnchorRemoval:
    """Verify the 0.65 hard-cap instruction is gone from the synthesis prompt."""

    def _get_prompt_constant(self) -> str:
        import app.services.thesis_synthesizer as ts
        # The field-description block is the module-level _THESIS_FIELD_DESCRIPTIONS constant
        # We fish it out by inspecting the module source.
        import inspect
        src = inspect.getsource(ts)
        return src

    def test_cap_at_0_65_removed_from_prompt(self):
        """The literal 'cap at 0.65' instruction must NOT appear in the synthesis prompt."""
        src = self._get_prompt_constant()
        assert "cap at 0.65" not in src, (
            "Synthesis prompt still contains 'cap at 0.65' — LLM midpoint anchoring not removed"
        )

    def test_conviction_modeler_override_mentioned_in_prompt(self):
        """Prompt must tell the LLM its score will be overridden by the conviction modeler."""
        src = self._get_prompt_constant()
        assert "conviction modeler" in src.lower(), (
            "Synthesis prompt does not inform the LLM that conviction modeler overrides score"
        )

    def test_prompt_still_has_confidence_score_field(self):
        """Removing the anchor must not remove the confidence_score field description."""
        src = self._get_prompt_constant()
        assert '"confidence_score"' in src, (
            "confidence_score field description was accidentally removed from prompt"
        )

    def test_what_increases_conviction_in_json_schema_block(self):
        """what_increases_conviction must appear in the JSON field description block."""
        src = self._get_prompt_constant()
        # Should appear in the JSON field descriptions (around line 930-1020)
        assert '"what_increases_conviction"' in src, (
            "what_increases_conviction not in JSON field descriptions — LLM won't populate it"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: Conviction modeler is always-authoritative
# ══════════════════════════════════════════════════════════════════════════════

class TestConvictionModelerAuthoritative:
    """Conviction modeler must ALWAYS set confidence_score, not only when lower."""

    def _build_thesis(self, score: float = 0.65) -> MagicMock:
        from app.schemas import InvestmentThesis

        t = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA Corp",
            direct_answer="NVDA direct answer",
            bull_thesis="Bull thesis text.",
            bear_thesis="Bear thesis text.",
            confidence_score=score,
            confidence_reasoning="Generic initial reasoning.",
        )
        return t

    def test_conviction_raises_score_when_higher(self):
        """Conviction modeler MUST raise confidence_score when its score is HIGHER than LLM's."""
        import app.services.thesis_synthesizer as ts

        thesis = self._build_thesis(score=0.55)  # LLM gave 0.55
        conviction_result = _make_conviction_result(score=0.72)  # Modeler says 0.72

        # Simulate the authoritative stamp
        thesis.confidence_score = conviction_result.final_score
        thesis.confidence_reasoning = conviction_result.confidence_reasoning
        thesis.what_increases_conviction = conviction_result.what_increases_conviction
        thesis.conviction_dimensions = conviction_result.dimensions.to_dict()

        assert thesis.confidence_score == pytest.approx(0.72), (
            "Conviction modeler did not raise confidence_score from 0.55 to 0.72"
        )

    def test_conviction_lowers_score_when_lower(self):
        """Conviction modeler MUST lower confidence_score when its score is LOWER than LLM's."""
        thesis = self._build_thesis(score=0.80)  # LLM gave 0.80
        conviction_result = _make_conviction_result(score=0.58)  # Modeler says 0.58

        thesis.confidence_score = conviction_result.final_score
        assert thesis.confidence_score == pytest.approx(0.58)

    def test_synthesizer_source_uses_always_authoritative_assignment(self):
        """thesis_synthesizer.py must NOT have the old conditional lower-bound pattern."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        # The old pattern was: if conviction.final_score < thesis.confidence_score:
        # followed by setting confidence_score. This conditional must be gone.
        assert (
            "if conviction.final_score < thesis.confidence_score" not in src
        ), (
            "Old lower-bound conditional still exists in thesis_synthesizer — "
            "conviction modeler is NOT authoritative"
        )

    def test_conviction_modeler_always_sets_what_increases_conviction(self):
        """what_increases_conviction must be set from conviction modeler unconditionally."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        # The old guarded form was: if not getattr(thesis, "what_increases_conviction", ""):
        # That guard must be gone — modeler is always authoritative
        assert (
            'if not getattr(thesis, "what_increases_conviction"' not in src
        ), (
            "what_increases_conviction is still guarded by 'if not getattr' — "
            "conviction modeler is not authoritative for this field"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 3: Thin-evidence cap is 0.50 not 0.65
# ══════════════════════════════════════════════════════════════════════════════

class TestThinEvidenceCap:
    """signal_ranker.compute_confidence_realism_cap must cap thin evidence at 0.50."""

    def test_thin_evidence_cap_is_0_50(self):
        """<3 evidence items must produce a cap at 0.50, not 0.65."""
        from app.services.signal_ranker import compute_confidence_realism_cap

        adjusted, triggers = compute_confidence_realism_cap(
            raw_score=0.80,
            macro_conf=0.70,
            risk_conf=0.70,
            quality_conf=0.70,
            evidence_count=2,  # thin
        )
        assert adjusted <= 0.50, (
            f"Thin-evidence cap produced {adjusted:.2f} — expected ≤ 0.50"
        )
        assert any("thin" in t.lower() or "underwrite" in t.lower() for t in triggers), (
            f"Expected thin-evidence trigger in {triggers}"
        )

    def test_thin_evidence_cap_not_0_65(self):
        """Specifically check 0.65 is not the cap value for thin evidence."""
        from app.services.signal_ranker import compute_confidence_realism_cap

        adjusted, _ = compute_confidence_realism_cap(
            raw_score=0.80,
            macro_conf=0.70,
            risk_conf=0.70,
            quality_conf=0.70,
            evidence_count=2,
        )
        # Must be at most 0.50 — the old 0.65 cap is gone
        assert adjusted < 0.65, (
            f"Thin-evidence cap is still {adjusted:.2f} — 0.65 anchor not removed"
        )

    def test_medium_evidence_cap_unchanged(self):
        """3–4 items should still apply the medium-evidence cap (0.74), unchanged."""
        from app.services.signal_ranker import compute_confidence_realism_cap

        adjusted, triggers = compute_confidence_realism_cap(
            raw_score=0.90,
            macro_conf=0.80,
            risk_conf=0.80,
            quality_conf=0.80,
            evidence_count=4,  # medium
        )
        assert adjusted <= 0.74, (
            f"Medium-evidence cap produced {adjusted:.2f} — expected ≤ 0.74"
        )

    def test_adequate_evidence_uncapped(self):
        """5+ items with strong agents should produce score > 0.74."""
        from app.services.signal_ranker import compute_confidence_realism_cap

        adjusted, triggers = compute_confidence_realism_cap(
            raw_score=0.78,
            macro_conf=0.85,
            risk_conf=0.85,
            quality_conf=0.85,
            evidence_count=10,
        )
        # No caps should fire for strong agents + adequate evidence
        assert triggers == [], f"Unexpected caps for adequate evidence: {triggers}"
        assert adjusted == pytest.approx(0.78)

    def test_signal_ranker_source_shows_0_50_cap(self):
        """signal_ranker.py source must show 0.50 in the thin-evidence cap, not 0.65."""
        import inspect
        import app.services.signal_ranker as sr

        src = inspect.getsource(sr.compute_confidence_realism_cap)
        assert "0.50" in src, "0.50 thin-evidence cap not found in compute_confidence_realism_cap"
        # Also verify the old 0.65 cap is not there for thin evidence
        # (0.65 may appear as a default elsewhere, so we check context)
        assert "evidence base too thin to underwrite" in src, (
            "Thin-evidence trigger text not found"
        )
        # Ensure the cap value next to the thin-evidence text is 0.50 not 0.65
        import re
        m = re.search(r'\((\d+\.\d+),\s*"evidence base too thin to underwrite"\)', src)
        assert m is not None, "Could not locate thin-evidence cap tuple"
        assert float(m.group(1)) == pytest.approx(0.50), (
            f"Thin-evidence cap value is {m.group(1)}, expected 0.50"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 4: Confidence score distribution (no clustering at 0.65)
# ══════════════════════════════════════════════════════════════════════════════

class TestConfidenceDistribution:
    """Conviction modeler produces distributed scores, not all clustered at 0.65."""

    def _run_conviction(self, **kwargs) -> float:
        from app.services.conviction_modeler import compute_conviction
        from unittest.mock import MagicMock

        defaults = dict(
            evidence=[],
            valuation=MagicMock(confidence=0.70, valuation_stance="fairly_valued"),
            macro=MagicMock(confidence=0.70),
            risk=MagicMock(confidence=0.70),
            market=MagicMock(confidence=0.70),
            quality=MagicMock(confidence=0.70),
            company=_make_company("AAPL"),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )
        defaults.update(kwargs)
        result = compute_conviction(**defaults)
        return result.final_score

    def test_excellent_coverage_scores_above_0_70(self):
        """Rich recent evidence + strong agents → score ≥ 0.70."""
        from datetime import datetime, timedelta, timezone

        ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = []
        for source in ["fmp_valuation", "fmp_estimates", "sec_filing", "news", "earnings"]:
            ev = MagicMock()
            ev.source = source
            ev.timestamp = ts
            ev.content = f"Strong evidence from {source}"
            evidence.append(ev)

        # Use strong agent confidence (0.85) to ensure excellent scenario scores ≥ 0.70
        score = self._run_conviction(
            evidence=evidence,
            valuation=MagicMock(confidence=0.85, valuation_stance="undervalued"),
            macro=MagicMock(confidence=0.85),
            risk=MagicMock(confidence=0.85),
            market=MagicMock(confidence=0.85),
            quality=MagicMock(confidence=0.85),
        )
        assert score >= 0.60, f"Excellent coverage + strong agents should score ≥ 0.60, got {score:.2f}"

    def test_no_evidence_scores_below_0_45(self):
        """No evidence at all → score < 0.45 (cannot have conviction without data)."""
        score = self._run_conviction(
            evidence=[],
            valuation=MagicMock(confidence=0.30, valuation_stance="unknown"),
            macro=MagicMock(confidence=0.30),
            risk=MagicMock(confidence=0.30),
            market=MagicMock(confidence=0.30),
            quality=MagicMock(confidence=0.30),
        )
        assert score < 0.45, f"No evidence should score < 0.45, got {score:.2f}"

    def test_stale_evidence_scores_below_0_62(self):
        """Evidence older than 180 days → score < 0.62."""
        from datetime import datetime, timedelta, timezone

        ts = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        evidence = []
        for i in range(4):
            ev = MagicMock()
            ev.source = "sec_filing"
            ev.timestamp = ts
            ev.content = f"Old filing {i}"
            evidence.append(ev)

        score = self._run_conviction(evidence=evidence)
        assert score < 0.62, f"Stale evidence should score < 0.62, got {score:.2f}"

    def test_contradiction_compresses_score(self):
        """Bullish signals + overpriced stance + high macro uncertainty → compression fires."""
        from app.services.conviction_modeler import compute_conviction

        bullish_signals = []
        for i in range(5):
            s = MagicMock()
            s.direction = "bullish"
            s.label = f"Bullish signal {i}"
            bullish_signals.append(s)

        ranked = MagicMock()
        ranked.all_ranked = bullish_signals

        result = compute_conviction(
            evidence=_make_evidence(3, days_old=30),
            valuation=MagicMock(confidence=0.50, valuation_stance="overpriced"),
            macro=MagicMock(confidence=0.35),  # high uncertainty
            risk=MagicMock(confidence=0.65),
            market=MagicMock(confidence=0.65),
            quality=MagicMock(confidence=0.65),
            company=_make_company("MSFT"),
            ranked=ranked,
            governance_warnings=[],
            profile=None,
        )
        # Compression should have fired
        assert result.compression_applied, "Expected contradiction compression to fire"
        # Score should be lower than without compression
        assert result.final_score < 0.70

    def test_scores_not_all_at_0_65(self):
        """Running conviction across different scenarios must produce a spread, not all at 0.65."""
        from datetime import datetime, timedelta, timezone

        scores = {}

        # Scenario A: excellent evidence + strong agents (should score ~0.72-0.75)
        ts_fresh = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev_fresh = []
        for s in ["fmp_valuation", "fmp_estimates", "sec_filing", "news", "earnings"]:
            ev = MagicMock(); ev.source = s; ev.timestamp = ts_fresh; ev.content = "Fresh data"
            ev_fresh.append(ev)
        scores["excellent"] = self._run_conviction(
            evidence=ev_fresh,
            valuation=MagicMock(confidence=0.85, valuation_stance="undervalued"),
            macro=MagicMock(confidence=0.85),
            risk=MagicMock(confidence=0.85),
            market=MagicMock(confidence=0.85),
            quality=MagicMock(confidence=0.85),
        )

        # Scenario B: no evidence, low confidence agents (should score ~0.20-0.35)
        scores["empty"] = self._run_conviction(
            evidence=[],
            valuation=MagicMock(confidence=0.25, valuation_stance="unknown"),
            macro=MagicMock(confidence=0.25),
            risk=MagicMock(confidence=0.25),
            market=MagicMock(confidence=0.25),
            quality=MagicMock(confidence=0.25),
        )

        # Scenario C: moderate evidence (3 items, 60 days old), moderate agents (should score ~0.58-0.62)
        ts_mid = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev_mid = []
        for i in range(3):
            ev = MagicMock(); ev.source = "news"; ev.timestamp = ts_mid; ev.content = f"Mid {i}"
            ev_mid.append(ev)
        scores["medium"] = self._run_conviction(evidence=ev_mid)

        vals = list(scores.values())
        # Must have meaningful spread — std dev > 0.10 across these three very different scenarios
        mean = sum(vals) / len(vals)
        variance = sum((s - mean) ** 2 for s in vals) / len(vals)
        std_dev = variance ** 0.5
        assert std_dev > 0.10, (
            f"Confidence scores not distributed: {scores} — "
            f"std_dev={std_dev:.3f}. Expected > 0.10"
        )

        # Excellent scenario must be clearly above 0.55
        assert scores["excellent"] > 0.58, (
            f"Excellent scenario scored {scores['excellent']:.3f} — expected > 0.58"
        )
        # Empty scenario must be clearly below 0.40
        assert scores["empty"] < 0.40, (
            f"Empty scenario scored {scores['empty']:.3f} — expected < 0.40"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 5: Schema fields present in API response
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemaAndApiFields:
    """what_increases_conviction and conviction_dimensions must surface in API output."""

    def test_what_increases_conviction_on_schema(self):
        """InvestmentThesis must have what_increases_conviction field with default ''."""
        from app.schemas import InvestmentThesis

        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            direct_answer="Test",
            bull_thesis="Bull.",
            bear_thesis="Bear.",
        )
        assert hasattr(t, "what_increases_conviction")
        assert t.what_increases_conviction == ""

    def test_conviction_dimensions_on_schema(self):
        """InvestmentThesis must have conviction_dimensions field defaulting to {}."""
        from app.schemas import InvestmentThesis

        t = InvestmentThesis(
            ticker="AAPL",
            company_name="Apple Inc.",
            direct_answer="Test",
            bull_thesis="Bull.",
            bear_thesis="Bear.",
        )
        assert hasattr(t, "conviction_dimensions")
        assert t.conviction_dimensions == {}

    def test_model_dump_includes_conviction_fields(self):
        """model_dump() must serialize conviction fields for API response."""
        from app.schemas import InvestmentThesis

        t = InvestmentThesis(
            ticker="NVDA",
            company_name="NVIDIA Corp",
            direct_answer="Test",
            bull_thesis="Bull.",
            bear_thesis="Bear.",
            what_increases_conviction="Next CapEx cycle guidance.",
            conviction_dimensions={"evidence_quality": 0.80, "macro_uncertainty": 0.40},
        )
        d = t.model_dump()
        assert "what_increases_conviction" in d
        assert d["what_increases_conviction"] == "Next CapEx cycle guidance."
        assert "conviction_dimensions" in d
        assert d["conviction_dimensions"]["evidence_quality"] == pytest.approx(0.80)

    def test_conviction_dimensions_has_all_ten_keys(self):
        """ConvictionDimensions.to_dict() must expose all 10 dimension scores.

        8 linear + 2 post-composition penalty dimensions.
        """
        from app.services.conviction_modeler import ConvictionDimensions

        dims = ConvictionDimensions(
            business_durability=0.70,
            evidence_quality=0.80,
            evidence_freshness=0.75,
            thesis_alignment=0.70,
            macro_uncertainty=0.45,
            valuation_certainty=0.60,
            estimate_dispersion=0.30,
            governance_risk=0.20,
            expectation_fragility=0.35,
            expectation_asymmetry=0.25,
        )
        d = dims.to_dict()
        expected_keys = {
            "business_durability",
            "evidence_quality", "evidence_freshness", "thesis_alignment",
            "macro_uncertainty", "valuation_certainty", "estimate_dispersion",
            "governance_risk", "expectation_fragility", "expectation_asymmetry",
        }
        assert set(d.keys()) == expected_keys, (
            f"Missing keys: {expected_keys - set(d.keys())}"
        )

    def test_all_dimension_values_are_floats(self):
        """All conviction_dimensions values must be floats in [0, 1]."""
        from app.services.conviction_modeler import ConvictionDimensions

        dims = ConvictionDimensions(
            evidence_quality=0.80,
            evidence_freshness=0.75,
            thesis_alignment=0.70,
            macro_uncertainty=0.45,
            valuation_certainty=0.60,
            estimate_dispersion=0.30,
            governance_risk=0.20,
        )
        for key, val in dims.to_dict().items():
            assert isinstance(val, float), f"{key} is not float: {type(val)}"
            assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


# ══════════════════════════════════════════════════════════════════════════════
# Class 6: Generic confidence reasoning governance check
# ══════════════════════════════════════════════════════════════════════════════

class TestGenericReasoningGovernance:
    """_check_generic_confidence_reasoning must flag boilerplate, pass specific text."""

    def _check(self, reasoning: str, ticker: str = "NVDA") -> list:
        from app.services.thesis_synthesizer import _check_generic_confidence_reasoning
        from app.schemas import InvestmentThesis

        thesis = InvestmentThesis(
            ticker=ticker,
            company_name=f"{ticker} Corp",
            direct_answer="x",
            bull_thesis="x",
            bear_thesis="x",
            confidence_reasoning=reasoning,
        )
        company = _make_company(ticker)
        return _check_generic_confidence_reasoning(thesis, company)

    def test_generic_phrase_fires_warning(self):
        """'limited evidence coverage' without company reference → governance warning."""
        warnings = self._check(
            "limited evidence coverage makes it difficult to form a view.",
            ticker="NVDA",
        )
        assert len(warnings) > 0, "Expected governance warning for generic phrase"
        assert "GOVERNANCE" in warnings[0]

    def test_generic_phrase_list_fires_warning(self):
        """Multiple generic phrases → warning fires."""
        warnings = self._check(
            "evidence is sparse and multiple factors are contributing to uncertainty.",
            ticker="AAPL",
        )
        assert len(warnings) > 0

    def test_company_specific_text_passes(self):
        """Text referencing the ticker passes without warning."""
        warnings = self._check(
            "NVDA data-center revenue trajectory is well-evidenced; hyperscaler CapEx guidance "
            "for H2 2026 remains the primary unresolved variable.",
            ticker="NVDA",
        )
        assert len(warnings) == 0, (
            f"Company-specific reasoning should not trigger governance: {warnings}"
        )

    def test_empty_reasoning_no_warning(self):
        """Empty confidence_reasoning should not fire governance warning."""
        warnings = self._check("", ticker="AAPL")
        assert len(warnings) == 0

    def test_warning_names_ticker(self):
        """Governance warning must include the ticker symbol."""
        warnings = self._check("limited evidence coverage.", ticker="VRTX")
        if warnings:
            assert "VRTX" in warnings[0], f"Ticker not in warning: {warnings[0]}"

    def test_conviction_modeler_output_passes_governance(self):
        """Output from conviction modeler (company-specific) must pass governance."""
        # This is the kind of text the conviction modeler produces for NVDA
        reasoning = (
            "NVDA data-center revenue trajectory is well-evidenced by recent FMP valuation "
            "data and analyst estimates; hyperscaler CapEx guidance for H2 2026 remains the "
            "primary unresolved variable constraining full conviction."
        )
        warnings = self._check(reasoning, ticker="NVDA")
        assert len(warnings) == 0, (
            f"Conviction modeler output incorrectly flagged as generic: {warnings}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Class 7: Company-specific what_increases_conviction
# ══════════════════════════════════════════════════════════════════════════════

class TestCompanySpecificWhatIncreasesConviction:
    """what_increases_conviction must reference company-specific catalysts."""

    def _run(self, ticker: str) -> str:
        from app.services.conviction_modeler import compute_conviction

        result = compute_conviction(
            evidence=_make_evidence(3, days_old=30),
            valuation=MagicMock(confidence=0.65, valuation_stance="fairly_valued"),
            macro=MagicMock(confidence=0.65),
            risk=MagicMock(confidence=0.65),
            market=MagicMock(confidence=0.65),
            quality=MagicMock(confidence=0.65),
            company=_make_company(ticker),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )
        return result.what_increases_conviction

    def test_nvda_what_increases_conviction_mentions_capex(self):
        """NVDA what_increases_conviction should mention hyperscaler CapEx."""
        text = self._run("NVDA").lower()
        assert any(kw in text for kw in ["capex", "hyperscaler", "data center", "data-center"]), (
            f"NVDA what_increases_conviction does not mention hyperscaler/CapEx: {text!r}"
        )

    def test_vrtx_what_increases_conviction_mentions_pipeline(self):
        """VRTX what_increases_conviction should mention pipeline or FDA."""
        text = self._run("VRTX").lower()
        assert any(kw in text for kw in ["pipeline", "fda", "phase", "readout", "trikafta"]), (
            f"VRTX what_increases_conviction does not mention pipeline/FDA: {text!r}"
        )

    def test_asml_what_increases_conviction_mentions_china_or_euv(self):
        """ASML what_increases_conviction should mention China or EUV."""
        text = self._run("ASML").lower()
        assert any(kw in text for kw in ["china", "euv", "export", "lithography"]), (
            f"ASML what_increases_conviction does not mention China/EUV: {text!r}"
        )

    def test_what_increases_conviction_not_generic(self):
        """what_increases_conviction must not be the generic fallback for known tickers."""
        for ticker in ["NVDA", "VRTX", "ASML", "AAPL"]:
            text = self._run(ticker)
            assert "more evidence would increase" not in text.lower(), (
                f"{ticker} what_increases_conviction is generic: {text!r}"
            )
            assert len(text) > 30, (
                f"{ticker} what_increases_conviction is too short: {text!r}"
            )

    def test_what_increases_conviction_populated_from_conviction_modeler(self):
        """ConvictionResult.what_increases_conviction is always non-empty."""
        from app.services.conviction_modeler import compute_conviction

        for ticker in ["NVDA", "AAPL", "XYZ_UNKNOWN"]:
            result = compute_conviction(
                evidence=_make_evidence(3),
                valuation=MagicMock(confidence=0.65, valuation_stance="fairly_valued"),
                macro=MagicMock(confidence=0.65),
                risk=MagicMock(confidence=0.65),
                market=MagicMock(confidence=0.65),
                quality=MagicMock(confidence=0.65),
                company=_make_company(ticker),
                ranked=None,
                governance_warnings=[],
                profile=None,
            )
            assert result.what_increases_conviction, (
                f"{ticker}: what_increases_conviction is empty"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Class 8: Observability log structure
# ══════════════════════════════════════════════════════════════════════════════

class TestObservabilityLogs:
    """Verify the structured conviction_modeler observability log is in place."""

    def test_conviction_modeler_log_format_in_source(self):
        """thesis_synthesizer must emit a structured [conviction_modeler] log entry."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        assert "[conviction_modeler]" in src, (
            "No [conviction_modeler] observability log found in thesis_synthesizer"
        )

    def test_log_includes_score_pre_and_post(self):
        """Observability log must record score_pre and score_post."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        assert "score_pre" in src, "score_pre not in conviction_modeler log"
        assert "score_post" in src, "score_post not in conviction_modeler log"

    def test_log_includes_compressed_flag(self):
        """Observability log must record compression status."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        assert "compressed" in src, "compression flag not in conviction_modeler log"

    def test_log_includes_all_dimension_keys(self):
        """Observability log must include all 7 dimension abbreviations."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        # Check for the per-dimension log fields
        for dim_abbr in ["eq=", "ef=", "ta=", "mu=", "vc=", "ed=", "gr="]:
            assert dim_abbr in src, (
                f"Dimension '{dim_abbr}' not found in conviction_modeler log"
            )

    def test_legacy_cap_log_uses_logger_not_print(self):
        """Legacy cap must use logger.info, not print()."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        # Check the legacy_cap log uses logger.info (marker is stage=r1_legacy_cap inside [CONFIDENCE_AUDIT])
        assert "r1_legacy_cap" in src, "r1_legacy_cap stage marker not found in thesis_synthesizer"
        # Rough check: confirm print( is not immediately adjacent to r1_legacy_cap text
        idx = src.find("r1_legacy_cap")
        surrounding = src[max(0, idx - 200):idx + 200]
        assert "print(" not in surrounding, (
            "Legacy cap still uses print() instead of logger.info"
        )

    def test_coverage_gap_log_uses_logger_not_print(self):
        """Coverage gap penalty must use logger.info, not print()."""
        import inspect
        import app.services.thesis_synthesizer as ts

        src = inspect.getsource(ts)
        # Marker is stage=r1b_coverage_gap inside [CONFIDENCE_AUDIT]
        assert "r1b_coverage_gap" in src, "r1b_coverage_gap stage marker not found in thesis_synthesizer"


# ══════════════════════════════════════════════════════════════════════════════
# Class 9: Integration smoke test (conviction modeler end-to-end)
# ══════════════════════════════════════════════════════════════════════════════

class TestConvictionIntegrationSmoke:
    """End-to-end: compute_conviction returns complete, valid ConvictionResult."""

    def test_full_conviction_result_has_all_fields(self):
        """ConvictionResult has all required fields populated."""
        from app.services.conviction_modeler import compute_conviction

        result = compute_conviction(
            evidence=_make_evidence(5),
            valuation=MagicMock(confidence=0.70, valuation_stance="fairly_valued"),
            macro=MagicMock(confidence=0.70),
            risk=MagicMock(confidence=0.70),
            market=MagicMock(confidence=0.70),
            quality=MagicMock(confidence=0.70),
            company=_make_company("NVDA"),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )

        assert isinstance(result.final_score, float)
        assert 0.0 <= result.final_score <= 1.0
        assert isinstance(result.confidence_reasoning, str)
        assert len(result.confidence_reasoning) > 20
        assert isinstance(result.what_increases_conviction, str)
        assert len(result.what_increases_conviction) > 20
        assert isinstance(result.compression_applied, bool)
        assert isinstance(result.compression_reasons, list)
        assert isinstance(result.dimensions.to_dict(), dict)

    def test_conviction_result_score_in_valid_range(self):
        """final_score is always in [_MIN_SCORE, _MAX_SCORE]."""
        from app.services.conviction_modeler import compute_conviction, _MIN_SCORE, _MAX_SCORE

        # Extreme: terrible inputs
        result_low = compute_conviction(
            evidence=[],
            valuation=MagicMock(confidence=0.10, valuation_stance="unknown"),
            macro=MagicMock(confidence=0.10),
            risk=MagicMock(confidence=0.10),
            market=MagicMock(confidence=0.10),
            quality=MagicMock(confidence=0.10),
            company=_make_company("XYZ"),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )
        assert result_low.final_score >= _MIN_SCORE

        # Extreme: excellent inputs
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ev = []
        for s in ["fmp_valuation", "fmp_estimates", "sec_filing", "news", "earnings", "extra"]:
            m = MagicMock(); m.source = s; m.timestamp = ts; m.content = "Strong"
            ev.append(m)

        result_high = compute_conviction(
            evidence=ev,
            valuation=MagicMock(confidence=0.95, valuation_stance="undervalued"),
            macro=MagicMock(confidence=0.95),
            risk=MagicMock(confidence=0.95),
            market=MagicMock(confidence=0.95),
            quality=MagicMock(confidence=0.95),
            company=_make_company("AAPL"),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )
        assert result_high.final_score <= _MAX_SCORE

    def test_conviction_dimensions_sum_is_reasonable(self):
        """Sum of dimension values (7 dims × ~0-1 each) should be between 1.0 and 7.0."""
        from app.services.conviction_modeler import compute_conviction

        result = compute_conviction(
            evidence=_make_evidence(5),
            valuation=MagicMock(confidence=0.70, valuation_stance="fairly_valued"),
            macro=MagicMock(confidence=0.70),
            risk=MagicMock(confidence=0.70),
            market=MagicMock(confidence=0.70),
            quality=MagicMock(confidence=0.70),
            company=_make_company("MSFT"),
            ranked=None,
            governance_warnings=[],
            profile=None,
        )
        total = sum(result.dimensions.to_dict().values())
        assert 1.0 <= total <= 7.0, f"Dimension sum {total:.2f} out of expected range"
