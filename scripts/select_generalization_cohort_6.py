"""Generalization cohort 6: the cohort 5 procedure with a new seed, a newer retained directory and
extended exclusions. Fixed in this file, and committed, before it is applied.

Reads only the retained SEC company directory (company_tickers.json, the bytes retained in the
Run 11 ledger, sha256 a04725d9ea575489715bd16544f1cdcd420080fd81b8d8779dbb5ee19cdc62cb) and the lists
of previously studied issuers. It never reads a filing, company facts or any answer-bearing source and
makes no network request.

Rule (identical to cohort 5 except the seed, the directory and the exclusion inputs):
  * seed "clearsignal-generalization-6:"; an issuer's rank is sha256(seed + ticker), lowest first;
  * buckets by directory position, not by verified company size: 1,001-2,500, 2,501-5,000 and
    5,001-9,000, two issuers each, none from the top 1,000;
  * eligible: a ticker of 1-5 capital letters, and no fund, trust, ETF, acquisition, SPAC, BDC, REIT,
    partnership, income, portfolio or merger term in the registrant name;
  * excluded by CIK, which removes every alternate ticker of an issuer: (a) every issuer in a pilot
    Run 1-11 cohort or with any SEC response in a Run 1-11 ledger; (b) every issuer whose ticker, CIK
    or name appears in app/, tests/, validation/, docs/ or scripts/ at the code commit given below;
  * one issuer once, whatever its ticker; NO substitution: whatever is selected stays in the
    denominator even if its filing is oversized, missing, of an unsupported form, unreadable, reports
    in another currency, or has no company facts.

Usage:
  python -I scripts/select_generalization_cohort_6.py <company_tickers.json> \
      <repo root> <code commit> <exposure> [<exposure> ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import select_generalization_cohort as base  # noqa: E402

base.SEED = "clearsignal-generalization-6:"
base.BUCKETS = (("mid", 1001, 2500), ("small", 2501, 5000), ("micro", 5001, 9000))
base.PER_BUCKET = 2

if __name__ == "__main__":
    base.main(*sys.argv[1:])
