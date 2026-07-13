"""Sprint 0 — dependency & runtime reproducibility guards.

These tests fail if requirements.txt drifts back to unpinned specifiers or the
Python runtime pin is removed/malformed.  They do not hit the network.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _requirement_lines():
    txt = (_ROOT / "requirements.txt").read_text().splitlines()
    for line in txt:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # strip inline comments
        s = s.split("#", 1)[0].strip()
        if s:
            yield s


def test_requirements_txt_is_fully_pinned():
    unpinned = []
    for req in _requirement_lines():
        # every dependency must be exact-pinned with '=='
        if "==" not in req:
            unpinned.append(req)
        # and must not carry a floating range/wildcard
        if any(tok in req for tok in (">=", "<=", "~=", ">", "<", "*")):
            unpinned.append(req)
    assert not unpinned, f"unpinned requirements found: {unpinned}"


def test_requirements_txt_has_expected_core_pins():
    reqs = list(_requirement_lines())
    joined = " ".join(reqs)
    for pkg in ("fastapi==", "pydantic==", "sqlalchemy==", "PyJWT==", "stripe==", "openai=="):
        assert pkg in joined, f"missing exact pin for {pkg!r}"


def test_requirements_in_exists_as_human_input():
    assert (_ROOT / "requirements.in").exists(), "requirements.in (human source) missing"


def test_runtime_pin_is_python_311():
    runtime = (_ROOT / "runtime.txt").read_text().strip()
    assert re.fullmatch(r"python-3\.11\.\d+", runtime), (
        f"runtime.txt must pin an exact Python 3.11.x, got {runtime!r}"
    )
