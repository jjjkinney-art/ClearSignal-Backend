"""Fresh-process twelve-case rehearsal launcher; no live or resume option."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from validation.capture_budget import BudgetError
from validation.pilot_policy import AUDITED_DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('happy', 'wire_connect_failure', 'wire_read_failure')


def run_rehearsal(output_dir, *, scenario='happy'):
    if (type(scenario) is not str or scenario not in SCENARIOS
            or sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 11, 9)
            or {name: importlib.metadata.version(name) for name in AUDITED_DEPENDENCIES}
            != dict(AUDITED_DEPENDENCIES)):
        raise BudgetError('ordinary rehearsal runtime or scenario refused')
    output = Path(output_dir).absolute()
    if output.is_symlink() or output.resolve() != output:
        raise BudgetError('ordinary rehearsal output must have a canonical fresh path')
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    (output / 'isolated-home').mkdir(mode=0o700)
    code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
            'from validation._ordinary_rehearsal_worker import main; raise SystemExit(main())')
    try:
        child = subprocess.run([sys.executable, '-I', '-B', '-c', code, scenario], cwd=output,
                               env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=480)
    except subprocess.TimeoutExpired:
        return {'status': 'worker_incomplete', 'execution_authorized': False}
    artifact = output / 'result.json'
    if child.returncode or not artifact.is_file() or artifact.is_symlink():
        return {'status': 'worker_incomplete', 'execution_authorized': False}
    return json.loads(artifact.read_text())
