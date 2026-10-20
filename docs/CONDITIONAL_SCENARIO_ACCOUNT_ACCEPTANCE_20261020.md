# Conditional scenario account-boundary acceptance

Base: PR310 merge `7df9a08468b5ded5dd1762807d20d3361e12dada`.

## Scope

This is a test and review increment, not a production repair or activation.
PR310's initial ASGI tests injected request identity. The added suite exercises
the real cryptographic JWT verifier, `AuthMiddleware`, database-backed controlled
beta admission and local owner resolution before the actual conditional scenario
handler and calculator. No production implementation or setting is changed.

Every account, email address, invitation, signing key, signing secret, claim,
directory and SEC observation is invented. Each test creates a disposable SQLite
database with the real application schema. HS256 signatures are verified by
PyJWT. ES256 signatures use locally generated test keys and real PyJWT key
selection and signature/issuer/audience/expiry verification; only delivery of the
invented JWKS document is substituted. There is no Supabase session, downloaded
JWKS, real user credential, production database or source request.

The test application registers the real scenario router and `AuthMiddleware`.
A separate observation-only middleware records the resolved request identity; it
never assigns one. The database session factory and SEC provider boundary are
substituted with disposable local storage and invented records. Authentication,
identity resolution, invitation redemption and cryptographic verification are
not mocked. This is not a full deployed app, browser/CORS/edge/lifespan test.

## Demonstrated offline behavior

| Boundary | Demonstrated result |
| --- | --- |
| Missing/malformed/expired/wrong-audience/wrong-signature/wrong-algorithm/missing-subject credentials | 401 before provisioning, handler or SEC work |
| Validly signed but uninvited, expired-invite, untrusted-provider, anonymous or metadata-only-email identity | Stable 403, no provisioning or SEC work |
| Approved HS256 or ES256 identity | Real grant redemption, local owner resolution and available partial scenario |
| ES256 wrong issuer/audience/expiry/key ID/signature or symmetric-algorithm substitution | 401 without source work |
| Established account's grant revoked | Next request denied before another source invocation |
| A new subject reusing an existing account email | Access denied; existing owner retained |
| Established local ID differing from token subject | Expensive rate budget keyed to local owner, not token subject |
| Two admitted accounts | Separate identity and explicit assumptions on repeated and simultaneous requests |
| Feature disabled | Handler 404, no SEC work; global account admission still runs first |
| Database unavailable | Valid signed identity fails closed before source work |
| Provider exception after admission | Fixed evidence-gap response, no raw exception/token/email leak |
| Scenario execution | No research conversation/message, thesis version, scenario snapshot, memory entry or notification written |

Account provisioning, sign-in timestamps, admission grant changes and admission
audit records are expected database effects of authentication. The absence of
scenario persistence does not mean the request makes no database writes.

The simultaneous test establishes both accounts before using an explicit thread
barrier at the invented provider boundary. Both requests must reach that boundary
before either proceeds; no sleep-based ordering is used. Each answer retains only
its own assumption marker and calculation. This is request isolation, not a
saved/reopened conversation or portfolio-personalization acceptance test.

The first draft of these tests incorrectly assumed a newly provisioned local
owner always differs from the JWT subject. The existing service intentionally
uses the subject for fresh accounts. The test now checks actual provisioning,
and the distinct-local-ID case explicitly seeds an established account with its
own subject grant. No application change was necessary.

## Reproduction

Use CPython 3.11.9 with the repository's pinned dependencies. The local execution
environment contains only test placeholders. An audit hook denies IP sockets,
DNS and connection events; AF_UNIX constructors are allowed for ASGI event loops.

```sh
python -m pytest -q tests/test_conditional_valuation_account_boundary.py tests/test_conditional_valuation_api.py tests/test_launch_security.py tests/test_launch_access_policy.py tests/test_rate_limit_middleware.py tests/test_dependency_pinning.py tests/test_services/test_admission_boundary.py tests/test_services/test_supabase_auth_service.py tests/test_services/test_auth_middleware.py tests/test_auth_scoping.py
python -m pytest tests/ --collect-only -q -o addopts=""
```

## Remaining activation and launch gates

These tests strengthen offline acceptance of the account boundary. They do not
establish live JWT issuance, live JWKS delivery/rotation, deployed database access,
real provider responses, latency, source accuracy, saved research ownership or
answer usefulness. Required CI and review still apply to this exact diff.

The endpoint remains default-off. An actual activation/live test requires separate
authorization bound to reviewed code, environment/configuration, scope, budgets
and fresh execution artifacts. This document is not an approval package and
creates no spending or execution authority. All eleven consumed pilot approvals
remain consumed; no old ledger/output is reset or resumed. Historical run files
were not revalidated in this checkout.

Before proposing another scenario pilot, explicitly review supported source
coverage and question/input adequacy. PR310 currently supports annual USD GAAP
diluted EPS in 10-K/10-K/A, with a current-directory identity boundary. Retained
ASML EUR/20-F and NPK basic-only sources are outside this contract; do not silently
substitute a different basis or expect repeating the old three-issuer cohort to
close those known gaps. Actual user hypotheses must be explicitly supplied,
separate from observations, and must not be invented on the user's behalf.

Independent material-claim and usefulness adjudication, development benchmark
expansion using the existing cohort, reserved holdouts and signed-in saved/reopened
personalization remain necessary before resolving the universal-company launch
blocker. Offline account success does not clear those gates or change a roadmap
completion percentage.

Final local results: **363 related request/auth/admission/security tests passed**,
including **29 new account-boundary cases**. Single-process collection found
**18,098 tests with zero collection errors**. One existing Starlette/AnyIO
BlockingPortal deprecation warning appeared in the related run and collection.
No production code changed, so the earlier calculator/pilot checks are not
presented as rerun results. Full hosted repository CI remains required.
