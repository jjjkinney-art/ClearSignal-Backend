#!/usr/bin/env python3
"""Check explicit conditional EPS/P-E scenarios offline; distributions excluded."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from validation.valuation_scenario import evaluate_scenario, load_scenario, ValuationContractError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    args = parser.parse_args(argv)
    try:
        with args.input.open(encoding='utf-8') as stream:
            text = stream.read(65537)
        if len(text) > 65536:
            raise ValuationContractError('scenario exceeds 65536-character technical input limit')
        result = evaluate_scenario(load_scenario(text))
    except (ValuationContractError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["available"] else 2


if __name__ == '__main__':
    raise SystemExit(main())
