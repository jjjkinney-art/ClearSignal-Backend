#!/usr/bin/env python3
"""Rehearse the frozen synthetic benchmark schedule without side effects."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.shadow_rehearsal import run_rehearsal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", required=True, help="timezone-aware evaluation instant")
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"evaluated_at": args.at}
    if args.schedule is not None:
        kwargs["schedule_path"] = args.schedule
    if args.registry is not None:
        kwargs["registry_path"] = args.registry
    result = run_rehearsal(**kwargs)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
