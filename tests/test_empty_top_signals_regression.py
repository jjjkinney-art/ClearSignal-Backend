"""
tests/test_empty_top_signals_regression.py

Regression suite: empty top_signals arrays for MSFT and AMD.

Root cause
----------
When the LLM returns a JSON array as a JSON-encoded string on the
``signals`` field of any agent output (e.g. ValuationView, MacroSensitivity,
RiskProfile, MarketContext, QualityAssessment):

    "signals": "[{\"signal\": \"...\", \"direction\": \"bullish\", ...}]"

...the old repair_data() logic split the string on hyphen characters
(which appear in JSON strings), producing garbage fragments.  Pydantic
could not coerce those fragments to Signal objects, validation failed,
max retries were exhausted, and the agent returned a fallback
ValuationView() with signals=[].  signal_ranker._collect_signals() then
had nothing to rank, so top_signals=[] and top_risks=[] for the entire
thesis — even for well-covered companies like MSFT and AMD.

Fix
---
Commit 64c4fd0 (fix(repair-data): parse stringified JSON arrays so
signals/risks don't render as raw strings) added a json.loads pre-pass
inside repair_data().  When a string value starts with '[' and ends
with ']', the code now tries json.loads before falling through to the
split-on-delimiter logic.  For stringified signal arrays this produces
the correct list of signal dicts, which Pydantic successfully coerces
to List[Signal].

Proof strategy
--------------
1. Simulate the OLD behavior by calling the split-on-delimiter logic
   directly and confirming it produces garbage that fails validation.
2. Call repair_data() with the current (fixed) code and confirm it
   produces valid Signal objects.
3. Run rank_signals() end-to-end and assert top_signals is non-empty
   for MSFT and AMD when signals are present in agent output.

Run
---
    python3 -m pytest tests/test_empty_top_signals_regression.py -v
"""

from __future__ import annotations

import json
import re
import pytest
from pydantic import ValidationError

from app.schemas import (
    CompanyContext,
    MacroSensitivity,
    MarketContext,
    QualityAssessment,
    RiskProfile,
    Signal,
    ValuationView,
)
from app.services.signal_ranker import rank_signals
from app.structured_output import repair_data


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def msft_company():
    return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation")


@pytest.fixture
def amd_company():
    return CompanyContext(ticker="AMD", company_name="Advanced Micro Devices")


@pytest.fixture
def msft_signals_raw():
    """Signals as a proper list of dicts — what the LLM SHOULD return."""
    return [
        {
            "signal": (
                "Azure cloud 29% growth drives FCF expansion and P/E multiple "
                "support at 32x — not yet fully priced at current levels"
            ),
            "direction": "bullish",
            "signal_type": "structural",
            "impact_score": 0.88,
            "time_horizon": "medium_term",
            "confidence": 0.78,
            "importance_reason": "Primary revenue driver for MSFT premium multiple",
            "evidence_origin": "earnings call",
            "source_category": "earnings",
        },
        {
            "signal": (
                "Copilot enterprise attach rate approaching 30% of O365 base — "
                "upsell runway not yet in sell-side consensus estimates"
            ),
            "direction": "bullish",
            "signal_type": "catalyst",
            "impact_score": 0.75,
            "time_horizon": "medium_term",
            "confidence": 0.68,
            "importance_reason": "Near-term catalyst with unpriced upside",
            "evidence_origin": "product announcement",
            "source_category": "news",
        },
    ]


@pytest.fixture
def amd_signals_raw():
    """Signals as a proper list of dicts for AMD."""
    return [
        {
            "signal": (
                "MI300 GPU ramp at $4B quarterly run rate implies 35% data-center "
                "GPU share by H2 2026 vs ~18% today — significant EPS accretion path"
            ),
            "direction": "bullish",
            "signal_type": "structural",
            "impact_score": 0.90,
            "time_horizon": "medium_term",
            "confidence": 0.75,
            "importance_reason": "Thesis-defining revenue shift",
            "evidence_origin": "earnings call",
            "source_category": "earnings",
        },
        {
            "signal": (
                "EPYC server CPU share at 24% vs Intel legacy — "
                "100bps share gain per quarter adds ~$350M to annual revenue"
            ),
            "direction": "bullish",
            "signal_type": "catalyst",
            "impact_score": 0.80,
            "time_horizon": "medium_term",
            "confidence": 0.72,
            "importance_reason": "Structural market share gain against entrenched competitor",
            "evidence_origin": "analyst research",
            "source_category": "research",
        },
        {
            "signal": (
                "Nvidia CUDA moat limits AMD GPU software adoption — "
                "enterprise ML inference still ~90% Nvidia, switching cost is high"
            ),
            "direction": "bearish",
            "signal_type": "risk",
            "impact_score": 0.75,
            "time_horizon": "long_term",
            "confidence": 0.80,
            "importance_reason": "Structural competitive risk constraining bull case",
            "evidence_origin": "market data",
            "source_category": "market_data",
        },
    ]


def _make_empty_agents():
    """Return agent stubs with non-zero confidence and no signals."""
    return (
        MacroSensitivity(overall="macro stub", confidence=0.55, signals=[]),
        RiskProfile(overall="risk stub", confidence=0.55, signals=[], key_risks=[]),
        MarketContext(overall="market stub", confidence=0.55, signals=[]),
        QualityAssessment(overall="quality stub", confidence=0.55, signals=[]),
    )


# ── Before-fix simulation ─────────────────────────────────────────────────────

class TestBeforeFixBehavior:
    """Prove the OLD repair_data logic caused empty signals.

    We cannot un-apply the fix to the module, but we can simulate what
    the old split-on-delimiter code produced and verify that it fails
    Pydantic validation — demonstrating why signals were lost.
    """

    def test_old_split_on_stringified_array_produces_garbage(self, msft_signals_raw):
        """Old repair_data split on hyphens and produced fragments that fail as Signal."""
        stringified = json.dumps(msft_signals_raw)
        # Replicate the OLD split-on-delimiter logic exactly:
        old_result = [
            item.strip().lstrip("-").strip()
            for item in re.split(r"[\n\r]+|•|\-|;|\*", stringified)
            if item.strip()
        ]
        # Old logic produced multiple small string fragments — NOT Signal dicts
        assert len(old_result) > 1, (
            "Expected old logic to split into multiple fragments, not a single element"
        )
        for fragment in old_result:
            assert not fragment.startswith("{"), (
                f"Fragment {fragment!r} looks like a JSON object — old logic should not produce that"
            )

    def test_old_fragments_fail_valuation_view_validation(self, msft_signals_raw):
        """After old split, ValuationView.model_validate raises ValidationError."""
        stringified = json.dumps(msft_signals_raw)
        old_fragments = [
            item.strip().lstrip("-").strip()
            for item in re.split(r"[\n\r]+|•|\-|;|\*", stringified)
            if item.strip()
        ]
        data = {
            "pe_assessment": "MSFT at ~32x forward P/E",
            "overall": "Microsoft cloud transition",
            "confidence": 0.72,
            "signals": old_fragments,  # garbage fragments
        }
        with pytest.raises(ValidationError):
            ValuationView.model_validate(data)

    def test_before_fix_agent_would_return_empty_signals(self, msft_signals_raw):
        """Simulating the agent fallback: empty ValuationView() with signals=[].

        When max_retries are exhausted (because both the raw and repaired
        validations fail), get_structured_response returns ValuationView().
        This fallback has signals=[].
        """
        fallback = ValuationView()
        assert fallback.signals == [], (
            "Fallback ValuationView() must have signals=[] — confirms pre-fix state"
        )

    def test_before_fix_empty_agent_signals_produce_empty_top_signals(
        self, msft_company, msft_signals_raw
    ):
        """With empty agent signals (pre-fix state), rank_signals returns top_signals=[]."""
        val_before = ValuationView(
            overall="MSFT valuation overview",
            confidence=0.72,
            signals=[],  # ← pre-fix: signals lost due to stringified-array bug
        )
        macro, risk, market, quality = _make_empty_agents()
        ranked = rank_signals(
            val_before, macro, risk, market, quality, company=msft_company
        )
        assert ranked.top_signals == [], (
            "Pre-fix: empty agent signals must produce empty top_signals"
        )


# ── After-fix: MSFT ───────────────────────────────────────────────────────────

class TestMsftSignalsAfterFix:
    """After the repair_data fix, MSFT returns populated top_signals."""

    def test_msft_stringified_signals_repaired_to_dicts(self, msft_signals_raw):
        """repair_data correctly parses the stringified signal array back to dicts."""
        data = {"signals": json.dumps(msft_signals_raw)}
        repaired = repair_data(data, ValuationView)
        result = repaired["signals"]
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == len(msft_signals_raw), (
            f"Expected {len(msft_signals_raw)} signals, got {len(result)}"
        )
        for item in result:
            assert isinstance(item, dict), (
                f"Each signal must be a dict after repair, got {type(item)}: {item!r}"
            )

    def test_msft_repaired_signals_validate_to_signal_objects(self, msft_signals_raw):
        """After repair, ValuationView.model_validate produces real Signal objects."""
        data = {
            "pe_assessment": "MSFT at ~32x forward P/E",
            "overall": "Microsoft cloud transition durable",
            "confidence": 0.72,
            "signals": json.dumps(msft_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        v = ValuationView.model_validate(repaired)
        assert len(v.signals) == len(msft_signals_raw)
        for sig in v.signals:
            assert isinstance(sig, Signal)
            assert sig.direction in ("bullish", "bearish", "neutral")
            assert 0.0 <= sig.impact_score <= 1.0

    def test_msft_top_signals_non_empty_after_fix(self, msft_company, msft_signals_raw):
        """End-to-end: rank_signals returns non-empty top_signals for MSFT."""
        data = {
            "pe_assessment": "MSFT at ~32x forward P/E",
            "overall": "Microsoft cloud transition durable",
            "confidence": 0.72,
            "signals": json.dumps(msft_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        val = ValuationView.model_validate(repaired)
        macro, risk, market, quality = _make_empty_agents()
        ranked = rank_signals(val, macro, risk, market, quality, company=msft_company)
        assert len(ranked.top_signals) > 0, (
            "MSFT top_signals must be non-empty after fix. "
            "Signals were lost before fix because repair_data split the stringified "
            "JSON array on hyphens, producing garbage that failed Signal validation."
        )

    def test_msft_top_signals_are_bullish(self, msft_company, msft_signals_raw):
        """MSFT bullish signals appear in top_signals, not top_risks."""
        data = {
            "overall": "Microsoft cloud transition",
            "confidence": 0.72,
            "signals": json.dumps(msft_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        val = ValuationView.model_validate(repaired)
        macro, risk, market, quality = _make_empty_agents()
        ranked = rank_signals(val, macro, risk, market, quality, company=msft_company)
        directions = [s.direction for s in ranked.top_signals]
        assert all(d in ("bullish", "neutral") for d in directions), (
            f"top_signals must only contain bullish/neutral signals, got {directions}"
        )

    def test_msft_before_vs_after_signal_count(self, msft_company, msft_signals_raw):
        """Before fix: top_signals=0. After fix: top_signals>0. Prove both."""
        # BEFORE: empty signals (what fallback ValuationView() returns)
        val_before = ValuationView(overall="test", confidence=0.72, signals=[])
        macro, risk, market, quality = _make_empty_agents()
        ranked_before = rank_signals(
            val_before, macro, risk, market, quality, company=msft_company
        )
        assert ranked_before.top_signals == [], "Pre-fix state must produce 0 top_signals"

        # AFTER: signals properly parsed via repair_data
        data = {
            "overall": "Microsoft cloud transition",
            "confidence": 0.72,
            "signals": json.dumps(msft_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        val_after = ValuationView.model_validate(repaired)
        ranked_after = rank_signals(
            val_after, macro, risk, market, quality, company=msft_company
        )
        assert len(ranked_after.top_signals) > 0, "Post-fix state must produce >0 top_signals"
        # The delta: fix converts 0 → N signals
        delta = len(ranked_after.top_signals) - len(ranked_before.top_signals)
        assert delta > 0, f"Expected positive signal count delta, got {delta}"


# ── After-fix: AMD ────────────────────────────────────────────────────────────

class TestAmdSignalsAfterFix:
    """After the repair_data fix, AMD returns populated top_signals."""

    def test_amd_stringified_signals_repaired_to_dicts(self, amd_signals_raw):
        """repair_data correctly parses AMD's stringified signal array."""
        data = {"signals": json.dumps(amd_signals_raw)}
        repaired = repair_data(data, ValuationView)
        result = repaired["signals"]
        assert len(result) == len(amd_signals_raw)
        assert all(isinstance(item, dict) for item in result)

    def test_amd_top_signals_non_empty_after_fix(self, amd_company, amd_signals_raw):
        """End-to-end: rank_signals returns non-empty top_signals for AMD."""
        data = {
            "pe_assessment": "AMD at ~28x forward P/E",
            "overall": "AMD semiconductor transition to data-center",
            "confidence": 0.70,
            "signals": json.dumps(amd_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        val = ValuationView.model_validate(repaired)
        macro, risk, market, quality = _make_empty_agents()
        ranked = rank_signals(val, macro, risk, market, quality, company=amd_company)
        assert len(ranked.top_signals) > 0, (
            "AMD top_signals must be non-empty after fix. "
            f"Got {len(ranked.top_signals)} top_signals."
        )

    def test_amd_bearish_risk_signal_routed_to_top_risks(self, amd_company, amd_signals_raw):
        """AMD's bearish CUDA-moat signal routes to top_risks, not top_signals."""
        data = {
            "overall": "AMD test",
            "confidence": 0.70,
            "signals": json.dumps(amd_signals_raw),
        }
        repaired = repair_data(data, ValuationView)
        val = ValuationView.model_validate(repaired)
        macro, risk, market, quality = _make_empty_agents()
        ranked = rank_signals(val, macro, risk, market, quality, company=amd_company)
        risk_signals = [s for s in ranked.top_risks if "CUDA" in s.signal or "Nvidia" in s.signal]
        assert len(risk_signals) >= 1, (
            "AMD's Nvidia CUDA moat risk must appear in top_risks, not top_signals"
        )

    def test_amd_before_vs_after_signal_count(self, amd_company, amd_signals_raw):
        """Before fix: top_signals=0 for AMD. After fix: top_signals>0."""
        macro, risk, market, quality = _make_empty_agents()

        # BEFORE: empty signals
        val_before = ValuationView(overall="AMD valuation", confidence=0.70, signals=[])
        ranked_before = rank_signals(
            val_before, macro, risk, market, quality, company=amd_company
        )
        assert ranked_before.top_signals == []

        # AFTER: signals properly parsed
        data = {"overall": "AMD test", "confidence": 0.70, "signals": json.dumps(amd_signals_raw)}
        repaired = repair_data(data, ValuationView)
        val_after = ValuationView.model_validate(repaired)
        ranked_after = rank_signals(
            val_after, macro, risk, market, quality, company=amd_company
        )
        assert len(ranked_after.top_signals) > 0


# ── Multi-agent path ──────────────────────────────────────────────────────────

class TestMultiAgentSignalCollection:
    """Signals from multiple agents, each with stringified arrays, are all collected."""

    def test_signals_from_all_five_agents_collected(self, msft_company):
        """When all five agents return stringified signal arrays, rank_signals
        collects from all of them — signals are not dropped."""
        def _make_agent_data(signal_text: str, direction: str, signal_type: str, conf: float):
            return [{"signal": signal_text, "direction": direction,
                     "signal_type": signal_type, "impact_score": 0.75,
                     "time_horizon": "medium_term", "confidence": 0.70}]

        val_data = {
            "overall": "test valuation", "confidence": 0.70,
            "signals": json.dumps(_make_agent_data("Azure FCF expansion", "bullish", "structural", 0.70)),
        }
        macro_data = {
            "overall": "test macro", "confidence": 0.60,
            "signals": json.dumps(_make_agent_data("Rate compression on 32x P/E", "bearish", "macro", 0.60)),
        }
        risk_data = {
            "overall": "test risk", "confidence": 0.65, "key_risks": [],
            "signals": json.dumps(_make_agent_data("Regulatory antitrust exposure", "bearish", "risk", 0.65)),
        }
        market_data = {
            "overall": "test market", "confidence": 0.60,
            "signals": json.dumps(_make_agent_data("Consensus estimate revision up", "bullish", "catalyst", 0.60)),
        }
        quality_data = {
            "overall": "test quality", "confidence": 0.65,
            "signals": json.dumps(_make_agent_data("FCF yield above cost of capital", "bullish", "quality", 0.65)),
        }

        val = ValuationView.model_validate(repair_data(val_data, ValuationView))
        macro = MacroSensitivity.model_validate(repair_data(macro_data, MacroSensitivity))
        risk = RiskProfile.model_validate(repair_data(risk_data, RiskProfile))
        market = MarketContext.model_validate(repair_data(market_data, MarketContext))
        quality = QualityAssessment.model_validate(repair_data(quality_data, QualityAssessment))

        ranked = rank_signals(val, macro, risk, market, quality, company=msft_company)

        # Should have collected from all 5 agents (5 signals total, before dedup)
        total = (
            len(ranked.top_signals)
            + len(ranked.top_risks)
            + len(ranked.secondary_signals)
            + len(ranked.noise)
        )
        assert total == 5, (
            f"Expected 5 signals from 5 agents, got {total}. "
            "At least one agent's signals were dropped."
        )
        assert len(ranked.top_signals) > 0, "At least one bullish signal must reach top_signals"
        assert len(ranked.top_risks) > 0, "At least one risk signal must reach top_risks"


# ── Regression: top_signals on InvestmentThesis populated after fix ───────────

class TestInvestmentThesisTopSignals:
    """thesis.top_signals is non-empty when agents produce signals."""

    def test_thesis_top_signals_populated_from_agent_signals(self, msft_company):
        """synthesize_thesis integration: top_signals flows from agent → ranker → thesis."""
        from app.services.signal_ranker import rank_signals
        from app.schemas import InvestmentThesis

        bullish_sig = Signal(
            signal="Azure cloud 29% growth drives FCF expansion",
            direction="bullish",
            signal_type="structural",
            impact_score=0.88,
            confidence=0.78,
            time_horizon="medium_term",
        )
        val = ValuationView(overall="MSFT val", confidence=0.72, signals=[bullish_sig])
        macro, risk, market, quality = _make_empty_agents()

        ranked = rank_signals(val, macro, risk, market, quality, company=msft_company)
        assert len(ranked.top_signals) > 0

        # Build minimal thesis and attach ranked signals
        thesis = InvestmentThesis(
            ticker="MSFT",
            company_name="Microsoft Corporation",
            bull_thesis="Azure growth supports multiple.",
            bear_thesis="Rate pressure on 32x P/E.",
            confidence_score=0.68,
            key_drivers=["Azure growth"],
            key_risks=["Rate risk"],
        )
        thesis.top_signals = ranked.top_signals
        thesis.top_risks = ranked.top_risks
        thesis.secondary_signals = ranked.secondary_signals

        # Verify thesis carries non-empty top_signals
        assert len(thesis.top_signals) > 0, (
            "InvestmentThesis.top_signals must be non-empty when agent signals exist"
        )
        assert thesis.top_signals[0].direction == "bullish"

        # Verify model_dump() serialises them as a list of dicts (not raw JSON strings)
        payload = thesis.model_dump()
        top_sigs = payload["top_signals"]
        assert isinstance(top_sigs, list), f"Expected list, got {type(top_sigs)}"
        assert len(top_sigs) > 0
        for item in top_sigs:
            assert isinstance(item, dict), (
                f"Each serialised signal must be a dict, got {type(item)}: {item!r}"
            )
            assert "signal" in item
            assert not str(item["signal"]).startswith("["), (
                "Signal text must not be a raw JSON string"
            )
