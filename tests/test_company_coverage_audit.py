"""The audit must expose failures, not silently turn missing coverage green."""
from types import SimpleNamespace
import json

import pytest

from scripts import company_coverage_audit as audit


def issuer(ticker="TEST"):
    return {"ticker": ticker, "company": "Test Company", "market_cap_tier": "mid",
            "sector": "Materials"}


def test_identity_reports_wrong_issuer_separately_from_unresolved(monkeypatch):
    from app.services import company_detection
    def resolve(value):
        return SimpleNamespace(context=SimpleNamespace(ticker="WRONG") if value == "TEST" else None,
                               method="fuzzy_token", confidence=0.9)
    monkeypatch.setattr(company_detection, "resolve_entity", resolve)
    rows = audit.identity_probe([issuer()])
    assert rows[0]["wrong_issuer"] and not rows[0]["passed"]
    assert not rows[1]["wrong_issuer"] and not rows[1]["passed"]


def test_routing_stops_legacy_before_analysis(monkeypatch):
    from app.services import router_service
    monkeypatch.setattr(router_service, "route_question", lambda request:
                        router_service.enrich_grounding_context())
    rows = audit.routing_probe([issuer()])
    assert len(rows) == 3
    assert all(not row["passed"] for row in rows)
    assert {row["pipeline"] for row in rows} == {"provider_or_legacy_analysis_boundary"}


def test_routing_cannot_make_network_request(monkeypatch):
    import requests
    from app.services import router_service
    monkeypatch.setattr(router_service, "route_question", lambda request:
                        requests.get("https://example.invalid/must-not-be-requested"))
    assert all(not r["passed"] for r in audit.routing_probe([issuer()]))


def test_wrong_pipeline_handoff_fails_even_with_valid_response_shape(monkeypatch):
    from app.services import router_service
    monkeypatch.setattr(router_service, "route_question", lambda request:
        router_service._run_investment_pipeline(company=SimpleNamespace(ticker="WRONG")))
    rows = audit.routing_probe([issuer()])
    assert all(row["wrong_issuer"] and not row["passed"] for row in rows)
    assert all(row["saved_text_raw_json"] is False for row in rows)


@pytest.mark.parametrize("failed_layer", ["identity", "routing", "topic"])
def test_any_failed_layer_blocks_launch_report(monkeypatch, failed_layer):
    for layer in ("identity", "routing", "topic"):
        row = {"ticker": "TEST", "passed": layer != failed_layer, "wrong_issuer": False}
        if layer == "topic":
            monkeypatch.setattr(audit, "topic_probe", lambda row=row: [row])
        else:
            monkeypatch.setattr(audit, layer + "_probe", lambda issuers, row=row: [row])
    report = audit.build_report({"classification_as_of": "2026-09-29", "issuers": [issuer()]})
    assert report["launch_blocked_for_unrestricted_company_coverage"]
    assert not report["passed"]
    assert not report["production_authenticated_ask_tested"]
    assert report["llm_calls"] == 0


def test_live_fact_inventory_requires_correct_cik(monkeypatch):
    import requests
    class Response:
        content = b"synthetic test response"
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"cik": 999, "name": "Test Company", "tickers": ["TEST"],
                    "filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-08-01"]}},
                    "facts": {"us-gaap": {"Revenues": {}}}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
    rows = audit.live_sec_probe({"0": {"ticker": "TEST", "cik_str": 123}}, ["TEST"])
    assert rows[0]["checks"]["submissions"]["passed"]
    assert not rows[0]["checks"]["companyfacts"]["passed"]
    assert not rows[0]["passed"]


def test_sec_snapshot_without_live_flag_does_not_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "identity_probe", lambda issuers: [])
    monkeypatch.setattr(audit, "routing_probe", lambda issuers: [])
    monkeypatch.setattr(audit, "topic_probe", lambda: [])
    monkeypatch.setattr(audit, "live_sec_probe", lambda *a: pytest.fail("unexpected live fetch"))
    snapshot = tmp_path / "tickers.json"
    snapshot.write_text(json.dumps({"0": {"ticker": "AAPL", "cik_str": 320193}}))
    report = audit.build_report({"classification_as_of": "2026-09-29", "issuers": [issuer()]}, snapshot)
    assert report["independent_live_sec_checks"] == []
    assert report["official_identity_snapshot"]["ticker_row_count"] == 1


@pytest.mark.parametrize("body,passed", [("valid", True), ("malformed", False)])
def test_curl_transport_checks_json_and_records_http_status(monkeypatch, body, passed):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("wrong transport"))
    data = {"cik": 123, "name": "Test", "tickers": ["TEST"],
            "filings": {"recent": {"form": ["10-Q"], "filingDate": ["2026-08-01"]}},
            "facts": {"us-gaap": {"Revenues": {}}}}
    stdout = (json.dumps(data).encode() if body == "valid" else b"not json") + b"\n200"
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    row = audit.live_sec_probe({"0": {"ticker": "TEST", "cik_str": 123}}, ["TEST"], "curl")[0]
    assert row["passed"] is passed
    if passed:
        assert row["checks"]["companyfacts"]["status"] == 200
        assert row["checks"]["companyfacts"]["transport"] == "curl"


def test_empty_cohort_never_claims_launch_coverage_passed(monkeypatch):
    monkeypatch.setattr(audit, "topic_probe", lambda: [{"passed": True}] * 4)
    report = audit.build_report({"classification_as_of": "2026-09-29", "issuers": []})
    assert not report["coverage_checks_complete"]
    assert not report["passed"]


def test_local_audit_pass_does_not_certify_production_launch(monkeypatch):
    monkeypatch.setattr(audit, "identity_probe", lambda issuers: [{"passed": True}] * 2)
    monkeypatch.setattr(audit, "routing_probe", lambda issuers: [
        {"passed": True, "wrong_issuer": False, "ticker": "TEST"}] * 3)
    monkeypatch.setattr(audit, "topic_probe", lambda: [{"passed": True}] * 4)
    report = audit.build_report({"classification_as_of": "2026-09-29", "issuers": [issuer()]})
    assert report["passed"]
    assert report["launch_blocked_for_unrestricted_company_coverage"]
    assert not report["production_authenticated_ask_tested"]
