"""The CI scheduler: same files and flags, nothing lost, and failures still fail.

Runs scripts/ci_isolated_regression.sh on throwaway files with a stand-in Python,
so no real test run happens here. Files are named explicitly because macOS bash
3.2 has no mapfile; CI uses its discovery path, pinned by the text checks below.
"""
from pathlib import Path
import os
import subprocess

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "ci_isolated_regression.sh"
_STAND_IN = """#!/bin/bash
file="${@: -1}"
printf '%s\\n' "$*" >> "$CALLS"
case "$file" in
  *pass*) echo "1 passed in 0.01s"; exit 0 ;;
  *retired*) echo "1 skipped in 0.01s"; exit 5 ;;
  *empty*) echo "no tests ran in 0.01s"; exit 5 ;;
  *lost*) kill -9 "$PPID"; sleep 1; exit 0 ;;
  *) echo "1 failed in 0.01s"; exit 1 ;;
esac
"""


def run(tmp_path, *names, workers="4"):
    stand_in, calls = tmp_path / "python", tmp_path / "calls"
    stand_in.write_text(_STAND_IN)
    stand_in.chmod(0o755)
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    done = subprocess.run(["bash", str(_SCRIPT), *names], cwd=tmp_path, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PY": str(stand_in), "CALLS": str(calls), "WORKERS": workers})
    return done, calls.read_text().splitlines() if calls.exists() else []


def test_every_file_runs_once_in_its_own_process_with_the_same_flags(tmp_path):
    names = [f"tests/test_pass_{i}.py" for i in range(9)]
    done, calls = run(tmp_path, *names)
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(calls) == sorted(f'-m pytest -q -o addopts= --disable-warnings --tb=short {n}' for n in names)
    assert [line[4:] for line in done.stdout.splitlines() if line.startswith("=== ")] == names


def test_a_failing_file_fails_the_job_and_is_named(tmp_path):
    done, _ = run(tmp_path, "tests/test_pass_a.py", "tests/test_bad.py", "tests/test_ordinary_bad.py")
    assert done.returncode == 1
    assert " - tests/test_bad.py" in done.stdout and " - tests/test_ordinary_bad.py" in done.stdout


def test_status_five_passes_only_with_an_explicit_skip(tmp_path):
    assert run(tmp_path, "tests/test_retired.py")[0].returncode == 0
    done, _ = run(tmp_path, "tests/test_empty.py")
    assert done.returncode == 1 and " - tests/test_empty.py" in done.stdout


def test_a_file_with_no_result_fails_the_job(tmp_path):
    done, _ = run(tmp_path, "tests/test_pass_a.py", "tests/test_lost.py", workers="1")
    assert done.returncode == 1
    assert " - tests/test_lost.py (no result)" in done.stdout


def test_sensitive_files_run_serially_after_the_pool(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pass_ports.py").write_text("PORT = 8443\n")
    done, calls = run(tmp_path, "tests/test_pass_a.py", "tests/test_ordinary_pass.py", "tests/test_pilot_pass.py",
                      "tests/test_pass_ports.py")
    assert done.returncode == 0
    assert "pool=1" in done.stdout and "serial=3" in done.stdout
    assert calls[0].endswith("tests/test_pass_a.py")


def test_ci_uses_the_script_and_the_script_discovers_every_test_file():
    text = _SCRIPT.read_text()
    assert "find tests -name 'test_*.py' -print0 | sort -z" in text
    assert '-m pytest -q -o addopts="" --disable-warnings --tb=short "$f"' in text
    assert "bash scripts/ci_isolated_regression.sh" in (_ROOT / ".github" / "workflows" / "ci.yml").read_text()
