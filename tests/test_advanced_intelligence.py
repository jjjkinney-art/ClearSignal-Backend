"""
Advanced intelligence tests for the AI analyst backend.

These tests focus on the institutional‑grade intelligence upgrades
including advanced signal scoring, adaptation loops, scenario
analysis, event categorisation and caching.  They ensure that
signals are scored with appropriate metadata, that repeated
signals influence ranking via the learning memory, that scenario
generation produces coherent narratives, that events are
categorised correctly, and that the evidence layer caches provider
results.
"""

import os
import sys
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import SynthesisOutput, GroundingContext
from app.services.signal_scoring import score_signals
from app.services.prioritization_utils import rank_signals
from app.services.thesis_change_logic import detect_thesis_change
from app.services.learning import get_signal_weight
from app.services.advanced_reasoning import generate_scenario_analysis
from app.services.event_categorization import categorize_events
from app.services.evidence_service import build_evidence
import app.services.evidence_service as esvc


def test_score_signals_structure() -> None:
    """score_signals should return structured metadata for each signal."""
    items = [
        "Regulatory risk from new emissions standards",
        "Growth opportunity in EV market",
        "Macro uncertainty due to inflation",
    ]
    scored = score_signals(items)
    # Should return a list of dicts matching the number of items
    assert isinstance(scored, list)
    assert len(scored) == len(items)
    for entry in scored:
        assert set(entry.keys()) == {
            "signal",
            "importance_score",
            "impact_type",
            "time_horizon",
            "confidence_score",
            "weighted_score",
        }
        assert 0.0 <= entry["confidence_score"] <= 1.0
        assert 0.0 <= entry["importance_score"] <= 100.0


def test_learning_adaptation_affects_ranking() -> None:
    """Signals that trigger thesis changes should gain weight and rank higher."""
    # Create two syntheses with a changed driver
    prev = SynthesisOutput(key_drivers_ranked=["stable revenues"], final_verdict="hold")
    curr = SynthesisOutput(key_drivers_ranked=["litigation risk"], final_verdict="hold")
    # Detect change twice to simulate repeated influence
    for _ in range(2):
        _ = detect_thesis_change(prev, curr)
    # Now rank two signals: one that triggered the change and one that did not
    items = ["litigation risk", "growth opportunity in EV market"]
    ranked = rank_signals(items, top_n=2)
    # Expect the repeatedly impactful signal to appear first due to higher weight
    assert ranked[0].lower().startswith("litigation risk")
    # Its weight multiplier should be > 1.0
    assert get_signal_weight("litigation risk") > 1.0


def test_generate_scenario_analysis_output() -> None:
    """generate_scenario_analysis should produce base, upside and downside narratives."""
    synth = SynthesisOutput(
        key_drivers_ranked=["expanding margins"],
        key_risks_ranked=["competitive pressure"],
        bull_case=["new product success"],
        bear_case=["supply chain disruptions"],
        macro_overlay=["rising interest rates"],
        final_verdict="buy",
    )
    scenarios = generate_scenario_analysis(synth)
    assert set(scenarios.keys()) == {"base_case", "upside_case", "downside_case"}
    for case in scenarios.values():
        assert isinstance(case, list) and case


def test_event_categorization() -> None:
    """categorize_events should label events based on keywords."""
    events = [
        "Company announces Q1 earnings release",
        "New regulation on emissions standards",
        "Inflation hits record high",
        "Product launch event",
        "Random corporate update",
    ]
    categories = categorize_events(events)
    assert categories == ["earnings", "regulatory", "macro", "product", "other"]


def test_evidence_caching(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_evidence should cache provider results and avoid redundant calls."""
    # Counters to verify call counts
    counts: Dict[str, int] = {
        "profile": 0,
        "snapshot": 0,
        "financial": 0,
    }
    # Stub provider functions to increment counters
    def fake_profile(symbol: str, api_key: str = "") -> Dict[str, Any]:
        counts["profile"] += 1
        return {"name": "Foo Inc"}

    def fake_snapshot(symbol: str, api_key: str = "") -> Dict[str, Any]:
        counts["snapshot"] += 1
        return {"price": 100.0}

    def fake_financial(symbol: str, api_key: str = "") -> Dict[str, Any]:
        counts["financial"] += 1
        return {"revenue": 1000.0}

    # Patch both provider modules and aliases in evidence_service.
    # Also bypass governance so providers are called even without a real API key.
    monkeypatch.setattr(esvc, "get_company_profile", fake_profile)
    monkeypatch.setattr(esvc, "get_market_snapshot", fake_snapshot)
    monkeypatch.setattr(esvc, "get_financial_context", fake_financial)
    monkeypatch.setattr(esvc, "_check_provider_access", lambda *a, **kw: True)

    # Clear any existing cache by reloading the module (if necessary)
    # Not possible to reload easily in this environment; rely on global cache starting fresh.
    ctx = GroundingContext(company="Foo")
    # First call should invoke providers once each
    _ = build_evidence("Foo", None, None, ["fmp"], ctx)
    assert counts["profile"] == 1
    assert counts["snapshot"] == 1
    assert counts["financial"] == 1
    # Second call with same symbol should not increment counters due to caching
    ctx2 = GroundingContext(company="Foo")
    _ = build_evidence("Foo", None, None, ["fmp"], ctx2)
    assert counts["profile"] == 1
    assert counts["snapshot"] == 1
    assert counts["financial"] == 1