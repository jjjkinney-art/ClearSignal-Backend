"""Cohort 4: the cohort 3 procedure with a new seed and buckets weighted to smaller,
less familiar companies. Fixed in this file before it is applied.

Reads only the retained SEC company directory and the lists of previously studied
issuers. It never reads a filing or company facts and makes no network request.

Usage:
  python -I scripts/select_generalization_cohort_4.py <company_tickers.json> \
      <repo root> <code commit> <exposure> [<exposure> ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import select_generalization_cohort as base  # noqa: E402

base.SEED = "clearsignal-generalization-4:"
# Directory positions, not verified company sizes. None from the top 1,000.
base.BUCKETS = (("mid", 1001, 2500), ("small", 2501, 5000), ("micro", 5001, 9000))
base.PER_BUCKET = 2

if __name__ == "__main__":
    base.main(*sys.argv[1:])
