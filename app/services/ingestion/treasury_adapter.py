"""
Treasury / Macro / Fed Ingestion Adapter.

Covers:
- US Treasury yields (2Y, 5Y, 10Y, 30Y)
- Fed FOMC decisions and statements
- CPI / Core CPI / PPI releases
- Nonfarm Payrolls / Unemployment
- GDP releases
- ISM Manufacturing / Services PMI

Data sources (live mode):
- FRED API (Federal Reserve Bank of St. Louis) — free, no key required for basic access
- US Bureau of Labor Statistics (BLS) — public releases
- Treasury.gov Direct Data API

In development/synthetic mode: returns high-fidelity synthetic macro events
that mirror real release cadences and market-moving magnitudes.

Design principles:
- All macro events get source_reliability=HIGH (official government sources)
- Market-moving flag set based on release category
- Tags aligned with Phase M extended vocabulary (hot_cpi, rate_hike, etc.)
- All events include provenance data for frontend display
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .base import EventIngestionAdapter
from .normalized_event import EventCategory, NormalizedEvent, SourceReliability

logger = logging.getLogger(__name__)

# Macro release → market-moving threshold
_MARKET_MOVING_RELEASES = frozenset([
    "cpi", "core cpi", "ppi", "fomc", "fed decision", "rate decision",
    "nonfarm payroll", "unemployment", "gdp", "ism manufacturing",
    "treasury yield", "10-year yield", "fed funds",
])

# Release type → materiality score
_RELEASE_MATERIALITY: dict[str, float] = {
    "fomc":        0.90,
    "cpi":         0.85,
    "ppi":         0.75,
    "nonfarm":     0.80,
    "gdp":         0.70,
    "ism":         0.55,
    "treasury":    0.65,
    "yield_move":  0.60,
}


def _classify_macro_tags(headline: str, body: str = "") -> list[str]:
    """Extract macro-specific tags from release text."""
    combined = f"{headline} {body}".lower()
    tags: list[str] = []

    if any(k in combined for k in ["above expectations", "hotter than", "higher than expected"]):
        if "cpi" in combined or "inflation" in combined:
            tags.append("hot_cpi")
        tags.append("beat")
    elif any(k in combined for k in ["below expectations", "cooler than", "lower than expected", "cooled"]):
        if "cpi" in combined or "inflation" in combined:
            tags.append("cool_cpi")
        tags.append("miss")

    if any(k in combined for k in ["rate hike", "raised rates", "increased rates"]):
        tags.append("rate_hike")
    elif any(k in combined for k in ["rate cut", "reduced rates", "cut rates", "easing"]):
        tags.append("rate_cut")
    elif any(k in combined for k in ["held rates", "unchanged", "pause", "on hold"]):
        tags.append("fed_hold")

    if any(k in combined for k in ["payrolls beat", "jobs added", "labor market strong"]):
        tags.append("jobs_strong")
    elif any(k in combined for k in ["payrolls missed", "job cuts", "unemployment rose"]):
        tags.append("jobs_weak")

    if "cpi" in combined:
        tags.append("cpi_release")
    if "ppi" in combined:
        tags.append("ppi_release")
    if "fomc" in combined or ("fed" in combined and "decision" in combined):
        tags.append("fed_decision")
    if "treasury" in combined or "yield" in combined:
        tags.append("treasury_move")
    if "gdp" in combined:
        tags.append("gdp_release")

    return tags


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TreasuryMacroAdapter(EventIngestionAdapter):
    """
    Ingestion adapter for US Treasury yields, Fed decisions, and macro releases.

    Operates in synthetic mode by default. In production, connect to
    FRED API or BLS data releases for live macro data.
    """

    source_name = "treasury_macro"
    source_reliability = "high"

    def __init__(self, use_live_api: bool = False) -> None:
        self._use_live_api = use_live_api

    async def fetch_latest(
        self,
        tickers: Optional[List[str]] = None,
        since: Optional[str] = None,
    ) -> List[NormalizedEvent]:
        """Fetch latest macro / Treasury events."""
        try:
            if self._use_live_api:
                return await self._fetch_live(tickers, since)
            return self._synthetic_events()
        except Exception as exc:
            logger.warning("TreasuryMacroAdapter.fetch_latest failed: %s", exc)
            return []

    async def health_check(self) -> bool:
        return True  # Synthetic always healthy; live would ping FRED

    # ── Live API path ──────────────────────────────────────────────────────

    async def _fetch_live(
        self,
        tickers: Optional[List[str]],
        since: Optional[str],
    ) -> List[NormalizedEvent]:
        """
        Production path: fetch from FRED or BLS.
        Implemented as a stub — returns synthetic in this version.
        Replace with actual FRED API calls for production deployment.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthetic_events)

    # ── Synthetic events ───────────────────────────────────────────────────

    def _synthetic_events(self) -> List[NormalizedEvent]:
        """
        Generate realistic synthetic macro events for development and testing.

        These mirror actual market-moving release patterns with realistic
        language, tags, and materiality scores.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        ts = _now_iso()

        releases = [
            {
                "headline": "CPI March 2025: Core Inflation +3.4% YoY, Above 3.2% Estimate",
                "body": (
                    "Core CPI came in at 3.4% year-over-year for March 2025, above the consensus "
                    "estimate of 3.2%. Monthly change was +0.4%, above the 0.3% expected. "
                    "Shelter and services inflation remain sticky. Market now pricing 2 cuts vs 3 prior."
                ),
                "source": "bls_cpi_release",
                "release_type": "cpi",
                "is_market_moving": True,
                "tags": ["hot_cpi", "beat", "cpi_release"],
                "magnitude": 0.85,
            },
            {
                "headline": "FOMC March 2025: Fed Holds Rates at 5.25-5.50%, Signals Patient Stance",
                "body": (
                    "The Federal Open Market Committee voted unanimously to hold the federal funds rate "
                    "target range at 5.25-5.50%. Chair Powell noted 'inflation progress has slowed' "
                    "and emphasized data dependence. Dot plot revised to 2 cuts in 2025 vs 3 prior. "
                    "10-year Treasury yield rose 12bps on the statement."
                ),
                "source": "federal_reserve_fomc",
                "release_type": "fomc",
                "is_market_moving": True,
                "tags": ["fed_hold", "fed_decision", "higher_for_longer"],
                "magnitude": 0.90,
            },
            {
                "headline": "10Y Treasury Yield Hits 4.62% — Highest Since November 2024",
                "body": (
                    "The 10-year US Treasury yield reached 4.62%, its highest level since November 2024, "
                    "driven by sticky inflation data and a repricing of Fed rate cut expectations. "
                    "The 2Y-10Y spread narrowed to -18bps. Duration-sensitive equities underperformed."
                ),
                "source": "treasury_direct",
                "release_type": "yield_move",
                "is_market_moving": True,
                "tags": ["treasury_move", "rate_hike"],
                "magnitude": 0.65,
            },
            {
                "headline": "Nonfarm Payrolls March 2025: +303K vs +214K Estimate; Unemployment 3.8%",
                "body": (
                    "The US economy added 303,000 nonfarm payroll jobs in March, well above the "
                    "consensus estimate of 214,000. Unemployment rate fell to 3.8% from 3.9%. "
                    "Average hourly earnings rose 4.1% YoY. Report reinforces higher-for-longer rate path."
                ),
                "source": "bls_employment_situation",
                "release_type": "nonfarm",
                "is_market_moving": True,
                "tags": ["jobs_strong", "beat"],
                "magnitude": 0.80,
            },
        ]

        events: List[NormalizedEvent] = []
        for r in releases:
            extra_tags = _classify_macro_tags(r["headline"], r.get("body", ""))
            all_tags = list(set(r["tags"] + extra_tags))

            events.append(
                NormalizedEvent(
                    ticker=None,  # Macro events have no ticker
                    category=EventCategory.MACRO,
                    headline=r["headline"],
                    body=r.get("body", ""),
                    source=r["source"],
                    source_reliability=SourceReliability.HIGH,
                    event_timestamp=f"{today}T08:30:00+00:00",
                    ingestion_timestamp=ts,
                    is_market_moving=r.get("is_market_moving", True),
                    magnitude=r.get("magnitude", 0.6),
                    tags=all_tags,
                    raw_payload=r,
                )
            )
        return events
