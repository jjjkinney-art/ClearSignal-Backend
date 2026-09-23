# Account and data deletion — manual operator runbook

Status: **procedure only.** ClearSignal has **no automatic deletion.**
Deletion is handled manually by the operator, after identity verification and
a separate approval, and it is **not instantaneous**. No deletion tooling
exists in this repository, and this runbook does not add any.

This document contains no live identifier and no SQL containing a real
identifier. It must stay that way.

## 1. Request intake

* Requests are accepted **only** through `supportclearsignal@gmail.com`.
* Reply asking the requester to confirm, **from the same address** they use
  to sign in with Google, that they want their ClearSignal account and data
  deleted.
* Never ask for, and never accept: passwords, access tokens, recovery codes,
  brokerage credentials, portfolio exports or payment details.
* Assign an opaque request reference, e.g. `DEL-001`. This reference, the
  date and an aggregate completion status are the **only** things recorded
  outside the mailbox.

## 2. Identity verification (before any mutation)

The request must come from the address bound to the account being deleted.
The operator confirms this without writing any identifier into a report,
ticket, commit or chat:

* the request email's sender matches the sign-in address; **and**
* the requester can sign in to ClearSignal with that Google account (for
  example, by confirming they reached the signed-in app on a stated date).

If verification is ambiguous, stop and ask again. **Do not delete on doubt.**

## 3. What "the account" covers

There are two separate systems, and they are deleted separately:

| System | What it holds | Who deletes it |
|---|---|---|
| **ClearSignal application database** | the local user row, profile and settings, watchlists, portfolios and positions, preferences, analysis history and generated content, notifications, and operational/audit records | the operator, through a separately approved procedure (§5) |
| **Supabase authentication** | the sign-in identity linked to Google | the operator, in the Supabase dashboard, **after** the application data (§6) |
| **Gmail support inbox** | the request emails themselves | outside ClearSignal; handled per mailbox policy |

Hosting platform logs (Render, Vercel) are not deletable per account from
ClearSignal. The application logs only an opaque one-way `subject_ref`, never
an address.

## 4. Inventory — regenerate it at the time of each request

The set of per-account tables changes as the product changes, so **never rely
on a stored list.** Regenerate it from the models on the deployed commit
(this reads source code only and prints table names, never data):

```bash
python3 - <<'PY'
from app.db.models import Base
keys = ("user_id", "auth_subject", "subject")
for name, table in sorted(Base.metadata.tables.items()):
    found = [c.name for c in table.columns if c.name in keys]
    if found:
        print(f"{name:<34} {found}")
PY
```

At the time of writing this prints **45** tables. Also include child tables
reached only through a parent — for example `portfolio_positions`, which is
keyed by `portfolio_id` rather than by user. Review the list by hand before
each request.

Records that need a policy decision before deletion (see §8):

* `audit_log` is designed as an append-only record.
* `access_grants` holds the operator's approval for the account. Revoke the
  grant (§5, step 1) before deleting it or retaining it.

## 5. Application-data deletion

1. **Revoke access first** so the account cannot create new data meanwhile:
   `python3 scripts/beta_admission.py revoke` (masked, entered twice).
2. **Read-only preview.** Produce per-table **row counts only** for the
   account, inside a read-only transaction. No tool for this exists today:
   the preview query or tool needs its own separate approval, and it must
   print counts only — never rows, ids, tickers, quantities, cost bases or
   values.
3. **Separate operator approval** of the preview counts before any deletion.
4. **Delete in one transaction** where the database supports it, children
   before parents, with the per-table deleted counts asserted against the
   preview counts. Any mismatch → roll back and stop.
5. **Verify aggregates after:** the account's per-table counts are all 0, and
   the total user count fell by exactly one.
6. Record `DEL-001`, the date, and `completed` / `rolled back`. Nothing else.

## 6. Supabase authentication deletion

After §5 completes, delete the authentication user in the Supabase dashboard
(Authentication → Users). Doing this **last** means that if §5 fails, the
person can still sign in to confirm or retry. Do not screenshot or copy the
user list.

## 7. Rollback limitations — be honest with the requester

* Deletion is **not reversible** from within ClearSignal. Once committed, the
  application data is gone.
* Restoring from a database backup — if one exists for the relevant period —
  restores the **whole database**, not one account, and is not a supported
  per-account operation.
* Hosting logs and the support mailbox are outside this procedure.

## 8. Open policy decisions (owner review)

These are decided by the owner, not by this runbook:

* whether `audit_log` rows for the account are deleted, retained, or
  anonymised, and for how long;
* whether the revoked `access_grants` row is deleted or retained;
* any retention period for records that must be kept for technical, security
  or legal reasons — **none is stated or promised anywhere yet**;
* a response or completion timeframe to publish — **none is promised yet**.
