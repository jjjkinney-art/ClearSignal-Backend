#!/usr/bin/env python3
"""
tests/validate_10c_delivery_shadow.py

Phase 10C · Slice 10 — Delivery shadow validation script.

Validates that the Phase 10C delivery subsystem is in a safe, observable state
after deployment.  Run this script against a live backend to confirm:

  1. Health endpoint is reachable and returning "ok".
  2. GET /admin/delivery-status responds and has the expected schema.
  3. Delivery flags reflect safe defaults (shadow mode active).
  4. All 5 delivery endpoints respond (preferences, inbox, digests).
  5. Ledger rows (if any) have canonical severity values.
  6. No live Notification rows with kind="delivery" exist by default.
  7. Duplicate count is 0 in a clean deployment.
  8. Guardrail settings are non-zero / sane.

Usage
-----
    # Against local dev server (DATABASE_URL must be set in .env):
    python tests/validate_10c_delivery_shadow.py

    # Against Render production:
    BACKEND_URL=https://clearsignal-backend-dlsc.onrender.com \
        python tests/validate_10c_delivery_shadow.py

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

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"
WARN = "\033[33mWARN\033[0m"

results: List[Tuple[str, str, str]] = []   # (check_name, verdict, detail)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: str = "") -> Tuple[Optional[int], Optional[Dict]]:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + params
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        return None, None


def _check(name: str, passed: bool, detail: str = "") -> None:
    verdict = PASS if passed else FAIL
    results.append((name, "PASS" if passed else "FAIL", detail))
    symbol = "✓" if passed else "✗"
    print(f"  {symbol} [{verdict}] {name}" + (f" — {detail}" if detail else ""))


def _skip(name: str, reason: str) -> None:
    results.append((name, "SKIP", reason))
    print(f"  - [{SKIP}] {name} — {reason}")


# ---------------------------------------------------------------------------
# Check groups
# ---------------------------------------------------------------------------

def check_health():
    print("\n[1] Health endpoint")
    code, body = _get("/health")
    _check("GET /health responds 200", code == 200, f"got {code}")
    if body:
        _check("health.status == 'ok'", body.get("status") == "ok",
               f"got {body.get('status')!r}")
        _check("health.db_enabled present", "db_enabled" in body)
    else:
        _skip("health body checks", "no body returned")


def check_delivery_status():
    print("\n[2] GET /admin/delivery-status")
    code, body = _get("/admin/delivery-status")
    _check("endpoint responds 200", code == 200, f"got {code}")
    if body is None:
        _skip("delivery-status body checks", "no body returned")
        return

    _check("status == 'ok'", body.get("status") == "ok",
           f"got {body.get('status')!r}")
    _check("snapshot_utc present and non-empty",
           bool(body.get("snapshot_utc", "")))
    _check("db_available present", "db_available" in body,
           f"db_available={body.get('db_available')}")

    # Safe state
    safe = body.get("safe_state")
    _check("safe_state is True (shadow mode active)", safe is True,
           f"safe_state={safe!r}  (set DELIVERY_IN_APP_ENABLED=false or DELIVERY_SHADOW=true)")

    # Flags schema
    flags = body.get("delivery_flags", {})
    for flag in ("delivery_in_app_enabled", "delivery_shadow",
                 "delivery_internal_only", "delivery_canary_pct"):
        _check(f"delivery_flags.{flag} present", flag in flags)

    _check("delivery_flags.delivery_in_app_enabled is False (safe default)",
           flags.get("delivery_in_app_enabled") is False,
           f"got {flags.get('delivery_in_app_enabled')!r}")
    _check("delivery_flags.delivery_shadow is True (safe default)",
           flags.get("delivery_shadow") is True,
           f"got {flags.get('delivery_shadow')!r}")

    return body


def check_no_live_notifications(status_body: Optional[Dict]):
    print("\n[3] No live delivery notifications (safe state)")
    if status_body is None:
        _skip("notification checks", "delivery-status body unavailable")
        return
    notif = status_body.get("notifications", {})
    delivery_notifs = notif.get("delivery_notifications", 0)
    _check("notifications.delivery_notifications == 0 (no real delivery rows)",
           delivery_notifs == 0,
           f"got {delivery_notifs} (real Notification rows with kind='delivery')")


def check_ledger_severity_values(status_body: Optional[Dict]):
    print("\n[4] Ledger severity values canonical")
    if status_body is None:
        _skip("ledger severity checks", "delivery-status body unavailable")
        return
    ledger = status_body.get("ledger", {})
    total = ledger.get("total", 0)
    if total == 0:
        _skip("severity canonicality (no rows in ledger)", "ledger is empty")
        return

    _check(f"ledger.total > 0 ({total} rows)", total > 0)
    by_sev = ledger.get("by_severity", {})
    canonical = {"critical", "high", "medium", "low", "info", "unknown"}
    bad = set(by_sev.keys()) - canonical
    _check("all severity values canonical", len(bad) == 0,
           f"unexpected values: {bad}" if bad else "ok")


def check_duplicate_count(status_body: Optional[Dict]):
    print("\n[5] Duplicate count")
    if status_body is None:
        _skip("duplicate count check", "delivery-status body unavailable")
        return
    dup = status_body.get("duplicate_count", -1)
    _check("duplicate_count == 0 (no in-process dedup hits)", dup == 0,
           f"got {dup}")


def check_guardrails(status_body: Optional[Dict]):
    print("\n[6] Guardrail settings sane")
    if status_body is None:
        _skip("guardrail checks", "delivery-status body unavailable")
        return
    g = status_body.get("guardrails", {})
    _check("quiet_hours_start_utc in 0..23",
           0 <= g.get("quiet_hours_start_utc", -1) <= 23,
           f"got {g.get('quiet_hours_start_utc')}")
    _check("quiet_hours_end_utc in 0..23",
           0 <= g.get("quiet_hours_end_utc", -1) <= 23,
           f"got {g.get('quiet_hours_end_utc')}")
    _check("daily_cap > 0", g.get("daily_cap", 0) > 0,
           f"got {g.get('daily_cap')}")
    _check("severity_floor non-empty", bool(g.get("severity_floor", "")),
           f"got {g.get('severity_floor')!r}")
    _check("stale_threshold_hours == 72",
           g.get("stale_threshold_hours") == 72,
           f"got {g.get('stale_threshold_hours')}")


def check_delivery_endpoints():
    print("\n[7] Delivery API endpoints respond")

    # GET /delivery/preferences
    code, body = _get("/delivery/preferences")
    _check("GET /delivery/preferences responds 200", code == 200, f"got {code}")
    if body:
        _check("/delivery/preferences has channel field", "channel" in body)

    # GET /delivery/inbox
    code, body = _get("/delivery/inbox")
    _check("GET /delivery/inbox responds 200", code == 200, f"got {code}")
    if body is not None:
        _check("/delivery/inbox returns list", isinstance(body, list),
               f"got {type(body).__name__}")

    # GET /delivery/inbox/{id} — 404 expected for unknown id
    code, _ = _get("/delivery/inbox/nonexistent-delivery-id-xyz")
    _check("GET /delivery/inbox/{id} returns 404 for unknown id",
           code == 404, f"got {code}")

    # GET /delivery/digests
    code, body = _get("/delivery/digests")
    _check("GET /delivery/digests responds 200", code == 200, f"got {code}")
    if body is not None:
        _check("/delivery/digests returns list", isinstance(body, list),
               f"got {type(body).__name__}")

    # GET /delivery/digests/{batch_id} — 404 expected for unknown batch
    code, _ = _get("/delivery/digests/nonexistent-batch-id-xyz")
    _check("GET /delivery/digests/{batch_id} returns 404 for unknown batch",
           code == 404, f"got {code}")


def check_no_secrets_in_response():
    print("\n[8] No secrets in delivery-status response")
    code, body = _get("/admin/delivery-status")
    if body is None:
        _skip("no-secrets check", "no body returned")
        return
    body_str = json.dumps(body).lower()
    for secret_key in ("openai_api_key", "fmp_api_key", "database_url", "fred_api_key", "password"):
        _check(f"no {secret_key!r} in response body",
               secret_key not in body_str,
               f"FOUND in response — remove before shipping")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"\n{'=' * 60}")
    print(f"Phase 10C — Delivery Shadow Validation")
    print(f"Backend: {BASE_URL}")
    print(f"{'=' * 60}")

    check_health()
    status_body = check_delivery_status()
    check_no_live_notifications(status_body)
    check_ledger_severity_values(status_body)
    check_duplicate_count(status_body)
    check_guardrails(status_body)
    check_delivery_endpoints()
    check_no_secrets_in_response()

    # Summary
    total   = len(results)
    passed  = sum(1 for _, v, _ in results if v == "PASS")
    failed  = sum(1 for _, v, _ in results if v == "FAIL")
    skipped = sum(1 for _, v, _ in results if v == "SKIP")

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped")

    if failed:
        print("\nFAILED checks:")
        for name, verdict, detail in results:
            if verdict == "FAIL":
                print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))
        print()
        return 1

    print(f"\n{PASS} — all checks passed.  Phase 10C delivery shadow is healthy.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
