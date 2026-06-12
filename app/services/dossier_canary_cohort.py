"""
Phase 9G · Slice 5C — Deterministic cohort assignment for the dossier injection canary.

Assigns each session to one of three cohorts based on a CRC32 hash of the session_id:

  COHORT_INJECTED   — session receives the injection block in the synthesis prompt
  COHORT_CONTROL    — session is in the non-injected comparison arm
  COHORT_INELIGIBLE — injection is disabled; no canary active

The permanent 5% holdout (HOLDOUT_PCT buckets 0–4) is always COHORT_CONTROL
even when canary_pct=95.  This preserves a live comparison arm post-GA and makes
long-run drift detectable.  canary_pct is clamped to [0, 95] so the holdout can
never be crowded out.

Stickiness by construction: the same session_id always CRC32-hashes to the same
0–99 bucket, so cohort assignment is deterministic with no persistence required.
"""

from __future__ import annotations

import binascii

COHORT_INJECTED   = "injected"
COHORT_CONTROL    = "control"
COHORT_INELIGIBLE = "ineligible"

HOLDOUT_PCT = 5  # buckets 0–4, permanent control holdout


def _session_bucket(session_id: str) -> int:
    """Deterministic 0–99 bucket from CRC32 of session_id."""
    raw = binascii.crc32(session_id.encode("utf-8", errors="replace")) & 0xFFFFFFFF
    return int(raw % 100)


def decide_cohort(session_id: str, canary_pct: int, enabled: bool) -> str:
    """Return the cohort label for this session.

    Args:
        session_id:  stable per-session identifier (e.g. X-Session-ID header).
        canary_pct:  percentage of sessions (0–95) that receive injection.
                     Values above 95 are clamped to preserve the holdout floor.
        enabled:     whether live injection is active.

    Returns:
        COHORT_INJECTED, COHORT_CONTROL, or COHORT_INELIGIBLE.
    """
    if not enabled or canary_pct <= 0:
        return COHORT_INELIGIBLE

    pct = min(max(int(canary_pct), 0), 95)
    bucket = _session_bucket(session_id)

    if bucket < HOLDOUT_PCT:
        # Permanent holdout: always CONTROL, even at 95% rollout.
        return COHORT_CONTROL

    if bucket < HOLDOUT_PCT + pct:
        return COHORT_INJECTED

    return COHORT_CONTROL
