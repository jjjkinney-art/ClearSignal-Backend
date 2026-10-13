"""One shared SEC issuer-directory response for both identity consumers.

All directory rows are invented. Network fetches are counting fakes; time is a
controlled clock; concurrency uses explicit events, never sleeps.
"""
import ast
import json
import threading
from pathlib import Path

import pytest

from app.services import issuer_identity
from app.services.issuer_risk_evidence import requested_risk_profile
from app.services.providers import sec_provider

DIRECTORY = {
    "0": {"cik_str": 4242001, "ticker": "INVTA", "title": "Invented Alpha Holdings Inc"},
    "1": {"cik_str": 4242002, "ticker": "BETA-B", "title": "Invented Beta Industries"},
    "2": {"cik_str": 4242003, "ticker": "GAMA", "title": "Invented Gamma Staffing Corp"},
}


def _real_fetch_directory_json():
    """The source implementation; repository conftest neuters it at import."""
    path = Path(issuer_identity.__file__)
    tree = ast.parse(path.read_text())
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef) and item.name == "_fetch_directory_json")
    namespace = {}
    exec(compile(ast.Module([node], []), str(path), "exec"), issuer_identity.__dict__, namespace)
    return namespace["_fetch_directory_json"]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Fetches:
    """Counting fake for sec_provider._fetch_json; optional gate and failures."""
    def __init__(self, responses=None):
        self.responses = list(responses or [DIRECTORY])
        self.calls = []
        self.entered = threading.Event()
        self.release = None

    def __call__(self, url, timeout=10):
        self.calls.append((url, timeout))
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(10), "test gate never released"
        value = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(value, BaseException):
            raise value
        return json.loads(json.dumps(value))


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(sec_provider.time, "monotonic", value)
    return value


@pytest.fixture
def fresh(monkeypatch, clock):
    """Cold caches in both consumers and the shared layer, real fetch hooks."""
    monkeypatch.setattr(issuer_identity, "_fetch_directory_json", _real_fetch_directory_json())
    for name, value in (("_cache", None), ("_expires_at", 0.0), ("_retry_at", 0.0), ("_fetched", None)):
        monkeypatch.setattr(issuer_identity, name, value)
    monkeypatch.setattr(sec_provider, "_ticker_cik_cache", None)
    sec_provider._reset_shared_company_tickers()
    yield
    sec_provider._reset_shared_company_tickers()


def install(monkeypatch, fetches):
    monkeypatch.setattr(sec_provider, "_fetch_json", fetches)
    return fetches


def cold_consumers(monkeypatch):
    monkeypatch.setattr(sec_provider, "_ticker_cik_cache", None)
    for name, value in (("_cache", None), ("_expires_at", 0.0), ("_retry_at", 0.0)):
        monkeypatch.setattr(issuer_identity, name, value)


# --- Sharing, in both orders and concurrently ---------------------------------

@pytest.mark.parametrize("first", ["ticker_map", "identity"])
def test_both_consumer_orders_share_one_fetch(fresh, monkeypatch, first):
    fetches = install(monkeypatch, Fetches())
    loads = [sec_provider._load_ticker_cik_map, issuer_identity._load_directory]
    if first == "identity":
        loads.reverse()
    results = [load() for load in loads]
    mapping, directory = (results if first == "ticker_map" else results[::-1])
    assert fetches.calls == [(sec_provider._COMPANY_TICKERS_URL, 15 if first == "ticker_map" else 5)]
    # Each consumer keeps its own output contract.
    assert mapping == {"INVTA": "0004242001", "BETA-B": "0004242002", "BETA.B": "0004242002",
                       "GAMA": "0004242003"}
    assert set(directory.symbols) == {"INVTA", "BETA.B", "GAMA"}
    assert directory.symbols["GAMA"].name == "Invented Gamma Staffing Corp"
    assert [item.ticker for item in directory.names["invented alpha holdings"]] == ["INVTA"]


class SignallingLock:
    """A real lock that reports when a second caller starts waiting for it."""
    def __init__(self):
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.waiting.set()
            self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


def run_concurrently(monkeypatch, fetches):
    """Start the ticker map, hold its fetch, then start identity behind it."""
    lock = SignallingLock()
    monkeypatch.setattr(sec_provider, "_directory_lock", lock)
    fetches.release = threading.Event()
    results = {}
    first = threading.Thread(target=lambda: results.__setitem__("map", sec_provider._load_ticker_cik_map()))
    second = threading.Thread(target=lambda: results.__setitem__("dir", issuer_identity._load_directory()))
    first.start()
    assert fetches.entered.wait(10)
    second.start()
    assert lock.waiting.wait(10)  # identity is now queued behind the in-flight fetch
    fetches.release.set()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    return results


def test_concurrent_consumers_share_one_in_flight_fetch(fresh, monkeypatch):
    fetches = install(monkeypatch, Fetches())
    results = run_concurrently(monkeypatch, fetches)
    assert len(fetches.calls) == 1
    assert results["map"]["INVTA"] == "0004242001"
    assert set(results["dir"].symbols) == {"INVTA", "BETA.B", "GAMA"}


def test_concurrent_waiter_shares_a_failure_then_a_later_caller_recovers(fresh, monkeypatch, clock):
    fetches = install(monkeypatch, Fetches([OSError("invented outage"), DIRECTORY]))
    results = run_concurrently(monkeypatch, fetches)
    assert len(fetches.calls) == 1  # the waiter did not fetch again
    assert results["map"] == {} and results["dir"].symbols == {}
    # Each consumer keeps its own failure policy: identity retries after 30s.
    clock.now += 29
    assert issuer_identity._load_directory().symbols == {}
    assert len(fetches.calls) == 1
    clock.now += 2
    assert set(issuer_identity._load_directory().symbols) == {"INVTA", "BETA.B", "GAMA"}
    assert len(fetches.calls) == 2
    # The ticker map keeps its process-lifetime withheld result, as before.
    assert sec_provider._load_ticker_cik_map() == {}


# --- Separate semantic validation ---------------------------------------------

def test_conflicting_and_ambiguous_identities_stay_rejected(fresh, monkeypatch):
    rows = {
        "0": {"cik_str": 1, "ticker": "DUPE", "title": "Invented First Duplicate"},
        "1": {"cik_str": 2, "ticker": "DUPE", "title": "Invented Second Duplicate"},
        "2": {"cik_str": 3, "ticker": "TWIN", "title": "Invented Twin Holdings"},
        "3": {"cik_str": 4, "ticker": "TWINB", "title": "Invented Twin Holdings Inc"},
        "4": {"cik_str": 5, "ticker": "SOLO", "title": "Invented Solo Corp"},
    }
    fetches = install(monkeypatch, Fetches([rows]))
    mapping = sec_provider._load_ticker_cik_map()
    directory = issuer_identity._load_directory()
    assert len(fetches.calls) == 1
    assert "DUPE" not in directory.symbols  # conflicting symbol withheld
    assert issuer_identity.exact_issuer("Invented Twin Holdings", directory) is None  # ambiguous name
    assert issuer_identity.exact_issuer("SOLO", directory).cik == "0000000005"
    assert mapping["DUPE"] == "0000000002"  # the reduced map's existing contract is unchanged


def test_unsupported_rows_are_filtered_by_each_consumer(fresh, monkeypatch):
    rows = {"0": {"cik_str": 7, "ticker": "GOOD", "title": "Invented Good Corp"},
            "1": {"cik_str": True, "ticker": "BOOL", "title": "Invented Bool Corp"},
            "2": {"cik_str": 8, "ticker": "lower case!", "title": "x"},
            "3": "not a row"}
    install(monkeypatch, Fetches([rows]))
    directory = issuer_identity._load_directory()
    assert set(directory.symbols) == {"GOOD"}
    # The reduced map has always required object rows and withholds the whole
    # map for the process when one is not; that existing policy is unchanged.
    assert sec_provider._load_ticker_cik_map() == {}


@pytest.mark.parametrize("response", [[], {}, "text", None])
def test_malformed_responses_are_not_shared(fresh, monkeypatch, response):
    fetches = install(monkeypatch, Fetches([response, DIRECTORY]))
    assert sec_provider._load_ticker_cik_map() == {}
    # Nothing was retained, so the next eligible consumer fetches again.
    assert set(issuer_identity._load_directory().symbols) == {"INVTA", "BETA.B", "GAMA"}
    assert len(fetches.calls) == 2


def test_identity_rejection_discards_the_shared_response(fresh, monkeypatch, clock):
    useless = {"0": {"cik_str": 0, "ticker": "ZERO", "title": "Invented Zero"}}
    fetches = install(monkeypatch, Fetches([useless, DIRECTORY]))
    assert issuer_identity._load_directory().symbols == {}
    clock.now += 31
    assert set(issuer_identity._load_directory().symbols) == {"INVTA", "BETA.B", "GAMA"}
    assert len(fetches.calls) == 2  # recovered instead of reusing the rejected response


def test_a_rejection_never_discards_a_newer_response(fresh, monkeypatch):
    install(monkeypatch, Fetches([DIRECTORY]))
    _, _, generation = sec_provider.shared_company_tickers(max_age=60, timeout=1)
    sec_provider.discard_shared_company_tickers(generation - 1)
    assert sec_provider._directory_response is not None


# --- Full response, copies and freshness --------------------------------------

def test_full_response_is_preserved_and_consumer_mutation_is_isolated(fresh, monkeypatch):
    rich = {"0": {**DIRECTORY["0"], "exchange": "Invented", "extra": [1, 2]}}
    install(monkeypatch, Fetches([rich]))
    first, _, _ = sec_provider.shared_company_tickers(max_age=60, timeout=1)
    assert first == rich
    first["0"]["ticker"] = "MUTATED"
    first["0"]["extra"].append(3)
    first["1"] = {"cik_str": 9, "ticker": "ADDED", "title": "Invented Added"}
    second, _, _ = sec_provider.shared_company_tickers(max_age=60, timeout=1)
    assert second == rich and second is not first


def test_expired_response_is_refetched(fresh, monkeypatch, clock):
    fetches = install(monkeypatch, Fetches([DIRECTORY, DIRECTORY]))
    sec_provider._load_ticker_cik_map()
    clock.now += issuer_identity.DIRECTORY_TTL_SECONDS  # exactly the maximum age
    issuer_identity._load_directory()
    assert len(fetches.calls) == 2


def test_identity_expiry_runs_from_the_original_fetch(fresh, monkeypatch, clock):
    fetches = install(monkeypatch, Fetches([DIRECTORY, DIRECTORY]))
    sec_provider._load_ticker_cik_map()  # SEC served the response at t0
    clock.now += 3000
    issuer_identity._load_directory()  # reused: no second fetch
    assert len(fetches.calls) == 1
    clock.now += 599
    issuer_identity._load_directory()
    assert len(fetches.calls) == 1
    clock.now += 1  # t0 + 3600: reuse must not extend freshness to t0 + 6600
    issuer_identity._load_directory()
    assert len(fetches.calls) == 2


# --- Isolation ----------------------------------------------------------------

def test_a_different_fetch_function_never_reuses_a_response(fresh, monkeypatch):
    first = install(monkeypatch, Fetches([DIRECTORY]))
    sec_provider._load_ticker_cik_map()
    other = {"0": {"cik_str": 77, "ticker": "OTHR", "title": "Invented Other Transport"}}
    second = install(monkeypatch, Fetches([other]))
    assert set(issuer_identity._load_directory().symbols) == {"OTHR"}
    assert len(first.calls) == len(second.calls) == 1


@pytest.mark.parametrize("entry", ["module_urlopen", "urllib_urlopen", "opener_open"])
def test_a_swapped_urllib_path_never_reuses_a_response(fresh, monkeypatch, entry):
    import urllib.request
    fetches = install(monkeypatch, Fetches([DIRECTORY, DIRECTORY]))
    sec_provider._load_ticker_cik_map()

    def bridge(*args, **kwargs):
        raise AssertionError("never called: the fetch itself is a fake")
    target = {"module_urlopen": (sec_provider, "urlopen"),
              "urllib_urlopen": (urllib.request, "urlopen"),
              "opener_open": (urllib.request.OpenerDirector, "open")}[entry]
    monkeypatch.setattr(*target, bridge)
    issuer_identity._load_directory()
    assert len(fetches.calls) == 2


def test_reset_makes_the_next_consumer_cold(fresh, monkeypatch):
    fetches = install(monkeypatch, Fetches([DIRECTORY, DIRECTORY]))
    sec_provider._load_ticker_cik_map()
    sec_provider._reset_shared_company_tickers()
    cold_consumers(monkeypatch)
    sec_provider._load_ticker_cik_map()
    assert len(fetches.calls) == 2


def test_pilot_worker_resets_the_shared_response_with_the_ticker_map():
    source = Path("validation/_pilot_worker.py").read_text()
    assert ("sec_provider._ticker_cik_cache = None\n"
            "                sec_provider._reset_shared_company_tickers()\n") in source


# --- Risk extraction ----------------------------------------------------------

def test_risk_profile_reuses_the_earlier_directory(fresh, monkeypatch):
    fetches = install(monkeypatch, Fetches())
    sec_provider._load_ticker_cik_map()
    profile = requested_risk_profile("GAMA", "What staffing risks could invalidate the thesis?")
    assert profile is not None and profile.cik == "4242003" and profile.scope == "Staffing demand"
    assert len(fetches.calls) == 1


def test_risk_profile_without_an_eligible_directory_still_fails_closed(fresh, monkeypatch):
    install(monkeypatch, Fetches([OSError("invented outage")]))
    assert requested_risk_profile("GAMA", "What staffing risks could invalidate the thesis?") is None


# --- The actual isolated pilot worker -----------------------------------------

def _directory_claims(result):
    cases = sorted({claim["case_id"] for claim in result["claims"]})
    return {case: sum(1 for claim in result["claims"]
                      if claim["case_id"] == case and claim["route"] == "sec/directory")
            for case in cases}


# Thesis risk extraction runs only after fetch_public_document has accepted
# the filing (bytes, media, canonical hash and HTML parsing).
_RISK_TRACE = """
import json as _json
from app.services import thesis_disclosures as _td
_original_extract = _td.extract_issuer_risk_evidence
def _traced_extract(document, *args, **kwargs):
    with open('risk-extraction-calls.jsonl', 'a') as _stream:
        _stream.write(_json.dumps(kwargs.get('ticker')) + '\\n')
    return _original_extract(document, *args, **kwargs)
_td.extract_issuer_risk_evidence = _traced_extract
"""


def _run_with_trace(tmp_path, monkeypatch, scenario):
    from validation import pilot_rehearsal
    original = pilot_rehearsal.subprocess.run

    def run(args, *a, **k):
        if "-c" in args and "from validation._pilot_worker import main" in args[-1]:
            args = list(args)
            prefix, suffix = args[-1].split("from validation._pilot_worker import main", 1)
            args[-1] = prefix + "\n" + _RISK_TRACE + "\nfrom validation._pilot_worker import main" + suffix
        return original(args, *a, **k)
    monkeypatch.setattr(pilot_rehearsal.subprocess, "run", run)
    output = tmp_path / scenario
    result = pilot_rehearsal.run_rehearsal(output, scenario=scenario, mode="live_adapter_validation")
    trace = output / "risk-extraction-calls.jsonl"
    calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    return result, calls


def test_isolated_pipeline_risk_extraction_makes_no_second_directory_get(tmp_path, monkeypatch):
    result, calls = _run_with_trace(tmp_path, monkeypatch, "happy")
    assert result["status"] == "complete" and len(result["completed_cases"]) == 6
    assert "ASML" in calls  # successful ingestion reached risk extraction
    # Before this change ASML:core_thesis made two directory GETs.
    assert _directory_claims(result) == dict.fromkeys(_directory_claims(result), 1)
    assert result["ledger"]["unresolved_attempts"] == 0
    assert result["network_attempts"] == result["external_dispatches"] == 0


def test_isolated_pipeline_hash_failure_still_prevents_risk_extraction(tmp_path, monkeypatch):
    result, calls = _run_with_trace(tmp_path, monkeypatch, "reviewed_document_admitted")
    assert result["status"] == "complete"
    assert "ASML" not in calls  # canonical-hash rejection stops before risk extraction
    assert _directory_claims(result)["ASML:core_thesis"] == 1


# --- Existing stage supervision is unchanged ----------------------------------

def test_late_directory_claim_stays_unresolved_and_fenced_after_stage_timeout(tmp_path):
    from validation.capture_budget import AttemptLedger, BudgetError, digest
    from validation.pilot_live import LiveAdapterBoundary
    from validation.pilot_policy import AUDITED_DEPENDENCIES, policy_for
    policy = policy_for({"revision": "fixture", "source_sha256": "fixture"},
                        dict(AUDITED_DEPENDENCIES), mode="live_adapter_validation")
    owner = LiveAdapterBoundary(AttemptLedger(tmp_path / "book.sqlite", policy, create=True), "happy")
    try:
        owner.begin(owner.cases[0])
        owner.stage.set("evidence.thesis_disclosures")
        url = "https://www.sec.gov/files/company_tickers.json"
        fingerprint = digest({"method": "GET", "url": url, "route": "sec/directory",
                              "stage": "evidence.thesis_disclosures"})
        owner.claim("sec/directory", fingerprint, 0, 0)
        owner.ledger.halt("stage_timeout")  # the existing evidence deadline fires
        summary = owner.ledger.summary()
        assert summary["halted"] == "stage_timeout"
        assert summary["attempts"] == summary["unresolved_attempts"] == 1
        with pytest.raises(BudgetError):
            owner.sec_exchange("GET", url, None)
        assert owner.ledger.summary()["attempts"] == 1
    finally:
        owner.close()


def test_frozen_directory_quota_and_deadlines_are_unchanged():
    from validation.pilot_policy import RUN_DEADLINE_SECONDS, policy_for, AUDITED_DEPENDENCIES
    policy = policy_for({"revision": "fixture", "source_sha256": "fixture"},
                        dict(AUDITED_DEPENDENCIES), mode="offline")
    quotas = policy["quotas"]
    assert quotas["overall"] == {"model": 24, "sec": 30}
    assert quotas["per_case"]["ASML:core_thesis"]["sec/directory"] == 2
    assert quotas["per_case"]["ASML:decision_threshold"]["sec/directory"] == 1
    assert RUN_DEADLINE_SECONDS == 480
