"""Primary metadata replay and authored passages; no live coverage certificate."""
from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.providers import sec_provider
from app.services import public_document_ingestion as ingestion
from app.services.issuer_risk_evidence import extract_issuer_risk_evidence, bound_issuer_risk
from app.services.evidence_references import admit_evidence
from app.services.source_answer import apply_source_answer_gate
from app.schemas import InvestmentThesis
from scripts import company_evidence_acceptance as acceptance

# Reduced shape observed from SEC's exact-CIK EFTS response on 7 October.
# Test passages below are authored, not complete downloaded filing bodies.
def annual_hit():
    return {"_id": "0000034088-26-000045:xom-20251231.htm", "_source": {
        "ciks": ["0000034088"], "form": "10-K", "file_type": "10-K",
        "root_forms": ["10-K"], "sequence": 1, "adsh": "0000034088-26-000045",
        "file_date": "2026-02-18", "period_ending": "2025-12-31"}}


def payload(hits=None):
    return {"timed_out": False, "_shards": {"failed": 0},
            "hits": {"hits": [annual_hit()] if hits is None else hits}}


def fallback(monkeypatch, response, *, limit=1):
    calls = []
    monkeypatch.setattr(sec_provider, "_fetch_json", lambda url, **kwargs:
                        calls.append((url, kwargs)) or response)
    result = sec_provider._fetch_missing_annual_by_cik(
        "0000034088", "EXXON MOBIL CORP", ["10-K"], limit,
        cutoff="2024-10-07", as_of="2026-10-07")
    assert len(calls) == 1 and calls[0][1]["timeout"] == 5
    query = parse_qs(urlsplit(calls[0][0]).query)
    assert query["ciks"] == ["0000034088"] and query["forms"] == ["10-K"]
    assert query["enddt"] == ["2026-10-07"] and "q" not in query and "entity" not in query
    return result


def test_observed_exact_cik_hit_constructs_primary_annual_metadata(monkeypatch):
    result = fallback(monkeypatch, payload())
    assert len(result) == 1
    item = result[0]
    assert item.url == "https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/xom-20251231.htm"
    assert item.document_type == "10-K" and item.filed_at == "2026-02-18"
    assert item.claim_type == "filing_metadata" and not item.risk_disclosures


@pytest.mark.parametrize("field,value", [
    ("ciks", ["0000019617"]), ("ciks", ["0000034088", "0000019617"]),
    ("ciks", []), ("ciks", ["34088/path"]), ("ciks", [34088]),
    ("form", "10-K/A"), ("file_type", "EX-99.1"), ("root_forms", ["8-K"]),
    ("sequence", 2), ("sequence", True), ("sequence", "1"),
    ("adsh", "0000034088-26-000044"), ("adsh", "../unsafe"),
    ("file_date", "2026-10-08"), ("file_date", "2024-10-06"),
    ("file_date", "2026-02-30"), ("file_date", "2026-02-18T00:00:00Z"),
    ("period_ending", "2026-02-19"), ("period_ending", ""),
])
def test_search_filter_alone_cannot_admit_wrong_or_malformed_source(monkeypatch, field, value):
    hit = annual_hit(); hit["_source"][field] = value
    assert fallback(monkeypatch, payload([hit])) == []


@pytest.mark.parametrize("filename", ["../xom.htm", "xom.htm?token=x", "xom.htm#fragment",
    "https://example.com/xom.htm", "xom.xml", "xom\\unsafe.htm", "bad..htm"])
def test_primary_file_identifier_cannot_escape_sec_accession(monkeypatch, filename):
    hit = annual_hit(); hit["_id"] = hit["_source"]["adsh"] + ":" + filename
    assert fallback(monkeypatch, payload([hit])) == []


@pytest.mark.parametrize("response", [
    {"timed_out": True, "_shards": {"failed": 0}, "hits": {"hits": [annual_hit()]}},
    {"timed_out": False, "_shards": {"failed": 1}, "hits": {"hits": [annual_hit()]}},
    {}, None, {"timed_out": False, "_shards": {"failed": 0}, "hits": {"hits": "bad"}},
])
def test_partial_or_invalid_search_is_not_success(monkeypatch, response):
    assert fallback(monkeypatch, response) == []


def test_scan_and_return_are_bounded_sorted_and_deduplicated(monkeypatch):
    old = annual_hit()
    old["_id"] = "0000034088-25-000010:xom-20241231.htm"
    old["_source"].update(adsh="0000034088-25-000010", file_date="2025-02-19", period_ending="2024-12-31")
    assert len(fallback(monkeypatch, payload([annual_hit()] * 100), limit=5)) == 1
    assert fallback(monkeypatch, payload([{}] * 100 + [annual_hit()])) == []
    items = fallback(monkeypatch, payload([old, annual_hit(), deepcopy(old)]), limit=5)
    assert [i.filed_at for i in items] == ["2026-02-18", "2025-02-19"]


@pytest.mark.parametrize("forms,expect_search", [(["10-K"], True), (["10-K/A"], True),
    (["10-Q"], False), (["10-Q", "10-K"], False), (["8-K"], False), (["20-F"], False)])
def test_only_missing_annual_only_request_uses_exact_cik_search(monkeypatch, forms, expect_search):
    monkeypatch.setattr(sec_provider, "_ticker_cik_cache", {"XOM": "0000034088"})
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if "submissions" in url:
            return {"name": "EXXON MOBIL CORP", "filings": {"recent": {}}}
        data = payload()
        if forms == ["10-K/A"]:
            data["hits"]["hits"][0]["_source"].update(form="10-K/A", file_type="10-K/A", root_forms=["10-K/A"])
        return data
    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    result = sec_provider.fetch_recent_filings("XOM", forms=forms, as_of="2026-10-07")
    assert len(calls) == (2 if expect_search else 1)
    assert bool(result) == expect_search


def test_existing_annual_and_unresolved_identity_never_issue_search(monkeypatch):
    monkeypatch.setattr(sec_provider, "_ticker_cik_cache", {"XOM": "0000034088"})
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return {"name": "EXXON MOBIL CORP", "filings": {"recent": {
            "form": ["10-K"], "filingDate": ["2026-02-18"], "reportDate": ["2025-12-31"],
            "accessionNumber": ["0000034088-26-000045"], "primaryDocument": ["xom-20251231.htm"]}}}
    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    assert sec_provider.fetch_recent_filings("XOM", forms=["10-K"], as_of="2026-10-07")
    assert sec_provider.fetch_recent_filings("UNKNOWN", forms=["10-K"], as_of="2026-10-07") == []
    assert len(calls) == 1


def test_search_outage_stays_withheld(monkeypatch):
    monkeypatch.setattr(sec_provider, "_fetch_json", lambda *a, **k:
                        (_ for _ in ()).throw(TimeoutError("private-contact-canary")))
    assert sec_provider._fetch_missing_annual_by_cik("0000034088", "Exxon", ["10-K"], 1,
        cutoff="2024-10-07", as_of="2026-10-07") == []


def test_missing_annual_discovery_restores_source_bound_answer_with_two_downloads(monkeypatch):
    import socket
    from app.services import issuer_identity
    from tests.test_company_evidence_inspection import Response
    # Authored issuer: current XOM is a different CIK and may NOT inherit this
    # predecessor filing without a separately proven succession relationship.
    case = {'ticker': 'TESTENERGY', 'company': 'Authored Energy Issuer', 'cik': '34088',
            'topic': 'commodity prices', 'question': 'What operating risks affect commodity prices?'}
    directory = issuer_identity.parse_directory({'0': {'ticker': case['ticker'], 'title': case['company'], 'cik_str': 34088}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(issuer_identity, '_cache', directory)
    monkeypatch.setattr(sec_provider, '_ticker_cik_cache', {case['ticker']: '0000034088'})
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    queries, downloads = [], []
    def fetch_json(url, **kwargs):
        queries.append(url)
        if 'efts.sec.gov' in url:
            return payload()
        return {'name': case['company'], 'filings': {'recent': {
            'form': ['10-Q'], 'filingDate': ['2026-08-03'], 'reportDate': ['2026-06-30'],
            'accessionNumber': ['0000034088-26-000123'], 'primaryDocument': ['q.htm']}}}
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch_json)
    quote = 'Commodity prices could decline and adversely affect operating results.'
    def fetch_document(url, **kwargs):
        downloads.append(url)
        text = ('Item 1A. Risk Factors ' + quote + ' Item 1B. Unresolved Staff Comments'
                if url.endswith('xom-20251231.htm') else 'See annual report risk disclosures.')
        return Response(('<html><body>' + text + '</body></html>').encode())
    monkeypatch.setattr(ingestion.requests, 'get', fetch_document)
    row = acceptance.run_case(case, user_agent='test-contact', inspect_source=True, evaluated_at='2026-10-07')
    assert row['passed'], json.dumps(row)
    assert row['reason'] == 'exact_source_spans_and_answer_citations'
    assert row['documents_attempted'] == 2 and row['admitted_risk_count'] == 1
    assert len(downloads) == 2 and sum('efts.sec.gov' in q for q in queries) == 1
    sample = row['document_diagnostics'][1]['source_inspection']['topic_candidates']['topic_sentence_samples'][0]
    assert sample['excerpt'] == quote and not sample['rejection_reasons']
    assert not row['retrieval_failures']


def test_current_xom_cannot_silently_inherit_predecessor_filing(monkeypatch):
    monkeypatch.setattr(sec_provider, '_ticker_cik_cache', {'XOM': '0002115436'})
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        if 'submissions' in url:
            return {'name': 'ExxonMobil Holdings Corp', 'filings': {'recent': {}}}
        return payload()  # Predecessor CIK 34088, despite the current-CIK query.
    monkeypatch.setattr(sec_provider, '_fetch_json', fetch)
    assert sec_provider.fetch_recent_filings('XOM', forms=['10-K'], as_of='2026-10-07') == []
    assert len(calls) == 2 and parse_qs(urlsplit(calls[1]).query)['ciks'] == ['0002115436']


@pytest.mark.parametrize("phrase", ["retain members", "retain existing members", "retaining our existing members",
    "retain our subscribers", "retaining subscribers"])
def test_explicit_retention_binds_to_subscription_question(monkeypatch, phrase):
    from tests.test_sec_risk_passages import document, CASES
    from app.services import issuer_identity
    case = CASES["NFLX"]
    directory = issuer_identity.parse_directory({"0": {"ticker": "NFLX", "title": case["company"], "cik_str": int(case["cik"])}})
    monkeypatch.setattr(issuer_identity, "_load_directory", lambda: directory)
    quote = (f'Problems {phrase} could adversely affect our revenue.' if phrase.startswith('retaining')
             else f'If service disruptions prevent us from being able to {phrase}, our revenue could decline.')
    doc = document("NFLX", f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments')
    items = extract_issuer_risk_evidence(doc, ticker="NFLX", question=case["question"])
    assert len(items) == 1
    claim = bound_issuer_risk(items[0], ticker="NFLX", question=case["question"])
    assert doc.text[claim['start_offset']:claim['end_offset']] == quote
    admitted, refs, _ = admit_evidence(items, evaluated_at='2026-10-07')
    thesis = InvestmentThesis(ticker='NFLX', company_name=case['company'])
    assert apply_source_answer_gate(thesis, case['question'], admitted, references=refs)['status'] == 'attributed'
    assert '[E1]' in thesis.direct_answer


@pytest.mark.parametrize("quote", [
    'We may renew content licenses and incur additional costs.',
    'We may retain employees and suffer higher compensation costs.',
    'We may retain union members and incur additional costs.',
    'We may retain members of the guild and incur additional costs.',
    'We may attract new members and experience declines in advertising.',
    'Our ability to retain existing members is improving.',
])
def test_non_customer_retention_or_nonadverse_words_cannot_supply_answer(monkeypatch, quote):
    from tests.test_sec_risk_passages import document, CASES
    from app.services import issuer_identity
    case = CASES['NFLX']
    directory = issuer_identity.parse_directory({'0': {'ticker': 'NFLX', 'title': case['company'], 'cik_str': int(case['cik'])}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    doc = document('NFLX', f'Item 1A. Risk Factors {quote} Item 1B. Unresolved Staff Comments')
    assert extract_issuer_risk_evidence(doc, ticker='NFLX', question=case['question']) == []


@pytest.mark.parametrize('declared', [True, False])
def test_size_failure_metadata_reports_measurement_not_headers_or_body(declared):
    from tests.test_company_evidence_inspection import Response
    response = Response(b'x' * 1001, {'Content-Length': '1001'} if declared else {})
    with pytest.raises(ingestion.PublicDocumentError) as error:
        ingestion._read_bounded(response, max_bytes=1000)
    assert error.value.size_limit_bytes == 1000
    assert (error.value.declared_bytes if declared else error.value.observed_bytes) == 1001


def test_diagnostic_export_reports_size_without_contact_or_source_text(monkeypatch):
    from tests.test_company_evidence_inspection import CASE, prepare
    from app.services import issuer_identity
    directory = issuer_identity.parse_directory({'0': {'ticker': CASE['ticker'], 'title': CASE['company'], 'cik_str': int(CASE['cik'])}})
    monkeypatch.setattr(issuer_identity, '_load_directory', lambda: directory)
    monkeypatch.setattr(acceptance.live.sec_provider, '_ticker_cik_cache', {CASE['ticker']: CASE['cik'].zfill(10)})
    import socket
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    prepare(monkeypatch, 'source-body-canary', headers={'Content-Length': str(ingestion.MAX_SEC_PERIODIC_BYTES + 1)})
    row = acceptance.run_case(CASE, user_agent='contact-canary', inspect_source=True)
    assert not row['passed'] and not row['documents_retrieved']
    failure = row['retrieval_failures'][0]
    assert failure['size_limit_bytes'] == ingestion.MAX_SEC_PERIODIC_BYTES
    assert failure['declared_bytes'] == ingestion.MAX_SEC_PERIODIC_BYTES + 1
    assert 'source-body-canary' not in json.dumps(row) and 'contact-canary' not in json.dumps(row)


@pytest.mark.parametrize('declared', [True, False])
def test_observed_jpm_size_fits_only_eligible_periodic_html(monkeypatch, declared):
    import socket
    from hashlib import sha256
    from tests.test_company_evidence_inspection import Response
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    text = 'Item 1A. Risk Factors Credit losses could adversely affect our revenue. Item 1B. Unresolved Staff Comments'
    # JPM's observed byte size, with authored visible text and synthetic HTML
    # comments. This is a resource-bound/parser replay, not a real filing.
    prefix = ('<html><body>' + text + '<!--').encode()
    suffix = b'--></body></html>'
    body = prefix + b'x' * (12_927_325 - len(prefix) - len(suffix)) + suffix
    response = Response(body, {'Content-Length': str(len(body))} if declared else {})
    monkeypatch.setattr(ingestion.requests, 'get', lambda *a, **k: response)
    document = ingestion.fetch_public_document(
        'https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/jpm-20251231.htm',
        publisher='SEC EDGAR', document_type='10-K', source_type='regulatory_filing',
        source_tier='primary', sec_periodic_limits=True)
    assert document.byte_count == len(body) and document.content_hash == sha256(body).hexdigest()
    assert document.text == text and response.closed
    with pytest.raises(ingestion.PublicDocumentError):
        ingestion.fetch_public_document('https://example.com/report.htm')
