"""
Investment Memory context formatter.

Converts the raw memory dict from ``get_memory_context()`` into:
  - A plain-text block for injection into the synthesis prompt.
  - A structured dict matching MemoryContextSummary for the API response.

No LLM calls.  Pure Python.  Designed for fast inline execution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Prompt block formatting
# ---------------------------------------------------------------------------

_DIRECTION_ARROW = {
    "rising":   "↑ rising",
    "falling":  "↓ falling",
    "stable":   "→ stable",
    "volatile": "⇄ volatile",
}


def format_memory_for_prompt(ctx: Dict[str, Any]) -> str:
    """Return a plain-text memory block for injection into the synthesis prompt.

    The block opens and closes with sentinel lines so the LLM clearly
    understands what is historical context vs current analysis.

    Returns an empty string when ctx is None or empty.
    """
    if not ctx:
        return ""

    ticker = ctx.get("ticker", "")
    total_queries = ctx.get("total_queries", 0)
    days_in_coverage = ctx.get("days_in_coverage", 0)
    stance_history: List[str] = ctx.get("stance_history", [])
    conviction_trend: List[float] = ctx.get("conviction_trend", [])
    conviction_direction: str = ctx.get("conviction_direction", "stable")
    dominant_concern: str = ctx.get("dominant_concern", "")
    concern_dist: Dict[str, int] = ctx.get("concern_distribution", {})
    last_delta_magnitude: Optional[str] = ctx.get("last_delta_magnitude")
    last_delta_days_ago: Optional[int] = ctx.get("last_delta_days_ago")
    notable_events: List[str] = ctx.get("notable_events", [])
    stance_changes_total: int = ctx.get("stance_changes_total", 0)

    lines: List[str] = [
        f"=== CLEARSIGNAL MEMORY: {ticker} ===",
        f"Coverage: {total_queries} prior {'analysis' if total_queries == 1 else 'analyses'}"
        + (f" over {days_in_coverage} days" if days_in_coverage > 0 else ""),
    ]

    # ── Stance consistency ───────────────────────────────────────────────────
    if stance_history:
        unique_stances = list(dict.fromkeys(stance_history))  # preserve order, dedupe
        if len(unique_stances) == 1:
            lines.append(f"Stance: consistently {stance_history[0]} across all analyses")
        else:
            history_str = " → ".join(stance_history)
            lines.append(f"Stance history (newest first): {history_str}")

    if stance_changes_total == 0 and len(stance_history) > 1:
        lines.append("Stance changes: none — view has been consistent")
    elif stance_changes_total > 0:
        lines.append(f"Stance changes: {stance_changes_total} recorded")

    # ── Conviction trend ─────────────────────────────────────────────────────
    if conviction_trend:
        pcts = [f"{round(c * 100)}pp" for c in conviction_trend]
        direction_label = _DIRECTION_ARROW.get(conviction_direction, conviction_direction)
        peak = max(conviction_trend)
        trough = min(conviction_trend)
        trend_str = " → ".join(pcts)
        lines.append(f"Conviction trend (newest first): {trend_str}  [{direction_label}]")
        if conviction_direction in ("rising", "falling") and len(conviction_trend) > 2:
            if conviction_direction == "falling":
                lines.append(
                    f"  Note: conviction has declined from a {round(peak * 100)}pp peak"
                )
            else:
                lines.append(
                    f"  Note: conviction has risen from a {round(trough * 100)}pp trough"
                )

    # ── Concern pattern ──────────────────────────────────────────────────────
    if dominant_concern:
        concern_label = dominant_concern.replace("_", " ")
        n = total_queries
        count = concern_dist.get(dominant_concern, 0)
        if count > 0 and n > 0:
            lines.append(
                f"Persistent concern: {concern_label} "
                f"(flagged in {count}/{n} {'analysis' if n == 1 else 'analyses'})"
            )
        else:
            lines.append(f"Persistent concern: {concern_label}")

    # Secondary concerns (top 2, excluding dominant)
    secondary = [
        (k, v) for k, v in concern_dist.items()
        if k != dominant_concern
    ][:2]
    if secondary:
        sec_str = ", ".join(
            f"{k.replace('_', ' ')} ({v})" for k, v in secondary
        )
        lines.append(f"Secondary concerns: {sec_str}")

    # ── Recent delta ─────────────────────────────────────────────────────────
    if last_delta_magnitude is not None:
        days_str = (
            f"{last_delta_days_ago}d ago"
            if last_delta_days_ago is not None
            else "recently"
        )
        lines.append(f"Last thesis change: {last_delta_magnitude} ({days_str})")

    # ── Notable events ───────────────────────────────────────────────────────
    for event in notable_events[:2]:
        lines.append(f"Notable: {event}")

    # ── LLM instructions ─────────────────────────────────────────────────────
    lines.append("")
    lines.append("Your synthesis MUST acknowledge this history explicitly:")
    lines.append(
        "  1. State whether today's view ALIGNS WITH or DIVERGES FROM prior analyses."
    )
    lines.append(
        "  2. If conviction is trending in a direction, acknowledge it and explain whether"
        " today's analysis continues or reverses that trend."
    )
    if dominant_concern:
        concern_label = dominant_concern.replace("_", " ")
        lines.append(
            f"  3. Address whether {concern_label} (the persistent concern) has intensified,"
            " stabilized, or resolved."
        )
    lines.append(
        "  IMPORTANT: New evidence overrides memory. Do not anchor to prior views"
        " if today's analysis points in a different direction."
    )
    lines.append("=== END MEMORY ===")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response dict (for MemoryContextSummary schema)
# ---------------------------------------------------------------------------

def memory_context_for_response(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stripped-down dict matching the MemoryContextSummary schema.

    Excludes large internal fields (version_ids) that are not needed in the API response.
    """
    if not ctx:
        return {}
    return {
        "ticker": ctx.get("ticker", ""),
        "total_queries": ctx.get("total_queries", 0),
        "days_in_coverage": ctx.get("days_in_coverage", 0),
        "stance_history": ctx.get("stance_history", []),
        "conviction_trend": ctx.get("conviction_trend", []),
        "conviction_direction": ctx.get("conviction_direction", "stable"),
        "dominant_concern": ctx.get("dominant_concern", ""),
        "concern_distribution": ctx.get("concern_distribution", {}),
        "last_delta_magnitude": ctx.get("last_delta_magnitude"),
        "last_delta_days_ago": ctx.get("last_delta_days_ago"),
        "stance_changes_total": ctx.get("stance_changes_total", 0),
        "notable_events": ctx.get("notable_events", []),
    }
