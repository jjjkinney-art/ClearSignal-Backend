#!/usr/bin/env python3
"""Reconcile captured company-quality batches into an offline pending-review worksheet."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validation.benchmark_registry import REGISTRY_PATH, load_registry
from validation.company_quality_review import reconcile_captures
from validation.intelligence_benchmark import BenchmarkContractError


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkContractError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise BenchmarkContractError('nonfinite JSON number')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise BenchmarkContractError('nonfinite JSON number')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--batch', type=Path, action='append', default=[])
    parser.add_argument('--registry', type=Path, default=REGISTRY_PATH)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        artifacts = [args.plan, *args.batch, args.registry]
        raw = [path.read_bytes() for path in artifacts]
        values = [json.loads(data, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float) for data in raw]
        report = reconcile_captures(values[0], values[1:-1], registry=load_registry(args.registry))
        report['input_file_sha256'] = [hashlib.sha256(data).hexdigest() for data in raw]
        # Refuse overwrite, including any input file. No provider execution flags.
        with args.output.open('x') as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    except (OSError, ValueError, TypeError, BenchmarkContractError) as exc:
        parser.error(str(exc))
    print(json.dumps({'output': str(args.output), 'capture_counts': report['capture_counts'], 'launch_ready': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
