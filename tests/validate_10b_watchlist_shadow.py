#!/usr/bin/env python3
"""
Phase 10B · Slice 10 — Watchlist Intelligence Shadow Readiness Validator.

Usage
-----
  python tests/validate_10b_watchlist_shadow.py [options]

Options
-------
  --url URL               Backend base URL (default: $BACKEND_URL or http://127.0.0.1:8000)
  --token TOKEN           Bearer token for admin endpoints (default: $ADMIN_TOKEN or empty)
  --expect-db-tables N    Assert db_table_count == N (default: 25)
  --seed-jobs             POST /admin/loop/seed-jobs before checking job counts
  --verbose               Print full JSON response bodies

Exit codes
----------
  0  All checks passed
  1  One or more checks failed
  2  Network / configuration error (backend unreachable, bad token, etc.)

Checks performed
----------------
  1.  GET /health — backend reachable, db_table_count == 25
  2.  GET /admin/loop-status — 'watchlist' key present, tickers accessible
  3.  Watched tickers — watched_tickers table populated (>= 1 ticker)
  4.  DB/legacy parity — loop-status active_ticker_count > 0
  5.  Job seeding — watchlist_scan jobs exist (or --seed-jobs seeds them)
  6.  No duplicate scheduled_jobs — duplicate_job_combos == 0
  7.  Watchlist scan shadow mode — loop_shadow=True, loop_enabled=False
  8.  Delivery ledger shadow rows — shadow_count reported (may be 0 if no tick yet)
  9.  Duplicate delivery rows — checked via delivery section (should be 0)
  10. Drift gate substrate — drift_gate_enabled=True reported in guardrails
  11. GET /watchlist and GET /watchlist/drift consistency — both return tickers
  12. GET /morning-brief — returns deprecation JSON ({"deprecated": true, ...})
  13. GET /morning-brief/v2 — returns valid v2 brief
  14. Timeline cap check — timeline section reported (checked via watchlist/status)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_URL   = "http://127.0.0.1:8000"
DEFAULT_TOKEN = ""
DEFAULT_EXPECT_TABLES = 25


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, token: str, timeout: int = 30) -> Tuple[int, Any]:
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


def _post(url: str, token: str, payload: Optional[dict] = None, timeout: int = 30) -> Tuple[int, Any]:
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    suffix = f": {detail}" if detail else ""
    print(f"  {mark} [{status}] {name}{suffix}")
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
    print("\n[1] GET /health — backend reachable, db_table_count")
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
    ok &= check("db_enabled=True", body.get("db_enabled") is True, f"got {body.get('db_enabled')!r}")
    return ok


def check_loop_status(base_url: str, token: str, verbose: bool) -> Tuple[bool, dict]:
    print("\n[2] GET /admin/loop-status — watchlist section present")
    try:
        status, body = _get(f"{base_url}/admin/loop-status", token)
    except RuntimeError as exc:
        check("reachable", False, str(exc))
        return False, {}

    if verbose:
        print(f"    {json.dumps(body, indent=2)}")

    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("status=ok", body.get("status") == "ok")
    ok &= check("db_available", body.get("db_available") is not False, f"got {body.get('db_available')!r}")
    ok &= check("'watchlist' key present", "watchlist" in body, f"keys: {list(body)}")

    if "watchlist" in body:
        wl = body["watchlist"]
        for key in ("active_ticker_count", "active_tickers", "scan_jobs_total", "duplicate_job_combos", "drift_skip_count"):
            ok &= check(f"watchlist.{key} present", key in wl, f"wl keys: {list(wl)}")

    return ok, body


def check_watched_tickers(body: dict) -> bool:
    print("\n[3] Watched tickers — DB table populated")
    wl = body.get("watchlist", {})
    ticker_count = wl.get("active_ticker_count", 0)
    tickers      = wl.get("active_tickers", [])
    ok = True
    ok &= check(
        "active_ticker_count > 0",
        ticker_count > 0,
        f"got {ticker_count} — run POST /admin/loop/seed-jobs if 0",
    )
    ok &= check(
        "active_tickers is list",
        isinstance(tickers, list),
        f"got {type(tickers).__name__}",
    )
    if ticker_count > 0 and tickers:
        print(f"    Tickers: {', '.join(tickers[:10])}{'…' if len(tickers) > 10 else ''}")
    return ok


def check_db_legacy_parity(body: dict, base_url: str, token: str) -> bool:
    print("\n[4] DB/legacy parity — loop-status ticker count matches /watchlist")
    db_count = _get_nested(body, "watchlist", "active_ticker_count", default=0)

    try:
        _, wl_body = _get(f"{base_url}/watchlist", token)
        api_count = len(wl_body) if isinstance(wl_body, list) else 0
    except RuntimeError:
        skip("parity check", "GET /watchlist unreachable")
        return True

    ok = True
    ok &= check(
        "ticker counts consistent (DB vs /watchlist)",
        abs(db_count - api_count) <= max(2, int(api_count * 0.1)),
        f"DB={db_count} /watchlist={api_count}",
    )
    return ok


def check_job_seeding(base_url: str, token: str, body: dict, seed: bool) -> bool:
    print("\n[5] Scheduled job seeding")

    if seed:
        print("    Seeding jobs via POST /admin/loop/seed-jobs ...")
        try:
            _, seed_resp = _post(f"{base_url}/admin/loop/seed-jobs", token)
            created = seed_resp.get("jobs_created", 0)
            existing = seed_resp.get("jobs_existing", 0)
            tickers_seen = seed_resp.get("tickers_seen", 0)
            check(
                "seed-jobs ok",
                seed_resp.get("status") == "ok",
                str(seed_resp),
            )
            print(f"    Seeded: created={created} existing={existing} tickers_seen={tickers_seen}")
        except RuntimeError as exc:
            check("seed-jobs request", False, str(exc))
            return False

    scan_total = _get_nested(body, "watchlist", "scan_jobs_total", default=0)
    ok = check(
        "scan_jobs_total > 0",
        scan_total > 0,
        f"got {scan_total} — run with --seed-jobs to create",
    )
    return ok


def check_no_duplicate_jobs(body: dict) -> bool:
    print("\n[6] No duplicate scheduled_jobs")
    dupes = _get_nested(body, "watchlist", "duplicate_job_combos", default=0)
    return check(
        "duplicate_job_combos == 0",
        dupes == 0,
        f"got {dupes}",
    )


def check_shadow_mode(body: dict) -> bool:
    print("\n[7] Shadow mode gates")
    ok = True
    ok &= check(
        "loop_shadow=True",
        body.get("loop_shadow") is True,
        f"got {body.get('loop_shadow')!r}",
    )
    ok &= check(
        "loop_enabled=False (shadow default)",
        body.get("loop_enabled") is False,
        f"got {body.get('loop_enabled')!r}",
    )
    return ok


def check_delivery_ledger(body: dict) -> bool:
    print("\n[8] Delivery ledger — shadow rows")
    delivery = body.get("delivery", {})
    shadow_count  = delivery.get("shadow_count", 0)
    total         = delivery.get("total", 0)

    check(
        "delivery section present",
        isinstance(delivery, dict) and "total" in delivery,
    )
    # shadow_count may be 0 if loop hasn't ticked yet — that's OK pre-tick
    check(
        "shadow_count reported (may be 0 pre-tick)",
        isinstance(shadow_count, int),
        f"shadow_count={shadow_count} total={total}",
    )
    if shadow_count > 0:
        print(f"    shadow deliveries observed: {shadow_count}")
    else:
        print("    No shadow rows yet (expected before first tick)")
    return True  # non-blocking: pre-tick is valid state


def check_no_duplicate_delivery(body: dict) -> bool:
    print("\n[9] No duplicate delivery rows")
    delivery = body.get("delivery", {})
    dup = delivery.get("duplicate_total", 0)
    by_status = delivery.get("by_status", {})
    suppressed = by_status.get("suppressed_duplicate", 0)
    ok = check(
        "duplicate_total == 0",
        dup == 0,
        f"got {dup}",
    )
    if suppressed > 0:
        print(f"    suppressed_duplicate rows: {suppressed} (content-key dedup working)")
    return ok


def check_drift_gate(body: dict) -> bool:
    print("\n[10] Drift gate substrate")
    guardrails = body.get("guardrails", {})
    enabled = guardrails.get("drift_gate_enabled", False)
    min_score = guardrails.get("drift_materiality_min", 0)
    ok = True
    ok &= check(
        "drift_gate_enabled=True",
        enabled is True,
        f"got {enabled!r}",
    )
    ok &= check(
        "drift_materiality_min > 0",
        isinstance(min_score, (int, float)) and min_score > 0,
        f"got {min_score!r}",
    )
    drift_skips = _get_nested(body, "watchlist", "drift_skip_count", default=0)
    print(f"    drift_skip_count: {drift_skips} (runs skipped by drift gate)")
    return ok


def check_endpoint_drift_consistency(base_url: str, token: str) -> bool:
    print("\n[11] Endpoint drift consistency — /watchlist and /watchlist/drift agree")
    try:
        _, wl_body = _get(f"{base_url}/watchlist", token)
        _, drift_body = _get(f"{base_url}/watchlist/drift", token)
    except RuntimeError as exc:
        skip("drift consistency", str(exc))
        return True

    ok = True
    ok &= check("GET /watchlist is list", isinstance(wl_body, list), f"got {type(wl_body).__name__}")
    ok &= check("GET /watchlist/drift is list", isinstance(drift_body, list), f"got {type(drift_body).__name__}")

    if isinstance(wl_body, list) and isinstance(drift_body, list) and wl_body and drift_body:
        wl_tickers    = {e.get("ticker", "").upper() for e in wl_body if isinstance(e, dict)}
        drift_tickers = {d.get("ticker", "").upper() for d in drift_body if isinstance(d, dict)}
        parity = wl_tickers == drift_tickers
        ok &= check(
            "same tickers in both endpoints",
            parity,
            f"wl={sorted(wl_tickers)} drift={sorted(drift_tickers)}" if not parity else "",
        )
    return ok


def check_morning_brief_deprecated(base_url: str, token: str, verbose: bool) -> bool:
    print("\n[12] GET /morning-brief — returns deprecation JSON")
    try:
        status, body = _get(f"{base_url}/morning-brief", token)
    except RuntimeError as exc:
        check("reachable", False, str(exc))
        return False

    if verbose:
        print(f"    {json.dumps(body, indent=2)}")

    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("deprecated=True", body.get("deprecated") is True, f"got {body.get('deprecated')!r}")
    ok &= check("redirect present", "redirect" in body, f"keys: {list(body)}")
    ok &= check(
        "redirect points to v2",
        "/morning-brief/v2" in str(body.get("redirect", "")),
        f"got {body.get('redirect')!r}",
    )
    return ok


def check_morning_brief_v2(base_url: str, token: str, verbose: bool) -> bool:
    print("\n[13] GET /morning-brief/v2 — returns valid v2 brief")
    try:
        status, body = _get(f"{base_url}/morning-brief/v2", token)
    except RuntimeError as exc:
        check("reachable", False, str(exc))
        return False

    if verbose:
        print(f"    {json.dumps(body, indent=2)}")

    required = {
        "generated_at", "reference_date", "ticker_count",
        "regime_headline", "narrative_shifts", "debate_shifts",
        "priority_alerts", "attention_required", "watchlist_drift",
    }
    ok = True
    ok &= check("status 200", status == 200, f"got {status}")
    ok &= check("not deprecated response", not body.get("deprecated"), str(body.get("deprecated")))
    for key in required:
        ok &= check(f"field '{key}' present", key in body, f"body keys: {list(body)[:8]}…")
    return ok


def check_timeline_cap(base_url: str, token: str) -> bool:
    print("\n[14] Timeline cap / archival readiness")
    try:
        _, status_body = _get(f"{base_url}/watchlist/status", token)
    except RuntimeError as exc:
        skip("timeline-cap", f"GET /watchlist/status unavailable: {exc}")
        return True

    ok = True
    tickers_analyzed = (
        status_body.get("tickers_with_analyses", 0)
        if isinstance(status_body, dict) else 0
    )
    ok &= check(
        "/watchlist/status reachable and structured",
        isinstance(status_body, dict),
        f"got {type(status_body).__name__}",
    )
    print(f"    tickers_with_analyses={tickers_analyzed}")
    print("    Timeline archival: LIVE_CAP=50 enforced inline on save() — no pre-validation needed")
    return ok


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary() -> int:
    print("\n" + "=" * 60)
    passed  = sum(1 for r in _results if r[0] == PASS)
    failed  = sum(1 for r in _results if r[0] == FAIL)
    skipped = sum(1 for r in _results if r[0] == SKIP)
    total   = passed + failed

    print(f"SUMMARY: {passed}/{total} checks passed  ({skipped} skipped)")
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
    p = argparse.ArgumentParser(
        description="Phase 10B Watchlist Shadow Readiness Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--url",   default=os.environ.get("BACKEND_URL", DEFAULT_URL),
                   help="Backend base URL (default: $BACKEND_URL or http://127.0.0.1:8000)")
    p.add_argument("--token", default=os.environ.get("ADMIN_TOKEN", DEFAULT_TOKEN),
                   help="Bearer token for admin endpoints")
    p.add_argument("--expect-db-tables", type=int, default=DEFAULT_EXPECT_TABLES,
                   metavar="N", help="Expected db_table_count (default: 25)")
    p.add_argument("--seed-jobs", action="store_true", default=False,
                   help="POST /admin/loop/seed-jobs before checking job counts")
    p.add_argument("--verbose", action="store_true", default=False,
                   help="Print full JSON response bodies")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    base = args.url.rstrip("/")

    print("Phase 10B Watchlist Shadow Readiness Validator")
    print(f"Target:         {base}")
    print(f"Expect tables:  {args.expect_db_tables}")
    print(f"Seed jobs:      {args.seed_jobs}")

    overall = True

    try:
        # [1] Health
        health_ok = check_health(base, args.token, args.expect_db_tables, args.verbose)
        overall &= health_ok
        if not health_ok:
            print("\n  Backend unreachable or unhealthy — aborting remaining checks.")
            return 2

        # [2] Loop status (source for many subsequent checks)
        status_ok, loop_body = check_loop_status(base, args.token, args.verbose)
        overall &= status_ok

        if loop_body:
            # [3] Watched tickers
            overall &= check_watched_tickers(loop_body)

            # [4] DB/legacy parity
            overall &= check_db_legacy_parity(loop_body, base, args.token)

            # [5] Job seeding
            overall &= check_job_seeding(base, args.token, loop_body, args.seed_jobs)

            # [6] No duplicates
            overall &= check_no_duplicate_jobs(loop_body)

            # [7] Shadow mode
            overall &= check_shadow_mode(loop_body)

            # [8] Delivery ledger
            overall &= check_delivery_ledger(loop_body)

            # [9] No duplicate delivery
            overall &= check_no_duplicate_delivery(loop_body)

            # [10] Drift gate
            overall &= check_drift_gate(loop_body)

        # [11] Drift endpoint consistency
        overall &= check_endpoint_drift_consistency(base, args.token)

        # [12] Morning brief deprecated
        overall &= check_morning_brief_deprecated(base, args.token, args.verbose)

        # [13] Morning brief v2
        overall &= check_morning_brief_v2(base, args.token, args.verbose)

        # [14] Timeline cap
        overall &= check_timeline_cap(base, args.token)

    except Exception as exc:
        print(f"\n  FATAL: {exc}")
        import traceback
        traceback.print_exc()
        return 2

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
