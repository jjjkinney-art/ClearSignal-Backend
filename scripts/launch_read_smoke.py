#!/usr/bin/env python3
"""Non-mutating production launch smoke checks for ClearSignal.

The access token is read only from CLEARSIGNAL_SMOKE_ACCESS_TOKEN. The script
never prints the token, authorization header, response bodies, account IDs, or
private research content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND_URL = "https://clearsignal-backend-dlsc.onrender.com"
DEFAULT_FRONTEND_URL = "https://ai-intelligence-interface.vercel.app"
TOKEN_ENV = "CLEARSIGNAL_SMOKE_ACCESS_TOKEN"


@dataclass(frozen=True)
class ProbeResult:
    name: str
    passed: bool
    status: int | None
    detail: str


def _request(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "ClearSignal-Launch-Smoke/1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            parsed: Any = None
            if "json" in content_type.lower() and raw:
                parsed = json.loads(raw.decode("utf-8"))
            return (
                int(response.status),
                {key.lower(): value for key, value in response.headers.items()},
                parsed,
            )
    except HTTPError as exc:
        return (
            int(exc.code),
            {key.lower(): value for key, value in exc.headers.items()},
            None,
        )


def _probe(
    name: str,
    request_fn,
    *,
    expected_status: int,
    validator=None,
) -> ProbeResult:
    try:
        status, headers, payload = request_fn()
        if status != expected_status:
            return ProbeResult(name, False, status, f"expected_http_{expected_status}")
        if validator is not None:
            valid, detail = validator(headers, payload)
            if not valid:
                return ProbeResult(name, False, status, detail)
        return ProbeResult(name, True, status, "ok")
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return ProbeResult(name, False, None, type(exc).__name__)


def _is_mapping(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    return (isinstance(payload, dict), "expected_json_object")


def _is_list(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    return (isinstance(payload, list), "expected_json_array")


def _health(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    valid = (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("service") == "clearsignal-backend"
    )
    return valid, "health_contract_mismatch"


def _ready(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    valid = (
        isinstance(payload, dict)
        and payload.get("ready") is True
        and payload.get("db") == "connected"
    )
    return valid, "readiness_contract_mismatch"


def _version(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    valid = (
        isinstance(payload, dict)
        and bool(payload.get("schema_version"))
        and bool(payload.get("build_commit"))
    )
    return valid, "version_contract_mismatch"


def _session(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    valid = (
        isinstance(payload, dict)
        and payload.get("session_active") is True
        and payload.get("is_authenticated") is True
        and payload.get("auth_enabled") is True
        and payload.get("bypass_mode") is False
    )
    return valid, "authenticated_session_contract_mismatch"


def _me(_headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    valid = (
        isinstance(payload, dict)
        and payload.get("is_authenticated") is True
        and bool(payload.get("user_id"))
        and payload.get("bypass_mode") is False
    )
    return valid, "authenticated_identity_contract_mismatch"


def _private_export(headers: dict[str, str], payload: Any) -> tuple[bool, str]:
    cache_control = headers.get("cache-control", "").lower()
    disposition = headers.get("content-disposition", "").lower()
    valid = (
        isinstance(payload, dict)
        and "private" in cache_control
        and "no-store" in cache_control
        and "attachment" in disposition
        and "clearsignal-research-memory.json" in disposition
    )
    return valid, "private_export_contract_mismatch"


def run_smoke(
    *,
    backend_url: str,
    frontend_url: str,
    token: str | None,
    include_authenticated: bool = True,
) -> dict[str, Any]:
    backend = backend_url.rstrip("/")
    frontend = frontend_url.rstrip("/")
    results: list[ProbeResult] = []

    results.extend([
        _probe(
            "backend_health",
            lambda: _request(f"{backend}/health"),
            expected_status=200,
            validator=_health,
        ),
        _probe(
            "backend_readiness",
            lambda: _request(f"{backend}/readyz"),
            expected_status=200,
            validator=_ready,
        ),
        _probe(
            "backend_version",
            lambda: _request(f"{backend}/version"),
            expected_status=200,
            validator=_version,
        ),
        _probe(
            "frontend_intelligence",
            lambda: _request(f"{frontend}/intelligence"),
            expected_status=200,
        ),
        _probe(
            "frontend_history",
            lambda: _request(f"{frontend}/history"),
            expected_status=200,
        ),
    ])

    protected_reads = (
        ("unsigned_conversations_rejected", "/research/conversations?limit=1"),
        ("unsigned_personalization_rejected", "/research/personalization"),
        ("unsigned_notices_rejected", "/research/notices?limit=1"),
        ("unsigned_export_rejected", "/research/export"),
    )
    for name, path in protected_reads:
        results.append(
            _probe(
                name,
                lambda path=path: _request(f"{backend}{path}"),
                expected_status=401,
            )
        )

    if include_authenticated:
        if not token:
            results.append(
                ProbeResult(
                    "authenticated_token_present",
                    False,
                    None,
                    f"{TOKEN_ENV}_missing",
                )
            )
        else:
            results.extend([
                _probe(
                    "authenticated_session",
                    lambda: _request(f"{backend}/auth/session", token=token),
                    expected_status=200,
                    validator=_session,
                ),
                _probe(
                    "authenticated_identity",
                    lambda: _request(f"{backend}/auth/me", token=token),
                    expected_status=200,
                    validator=_me,
                ),
                _probe(
                    "private_conversations_read",
                    lambda: _request(
                        f"{backend}/research/conversations?limit=1",
                        token=token,
                    ),
                    expected_status=200,
                    validator=_is_list,
                ),
                _probe(
                    "private_personalization_read",
                    lambda: _request(
                        f"{backend}/research/personalization",
                        token=token,
                    ),
                    expected_status=200,
                    validator=_is_mapping,
                ),
                _probe(
                    "private_notices_read",
                    lambda: _request(
                        f"{backend}/research/notices?limit=1",
                        token=token,
                    ),
                    expected_status=200,
                    validator=_is_list,
                ),
                _probe(
                    "private_recall_read",
                    lambda: _request(
                        f"{backend}/research/recall",
                        token=token,
                        method="POST",
                        json_body={"query": "launch smoke", "limit": 1},
                    ),
                    expected_status=200,
                    validator=_is_mapping,
                ),
                _probe(
                    "private_export_read",
                    lambda: _request(
                        f"{backend}/research/export",
                        token=token,
                    ),
                    expected_status=200,
                    validator=_private_export,
                ),
            ])

    passed = all(result.passed for result in results)
    return {
        "schema_version": 1,
        "passed": passed,
        "non_mutating": True,
        "authenticated_checks_requested": include_authenticated,
        "token_source": TOKEN_ENV if include_authenticated else None,
        "check_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "failed_count": sum(not result.passed for result in results),
        "checks": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run non-mutating ClearSignal production launch smoke checks."
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND_URL)
    parser.add_argument(
        "--public-only",
        action="store_true",
        help="Skip signed-in private reads; full launch verification requires auth.",
    )
    args = parser.parse_args()

    token = None if args.public_only else os.environ.get(TOKEN_ENV, "").strip() or None
    report = run_smoke(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        token=token,
        include_authenticated=not args.public_only,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
