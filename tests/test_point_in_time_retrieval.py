from app.schemas import GroundingContext
from app.services import context_service, data_providers
from app.services.providers import sec_provider


def test_sec_cik_lookup_excludes_filings_after_as_of(monkeypatch):
    sec_provider._ticker_cik_cache = None
    submissions = {
        "name": "Acme Inc.",
        "filings": {"recent": {
            "form": ["10-Q", "10-Q", "10-K"],
            "filingDate": ["2024-09-01", "2024-08-01", "2024-02-01"],
            "reportDate": ["2024-06-30", "2024-06-30", "2023-12-31"],
        }},
    }

    def fetch(url, timeout=10):
        if "company_tickers" in url:
            return {"0": {"ticker": "ACME", "cik_str": 1}}
        return submissions

    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    results = sec_provider.fetch_recent_filings(
        "ACME", as_of="2024-08-15T23:59:59Z", years_back=2,
    )

    assert [item.timestamp for item in results] == ["2024-08-01", "2024-02-01"]
    assert all(item.timestamp <= "2024-08-15" for item in results)


def test_sec_entity_search_sends_and_enforces_end_boundary(monkeypatch):
    sec_provider._ticker_cik_cache = None
    seen_urls = []

    def fetch(url, timeout=10):
        seen_urls.append(url)
        return {"hits": {"hits": [
            {"_source": {
                "form_type": "10-Q", "file_date": "2024-09-01",
                "period_of_report": "2024-06-30", "entity_name": "Acme Corp",
            }},
            {"_source": {
                "form_type": "10-Q", "file_date": "2024-08-01",
                "period_of_report": "2024-03-31", "entity_name": "Acme Corp",
            }},
        ]}}

    monkeypatch.setattr(sec_provider, "_fetch_json", fetch)
    results = sec_provider.fetch_recent_filings(
        "Acme Corp", as_of="2024-08-15", years_back=2,
    )

    assert [item.timestamp for item in results] == ["2024-08-01"]
    assert any("enddt=2024-08-15" in url for url in seen_urls)
    assert any("startdt=2022-08-16" in url for url in seen_urls)


def test_historical_context_suppresses_latest_only_fmp(monkeypatch):
    monkeypatch.setattr(context_service.settings, "enable_data_retrieval", True)
    called = {"fmp": 0, "as_of": None}

    def fmp(*args, **kwargs):
        called["fmp"] += 1
        return {"revenue": 999}

    def sec(company, ticker, user_agent, count=1, as_of=None):
        called["as_of"] = as_of
        return {
            "recent_events": ["10-K on 2020-02-01"],
            "known_facts": [],
            "source_notes": ["SEC EDGAR point-in-time filings"],
        }

    monkeypatch.setattr(context_service.data_providers, "fetch_fmp_financials", fmp)
    monkeypatch.setattr(context_service.data_providers, "fetch_sec_filings", sec)
    context = GroundingContext(company="Acme", ticker="ACME")

    result = context_service.enrich_grounding_context(
        "Acme", "Historical performance", context,
        as_of="2020-12-31T23:59:59Z",
    )

    assert called == {"fmp": 0, "as_of": "2020-12-31T23:59:59Z"}
    assert result.financials == {}
    assert result.recent_events == ["10-K on 2020-02-01"]


def test_legacy_sec_feed_uses_dateb_and_filters_future_rows():
    text = """
        <feed><title>Feed</title>
        <title>Future filing</title><updated>2021-02-01</updated>
        <title>Boundary filing</title><updated>2020-12-31</updated>
        </feed>
        """

    url = data_providers._sec_feed_url("ACME", 1, "2020-12-31")
    events = data_providers._parse_sec_feed_events(
        text, count=1, boundary="2020-12-31",
    )

    assert "dateb=20201231" in url
    assert "count=100" in url
    assert events == ["Boundary filing on 2020-12-31"]
