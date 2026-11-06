"""The ordinary pilot tests on the completing runs-1-2 cohort, in their own process.

Run 3 halts at its eleventh case by design, so tests of a fully completing run
(late-answer ruling, degraded-but-complete evidence, twelve answered cases)
execute here, against the unchanged historical cohort, instead of being skipped.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from validation.ordinary_pilot_contract import COHORT


@pytest.mark.skipif(COHORT != 'run3', reason='this process already uses the historical cohort')
@pytest.mark.timeout(1800)
def test_ordinary_pilot_tests_pass_on_the_completing_historical_cohort():
    root = Path(__file__).resolve().parents[1]
    tests = sorted(str(p.relative_to(root)) for p in (root / 'tests').glob('test_ordinary_*.py')
                   if p.name != Path(__file__).name)
    process = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *tests],
                             cwd=root, env={**os.environ, 'ORDINARY_PILOT_COHORT': 'runs-1-2'},
                             capture_output=True, text=True, timeout=1750)
    summary = process.stdout.strip().splitlines()[-1] if process.stdout.strip() else process.stderr[-2000:]
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-2000:]
    assert ' passed' in summary and 'failed' not in summary and 'error' not in summary, summary
