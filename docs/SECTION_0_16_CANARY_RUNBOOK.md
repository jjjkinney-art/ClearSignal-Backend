# One-person controlled-beta canary — operator runbook (Section 0.16)

Status: **procedure only.** Nothing in this document has been executed. Each
numbered stage below needs its own explicit approval, and the whole canary
waits until the support inbox has been tested in both directions.

Production preconditions this runbook assumes (confirm before stage 1):

| Item | Expected |
|---|---|
| `BETA_ADMISSION_MODE` | `enforce` |
| `BETA_ADMISSION_PEPPER` | configured (never displayed) |
| Migration head | `0006_access_grants` |
| Grants | 4 subject grants, 4 redeemed, 0 pending / expired / revoked / invitation |
| Monitoring, generated alerts, delivery, Stripe, billing | all disabled |
| Invitation ledger | baseline 0, no invitations sent |
| Support inbox `supportclearsignal@gmail.com` | tested: can send AND receive |

## Privacy rules for every stage

Nothing below ever enters a report, commit, chat message, ticket or log:
email addresses (other than the public support address), Supabase subjects,
user ids, grant locators, tokens, the pepper, customer ids, tickers,
holdings, quantities, cost bases or portfolio values.

What is allowed: aggregate counts, booleans, the admission mode, dry-run /
executed state, the tool's random `operation_ref`, and the opaque ledger
reference `R-001`.

The recipient's address is typed **only** into the tool's masked prompts
(twice), and written **only** in the invitation email itself, in the
operator's own mail client. The mapping `R-001` → person lives only in the
operator's private contacts, never in the ledger.

All commands run in the **Render Shell** of the backend service.

## Stage 0 — aggregate baseline (read-only)

```bash
python3 scripts/beta_admission.py status
python3 scripts/beta_admission.py grandfather-existing
```

Expected:

| Output | Value |
|---|---|
| `status`: `total` / `approved_redeemed` / `subject_grants` | 4 / 4 / 4 |
| `status`: `approved_pending`, `expired_pending`, `revoked`, `invite_grants` | 0 |
| dry run: `examined` / `already_granted` / `skipped_unbound` / `would_grant` | 5 / 4 / 1 / 0 |
| dry run header | `read_only=True  written=0` |

Also note, in Render → Logs, the current count of lines containing
`admission denied` (expected 0) and `admission configuration invalid`
(expected 0), and the time range the log view actually covers.

**Abort** if any value differs.

## Stage 1 — private ledger entry

In the private ledger (never in either repository):

| # | sent_at (UTC) | status | cohort | recipient_ref | notes | last_health_review | incident_ref |
|---|---|---|---|---|---|---|---|
| 1 | — | planned | C1 | R-001 | — | — | — |

Invitation count stays **0**: it increments only when an invitation is
actually sent.

## Stage 2 — masked approval

```bash
python3 scripts/beta_admission.py approve --note-ref R-001
```

* **Omit `--expires-days` for this canary.** Expiry is checked on every
  request, including after redemption, so an expiry date would end the
  participant's access on that date. With no expiry, access continues until
  it is explicitly revoked (stage 7). The expiry semantics are intentionally
  unchanged in this section.
* The tool asks for the address **twice**, with input hidden both times.
  Type it carefully; nothing is echoed.
* A mismatch, an empty or malformed entry, Ctrl-D or Ctrl-C prints a single
  `refused: …` line and writes nothing. Re-run the command.

Expected: `state=EXECUTED  committed=True`, `created 1`, `approved_pending 1`.

Then:

```bash
python3 scripts/beta_admission.py status
```

Expected: `total 5`, `approved_pending 1`, `invite_grants 1`,
`approved_redeemed 4`. **Abort** otherwise, and revoke (stage 7).

## Stage 3 — separate invitation delivery

Send the invitation manually from the operator's mail client, to the same
address typed in stage 2, stating that:

* sign-in is **Google only**, with that exact Google account;
* automatic monitoring, generated alerts and delivery are paused;
* billing is not active and no payment details are requested;
* support and deletion requests go to `supportclearsignal@gmail.com`;
* the privacy notice and beta terms are at `/privacy` and `/terms`.

Ledger: set row 1 to `sent` with the UTC time. Invitation count becomes **1**.
A bounced or failed delivery still counts as sent; record it in `notes`.

## Stage 4 — first Google login (participant)

The participant signs in with Google using the invited address.

Expected, as reported by the participant:

* sign-in succeeds; onboarding shows **"Start with sample data"** and
  describes the sample watchlist without calling it theirs;
* `/analyze` and `/watchlist` open.

If the participant sees **"ClearSignal is in a private beta"**, they used a
different Google account, or the address was mistyped in stage 2. Do not
retry blindly: check stage 5 counts first.

## Stage 5 — aggregate redemption checks (read-only)

```bash
python3 scripts/beta_admission.py status
python3 scripts/beta_admission.py grandfather-existing
```

Expected:

| Output | Value |
|---|---|
| `status`: `approved_pending` / `approved_redeemed` / `total` | 0 / 5 / 5 |
| dry run: `examined` / `already_granted` / `would_grant` | 6 / 5 / 0 |

`examined` rising from 5 to 6 is the only new account. `already_granted`
counts the participant's now-bound grant.

If instead `approved_pending` is still 1 and `examined` is still 5, the grant
was not redeemed (wrong Google account or mistyped address): revoke it
(stage 7) and start again from stage 2.

## Stage 6 — repeat login and denial-log review

* The participant signs out and signs in again: it must succeed.
* Render → Logs: the `admission denied` count must be **unchanged** from
  stage 0 (a deny here would mean the participant was refused after
  redemption). `admission configuration invalid` must remain 0.
* Optional, only with a spare Google account the operator owns: signing in
  with it must show the private-beta screen, the deny count rises by exactly
  one, and `examined` does not change. Never use someone else's account.

Ledger: set row 1 to `accepted`, then `active`, and record `last_health_review`.

## Stage 7 — revoke / rollback

```bash
python3 scripts/beta_admission.py revoke
```

The address is again requested twice, masked. Expected: `revoked 1`. The
participant's **next request** shows the private-beta screen. The user row is
not deleted — revocation removes access, it does not delete data (for that,
see `ACCOUNT_DELETION_RUNBOOK.md`).

Then `status`: `revoked 1`. Ledger: set row 1 to `revoked`.

**Do not change `BETA_ADMISSION_MODE`** to roll back a single participant.
`off` or `shadow` would reopen admission to anyone with a Google account.
They are the emergency lever only if the gate misbehaves for everyone.

## Abort conditions

Stop, revoke the canary grant if one exists, and record an incident reference
in the ledger if any of these happens:

* any stage's counts differ from the expected values;
* any `admission denied` line appears for an existing account;
* the participant is denied after stage 5 showed the grant redeemed;
* `examined` rises by more than one;
* anything identifying appears in any tool output;
* the support inbox cannot receive or reply.
