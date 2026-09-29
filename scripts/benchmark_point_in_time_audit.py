#!/usr/bin/env python3
"""Audit a JSON source manifest for point-in-time look-ahead leakage."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.point_in_time_sources import audit_point_in_time_sources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args(argv)
    payload = json.loads(args.manifest.read_text())
    report = audit_point_in_time_sources(
        as_of=str(payload["as_of"]), records=payload.get("sources", [])
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"as of: {report.as_of}")
        print(f"admitted: {len(report.admitted)}")
        print(f"rejected: {len(report.rejected_source_ids)}")
        print(f"look-ahead leakage: {report.lookahead_leakage_count}")
        print(f"integrity: {'PASS' if report.passed else 'FAIL'}")
        for finding in report.findings:
            print(
                f"{finding.severity.value.upper()}: {finding.source_id}: "
                f"{finding.code}: {finding.message}"
            )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

