"""
Scenario Calibration Service — Phase 14 · Slice 9.

Measures scenario quality over time by recording observed outcomes against
stored scenarios, then computing hit-rate, transmission accuracy, portfolio
impact accuracy, stability, churn, and summary metrics.

Core rule: calibration OBSERVES scenario outcomes and NEVER changes stored
scenarios, snapshots, evidence, forecasts, convictions, or decisions.

Immutability invariant
----------------------
  record_scenario_outcome() only ever calls add_run_log() — an insert-only
  function.  No UPDATE or DELETE path exists anywhere in this module.
  This is verified by AST inspection in the calibration tests.

Realized-state vocabulary
--------------------------
  materialized — the condition in changed_assumption actually occurred
  invalidated  — one or more invalidators was triggered; condition cannot
                 apply in its original form
  unresolved   — outcome not yet determinable (too soon or ambiguous)

Metrics supported
-----------------
  hit_rate
    Fraction of binary outcomes (materialized + invalidated) where the
    scenario condition actually materialized.  Excludes unresolved outcomes.

  transmission_accuracy
    For scenario_ids with ≥2 calibration_outcome rows (primary entity +
    at least one secondary entity), what fraction had a consistent
    realized_state across all rows.  Measures whether predicted propagation
    channels carried the impact coherently.

  portfolio_impact_accuracy
    Hit rate restricted to calibration_outcome rows with entity_type="portfolio".
    Measures whether portfolio-level impact predictions matched observation.

  scenario_stability
    Fraction of distinct (entity_key, scenario_key) pairs that appear in ≥2
    assembly run_log rows — i.e. survived at least one rebuild cycle.

  scenario_churn
    Fraction of distinct (scenario_type, entity_key, scenario_key) tuples whose
    most-recent calibration_outcome row has realized_state="invalidated".
    Measures how often scenarios get invalidated rather than materializing.

  insufficient_samples
    Every metric reports this flag when its denominator falls below
    MIN_SAMPLES.  Callers must treat metrics with this flag as indicative only.

Safety invariants (SP-6)
------------------------
  - No scenario_snapshot row is read for mutation or updated anywhere.
  - No forecast_vector, conviction, decision, or source table is read or written.
  - No delivery_ledger or Notification row is created by this module.
  - No buy/sell, target price, or investment advice language is present.
  - Null-session safety: every function returns None / {} / [] when session is
    None without raising.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_REALIZED_STATES = frozenset({"materialized", "invalidated", "unresolved"})
BINARY_STATES             = frozenset({"materialized", "invalidated"})

MIN_SAMPLES: int = 10

# Number of days in default rolling windows
DEFAULT_WINDOW_DAYS: int = 30

CALIBRATION_SCHEMA_VERSION: int = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------

def _calibration_enabled(run_override: Optional[bool] = None) -> bool:
    """Return True when scenario_calibration_enabled is set.

    run_override=True  → always enabled (test/admin seam).
    run_override=False → always disabled.
    run_override=None  → consult settings flags.
    """
    if run_override is not None:
        return bool(run_override)
    try:
        from app.config import settings
        return bool(getattr(settings, "scenario_calibration_enabled", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# record_scenario_outcome
# ---------------------------------------------------------------------------

async def record_scenario_outcome(
    session,
    *,
    scenario_id: Optional[str] = None,
    scenario_type: str = "",
    entity_type: str = "",
    entity_key: str = "",
    realized_state: str,
    snapshot_reason: str = "calibration_outcome",
    user_id: Optional[str] = None,
    evaluated_at: Optional[datetime] = None,
    run_override: Optional[bool] = None,
) -> Optional[Any]:
    """Append one calibration_outcome row to scenario_run_log.

    This is the ONLY write path in this module.  It calls add_run_log()
    with run_reason="calibration_outcome" and the given realized_state.

    Returns the inserted ScenarioRunLog row, or None when session is None,
    flags are not set, realized_state is unsupported, or on error.

    The caller is responsible for determining the realized_state; this
    function does not make any inference about scenario quality.
    """
    if session is None:
        return None
    if realized_state not in SUPPORTED_REALIZED_STATES:
        logger.debug(
            "[scenario_calibration] unsupported realized_state %r — skipping",
            realized_state,
        )
        return None
    if not _calibration_enabled(run_override):
        return None

    try:
        from app.db.repositories.scenario_repo import add_run_log

        return await add_run_log(
            session,
            scenario_id     = scenario_id,
            scenario_type   = scenario_type,
            entity_type     = entity_type,
            entity_key      = entity_key,
            user_id         = user_id,
            run_reason      = "calibration_outcome",
            snapshot_reason = snapshot_reason,
            realized_state  = realized_state,
            evaluated_at    = evaluated_at,
        )
    except Exception as exc:
        logger.debug("[scenario_calibration] record_scenario_outcome error: %r", exc)
        return None


# ---------------------------------------------------------------------------
# Internal row fetcher
# ---------------------------------------------------------------------------

async def _fetch_calibration_rows(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 2000,
) -> List[Any]:
    """Return calibration_outcome run_log rows matching filters."""
    if session is None:
        return []
    try:
        from app.db.repositories.scenario_repo import list_run_logs

        return await list_run_logs(
            session,
            run_reason       = "calibration_outcome",
            scenario_type    = scenario_type,
            entity_type      = entity_type,
            evaluated_after  = evaluated_after,
            limit            = limit,
        )
    except Exception as exc:
        logger.debug("[scenario_calibration] _fetch_calibration_rows error: %r", exc)
        return []


async def _fetch_assembly_rows(
    session,
    *,
    scenario_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    limit: int = 2000,
) -> List[Any]:
    """Return assembly run_log rows matching filters."""
    if session is None:
        return []
    try:
        from app.db.repositories.scenario_repo import list_run_logs

        return await list_run_logs(
            session,
            run_reason       = "assembly",
            scenario_type    = scenario_type,
            evaluated_after  = evaluated_after,
            limit            = limit,
        )
    except Exception as exc:
        logger.debug("[scenario_calibration] _fetch_assembly_rows error: %r", exc)
        return []


def _state(row: Any) -> Optional[str]:
    """Read realized_state from an ORM row or dict."""
    if isinstance(row, dict):
        return row.get("realized_state")
    return getattr(row, "realized_state", None)


def _attr(row: Any, name: str) -> Optional[str]:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


# ---------------------------------------------------------------------------
# calculate_scenario_hit_rate
# ---------------------------------------------------------------------------

async def calculate_scenario_hit_rate(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Compute hit rate from calibration_outcome run_log rows.

    hit_rate = materialized / (materialized + invalidated)

    Excludes unresolved outcomes from the denominator.

    Returns:
        hit_rate             float or None  — None if insufficient_samples
        materialized         int
        invalidated          int
        unresolved           int
        total_evaluated      int
        insufficient_samples bool
        scenario_type        str or None
        entity_type          str or None
    """
    empty: Dict[str, Any] = {
        "hit_rate":            None,
        "materialized":        0,
        "invalidated":         0,
        "unresolved":          0,
        "total_evaluated":     0,
        "insufficient_samples": True,
        "scenario_type":       scenario_type,
        "entity_type":         entity_type,
    }
    if session is None:
        return empty

    try:
        rows = await _fetch_calibration_rows(
            session,
            scenario_type   = scenario_type,
            entity_type     = entity_type,
            evaluated_after = evaluated_after,
        )
        if not rows:
            return empty

        materialized = sum(1 for r in rows if _state(r) == "materialized")
        invalidated  = sum(1 for r in rows if _state(r) == "invalidated")
        unresolved   = sum(1 for r in rows if _state(r) == "unresolved")
        binary_total = materialized + invalidated
        insufficient = binary_total < min_samples

        hit_rate = (
            round(materialized / binary_total, 4)
            if binary_total > 0 and not insufficient
            else None
        )

        return {
            "hit_rate":            hit_rate,
            "materialized":        materialized,
            "invalidated":         invalidated,
            "unresolved":          unresolved,
            "total_evaluated":     len(rows),
            "insufficient_samples": insufficient,
            "scenario_type":       scenario_type,
            "entity_type":         entity_type,
        }
    except Exception as exc:
        logger.debug("[scenario_calibration] calculate_scenario_hit_rate error: %r", exc)
        return empty


# ---------------------------------------------------------------------------
# calculate_transmission_accuracy
# ---------------------------------------------------------------------------

async def calculate_transmission_accuracy(
    session,
    *,
    scenario_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Compute transmission accuracy from calibration_outcome rows.

    For each scenario_id with ≥2 calibration_outcome rows (primary entity +
    at least one secondary entity), checks whether all rows share the same
    realized_state.  Consistent state means the predicted propagation channels
    carried the impact coherently.

    transmission_accuracy = consistent_scenarios / total_multi_entity_scenarios

    Returns:
        transmission_accuracy     float or None
        consistent_scenarios      int
        total_multi_entity_scenarios int
        insufficient_samples      bool
        scenario_type             str or None
    """
    empty: Dict[str, Any] = {
        "transmission_accuracy":          None,
        "consistent_scenarios":           0,
        "total_multi_entity_scenarios":   0,
        "insufficient_samples":           True,
        "scenario_type":                  scenario_type,
    }
    if session is None:
        return empty

    try:
        rows = await _fetch_calibration_rows(
            session,
            scenario_type   = scenario_type,
            evaluated_after = evaluated_after,
        )
        if not rows:
            return empty

        # Group by scenario_id
        by_scenario: Dict[str, List[str]] = {}
        for row in rows:
            sid = _attr(row, "scenario_id")
            if not sid:
                continue
            state = _state(row)
            if state is None:
                continue
            by_scenario.setdefault(sid, []).append(state)

        # Only scenarios with ≥2 outcome rows are meaningful for transmission
        multi = {sid: states for sid, states in by_scenario.items() if len(states) >= 2}
        total_multi = len(multi)

        if total_multi < min_samples:
            return {**empty, "total_multi_entity_scenarios": total_multi}

        consistent = sum(
            1 for states in multi.values()
            if len(set(states)) == 1  # all same state
        )

        return {
            "transmission_accuracy":        round(consistent / total_multi, 4),
            "consistent_scenarios":         consistent,
            "total_multi_entity_scenarios": total_multi,
            "insufficient_samples":         False,
            "scenario_type":                scenario_type,
        }
    except Exception as exc:
        logger.debug(
            "[scenario_calibration] calculate_transmission_accuracy error: %r", exc
        )
        return empty


# ---------------------------------------------------------------------------
# calculate_portfolio_impact_accuracy
# ---------------------------------------------------------------------------

async def calculate_portfolio_impact_accuracy(
    session,
    *,
    scenario_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Hit rate restricted to calibration_outcome rows with entity_type='portfolio'.

    portfolio_hit_rate = portfolio_materialized / (portfolio_materialized + portfolio_invalidated)

    Returns:
        portfolio_hit_rate        float or None
        portfolio_materialized    int
        portfolio_invalidated     int
        portfolio_unresolved      int
        total_portfolio_evaluated int
        insufficient_samples      bool
        scenario_type             str or None
    """
    empty: Dict[str, Any] = {
        "portfolio_hit_rate":         None,
        "portfolio_materialized":     0,
        "portfolio_invalidated":      0,
        "portfolio_unresolved":       0,
        "total_portfolio_evaluated":  0,
        "insufficient_samples":       True,
        "scenario_type":              scenario_type,
    }
    if session is None:
        return empty

    try:
        rows = await _fetch_calibration_rows(
            session,
            scenario_type   = scenario_type,
            entity_type     = "portfolio",
            evaluated_after = evaluated_after,
        )
        if not rows:
            return empty

        materialized = sum(1 for r in rows if _state(r) == "materialized")
        invalidated  = sum(1 for r in rows if _state(r) == "invalidated")
        unresolved   = sum(1 for r in rows if _state(r) == "unresolved")
        binary_total = materialized + invalidated
        insufficient = binary_total < min_samples

        hit_rate = (
            round(materialized / binary_total, 4)
            if binary_total > 0 and not insufficient
            else None
        )

        return {
            "portfolio_hit_rate":         hit_rate,
            "portfolio_materialized":     materialized,
            "portfolio_invalidated":      invalidated,
            "portfolio_unresolved":       unresolved,
            "total_portfolio_evaluated":  len(rows),
            "insufficient_samples":       insufficient,
            "scenario_type":              scenario_type,
        }
    except Exception as exc:
        logger.debug(
            "[scenario_calibration] calculate_portfolio_impact_accuracy error: %r", exc
        )
        return empty


# ---------------------------------------------------------------------------
# calculate_scenario_stability
# ---------------------------------------------------------------------------

async def calculate_scenario_stability(
    session,
    *,
    scenario_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Measure how often scenarios survive rebuild cycles.

    A scenario (entity_key, scenario_key) is "stable" when it appears in
    ≥2 assembly run_log rows — it was rebuilt at least once, meaning the
    condition was still considered valid on a subsequent evaluation pass.

    stability = stable_pairs / total_distinct_pairs

    Returns:
        stability            float or None
        stable_pairs         int   — pairs with ≥2 assembly rows
        single_run_pairs     int   — pairs that appeared only once
        total_distinct_pairs int
        insufficient_samples bool
        scenario_type        str or None
    """
    empty: Dict[str, Any] = {
        "stability":            None,
        "stable_pairs":         0,
        "single_run_pairs":     0,
        "total_distinct_pairs": 0,
        "insufficient_samples": True,
        "scenario_type":        scenario_type,
    }
    if session is None:
        return empty

    try:
        rows = await _fetch_assembly_rows(
            session,
            scenario_type   = scenario_type,
            evaluated_after = evaluated_after,
        )
        if not rows:
            return empty

        # Count assembly rows per (entity_key, scenario_key) pair
        pair_counts: Dict[tuple, int] = {}
        for row in rows:
            entity_key   = _attr(row, "entity_key")   or ""
            scenario_key = _attr(row, "snapshot_reason") or ""
            # snapshot_reason carries the scenario key in assembly rows
            pair = (entity_key, scenario_key)
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        total  = len(pair_counts)
        stable = sum(1 for c in pair_counts.values() if c >= 2)
        single = total - stable
        insufficient = total < min_samples

        stability = (
            round(stable / total, 4)
            if total > 0 and not insufficient
            else None
        )

        return {
            "stability":            stability,
            "stable_pairs":         stable,
            "single_run_pairs":     single,
            "total_distinct_pairs": total,
            "insufficient_samples": insufficient,
            "scenario_type":        scenario_type,
        }
    except Exception as exc:
        logger.debug(
            "[scenario_calibration] calculate_scenario_stability error: %r", exc
        )
        return empty


# ---------------------------------------------------------------------------
# calculate_scenario_churn
# ---------------------------------------------------------------------------

async def calculate_scenario_churn(
    session,
    *,
    scenario_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Measure the rate at which scenarios are ultimately invalidated.

    For each distinct (scenario_type, entity_key, snapshot_reason) tuple
    with at least one calibration_outcome row, churn counts those whose
    most-recent calibration_outcome has realized_state="invalidated".

    churn_rate = invalidated_tuples / total_tuples

    Returns:
        churn_rate           float or None
        invalidated_tuples   int
        total_tuples         int
        insufficient_samples bool
        scenario_type        str or None
    """
    empty: Dict[str, Any] = {
        "churn_rate":          None,
        "invalidated_tuples":  0,
        "total_tuples":        0,
        "insufficient_samples": True,
        "scenario_type":       scenario_type,
    }
    if session is None:
        return empty

    try:
        rows = await _fetch_calibration_rows(
            session,
            scenario_type   = scenario_type,
            evaluated_after = evaluated_after,
        )
        if not rows:
            return empty

        # list_run_logs returns evaluated_at DESC — first occurrence per tuple
        # is the most-recent row for that tuple.
        seen: set = set()
        last_state: Dict[tuple, str] = {}
        for row in rows:
            stype    = _attr(row, "scenario_type")    or ""
            ekey     = _attr(row, "entity_key")       or ""
            sreason  = _attr(row, "snapshot_reason")  or ""
            tup      = (stype, ekey, sreason)
            if tup not in seen:
                seen.add(tup)
                state = _state(row)
                if state:
                    last_state[tup] = state

        total      = len(last_state)
        invalidated = sum(1 for s in last_state.values() if s == "invalidated")
        insufficient = total < min_samples

        churn_rate = (
            round(invalidated / total, 4)
            if total > 0 and not insufficient
            else None
        )

        return {
            "churn_rate":          churn_rate,
            "invalidated_tuples":  invalidated,
            "total_tuples":        total,
            "insufficient_samples": insufficient,
            "scenario_type":       scenario_type,
        }
    except Exception as exc:
        logger.debug(
            "[scenario_calibration] calculate_scenario_churn error: %r", exc
        )
        return empty


# ---------------------------------------------------------------------------
# summarize_scenario_calibration
# ---------------------------------------------------------------------------

async def summarize_scenario_calibration(
    session,
    *,
    scenario_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    evaluated_after: Optional[datetime] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_samples: int = MIN_SAMPLES,
) -> Dict[str, Any]:
    """Aggregate all calibration metrics into one summary dict.

    Calls all individual metric functions and combines their results.
    When session is None, returns a safe empty summary with db_available=False.
    Never raises.

    Returns:
        hit_rate_metrics              dict
        transmission_accuracy_metrics dict
        portfolio_impact_metrics      dict
        stability_metrics             dict
        churn_metrics                 dict
        db_available                  bool
        safe_state                    bool
        scenario_type                 str or None
        entity_type                   str or None
        schema_version                int
    """
    safe_empty: Dict[str, Any] = {
        "hit_rate_metrics":              {},
        "transmission_accuracy_metrics": {},
        "portfolio_impact_metrics":      {},
        "stability_metrics":             {},
        "churn_metrics":                 {},
        "db_available":                  False,
        "safe_state":                    True,
        "scenario_type":                 scenario_type,
        "entity_type":                   entity_type,
        "schema_version":                CALIBRATION_SCHEMA_VERSION,
    }
    if session is None:
        return safe_empty

    try:
        # Use evaluated_after from window_days if not supplied
        after = evaluated_after
        if after is None and window_days > 0:
            after = _now() - timedelta(days=window_days)

        hit_rate_metrics = await calculate_scenario_hit_rate(
            session,
            scenario_type   = scenario_type,
            entity_type     = entity_type,
            evaluated_after = after,
            min_samples     = min_samples,
        )
        transmission_metrics = await calculate_transmission_accuracy(
            session,
            scenario_type   = scenario_type,
            evaluated_after = after,
            min_samples     = min_samples,
        )
        portfolio_metrics = await calculate_portfolio_impact_accuracy(
            session,
            scenario_type   = scenario_type,
            evaluated_after = after,
            min_samples     = min_samples,
        )
        stability_metrics = await calculate_scenario_stability(
            session,
            scenario_type   = scenario_type,
            evaluated_after = after,
            min_samples     = min_samples,
        )
        churn_metrics = await calculate_scenario_churn(
            session,
            scenario_type   = scenario_type,
            evaluated_after = after,
            min_samples     = min_samples,
        )

        return {
            "hit_rate_metrics":              hit_rate_metrics,
            "transmission_accuracy_metrics": transmission_metrics,
            "portfolio_impact_metrics":      portfolio_metrics,
            "stability_metrics":             stability_metrics,
            "churn_metrics":                 churn_metrics,
            "db_available":                  True,
            "safe_state":                    True,
            "scenario_type":                 scenario_type,
            "entity_type":                   entity_type,
            "schema_version":                CALIBRATION_SCHEMA_VERSION,
        }
    except Exception as exc:
        logger.debug("[scenario_calibration] summarize_scenario_calibration error: %r", exc)
        return {**safe_empty, "db_available": True}
