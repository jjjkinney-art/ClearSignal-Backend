"""
Phase 9G · Slice 5B — adversarial-prior ("poison") builder.

The poison condition is the load-bearing anti-anchoring test.  Given a real
dossier and the direction THIS CYCLE'S EVIDENCE points, ``build_poison_dossier``
returns a new dossier whose prior asserts the OPPOSITE direction with high
conviction:

  * head.stance flipped to the contradicting direction, conviction pinned high,
    the genuine ``primary_concern`` stripped (poison hides the real worry);
  * debate.current_lean planted toward the contradicting pole, confidence high;
  * every catalyst direction flipped to support the contradicting view, weight
    pinned high, kept fresh so decay can't gate it out;
  * failure-modes aligned with the contradicting story (dropped when the poison
    is "all-clear" bullish; strengthened when the poison manufactures doom).

A correct, non-anchored synthesis must follow the fresh evidence and reject (or
explicitly discount) this planted prior.  Pure: the input dossier is never
mutated; all timestamps are derived from the supplied ``now``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

from app.services.dossier_injection_service import _g

from .golden_set import NOW, BULLISH, BEARISH, NEUTRAL

# How confident the planted (wrong) prior is.  High by design — a timid poison
# would be a weak test of the red-team trailer.
POISON_CONVICTION = 0.9
POISON_DEBATE_CONFIDENCE = 0.85
POISON_CATALYST_WEIGHT = 0.88

_LEAN_FOR = {BULLISH: "lean_bull", BEARISH: "lean_bear", NEUTRAL: "balanced"}
_CATALYST_DIR_FOR = {BULLISH: "positive", BEARISH: "negative", NEUTRAL: "neutral"}
_DISMISSIVE_CONCERN = {
    BULLISH: "no material downside risks identified",
    BEARISH: "no offsetting strengths identified",
    NEUTRAL: "no decisive factors identified",
}


def _fresh(now: datetime, days: int = 4) -> datetime:
    return now - timedelta(days=days)


def build_poison_dossier(
    dossier: Optional[Dict[str, Any]],
    contradict_direction: str,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Return a new dossier whose prior confidently asserts *contradict_direction*.

    *contradict_direction* should be the OPPOSITE of the case's
    ``evidence_direction`` so the planted prior fights the fresh evidence.
    """
    if not dossier:
        return None
    now = now or NOW
    head = dossier.get("head")
    if head is None:
        return None

    ts = _fresh(now)

    poisoned_head = SimpleNamespace(
        ticker=_g(head, "ticker", ""),
        stance=contradict_direction,
        conviction=POISON_CONVICTION,
        primary_concern=_DISMISSIVE_CONCERN.get(contradict_direction,
                                                "no material risks identified"),
        prior_as_of=ts,
        last_full_update_at=ts,
        updated_at=ts,
    )

    # Debate: keep the poles (so the framing is intact) but plant a confident
    # lean toward the contradicting pole.
    src_debate = dossier.get("debate")
    poisoned_debate = None
    if src_debate is not None:
        poisoned_debate = SimpleNamespace(
            question=_g(src_debate, "question", ""),
            bull_pole=_g(src_debate, "bull_pole", ""),
            bear_pole=_g(src_debate, "bear_pole", ""),
            current_lean=_LEAN_FOR.get(contradict_direction, "balanced"),
            confidence=POISON_DEBATE_CONFIDENCE,
            updated_at=ts,
        )

    # Catalysts: flip every direction to support the contradicting view.
    poisoned_catalysts = []
    flipped_dir = _CATALYST_DIR_FOR.get(contradict_direction, "neutral")
    for c in dossier.get("catalysts", []) or []:
        poisoned_catalysts.append(SimpleNamespace(
            statement=_g(c, "statement", ""),
            direction=flipped_dir,
            expected_window=_g(c, "expected_window", "") or "near term",
            status="open",
            conviction_weight=POISON_CATALYST_WEIGHT,
            created_at=ts,
        ))

    # Failure modes: align with the planted story.
    #   bullish poison  → "all clear", drop the warning;
    #   bearish poison  → manufacture a high-relevance doom analog.
    if contradict_direction == BULLISH:
        poisoned_failures = []
        poisoned_durability = SimpleNamespace(
            cycle_position="early-cycle", horizon_hint="18+ months",
            updated_at=ts)
    else:
        poisoned_failures = [SimpleNamespace(
            analog_id="planted_terminal_decline",
            sequence_stage=4,
            stage_evidence="planted: prior asserts terminal, irreversible deterioration",
            relevance_at_match=0.92,
            matched_at=ts,
        )]
        poisoned_durability = SimpleNamespace(
            cycle_position="end-of-cycle", horizon_hint="0-3 months",
            updated_at=ts)

    return {
        "head": poisoned_head,
        "debate": poisoned_debate,
        "dimensions": [],
        "catalysts": poisoned_catalysts,
        "variant": None,
        "durability": poisoned_durability,
        "failure_modes": poisoned_failures,
    }
