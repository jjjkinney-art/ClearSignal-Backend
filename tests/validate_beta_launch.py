"""Controlled-beta launch gate.

This validator extends the authenticated production acceptance check with the
two operational snapshots that determine whether invited users can be admitted
safely: billing and continuous delivery.  It is read-only and never prints or
persists the bearer token.

Exit codes:
    0  all requested beta checks passed
    1  one or more checks failed
    2  authenticated checks are blocked because no token was supplied
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    from tests.validate_production_acceptance import (
        CheckResult,
        DEFAULT_BACKEND_URL,
        HttpClient,
        run_acceptance,
    )
except ModuleNotFoundError:  # Direct execution: python tests/validate_beta_launch.py
    from validate_production_acceptance import (  # type: ignore[no-redef]
        CheckResult,
        DEFAULT_BACKEND_URL,
        HttpClient,
        run_acceptance,
    )


def run_beta_readiness(
    client: HttpClient,
    *,
    token: str | None,
    admin_token: str | None = None,
    expected_commit: str | None = None,
    paid_beta: bool = False,
    allow_live_delivery: bool = False,
) -> tuple[list[CheckResult], bool]:
    """Return beta-readiness results and whether auth is blocked."""
    results, blocked = run_acceptance(
        client,
        token=token,
        expected_commit=expected_commit,
        include_analysis=False,
    )
    if blocked or not token:
        return results, True

    # Product acceptance deliberately uses a non-admin beta account. Operator
    # snapshots are protected by the central /admin boundary and therefore
    # require a distinct short-lived admin credential. Never silently reuse
    # the beta user's token: doing so makes a correct production policy return
    # 403 and obscures which boundary was actually exercised.
    if not admin_token:
        return results, True

    status, billing = client.request(
        "GET", "/admin/billing-status", token=admin_token
    )
    billing = billing if isinstance(billing, dict) else {}
    billing_ready = (
        billing.get("billing_live_ready") is True
        if paid_beta
        else billing.get("safe_state") is True
    )
    results.append(CheckResult(
        "billing_mode",
        status == 200 and billing_ready,
        f"http={status} mode={'paid' if paid_beta else 'free'} "
        f"ready={billing_ready}",
    ))

    status, loop = client.request("GET", "/admin/loop/status", token=admin_token)
    loop = loop if isinstance(loop, dict) else {}
    delivery = loop.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    results.extend([
        CheckResult(
            "loop_snapshot",
            status == 200
            and loop.get("status") == "ok"
            and loop.get("db_available") is True,
            f"http={status} db_available={loop.get('db_available')!r}",
        ),
        CheckResult(
            "zero_duplicate_delivery",
            delivery.get("duplicate_total") == 0,
            f"duplicate_total={delivery.get('duplicate_total')!r}",
        ),
        CheckResult(
            "delivery_mode",
            (
                loop.get("effective_enabled") is True
                and loop.get("loop_shadow") is False
                if allow_live_delivery
                else (
                    loop.get("effective_enabled") is False
                    or loop.get("loop_shadow") is True
                )
            ),
            f"mode={'live' if allow_live_delivery else 'shadow'} "
            f"effective_enabled={loop.get('effective_enabled')!r} "
            f"loop_shadow={loop.get('loop_shadow')!r}",
        ),
    ])
    return results, False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL)
    )
    parser.add_argument(
        "--expected-commit", default=os.environ.get("EXPECTED_BUILD_COMMIT")
    )
    parser.add_argument(
        "--paid-beta",
        action="store_true",
        help="require Stripe and entitlement enforcement to be live-ready",
    )
    parser.add_argument(
        "--allow-live-delivery",
        action="store_true",
        help="require the continuous loop to be enabled outside shadow mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    results, blocked = run_beta_readiness(
        HttpClient(args.url),
        token=os.environ.get("CLEARSIGNAL_ACCESS_TOKEN"),
        admin_token=os.environ.get("CLEARSIGNAL_ADMIN_ACCESS_TOKEN"),
        expected_commit=args.expected_commit,
        paid_beta=args.paid_beta,
        allow_live_delivery=args.allow_live_delivery,
    )
    for result in results:
        label = "PASS" if result.passed else "FAIL"
        suffix = f" ({result.detail})" if result.detail else ""
        print(f"{label:4} {result.name}{suffix}")

    if any(not result.passed for result in results):
        return 1
    if blocked:
        print(
            "BLOCK authenticated beta checks require both "
            "CLEARSIGNAL_ACCESS_TOKEN and CLEARSIGNAL_ADMIN_ACCESS_TOKEN; "
            "tokens are never printed or persisted."
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
