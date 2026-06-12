"""
Phase 10A · Slice 9 — Deterministic cohort assignment for the loop canary.

Assigns each session/user to one of four cohorts based on a CRC32 hash of
the user_id or session_id:

  COHORT_INTERNAL   — internal users always receive the loop output
  COHORT_CANARY     — hash-selected rollout cohort (loop active)
  COHORT_CONTROL    — hash-selected non-rollout arm (loop shadow/off)
  COHORT_INELIGIBLE — loop is off or canary_pct=0

The permanent 5% holdout (buckets 0–4) is always COHORT_CONTROL even when
canary_pct=95.  This preserves a live comparison arm post-GA.
canary_pct is clamped to [0, 95] to protect the holdout floor.

Stickiness by construction: the same subject_id always CRC32-hashes to the
same 0–99 bucket, so cohort assignment is deterministic and requires no
persistence.

Internal users bypass the hash entirely and always receive COHORT_INTERNAL.
The internal list is configured via LOOP_INTERNAL_USER_IDS (comma-separated).
"""

from __future__ import annotations

import binascii
from typing import Set

COHORT_INTERNAL   = "internal"
COHORT_CANARY     = "canary"
COHORT_CONTROL    = "control"
COHORT_INELIGIBLE = "ineligible"

HOLDOUT_PCT = 5   # buckets 0–4, permanent control holdout


def _subject_bucket(subject_id: str) -> int:
    """Deterministic 0–99 bucket from CRC32 of subject_id."""
    raw = binascii.crc32(subject_id.encode("utf-8", errors="replace")) & 0xFFFFFFFF
    return int(raw % 100)


def _internal_user_ids() -> Set[str]:
    """Return the configured set of internal user_ids (empty if unconfigured)."""
    try:
        from app.config import settings
        raw = getattr(settings, "loop_internal_user_ids", "") or ""
        return {uid.strip() for uid in raw.split(",") if uid.strip()}
    except Exception:
        return set()


def decide_cohort(
    subject_id: str,
    canary_pct: int,
    enabled: bool,
    *,
    shadow: bool = True,
) -> str:
    """Return the cohort label for this subject.

    Parameters
    ----------
    subject_id : Stable per-user or per-session identifier.
    canary_pct : Percentage of subjects (0–95) that receive the loop output.
                 Values above 95 are clamped to preserve the holdout floor.
    enabled    : Whether the loop is active (master gate).
    shadow     : When True, loop runs in shadow mode — all hash-selected
                 subjects still receive COHORT_CANARY but no real delivery
                 occurs.  This flag is informational for callers; the cohort
                 assignment logic itself does not change.

    Returns
    -------
    One of COHORT_INTERNAL, COHORT_CANARY, COHORT_CONTROL, COHORT_INELIGIBLE.
    """
    if not enabled:
        return COHORT_INELIGIBLE

    # Internal users bypass the canary_pct gate and the hash entirely
    if subject_id in _internal_user_ids():
        return COHORT_INTERNAL

    if canary_pct <= 0:
        return COHORT_INELIGIBLE

    pct    = min(max(int(canary_pct), 0), 95)
    bucket = _subject_bucket(subject_id)

    # Permanent holdout: always CONTROL even at 95% rollout
    if bucket < HOLDOUT_PCT:
        return COHORT_CONTROL

    if bucket < HOLDOUT_PCT + pct:
        return COHORT_CANARY

    return COHORT_CONTROL
