#!/usr/bin/env python3
"""Explicit, owner-scoped production write smoke for private research memory.

The harness creates one uniquely tagged private conversation and one user
message, verifies direct read and deterministic recall, then soft-deletes the
conversation in a finally block. It never calls /ask, model providers, shared
ticker-wide stores, notices, personalization, portfolios, or billing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND_URL = "https://clearsignal-backend-dlsc.onrender.com"
TOKEN_ENV = "CLEARSIGNAL_SMOKE_ACCESS_TOKEN"
CONFIRMATION = "WRITE_PRIVATE_RESEARCH_MEMORY"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    status: int | None
    detail: str


def _request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ClearSignal-Research-Memory-Write-Smoke/1",
    }
    body = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else None
            return int(response.status), payload
    except HTTPError as exc:
        return int(exc.code), None


def _check(name: str, status: int | None, passed: bool, detail: str) -> Check:
    return Check(name=name, passed=passed, status=status, detail=detail)


def run_smoke(*, backend_url: str, token: str, marker: str | None = None) -> dict[str, Any]:
    backend = backend_url.rstrip("/")
    marker = marker or f"cs-write-smoke-{uuid.uuid4().hex}"
    title = f"ClearSignal launch write smoke {marker}"
    message_text = f"Private memory verification marker {marker}"
    conversation_id: str | None = None
    checks: list[Check] = []
    cleanup_attempted = False
    cleanup_succeeded = False

    try:
        status, payload = _request(
            f"{backend}/research/conversations",
            token=token,
            method="POST",
            json_body={"title": title, "tickers": []},
        )
        conversation_id = payload.get("id") if isinstance(payload, dict) else None
        created = status == 201 and bool(conversation_id)
        checks.append(_check("private_conversation_created", status, created,
                             "ok" if created else "create_failed"))
        if not created:
            return _report(checks, marker, cleanup_attempted, cleanup_succeeded)

        status, payload = _request(
            f"{backend}/research/conversations/{conversation_id}/messages",
            token=token,
            method="POST",
            json_body={"text": message_text, "request_ref": marker[:100]},
        )
        appended = (
            status == 201
            and isinstance(payload, dict)
            and payload.get("role") == "user"
            and payload.get("text") == message_text
        )
        checks.append(_check("private_message_appended", status, appended,
                             "ok" if appended else "append_failed"))

        status, payload = _request(
            f"{backend}/research/conversations/{conversation_id}", token=token
        )
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        direct = (
            status == 200
            and payload.get("id") == conversation_id
            and any(item.get("text") == message_text for item in messages if isinstance(item, dict))
        ) if isinstance(payload, dict) else False
        checks.append(_check("private_direct_read_verified", status, direct,
                             "ok" if direct else "direct_read_mismatch"))

        status, payload = _request(
            f"{backend}/research/recall",
            token=token,
            method="POST",
            json_body={"query": marker, "limit": 3},
        )
        candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
        recalled = status == 200 and any(
            item.get("conversation", {}).get("id") == conversation_id
            for item in candidates if isinstance(item, dict)
        )
        checks.append(_check("owner_scoped_recall_verified", status, recalled,
                             "ok" if recalled else "recall_mismatch"))
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        checks.append(_check("write_smoke_transport", None, False, type(exc).__name__))
    finally:
        if conversation_id:
            cleanup_attempted = True
            try:
                status, payload = _request(
                    f"{backend}/research/conversations/{conversation_id}",
                    token=token,
                    method="DELETE",
                )
                cleanup_succeeded = (
                    status == 200
                    and isinstance(payload, dict)
                    and payload.get("deleted") is True
                )
                checks.append(_check("private_cleanup_completed", status, cleanup_succeeded,
                                     "ok" if cleanup_succeeded else "cleanup_failed"))
                status, _payload = _request(
                    f"{backend}/research/conversations/{conversation_id}", token=token
                )
                hidden = status == 404
                checks.append(_check("deleted_record_hidden", status, hidden,
                                     "ok" if hidden else "deleted_record_visible"))
                status, payload = _request(
                    f"{backend}/research/recall",
                    token=token,
                    method="POST",
                    json_body={"query": marker, "limit": 3},
                )
                candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
                absent = status == 200 and not any(
                    item.get("conversation", {}).get("id") == conversation_id
                    for item in candidates if isinstance(item, dict)
                )
                checks.append(_check("deleted_record_excluded_from_recall", status, absent,
                                     "ok" if absent else "deleted_record_recalled"))
            except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                checks.append(_check("private_cleanup_completed", None, False, type(exc).__name__))

    return _report(checks, marker, cleanup_attempted, cleanup_succeeded)


def _report(checks: list[Check], marker: str, cleanup_attempted: bool,
            cleanup_succeeded: bool) -> dict[str, Any]:
    passed = bool(checks) and all(check.passed for check in checks) and cleanup_succeeded
    return {
        "schema_version": 1,
        "passed": passed,
        "production_write": True,
        "scope": "current_account_private_research_memory_only",
        "shared_ticker_writes": False,
        "provider_calls": False,
        "marker": marker,
        "cleanup_attempted": cleanup_attempted,
        "cleanup_succeeded": cleanup_succeeded,
        "check_count": len(checks),
        "passed_count": sum(check.passed for check in checks),
        "failed_count": sum(not check.passed for check in checks),
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private research-memory write smoke")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--confirm-production-write")
    args = parser.parse_args()
    if args.confirm_production_write != CONFIRMATION:
        print(json.dumps({"passed": False, "detail": "explicit_confirmation_required"}, indent=2))
        return 2
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(json.dumps({"passed": False, "detail": f"{TOKEN_ENV}_missing"}, indent=2))
        return 2
    report = run_smoke(backend_url=args.backend_url, token=token)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
