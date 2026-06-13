"""
Canonical Severity Model — Phase 10C · Slice 1.

THE single authoritative severity ladder for the ClearSignal intelligence
platform.  Before this module, four divergent severity vocabularies existed
across the codebase (see ``LEGACY_VOCABULARIES`` below).  This module defines
one canonical five-level ladder and the *only* sanctioned translation point
between every legacy vocabulary and the canonical one.

Canonical ladder (most → least severe)
--------------------------------------
    CRITICAL  > HIGH  > MEDIUM  > LOW  > INFO

These five — and only these five — are the canonical severity values.  Their
string forms are lowercase (``"critical"`` … ``"info"``) so they are stable in
JSON payloads, DB columns, and logs.

Design contract
---------------
* **One translator.**  ``to_canonical_severity()`` is the sole function that
  converts a legacy/raw severity string into a canonical value.  Every other
  module that needs a canonical severity calls it (or a source adapter that
  wraps it).  A second translation function anywhere in the codebase is a
  release blocker (Phase 10C spec §3.2; the Phase 10B Slice 9 ``drift_state``
  single-translator precedent).
* **Fail safe = fail low.**  Unknown values never escalate.  In a delivery
  system the safe direction is *down* (toward ``INFO``/no-interruption), never
  *up* (toward ``CRITICAL``/spam).  Lenient mode maps unknowns to a caller-
  chosen ``default`` (``INFO`` by default).  Strict mode raises ``ValueError``
  so audits can detect an unregistered vocabulary.
* **No behavior change in Slice 1.**  This module *adds* a canonical model and
  adapters.  It does not rewire ``alert_prioritizer``, ``loop_delivery_service``,
  or ``morning_brief_service`` — those keep their own internal rank maps until
  Slice 2 consumes the adapters.  The one consolidation made now is
  ``watchlist_alert_payload.normalize_severity``, which already used this exact
  five-level ladder and now delegates here (behavior-preserving).

This module performs no DB writes, no delivery, no notification, and no I/O.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ---------------------------------------------------------------------------
# Canonical ladder
# ---------------------------------------------------------------------------

CRITICAL: str = "critical"
HIGH: str = "high"
MEDIUM: str = "medium"
LOW: str = "low"
INFO: str = "info"

# Ordered most → least severe.  Index in this tuple is NOT the rank; use
# ``severity_rank`` for the numeric rank (higher == more severe).
CANONICAL_SEVERITIES: Tuple[str, ...] = (CRITICAL, HIGH, MEDIUM, LOW, INFO)

# Numeric rank — higher is more severe.  Aligns with the existing
# morning_brief_service ordering (critical=4 … low=1) and extends it with
# INFO=0, so promoting the brief to this model later is a no-op on ordering.
_CANONICAL_RANK: Dict[str, int] = {
    CRITICAL: 4,
    HIGH:     3,
    MEDIUM:   2,
    LOW:      1,
    INFO:     0,
}


# ---------------------------------------------------------------------------
# Registered legacy vocabularies (the audit's source of truth)
# ---------------------------------------------------------------------------
#
# Every severity vocabulary that exists in the codebase is registered here.
# The audit test (tests/test_services/test_severity_audit.py) asserts that the
# union of these tokens is EXACTLY the translator's known domain — so a fifth
# (unregistered) vocabulary cannot appear without failing the build.

LEGACY_VOCABULARIES: Dict[str, FrozenSet[str]] = {
    # app/services/alert_prioritizer.py — AlertPriority.priority output
    "alert_prioritizer": frozenset({"critical", "high", "medium", "ignore"}),
    # app/services/loop_delivery_service.py — _SEVERITY_RANK (floor comparison)
    "delivery_ledger":   frozenset({"info", "warning", "alert", "critical"}),
    # app/services/watchlist_alert_payload.py — normalize_severity five-level
    "watchlist_alert":   frozenset({"critical", "high", "medium", "low", "info"}),
    # app/services/morning_brief_service.py — _SEVERITY_RANK ordering
    "briefing_ranking":  frozenset({"critical", "high", "medium", "low", ""}),
}

# The unified translation map: every legacy token → its canonical value.
# Built so that no two legacy vocabularies collide (verified by the audit).
# The empty string is intentionally NOT a key — absence is handled by the
# ``default`` parameter so each caller chooses its own safe floor.
_TRANSLATION_MAP: Dict[str, str] = {
    # canonical (identity)
    "critical": CRITICAL,
    "high":     HIGH,
    "medium":   MEDIUM,
    "low":      LOW,
    "info":     INFO,
    # alert_prioritizer
    "ignore":   INFO,      # "ignore" → INFO (do not interrupt)
    # delivery_ledger
    "warning":  MEDIUM,    # delivery "warning" sits at MEDIUM
    "alert":    HIGH,      # delivery "alert" sits at HIGH
    # common aliases (defensive; absent/none → safe floor)
    "none":     INFO,
}

# Defensive aliases: tokens the translator accepts that are NOT part of any
# product severity vocabulary — they exist only to normalize absent/placeholder
# inputs.  Registered here so the audit can distinguish them from a genuine new
# vocabulary.  ``"none"`` preserves the pre-10C watchlist mapping ("none" → info).
DEFENSIVE_ALIASES: FrozenSet[str] = frozenset({"none"})

# The set of raw tokens the translator recognizes (excludes "" by design).
KNOWN_TOKENS: FrozenSet[str] = frozenset(_TRANSLATION_MAP.keys())


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

class UnknownSeverityError(ValueError):
    """Raised by ``to_canonical_severity(strict=True)`` on an unmapped value."""


def is_canonical(value: str) -> bool:
    """Return True iff ``value`` is already one of the five canonical strings."""
    return value in _CANONICAL_RANK


def severity_rank(canonical: str) -> int:
    """Return the numeric rank of a canonical severity (higher == more severe).

    Unknown / non-canonical input returns the floor rank (0), never raises —
    callers compare ranks on hot paths and must not crash on bad data.
    """
    return _CANONICAL_RANK.get(canonical, 0)


def to_canonical_severity(
    raw: str,
    *,
    strict: bool = False,
    default: str = INFO,
) -> str:
    """Translate any registered legacy severity string to a canonical value.

    This is the **only** sanctioned severity-translation function in the
    codebase.  All source adapters below wrap it.

    Parameters
    ----------
    raw:
        The incoming severity string from any vocabulary (case-insensitive,
        surrounding whitespace ignored).
    strict:
        When True, an unrecognized value raises ``UnknownSeverityError``
        instead of falling back.  Used by audits to detect a new vocabulary.
    default:
        The canonical value returned for an unrecognized input in lenient
        mode.  Defaults to ``INFO`` (fail-low).  ``default`` itself must be a
        canonical value.

    Returns
    -------
    One of ``CANONICAL_SEVERITIES``.
    """
    if default not in _CANONICAL_RANK:
        raise ValueError(f"default must be a canonical severity, got {default!r}")

    key = (raw or "").strip().lower()
    if key in _TRANSLATION_MAP:
        return _TRANSLATION_MAP[key]

    if strict:
        raise UnknownSeverityError(
            f"unmapped severity {raw!r}; not in any registered vocabulary "
            f"({sorted(KNOWN_TOKENS)})"
        )
    return default


# ---------------------------------------------------------------------------
# Source adapters
# ---------------------------------------------------------------------------
#
# One adapter per registered vocabulary.  Each is a thin, intention-revealing
# wrapper over ``to_canonical_severity`` that documents the source and applies
# a sensible safe-floor default.  Slice 2 wires these at the ranking boundary;
# they change no existing behavior on their own.


def from_alert_prioritizer(priority: str, *, strict: bool = False) -> str:
    """Adapt an ``alert_prioritizer`` priority (critical/high/medium/ignore).

    ``ignore`` → ``INFO``; unknown → ``INFO`` (lenient).
    """
    return to_canonical_severity(priority, strict=strict, default=INFO)


def from_watchlist_alert(severity: str, *, strict: bool = False) -> str:
    """Adapt a ``watchlist_alert_payload`` severity (already five-level).

    Identity for the five canonical values; unknown → ``LOW`` to preserve the
    pre-existing watchlist fallback behavior exactly.
    """
    return to_canonical_severity(severity, strict=strict, default=LOW)


def from_delivery_ledger(severity: str, *, strict: bool = False) -> str:
    """Adapt a ``loop_delivery_service`` severity (info/warning/alert/critical).

    ``warning`` → ``MEDIUM``, ``alert`` → ``HIGH``; unknown → ``INFO`` (the
    delivery layer's existing floor default).
    """
    return to_canonical_severity(severity, strict=strict, default=INFO)


def from_briefing_ranking(severity: str, *, strict: bool = False) -> str:
    """Adapt a ``morning_brief_service`` severity (critical/high/medium/low/"").

    Empty string → ``INFO``; unknown → ``INFO`` (lenient).  Reserved for the
    Slice 3+ briefing ranking, which will emit canonical values directly.
    """
    return to_canonical_severity(severity, strict=strict, default=INFO)
