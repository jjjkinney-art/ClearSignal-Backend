"""
Scenario Query Routing — Phase 20A · Priority 1.

Detects scenario-intent questions and routes them into the scenario-analysis
path, even when no explicit company ticker is mentioned.

Problem
-------
"What happens if AI CapEx falls 20%?" fails because:
  1. No company detected in the text
  2. Question falls through to general-finance, which cannot run scenarios

The scenario engine works fine — routing is the bottleneck.

Solution
--------
  1. Detect scenario intent patterns BEFORE company detection
  2. If a company is in active context → use it directly
  3. If no company → check theme mapping → surface affected companies

This module exports two functions:
  detect_scenario_intent  — returns True if the question is a scenario question
  extract_scenario_context — returns {is_scenario, theme, affected_tickers, ...}
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Scenario intent patterns
# ---------------------------------------------------------------------------

_SCENARIO_PATTERNS: Tuple[str, ...] = (
    # ── "what happens if" family ─────────────────────────────────────────────
    "what happens if",
    "what would happen if",
    "what would happen when",
    "what happens when",
    # ── "what if" family ─────────────────────────────────────────────────────
    "what if .+ fails",
    "what if .+ slows",
    "what if .+ declines",
    "what if .+ drops",
    "what if .+ falls",
    "what if .+ collapses",
    "what if .+ loses",
    "what if .+ rises",
    "what if .+ grows",
    "what if .+ doubles",
    "what if .+ halves",
    "what if .+ shrinks",
    "what if .+ stalls",
    "what if .+ accelerates",
    "what if .+ weakens",
    "what if .+ strengthens",
    "what if .+ deteriorates",
    "what if .+ improves?",
    "what if .+ reverses?",
    "what if .+ is delayed",
    "what if .+ is cancelled",
    "what if .+ is canceled",
    "what if .+ is cut",
    "what if .+ increases",
    "what if .+ decreases",
    # ── "if X metric-verb" family (conditional without "what") ───────────────
    "if .+ falls below",
    "if .+ rises above",
    "if .+ drops below",
    "if .+ drops to",
    "if .+ falls to",
    "if .+ rises to",
    "if .+ declines by",
    "if .+ declines to",
    "if .+ grows to",
    "if .+ slows to",
    "if .+ slows by",
    "if .+ increases to",
    "if .+ decreases to",
    "if .+ what happens",
    # ── "suppose / assume / imagine" family ──────────────────────────────────
    "suppose .+ falls",
    "suppose .+ drops",
    "suppose .+ rises",
    "suppose .+ slows",
    "suppose .+ declines",
    "suppose .+ grows",
    "suppose .+ collapses",
    "assume .+ falls",
    "assume .+ drops",
    "assume .+ rises",
    "assume .+ slows",
    "assume .+ declines?",
    "assume .+ grows",
    "assume .+ collapses?",
    "imagine .+ falls",
    "imagine .+ drops",
    "imagine .+ declines",
    "imagine .+ collapses",
    "under a scenario where",
    "in a scenario where",
    "in the scenario where",
    # ── thesis-break variants ────────────────────────────────────────────────
    "what breaks the thesis",
    "what invalidates the thesis",
    "what changes the thesis",
    "what could break the thesis",
    "what would break the thesis",
    "what could invalidate the thesis",
    "what would invalidate the thesis",
    "what would change the thesis",
    "what would increase conviction",
    "what would decrease conviction",
    "what would improve the thesis",
    "what would weaken the thesis",
    "what would strengthen the thesis",
    "what threatens the thesis",
    "what supports the thesis",
    "what confirms the thesis",
    "what disproves the thesis",
    # ── general disruption / risk patterns ───────────────────────────────────
    "what could derail",
    "what could impair",
    "what could disrupt",
    "what could break",
    "what would break",
    "what would change",
    "what would invalidate",
    "what would cause .+ to fail",
    "what would cause .+ to decline",
    "what would cause .+ to drop",
    "what would need to happen for",
    "what needs to go wrong",
    "what needs to go right",
    "what is the biggest risk",
    "what is the main risk",
    "what is the key risk",
    "what are the risks",
    "worst case scenario",
    "downside scenario",
    "upside scenario",
    "bear case for",
    "bull case for",
    "base case for",
    "stress test",
    "stress scenario",
    # ── "how exposed" / sensitivity patterns ─────────────────────────────────
    "how exposed .+ to",
    "how sensitive .+ to",
    "how vulnerable .+ to",
    "how dependent .+ on",
)

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _SCENARIO_PATTERNS]


def detect_scenario_intent(question: str) -> bool:
    """Return True if the question has scenario-analysis intent.

    Checked BEFORE company detection so that scenario questions without
    explicit tickers are not lost to the general-finance path.
    """
    q = question.strip()
    if not q:
        return False
    return any(p.search(q) for p in _COMPILED_PATTERNS)


# ---------------------------------------------------------------------------
# Theme exposure mapping (Priority 2 integration point)
# ---------------------------------------------------------------------------

_THEME_MAPPINGS: Dict[str, List[str]] = {
    "ai capex":                ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MSFT", "AMZN", "GOOGL"],
    "ai spending":             ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MSFT", "AMZN", "GOOGL"],
    "ai infrastructure":       ["NVDA", "AMD", "AVGO", "TSM", "ASML", "MSFT", "AMZN", "GOOGL"],
    "cloud spending":          ["MSFT", "AMZN", "GOOGL"],
    "cloud growth":            ["MSFT", "AMZN", "GOOGL"],
    "azure":                   ["MSFT"],
    "aws":                     ["AMZN"],
    "gcp":                     ["GOOGL"],
    "cross-border payments":   ["V", "MA"],
    "cross border payments":   ["V", "MA"],
    "payment volume":          ["V", "MA"],
    "credit losses":           ["JPM", "BAC", "C"],
    "credit quality":          ["JPM", "BAC", "C"],
    "loan losses":             ["JPM", "BAC", "C"],
    "glp-1":                   ["LLY", "NVO"],
    "glp1":                    ["LLY", "NVO"],
    "obesity drug":            ["LLY", "NVO"],
    "weight loss drug":        ["LLY", "NVO"],
    "semiconductor equipment": ["ASML", "AMAT", "LRCX"],
    "euv":                     ["ASML"],
    "euv shipment":            ["ASML"],
    "lithography":             ["ASML"],
    "interest rate":           ["JPM", "BAC", "C", "SCHW"],
    "rate hike":               ["JPM", "BAC", "C", "SCHW"],
    "rate cut":                ["JPM", "BAC", "C", "SCHW"],
    "consumer spending":       ["COST", "WMT", "TGT"],
    "retail spending":         ["COST", "WMT", "TGT"],
    "data center":             ["NVDA", "AMD", "AVGO", "MSFT", "AMZN"],
    "data center demand":      ["NVDA", "AMD", "AVGO", "MSFT", "AMZN"],
    "chip demand":             ["NVDA", "AMD", "AVGO", "TSM", "INTC"],
    "gpu demand":              ["NVDA", "AMD"],
    "credit rating":           ["MCO", "SPGI"],
    "ratings revenue":         ["MCO", "SPGI"],
    "index revenue":           ["SPGI", "MSCI"],
    # ── data analytics / information services ────────────────────────────────
    "data analytics":          ["SPGI", "MSCI", "VRSK", "FDS"],
    "financial data":          ["SPGI", "MSCI", "FDS", "ICE"],
    "market data":             ["SPGI", "MSCI", "ICE", "CME"],
    # ── insurance ────────────────────────────────────────────────────────────
    "insurance premium":       ["PGR", "ALL", "CB", "TRV"],
    "insurance losses":        ["PGR", "ALL", "CB", "TRV"],
    "catastrophe losses":      ["PGR", "ALL", "CB", "TRV"],
    "underwriting":            ["PGR", "ALL", "CB", "TRV"],
    # ── asset management ─────────────────────────────────────────────────────
    "asset management":        ["BLK", "BX", "KKR", "APO"],
    "aum":                     ["BLK", "BX", "KKR", "APO"],
    "fund flows":              ["BLK", "TROW", "IVZ"],
    "alternative assets":      ["BX", "KKR", "APO", "ARES"],
    "private equity":          ["BX", "KKR", "APO"],
    "private credit":          ["BX", "KKR", "APO", "ARES"],
    # ── travel / leisure ─────────────────────────────────────────────────────
    "travel demand":           ["BKNG", "ABNB", "MAR", "HLT"],
    "hotel occupancy":         ["MAR", "HLT", "H"],
    "airline demand":          ["DAL", "UAL", "LUV"],
    "travel spending":         ["BKNG", "ABNB", "MAR", "HLT", "V", "MA"],
    # ── consumer staples ─────────────────────────────────────────────────────
    "consumer staples demand":  ["PG", "KO", "PEP", "CL"],
    "commodity cost":          ["PG", "KO", "PEP", "CL"],
    "input cost":              ["PG", "KO", "PEP", "CL", "COST"],
    "grocery spending":        ["COST", "WMT", "KR"],
    # ── defense / aerospace ──────────────────────────────────────────────────
    "defense spending":        ["LMT", "RTX", "NOC", "GD"],
    "defense budget":          ["LMT", "RTX", "NOC", "GD"],
    "military spending":       ["LMT", "RTX", "NOC", "GD"],
    # ── industrial automation / robotics ──────────────────────────────────────
    "factory automation":      ["ROK", "EMR", "ABB", "HON"],
    "industrial automation":   ["ROK", "EMR", "ABB", "HON"],
    "robotics":                ["ISRG", "ROK", "ABB"],
    # ── payments (expanded) ──────────────────────────────────────────────────
    "digital payments":        ["V", "MA", "PYPL", "SQ"],
    "payment processing":      ["V", "MA", "FIS", "GPN"],
    "fintech":                 ["PYPL", "SQ", "SOFI", "AFRM"],
    "bnpl":                    ["AFRM", "PYPL", "SQ"],
    "buy now pay later":       ["AFRM", "PYPL", "SQ"],
    # ── obesity / weight loss (expanded) ─────────────────────────────────────
    "glp-1 competition":       ["LLY", "NVO", "AMGN", "VKTX"],
    "weight loss competition": ["LLY", "NVO", "AMGN", "VKTX"],
    "ozempic":                 ["NVO"],
    "mounjaro":                ["LLY"],
    "wegovy":                  ["NVO"],
    "zepbound":                ["LLY"],
    # ── cybersecurity ────────────────────────────────────────────────────────
    "cybersecurity spending":  ["CRWD", "PANW", "FTNT", "ZS"],
    "cybersecurity":           ["CRWD", "PANW", "FTNT", "ZS"],
    "cyber threat":            ["CRWD", "PANW", "FTNT", "ZS"],
    "ransomware":              ["CRWD", "PANW", "FTNT", "ZS"],
    # ── energy ───────────────────────────────────────────────────────────────
    "oil price":               ["XOM", "CVX", "COP", "OXY"],
    "oil demand":              ["XOM", "CVX", "COP"],
    "natural gas":             ["LNG", "EQT", "XOM"],
    "energy transition":       ["NEE", "ENPH", "FSLR"],
    "renewable energy":        ["NEE", "ENPH", "FSLR"],
    # ── ev / battery ─────────────────────────────────────────────────────────
    "ev demand":               ["TSLA", "GM", "F", "RIVN"],
    "ev sales":                ["TSLA", "GM", "F", "RIVN"],
    "battery cost":            ["TSLA", "ALB", "SQM"],
    "lithium price":           ["ALB", "SQM", "LTHM"],
    # ── advertising / media ──────────────────────────────────────────────────
    "ad spending":             ["GOOGL", "META", "TTD", "DIS"],
    "digital advertising":     ["GOOGL", "META", "TTD", "SNAP"],
    "streaming":               ["NFLX", "DIS", "WBD", "PARA"],
    "streaming subscriber":    ["NFLX", "DIS", "WBD"],
}


def _detect_theme(question: str) -> Optional[str]:
    """Return the best-matching theme key, or None."""
    q = question.lower()
    best_match: Optional[str] = None
    best_len = 0
    for theme in _THEME_MAPPINGS:
        if theme in q and len(theme) > best_len:
            best_match = theme
            best_len = len(theme)
    return best_match


def _affected_tickers_for_theme(theme: str) -> List[str]:
    """Return the tickers affected by a theme."""
    return list(_THEME_MAPPINGS.get(theme, []))


# ---------------------------------------------------------------------------
# Full scenario context extraction
# ---------------------------------------------------------------------------

def extract_scenario_context(
    question: str,
    *,
    active_ticker: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract full scenario routing context from a question.

    Returns:
      is_scenario        — True if scenario intent detected
      theme              — matched theme key, or None
      affected_tickers   — list of tickers affected by the theme
      active_ticker      — the ticker to use (from active context or theme)
      needs_disambiguation — True when multiple tickers and no active context
      scenario_question  — the original question (for downstream)
    """
    is_scenario = detect_scenario_intent(question)
    theme = _detect_theme(question)
    affected = _affected_tickers_for_theme(theme) if theme else []

    if active_ticker:
        target = active_ticker
        needs_disambiguation = False
    elif len(affected) == 1:
        target = affected[0]
        needs_disambiguation = False
    elif len(affected) > 1:
        target = affected[0]
        needs_disambiguation = True
    else:
        target = None
        needs_disambiguation = False

    return {
        "is_scenario":            is_scenario,
        "theme":                  theme,
        "affected_tickers":       affected,
        "active_ticker":          target,
        "needs_disambiguation":   needs_disambiguation,
        "scenario_question":      question,
    }
