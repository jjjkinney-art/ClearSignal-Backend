"""Emit the offline expansion proposal; no execute, provider or approval options."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.company_quality_expansion import build_expansion_plan
from validation.intelligence_benchmark import BenchmarkContractError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = build_expansion_plan()
        payload = json.dumps(plan, indent=2, sort_keys=True, allow_nan=False) + '\n'
        with args.output.open('x') as stream:
            stream.write(payload)
    except (OSError, ValueError, BenchmarkContractError):
        parser.error('offline proposal refused; frozen setup and fresh output required')
    print(json.dumps({'output': str(args.output), 'case_count': plan['total']['case_count'],
                      'execution_authorized': False, 'launch_ready': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
