"""
Onboarding state machine — Phase 16 · Slice 7.

Tracks sign-up wizard progress via user_profiles.onboarding_step.
No new tables required — the column already exists with default "pending".

Step sequence (ordered):
  account_created → auth_verified → import_offered → import_completed → onboarding_complete

DB compat:
  The model default is "pending"; this module treats "pending" as an alias
  for "account_created" on read and never writes "pending" back.

Public API:
  get_onboarding_state(session, user_id) → OnboardingState
  advance_step(session, user_id)         → OnboardingState  (move one step forward)
  complete_step(session, user_id)        → OnboardingState  (jump to onboarding_complete)
  set_step(session, user_id, step)       → OnboardingState  (direct write; validates step name)
  mark_import_completed(session, user_id)→ OnboardingState  (called by account_import_service)

Null-session safety:
  All functions return safe defaults when session is None.

Idempotency:
  advance_step at the terminal step is a no-op (returns current state).
  set_step to the same step is a no-op.
  mark_import_completed when step > import_completed is a no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step sequence
# ---------------------------------------------------------------------------

STEPS: List[str] = [
    "account_created",
    "auth_verified",
    "import_offered",
    "import_completed",
    "onboarding_complete",
]

_STEP_INDEX = {step: i for i, step in enumerate(STEPS)}
_TERMINAL   = "onboarding_complete"
_INITIAL    = "account_created"

# The DB column default; treated as account_created on read.
_PENDING_ALIAS = "pending"


def _normalise(step: Optional[str]) -> str:
    """Translate DB default 'pending' → 'account_created'; return as-is otherwise."""
    if step is None or step == _PENDING_ALIAS:
        return _INITIAL
    return step


def _validate_step(step: str) -> None:
    if step not in _STEP_INDEX:
        raise ValueError(
            f"unknown onboarding step {step!r}; valid steps: {STEPS}"
        )


def _next_step(current: str) -> Optional[str]:
    idx = _STEP_INDEX.get(current)
    if idx is None or idx >= len(STEPS) - 1:
        return None
    return STEPS[idx + 1]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OnboardingState:
    """Current onboarding state for one user."""
    user_id:      str
    step:         str             # current step name (never "pending")
    step_index:   int             # 0-based position in STEPS
    is_complete:  bool            # True when step == onboarding_complete
    next_step:    Optional[str]   # None when terminal
    completed_at: Optional[datetime]  # from user_profiles.onboarding_completed_at


def _make_state(user_id: str, step: str, completed_at: Optional[datetime]) -> OnboardingState:
    step = _normalise(step)
    return OnboardingState(
        user_id=user_id,
        step=step,
        step_index=_STEP_INDEX.get(step, 0),
        is_complete=(step == _TERMINAL),
        next_step=_next_step(step),
        completed_at=completed_at,
    )


def _empty_state(user_id: str) -> OnboardingState:
    return _make_state(user_id, _INITIAL, None)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _get_profile(session, user_id: str):
    from app.db.models import UserProfile
    from sqlalchemy import select

    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _write_step(session, user_id: str, step: str) -> OnboardingState:
    """Persist step to user_profiles.onboarding_step; create profile if absent."""
    now = datetime.now(timezone.utc)

    from app.db.models import UserProfile
    from sqlalchemy import select

    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    completed_at: Optional[datetime] = None

    if profile is None:
        profile = UserProfile(
            user_id=user_id,
            onboarding_step=step,
            onboarding_completed_at=(now if step == _TERMINAL else None),
        )
        session.add(profile)
    else:
        completed_at = profile.onboarding_completed_at
        if profile.onboarding_step == step:
            return _make_state(user_id, step, completed_at)

        profile.onboarding_step = step
        if step == _TERMINAL and profile.onboarding_completed_at is None:
            profile.onboarding_completed_at = now
            completed_at = now
        profile.updated_at = now

    await session.flush()
    return _make_state(user_id, step, completed_at)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_onboarding_state(session, user_id: str) -> OnboardingState:
    """Return the current onboarding state for user_id.

    Returns an empty (account_created) state when session is None or when the
    user has no profile row yet.
    """
    if session is None:
        return _empty_state(user_id)

    profile = await _get_profile(session, user_id)
    if profile is None:
        return _empty_state(user_id)

    return _make_state(user_id, profile.onboarding_step, profile.onboarding_completed_at)


async def advance_step(session, user_id: str) -> OnboardingState:
    """Move the user one step forward in the onboarding sequence.

    Idempotent at the terminal step (onboarding_complete) — returns the
    current state without error rather than raising.
    Returns the updated OnboardingState.
    Returns the current (empty) state when session is None.
    """
    if session is None:
        return _empty_state(user_id)

    current = await get_onboarding_state(session, user_id)

    if current.is_complete:
        return current  # already terminal — no-op

    nxt = _next_step(current.step)
    if nxt is None:
        return current  # defensive; should not happen unless STEPS changed

    return await _write_step(session, user_id, nxt)


async def complete_step(session, user_id: str) -> OnboardingState:
    """Mark onboarding as fully complete, skipping any remaining steps.

    Idempotent: calling again when already complete is a no-op.
    Returns the terminal OnboardingState.
    Returns the empty state when session is None.
    """
    if session is None:
        return _empty_state(user_id)

    return await _write_step(session, user_id, _TERMINAL)


async def set_step(session, user_id: str, step: str) -> OnboardingState:
    """Write an explicit step name.

    Raises ValueError for unknown step names.
    Lower-than-current transitions are allowed (e.g. for admin reset).
    Idempotent: writing the current step is a no-op.
    Returns the empty state when session is None.
    """
    if session is None:
        return _empty_state(user_id)

    _validate_step(step)
    return await _write_step(session, user_id, step)


async def mark_import_completed(session, user_id: str) -> OnboardingState:
    """Advance to import_completed.

    Called by account_import_service.execute_import after a successful import.
    Only advances if the current step is at or before import_offered; if the
    user is already at import_completed or onboarding_complete, this is a no-op.
    Returns the empty state when session is None.
    """
    if session is None:
        return _empty_state(user_id)

    current = await get_onboarding_state(session, user_id)
    target_idx = _STEP_INDEX["import_completed"]

    if current.step_index >= target_idx:
        return current  # already at or past import_completed — no-op

    return await _write_step(session, user_id, "import_completed")
