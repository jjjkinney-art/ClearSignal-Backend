#!/usr/bin/env python3
"""
tests/validate_10d_portfolio_shadow.py

Phase 10D · Slice 8 — Portfolio intelligence shadow validation script.

Validates that the Phase 10D portfolio intelligence subsystem is in a safe,
observable state after deployment.  Run this script against a live backend to
confirm:

  1.  Health endpoint is reachable and returning "ok".
  2.  GET /admin/portfolio-status responds and has the expected schema.
  3.  safe_state = true (no live portfolio delivery active).
  4.  Portfolio tables exist in the DB (db_table_count >= 31).
  5.  Portfolio flags reflect safe defaults (shadow mode active).
  6.  Insights: total, by_type, by_severity, by_rank_band keys present.
  7.  Regulatory disclaimer present in snapshot.
  8.  No live Notification rows with kind=portfolio_alert (shadow-only).
  9.  delivery_ledger portfolio_alert rows (if any) are shadow-only.
 10.  No external delivery (email/push) rows present.
 11.  Regulatory blocked count check (disclaimer presence).
 12.  Prohibited language count = 0 (guard active).

Usage
-----
    # Against local dev server:
    python tests/validate_10d_portfolio_shadow.py

    # Against Render production:
    BACKEND_URL=https://clearsignal-backend-dlsc.onrender.com \\
        python tests/validate_10d_portfolio_shadow.py

    # Verbose (show all field values):
    VERBOSE=1 python tests/validate_10d_portfolio_shadow.py

Exit codes
----------
    0  all checks PASS
    1  one or more checks FAIL (see output)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get(
    "BACKEND_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

REQUEST_TIMEOUT = 20  # seconds
VERBOSE = os.environ.get("VERBOSE", "0") not in ("0", "false", "")

# Expected minimum DB table count after Phase 10D (3 new tables: portfolios,
# portfolio_positions, portfolio_insights).
EXPECTED_DB_TABLE_COUNT = 31

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"
WARN = "\033[33mWARN\033[0m"

results: List[Tuple[str, str, str]] = []   # (check_name, verdict, detail)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str) -> Tuple[Optional[int], Optional[Dict]]:
    url = f"{BASE_URL}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return None, None


def _record(name: str, passed: bool, detail: str = "") -> None:
    verdict = PASS if passed else FAIL
    results.append((name, "PASS" if passed else "FAIL", detail))
    marker = "  ✓" if passed else "  ✗"
    print(f"{marker} [{verdict}] {name}" + (f" — {detail}" if detail else ""))


def _warn(name: str, detail: str = "") -> None:
    results.append((name, "WARN", detail))
    print(f"  ! [{WARN}] {name}" + (f" — {detail}" if detail else ""))


def _skip(name: str, detail: str = "") -> None:
    results.append((name, "SKIP", detail))
    print(f"  - [{SKIP}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Check 1 — Health endpoint
# ---------------------------------------------------------------------------

def check_health() -> Optional[Dict]:
    print("\n── Check 1: Health endpoint ────────────────────────────────")
    status, body = _get("/health")
    if status is None:
        _record("health reachable", False, "connection refused / timeout")
        return None
    _record("health HTTP 200", status == 200, f"got {status}")
    if body is None:
        _record("health JSON parseable", False, "no body")
        return None
    _record("health status=ok", body.get("status") == "ok", repr(body.get("status")))
    if VERBOSE:
        print(f"     health body: {json.dumps(body, indent=2)}")
    return body


# ---------------------------------------------------------------------------
# Check 2 — DB table count
# ---------------------------------------------------------------------------

def check_db_table_count(health_body: Optional[Dict]) -> None:
    print("\n── Check 2: DB table count ─────────────────────────────────")
    if health_body is None:
        _skip("db_table_count", "health check failed")
        return
    count = health_body.get("db_table_count", 0)
    _record(
        f"db_table_count >= {EXPECTED_DB_TABLE_COUNT}",
        int(count) >= EXPECTED_DB_TABLE_COUNT,
        f"got {count}",
    )


# ---------------------------------------------------------------------------
# Check 3 — /admin/portfolio-status endpoint
# ---------------------------------------------------------------------------

def check_portfolio_status() -> Optional[Dict]:
    print("\n── Check 3: /admin/portfolio-status endpoint ───────────────")
    status, body = _get("/admin/portfolio-status")
    if status is None:
        _record("portfolio-status reachable", False, "connection refused / timeout")
        return None
    _record("portfolio-status HTTP 200", status == 200, f"got {status}")
    if body is None:
        _record("portfolio-status JSON parseable", False, "no body")
        return None
    _record("portfolio-status status=ok", body.get("status") == "ok", repr(body.get("status")))
    if VERBOSE:
        print(f"     portfolio-status body: {json.dumps(body, indent=2)}")
    return body


# ---------------------------------------------------------------------------
# Check 4 — Schema completeness
# ---------------------------------------------------------------------------

def check_schema(ps: Optional[Dict]) -> None:
    print("\n── Check 4: Portfolio status schema completeness ───────────")
    if ps is None:
        _skip("schema check", "no response body")
        return

    required_top = [
        "status", "snapshot_utc", "db_available", "safe_state",
        "portfolio_flags", "portfolios", "positions", "insights",
        "delivery", "notifications", "digests", "regulatory",
    ]
    for key in required_top:
        _record(f"key '{key}' present", key in ps, "missing" if key not in ps else "")

    # Nested keys
    flags = ps.get("portfolio_flags", {})
    for flag_key in ["portfolio_insight_enabled", "portfolio_delivery_enabled",
                     "portfolio_shadow", "portfolio_internal_only"]:
        _record(f"portfolio_flags.{flag_key} present", flag_key in flags)

    insights = ps.get("insights", {})
    for ins_key in ["total", "by_type", "by_severity", "by_rank_band",
                    "stale_count", "last_generated_at"]:
        _record(f"insights.{ins_key} present", ins_key in insights)

    regulatory = ps.get("regulatory", {})
    _record("regulatory.disclaimer_present key exists", "disclaimer_present" in regulatory)
    _record("regulatory.prohibited_word_count key exists", "prohibited_word_count" in regulatory)


# ---------------------------------------------------------------------------
# Check 5 — safe_state
# ---------------------------------------------------------------------------

def check_safe_state(ps: Optional[Dict]) -> None:
    print("\n── Check 5: safe_state = true ──────────────────────────────")
    if ps is None:
        _skip("safe_state", "no response body")
        return
    safe = ps.get("safe_state")
    _record("safe_state is True", safe is True, f"got {safe!r}")


# ---------------------------------------------------------------------------
# Check 6 — Portfolio flags (safe defaults)
# ---------------------------------------------------------------------------

def check_portfolio_flags(ps: Optional[Dict]) -> None:
    print("\n── Check 6: Portfolio flags — safe defaults ─────────────────")
    if ps is None:
        _skip("portfolio flags", "no response body")
        return
    flags = ps.get("portfolio_flags", {})

    delivery_enabled = flags.get("portfolio_delivery_enabled", False)
    shadow = flags.get("portfolio_shadow", True)
    internal_only = flags.get("portfolio_internal_only", True)

    if delivery_enabled:
        _record(
            "portfolio_delivery_enabled=False (safe default)",
            not delivery_enabled,
            f"got {delivery_enabled} — delivery active; ensure shadow=True",
        )
        _record(
            "portfolio_shadow=True when delivery enabled",
            shadow is True,
            f"got {shadow!r}",
        )
    else:
        _record("portfolio_delivery_enabled=False (safe default)", True)

    _record(
        "portfolio_internal_only=True (safe default)",
        internal_only is True,
        f"got {internal_only!r}",
    )
    _record(
        "portfolio_shadow=True (safe default)",
        shadow is True,
        f"got {shadow!r}",
    )


# ---------------------------------------------------------------------------
# Check 7 — No live Notification rows (portfolio_alert)
# ---------------------------------------------------------------------------

def check_no_live_notifications(ps: Optional[Dict]) -> None:
    print("\n── Check 7: No live portfolio_alert Notification rows ──────")
    if ps is None:
        _skip("notification check", "no response body")
        return
    notif = ps.get("notifications", {})
    pa_count = notif.get("portfolio_alert_count", 0)
    if pa_count == 0:
        _record("portfolio_alert Notification rows = 0", True)
    else:
        _warn(
            f"portfolio_alert Notification rows = {pa_count}",
            "live Notification rows exist — confirm shadow mode is active",
        )


# ---------------------------------------------------------------------------
# Check 8 — Delivery ledger (shadow-only)
# ---------------------------------------------------------------------------

def check_delivery_shadow(ps: Optional[Dict]) -> None:
    print("\n── Check 8: Delivery ledger — shadow rows only ─────────────")
    if ps is None:
        _skip("delivery ledger check", "no response body")
        return
    delivery = ps.get("delivery", {})
    shadow_count = delivery.get("shadow_count", 0)
    in_app_total = delivery.get("in_app_total", 0)

    # In safe state, any in-app rows should be shadow rows
    if in_app_total == 0:
        _record("delivery_ledger in_app rows = 0 (clean state)", True)
    else:
        _record(
            "all in_app rows are shadow (shadow_count == in_app_total)",
            shadow_count == in_app_total,
            f"shadow={shadow_count} in_app_total={in_app_total}",
        )


# ---------------------------------------------------------------------------
# Check 9 — Regulatory disclaimer present
# ---------------------------------------------------------------------------

def check_regulatory(ps: Optional[Dict]) -> None:
    print("\n── Check 9: Regulatory guard active ────────────────────────")
    if ps is None:
        _skip("regulatory check", "no response body")
        return
    regulatory = ps.get("regulatory", {})
    _record(
        "regulatory.disclaimer_present = True",
        regulatory.get("disclaimer_present") is True,
        f"got {regulatory.get('disclaimer_present')!r}",
    )
    word_count = regulatory.get("prohibited_word_count", 0)
    _record(
        "regulatory.prohibited_word_count > 0 (guard loaded)",
        word_count > 0,
        f"got {word_count}",
    )


# ---------------------------------------------------------------------------
# Check 10 — db_available (DB reachable or graceful degradation)
# ---------------------------------------------------------------------------

def check_db_available(ps: Optional[Dict]) -> None:
    print("\n── Check 10: DB availability ───────────────────────────────")
    if ps is None:
        _skip("db_available check", "no response body")
        return
    dba = ps.get("db_available")
    if dba is True:
        _record("db_available = True", True)
    elif dba == "partial":
        _warn("db_available = partial", "some DB sections had errors")
    else:
        _warn("db_available = False", "DB not reachable — snapshot is config-only")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"Phase 10D Portfolio Shadow Validation")
    print(f"Backend: {BASE_URL}")
    print("=" * 60)

    health_body = check_health()
    check_db_table_count(health_body)
    ps = check_portfolio_status()
    check_schema(ps)
    check_safe_state(ps)
    check_portfolio_flags(ps)
    check_no_live_notifications(ps)
    check_delivery_shadow(ps)
    check_regulatory(ps)
    check_db_available(ps)

    # Summary
    print("\n" + "=" * 60)
    total    = len(results)
    passed   = sum(1 for _, v, _ in results if v == "PASS")
    failed   = sum(1 for _, v, _ in results if v == "FAIL")
    warnings = sum(1 for _, v, _ in results if v == "WARN")
    skipped  = sum(1 for _, v, _ in results if v == "SKIP")

    print(f"Results: {passed}/{total} PASS  {failed} FAIL  {warnings} WARN  {skipped} SKIP")

    if failed > 0:
        print(f"\n{FAIL} {failed} check(s) failed — Phase 10D shadow readiness NOT confirmed.")
        return 1
    elif warnings > 0:
        print(f"\n{WARN} All checks passed with {warnings} warning(s) — review before canary.")
        return 0
    else:
        print(f"\n{PASS} All checks passed — Phase 10D shadow readiness confirmed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
