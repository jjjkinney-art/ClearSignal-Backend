#!/usr/bin/env python3
"""Controlled end-to-end production smoke for authenticated /ask persistence.

This harness performs one explicitly authorized provider-backed analysis in a
uniquely tagged private investigation. It verifies the emitted response,
evidence metadata, exact assistant snapshot, owner-scoped recall, and the new
History thesis record. A finally block removes the conversation and every
new exact-match thesis record created by this run.

It never writes to legacy or shared ticker-wide research stores. The analysis
may use ordinary read-only public-data providers and incurs one real /ask run.
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
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BACKEND_URL = "https://clearsignal-backend-dlsc.onrender.com"
TOKEN_ENV = "CLEARSIGNAL_SMOKE_ACCESS_TOKEN"
CONFIRMATION = "RUN_ONE_REAL_ASK_SMOKE"


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
    timeout: float = 30.0,
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "ClearSignal-Ask-Production-Smoke/1",
    }
    body = None
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8").strip()
            return int(response.status), json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = None
        return int(exc.code), payload


def _check(name: str, status: int | None, passed: bool, detail: str) -> Check:
    return Check(name=name, passed=passed, status=status, detail=detail)


def _history_url(backend: str) -> str:
    return f"{backend}/research/history?{urlencode({'ticker': 'AAPL', 'limit': 100})}"


def _history_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _evidence_metadata(payload: Any) -> dict[str, int]:
    """Count non-empty evidence/source metadata without copying source content."""
    counts = {
        "positive_evidence_counts": 0,
        "evidence_references": 0,
        "source_documents": 0,
        "sources": 0,
        "retrieved_evidence": 0,
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower()
                if normalized == "evidence_count" and isinstance(child, (int, float)) and child > 0:
                    counts["positive_evidence_counts"] += int(child)
                elif normalized in counts and normalized != "positive_evidence_counts":
                    if isinstance(child, list):
                        counts[normalized] += len(child)
                    elif isinstance(child, dict) and child:
                        counts[normalized] += len(child)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return counts


def run_smoke(*, backend_url: str, token: str, marker: str | None = None) -> dict[str, Any]:
    backend = backend_url.rstrip("/")
    marker = marker or f"cs-ask-smoke-{uuid.uuid4().hex}"
    title = f"ClearSignal /ask launch smoke {marker}"
    question = (
        "Using the latest available public filings, what is Apple's largest "
        "operating risk to services growth over the next 12 months? "
        f"[ClearSignal smoke marker: {marker}]"
    )
    conversation_id: str | None = None
    baseline_history_ids: set[str] = set()
    thesis_ids: list[str] = []
    checks: list[Check] = []
    response_payload: dict[str, Any] | None = None
    conversation_cleanup = False
    thesis_cleanup = False

    try:
        status, payload = _request(_history_url(backend), token=token)
        rows = _history_rows(payload)
        history_ready = status == 200 and isinstance(payload, list)
        baseline_history_ids = {
            str(item.get("id")) for item in rows if item.get("id")
        }
        checks.append(_check(
            "history_baseline_captured", status, history_ready,
            "ok" if history_ready else "history_baseline_failed",
        ))
        if not history_ready:
            return _report(
                checks, marker, conversation_cleanup, thesis_cleanup, {},
            )

        status, payload = _request(
            f"{backend}/research/conversations",
            token=token,
            method="POST",
            json_body={"title": title, "tickers": ["AAPL"]},
        )
        conversation_id = payload.get("id") if isinstance(payload, dict) else None
        created = status == 201 and bool(conversation_id)
        checks.append(_check(
            "private_conversation_created", status, created,
            "ok" if created else "conversation_create_failed",
        ))
        if not created:
            return _report(
                checks, marker, conversation_cleanup, thesis_cleanup, {},
            )

        status, payload = _request(
            f"{backend}/ask",
            token=token,
            method="POST",
            timeout=180.0,
            json_body={
                "company_name": "Apple",
                "question": question,
                "intent": "company_analysis",
                "active_ticker": "AAPL",
                "research_conversation_id": conversation_id,
                "research_request_ref": marker[:100],
            },
        )
        response_payload = payload if isinstance(payload, dict) else None
        valid_response = (
            status == 200
            and response_payload is not None
            and "error" not in response_payload
            and response_payload.get("answer") is not None
            and isinstance(response_payload.get("routing"), dict)
        )
        checks.append(_check(
            "ask_response_valid", status, valid_response,
            "ok" if valid_response else "invalid_ask_response",
        ))

        evidence = _evidence_metadata(response_payload or {})
        evidence_present = sum(evidence.values()) > 0
        checks.append(_check(
            "evidence_metadata_present", status, evidence_present,
            "ok" if evidence_present else "no_nonempty_evidence_metadata",
        ))

        status, payload = _request(
            f"{backend}/research/conversations/{conversation_id}", token=token
        )
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        user_messages = [
            item for item in messages
            if isinstance(item, dict)
            and item.get("role") == "user"
            and item.get("text") == question
            and item.get("request_ref") == marker[:100]
        ]
        assistant_messages = [
            item for item in messages
            if isinstance(item, dict)
            and item.get("role") == "assistant"
            and item.get("request_ref") == marker[:100]
        ]
        turn_saved = status == 200 and len(user_messages) == 1 and len(assistant_messages) == 1
        checks.append(_check(
            "completed_private_turn_saved", status, turn_saved,
            "ok" if turn_saved else "saved_turn_mismatch",
        ))
        snapshot = (
            assistant_messages[0].get("displayed_snapshot", {})
            if len(assistant_messages) == 1 else {}
        )
        exact_snapshot = (
            response_payload is not None
            and isinstance(snapshot, dict)
            and snapshot.get("response_version") == 1
            and snapshot.get("response") == response_payload
        )
        checks.append(_check(
            "assistant_snapshot_matches_emitted_response", status, exact_snapshot,
            "ok" if exact_snapshot else "assistant_snapshot_mismatch",
        ))

        status, payload = _request(
            f"{backend}/research/recall",
            token=token,
            method="POST",
            json_body={"query": marker, "ticker": "AAPL", "limit": 3},
        )
        candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
        recalled = status == 200 and any(
            isinstance(item, dict)
            and item.get("conversation", {}).get("id") == conversation_id
            for item in candidates
        )
        checks.append(_check(
            "owner_scoped_recall_verified", status, recalled,
            "ok" if recalled else "recall_mismatch",
        ))

        status, payload = _request(_history_url(backend), token=token)
        rows = _history_rows(payload)
        thesis_ids = [
            str(item["id"]) for item in rows
            if item.get("id")
            and str(item["id"]) not in baseline_history_ids
            and item.get("question") == question
        ]
        thesis_saved = status == 200 and len(thesis_ids) == 1
        checks.append(_check(
            "account_owned_history_record_saved", status, thesis_saved,
            "ok" if thesis_saved else f"exact_new_record_count_{len(thesis_ids)}",
        ))
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        checks.append(_check("ask_smoke_transport", None, False, type(exc).__name__))
    finally:
        if conversation_id:
            try:
                status, payload = _request(
                    f"{backend}/research/conversations/{conversation_id}",
                    token=token,
                    method="DELETE",
                )
                conversation_cleanup = (
                    status == 200
                    and isinstance(payload, dict)
                    and payload.get("deleted") is True
                )
                checks.append(_check(
                    "private_conversation_cleanup", status, conversation_cleanup,
                    "ok" if conversation_cleanup else "conversation_cleanup_failed",
                ))
            except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                checks.append(_check(
                    "private_conversation_cleanup", None, False, type(exc).__name__,
                ))

        # Re-query so a thesis created before a transport failure is still found.
        try:
            status, payload = _request(_history_url(backend), token=token)
            rows = _history_rows(payload)
            discovered = [
                str(item["id"]) for item in rows
                if item.get("id")
                and str(item["id"]) not in baseline_history_ids
                and item.get("question") == question
            ]
            thesis_ids = sorted(set(thesis_ids) | set(discovered))
            results = []
            for thesis_id in thesis_ids:
                delete_status, delete_payload = _request(
                    f"{backend}/research/history/{thesis_id}",
                    token=token,
                    method="DELETE",
                )
                results.append(
                    delete_status == 200
                    and isinstance(delete_payload, dict)
                    and delete_payload.get("deleted") is True
                )
            thesis_cleanup = status == 200 and bool(thesis_ids) and all(results)
            checks.append(_check(
                "history_record_cleanup", status, thesis_cleanup,
                "ok" if thesis_cleanup else "history_cleanup_failed_or_record_missing",
            ))
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append(_check("history_record_cleanup", None, False, type(exc).__name__))

    return _report(
        checks,
        marker,
        conversation_cleanup,
        thesis_cleanup,
        _evidence_metadata(response_payload or {}),
    )


def _report(
    checks: list[Check],
    marker: str,
    conversation_cleanup: bool,
    thesis_cleanup: bool,
    evidence_metadata: dict[str, int],
) -> dict[str, Any]:
    passed = (
        bool(checks)
        and all(check.passed for check in checks)
        and conversation_cleanup
        and thesis_cleanup
    )
    return {
        "schema_version": 1,
        "passed": passed,
        "production_write": True,
        "provider_calls": True,
        "provider_call_limit": 1,
        "scope": "current_account_private_research_memory_and_history",
        "shared_ticker_writes": False,
        "marker": marker,
        "conversation_cleanup_succeeded": conversation_cleanup,
        "history_cleanup_succeeded": thesis_cleanup,
        "evidence_metadata_counts": evidence_metadata,
        "check_count": len(checks),
        "passed_count": sum(check.passed for check in checks),
        "failed_count": sum(not check.passed for check in checks),
        "checks": [asdict(check) for check in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one provider-backed authenticated /ask production smoke"
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--confirm-provider-call")
    args = parser.parse_args()
    if args.confirm_provider_call != CONFIRMATION:
        print(json.dumps({
            "passed": False,
            "detail": "explicit_provider_call_confirmation_required",
            "required_value": CONFIRMATION,
        }, indent=2))
        return 2
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        print(json.dumps({
            "passed": False,
            "detail": f"{TOKEN_ENV}_missing",
        }, indent=2))
        return 2
    report = run_smoke(backend_url=args.backend_url, token=token)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
