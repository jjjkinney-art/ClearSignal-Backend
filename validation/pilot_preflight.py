"""Frozen six-case preparation only: no app imports, credentials or dispatch."""
from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
from types import MappingProxyType


SETUP_DIR = Path(__file__).resolve().parent
PILOT_TICKERS = ("ASML", "ACHC", "NPK")
QUESTION_IDS = ("core_thesis", "decision_threshold")
PILOT_CASES = tuple((ticker, question) for ticker in PILOT_TICKERS for question in QUESTION_IDS)
# Reviewed v2 bytes on main e3054c3. Rebinding requires a separate setup review;
# caller-supplied hashes or recomputed metadata cannot bless changed identities.
FROZEN_SETUP_SHA256 = MappingProxyType({
    "issuer_registry.v2.json": "7acd7a369a2321e40626b9ae803ad63739690e1dc93652c41a952c278dd74842",
    "company_quality_manifest.v2.json": "f7f4b3bf630e309b1250162df0b200f9e00a12fd950428050566c2c002c1d1f8",
    "company_quality_manifest.v2.metadata.json": "eec99ce3a5f8e336e58d7234a5105432746bdf0d14dd5ad9a27a52c83853e264",
})


class PilotPreflightError(ValueError):
    """Rejected preparation input; messages never echo supplied values."""


@dataclass(frozen=True)
class PilotIdentity:
    ticker: str
    cik: str
    company_name: str
    sector: str

    def company_context(self):
        """Pipeline-compatible data, without calling production detection.

        CIK stays in the bound identity; CompanyContext has no CIK field.
        Sector retains the registry's benchmark classification, not a GICS claim.
        """
        return dict(ticker=self.ticker, company_name=self.company_name, sector=self.sector)


def _load_setup(setup_dir):
    documents = []
    for name, expected in FROZEN_SETUP_SHA256.items():
        try:
            raw = (Path(setup_dir) / name).read_bytes()
        except OSError:
            raise PilotPreflightError("frozen v2 setup artifact unavailable") from None
        if hashlib.sha256(raw).hexdigest() != expected:
            raise PilotPreflightError("frozen v2 setup binding changed; separate review required")
        documents.append(json.loads(raw))
    registry, manifest, metadata = documents
    if (registry["registry_version"] != 2 or registry["schema_version"] != 1
            or registry["execution_authorized"] is not False
            or metadata["execution_authorized"] is not False
            or metadata["captures_executed"] != 0 or metadata["launch_ready"] is not False
            or manifest["registry_sha256"] != metadata["registry_sha256"]
            or manifest["matrix_sha256"] != metadata["matrix_sha256"]):
        raise PilotPreflightError("unsupported or executable setup")
    return registry, manifest, metadata


def _identity(ticker, cik, registry, metadata):
    if not isinstance(ticker, str) or not isinstance(cik, str):
        raise PilotPreflightError("exact ticker and CIK strings required")
    if ticker in metadata["reserved_holdouts"]:
        raise PilotPreflightError("reserved holdout cannot enter the pilot")
    if ticker not in PILOT_TICKERS or ticker not in metadata["development_issuers"]:
        raise PilotPreflightError("identity outside reviewed development pilot")
    row = next(item for item in registry["issuers"] if item["ticker"] == ticker)
    admission = row["admission_evidence"]
    if (row["reserved_holdout"] is not False or admission["reserved_holdout"] is not False
            or admission["company_admitted"] is not True
            or admission["identity_class_eligible"] is not True
            or admission["metadata_blockers"] != []
            or admission["ticker"] != ticker
            or row["issuer_deduplication_key"] != admission["issuer_deduplication_key"]):
        raise PilotPreflightError("identity lacks reviewed v2 admission")
    if row["issuer_deduplication_key"] != "SEC_CIK:" + cik:
        raise PilotPreflightError("ticker and CIK do not match reviewed identity")
    return PilotIdentity(ticker, cik, row["company"], row["sector"])


def resolve_pilot_identity(ticker, cik, *, setup_dir=SETUP_DIR):
    """Resolve exact frozen identity, including NPK; never substitute a ticker."""
    registry, _, metadata = _load_setup(setup_dir)
    return _identity(ticker, cik, registry, metadata)


def _route_inventory(question_id):
    source = question_id == "core_thesis"
    return {
        "kind": "expected_logical_tasks_not_observed_physical_dispatches",
        "source_evidence": source,
        "sec_tasks": ["recent_filings"] + (
            ["sec_metrics", "thesis_disclosures", "filing_metrics"] if source else []),
        "model_stage_maxima": {"specialists": 0 if source else 5,
                               "question_answerer": 0 if source else 1,
                               "synthesis_invocations": 0 if source else 2},
        "issuer_kpis": False,
        "issuer_releases": False,
        "fred_topics": [],
        "physical_attempt_limit_established": False,
    }


def validate_route_inventory(inventory):
    """Reject drift in a synthetic logical-task report, not authorize a route.

    Real physical dispatch enforcement remains unimplemented. This check also
    refuses missing cases, extra providers and changed field types/counts.
    """
    expected = {":".join(key): _route_inventory(key[1]) for key in PILOT_CASES}
    try:
        matches = (type(inventory) is dict and
                   json.dumps(inventory, sort_keys=True, allow_nan=False) ==
                   json.dumps(expected, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError):
        matches = False
    if not matches:
        raise PilotPreflightError("unexpected or incomplete logical route inventory")


def preflight(request=None, *, setup_dir=SETUP_DIR, route_inventory=None):
    """Prepare exactly six cases. No execution option or environment inspection."""
    registry, manifest, metadata = _load_setup(setup_dir)
    if route_inventory is not None:
        validate_route_inventory(route_inventory)
    rows = {row["ticker"]: row for row in registry["issuers"]}
    questions = {(case["issuer_id"], case["question_id"]): case["question"]
                 for case in manifest["cases"]}
    if request is None:
        request = {"schema_version": 1, "registry_version": 2, "cases": [
            dict(issuer_id=ticker, cik=rows[ticker]["issuer_deduplication_key"].removeprefix("SEC_CIK:"),
                 question_id=question_id, question=questions[ticker, question_id])
            for ticker, question_id in PILOT_CASES]}
    if (type(request) is not dict or set(request) != {"schema_version", "registry_version", "cases"}
            or type(request["schema_version"]) is not int or request["schema_version"] != 1
            or type(request["registry_version"]) is not int or request["registry_version"] != 2
            or type(request["cases"]) is not list or len(request["cases"]) != 6):
        raise PilotPreflightError("exact six-case v2 request required")
    resolved = {}
    for case in request["cases"]:
        if (type(case) is not dict or set(case) != {"issuer_id", "cik", "question_id", "question"}
                or any(not isinstance(value, str) for value in case.values())):
            raise PilotPreflightError("case requires only exact identity and question fields")
        identity = _identity(case["issuer_id"], case["cik"], registry, metadata)
        key = (identity.ticker, case["question_id"])
        if key not in PILOT_CASES or key in resolved:
            raise PilotPreflightError("unknown or duplicate pilot question")
        if case["question"] != questions[key]:
            raise PilotPreflightError("question differs from frozen v2 manifest")
        resolved[key] = {
            "case_id": ":".join(key), "question": questions[key],
            "identity": asdict(identity), "company_context": identity.company_context(),
            "identity_reference": "validation/issuer_registry.v2.json#" + identity.ticker,
            "routes": _route_inventory(case["question_id"]),
        }
    if set(resolved) != set(PILOT_CASES):
        raise PilotPreflightError("all six distinct development cases required")
    return {
        "schema_version": 1, "artifact_type": "offline_six_case_preflight",
        "registry_version": 2, "setup_sha256": dict(FROZEN_SETUP_SHA256),
        "cases": [resolved[key] for key in PILOT_CASES],
        "identity_scope": "reviewed_frozen_setup_not_live_verified",
        "sector_scope": "benchmark_classification_not_verified_gics",
        "excluded_providers": ["fmp", "newsapi", "fred"],
        "coverage_gaps": ["fmp_financial_market_valuation_estimate_evidence",
                          "newsapi_company_and_macro_news", "fred_macro_evidence"],
        "credential_presence_checked": False,
        "execution_allowed": False, "spending_authorized": False,
        "hard_usd_cap_established": False, "launch_ready": False,
        "quality_status": "not_adjudicated",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional exact six-case request JSON")
    parser.add_argument("--setup-dir", type=Path, default=SETUP_DIR)
    args = parser.parse_args(argv)
    try:
        request = json.loads(args.input.read_text()) if args.input else None
        if args.input and type(request) is not dict:
            raise PilotPreflightError("request must be an object")
        result = preflight(request, setup_dir=args.setup_dir)
    except (OSError, UnicodeError, json.JSONDecodeError):
        parser.error("preflight input unavailable or invalid JSON")
    except PilotPreflightError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
