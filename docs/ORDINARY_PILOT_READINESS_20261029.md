# Ordinary twelve-case pilot: execution readiness and human review package

State on 2026-10-29. Live execution is disabled. No live SEC, model or
provider request, merge, deploy or spend was made to produce this document.
No approval exists.

**Every review referenced below is model-assisted** (Claude Code, 2026-10-29).
None is an independent human review, and none satisfies the
independent-reviewer requirement.

## 1. Code under review

| | Branch / head | Base | CI on head | Scope |
|---|---|---|---|---|
| PR #350 | `pilot/offline-ordinary-accounting` @ `7eb8de5` | `main` @ `9da213d` (already merged in) | green, run 40813186358 | 59 commits; 30 files, +3,681 / −45 |
| PR #352 | `pilot/ordinary-live-launcher` @ `a7a7e7f` | #350 head `7eb8de5` + 3 commits (`6b087c8`, `dcbc333`, `a7a7e7f`) | green, run 40826203159 | 10 files, +1,337 / −50 |
| Frontend #86 | merged as `5ee51c3`, deployed to Vercel production | — | green | `lib/queryIntent.ts` routing |

### PR #350: review package

**Production application change.** There is exactly one, and it reaches every
`/ask` user once merged: `app/services/issuer_identity.py`, +9 lines.
- A multi-word name window that ends in a legal form ("NN Inc") also matches
  its `name_key`. Before this, short registrant names named with their legal
  form went unresolved.
- Evidence: a false-positive scan of 854 repository questions against 250
  issuers, including decoys such as IT INC, US CORP and AT&T INC, changed 4
  resolutions, all correctly.
- Two-issuer, shared-short-name and bare-word cases still resolve to nothing.

**Pilot code** (validation/ and tests/; not imported by the application):
- **The native path:**
  - the ordinary ledger, gate, transport and boundary;
  - the parent-supervised worker;
  - the read-only export;
  - the routing-stage directory slot, a contract amendment the owner approved;
  - the pinned frontend intents (`validation/ordinary_frontend_intents.py`:
    frontend `5ee51c3`, classifier SHA-256 `d8f9810f…41b6`).
- **Fixed during model-assisted review:**
  - the frontend-intent blocker, fixed in the frontend via #86;
  - late answers exported after the parent's deadline;
  - missing outcomes when the worker refused early;
  - a check that compared a value with itself.

**Limits, frozen:**
- 66 SEC GETs: 8 per thesis case and 3 per threshold case;
- 10 dispatches per second and 4 concurrent;
- a 16 MiB cap per body and 256 MiB retained;
- 30 s, 20 s and 480 s deadlines;
- 0 model and 0 paid-provider attempts;
- no retries and no redirects;
- one active case at a time.

**Review record:** `docs/PR350_REVIEW_20261029.md` and
`docs/ORDINARY_PILOT_INTEGRATION_20261029.md`.

### PR #352: review package

**No application change.** The pilot code changes are:
- `validation/ordinary_approved.py`, the launcher, with three commands:
  - `evidence-template`;
  - `prepare`, which binds the package;
  - `run`, which only checks unless `--execute` is given.
- The worker's `loopback` and `approved` modes:
  - sockets are admitted only by the gate's audit;
  - the zero-model placeholder is required;
  - the approval kind is checked.
- `NATIVE_BACKEND`, an explicit marker.
- The pilot-only `direct_tls` network configuration
  (`validation/ordinary_network.py`), described in
  `docs/ORDINARY_LIVE_LAUNCHER_20261029.md` under "Network configurations".
- One shared supervise-and-export path.
- A durable outcome record for every run, even with no ledger.

**Evidence:**
- **Loopback live-path run.** Real sockets carried 60 CONNECTs and 60
  TLS-verified requests, and all 12 cases were answered.
- **Unpinned certificate.** The run is refused before any request is served.
- **37 launcher tests.** They cover:
  - an 18-way refusal matrix;
  - single use;
  - no run without `--execute`;
  - evidence binding;
  - early-failure records;
  - the declared inventory.
- **Mutation sweep.** 17 of 18 mutations are caught; the 18th is equivalent.

**Review record:** `docs/ORDINARY_LIVE_LAUNCHER_20261029.md`.

### Accepted limitations (both PRs)
- **Approval is self-asserted.** A JSON record is not proof of identity.
- **`source_binding` hashes `.py` files only.** Dependencies are bound by
  version.
- **The application's SSRF check is neutralised** by the reviewed DNS rule
  inside claimed exchanges. This is the historical design.
- **Rate and concurrency are measured at owned HTTPX entry,** not at SEC
  arrival.
- **Each case assumes a fresh session** with no `active_ticker` and no
  history.
- **TLS trust ends at the pinned bundle.**
  - With the explicit proxy, if that proxy intercepts TLS, the bundle is the
    proxy's CA, and the run trusts the proxy for SEC origin.
  - With direct TLS, the bundle is a public CA bundle and the run verifies
    the SEC hosts' certificates, though not anything below the process, such
    as a VPN.

### Unresolved findings (open)
1. **The network path is not yet exercised live.** Direct TLS from this Mac
   through the VPN has been tested only over loopback. SEC's reaction to the
   VPN exit, and any VPN-level TLS handling, are unknown until the approved
   run. See §2.
2. **Real response sizes are unknown** for GOOGL, AMZN, INGR, NNBR and MAN.
   NPK is known: 10-K HTML 1,404,517 bytes and facts 2,490,080 bytes. A body
   over 16 MiB halts the run (`response_size`), which fails safe but spends
   the approval.
3. **The pilot paces at exactly SEC's published maximum** of 10 requests per
   second, and SEC states it may lower limits. A throttle response halts the
   run (`http_throttled`).

## 2. Execution environment: chosen path

**Decision (Julian, 2026-10-29): run locally on this Mac with the pilot-only
direct-TLS configuration.** No application proxy is used. The historical
explicit-proxy configuration remains supported and unchanged.

### Why not the current cloud environment
A read-only inspection of the current ChatGPT cloud task (made by the
operator; no SEC request) found:

- all four proxy variables at `http://127.0.0.1:44519`, a per-session
  loopback forwarder, instead of `http://proxy:8080`;
- both CA selectors on `/usr/local/share/ca-certificates/nebula-dns.crt`
  (SHA-256 `ab6933a8…8f2b`), a platform TLS-interception CA;
- no `clearsignal-venv`;
- `www.sec.gov` and `data.sec.gov` absent from the session's allowed
  domains.

These are session observations, not guarantees. Adapting to them would have
meant:

- generalising the shared historical proxy code;
- approving a configuration that changes every session;
- trusting the platform's interceptor for SEC origin.

### This Mac: what was verified (read-only, no external request)

| Item | Observed |
|---|---|
| OS | macOS 14.0, x86_64 |
| Interpreter | CPython 3.11.9 standalone at `~/clearsignal-pilot/cpython-3.11.9` (python-build-standalone `20240814`, archive SHA-256 `76073305…a13e`, matching the release's published `SHA256SUMS`) |
| Packages | Isolated venv at `~/clearsignal-pilot/venv`, from the pinned `requirements.txt`. Every `AUDITED_DEPENDENCIES` version matches: openai 2.32.0, httpx 0.28.1, httpcore 1.0.9, requests 2.32.5, urllib3 2.8.0. No system-wide change was made. |
| CA bundle candidate | `certifi` 2026.10.23, `~/clearsignal-pilot/venv/lib/python3.11/site-packages/certifi/cacert.pem`, SHA-256 `2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b`. `certifi` is not pinned in `requirements.txt`; the package pins these exact bytes, and `run` refuses any change. |
| Proxy variables | None set. No macOS system proxy is configured. Direct mode refuses to run if one appears. |
| Credentials | `OPENAI_API_KEY`, `SEC_USER_AGENT`, `FMP_API_KEY`, `FRED_API_KEY` and `NEWS_API_KEY` are all unset. The operator sets only the zero-model placeholder and the SEC contact for the run. |
| Disk | 488 GiB free |
| VPN | The default route is `utun5`. A NordVPN profile is reported connected. DNS goes to the VPN's resolver at `100.64.0.2`. The New York exit is as reported by Julian and was not verified, because that would require an external request. |

### What direct TLS does and does not establish
- It avoids the **application** proxy. TLS is verified end-to-end against the
  pinned public CA bundle, with hostname checking.
- It does **not** establish anything about the VPN:
  - if the VPN intercepted TLS with a CA outside the pinned bundle,
    verification would fail and the run would halt; if its CA were inside the
    bundle, this code could not tell;
  - the VPN sees connection metadata;
  - it determines the egress IP SEC sees;
  - it adds latency.
- DNS answers come from the VPN's resolver. The gate admits only globally
  routable answers for the claimed host.
- **New risk:** SEC may throttle or block shared VPN exit addresses. A `403`
  or `429` halts the run (`http_auth` or `http_throttled`) and spends the
  approval.

## 3. Cost and retention evidence

The facts below are documented or observed, with references. The
evidence-file attestations themselves stay **empty**: they are statements by
named humans, and none were invented.

**Cost: what is known**
- **SEC EDGAR:** anyone can access the data "for free". The current maximum
  rate is 10 requests per second, and SEC may lower it. Clients must declare a
  User-Agent with a name and contact. Source:
  [Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data), found
  by web search; not fetched from sec.gov.
- **The code proves:**
  - 0 model and 0 paid-provider attempts;
  - no model credential present;
  - at most 66 requests;
  - at most 1,060.125 MiB of response bodies read;
  - at most 256 MiB retained;
  - at most 480 s of run time.
- **The code does not bound** TLS handshakes, headers, framing or in-flight
  bytes.
- **Local execution** uses no cloud task and no application proxy.

**Cost: unknown.** Local execution does not guarantee zero cost. Possible
costs include:
- the VPN subscription or any VPN data limits;
- home ISP data, about 1.1 GiB of bodies plus overhead in the worst case;
- electricity and machine time.

None is metered by this code. The spending ceiling `all_in_usd` is **not
set**; it is Julian's decision. Billing evidence could not be gathered,
because the email connector needs reconnecting.

**Retention: what is known**
- The output directory is created 0700 on this Mac's disk.
- Its inventory, the 14 ledger tables, public-SEC-only content and the
  absence of runtime values are asserted by tests.
- Nothing is uploaded anywhere by the run.

**Retention: unknown, and a human decision**
- the location and its backup exposure (for example Time Machine or iCloud
  sync of that folder);
- who has access;
- the retention period;
- the deletion procedure;
- the terms for retaining SEC content.

## 4. Execution package: merge order and binding

The package cannot be produced yet. It requires the reviewed `execution.json`,
the completed evidence (§3) and the final merged code.

1. **Independent human review of #350, then merge it** with Squash and merge,
   the repository's convention.
2. **Update #352 from `main`.** #350's changes arrive identical on both sides,
   so no conflict is expected. Then wait for CI, review and merge.
3. **On this Mac,** check out the merged `main` commit in a clean clone. Leave
   no `.py` changes.
4. **Write `execution.json`** in the `direct_tls` shape:
   - `proxy: null`;
   - `ca_selectors` `["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"]`;
   - `ca_identity` set to the venv's `certifi/cacert.pem` path and its
     SHA-256;
   - non-secret review references.

   The network reviewer confirms it.
5. **Generate the evidence templates** (`evidence-template`). Humans fill in
   the attestations, and `all_in_usd` is set.
6. **Run `prepare`** with `~/clearsignal-pilot/venv/bin/python` and a fresh
   absolute output directory that does not yet exist, for example
   `/Users/juliankinney/clearsignal-pilot/run-1`. The package then binds:
   - the git revision and the source SHA-256 of `app/**/*.py` and
     `validation/*.py`, which covers the frontend intent pin;
   - the installed dependency versions;
   - `execution.json`, including the CA bundle hash;
   - the cohort projection;
   - both evidence files' SHA-256;
   - the output directory.
7. **The operator re-checks the production frontend** (`5ee51c3`,
   `queryIntent.ts` SHA-256 `d8f9810f…41b6`).
8. **Julian approves** the printed `package_sha256` in a separate approval
   file.
9. **Run once** with these variables and no proxy variable set:
   - `OPENAI_API_KEY=ORDINARY-ZERO-MODEL-NO-CREDENTIAL`;
   - `SEC_USER_AGENT='<name> <email>'`;
   - `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` naming the pinned bundle.

   First `run` (checks only), then `run --execute`. Keep the Mac awake and the
   VPN state unchanged during the at most 480 s run.

**Regeneration rule.** Any code, dependency, `certifi`, configuration or
evidence change after `prepare` makes `run` refuse. The package must then be
regenerated and re-approved. The approval is single-use, because the output
directory must not exist.

## 5. Launch criteria: what this SEC-only pilot evaluates

| Binding launch criterion | Evaluated by this pilot? |
|---|---|
| Broad-company coverage | **Partially.** Six issuers, from large cap (GOOGL, AMZN) through mid cap (INGR, MAN) to small cap (NPK, NNBR). Three are absent from the local database and are identified from question text alone. Six frozen issuers do not establish broad coverage. |
| Graceful degradation | **No, as a user experience.** The pilot fails closed: the first SEC failure halts the run, and all twelve outcomes are recorded. That is run-safety behaviour, not graceful degradation of an answer. |
| Web fallback | **No.** SEC only; every other destination is refused. |
| Personalization | **No.** Every case starts a fresh session in authenticated mode with no user history or active ticker. |
| Proactive noticing | **No.** There is no monitoring, alerting or scheduled work. |

The pilot's own results are answers built from real SEC sources. They are
recorded as `answered_unadjudicated`, and their research quality remains
unadjudicated until a human or benchmark review.

## 6. Julian: decisions only you can make

- [x] **Execution environment:** local Mac, direct TLS (decided 2026-10-29).
- [ ] **Independent reviewers:** one engineer for #350 and #352, who can
      also act as network reviewer for `execution.json`.
- [ ] **Spending ceiling `all_in_usd`,** given that the VPN, ISP and
      electricity costs are not metered by the code.
- [ ] **Retention:** location (exclude it from cloud sync if needed), access,
      period and deletion of the run directory.
- [ ] **SEC contact** for the User-Agent: a name and a monitored email.
- [ ] **Accept or reject the open risks:**
  - a VPN below the process is outside the code's view;
  - a shared VPN exit may be throttled or blocked by SEC;
  - an unknown response size can halt the run;
  - a throttle at the 10/s maximum can halt the run;
  - approval is self-asserted.
- [ ] **Approve the final `package_sha256`,** after steps 1–8 of §4.
