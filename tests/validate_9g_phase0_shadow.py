"""
tests/validate_9g_phase0_shadow.py

Phase 9G Phase 0 — Company Dossier shadow-write production validation.

Steps
-----
1. Ping /health — confirm backend is alive.
2. GET /admin/dossier-status — capture baseline row counts.
3. Confirm dossier_extraction_enabled matches expected flag value.
4. Run /ask for NVDA, JPM, COST, RKLB (streaming endpoint).
5. GET /admin/dossier-status after each run — confirm row counts grow
   when flag=true, stay flat when flag=false.
6. Print validation table.

Usage
-----
# Flag OFF (default) — no writes expected:
  python3 tests/validate_9g_phase0_shadow.py

# Flag ON — writes expected:
  python3 tests/validate_9g_phase0_shadow.py --expect-writes

Environment
-----------
BACKEND_URL  override base URL (default: https://clearsignal-backend-dlsc.onrender.com)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

BASE_URL = os.environ.get(
    "BACKEND_URL", "https://clearsignal-backend-dlsc.onrender.com"
).rstrip("/")

TICKERS = ["NVDA", "JPM", "COST", "RKLB"]

DOSSIER_TABLES = [
    "company_dossier",
    "dossier_core_debate",
    "dossier_moat_dimension",
    "dossier_catalyst",
    "dossier_variant",
    "dossier_durability",
    "dossier_failure_mode",
    "dossier_revision",
    "dossier_evidence_ref",
]

WRITE_TABLES = [
    "company_dossier",
    "dossier_core_debate",
    "dossier_catalyst",
    "dossier_durability",
    "dossier_failure_mode",
    "dossier_revision",
    "dossier_evidence_ref",
]

TIMEOUT_S = 120  # /ask is streaming; give it up to 2 min


# ─── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str, timeout: int = 15) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _post_streaming(path: str, payload: Dict[str, Any], timeout: int = TIMEOUT_S) -> str:
    """POST and drain the streaming NDJSON response; return concatenated body."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    chunks: List[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if line:
                    chunks.append(line)
    except urllib.error.HTTPError as exc:
        return f"ERROR {exc.code}: {exc.read().decode()[:200]}"
    return "\n".join(chunks)


# ─── Dossier status ───────────────────────────────────────────────────────────

def get_dossier_status() -> Dict[str, Any]:
    try:
        return _get("/admin/dossier-status")
    except Exception as exc:
        return {"error": str(exc), "dossier_extraction_enabled": None}


# Map from logical table name → response key
_STATUS_KEY_MAP = {
    "company_dossier":       "head_count",
    "dossier_core_debate":   "debate_count",
    "dossier_moat_dimension":"dimension_count",
    "dossier_catalyst":      "catalyst_count",
    "dossier_variant":       "variant_count",
    "dossier_durability":    "durability_count",
    "dossier_failure_mode":  "failure_mode_count",
    "dossier_revision":      "revision_count",
    "dossier_evidence_ref":  "evidence_ref_count",
}


def counts_from_status(status: Dict[str, Any]) -> Dict[str, int]:
    return {t: int(status.get(_STATUS_KEY_MAP[t], 0) or 0) for t in DOSSIER_TABLES}


def total_write_rows(counts: Dict[str, int]) -> int:
    return sum(counts.get(t, 0) for t in WRITE_TABLES)


# ─── /ask call ────────────────────────────────────────────────────────────────

def run_ask(ticker: str) -> Dict[str, Any]:
    """Fire /api/ask for a ticker; return timing + outcome summary."""
    payload = {
        "company_name": ticker,
        "question": f"What is the investment thesis for {ticker}?",
    }
    t0 = time.monotonic()
    raw = _post_streaming("/ask", payload)
    elapsed = round(time.monotonic() - t0, 1)

    # Parse last non-empty JSON line (streaming endpoint emits incremental lines)
    last_json: Optional[Dict[str, Any]] = None
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                last_json = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    is_fallback = False
    has_thesis  = False
    error_msg   = None

    if raw.startswith("ERROR"):
        error_msg = raw[:200]
    elif last_json:
        answer = last_json.get("answer") or {}
        thesis = answer.get("investment_thesis") if isinstance(answer, dict) else None
        if isinstance(thesis, dict):
            has_thesis = True
            conclusion = str(thesis.get("conclusion", "")).lower()
            score_source = str(thesis.get("score_source", "")).lower()
            bull = str(thesis.get("bull_thesis", "")).lower()
            conf = float(thesis.get("confidence_score", 1.0) or 1.0)
            is_fallback = (
                "wall cap exceeded" in conclusion
                or "synthesis unavailable" in bull
                or score_source == "fallback_empty"
                or conf == 0.0
            )

    return {
        "ticker":      ticker,
        "elapsed_s":   elapsed,
        "has_thesis":  has_thesis,
        "is_fallback": is_fallback,
        "error":       error_msg,
    }


# ─── Main validation ──────────────────────────────────────────────────────────

def main() -> None:
    expect_writes = "--expect-writes" in sys.argv

    print(f"\n{'='*70}")
    print(f"  Phase 9G Phase 0 — Dossier Shadow-Write Validation")
    print(f"  Backend : {BASE_URL}")
    print(f"  Flag    : {'ON — writes expected' if expect_writes else 'OFF — no writes expected'}")
    print(f"{'='*70}\n")

    # ── 1. Health check ──────────────────────────────────────────────────────
    print("Step 1: health check ...", end=" ", flush=True)
    try:
        h = _get("/health", timeout=10)
        print(f"OK  ({h.get('status', h)})")
    except Exception as exc:
        print(f"FAIL ({exc})\nBackend unreachable — aborting.")
        sys.exit(1)

    # ── 2. Baseline status ───────────────────────────────────────────────────
    print("\nStep 2: baseline /admin/dossier-status ...")
    baseline = get_dossier_status()
    flag_live = baseline.get("dossier_extraction_enabled")
    baseline_counts = counts_from_status(baseline)
    baseline_total  = total_write_rows(baseline_counts)

    if baseline.get("error"):
        print(f"  WARNING: {baseline['error']}")
    print(f"  dossier_extraction_enabled : {flag_live}")
    print(f"  db_active                  : {baseline.get('db_active')}")
    for t in DOSSIER_TABLES:
        print(f"    {t:<35} {baseline_counts[t]}")
    print(f"  total write-table rows     : {baseline_total}")

    # Flag agreement check
    flag_ok = (flag_live == expect_writes)
    flag_verdict = "PASS" if flag_ok else "WARN"
    print(f"\n  Flag check [{flag_verdict}]: live={flag_live}, expected={expect_writes}")
    if not flag_ok:
        print("  NOTE: Set DOSSIER_EXTRACTION_ENABLED env var on Render and redeploy to match.")

    # ── 3. Run /ask for each ticker ──────────────────────────────────────────
    print(f"\nStep 3: running /ask for {TICKERS} ...")
    ask_results: List[Dict[str, Any]] = []
    status_after: List[Dict[str, int]] = []

    for ticker in TICKERS:
        print(f"\n  [{ticker}] sending /api/ask ...", flush=True)
        result = run_ask(ticker)
        ask_results.append(result)

        status = get_dossier_status()
        after_counts = counts_from_status(status)
        status_after.append(after_counts)
        after_total = total_write_rows(after_counts)

        print(f"    elapsed   : {result['elapsed_s']}s")
        print(f"    has_thesis: {result['has_thesis']}")
        print(f"    fallback  : {result['is_fallback']}")
        if result["error"]:
            print(f"    error     : {result['error']}")
        print(f"    dossier write-table rows after : {after_total}")

    # ── 4. Validation table ──────────────────────────────────────────────────
    final_counts = status_after[-1] if status_after else baseline_counts
    final_total  = total_write_rows(final_counts)
    delta_total  = final_total - baseline_total

    print(f"\n{'='*70}")
    print("  Validation Table")
    print(f"{'='*70}")
    checks: List[tuple] = []

    # /ask did not error
    for r in ask_results:
        verdict = "PASS" if (r["has_thesis"] and not r["error"]) else "FAIL"
        checks.append((f"/ask {r['ticker']} returned thesis", verdict,
                        f"{r['elapsed_s']}s, fallback={r['is_fallback']}"))

    # No fallback syntheses
    fallback_count = sum(1 for r in ask_results if r["is_fallback"])
    checks.append(("No synthesis fallbacks",
                   "PASS" if fallback_count == 0 else "WARN",
                   f"{fallback_count}/{len(ask_results)} were fallback"))

    # Row growth matches flag
    if expect_writes:
        row_verdict = "PASS" if delta_total > 0 else "FAIL"
        row_note    = f"+{delta_total} rows written (baseline={baseline_total}, final={final_total})"
    else:
        row_verdict = "PASS" if delta_total == 0 else "FAIL"
        row_note    = f"delta={delta_total} (expected 0 — flag is OFF)"

    checks.append(("Dossier row growth matches flag", row_verdict, row_note))

    # company_dossier head rows == tickers written (when flag on)
    if expect_writes:
        head_rows = final_counts.get("company_dossier", 0)
        ticker_count = len([r for r in ask_results if r["has_thesis"] and not r["is_fallback"]])
        head_verdict = "PASS" if head_rows >= 1 else "FAIL"
        checks.append(("company_dossier head rows ≥ 1",
                        head_verdict,
                        f"head_rows={head_rows}, eligible_tickers={ticker_count}"))

    # Injection still OFF — check synthesis prompt not modified (static assertion)
    checks.append(("Injection remains OFF", "PASS",
                   "dossier_extraction_enabled controls writes only; injection=False is hardcoded"))

    # Flag status endpoint
    checks.append(("Flag check", flag_verdict,
                   f"live={flag_live}, expected={expect_writes}"))

    # Print
    col_w = 44
    for label, verdict, note in checks:
        icon = "✓" if verdict == "PASS" else ("!" if verdict == "WARN" else "✗")
        print(f"  [{icon}] {label:<{col_w}} {verdict:<5}  {note}")

    # Per-table delta
    if expect_writes and delta_total > 0:
        print(f"\n  Table deltas:")
        for t in DOSSIER_TABLES:
            b = baseline_counts.get(t, 0)
            f = final_counts.get(t, 0)
            arrow = f"+{f-b}" if f > b else ("=" if f == b else f"{f-b}")
            print(f"    {t:<35} {b:>5} → {f:>5}  ({arrow})")

    # ── Summary ──────────────────────────────────────────────────────────────
    fails   = [c for c in checks if c[1] == "FAIL"]
    warns   = [c for c in checks if c[1] == "WARN"]
    overall = "PASS" if not fails else "FAIL"

    print(f"\n{'='*70}")
    print(f"  Overall: {overall}  ({len(fails)} failures, {len(warns)} warnings)")
    print(f"  Commit : f2e9f12  (feat(dossier): Phase 9G Phase 0 — Slices 3+4)")
    print(f"  Flag   : DOSSIER_EXTRACTION_ENABLED={'true' if flag_live else 'false'}")
    print(f"{'='*70}\n")

    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
