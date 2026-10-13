# Approval-gated pilot activation (pending)

Base: `e6099dbfa2a349986569a7fa2f207c071ec13915` (PR274).

`validation.pilot_approved` adds an executable native HTTP path behind the existing
bridges. No execution approval is supplied by this change. Offline and disabled
adapter validation retain their prior behavior and authority flags. Production
application files are unchanged.

## Reviewed route; execution still pending

Official saved-cloud-environment documentation describes network secrets as placeholders
replaced by a proxy for allowed HTTPS destinations on port 443:
https://learn.chatgpt.com/docs/environments/cloud-environments#configure-environment-variables-and-network-secrets

Read-only task metadata established HTTP_PROXY, HTTPS_PROXY and both lowercase variants
all select scheme http, host proxy, port 8080, without userinfo/query/fragment. The
SSL_CERT_FILE and REQUESTS_CA_BUNDLE selectors resolve to the same readable local file.
No credentials, contact values or CA contents were displayed. This establishes the
explicit route design; it does not establish successful provider authentication.

The approved path uses exactly `http://proxy:8080`, `trust_env=False`, and an explicit
SSLContext built from the reviewed CA bundle. TLS hostname and certificate verification
remain required. All four proxy selectors must agree; both CA selectors must resolve
to the approved canonical path and SHA-256 certificate-bundle identity. No credential-
bearing proxy URLs, path/query/fragment variations, alternative proxies, automatic
fallback or retry are supported. DNS/connect permissions within a claimed exchange
apply only to this proxy endpoint. Before TLS, the only bytes admitted are the exact
CONNECT request for the claimed provider hostname on port 443, with Host and Accept
headers; provider authorization cannot be sent in the cleartext CONNECT.

Persisted configuration contains only `documentation_reference`, `verification_reference`,
`substitution: "explicit_environment_proxy"`, `bearer_source: "OPENAI_API_KEY"`,
`sec_contact_source: "SEC_USER_AGENT"`, `proxy: "http://proxy:8080"`, the four
`proxy_selectors`, the two `ca_selectors`, `ca_identity` (canonical path and certificate
bundle SHA-256), and `contains_no_credentials: true`. Runtime placeholder and contact
values never enter a manifest, request.json, policy, approval digest or configuration
hash. They are read only for the approved runtime, retained in memory, and checked for
reflection before response/result persistence. Configuration references attest operator
review; code does not authenticate the reviewer's identity.

The pending manifest still contains `execution_configuration: null`. No real approval
or filled execution configuration was created. Preparing one requires a separately
reviewed configuration bound to the exact source and output directory. Certificate
hashes identify non-secret trust material, never contacts or credentials.

## Prepare, approve separately, then run

After the reviewed code is frozen and committed, prepare a fresh manifest with the
pinned Python runtime. Preparation does not open a ledger or network connection:

```sh
/workspace/clearsignal-venv/bin/python -I -B -c 'import sys; sys.path.insert(0,"/workspace/ClearSignal-Backend"); from validation.pilot_approved import main; raise SystemExit(main())' --prepare --manifest /workspace/pilot-run.pending.json --execution-config /workspace/reviewed-nonsecret-network-config.json --output-dir /workspace/clearsignal-approved-run
```

Omitting `--execution-config` produces a deliberately blocked pending manifest.
`docs/pilot-run.pending.json` records that pending state for this local diff. Regenerate
it after commit because the binding includes both revision and source hash.

A separate future human execution/spending decision must supply an approval file with
exact fields `reference`, `run_id`, `manifest_sha256`, `output_dir`,
`execution_allowed: true`, and `spending_authorized: true`. The digest uses
`validation.capture_budget.digest` on the entire pending manifest. The approval must
match its exact code, configuration and absolute output directory. This change does
not generate approval. A JSON approval file is an operator-supplied authorization
record, not cryptographic proof of human identity.

Exact execution command, which refuses missing/mismatched approval or configuration:

```sh
/workspace/clearsignal-venv/bin/python -I -B -c 'import sys; sys.path.insert(0,"/workspace/ClearSignal-Backend"); from validation.pilot_approved import main; raise SystemExit(main())' --manifest /workspace/pilot-run.pending.json --approval /workspace/separately-supplied-pilot-approval.json --output-dir /workspace/clearsignal-approved-run
```

The output directory must not exist. The worker independently binds its canonical
working directory to approval before ledger creation; copying request.json elsewhere
cannot start another approved ledger. Approval cannot be transferred to another output
directory. No resume, reset or cleanup option exists. Never delete the run directory to
reuse approval. The first eventual authorized request consumes the existing allocation;
there is no extra authentication or paid smoke call.

## Retained boundaries

Approved purpose remains schema 2: six frozen development questions only; 24 model
attempts and 30 SEC GETs; unchanged per-case/stage quotas, reservations, claim/failure
fences, immutable model dispatch snapshots and 480-second whole-run deadline. Core
routes are source-only; thresholds use gpt-4o-mini/default tier. $0.5105664 model
allocation and $0.52 ledger allowance are illustrative accounting, not an invoice cap.

Only a consumed durable claim opens a thread-local native exchange. The gate atomically
consumes a shared grant and records native consumption in SQLite before I/O, preventing
replay through copied contexts or another gate. DNS resolves only the configured proxy
and connects only to its returned addresses on port 8080. TLS requires the claimed hostname and certificate validation. Other thread
contexts cannot use the grant. Native exchange entries, including connection failures,
are counted; timeout/crash artifacts report unknown counts rather than zero. Provider
usage remains protocol-reported usage, not a paid invoice. Authentication verification,
complete charge accounting, hard invoice cap and launch readiness remain unasserted.

Shutdown seals new network operations before draining workers and never restores the
ordinary requests/urllib/SDK bridges in approved workers. Process-lifetime audit checks
remain installed. Late threads cannot escape through restored transports; the launcher
retains the fixed hard deadline and terminates an incomplete child.

Focused tests use invented approvals/configuration and fake socket streams under an
inherited no-IP-sockets guard. They cover missing/mismatched approval, exact headers,
DNS/TLS scope, native HTTP parsing, quota/one-shot claim behavior, failure accounting,
late-worker fences, output-directory binding, and the approved launcher/worker path.
No real provider requests, credential probes, paid execution or network changes occurred.
