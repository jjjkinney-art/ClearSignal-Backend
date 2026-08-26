"""
Morning brief service — PM-style market intelligence summary.

Phase M: generate_morning_brief_v2() produces the 5-section command center
format (regime / what changed / debate shifts / priority alerts / watchlist drift).

All logic deterministic — no LLM calls.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from ..schemas import Alert, EventImpactAssessment, MaterialChangeEvent, MorningBriefV2, WatchlistDriftSummary, WatchlistEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output model (defined here to avoid schemas.py import complexity)
# ---------------------------------------------------------------------------


class MorningBrief(BaseModel):
    """PM-style morning brief summary."""

    generated_at: str           # ISO-8601
    reference_date: str         # The "morning" date
    brief_text: str             # The PM-style narrative (3-8 sentences)
    top_movers: List[str]       # Tickers with most significant changes
    attention_required: List[str]  # Tickers requiring PM decision
    debate_shifts: List[str]    # Tickers where core debate shifted
    market_regime_note: str     # 1-sentence macro context
    ticker_count: int           # How many watchlist names processed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANK: Dict[str, int] = {
    "critical": 4,
    "high":     3,
    "medium":   2,
    "low":      1,
    "":         0,
}

_CATEGORY_RANK: Dict[str, int] = {
    "thesis_broke":        5,
    "new_risk_emerged":    4,
    "market_repriced":     3,
    "thesis_strengthened": 2,
    "cosmetic":            1,
    "":                    0,
}

_TREND_RANK: Dict[str, int] = {
    "weakening":     4,
    "inflecting":    3,
    "strengthening": 2,
    "stable":        1,
    "unclear":       0,
}

_DRIFT_RANK: Dict[str, int] = {
    "breaking":     5,
    "shifting":     4,
    "repricing":    3,
    "transition":   3,
    "bifurcating":  3,
    "drifting":     2,
    "weakening":    2,
    "strengthening": 1,
    "unchanged":    1,
    "stable":       1,
    "unclear":      0,
    "":             0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str(reference_date: Optional[str]) -> str:
    if reference_date:
        return reference_date
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _format_material_change_shift(event: MaterialChangeEvent) -> str:
    """Return one complete, singly-prefixed material-change sentence."""
    ticker = (event.ticker or "").strip()
    summary = (event.summary or "").strip()
    prefix = f"{ticker}:"

    # Durable headlines may already include their ticker. Remove any repeated
    # leading prefixes before adding the canonical one below.
    while ticker and summary.casefold().startswith(prefix.casefold()):
        summary = summary[len(prefix):].lstrip()

    if not summary:
        return ticker
    return f"{prefix} {summary}"


def _entry_priority_score(
    entry: WatchlistEntry,
    change_map: Dict[str, MaterialChangeEvent],
) -> float:
    """Compute a priority score for a watchlist entry for ordering."""
    score = 0.0

    change = change_map.get(entry.ticker)
    if change:
        score += _CATEGORY_RANK.get(change.change_category, 0) * 20.0
        score += change.materiality_score * 10.0
        score += _SEVERITY_RANK.get(change.severity, 0) * 5.0

    score += _TREND_RANK.get(entry.latest_thesis_trend or "unclear", 0) * 3.0
    score += _DRIFT_RANK.get(entry.drift_state or "", 0) * 2.0
    if entry.has_material_change:
        score += 15.0

    return score


def _build_ticker_sentence(
    ticker: str,
    change: Optional[MaterialChangeEvent],
    entry: Optional[WatchlistEntry],
) -> str:
    """Build one PM-style sentence for a single ticker."""
    display = ticker

    if change is None and entry is None:
        return f"{display}: monitoring, no material change detected."

    # Choose the best summary available
    summary = ""
    if change and change.summary:
        summary = change.summary.strip().rstrip(".")
    elif entry and entry.what_changed_summary:
        summary = entry.what_changed_summary.strip().rstrip(".")
    elif entry and entry.latest_one_sentence:
        summary = entry.latest_one_sentence.strip().rstrip(".")

    if not summary:
        return f"{display}: flagged for review."

    category = change.change_category if change else ""
    trend    = entry.latest_thesis_trend if entry else ""
    drift    = entry.drift_state if entry else ""

    if category == "thesis_broke":
        return f"{display}: thesis broke — {summary}."
    elif category == "new_risk_emerged":
        return f"{display}: new structural risk — {summary}."
    elif category == "market_repriced":
        return f"{display}: market repriced, thesis intact — {summary}."
    elif category == "thesis_strengthened":
        return f"{display}: setup improved — {summary}."
    elif trend == "weakening" or drift in ("breaking", "shifting"):
        return f"{display}: conviction weakening — {summary}."
    elif trend == "strengthening":
        return f"{display}: setup improving — {summary}."
    else:
        return f"{display}: {summary}."


def _group_by_driver(
    ranked: List[Tuple[str, Optional[MaterialChangeEvent], Optional[WatchlistEntry]]],
    max_groups: int = 3,
) -> List[str]:
    """Attempt to group tickers sharing the same macro driver into combined sentences."""
    # Build driver → ticker list mapping
    driver_buckets: Dict[str, List[str]] = {}
    ungrouped: List[Tuple[str, Optional[MaterialChangeEvent], Optional[WatchlistEntry]]] = []

    for ticker, change, entry in ranked:
        if change and change.drivers:
            primary_driver = change.drivers[0].lower().strip()
            if primary_driver:
                driver_buckets.setdefault(primary_driver, []).append(ticker)
                continue
        ungrouped.append((ticker, change, entry))

    sentences: List[str] = []
    ticker_lookup = {ticker: (change, entry) for ticker, change, entry in ranked}

    grouped_tickers: set[str] = set()
    for driver, tickers in driver_buckets.items():
        if len(tickers) >= 2 and len(sentences) < max_groups:
            names = " and ".join(tickers) if len(tickers) == 2 else ", ".join(tickers[:-1]) + f", and {tickers[-1]}"
            # Use the highest-severity change for the sentence
            best_change = None
            for t in tickers:
                ch, _ = ticker_lookup.get(t, (None, None))
                if ch and (best_change is None or ch.materiality_score > best_change.materiality_score):
                    best_change = ch
            summary_str = best_change.summary.rstrip(".") if best_change and best_change.summary else driver
            sentences.append(f"{names} moved on shared driver — {summary_str}.")
            grouped_tickers.update(tickers)
        else:
            for t in tickers:
                if t not in grouped_tickers:
                    ungrouped.append((t, ticker_lookup[t][0], ticker_lookup[t][1]))

    # Add ungrouped in order
    for ticker, change, entry in ranked:
        if ticker not in grouped_tickers:
            sentences.append(_build_ticker_sentence(ticker, change, entry))

    return sentences


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_overnight_summary(
    event_impacts: List,
    regime: Optional[object] = None,
) -> str:
    """
    Generate the 'what changed overnight' section from event impacts.
    Returns 1-3 sentences in PM language.

    Parameters
    ----------
    event_impacts:
        List of EventImpactAssessment objects.
    regime:
        Optional MarketRegime object for macro context.
    """
    try:
        if not event_impacts:
            if regime is not None:
                narrative = getattr(regime, "dominant_narrative", "")
                if narrative:
                    return narrative
            return "No material overnight developments for tracked names."

        sentences: List[str] = []

        # Add regime narrative first if risk-off or higher-for-longer
        if regime is not None:
            rate_env = getattr(regime, "rate_environment", "")
            risk_app = getattr(regime, "risk_appetite", "")
            dominant_narrative = getattr(regime, "dominant_narrative", "")
            if dominant_narrative and (
                rate_env in ("higher_for_longer", "cutting_cycle")
                or risk_app == "risk_off"
            ):
                sentences.append(dominant_narrative)

        # Group by ticker, pick highest-priority impact per ticker
        ticker_impacts: dict = {}
        for impact in event_impacts:
            ticker = getattr(impact, "ticker", "")
            existing = ticker_impacts.get(ticker)
            if existing is None:
                ticker_impacts[ticker] = impact
            else:
                # Keep higher materiality
                if getattr(impact, "materiality_score", 0.0) > getattr(existing, "materiality_score", 0.0):
                    ticker_impacts[ticker] = impact

        for ticker, impact in ticker_impacts.items():
            priority = getattr(impact, "alert_priority", "ignore")
            implication = getattr(impact, "thesis_implication", "")
            if priority == "critical" and implication:
                sentences.append(f"{ticker}: {implication}")
            elif priority in ("high",) and implication:
                sentences.append(f"{ticker}'s setup changed — {implication}")

        # Cap at 3 sentences
        sentences = sentences[:3]

        if not sentences:
            return "No material overnight developments for tracked names."

        return " ".join(sentences)
    except Exception as exc:
        logger.warning("generate_overnight_summary failed: %s", exc)
        return "No material overnight developments for tracked names."


def generate_morning_brief(
    watchlist_entries: List[WatchlistEntry],
    recent_material_changes: List[MaterialChangeEvent],
    recent_alerts: List[Alert],
    reference_date: Optional[str] = None,
    event_impacts: Optional[List] = None,
) -> MorningBrief:
    """Generate a PM-style morning brief from watchlist state.

    Parameters
    ----------
    watchlist_entries:
        All current watchlist entries.
    recent_material_changes:
        MaterialChangeEvents from the last 24 hours.
    recent_alerts:
        Alert objects from the last 24 hours.
    reference_date:
        The date string for the brief header (ISO YYYY-MM-DD).
        Defaults to today UTC.

    Returns
    -------
    MorningBrief
        Structured morning note with brief_text, top_movers,
        attention_required, debate_shifts, and market_regime_note.

    .. deprecated::
        Use :func:`generate_morning_brief_v2` instead.  This function will be
        removed in a future release.  The canonical implementation is v2.
    """
    warnings.warn(
        "generate_morning_brief is deprecated; use generate_morning_brief_v2 instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # ── Pre-build event impact sentences for injection ────────────────────────
    _impact_sentences: List[str] = []
    if event_impacts:
        for impact in event_impacts:
            priority = getattr(impact, "alert_priority", "ignore")
            implication = getattr(impact, "thesis_implication", "")
            ticker = getattr(impact, "ticker", "")
            if priority == "critical" and implication and ticker:
                _impact_sentences.append(f"{ticker}: {implication}")
            elif priority == "high" and implication and ticker:
                _impact_sentences.append(f"{ticker}'s setup changed — {implication}")

    generated_at   = _now_iso()
    ref_date       = _today_str(reference_date)
    ticker_count   = len(watchlist_entries) if watchlist_entries else 0

    # ── Degenerate case: empty watchlist ────────────────────────────────────
    if not watchlist_entries:
        return MorningBrief(
            generated_at=generated_at,
            reference_date=ref_date,
            brief_text="No names currently monitored. Add tickers to the watchlist to generate a morning brief.",
            top_movers=[],
            attention_required=[],
            debate_shifts=[],
            market_regime_note="No watchlist data available.",
            ticker_count=0,
        )

    # ── Build change index: ticker → most recent/severe MaterialChangeEvent ─
    change_map: Dict[str, MaterialChangeEvent] = {}
    for ev in (recent_material_changes or []):
        t = ev.ticker.upper()
        existing = change_map.get(t)
        if existing is None or ev.materiality_score > existing.materiality_score:
            change_map[t] = ev

    # ── Build entry index ───────────────────────────────────────────────────
    entry_map: Dict[str, WatchlistEntry] = {}
    for entry in watchlist_entries:
        entry_map[entry.ticker.upper()] = entry

    # ── Compute debate shifts (from entries with core_debate change context)
    debate_shifts: List[str] = []
    for ev in (recent_material_changes or []):
        t = ev.ticker.upper()
        # A "debate shift" is signalled by change_category or thesis_trend_changed + summary mentions debate
        if ev.change_category in ("thesis_broke", "new_risk_emerged") or ev.thesis_trend_changed:
            if t not in debate_shifts:
                debate_shifts.append(t)

    # ── Rank entries by priority ─────────────────────────────────────────────
    scored: List[Tuple[float, str, Optional[MaterialChangeEvent], Optional[WatchlistEntry]]] = []
    for entry in watchlist_entries:
        t = entry.ticker.upper()
        ch = change_map.get(t)
        score = _entry_priority_score(entry, change_map)
        scored.append((score, t, ch, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked: List[Tuple[str, Optional[MaterialChangeEvent], Optional[WatchlistEntry]]] = [
        (t, ch, en) for _, t, ch, en in scored
    ]

    # ── Top movers: tickers with changes, sorted by materiality ─────────────
    top_movers: List[str] = [
        t for t, ch, _ in ranked
        if ch is not None or entry_map.get(t, WatchlistEntry(ticker=t)).has_material_change
    ][:5]

    # ── Attention required: critical or high severity ────────────────────────
    attention_required: List[str] = []
    for t, ch, entry in ranked:
        if ch and ch.severity in ("high",) and ch.change_category in ("thesis_broke", "new_risk_emerged", "market_repriced"):
            attention_required.append(t)
        elif ch and ch.change_category == "thesis_broke":
            attention_required.append(t)
        elif entry and entry.has_material_change and t not in attention_required:
            attention_required.append(t)
    # Deduplicate
    seen_attn: set[str] = set()
    attention_required = [t for t in attention_required if not (t in seen_attn or seen_attn.add(t))]  # type: ignore[func-returns-value]

    # ── No material changes overnight ────────────────────────────────────────
    n_material = len([t for t, ch, _ in ranked if ch is not None])
    if n_material == 0 and not any(e.has_material_change for e in watchlist_entries):
        market_regime_note = f"Overnight session quiet; {ticker_count} name{'s' if ticker_count != 1 else ''} monitoring."
        brief_text = (
            f"No material thesis changes overnight. "
            f"{ticker_count} name{'s' if ticker_count != 1 else ''} monitoring."
        )
        return MorningBrief(
            generated_at=generated_at,
            reference_date=ref_date,
            brief_text=brief_text,
            top_movers=top_movers,
            attention_required=[],
            debate_shifts=debate_shifts,
            market_regime_note=market_regime_note,
            ticker_count=ticker_count,
        )

    # ── Build brief sentences ────────────────────────────────────────────────
    # We aim for 3-8 sentences, each carrying unique information.
    # Priority order: thesis breaks → debate shifts → repricing → trend changes → stable

    priority_tickers = [t for t, ch, _ in ranked if ch is not None][:6]
    ranked_priority = [(t, ch, en) for t, ch, en in ranked if t in priority_tickers]

    sentences = _group_by_driver(ranked_priority)

    # Cap at 8 sentences, floor at 1
    sentences = sentences[:8]

    # Opening context line if multiple names flagged
    n_flagged = len(priority_tickers)
    if n_flagged >= 2:
        intro = f"{n_flagged} names flagged overnight."
        sentences = [intro] + sentences

    # Prepend critical/high event impact sentences
    if _impact_sentences:
        sentences = _impact_sentences + sentences

    # Trim to 8 sentences total
    sentences = sentences[:8]

    brief_text = " ".join(s for s in sentences if s)

    # ── Market regime note ───────────────────────────────────────────────────
    # Derive from the dominant change category across events
    all_categories = [ch.change_category for _, ch, _ in ranked if ch]
    if "thesis_broke" in all_categories:
        market_regime_note = "Thesis breaks elevated — review position sizing before open."
    elif "new_risk_emerged" in all_categories:
        market_regime_note = "New structural risks emerged overnight; risk/reward shifts warrant review."
    elif "market_repriced" in all_categories:
        market_regime_note = "Market repricing underway; thesis directionally intact but entry levels shifted."
    elif n_flagged > 0:
        market_regime_note = f"{n_flagged} name{'s' if n_flagged != 1 else ''} with thesis updates; no systemic break detected."
    else:
        market_regime_note = f"Session quiet across {ticker_count} monitored name{'s' if ticker_count != 1 else ''}."

    return MorningBrief(
        generated_at=generated_at,
        reference_date=ref_date,
        brief_text=brief_text,
        top_movers=top_movers,
        attention_required=attention_required,
        debate_shifts=debate_shifts,
        market_regime_note=market_regime_note,
        ticker_count=ticker_count,
    )


# ---------------------------------------------------------------------------
# Phase M — generate_morning_brief_v2 (5-section command center)
# ---------------------------------------------------------------------------

# PM-language narrative templates keyed by (rate_environment, risk_appetite)
_REGIME_NARRATIVES: dict[tuple[str, str], str] = {
    ("higher_for_longer", "risk_off"):
        "Higher-for-longer confirmed with risk appetite contracting — rate-duration pressure is real for long-dated multiples.",
    ("higher_for_longer", "selective"):
        "Higher-for-longer regime intact — market selective, quality over growth at current multiples.",
    ("higher_for_longer", "risk_on"):
        "Rate resilience surprising the market — risk-on despite higher-for-longer, likely driven by earnings momentum.",
    ("cutting_cycle", "risk_on"):
        "Cutting cycle underway with risk appetite recovering — rotation back into rate-sensitive growth underway.",
    ("cutting_cycle", "selective"):
        "Cutting cycle confirmed but market selective — front-end relief priced, back-end yields sticky.",
    ("cutting_cycle", "risk_off"):
        "Rate cuts priced but risk appetite not recovering — macro uncertainty overriding the rate tailwind.",
    ("pause", "selective"):
        "Fed on hold, market in wait-and-see — next catalyst is the data, not the Fed.",
    ("pause", "risk_on"):
        "Fed pause creating a Goldilocks window — neither too hot nor too cold for the risk trade.",
    ("pause", "risk_off"):
        "Fed pause not enough to calm markets — downside risks dominating despite rate stability.",
    ("uncertain", "selective"):
        "Macro regime unclear — market navigating without a dominant narrative, staying selective.",
    ("uncertain", "risk_off"):
        "Regime uncertainty with risk appetite contracting — defensive posture warranted.",
    ("uncertain", "risk_on"):
        "Regime uncertainty but risk-on — market front-running a positive resolution.",
}

# PM-style narrative shift templates
_NARRATIVE_SHIFT_TEMPLATES: dict[str, str] = {
    "thesis_broke":
        "{ticker}: thesis broke — {driver}",
    "debate_shift":
        "{ticker}: investment debate shifted — {driver}",
    "weakens_thesis":
        "{ticker}: setup less one-sided — {driver}",
    "strengthens_thesis":
        "{ticker}: execution check cleared — {driver}",
    "market_repriced":
        "{ticker}: multiple compressed, operating thesis intact — {driver}",
    "regime_change":
        "{ticker}: macro regime shift in play — {driver}",
    "priced_in":
        "{ticker}: expected outcome confirmed, debate moves to next catalyst",
}

# Debate shift PM-language
_DEBATE_SHIFT_TEMPLATES: list[str] = [
    "{ticker} debate shifting from {old_topic} → {new_topic}",
    "{ticker}: market rethinking the core question — {driver}",
    "Rate-sensitive names repricing again — macro overriding fundamentals",
    "AI infrastructure leadership debate rotating — {driver}",
    "Cloud optimization tailwinds broadening beyond mega-caps",
]


def _get_regime_narrative(rate_env: str, risk_app: str, dominant_narrative: str) -> str:
    """Derive the regime headline sentence."""
    if dominant_narrative:
        return dominant_narrative
    key = (rate_env, risk_app)
    return _REGIME_NARRATIVES.get(
        key,
        _REGIME_NARRATIVES.get(
            (rate_env, "selective"),
            "Market navigating without a dominant macro regime — stay selective.",
        ),
    )


def _build_narrative_shifts(
    event_impacts: List[EventImpactAssessment],
    watchlist_drift: List[WatchlistDriftSummary],
) -> List[str]:
    """
    Build 2-4 PM-compressed narrative-shift sentences from event impacts and drift.

    Priority: thesis_broke → debate_shift → weakens → strengthens → market_repriced
    """
    sentences: List[str] = []
    seen_tickers: set[str] = set()

    # Event impact-driven narratives (highest priority first)
    priority_order = [
        "thesis_broke", "debate_shift", "weakens_thesis",
        "strengthens_thesis", "market_repriced", "regime_change",
    ]
    impact_by_type: dict[str, List[EventImpactAssessment]] = {}
    for impact in event_impacts:
        impact_by_type.setdefault(impact.impact_type, []).append(impact)

    for itype in priority_order:
        for impact in impact_by_type.get(itype, []):
            ticker = impact.ticker
            if ticker in seen_tickers:
                continue
            if impact.alert_priority in ("critical", "high"):
                template = _NARRATIVE_SHIFT_TEMPLATES.get(itype, "{ticker}: {driver}")
                driver = (impact.thesis_implication or impact.event_headline or "")[:60]
                sentence = template.format(ticker=ticker, driver=driver)
                sentences.append(sentence)
                seen_tickers.add(ticker)
            if len(sentences) >= 4:
                break
        if len(sentences) >= 4:
            break

    # Drift-driven narratives (fill remaining slots)
    for drift in watchlist_drift:
        if drift.ticker in seen_tickers:
            continue
        if drift.direction in ("broke", "weakened") and drift.materiality >= 0.5:
            driver = drift.driver[:60] if drift.driver else ""
            if drift.direction == "broke":
                sentences.append(f"{drift.ticker}: thesis broke — {driver}".rstrip(" —"))
            else:
                sentences.append(f"{drift.ticker}: conviction weakening — {driver}".rstrip(" —"))
            seen_tickers.add(drift.ticker)
        if len(sentences) >= 4:
            break

    return sentences[:4]


def _build_debate_shifts(
    event_impacts: List[EventImpactAssessment],
    watchlist_drift: List[WatchlistDriftSummary],
) -> List[str]:
    """
    Build 2-3 PM-style debate-shift sentences.

    Sources:
    1. EventImpactAssessments with impact_type='debate_shift'
    2. WatchlistDriftSummary entries where direction='weakened' and materiality≥0.6
    """
    sentences: List[str] = []

    # From event impacts
    debate_impacts = [i for i in event_impacts if i.impact_type == "debate_shift"]
    debate_impacts.sort(key=lambda i: i.materiality_score, reverse=True)
    for impact in debate_impacts[:2]:
        driver = impact.thesis_implication or impact.event_headline or ""
        sentences.append(f"{impact.ticker}: {driver[:80]}")
        if len(sentences) >= 3:
            break

    # From drift summaries
    if len(sentences) < 3:
        for drift in watchlist_drift:
            if drift.direction == "weakened" and drift.materiality >= 0.6 and drift.driver:
                sentences.append(f"{drift.ticker} debate evolving — {drift.driver[:60]}")
                if len(sentences) >= 3:
                    break

    return sentences[:3]


def _build_priority_alerts(
    event_impacts: List[EventImpactAssessment],
    watchlist_drift: List[WatchlistDriftSummary],
) -> tuple[List[str], List[str]]:
    """
    Build alert sentences and attention_required ticker list.

    Returns (alert_sentences, attention_required_tickers).
    """
    alert_sentences: List[str] = []
    attention_tickers: List[str] = []

    # Critical first
    critical = [i for i in event_impacts if i.alert_priority == "critical"]
    critical.sort(key=lambda i: i.materiality_score, reverse=True)
    for impact in critical[:3]:
        implication = impact.thesis_implication or impact.event_headline or "review required"
        alert_sentences.append(f"⚑ {impact.ticker}: {implication[:80]}")
        if impact.ticker not in attention_tickers:
            attention_tickers.append(impact.ticker)

    # High priority
    high = [i for i in event_impacts if i.alert_priority == "high"]
    high.sort(key=lambda i: i.materiality_score, reverse=True)
    for impact in high[:3]:
        if len(alert_sentences) >= 5:
            break
        implication = impact.thesis_implication or impact.event_headline or "monitor closely"
        alert_sentences.append(f"{impact.ticker}: {implication[:80]}")
        if impact.ticker not in attention_tickers:
            attention_tickers.append(impact.ticker)

    # Drift-based attention (broke or weakened at high materiality)
    for drift in watchlist_drift:
        if drift.direction == "broke" and drift.ticker not in attention_tickers:
            attention_tickers.append(drift.ticker)

    return alert_sentences[:5], attention_tickers[:8]


def generate_morning_brief_v2(
    watchlist_entries: List[WatchlistEntry],
    recent_material_changes: Optional[List[MaterialChangeEvent]] = None,
    recent_alerts: Optional[List[Alert]] = None,
    event_impacts: Optional[List[EventImpactAssessment]] = None,
    watchlist_drift: Optional[List[WatchlistDriftSummary]] = None,
    regime: Optional[object] = None,
    reference_date: Optional[str] = None,
) -> MorningBriefV2:
    """
    Generate a Phase M 5-section institutional morning brief.

    Sections:
      1. MARKET REGIME    — dominant_narrative + key factors
      2. WHAT CHANGED     — 2-4 PM-compressed narrative-shift sentences
      3. DEBATE SHIFTS    — 2-3 investment debate evolution sentences
      4. PRIORITY ALERTS  — critical + high alerts as PM one-liners
      5. WATCHLIST DRIFT  — per-ticker thesis strengthened/weakened/broke

    Readable in under 60 seconds. Calm. Compressed. Institutional.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    ref_date = reference_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ticker_count = len(watchlist_entries) if watchlist_entries else 0

    _event_impacts = event_impacts or []
    _drift = watchlist_drift or []
    _material = recent_material_changes or []
    _alerts = recent_alerts or []

    # ── Section 1: Market Regime ───────────────────────────────────────────
    rate_env = "uncertain"
    risk_app = "selective"
    dominant_narrative = ""
    regime_factors: List[str] = []

    if regime is not None:
        rate_env = getattr(regime, "rate_environment", "uncertain") or "uncertain"
        risk_app = getattr(regime, "risk_appetite", "selective") or "selective"
        dominant_narrative = getattr(regime, "dominant_narrative", "") or ""
        regime_factors = list(getattr(regime, "key_macro_factors", []) or [])

    if not dominant_narrative and rate_env == "uncertain":
        if ticker_count:
            regime_headline = (
                "No new portfolio-wide regime event was available for this brief; "
                f"monitoring remains active across {ticker_count} tracked names."
            )
        else:
            regime_headline = (
                "No watchlist coverage is available yet; add tracked names to establish "
                "a briefing baseline."
            )
    else:
        regime_headline = _get_regime_narrative(rate_env, risk_app, dominant_narrative)

    # ── Section 2: What Changed ────────────────────────────────────────────
    narrative_shifts = _build_narrative_shifts(_event_impacts, _drift)

    # Fill from material changes if event impacts sparse
    if len(narrative_shifts) < 2 and _material:
        for ev in _material[:3]:
            if len(narrative_shifts) >= 4:
                break
            if ev.summary:
                narrative_shifts.append(_format_material_change_shift(ev))

    # ── Section 3: Debate Shifts ───────────────────────────────────────────
    debate_shifts_section = _build_debate_shifts(_event_impacts, _drift)

    # ── Section 4: Priority Alerts ─────────────────────────────────────────
    priority_alerts, attention_required = _build_priority_alerts(_event_impacts, _drift)

    # Fill attention from material changes
    for ev in _material:
        if ev.change_category in ("thesis_broke", "new_risk_emerged"):
            if ev.ticker not in attention_required:
                attention_required.append(ev.ticker)

    # ── Section 5: Watchlist Drift ─────────────────────────────────────────
    # Use provided drift, or compute minimal version from material changes
    if not _drift and _material:
        for ev in _material:
            direction = "broke" if ev.change_category == "thesis_broke" else "weakened"
            _drift.append(
                WatchlistDriftSummary(
                    ticker=ev.ticker,
                    direction=direction,
                    driver=(ev.summary or "")[:60],
                    materiality=ev.materiality_score,
                    alert_priority="high" if ev.severity == "high" else "medium",
                )
            )

    # Top movers by materiality
    top_movers = [
        d.ticker for d in sorted(_drift, key=lambda d: d.materiality, reverse=True)[:5]
    ]

    # ── Backward-compat brief_text ─────────────────────────────────────────
    brief_parts = [regime_headline] + narrative_shifts[:2] + priority_alerts[:2]
    brief_text = " ".join(p for p in brief_parts if p)

    market_regime_note = (
        "Thesis breaks elevated — review position sizing before open."
        if any(d.direction == "broke" for d in _drift)
        else regime_headline
    )

    return MorningBriefV2(
        generated_at=generated_at,
        reference_date=ref_date,
        ticker_count=ticker_count,
        regime_headline=regime_headline,
        regime_factors=regime_factors[:4],
        rate_environment=rate_env,
        risk_appetite=risk_app,
        narrative_shifts=narrative_shifts,
        debate_shifts=debate_shifts_section,
        priority_alerts=priority_alerts,
        attention_required=attention_required[:8],
        watchlist_drift=_drift,
        top_movers=top_movers,
        brief_text=brief_text,
        market_regime_note=market_regime_note,
    )
