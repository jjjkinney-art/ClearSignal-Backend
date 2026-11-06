"""Deterministic selection of an unseen-company evaluation cohort.

Reads only the retained SEC company directory (company_tickers.json: ticker,
CIK and name per row) and lists of previously studied issuers. It never reads
a filing, company facts or any other answer-bearing source, and it makes no
network request. The rule is fixed in this file before it is applied.

Usage:
  python -I scripts/select_generalization_cohort.py <company_tickers.json> \
      <repo root> <code commit> <exposure> [<exposure> ...]

The code base is read at <code commit> (the frozen code, before the document
that names the cohort), so a re-run reproduces the same exclusions.

An exposure file is a pilot request.json (its case records' expected_cik) or a
retained ledger.sqlite (every SEC URL it holds). Output: JSON on stdout.
"""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys

SEED = "clearsignal-generalization-2:"
BUCKETS = (("large", 1, 200), ("mid", 501, 1500), ("small", 2501, 5000))
PER_BUCKET = 2
TICKER = re.compile(r"^[A-Z]{1,5}$")
# Pooled vehicles and shells, whose filings do not answer the operating questions.
EXCLUDED_NAME = re.compile(r"\b(?:fund|trust|etf|acquisition|spac|bdc|reit|partnership|income|portfolio|"
                           r"merger|capital corp|holdings? corp i+)\b", re.I)
NAME_SUFFIX = re.compile(r"[,.]|\b(?:inc|corp|corporation|co|company|ltd|plc|llc|lp|sa|nv|ag|se|"
                         r"holdings?|group|the|de c ?v|s ?a ?p ?i|s ?a ?b)\b", re.I)
REPO_PATHS = ("app", "tests", "validation", "docs", "scripts")


def rank(ticker):
    return hashlib.sha256((SEED + ticker).encode()).hexdigest()


def directory(path):
    rows = json.load(open(path, encoding="utf-8"))
    return [(int(position) + 1, row["ticker"], int(row["cik_str"]), row["title"])
            for position, row in sorted(rows.items(), key=lambda item: int(item[0]))]


def name_core(name):
    return " ".join(NAME_SUFFIX.sub(" ", name.lower()).split())


def exposed_ciks(paths):
    """CIKs of issuers in earlier cohorts or with any retained SEC response."""
    ciks = set()
    for path in paths:
        if path.endswith(".json"):
            for case in json.load(open(path, encoding="utf-8"))["policy"]["case_records"]:
                ciks.add(int(case["expected_cik"]))
        else:
            db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
            for (url,) in db.execute("SELECT url FROM ordinary_responses"):
                for found in re.findall(r"CIK(\d{10})|/edgar/data/(\d+)/", url):
                    ciks.add(int(next(part for part in found if part)))
    return ciks


def repo_text(root, commit):
    listing = subprocess.run(["git", "-C", root, "ls-tree", "-r", "-z", commit, "--", *REPO_PATHS],
                             capture_output=True, check=True).stdout.decode().split("\0")
    blobs = [entry.split()[2] for entry in listing if entry and entry.split()[1] == "blob"]
    out = subprocess.run(["git", "-C", root, "cat-file", "--batch"], input="\n".join(blobs).encode() + b"\n",
                         capture_output=True, check=True).stdout
    chunks, at = [], 0
    while at < len(out):
        header_end = out.index(b"\n", at)
        size = int(out[at:header_end].split()[2])
        body = out[header_end + 1:header_end + 1 + size]
        at = header_end + 1 + size + 1
        try:
            chunks.append(body.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return "\n".join(chunks)


def mentioned(rows, text):
    """CIKs whose ticker, CIK or registrant name appears in the code base."""
    words = set(re.findall(r"\b[A-Z]{1,5}\b", text))
    tokens = re.sub(r"[^a-z0-9& ]", " ", text.lower()).split()
    numbers = set(re.findall(r"\d{4,10}", text))
    cores = {name_core(name) for _, _, _, name in rows}
    lengths = {len(core.split()) for core in cores if core}
    phrases = {" ".join(tokens[i:i + n]) for n in lengths for i in range(len(tokens) - n + 1)}
    hits = set()
    for _, ticker, cik, name in rows:
        core = name_core(name)
        if (ticker in words or str(cik) in numbers or str(cik).zfill(10) in numbers
                or (len(core) >= 5 and core in phrases)):
            hits.add(cik)
    return hits


def select(rows, excluded):
    cohort = []
    for bucket, first, last in BUCKETS:
        eligible = [row for row in rows if first <= row[0] <= last and TICKER.match(row[1])
                    and not EXCLUDED_NAME.search(row[3]) and row[2] not in excluded]
        chosen, ciks = [], set()
        for row in sorted(eligible, key=lambda row: rank(row[1])):
            if row[2] in ciks:
                continue  # one issuer once, whatever its ticker
            chosen.append(row)
            ciks.add(row[2])
            if len(chosen) == PER_BUCKET:
                break
        cohort += [{"bucket": bucket, "position": p, "ticker": t, "cik": c, "sec_name": n, "rank": rank(t)}
                   for p, t, c, n in chosen]
    return cohort


def main(directory_path, root, commit, *exposure_paths):
    rows = directory(directory_path)
    prior = exposed_ciks(exposure_paths)
    code = mentioned(rows, repo_text(root, commit))
    excluded = prior | code
    print(json.dumps({
        "seed": SEED, "buckets": BUCKETS, "per_bucket": PER_BUCKET, "code_commit": commit,
        "directory_sha256": hashlib.sha256(open(directory_path, "rb").read()).hexdigest(),
        "directory_rows": len(rows),
        "excluded_prior_cohort_or_retained": len(prior),
        "excluded_code_mentions": len(code - prior),
        "cohort": select(rows, excluded),
    }, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
