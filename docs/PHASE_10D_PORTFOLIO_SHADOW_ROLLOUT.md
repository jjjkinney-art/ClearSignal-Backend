# Phase 10D Portfolio Intelligence — Shadow Rollout Guide

## Overview

Phase 10D introduces portfolio-level intelligence: cross-exposure projection, health
metrics, insight generation, ranking, and delivery integration.  All delivery is gated
behind shadow mode by default — no live Notification rows are written until explicitly
enabled.

This document describes env vars, safe defaults, how to run shadow validation, internal
validation steps, rollback, regulatory gates, and criteria before canary promotion.

---

## Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PORTFOLIO_INSIGHT_ENABLED` | bool | `false` | Enable portfolio insight generation pipeline |
| `PORTFOLIO_DELIVERY_ENABLED` | bool | `false` | Enable portfolio delivery integration |
| `PORTFOLIO_SHADOW` | bool | `true` | Deliver to ledger only; no live Notification rows |
| `PORTFOLIO_INTERNAL_ONLY` | bool | `true` | Restrict delivery to internal user IDs |

**Safe defaults** — all four flags are `false` / `true` (off / shadow) until explicitly
promoted.  A deployment that ships 10D code with no env var changes runs entirely
inert: no insights are generated, no delivery rows are created, no notifications appear.

---

## Safe Defaults

```
PORTFOLIO_INSIGHT_ENABLED=false
PORTFOLIO_DELIVERY_ENABLED=false
PORTFOLIO_SHADOW=true
PORTFOLIO_INTERNAL_ONLY=true
```

These are the values assumed by `portfolio_observability_service.py` when the settings
object does not expose the flags.  No `.env` changes are required to deploy 10D safely.

---

## How to Run Shadow Validation

### Local (dev server running on port 8000)

```bash
# Ensure local server is running
uvicorn app.main:app --reload --port 8000 &

# Run validation
python tests/validate_10d_portfolio_shadow.py
```

### Against Render production

```bash
BACKEND_URL=https://clearsignal-backend-dlsc.onrender.com \
    python tests/validate_10d_portfolio_shadow.py
```

### Verbose output

```bash
VERBOSE=1 python tests/validate_10d_portfolio_shadow.py
```

### Expected output (clean deployment)

```
Phase 10D Portfolio Shadow Validation
Backend: http://127.0.0.1:8000
============================================================
── Check 1: Health endpoint ...
  ✓ [PASS] health reachable
  ✓ [PASS] health HTTP 200
  ✓ [PASS] health status=ok
── Check 2: DB table count ...
  ✓ [PASS] db_table_count >= 31
...
Results: N/N PASS  0 FAIL  0 WARN  0 SKIP

[PASS] All checks passed — Phase 10D shadow readiness confirmed.
```

---

## Internal Validation Steps

Run these after every deploy that touches Phase 10D code.

### Step 1 — Unit tests (CI gate)

```bash
python3 -m pytest tests/test_services/ -q
```

All 10D tests must pass.  The one known pre-existing failure
(`test_mute_until_future_defers_row` in `test_loop_delivery_service.py`) is
pre-Phase-10D and unrelated to portfolio intelligence.

### Step 2 — Observability snapshot

```bash
curl -s http://localhost:8000/admin/portfolio-status | python3 -m json.tool
```

Verify:
- `safe_state: true`
- `portfolio_flags.portfolio_shadow: true`
- `notifications.portfolio_alert_count: 0`
- `regulatory.disclaimer_present: true`

### Step 3 — Shadow validation script

```bash
python tests/validate_10d_portfolio_shadow.py
```

Must exit 0 with 0 FAILs before any canary promotion.

### Step 4 — Regulatory gate (manual)

Review `portfolio_observability_service._regulatory_section()` output:

- `prohibited_word_count > 0` confirms the word guard is loaded
- `disclaimer_length > 0` confirms the disclaimer is present in every insight body

### Step 5 — DB table count

Confirm `/health` returns `db_table_count >= 31`.  The three new Phase 10D tables are:

| # | Table | Added |
|---|-------|-------|
| 29 | `portfolios` | 10D Slice 1 |
| 30 | `portfolio_positions` | 10D Slice 1 |
| 31 | `portfolio_insights` | 10D Slice 1 |

---

## Rollback Steps

Phase 10D is fully additive.  No existing tables or columns are modified.
Rollback requires only reverting the code — no migrations need to be undone.

1. Revert the deployment to the previous commit:
   ```bash
   git revert HEAD  # or redeploy previous Render commit
   ```
2. Verify `/health` returns the pre-10D `db_table_count`.
3. Confirm `/admin/portfolio-status` returns 404 (endpoint no longer present).
4. The three portfolio tables remain in the DB but are inert without the service code.

No data loss occurs on rollback — portfolio rows (if any were created during shadow
testing) remain but are not read or processed.

---

## Regulatory Gates

Every portfolio insight body_json must contain a `regulatory_disclaimer` field.
The regulatory guard runs at generation time (Slice 5) and blocks any insight body
that contains prohibited investment language.

### Prohibited single-word terms (word-boundary matched)

`buy`, `sell`, `hold`, `overweight`, `underweight`, `outperform`, `underperform`,
`upgrade`, `downgrade`

Note: `hold` is matched only at word boundaries — "holdings" and "household" are NOT
flagged.

### Prohibited multi-word phrases (substring matched)

`should buy`, `should sell`, `target price`, `price target`, `expected return`,
`optimal allocation`, `increase position`, `reduce position`, `strong buy`,
`strong sell`, `recommend`

### Validation check

```bash
curl -s http://localhost:8000/admin/portfolio-status | \
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d['regulatory'])"
```

Expected:
```json
{
  "disclaimer_present": true,
  "disclaimer_length": <N>,
  "prohibited_word_count": 9,
  "prohibited_phrase_count": 11
}
```

Any `disclaimer_present: false` is a hard FAIL — do not promote to canary.

---

## Criteria Before Canary

All of the following must be true before promoting Phase 10D from shadow to canary:

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | `validate_10d_portfolio_shadow.py` exits 0 | Run script |
| 2 | `safe_state: true` in production snapshot | `/admin/portfolio-status` |
| 3 | `db_table_count >= 31` | `/health` |
| 4 | `portfolio_alert_count = 0` in Notification table | `/admin/portfolio-status` |
| 5 | `regulatory.disclaimer_present: true` | `/admin/portfolio-status` |
| 6 | `prohibited_word_count > 0` (guard loaded) | `/admin/portfolio-status` |
| 7 | All `test_services/` tests pass | `pytest tests/test_services/ -q` |
| 8 | No external delivery rows in ledger | `/admin/portfolio-status` + `/admin/delivery-status` |
| 9 | Manual review of one generated insight body | Confirm prose is template-bound |
| 10 | Product / compliance sign-off on disclaimer text | Out-of-band |

### To promote to canary (when ready)

```bash
# Enable insight generation only — delivery remains off
PORTFOLIO_INSIGHT_ENABLED=true

# Then re-run validation
python tests/validate_10d_portfolio_shadow.py
```

Do not enable `PORTFOLIO_DELIVERY_ENABLED=true` until criteria 1–10 above are all
confirmed and a separate canary plan (% rollout, kill-switch wire-up) is approved.

---

## Architecture Summary

```
portfolio_mirror_service   → portfolios + portfolio_positions (mirrors watchlist)
portfolio_exposure_service → cross-exposure projection (read-only, no new intelligence)
portfolio_health_service   → HHI, effective-N, theme exposure, regime sensitivity
portfolio_insight_service  → insight generation (8-type taxonomy, regulatory guard)
portfolio_insight_ranking_service → §3.3 rank formula (base×weight×novelty×recency)
portfolio_delivery_service → enqueue via loop_delivery_service, shadow mode default
portfolio_observability_service  → admin snapshot, safe_state, regulatory check
```

All services are null-session safe and never raise on DB errors.
No LLM calls are made in any portfolio service.
No investment recommendations are generated.
