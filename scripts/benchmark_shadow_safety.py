#!/usr/bin/env python3
"""Evaluate shadow benchmark admissions without executing research work."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.shadow_safety import evaluate_payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--require-inert", action="store_true",
        help="fail unless the policy is disabled or dry-run",
    )
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text())
    result = evaluate_payload(payload)
    print(json.dumps(result, indent=2, sort_keys=True))
    snapshot = result["operator_snapshot"]
    if args.require_inert and snapshot["enabled"] and not snapshot["dry_run"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
