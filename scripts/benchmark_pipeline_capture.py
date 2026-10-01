#!/usr/bin/env python3
"""Validate or execute a synthetic, side-effect-disabled pipeline capture."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.pipeline_capture import capture_pipeline_outputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--execute", action="store_true",
        help="Run providers and the analysis pipeline; disabled by default.",
    )
    args = parser.parse_args(argv)
    if args.execute and os.getenv("CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED") != "true":
        parser.error(
            "--execute requires CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true"
        )
    result = capture_pipeline_outputs(
        json.loads(args.input.read_text()), execute=args.execute,
    )
    payload = result.to_dict()
    # The executed document is accepted directly by benchmark_generated_outputs.
    if args.execute:
        payload = {
            "schema_version": 1,
            "run_id": result.run_id,
            "cases": list(result.captured_cases),
            "capture_safety": {
                "research_memory_enabled": result.research_memory_enabled,
                "persistence_enabled": result.persistence_enabled,
                "notification_delivery_enabled": result.notification_delivery_enabled,
            },
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
