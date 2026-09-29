#!/usr/bin/env python3
"""Offline coverage audit for the versioned Intelligence Benchmark registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.benchmark_registry import (
    REGISTRY_PATH,
    audit_registry,
    load_query_fixtures,
    load_registry,
)


DEFAULT_FIXTURES = REPO_ROOT / "validation" / "fixtures.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--strict-targets", action="store_true",
        help="Exit non-zero until all 100-company launch coverage targets are met.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_registry(
        load_registry(args.registry), load_query_fixtures(args.fixtures)
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"registry v{report.registry_version}: {report.registry_sha256}")
        print(f"issuers: {report.issuer_count}; fixtures: {report.fixture_count}")
        print(f"market-cap strata: {dict(report.market_cap_counts)}")
        print(f"sectors: {report.sector_count}; complexity tags: {report.complexity_tag_count}")
        print(f"integrity: {'PASS' if report.integrity_passed else 'FAIL'}")
        print(
            "launch coverage: "
            f"{'READY' if report.launch_coverage_ready else 'INCOMPLETE'}"
        )
        for error in report.integrity_errors:
            print(f"ERROR: {error}")
        for deficit in report.target_deficits:
            print(f"GAP: {deficit}")
    if not report.integrity_passed:
        return 2
    if args.strict_targets and not report.launch_coverage_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
