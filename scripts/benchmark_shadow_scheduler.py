#!/usr/bin/env python3
"""Evaluate one inert synthetic benchmark schedule tick."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.shadow_scheduler import evaluate_schedule_tick


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--require-inert", action="store_true",
        help="fail unless the tick is inert and creates no reservations",
    )
    args = parser.parse_args(argv)
    result = evaluate_schedule_tick(json.loads(args.input.read_text()))
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.require_inert and (
        not result["inert"]
        or result["operator_snapshot"]["active_jobs"] != 0
        or any(item["reservation_id"] is not None for item in result["decisions"])
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
