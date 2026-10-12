"""Frozen preparation and synthetic route checks only; never run a pipeline."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

from validation.pilot_preflight import (
    FROZEN_SETUP_SHA256, PILOT_CASES, PilotPreflightError, SETUP_DIR,
    main, preflight, resolve_pilot_identity,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("network forbidden in offline preflight tests")
    for method in ("connect", "connect_ex", "sendto", "sendmsg"):
        monkeypatch.setattr(socket.socket, method, refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture
def request_data():
    return {"schema_version": 1, "registry_version": 2, "cases": [
        dict(issuer_id=case["identity"]["ticker"], cik=case["identity"]["cik"],
             question_id=case["case_id"].split(":")[1], question=case["question"])
        for case in preflight()["cases"]]}


@pytest.fixture
def copied_setup(tmp_path):
    for name in FROZEN_SETUP_SHA256:
        shutil.copyfile(SETUP_DIR / name, tmp_path / name)
    return tmp_path


def offline_python(body, *, extra_env=None):
    # Never inherit the developer's credentials or configuration. The audit hook
    # is installed before importing any app module and cannot be monkeypatched
    # away by a provider test double. Only public identity metadata is returned.
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "OPENAI_API_KEY": "invented-preflight-only",
           "SEC_USER_AGENT": "Offline fixture contact@example.invalid"}
    if extra_env:
        env.update(extra_env)
    guard = '''
import socket, sys
socket.has_ipv6 = False
blocked = []
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                 'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto',
                 'socket.sendmsg', 'socket.bind'}:
        blocked.append(event)
        raise RuntimeError('offline subprocess prohibits sockets')
sys.addaudithook(audit)
'''
    result = subprocess.run([sys.executable, "-B", "-c", guard + body +
                             "\nassert not blocked, 'socket attempt detected'\n"],
                            env=env, cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_all_six_frozen_cases_and_disabled_claims(request_data):
    result = preflight(request_data)
    assert [case["case_id"] for case in result["cases"]] == [":".join(k) for k in PILOT_CASES]
    assert result["setup_sha256"] == dict(FROZEN_SETUP_SHA256)
    for field in ("execution_allowed", "spending_authorized", "hard_usd_cap_established",
                  "launch_ready", "credential_presence_checked"):
        assert result[field] is False
    assert result["quality_status"] == "not_adjudicated"
    assert result["excluded_providers"] == ["fmp", "newsapi", "fred"]
    assert len(result["coverage_gaps"]) == 3
    assert result["identity_scope"] == "reviewed_frozen_setup_not_live_verified"


def test_npk_resolves_without_production_catalog_or_ticker_substitution():
    offline_python('''
from validation.pilot_preflight import resolve_pilot_identity
from app.services.company_detection import detect_company
from app.schemas import CompanyContext
assert detect_company('NPK') is None  # Production lookup is deliberately unchanged.
identity = resolve_pilot_identity('NPK', '0000080172')
context = CompanyContext(**identity.company_context())
assert context.ticker == 'NPK'
assert context.company_name == 'National Presto Industries, Inc.'
assert context.sector == 'Industrials'
assert identity.cik == '0000080172'
assert 'app.main' not in sys.modules
''')


@pytest.mark.parametrize("ticker,cik", [
    ("NPK", "0000937966"), ("ASML", "0000080172"), ("ACHC", "0000000000"),
    ("NPK", "80172"), ("NPK", 80172), ("npk", "0000080172"),
    ("JOUT", "0000080172"), ("UNKNOWN", "0000080172"), ("AON", "0000080172"),
])
def test_exact_reviewed_identity_required(ticker, cik):
    with pytest.raises(PilotPreflightError):
        resolve_pilot_identity(ticker, cik)


@pytest.mark.parametrize("change", ["ticker", "cik", "question", "whitespace", "family", "holdout",
                                  "duplicate", "missing", "extra", "state", "version", "execute"])
def test_request_drift_rejected(request_data, change):
    cases = request_data["cases"]
    if change == "ticker": cases[0]["issuer_id"] = "NPK"
    elif change == "cik": cases[0]["cik"] = "0000080172"
    elif change == "question": cases[0]["question"] = "Invent a valuation"
    elif change == "whitespace": cases[0]["question"] += " "
    elif change == "family": cases[0]["question_id"] = "structural_risk"
    elif change == "holdout": cases[0]["issuer_id"] = "AON"
    elif change == "duplicate": cases[1] = copy.deepcopy(cases[0])
    elif change == "missing": cases.pop()
    elif change == "extra": cases.append(copy.deepcopy(cases[0]))
    elif change == "state": cases[0]["user_id"] = "synthetic-user"
    elif change == "version": request_data["registry_version"] = 1
    elif change == "execute": request_data["execution_allowed"] = True
    with pytest.raises(PilotPreflightError):
        preflight(request_data)


@pytest.mark.parametrize("change", ["v1", "identity", "admission", "holdout", "question", "authorization"])
def test_changed_setup_cannot_be_blessed_by_recomputed_metadata(copied_setup, change):
    registry_path = copied_setup / "issuer_registry.v2.json"
    manifest_path = copied_setup / "company_quality_manifest.v2.json"
    metadata_path = copied_setup / "company_quality_manifest.v2.metadata.json"
    registry = json.loads(registry_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    metadata = json.loads(metadata_path.read_text())
    npk = next(row for row in registry["issuers"] if row["ticker"] == "NPK")
    if change == "v1": registry = json.loads((SETUP_DIR / "issuer_registry.v1.json").read_text())
    elif change == "identity": npk["issuer_deduplication_key"] = "SEC_CIK:0000937966"
    elif change == "admission": npk["admission_evidence"]["identity_class_eligible"] = False
    elif change == "holdout": metadata["reserved_holdouts"].append("NPK")
    elif change == "question": manifest["cases"][0]["question"] = "changed"
    elif change == "authorization": metadata["execution_authorized"] = True
    registry_path.write_text(json.dumps(registry))
    manifest_path.write_text(json.dumps(manifest))
    for path in (registry_path, manifest_path):
        metadata["artifact_sha256"]["validation/" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(PilotPreflightError, match="binding changed"):
        preflight(setup_dir=copied_setup)


def test_exact_snapshot_can_be_relocated(copied_setup):
    assert preflight(setup_dir=copied_setup) == preflight()


def test_synthetic_inventory_matches_actual_question_gates_and_no_fred_dispatch():
    offline_python('''
import copy
from validation.pilot_preflight import preflight
from app.services.source_answer import is_source_answer_request
from app.services.live_issuer_kpi_service import requested_issuer_kpi_aliases
from app.services.issuer_risk_evidence import requested_risk_topic
from app.services.thesis_disclosures import requests_thesis_disclosures
from app.services.filing_metric_evidence import requests_filing_metrics
from app.services.issuer_release_evidence import requests_issuer_release
from app.services import general_finance_evidence as fred
attempts = []
def reject(*args, **kwargs):
    attempts.append(True)
    raise AssertionError('unexpected FRED dispatch')
fred.urlopen = reject
fred.fetch_fred_series = reject
inventory = {}
for case in preflight()['cases']:
    ticker, question = case['identity']['ticker'], case['question']
    source = is_source_answer_request(question)
    observed = copy.deepcopy(case['routes'])
    observed['source_evidence'] = source
    observed['sec_tasks'] = ['recent_filings']
    if source: observed['sec_tasks'].append('sec_metrics')
    if source and requests_thesis_disclosures(ticker, question): observed['sec_tasks'].append('thesis_disclosures')
    if source and requests_filing_metrics(ticker, question): observed['sec_tasks'].append('filing_metrics')
    observed['issuer_kpis'] = bool(requested_issuer_kpi_aliases(question) or requested_risk_topic(ticker, question))
    observed['issuer_releases'] = requests_issuer_release(ticker, question)
    observed['fred_topics'] = fred._detect_topics(question)
    assert fred.retrieve_general_finance_evidence(question) == []
    inventory[case['case_id']] = observed
assert not attempts
assert preflight(route_inventory=inventory)['execution_allowed'] is False
assert 'app.main' not in sys.modules
''', extra_env={"FRED_API_KEY": "invented-preflight-fred-key"})


def test_router_task_fanout_requires_inventory_review_on_drift():
    tree = ast.parse((ROOT / "app/services/router_service.py").read_text())
    pipeline = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_run_investment_pipeline")

    def literal_task_keys(name):
        assignments = [node for node in ast.walk(pipeline) if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == name
                               for target in node.targets)]
        assert len(assignments) == 1
        return set(ast.literal_eval(key) for key in assignments[0].value.keys)

    assert literal_task_keys("_ev_tasks") == {
        "fmp", "sec", "news_co", "news_macro", "fred", "valuation", "estimates"}
    additions = {ast.literal_eval(target.slice) for node in ast.walk(pipeline)
                 if isinstance(node, ast.Assign) for target in node.targets
                 if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                 and target.value.id == "_ev_tasks"}
    assert additions == {"sec_revenue", "sec_metrics", "issuer_kpis", "thesis_disclosures",
                         "filing_metrics", "issuer_releases"}
    agent_names = literal_task_keys("_agent_tasks")
    assert agent_names == {"valuation", "macro", "risk", "market", "quality", "question_answerer"}
    plan = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "_DEFAULT_SYNTHESIS_PLAN"
                        for target in node.targets))
    maxima = next(case["routes"]["model_stage_maxima"] for case in preflight()["cases"]
                  if case["case_id"] == "NPK:decision_threshold")
    assert maxima == {"specialists": len(agent_names - {"question_answerer"}),
                      "question_answerer": 1, "synthesis_invocations": len(ast.literal_eval(plan))}


@pytest.mark.parametrize("change", ["fred", "issuer_release", "unexpected_sec", "extra_provider", "model", "missing"])
def test_unexpected_logical_routes_fail_closed(change):
    inventory = {case["case_id"]: case["routes"] for case in preflight()["cases"]}
    route = inventory["ASML:core_thesis"]
    if change == "fred": route["fred_topics"] = ["interest_rates"]
    elif change == "issuer_release": route["issuer_releases"] = True
    elif change == "unexpected_sec": route["sec_tasks"].append("sec_revenue")
    elif change == "extra_provider": route["fmp"] = True
    elif change == "model": route["model_stage_maxima"]["specialists"] = 1
    elif change == "missing": inventory.pop("NPK:decision_threshold")
    with pytest.raises(PilotPreflightError, match="route inventory"):
        preflight(route_inventory=inventory)


def test_preflight_import_is_pure_and_capture_flag_cannot_enable_execution():
    offline_python('''
import json
from validation.pilot_preflight import preflight
assert not any(name == 'app' or name.startswith('app.') for name in sys.modules)
assert preflight()['execution_allowed'] is False
assert not any(name == 'app' or name.startswith('app.') for name in sys.modules)
''', extra_env={"CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED": "true"})


def test_cli_has_no_execute_option(capsys):
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["execution_allowed"] is False
    with pytest.raises(SystemExit) as error:
        main(["--execute"])
    assert error.value.code == 2
