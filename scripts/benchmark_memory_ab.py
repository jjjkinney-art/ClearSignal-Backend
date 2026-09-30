#!/usr/bin/env python3
"""Score matched control/treatment runs for research-memory personalization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.memory_ab import score_payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--require-safe", action="store_true")
    args = parser.parse_args(argv)
    scorecard = score_payload(json.loads(args.input.read_text()))
    print(json.dumps(scorecard.to_dict(), indent=2, sort_keys=True))
    if args.require_safe and not scorecard.safe_to_expand:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
