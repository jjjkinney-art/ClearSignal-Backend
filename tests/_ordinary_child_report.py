"""What a child pytest process ran. A child that exits 0 can still have skipped everything."""
from collections import Counter
from xml.etree import ElementTree


def read_junit(path):
    """Per-test outcomes from a pytest JUnit report: (module, function, status)."""
    rows = []
    for case in ElementTree.parse(path).getroot().iter('testcase'):
        status = 'passed'
        for child in case:
            if child.tag in {'failure', 'error', 'skipped'}:
                status = {'failure': 'failed', 'error': 'error', 'skipped': 'skipped'}[child.tag]
                break
        rows.append((case.get('classname', '').rsplit('.', 1)[-1], case.get('name', '').split('[')[0], status))
    return rows


def child_counts(rows, returncode):
    counts = Counter(status for _, _, status in rows)
    per_module = {}
    for module, _, status in rows:
        per_module.setdefault(module, Counter())[status] += 1
    return {'returncode': returncode, 'collected': len(rows), 'passed': counts['passed'], 'failed': counts['failed'],
            'error': counts['error'], 'skipped': counts['skipped'],
            'per_module': {m: dict(c) for m, c in sorted(per_module.items())},
            'skipped_tests': sorted(f'{m}::{f}' for m, f, status in rows if status == 'skipped'),
            'failed_tests': sorted(f'{m}::{f}' for m, f, status in rows if status in {'failed', 'error'})}


def child_problems(rows, returncode, *, required, allowed_skips=None):
    """Why a child run does not count. ``allowed_skips=None`` checks required tests only."""
    problems = [] if returncode == 0 else [f'child exited {returncode}']
    if not rows:
        problems.append('child collected no tests')
    outcomes = {}
    for module, function, status in rows:
        outcomes.setdefault((module, function), []).append(status)
    for key in sorted(required):
        if key not in outcomes:
            problems.append(f'required test missing: {key}')
        elif set(outcomes[key]) != {'passed'}:
            problems.append(f'required test not passed: {key} {sorted(set(outcomes[key]))}')
    for key, statuses in sorted(outcomes.items()):
        if {'failed', 'error'} & set(statuses):
            problems.append(f'test failed: {key}')
        if allowed_skips is not None and 'skipped' in statuses and key not in allowed_skips:
            problems.append(f'unexpected skip: {key}')
    return problems
