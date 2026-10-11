#!/usr/bin/env python3
"""Grade frozen numerical claims and explicitly adjudicated citations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.factual_citation_grading import grade_payload
from validation.intelligence_benchmark import BenchmarkContractError


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkContractError("duplicate JSON key in grading input")
        result[key] = value
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        scorecard = grade_payload(json.loads(args.input.read_text(), object_pairs_hook=_unique_object))
    except (BenchmarkContractError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(scorecard.to_dict(), indent=2, sort_keys=True))
    if args.require_complete and not scorecard.fully_adjudicated:
        return 2
    return 1 if scorecard.stop_ship_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

