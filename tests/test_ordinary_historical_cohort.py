"""The ordinary pilot tests on the completing runs-1-2 cohort, in their own process.

Run 3 leaves a case unresolved while the pinned frontend sends it as general,
so tests of twelve answered cases also execute here, against the unchanged
historical cohort, instead of being skipped.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from _ordinary_child_report import child_problems, read_junit
from _ordinary_cohort_expectations import ORIGINAL_QUOTA_SHAPE_TESTS
from validation.ordinary_pilot_contract import APPROVED_COHORT, COHORT


@pytest.mark.skipif(COHORT != APPROVED_COHORT, reason='this process already uses the historical cohort')
@pytest.mark.timeout(1800)
def test_ordinary_pilot_tests_pass_on_the_completing_historical_cohort(tmp_path):
    root = Path(__file__).resolve().parents[1]
    tests = sorted(str(p.relative_to(root)) for p in (root / 'tests').glob('test_ordinary_*.py')
                   if p.name != Path(__file__).name)
    junit = tmp_path / 'historical.xml'
    process = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                              f'--junitxml={junit}', *tests],
                             cwd=root, env={**os.environ, 'ORDINARY_PILOT_COHORT': 'runs-1-2'},
                             capture_output=True, text=True, timeout=1750)
    summary = process.stdout.strip().splitlines()[-1] if process.stdout.strip() else process.stderr[-2000:]
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-2000:]
    assert ' passed' in summary and 'failed' not in summary and 'error' not in summary, summary
    # These skip under the approved cohort's profile, so here they must really have run.
    required = {(module, name) for module, names in ORIGINAL_QUOTA_SHAPE_TESTS.items() for name in names}
    assert child_problems(read_junit(junit), process.returncode, required=required) == []
