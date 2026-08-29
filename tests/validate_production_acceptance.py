"""Read-only production acceptance gate for the current authenticated launch.

The validator never prints or persists the bearer token.  Its default path
uses a deterministic comparative question that does not invoke the LLM
pipeline.  A full ``/analyze`` request is available only through an explicit
flag because it consumes provider capacity.

Exit codes:
    0  all requested checks passed
    1  one or more checks failed
    2  public checks passed, but no access token was supplied
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND_URL = "https://clearsignal-backend-dlsc.onrender.com"
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


class HttpClient:
    def __init__(self, base_url: str, timeout: float = 95.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> tuple[int, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "User-Agent": "ClearSignal-acceptance/1"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        except (URLError, TimeoutError) as exc:
            return 0, {"network_error": str(exc)}

        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"raw": raw[:500]}


def run_acceptance(
    client: HttpClient,
    *,
    token: str | None,
    expected_commit: str | None = None,
    include_analysis: bool = False,
) -> tuple[list[CheckResult], bool]:
    results: list[CheckResult] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append(CheckResult(name, passed, detail))

    status, health = client.request("GET", "/health")
    health_ok = status == 200 and health.get("status") == "ok"
    check("public_health", health_ok, f"http={status} status={health.get('status')!r}")
    check(
        "production_environment",
        health_ok and health.get("environment") == "production",
        f"environment={health.get('environment')!r}",
    )
    if expected_commit:
        deployed = str(health.get("build_commit") or "")
        check(
            "expected_build_commit",
            bool(deployed)
            and (
                deployed.startswith(expected_commit)
                or expected_commit.startswith(deployed)
            ),
            f"deployed={deployed!r} expected_prefix={expected_commit[:12]!r}",
        )

    status, _ = client.request(
        "POST",
        "/ask",
        payload={"company_name": "", "question": "Compare NVDA vs AMD"},
    )
    check("anonymous_ask_rejected", status == 401, f"http={status}")

    if not token:
        return results, True

    status, session = client.request("GET", "/auth/session", token=token)
    check(
        "authenticated_session",
        status == 200
        and session.get("session_active") is True
        and session.get("is_authenticated") is True
        and session.get("auth_enabled") is True
        and session.get("bypass_mode") is False,
        f"http={status} active={session.get('session_active')!r} "
        f"authenticated={session.get('is_authenticated')!r}",
    )

    status, me = client.request("GET", "/auth/me", token=token)
    user_id = me.get("user_id")
    check(
        "authenticated_identity",
        status == 200
        and bool(user_id)
        and user_id != SYSTEM_USER_ID
        and me.get("is_authenticated") is True
        and me.get("bypass_mode") is False,
        f"http={status} real_user={bool(user_id and user_id != SYSTEM_USER_ID)}",
    )

    status, billing = client.request("GET", "/billing/status", token=token)
    check(
        "billing_status",
        status == 200
        and billing.get("plan") in {"free", "pro", "teams", "institutional"}
        and isinstance(billing.get("entitlements"), dict),
        f"http={status} plan={billing.get('plan')!r}",
    )

    status, answer = client.request(
        "POST",
        "/ask",
        token=token,
        payload={"company_name": "", "question": "Compare NVDA vs AMD"},
    )
    routing = answer.get("routing") if isinstance(answer, dict) else {}
    routing = routing if isinstance(routing, dict) else {}
    check(
        "deterministic_authenticated_ask",
        status == 200
        and routing.get("pipeline") == "comparative_ranking"
        and routing.get("detected_tickers") == ["NVDA", "AMD"],
        f"http={status} pipeline={routing.get('pipeline')!r} "
        f"tickers={routing.get('detected_tickers')!r}",
    )

    if include_analysis:
        status, analysis = client.request(
            "POST",
            "/analyze",
            token=token,
            payload={
                "company_name": "AAPL",
                "user_question": "What is the current investment thesis?",
                "analysis_depth": "standard",
            },
        )
        check(
            "full_authenticated_analysis",
            status == 200 and isinstance(analysis, dict) and bool(analysis),
            f"http={status} response_object={isinstance(analysis, dict)}",
        )

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
        "--include-analysis",
        action="store_true",
        help="also run one provider-backed /analyze request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    results, blocked = run_acceptance(
        HttpClient(args.url),
        token=os.environ.get("CLEARSIGNAL_ACCESS_TOKEN"),
        expected_commit=args.expected_commit,
        include_analysis=args.include_analysis,
    )

    for result in results:
        label = "PASS" if result.passed else "FAIL"
        suffix = f" ({result.detail})" if result.detail else ""
        print(f"{label:4} {result.name}{suffix}")

    if any(not result.passed for result in results):
        return 1
    if blocked:
        print(
            "BLOCK authenticated checks require CLEARSIGNAL_ACCESS_TOKEN; "
            "the token is never printed or persisted."
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
