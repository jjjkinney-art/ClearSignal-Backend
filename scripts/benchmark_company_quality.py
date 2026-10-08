#!/usr/bin/env python3
"""Plan or capture broad company-quality questions in bounded, resumable batches."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validation.benchmark_registry import REGISTRY_PATH, load_registry
from validation.company_quality_matrix import build_matrix, capture_matrix
from validation.intelligence_benchmark import BenchmarkContractError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--family", action="append")
    parser.add_argument("--plan", action="store_true", help="List the complete matrix without execution.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.plan and args.execute:
        parser.error("--plan cannot execute providers")
    if args.execute and os.getenv("CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED") != "true":
        parser.error("--execute requires CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true")
    if args.execute and args.output is None:
        parser.error("--execute requires --output for per-case checkpoints")

    if args.execute and args.output.exists():
        parser.error("capture output already exists; use a new path to preserve previous results")

    def checkpoint(report):
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent, delete=False) as stream:
                json.dump(report, stream, indent=2, sort_keys=True)
                temporary = Path(stream.name)
            os.replace(temporary, args.output)
    try:
        registry = load_registry(args.registry)
        if args.plan:
            report = build_matrix(registry=registry, tickers=args.ticker, families=args.family)
            checkpoint(report)
        else:
            # Provider diagnostics must not corrupt the JSON result stream.
            with redirect_stdout(sys.stderr):
                report = capture_matrix(registry=registry, tickers=args.ticker,
                    families=args.family, offset=args.offset, limit=args.limit,
                    execute=args.execute, checkpoint=checkpoint)
    except BenchmarkContractError as exc:
        parser.error(str(exc))
    if args.output:
        print(json.dumps({"output": str(args.output), "case_count": report["case_count"],
                          "capture_counts": report.get("capture_counts"),
                          "quality_status": report.get("quality_status", "not_executed"),
                          "launch_ready": False, "next_offset": report.get("next_offset")}))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("capture_counts", {}).get("execution_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
