"""
Intelligence layer tests for the AI analyst backend.

This module exercises the new thesis change detection, alert generation,
signal prioritization, and personalization hooks.  The tests use
structured ``SynthesisOutput`` instances to ensure comparisons operate
on semantic components rather than raw strings.  The goal is to
validate that meaningful changes are detected, alerts are
appropriately prioritised and personalised, and signals are ranked
deterministically.
"""

import os
import sys
from typing import List

import pytest

# Add project root to import path so ``import app`` resolves correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas import SynthesisOutput, ThesisChangeResult
from app.services.thesis_change_logic import detect_thesis_change
from app.services.alert_service import generate_alerts
from app.services.prioritization_utils import rank_signals


def _make_synth(**kwargs) -> SynthesisOutput:
    """Helper to build a SynthesisOutput with sensible defaults for tests."""
    defaults = {
        "business_overview": [],
        "bull_case": [],
        "bear_case": [],
        "key_risks": [],
        "key_catalysts": [],
        "macro_overlay": [],
        "opportunity_summary": [],
        "research_summary": [],
        "education_summary": [],
        "accounting_summary": [],
        "key_drivers_ranked": [],
        "key_risks_ranked": [],
        "what_to_monitor": [],
        "what_changes_the_thesis": [],
        "final_verdict": "neutral",
        "verdict_reasoning": "",
        "confidence_score": 0.5,
        "confidence_reasoning": "",
        "thesis_fragility": "",
        "assumptions": [],
        "uncertainties": [],
    }
    defaults.update(kwargs)
    return SynthesisOutput(**defaults)


def test_thesis_change_severity() -> None:
    """Detect significant vs minor changes and assign correct severity."""
    # Previous synthesis with baseline signals
    prev = _make_synth(
        final_verdict="hold",
        key_drivers_ranked=["growing revenue", "expanding margins"],
        key_risks_ranked=["regulatory scrutiny"],
        macro_overlay=["stable interest rates"],
        bull_case=["strong demand"],
        bear_case=["competitive pressure"],
    )
    # Current synthesis with material changes: verdict flips, new driver and risk
    curr_major = _make_synth(
        final_verdict="buy",
        key_drivers_ranked=["growing revenue", "new product launch"],
        key_risks_ranked=["regulatory scrutiny", "increasing debt"],
        macro_overlay=["rising interest rates"],
        bull_case=["strong demand"],
        bear_case=["competitive pressure"],
    )
    result_major = detect_thesis_change(prev, curr_major)
    # Major change should be detected with high or medium severity depending on default threshold
    assert result_major.has_changed is True
    assert result_major.change_severity in ("medium", "high")
    assert "final_verdict" in result_major.changed_components
    assert "key_drivers" in result_major.changed_components
    assert "key_risks" in result_major.changed_components
    assert result_major.change_summary
    # Minor change: only a new catalyst added; should yield low severity or no change
    curr_minor = _make_synth(
        final_verdict="hold",
        key_drivers_ranked=prev.key_drivers_ranked,
        key_risks_ranked=prev.key_risks_ranked,
        macro_overlay=prev.macro_overlay,
        bull_case=prev.bull_case,
        bear_case=prev.bear_case,
        key_catalysts=["new marketing campaign"],
    )
    result_minor = detect_thesis_change(prev, curr_minor, sensitivity="high")
    # High sensitivity suppresses minor changes; has_changed may be False or severity low
    assert result_minor.change_severity in ("low", "medium")
    # Impact should indicate minimal effect
    assert "minor" in result_minor.impact_on_thesis.lower() or "no impact" in result_minor.impact_on_thesis.lower()


def test_alert_generation_personalization() -> None:
    """Alerts should reflect changed components, severity, and user preferences."""
    # Create a change result indicating updates to key risks and macro
    changes = ThesisChangeResult(
        has_changed=True,
        change_severity="medium",
        change_summary="key risks added: litigation; macro overlay added: inflation",
        changed_components=["key_risks", "macro_overlay"],
        impact_on_thesis="Moderate impact on thesis.",
    )
    current = _make_synth()
    # Generate alerts with user focus on risk and preference for risk alerts only
    alerts = generate_alerts(
        changes,
        current,
        user_focus="risk",
        preferred_alert_types=["Risk Update"],
        sensitivity="low",
    )
    # Only one alert of type "Risk Update" should be generated
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == "Risk Update"
    # Severity should be elevated due to user focus (risk)
    assert alert.severity in ("medium", "high")
    # Reason and impact explanation should be non‑empty
    assert alert.reason
    assert alert.impact_explanation


def test_rank_signals_and_personalization() -> None:
    """Signals should be ranked by importance and boosted by user focus."""
    # Import freshly inside the function so we get the real module rather
    # than the stub that test_enterprise_integration.py installs at collection time.
    from app.services.prioritization_utils import rank_signals as _rank_signals
    items = [
        "Macro uncertainty due to inflation",
        "Growth opportunity in EV market",
        "Regulatory risk from new emissions standards",
        "Rising debt levels",
    ]
    # With macro focus, the macro item should rank higher than growth
    ranked_macro = _rank_signals(items, top_n=4, focus="macro")
    # Identify positions of macro and growth items
    macro_pos = next(i for i, it in enumerate(ranked_macro) if it.lower().startswith("macro"))
    growth_pos = next(i for i, it in enumerate(ranked_macro) if it.lower().startswith("growth"))
    assert macro_pos < growth_pos
    # Without focus, regulatory risk should outrank others due to higher weight
    ranked_default = _rank_signals(items, top_n=4)
    assert ranked_default[0].lower().startswith("regulatory")
    # Top 3 items should be returned when top_n is smaller than list length
    top3 = _rank_signals(items, top_n=3)
    assert len(top3) == 3


def test_noise_filtering_vs_meaningful_change() -> None:
    """High sensitivity should filter out negligible changes."""
    prev = _make_synth(key_drivers_ranked=["stable revenues"], key_risks_ranked=["competition"], final_verdict="hold")
    # Only reordering of drivers (semantic same) should not trigger high severity
    curr = _make_synth(key_drivers_ranked=["stable revenues"], key_risks_ranked=["competition"], final_verdict="hold")
    result = detect_thesis_change(prev, curr, sensitivity="high")
    assert result.has_changed is False or result.change_severity == "low"


def test_personalization_effects_in_alerts() -> None:
    """User focus should influence alert severity appropriately."""
    changes = ThesisChangeResult(
        has_changed=True,
        change_severity="low",
        change_summary="macro overlay added: inflation",
        changed_components=["macro_overlay"],
        impact_on_thesis="Minor impact.",
    )
    current = _make_synth()
    # Macro focus should elevate macro alert severity
    alerts_macro = generate_alerts(changes, current, user_focus="macro", sensitivity="low")
    assert alerts_macro
    assert alerts_macro[0].alert_type == "Macro Shift"
    sev_macro = alerts_macro[0].severity
    # Without macro focus, severity should be lower or equal
    alerts_default = generate_alerts(changes, current, user_focus=None, sensitivity="low")
    sev_default = alerts_default[0].severity if alerts_default else "low"
    # Macro focus should not downgrade severity
    order = {"low": 1, "medium": 2, "high": 3}
    assert order[sev_macro] >= order[sev_default]