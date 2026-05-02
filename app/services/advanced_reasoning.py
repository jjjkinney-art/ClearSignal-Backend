"""
Advanced reasoning utilities for scenario analysis and causal chains.

This module provides helper functions to derive richer analytical
insights from a ``SynthesisOutput``.  Scenario analysis generates
base, upside and downside narratives using existing drivers, risks
and bull/bear cases.  Causal chains illustrate how drivers and
macro factors cascade into thesis outcomes.  These functions are
heuristic and deterministic, suitable for use in monitoring and
alerting services without external dependencies.
"""

from __future__ import annotations

from typing import Dict, List

from ..schemas import SynthesisOutput


def generate_scenario_analysis(synth: SynthesisOutput) -> Dict[str, List[str]]:
    """Construct simple scenario narratives from a synthesis output.

    The base case highlights the primary driver and risk.  The upside
    case emphasises the best bull case and reduces the impact of
    risks.  The downside case focuses on the worst bear case and the
    most significant risk.  Macro overlay factors are included in
    each narrative when present.

    Parameters
    ----------
    synth : SynthesisOutput
        Structured synthesis from which to derive scenarios.

    Returns
    -------
    Dict[str, List[str]]
        A dictionary with keys ``base_case``, ``upside_case`` and
        ``downside_case``, each mapping to a list of narrative
        sentences.
    """
    base: List[str] = []
    upside: List[str] = []
    downside: List[str] = []
    # Base case uses first driver and first risk if available
    if synth.key_drivers_ranked:
        base.append(f"Core driver: {synth.key_drivers_ranked[0]}")
        upside.append(f"Upside driver: {synth.key_drivers_ranked[0]}")
        downside.append(f"Key driver remains {synth.key_drivers_ranked[0]}")
    if synth.key_risks_ranked:
        base.append(f"Primary risk: {synth.key_risks_ranked[0]}")
        downside.append(f"Downside risk: {synth.key_risks_ranked[0]}")
    # Use bull/bear cases for upside/downside narratives
    if synth.bull_case:
        upside.append(f"Bull case: {synth.bull_case[0]}")
    if synth.bear_case:
        downside.append(f"Bear case: {synth.bear_case[0]}")
    # Incorporate macro overlay for context
    if synth.macro_overlay:
        macro = synth.macro_overlay[0]
        base.append(f"Macro factor: {macro}")
        upside.append(f"Macro tailwind: {macro}")
        downside.append(f"Macro headwind: {macro}")
    # Guarantee non‑empty narratives
    if not base:
        base.append("No significant factors identified for base case.")
    if not upside:
        upside.append("No significant factors identified for upside case.")
    if not downside:
        downside.append("No significant factors identified for downside case.")
    return {
        "base_case": base,
        "upside_case": upside,
        "downside_case": downside,
    }


def generate_causal_chains(synth: SynthesisOutput) -> List[str]:
    """Generate simple causal chains linking drivers to thesis outcomes.

    Each chain takes the form ``driver → macro_effect → verdict``.
    If no macro overlay is available, the macro_effect component is
    omitted.  Chains are created for the top drivers and truncated
    to the top three to avoid excessive length.

    Parameters
    ----------
    synth : SynthesisOutput
        Structured synthesis from which to derive causal chains.

    Returns
    -------
    List[str]
        A list of causal chain strings.
    """
    chains: List[str] = []
    drivers = synth.key_drivers_ranked[:3] if synth.key_drivers_ranked else []
    macro = synth.macro_overlay[0] if synth.macro_overlay else None
    verdict = synth.final_verdict
    for drv in drivers:
        if macro:
            chains.append(f"{drv} → {macro} → {verdict}")
        else:
            chains.append(f"{drv} → {verdict}")
    return chains