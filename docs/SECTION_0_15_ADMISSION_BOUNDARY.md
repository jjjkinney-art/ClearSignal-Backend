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
| T6b | A revoked or expired account keeps working | n/a | Every login under `enforce` needs a live grant bound to its `sub` |
| T6c | A typo in the mode silently reopens admission | n/a | Unsupported values abort startup |
| T6d | The locator table is offline-guessable | n/a | Mandatory pepper; no fallback key |
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
operator approves          person signs in                every later login
(masked address prompt)    (Google, first time)           (enforce / shadow)
        │                          │                           │
   HMAC locator                redeem: conditional UPDATE   bound grant for THIS
   status=approved     ──►     subject := sub               sub must be approved
   subject=NULL                redeemed_at := now           and unexpired
        │                          │                           │
   revoke ─► status=revoked    expired / revoked / already   revoked / expired /
                               redeemed ─► generic denial    missing ─► denial
```

* **Atomic.** Redemption is `UPDATE … WHERE subject IS NULL AND redeemed_at
  IS NULL AND status='approved'`. Exactly one racing login matches. The
  UNIQUE constraint on `subject` is an independent second guard.
* **Replay-safe.** A repeated first login finds the grant already bound to
  the same subject and is admitted without consuming another. A different
  subject presenting the same address is denied.
* **Revocation is real.** Under `enforce`, every login — established accounts
  included — requires an approved, unexpired grant bound to that exact `sub`.
  Revoking a grant denies that account's **next** request. The user row is not
  deleted: revocation removes access, it does not un-provision.
* **Denial writes nothing about the user.** The decision is made before any
  write, so a denied login is not provisioned, not rebound, not imported and
  not even stamped with a sign-in time. The only trace is one sanitised
  `deny` audit row keyed by an opaque subject reference.
* **Exemption is narrow.** Only the system sentinel identity — the one the
  product runs as internally, never a human — is exempt. Administrators are
  not exempt: no emergency-access bypass exists, and none should be added
  without its own design and approval.

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

**This is a mandatory prerequisite for `enforce`, not an optional tidy-up.**
Under enforcement every established account needs a live grant bound to its
own `sub`. Enable `enforce` without running this and every existing account —
including the administrator's — is denied on its next request. A test proves
exactly that lockout, and that grandfathering resolves it.

(An earlier draft of this section claimed established accounts kept working
without grandfathering. That was true only because the subject fast path
skipped the gate entirely, which also made revocation meaningless. The fast
path has been corrected; the claim is withdrawn.)

## 6. Default-off rollout sequence

`BETA_ADMISSION_MODE` ∈ `off` (default) · `shadow` · `enforce`.

**Only unset or empty resolves to `off`** — that is the environment's only way
of saying "nothing configured". Any other value that is not exactly one of the
three supported words (after trimming and case-folding) is a **configuration
error**: startup aborts with a message naming the variable and the rule, never
the value. A typo such as `enfore` therefore can never silently reopen
admission. If an invalid value ever reaches a request anyway, that request is
denied, not admitted.

`BETA_ADMISSION_PEPPER` (at least 32 characters) is **required** for any
operation that creates, looks up or redeems an email-locator grant, and startup
aborts in `shadow` or `enforce` without it. There is no fallback key: an unkeyed
digest would let anyone who can read the table test candidate addresses offline
and learn who was invited. `off` starts without a pepper.

The binding invariants in §3 are unconditional and apply in `off` too.

| Step | Action | Effect |
|---|---|---|
| 1 | Deploy this branch | Binding invariants live; gate off; behaviour otherwise unchanged |
| 2 | Set `BETA_ADMISSION_PEPPER` (≥ 32 chars, secret) | Required before any locator exists |
| 3 | `grandfather-existing` dry run, then `--execute` | **Mandatory.** Every existing identity holds a subject grant |
| 4 | `BETA_ADMISSION_MODE=shadow` | Every identity evaluated and audited; nobody blocked |
| 5 | Review the audit aggregate: denials for existing accounts must be **zero** | Proves step 3 was complete |
| 6 | `approve` each invitee | Grants exist before any invitation is sent |
| 7 | `BETA_ADMISSION_MODE=enforce` | Open signup closes; revocation takes effect |

Steps 2–7 are configuration and operator actions requiring separate approval.
**Until step 7, production signup remains open.** Do not skip step 5: a
non-zero count of existing-account denials in shadow means step 7 would lock
someone out.

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

1. **Configuration first:** set `BETA_ADMISSION_MODE=off` (or unset it). That
   alone restores pre-section admission behaviour, with no deploy. Do **not**
   "disable" the gate with any other value: an unsupported value now aborts
   startup.
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
