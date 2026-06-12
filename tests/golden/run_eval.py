"""
Phase 9G · Slice 5B — golden-set evaluation CLI.

Runs the 3-way (OFF / TRUE / POISON) harness over the golden set, scores it, and
prints the PASS/FAIL report. Fully offline-safe: with no ``OPENAI_API_KEY`` it
still runs every mechanical gate (token cap, OFF-zero-bytes, poison cap) and
marks the behavioural gates SKIPPED.

  python3 -m tests.golden.run_eval                 # all cases
  python3 -m tests.golden.run_eval --ticker NVDA   # one ticker
  python3 -m tests.golden.run_eval --json out.json # also dump raw records+scores

This harness NEVER enables injection in production and never calls the live
``/ask`` route — it builds prompts in-process and (optionally) calls the model
client directly.
"""

from __future__ import annotations

import argparse
import json
import sys

from .golden_set import GOLDEN_CASES
from .harness import run_harness, get_model_client
from .scoring import score_records, format_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Slice 5B dossier-injection golden-set eval")
    ap.add_argument("--ticker", help="restrict to a single ticker (e.g. NVDA)")
    ap.add_argument("--json", help="path to dump raw records + scores as JSON")
    args = ap.parse_args(argv)

    cases = GOLDEN_CASES
    if args.ticker:
        t = args.ticker.upper()
        cases = [c for c in GOLDEN_CASES if c.ticker == t]
        if not cases:
            print(f"No golden cases for ticker {t!r}", file=sys.stderr)
            return 2

    client = get_model_client()
    if client is None:
        print("[run_eval] no model client (no OPENAI_API_KEY) — "
              "running MECHANICAL gates only.\n")

    records = run_harness(cases, client=client)
    scored = score_records(records)
    print(format_report(scored))

    if args.json:
        # Drop the bulky prompt text from the dump to keep it readable.
        slim = [{k: v for k, v in r.items() if k != "prompt"} for r in records]
        with open(args.json, "w") as fh:
            json.dump({"records": slim, "scores": scored}, fh, indent=2, default=str)
        print(f"\n[run_eval] wrote {args.json}")

    # Exit non-zero on FAIL so CI can gate on it.
    return 0 if scored["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
