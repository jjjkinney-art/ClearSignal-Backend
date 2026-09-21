# Controlled-beta admission boundary — Section 0.15

Status: **implemented, not deployed, gate OFF by default.** Nothing in this
section enables the gate, creates a grant, sends an invitation, or changes any
production configuration.

## 1. Threat model

The controlled beta is reachable by anyone who can obtain a Supabase session
for this project. Before this section, the first verified login auto-created a
local user and full product access. The threats that matter:

| # | Threat | Before | After |
|---|---|---|---|
| T1 | An uninvited person signs in and uses the product | Succeeds | Denied under `enforce` |
| T2 | An attacker obtains a token carrying someone else's address and takes over their local account | The email-collision path rebound the existing row to the attacker's subject | Impossible: no code path binds by email |
| T3 | The attacker's target is the administrator, so the takeover inherits admin | Followed from T2 | Impossible; admin also requires a bound identity |
| T4 | An attacker sets `user_metadata.email` to a victim's address | The email fallback read it | Never read |
| T5 | An anonymous or provider-less identity is provisioned | Would be provisioned | Denied in every mode |
| T6 | One invitation is redeemed by several identities | n/a | Conditional UPDATE plus a UNIQUE subject |
| T7 | Denials reveal whether an address is invited | n/a | One fixed 403 for every reason |
| T8 | Operator work leaks identities into logs, arguments or output | Emails in INFO logs | Opaque refs and aggregate counts only |

Out of scope here, and still open: privacy policy, terms, risk disclaimer,
deletion and support (§11).

## 2. Trusted versus untrusted identity fields

The middleware verifies the JWT signature, audience, issuer and expiry before
any of this runs. Within a verified token:

**Trusted — written by GoTrue, not by the account holder**

| Claim | Use |
|---|---|
| `sub` | the identity. The only permanent identity key. |
| `email` | top-level; mirrors `auth.users.email`. Used ONLY as a one-time admission locator, and as a display label. |
| `app_metadata.provider` / `providers` | must be inside the allow-list (default `google`). Service-role writable only. |
| `is_anonymous` | true ⇒ refused. |

**Untrusted — never consulted**

| Field | Why |
|---|---|
| `user_metadata.*` | the account holder sets this at sign-up and via `updateUser`. `user_metadata.email` was previously an email fallback; it is now ignored entirely. |
| any address supplied by a client | never accepted as identity or authorisation. |

**Why the top-level `email` may locate a grant.** It is populated from
`auth.users.email`, which only the provider or a confirmed change flow can
set. Google verifies the address it asserts. Changing the address in GoTrue
requires the email provider (disabled in production, Section 0.14) and
"Secure email change" (enabled), which confirms at both the old and the new
address. So an attacker cannot make GoTrue assert an address they do not
control. The locator is consumed once, and after redemption the grant is
bound to `sub` and the address plays no further part.

## 3. The identity-binding invariant

Stated exactly, and enforced in every mode including `off`:

1. A local user is located by `auth_subject == sub`, and by nothing else.
2. No code path locates, merges, rebinds or authorises a local user because
   an address matches. The rebinding write no longer exists.
3. An existing `auth_subject` is never overwritten.
4. An address already held by another local row is an identity conflict and
   fails closed: nothing is rebound and no user is provisioned.
5. One local user per subject, one subject per local user. A local id already
   held by a row bound to a different subject refuses provisioning.
6. Administrator status attaches to the bound identity and can never be
   inherited through an address.
7. An identity with no provider-supplied address, or an anonymous one, is
   never provisioned.

## 4. First-login grant lifecycle

```
operator approves          person signs in                later logins
(masked address prompt)    (Google, first time)
        │                          │                           │
   HMAC locator                redeem: conditional UPDATE   lookup by sub
   status=approved     ──►     subject := sub               (no grant read)
   subject=NULL                redeemed_at := now
        │                          │
   revoke ─► status=revoked    expired / revoked / already
                               redeemed ─► generic denial
```

* **Atomic.** Redemption is `UPDATE … WHERE subject IS NULL AND redeemed_at
  IS NULL AND status='approved'`. Exactly one racing login matches. The
  UNIQUE constraint on `subject` is an independent second guard.
* **Replay-safe.** A repeated first login finds the grant already bound to
  the same subject and is admitted without consuming another. A different
  subject presenting the same address is denied.
* **Revocation after admission** does not delete the user; it removes future
  admission. Removing an existing user's access is a separate operator action.

## 5. Existing-account transition

The identities that exist today are authorised **by subject**, never by
address, using:

```bash
python3 scripts/beta_admission.py grandfather-existing            # dry run
python3 scripts/beta_admission.py grandfather-existing --execute  # commits
```

It reads `users.auth_subject` at run time, so **no production identity, id,
address or count appears in source, migrations, tests, documentation or any
commit**. Rows with no `auth_subject` are skipped, never granted. Output is
aggregate counts only. It has **not been run**.

Established accounts do not actually depend on this to keep working: they
resolve by `sub` and never consult a grant. The grandfathering exists so the
grant table is a complete record of who is authorised, and so revocation is
possible for them too.

## 6. Default-off rollout sequence

`BETA_ADMISSION_MODE` ∈ `off` (default) · `shadow` · `enforce`.

**Unset, empty, malformed or unknown resolves to `off`.** The deliberate
choice is to preserve current behaviour rather than to enforce: a typo must
never lock the operator out of production, and enforcement must never begin
by accident. The fail-closed half of the design — the binding invariants in
§3 — is unconditional and applies in `off` too.

| Step | Action | Effect |
|---|---|---|
| 1 | Deploy this branch | Binding invariants live; gate off; behaviour otherwise unchanged |
| 2 | `grandfather-existing --execute` | Existing identities hold subject grants |
| 3 | `BETA_ADMISSION_MODE=shadow` | Denials computed and audited; nobody blocked |
| 4 | Review the audit aggregate | Confirms the decision matches expectation |
| 5 | `approve` each invitee | Grants exist before any invitation is sent |
| 6 | `BETA_ADMISSION_MODE=enforce` | Open signup closes |

Steps 2–6 are configuration and operator actions requiring separate approval.
**Until step 6, production signup remains open.**

## 7. Operator procedure

```bash
python3 scripts/beta_admission.py status     # aggregate counts
python3 scripts/beta_admission.py approve --expires-days 14 --note-ref R-001
python3 scripts/beta_admission.py revoke
```

`approve` and `revoke` read the address from a **masked prompt**. It is never
an argument, never echoed, never logged and never stored: only its HMAC is.
`--note-ref` is an opaque reference into the private invitation ledger. The
tool prints counts and opaque references only, and refuses a piped address.

## 8. User-facing denial

Every denial — no grant, revoked, expired, already redeemed, conflict,
untrusted provider, anonymous, missing address — returns the same 403 and the
same sentence. The frontend shows a calm "private controlled beta" panel with
a sign-out link and no retry, so a denied person is never looped back through
sign-in and never learns whether an address or invitation exists.

## 9. Rollback

Ordering matters, and the safe direction is the simple one:

1. **Configuration first:** set `BETA_ADMISSION_MODE=off`. That alone
   restores pre-section admission behaviour, with no deploy.
2. **Code:** revert the branch. The binding invariants go away with it, which
   reintroduces the T2/T3 rebinding exposure; prefer step 1.
3. **Migration:** `alembic downgrade` drops `access_grants`. Do this only
   after the mode is `off`, or approved identities lose their grants while
   the gate is still consulting them. Dropping the table loses the operator
   approvals and nothing else: no user, watchlist or portfolio row is
   touched by either direction of the migration.

## 10. Supabase email-provider containment

Section 0.14 found the Email provider enabled, giving an API-only signup path
the app never uses. The operator has since disabled it; Google remains
enabled, anonymous sign-ins and manual linking remain disabled, and "Confirm
email" remains enabled. This code does not depend on that containment — the
provider allow-list refuses non-Google identities under enforcement
regardless — but the containment is what makes the address a trustworthy
locator today (§2).

## 11. Unchanged and still outstanding

Automatic background monitoring, generated alerts, the loop, delivery, Stripe
and billing all remain **disabled**. No invitation has been sent, and this
section neither sends nor prepares to send one.

Still required before any invitation, and **not** implemented here:

* privacy policy, terms and a financial-risk disclaimer;
* an account-deletion procedure and a support path.

This section implements no technical hook for any of them. Their content and
whether they are legally sufficient is **not assessed here**; no legal review
has been performed or is claimed.
