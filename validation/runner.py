#!/usr/bin/env python3
"""Sprint 2A — production-validation CLI runner.

Submits the benchmark fixture suite to a deployed ClearSignal backend's /ask
endpoint, validates every response with validation/validator.py, and writes
JSON + Markdown artifacts. See validation/README.md for full usage.

No secrets are hardcoded: the backend URL and optional auth token are read
from environment variables / CLI flags only.

    python -m validation.runner --dry-run
    VALIDATION_BACKEND_URL=https://... python -m validation.runner --max-queries 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import QueryFixture, QueryOutcome
from .validator import validate
from . import report as report_mod

try:
    import requests
except ImportError:  # pragma: no cover - requests is a project dependency
    requests = None

# Sprint 3A.1 — headers that request authorized detailed observability. Must
# match app/observability.py; duplicated rather than imported because the
# harness is deliberately black-box and never imports the backend package.
OBSERVABILITY_DETAIL_HEADER = "X-ClearSignal-Observability-Detail"
OBSERVABILITY_TOKEN_HEADER = "X-ClearSignal-Observability-Token"
# Sprint 3B.1 — selects an experimental synthesis prompt for an A/B run.
SYNTHESIS_VARIANT_HEADER = "X-ClearSignal-Synthesis-Variant"
# Sprint 3B.2 — selects an alternate synthesis MODEL. Kept separate from the
# prompt-variant header so a model experiment never changes the prompt.
SYNTHESIS_MODEL_VARIANT_HEADER = "X-ClearSignal-Synthesis-Model-Variant"
# Sprint 3B.3 — selects an alternate risk-agent output shape. Independent of
# both synthesis headers so a risk experiment isolates the risk agent alone.
RISK_VARIANT_HEADER = "X-ClearSignal-Risk-Variant"

DEFAULT_TIMEOUT_S = 90.0
DEFAULT_RETRIES = 2
DEFAULT_CONCURRENCY = 1
MAX_ALLOWED_CONCURRENCY = 3  # hard safety ceiling — never raised via CLI flag


def load_fixtures(path: Path) -> List[QueryFixture]:
    data = json.loads(path.read_text())
    return [QueryFixture.from_dict(d) for d in data["fixtures"]]


def build_ask_headers(
    auth_token: Optional[str] = None, profile_token: Optional[str] = None,
    synthesis_variant: Optional[str] = None,
    synthesis_model_variant: Optional[str] = None,
    risk_variant: Optional[str] = None,
) -> Dict[str, str]:
    """Headers for one /ask call.

    The observability-detail pair is added only when a profiling token is
    supplied, so an ordinary validation run sends exactly the headers it always
    did. Kept as its own function so tests can assert on the header set without
    making a request.
    """
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if profile_token:
        headers[OBSERVABILITY_DETAIL_HEADER] = "1"
        headers[OBSERVABILITY_TOKEN_HEADER] = profile_token
    # The variant header is only meaningful alongside the profiling token —
    # the backend ignores it otherwise — so it is sent only when both exist.
    if profile_token and synthesis_variant:
        headers[SYNTHESIS_VARIANT_HEADER] = synthesis_variant
    if profile_token and synthesis_model_variant:
        headers[SYNTHESIS_MODEL_VARIANT_HEADER] = synthesis_model_variant
    if profile_token and risk_variant:
        headers[RISK_VARIANT_HEADER] = risk_variant
    return headers


def _post_ask(base_url: str, fixture: QueryFixture, *, timeout: float,
              auth_token: Optional[str],
              profile_token: Optional[str] = None,
              synthesis_variant: Optional[str] = None,
              synthesis_model_variant: Optional[str] = None,
              risk_variant: Optional[str] = None,
              progressive: bool = False) -> Dict[str, Any]:
    """Single HTTP attempt. Raises on any failure — caller handles retries."""
    url = base_url.rstrip("/") + "/ask"
    payload = {
        "company_name": fixture.ticker,
        "question": fixture.question,
        "intent": "company_analysis",
    }
    headers = build_ask_headers(auth_token, profile_token, synthesis_variant,
                                synthesis_model_variant, risk_variant)
    if progressive:
        headers["Accept"] = PROGRESSIVE_MEDIA_TYPE
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    if progressive or PROGRESSIVE_MEDIA_TYPE in (resp.headers.get("content-type") or ""):
        return extract_final_payload(resp.text)
    return resp.json()


# ── Sprint 3C.1A: progressive protocol ───────────────────────────────────────
# The backend only speaks NDJSON when a caller explicitly asks for it, so the
# default path below is byte-for-byte what it has always been. Progress frames
# are disposable UI state and are discarded here: correctness is evaluated
# solely against the authoritative terminal frame.
PROGRESSIVE_MEDIA_TYPE = "application/x-ndjson"


class IncompleteStreamError(RuntimeError):
    """The stream ended without a terminal frame.

    Treated as a failed attempt rather than a partial success — a truncated
    response must never be scored as a completed query.
    """


def extract_final_payload(body: str) -> Dict[str, Any]:
    """Return the payload from an NDJSON progressive response.

    Raises IncompleteStreamError when no terminal frame arrived, and re-raises
    a backend error frame as a failure so the runner's existing retry path
    handles it exactly like any other failed attempt.
    """
    terminal: Optional[Dict[str, Any]] = None
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue                      # heartbeat no-op
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue                      # tolerate a partial trailing frame
        if not isinstance(frame, dict):
            continue
        if frame.get("type") in ("final", "error"):
            terminal = frame
    if terminal is None:
        raise IncompleteStreamError(
            "progressive stream ended without a final or error frame"
        )
    if terminal.get("type") == "error":
        err = terminal.get("error") or {}
        raise RuntimeError(
            f"backend error frame: {err.get('message', 'unknown')} "
            f"({err.get('error_class', 'unknown')})"
        )
    data = terminal.get("data")
    if not isinstance(data, dict):
        raise IncompleteStreamError("final frame carried no object payload")
    return data


def run_one(
    fixture: QueryFixture, *, base_url: str, timeout: float, retries: int,
    auth_token: Optional[str], profile_token: Optional[str] = None,
    synthesis_variant: Optional[str] = None,
    synthesis_model_variant: Optional[str] = None,
    risk_variant: Optional[str] = None,
    progressive: bool = False,
) -> QueryOutcome:
    outcome = QueryOutcome(fixture=fixture, status="skipped")
    attempts = 0
    last_exc: Optional[Exception] = None
    start = time.monotonic()

    for attempt in range(1, retries + 2):  # first attempt + `retries` retries
        attempts = attempt
        try:
            raw = _post_ask(base_url, fixture, timeout=timeout,
                            auth_token=auth_token, profile_token=profile_token,
                            synthesis_variant=synthesis_variant,
                            synthesis_model_variant=synthesis_model_variant,
                            risk_variant=risk_variant,
                            progressive=progressive)
            outcome.status = "completed"
            outcome.raw_response = raw
            outcome.http_status = 200
            last_exc = None
            break
        except requests.exceptions.Timeout as exc:  # type: ignore[union-attr]
            last_exc = exc
            outcome.status = "timeout"
        except requests.exceptions.HTTPError as exc:  # type: ignore[union-attr]
            last_exc = exc
            outcome.status = "http_error"
            outcome.http_status = getattr(exc.response, "status_code", None)
            # Do not retry a definitive 4xx client error (e.g. 401/413/429 by
            # design); only retry on 5xx / network-level failures.
            if outcome.http_status and 400 <= outcome.http_status < 500:
                break
        except Exception as exc:  # network error, connection reset, DNS, etc.
            last_exc = exc
            outcome.status = "network_error"

        if attempt < retries + 1:
            time.sleep(min(2 ** attempt, 10))  # capped exponential backoff

    outcome.elapsed_s = time.monotonic() - start
    outcome.attempts = attempts
    if last_exc is not None:
        outcome.error = repr(last_exc)

    if outcome.status == "completed":
        thesis, findings, presence = validate(outcome.raw_response, fixture)
        outcome.thesis = thesis
        outcome.findings = findings
        outcome.field_presence = presence

    return outcome


def _load_resume_ids(output_dir: Path) -> set:
    results_path = output_dir / "results.jsonl"
    if not results_path.exists():
        return set()
    done = set()
    for line in results_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if row.get("status") == "completed":
                done.add(row["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def _append_result(output_dir: Path, outcome: QueryOutcome) -> None:
    results_path = output_dir / "results.jsonl"
    with results_path.open("a") as f:
        f.write(json.dumps(outcome.to_dict(include_raw=False)) + "\n")
    if outcome.raw_response is not None:
        raw_dir = output_dir / "raw_responses"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{outcome.fixture.id}.json").write_text(
            json.dumps(outcome.raw_response, indent=2)
        )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend-url", default=os.environ.get("VALIDATION_BACKEND_URL", ""),
                   help="Backend base URL. Defaults to $VALIDATION_BACKEND_URL. Never hardcode this.")
    p.add_argument("--auth-token", default=os.environ.get("VALIDATION_AUTH_TOKEN", ""),
                   help="Optional bearer token. Defaults to $VALIDATION_AUTH_TOKEN. Never pass secrets on the CLI in shared shells.")
    p.add_argument("--fixtures", default=str(Path(__file__).parent / "fixtures.json"),
                   help="Path to the fixture JSON file.")
    p.add_argument("--output-dir", default="", help="Output directory. Defaults to validation/runs/<run-id>.")
    p.add_argument("--run-id", default=time.strftime("%Y%m%dT%H%M%S"), help="Run identifier (used for the default output dir).")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                   help=f"Parallel requests, 1-{MAX_ALLOWED_CONCURRENCY} (safety-capped).")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="Per-request timeout in seconds.")
    p.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Retries on transient failure (5xx/timeout/network).")
    p.add_argument("--max-queries", type=int, default=0, help="Cap the number of queries run this invocation (0 = no cap).")
    p.add_argument("--category", default="", help="Only run fixtures in this category.")
    p.add_argument("--ticker", default="", help="Only run fixtures for this ticker.")
    p.add_argument("--resume", action="store_true", help="Skip fixtures already completed in --output-dir.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the fixture count / estimated request count and exit — no network calls.")
    p.add_argument("--observability-detail", action="store_true",
                   help="Request DETAILED observability (stage timings, model and provider "
                        "calls, token totals) for profiling. Requires the shared secret in "
                        "$VALIDATION_OBSERVABILITY_TOKEN, which must match the backend's "
                        "OBSERVABILITY_PROFILE_TOKEN. The secret is read from the environment "
                        "only — never accepted as a CLI value, never printed, never written "
                        "to run artifacts.")
    p.add_argument("--synthesis-variant", default="",
                   help="Sprint 3B.1 A/B: synthesis prompt variant to request "
                        "(control | compact_a | compact_b). Requires "
                        "--observability-detail and a valid profiling token; "
                        "the backend ignores it for unauthorized callers.")
    p.add_argument("--synthesis-model-variant", default="",
                   help="Sprint 3B.2 A/B: synthesis MODEL variant to request "
                        "(control | fast_a). Separate from --synthesis-variant, "
                        "which selects the prompt; leave that at control for a "
                        "model experiment. Requires --observability-detail and a "
                        "valid profiling token.")
    p.add_argument("--progressive", action="store_true",
                   help="Sprint 3C.1A: request the NDJSON progressive protocol "
                        "(Accept: application/x-ndjson) and evaluate only the "
                        "authoritative final frame. Off by default — the legacy "
                        "single-JSON response is unchanged.")
    p.add_argument("--risk-variant", default="",
                   help="Sprint 3B.3 A/B: risk-agent output-shape variant to "
                        "request (risk_control | risk_fast_a | risk_struct_a). "
                        "Independent of "
                        "--synthesis-variant and --synthesis-model-variant; "
                        "leave both at control for a risk experiment. Requires "
                        "--observability-detail and a valid profiling token.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    fixtures_path = Path(args.fixtures)
    fixtures = load_fixtures(fixtures_path)
    total_in_file = len(fixtures)

    if args.category:
        fixtures = [f for f in fixtures if f.category == args.category]
    if args.ticker:
        fixtures = [f for f in fixtures if f.ticker.upper() == args.ticker.upper()]

    matching_filter = len(fixtures)
    if args.max_queries and args.max_queries > 0:
        fixtures = fixtures[: args.max_queries]

    concurrency = max(1, min(args.concurrency, MAX_ALLOWED_CONCURRENCY))

    # Sprint 3A.1 — profiling secret. Environment only: never a CLI value (it
    # would land in shell history and `ps`), and only consulted when detail was
    # explicitly asked for. Its presence is reported, its value never is.
    _profile_token = ""
    if args.observability_detail:
        _profile_token = os.environ.get("VALIDATION_OBSERVABILITY_TOKEN", "").strip()
        if not _profile_token:
            print(
                "[validation] ERROR: --observability-detail requires "
                "$VALIDATION_OBSERVABILITY_TOKEN to be set.",
                file=sys.stderr,
            )
            return 2

    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "runs" / args.run_id

    print(f"[validation] fixture file:            {fixtures_path}")
    print(f"[validation] total fixtures in file:  {total_in_file}")
    print(f"[validation] matching category/ticker: {matching_filter}")
    print(f"[validation] fixtures selected (after --max-queries): {len(fixtures)}")
    print(f"[validation] concurrency:        {concurrency} (max allowed {MAX_ALLOWED_CONCURRENCY})")
    print(f"[validation] estimated requests: {len(fixtures)} (1 per fixture, plus up to {args.retries} retries each on transient failure)")
    print(f"[validation] output directory:   {output_dir}")
    print(
        "[validation] observability detail: "
        + ("requested (token present)" if _profile_token else "off (compact block)")
    )

    if args.dry_run:
        print("[validation] DRY RUN — no network calls made. Remove --dry-run to execute live.")
        return 0

    if not args.backend_url:
        print("[validation] ERROR: --backend-url or $VALIDATION_BACKEND_URL is required for a live run.", file=sys.stderr)
        return 2
    if requests is None:
        print("[validation] ERROR: the 'requests' package is required for a live run.", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    already_done = _load_resume_ids(output_dir) if args.resume else set()
    if already_done:
        print(f"[validation] resuming — {len(already_done)} fixture(s) already completed, will be skipped.")
    to_run = [f for f in fixtures if f.id not in already_done]

    outcomes: List[QueryOutcome] = []
    print(f"[validation] running {len(to_run)} quer{'y' if len(to_run) == 1 else 'ies'}...")

    def _task(fx: QueryFixture) -> QueryOutcome:
        return run_one(fx, base_url=args.backend_url, timeout=args.timeout,
                       retries=args.retries, auth_token=args.auth_token or None,
                       profile_token=_profile_token or None,
                       synthesis_variant=args.synthesis_variant or None,
                       synthesis_model_variant=args.synthesis_model_variant or None,
                       risk_variant=args.risk_variant or None,
                       progressive=bool(getattr(args, "progressive", False)))

    if concurrency == 1:
        for fx in to_run:
            outcome = _task(fx)
            outcomes.append(outcome)
            _append_result(output_dir, outcome)
            print(f"[validation]   {fx.id}: {outcome.status} ({outcome.elapsed_s:.1f}s, {len(outcome.findings)} findings)")
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {ex.submit(_task, fx): fx for fx in to_run}
            for fut in as_completed(futures):
                outcome = fut.result()
                outcomes.append(outcome)
                _append_result(output_dir, outcome)
                print(f"[validation]   {outcome.fixture.id}: {outcome.status} ({outcome.elapsed_s:.1f}s, {len(outcome.findings)} findings)")

    all_outcomes = outcomes  # this invocation's outcomes; report.py can also re-read results.jsonl for full history
    report_mod.write_artifacts(output_dir, all_outcomes)
    print(f"[validation] done. Artifacts written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
