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
- **TLS trust ends at the pinned bundle.** If the environment's proxy
  intercepts TLS to inject secrets, that bundle is the proxy's CA. The run
  then authenticates the proxy, and trusts it for SEC origin. Nothing in the
  code verifies SEC origin.

### Unresolved findings (open)
1. **The proxy and CA facts are unverified for today's environment.** See §2.
2. **Real response sizes are unknown** for GOOGL, AMZN, INGR, NNBR and MAN.
   NPK is known: 10-K HTML 1,404,517 bytes and facts 2,490,080 bytes. A body
   over 16 MiB halts the run (`response_size`), which fails safe but spends
   the approval.
3. **The pilot paces at exactly SEC's published maximum** of 10 requests per
   second, and SEC states it may lower limits. A throttle response halts the
   run (`http_throttled`).

## 2. Execution environment: what could and could not be verified

The historical approved pilots, ten approvals all consumed, ran in a saved
ChatGPT cloud task environment: `/workspace`, with a pinned venv at
`/workspace/clearsignal-venv` (`docs/APPROVED_PILOT_ACTIVATION.md`). That
document records that task metadata then showed all four proxy selectors equal
to `http://proxy:8080`, and both CA selectors naming one local file.

**No access to that environment exists from this session.** Nothing about its
current proxy, CA bundle, allowed domains, interpreter or dependencies was
observed.

The current official documentation
([Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments.md))
states:
- network secrets are placeholders that "the proxy substitutes" for allowed
  HTTPS destinations on port 443;
- TCP clients use "the environment's HTTP CONNECT proxy at `proxy:8088`", and
  "TCP tunnels don't intercept TLS or inject network secrets";
- other subdomains need their own allowed-domain entries, so `data.sec.gov`
  needs one;
- saved task state is recoverable "for up to seven days after you last start
  a turn or resume the task".

**It does not mention** `HTTP_PROXY`, port 8080 or any CA bundle.

| Item the package binds | Status |
|---|---|
| Proxy selectors = `http://proxy:8080` | **Unverified today.** Historical metadata only, and the current docs name no 8080. If the environment differs, `run` refuses (fail-safe), and `execution.json` needs a new network review. |
| CA bundle path and SHA-256 | **Unverified.** No hash is recorded anywhere in the repository. It must be read in the environment. |
| `www.sec.gov` and `data.sec.gov` in allowed domains | **Unverified.** These must be configured. |
| CPython 3.11.9 and `AUDITED_DEPENDENCIES` installed | **Unverified.** `run` refuses otherwise. |
| A non-secret `SEC_USER_AGENT` (name and contact) | **To be chosen.** It is a direct variable, not a network secret. |
| `OPENAI_API_KEY` | Must be set to `ORDINARY-ZERO-MODEL-NO-CREDENTIAL` in the run's shell, overriding any environment placeholder. |

## 3. Cost and retention evidence

The facts below are documented, with references. The evidence-file
attestations themselves stay **empty**: they are statements by named humans,
and none were invented.

**Cost: what is known**
- SEC EDGAR: anyone can access the data "for free". The current maximum rate
  is 10 requests per second, and SEC may lower it. Clients must declare a
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
- **The code does not bound** CONNECT and TLS setup, headers, framing or
  in-flight bytes.
- Cloud task VM resources are set by plan; for example, Plus gives 2 vCPUs,
  8 GiB of memory and 8 GiB of disk. Retained data at most 256 MiB fits. The
  documentation states no per-task price.

**Cost: unknown**
- Whether a cloud task incurs any incremental charge on this account's plan.
- Any proxy or egress charge.

Account evidence could not be gathered: the email connector is disconnected,
and there is no billing access. The spending ceiling `all_in_usd` is **not
set**. It is Julian's decision.

**Retention: what is known**
- The output directory is created 0700 inside the task's filesystem.
- Its inventory, the 14 ledger tables, public-SEC-only content and the absence
  of runtime values are all asserted by tests.
- Saved task state is recoverable for up to seven days after last activity.
- The documentation does not state what happens after that, or how deletion
  works.

**Retention: unknown, and a human decision**
- where the results are kept long-term (copied out of the task, or not);
- who has access;
- the retention period;
- the deletion procedure;
- the terms for retaining SEC content.

## 4. Execution package: merge order and binding

The package cannot be produced yet. It requires the reviewed `execution.json`
(§2), completed evidence (§3), and the final merged code.

1. **Independent human review of #350, then merge it** with Squash and merge,
   the repository's convention.
2. **Update #352 from `main`.** #350's changes arrive identical on both sides,
   so no conflict is expected. Then wait for CI, review and merge.
3. **In the execution environment,** check out the merged `main` commit. Leave
   no `.py` changes.
4. **Write `execution.json`** from the observed proxy selectors and the CA
   path and SHA-256. This is the network review.
5. **Generate the evidence templates** (`evidence-template`). Humans fill in
   the attestations, and `all_in_usd` is set.
6. **Run `prepare`** with a fresh absolute output directory, for example
   `/workspace/clearsignal-ordinary-run-1`. The package then binds:
   - the git revision and the source SHA-256 of `app/**/*.py` and
     `validation/*.py`, which covers the frontend intent pin;
   - the installed dependency versions;
   - `execution.json`;
   - the cohort projection;
   - both evidence files' SHA-256;
   - the output directory.
7. **The operator re-checks the production frontend** (`5ee51c3`,
   `queryIntent.ts` SHA-256 `d8f9810f…41b6`).
8. **Julian approves** the printed `package_sha256` in a separate approval
   file.
9. **`run` (checks only), then `run --execute`,** once.

**Regeneration rule.** Any code, dependency, configuration or evidence change
after `prepare` makes `run` refuse. The package must then be regenerated and
re-approved. The approval is single-use, because the output directory must
not exist.

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

- [ ] **Execution environment:** reuse the historical ChatGPT cloud task
      environment, or name another. Grant the network reviewer access to read
      its proxy and CA configuration.
- [ ] **Independent reviewers** for #350 and #352, and for the network, cost
      and retention reviews.
- [ ] **Spending ceiling `all_in_usd`**, after the plan and egress cost are
      known.
- [ ] **Retention:** storage location, access, period and deletion of the
      run's outputs, including whether to copy them out of the seven-day task
      state.
- [ ] **SEC contact** for the User-Agent: a name and a monitored email.
- [ ] **Accept or reject the open risks:**
  - TLS trust ends at the pinned bundle;
  - an unknown response size can halt the run;
  - a throttle at the 10/s maximum can halt the run;
  - approval is self-asserted.
- [ ] **Approve the final `package_sha256`,** after steps 1–7 of §4.
