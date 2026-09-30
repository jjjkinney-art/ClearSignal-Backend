#!/usr/bin/env python3
"""Build protected subgroup scorecards from benchmark observations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.subgroup_scorecards import score_payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    scorecard = score_payload(json.loads(args.input.read_text()))
    print(json.dumps(scorecard.to_dict(), indent=2, sort_keys=True))
    if args.require_pass and not scorecard.passed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
