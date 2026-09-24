"""SEC Atom filing metadata must retain only links from the matching entry."""
from types import SimpleNamespace

from app.providers import sec_client


def _entry(title, day, href=None):
    link = f'<link rel="alternate" href="{href}" />' if href else ""
    return f"<entry><title>{title}</title><updated>{day}T12:00:00Z</updated>{link}</entry>"


def test_filing_links_are_entry_scoped_and_only_sec_archives(monkeypatch):
    valid = "https://www.sec.gov/Archives/edgar/data/123/filing-index.htm"
    feed = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>Company feed</title>'
        + _entry("10-K - Example", "2026-08-01", valid)
        + _entry("10-K - Other", "2025-08-01", "https://evil.example/Archives/edgar/data/123/a")
        + _entry("10-K - No link", "2024-08-01")
        + "</feed>"
    )
    monkeypatch.setattr(sec_client.requests, "get", lambda *a, **kw: SimpleNamespace(
        text=feed, raise_for_status=lambda: None,
    ))
    filings = sec_client.get_recent_filings("Example", ticker="EX", count=3)
    assert [(f["title"], f["filing_date"], f["url"]) for f in filings] == [
        ("10-K - Example", "2026-08-01", valid),
        ("10-K - Other", "2025-08-01", None),
        ("10-K - No link", "2024-08-01", None),
    ]


def test_filing_link_rejects_non_archive_and_credential_urls(monkeypatch):
    feed = (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        + _entry("10-K - Login", "2026-08-01", "https://user@www.sec.gov/Archives/edgar/data/1/a")
        + _entry("10-K - Homepage", "2026-08-02", "https://www.sec.gov/")
        + _entry("10-K - Other", "2026-08-03", "http://www.sec.gov/Archives/edgar/data/1/a")
        + "</feed>"
    )
    monkeypatch.setattr(sec_client.requests, "get", lambda *a, **kw: SimpleNamespace(
        text=feed, raise_for_status=lambda: None,
    ))
    assert [f["url"] for f in sec_client.get_recent_filings("Example", ticker="EX")] == [None] * 3


def test_malformed_feed_fails_closed(monkeypatch):
    monkeypatch.setattr(sec_client.requests, "get", lambda *a, **kw: SimpleNamespace(
        text="<feed><entry>", raise_for_status=lambda: None,
    ))
    assert sec_client.get_recent_filings("Example", ticker="EX") == []
