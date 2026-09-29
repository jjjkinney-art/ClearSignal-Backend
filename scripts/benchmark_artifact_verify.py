#!/usr/bin/env python3
"""Verify immutable Intelligence Benchmark run bundles and shadow ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.benchmark_artifacts import BenchmarkArtifactStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Artifact-store root to verify")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args(argv)
    report = BenchmarkArtifactStore(args.root).verify()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"runs checked: {report.checked_runs}")
        print(f"ledger entries checked: {report.checked_ledger_entries}")
        print(f"integrity: {'PASS' if report.valid else 'FAIL'}")
        for error in report.errors:
            print(f"ERROR: {error}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

