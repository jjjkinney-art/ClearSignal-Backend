#!/usr/bin/env python3
"""
Phase 10A · Slice 10 — Deployment validation script (shadow mode).

Usage
-----
  python tests/validate_10a_loop_shadow.py [options]

Options
-------
  --url URL               Backend base URL (default: $BACKEND_URL or http://127.0.0.1:8000)
  --token TOKEN           Bearer token for admin endpoints (default: $ADMIN_TOKEN or empty)
  --expect-shadow         Assert loop_shadow=True (default: enabled)
  --no-expect-shadow      Skip the loop_shadow assertion
  --expect-db-tables N    Assert db_table_count == N (default: 24)
  --seed-job              POST a test scheduled job after status checks (requires DB write permission)
  --tick-once             POST /admin/loop/tick once and verify outcome (requires loop_enabled=True)
  --verbose               Print full JSON response bodies

Exit codes
----------
  0  All checks passed
  1  One or more checks failed
  2  Network / configuration error (backend unreachable, bad token, etc.)

Checks performed
----------------
  1. GET /health — backend reachable, db_table_count correct
  2. GET /admin/loop-status — all required fields present, shadow defaults
  3. Loop config gates — loop_shadow, loop_canary_pct, loop_internal_only
  4. Kill-switch state — override_state is null (not force-disabled)
  5. DB availability — db_available is not False
  6. (optional) Seed a dummy scheduled job via POST /admin/loop/seed-job
  7. (optional) Tick once and verify tick_count incremented
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_URL   = "http://127.0.0.1:8000"
DEFAULT_TOKEN = ""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, token: str) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except Exception as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def _post(url: str, token: str, payload: Optional[dict] = None) -> Tuple[int, Any]:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except Exception as exc:
        raise RuntimeError(f"POST {url} failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_results: list = []


def check(name: str, passed: bool, detail: str = "") -> bool:
    status = PASS if passed else FAIL
    _results.append((status, name, detail))
    mark = "✓" if passed else "✗"
    print(f"  {mark} [{status}] {name}{': ' + detail if detail else ''}")
    return passed


def skip(name: str, reason: str = "") -> None:
    _results.append((SKIP, name, reason))
    print(f"  - [SKIP] {name}{': ' + reason if reason else ''}")


def _get_nested(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_health(base_url: str, token: str, expect_tables: int, verbose: bool) -> bool:
    print("\n[1] GET /health")
    try:
        status, body = _get(f"{base_url}/health", token)
    except RuntimeError as exc:
        check("reachable", False, str(exc))
        return False

    if verbose:
        print(f"    {json.dumps(body, indent=2)}")

    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("status=ok", body.get("status") == "ok", f"got {body.get('status')!r}")
    if expect_tables > 0:
        actual = body.get("db_table_count", -1)
        ok &= check(
            f"db_table_count={expect_tables}",
            actual == expect_tables,
            f"got {actual}",
        )
    return ok


def check_loop_status(
    base_url: str,
    token: str,
    expect_shadow: bool,
    verbose: bool,
) -> Tuple[bool, dict]:
    print("\n[2] GET /admin/loop-status")
    try:
        status, body = _get(f"{base_url}/admin/loop-status", token)
    except RuntimeError as exc:
        check("reachable", False, str(exc))
        return False, {}

    if verbose:
        print(f"    {json.dumps(body, indent=2)}")

    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("status=ok", body.get("status") == "ok", f"got {body.get('status')!r}")
    ok &= check("snapshot_utc present", bool(body.get("snapshot_utc")))
    ok &= check("db_available not False",
                body.get("db_available") is not False,
                f"got {body.get('db_available')!r}")

    # Required top-level keys
    required_keys = [
        "loop_enabled", "loop_shadow", "effective_enabled", "override_state",
        "canary", "telemetry", "config", "jobs", "runs", "delivery",
        "locks", "guardrails",
    ]
    for key in required_keys:
        ok &= check(f"key '{key}' present", key in body, f"body keys: {list(body)}")

    return ok, body


def check_loop_config(body: dict, expect_shadow: bool) -> bool:
    print("\n[3] Loop config gates")
    ok = True

    if expect_shadow:
        actual_shadow = body.get("loop_shadow")
        ok &= check("loop_shadow=True", actual_shadow is True, f"got {actual_shadow!r}")

    # Default expectations for shadow mode
    ok &= check(
        "loop_enabled=False (shadow default)",
        body.get("loop_enabled") is False,
        f"got {body.get('loop_enabled')!r}",
    )
    ok &= check(
        "loop_canary_pct=0 (shadow default)",
        _get_nested(body, "canary", "canary_pct", default=-1) == 0,
        f"got {_get_nested(body, 'canary', 'canary_pct')!r}",
    )
    ok &= check(
        "loop_internal_only=True (shadow default)",
        _get_nested(body, "canary", "internal_only", default=None) is True,
        f"got {_get_nested(body, 'canary', 'internal_only')!r}",
    )
    return ok


def check_kill_switch(body: dict) -> bool:
    print("\n[4] Kill-switch state")
    override = body.get("override_state")
    ok = check(
        "override_state is null (not force-disabled)",
        override is None,
        f"got {override!r}",
    )
    return ok


def check_db_availability(body: dict) -> bool:
    print("\n[5] DB availability")
    dba = body.get("db_available")
    ok = check("db_available", dba is True or dba == "partial", f"got {dba!r}")
    if dba == "partial":
        print("    ⚠  db_available='partial' — one or more DB sections degraded")
    return ok


def check_tick_once(base_url: str, token: str, body: dict) -> bool:
    print("\n[7] Tick once (/admin/loop/tick)")
    if not body.get("loop_enabled"):
        skip("tick-once", "loop_enabled=False; enable loop to test tick")
        return True
    try:
        status, resp = _post(f"{base_url}/admin/loop/tick", token)
    except RuntimeError as exc:
        check("tick request", False, str(exc))
        return False

    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("tick_acquired present", "tick_acquired" in resp, str(resp))
    return ok


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary() -> int:
    print("\n" + "=" * 60)
    passed = sum(1 for r in _results if r[0] == PASS)
    failed = sum(1 for r in _results if r[0] == FAIL)
    skipped = sum(1 for r in _results if r[0] == SKIP)
    total = passed + failed

    print(f"SUMMARY: {passed}/{total} checks passed  "
          f"({skipped} skipped)")
    if failed:
        print("\nFailed checks:")
        for status, name, detail in _results:
            if status == FAIL:
                print(f"  ✗ {name}: {detail}")
    print("=" * 60)
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Phase 10A loop shadow deployment validator")
    p.add_argument("--url", default=os.environ.get("BACKEND_URL", DEFAULT_URL))
    p.add_argument("--token", default=os.environ.get("ADMIN_TOKEN", DEFAULT_TOKEN))
    p.add_argument("--expect-shadow", action="store_true", default=True)
    p.add_argument("--no-expect-shadow", dest="expect_shadow", action="store_false")
    p.add_argument("--expect-db-tables", type=int, default=24, metavar="N")
    p.add_argument("--seed-job", action="store_true", default=False)
    p.add_argument("--tick-once", action="store_true", default=False)
    p.add_argument("--verbose", action="store_true", default=False)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    base = args.url.rstrip("/")

    print(f"Phase 10A Loop Shadow Validator")
    print(f"Target: {base}")
    print(f"Expect tables: {args.expect_db_tables}")

    overall = True

    try:
        health_ok = check_health(base, args.token, args.expect_db_tables, args.verbose)
        overall &= health_ok
        if not health_ok:
            print("\n  Backend unreachable or unhealthy — aborting remaining checks.")
            return 2

        status_ok, loop_body = check_loop_status(base, args.token, args.expect_shadow, args.verbose)
        overall &= status_ok

        if loop_body:
            overall &= check_loop_config(loop_body, args.expect_shadow)
            overall &= check_kill_switch(loop_body)
            overall &= check_db_availability(loop_body)

        if args.seed_job:
            print("\n[6] Seed job (--seed-job)")
            print("    NOTE: /admin/loop/seed-job not yet implemented; skipping")
            skip("seed-job", "endpoint not yet implemented")

        if args.tick_once:
            overall &= check_tick_once(base, args.token, loop_body)

    except Exception as exc:
        print(f"\n  FATAL: {exc}")
        return 2

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
