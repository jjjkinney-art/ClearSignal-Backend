#!/usr/bin/env python3
"""Run the frozen six-company ClearSignal product-output acceptance gate."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.product_output_acceptance import run_product_output_acceptance


DEFAULT_MANIFEST = (
    REPO_ROOT / "validation" / "product_output_acceptance.v1.json"
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.execute and os.getenv("CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED") != "true":
        parser.error(
            "--execute requires CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED=true"
        )
    result = run_product_output_acceptance(
        json.loads(args.manifest.read_text()), execute=args.execute,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if not args.execute:
        return 0
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
