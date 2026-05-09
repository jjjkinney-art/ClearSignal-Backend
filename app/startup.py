"""
Startup diagnostics for the AI analyst backend.

This module contains only stdlib imports so it can be safely imported by
tests on Python 3.9 without pulling in api.py (which uses 3.10+ union-type
syntax ``list | dict`` in annotations).
"""

from __future__ import annotations

import os


def print_startup_diagnostics() -> None:
    """Print key-presence diagnostics to stdout at server startup.

    Prints whether FRED_API_KEY and OPENAI_API_KEY are set, with clear
    WARNING / CRITICAL labels when they are absent.  The actual key values
    are never logged — only the boolean presence and byte-length.
    """
    fred_key   = os.environ.get("FRED_API_KEY",   "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    print("=" * 60)
    print("[STARTUP] AI Analyst Backend — environment check")
    print(f"[STARTUP] FRED_API_KEY present:   {bool(fred_key)}  (len={len(fred_key)})")
    print(f"[STARTUP] OPENAI_API_KEY present: {bool(openai_key)}  (len={len(openai_key)})")

    if not fred_key:
        print(
            "[STARTUP] WARNING: FRED_API_KEY not set — live macro evidence will be "
            "skipped and all answers will fall back to conceptual reasoning."
        )
    if not openai_key:
        print(
            "[STARTUP] CRITICAL: OPENAI_API_KEY not set — the ModelClient has no "
            "OpenAI connection.  Every call to /api/ask will raise RuntimeError "
            "until OPENAI_API_KEY is added to the environment."
        )
    print("=" * 60)
