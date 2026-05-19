"""
Morning brief service — PM-style market intelligence summary.

Generates a compressed hedge-fund morning note from watchlist state,
recent material changes, and recent alerts.  All logic is deterministic:
no LLM calls.  The brief prioritises by materiality and groups related
names when they share a common macro driver.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from ..schemas import Alert, MaterialChangeEvent, WatchlistEntry


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


def generate_morning_brief(
    watchlist_entries: List[WatchlistEntry],
    recent_material_changes: List[MaterialChangeEvent],
    recent_alerts: List[Alert],
    reference_date: Optional[str] = None,
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
    """
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
