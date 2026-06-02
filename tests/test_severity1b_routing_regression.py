"""
tests/test_severity1b_routing_regression.py

Regression suite for Severity-1b coverage expansion (2026-06-02).

Root cause
----------
The 100-company production validation identified 15 P0 routing failures —
companies that returned Q:1, conf:0.000 in under 2 seconds:

  Category A — 12 companies truly absent from _COMPANY_DB:
    CB, ETN, EMR, EOG, PSX, OXY, VLO, D, AEP, EXC, TMUS, CHTR

  Category B — 3 companies present in _COMPANY_DB but blocked by
    _TICKER_STOP_WORDS, preventing exact-ticker resolution when queried
    directly (e.g. "Investment thesis for NOW"):
    NOW, SNOW, SO

Fix
---
  - Added 12 missing entries to _COMPANY_DB + _ALIAS_MAP.
  - Removed NOW, SNOW, SO from _TICKER_STOP_WORDS. On a financial analysis
    platform, uppercase NOW/SNOW/SO in user queries almost always refers to
    the ticker, not the English word. Long-form aliases ("servicenow",
    "snowflake", "southern company") still handle natural-language queries;
    PROTECTED_GENERIC_TICKERS still flags genuinely ambiguous edge cases.

Run
---
    python3 -m pytest tests/test_severity1b_routing_regression.py -v
"""

from __future__ import annotations

import pytest

from app.services.company_detection import (
    resolve_entity,
    MINIMUM_ROUTE_CONFIDENCE,
)
from app.services.router_service import _has_investment_intent


# ── Helpers ───────────────────────────────────────────────────────────────────

_HIGH_CONF_METHODS = frozenset({"exact_ticker", "alias_exact"})


def _would_route_investment(query: str) -> bool:
    """Replicate the router's routing decision without executing the pipeline."""
    er = resolve_entity(query)
    ctx = er.context
    if ctx is None:
        return False
    meets_threshold = (
        er.method in _HIGH_CONF_METHODS
        or er.confidence >= MINIMUM_ROUTE_CONFIDENCE
    )
    if not meets_threshold:
        return False
    has_intent = _has_investment_intent(query)
    is_high_conf = er.method in _HIGH_CONF_METHODS
    return has_intent or is_high_conf


# ── Category A: 12 companies added to _COMPANY_DB ────────────────────────────

class TestCategoryA_NewCompanyDB:
    """All 12 previously-absent companies must resolve and route to investment_thesis."""

    # ── CB — Chubb Limited ─────────────────────────────────────────────────────

    def test_cb_bare_ticker_resolves(self):
        er = resolve_entity("CB")
        assert er.context is not None, "CB must resolve to Chubb Limited"
        assert er.context.ticker == "CB"

    def test_cb_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for CB")
        assert er.context is not None
        assert er.context.ticker == "CB"

    def test_cb_alias_chubb(self):
        er = resolve_entity("chubb")
        assert er.context is not None
        assert er.context.ticker == "CB"

    def test_cb_alias_chubb_limited(self):
        er = resolve_entity("chubb limited")
        assert er.context is not None
        assert er.context.ticker == "CB"

    def test_cb_routes_investment(self):
        assert _would_route_investment("CB"), "CB must reach the investment pipeline"

    # ── ETN — Eaton Corporation ────────────────────────────────────────────────

    def test_etn_bare_ticker_resolves(self):
        er = resolve_entity("ETN")
        assert er.context is not None, "ETN must resolve to Eaton Corporation"
        assert er.context.ticker == "ETN"

    def test_etn_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for ETN")
        assert er.context is not None
        assert er.context.ticker == "ETN"

    def test_etn_alias_eaton(self):
        er = resolve_entity("eaton")
        assert er.context is not None
        assert er.context.ticker == "ETN"

    def test_etn_alias_eaton_corporation(self):
        er = resolve_entity("eaton corporation")
        assert er.context is not None
        assert er.context.ticker == "ETN"

    def test_etn_routes_investment(self):
        assert _would_route_investment("ETN"), "ETN must reach the investment pipeline"

    # ── EMR — Emerson Electric ─────────────────────────────────────────────────

    def test_emr_bare_ticker_resolves(self):
        er = resolve_entity("EMR")
        assert er.context is not None, "EMR must resolve to Emerson Electric"
        assert er.context.ticker == "EMR"

    def test_emr_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for EMR")
        assert er.context is not None
        assert er.context.ticker == "EMR"

    def test_emr_alias_emerson(self):
        er = resolve_entity("emerson")
        assert er.context is not None
        assert er.context.ticker == "EMR"

    def test_emr_alias_emerson_electric(self):
        er = resolve_entity("emerson electric")
        assert er.context is not None
        assert er.context.ticker == "EMR"

    def test_emr_routes_investment(self):
        assert _would_route_investment("EMR"), "EMR must reach the investment pipeline"

    # ── EOG — EOG Resources ────────────────────────────────────────────────────

    def test_eog_bare_ticker_resolves(self):
        er = resolve_entity("EOG")
        assert er.context is not None, "EOG must resolve to EOG Resources"
        assert er.context.ticker == "EOG"

    def test_eog_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for EOG")
        assert er.context is not None
        assert er.context.ticker == "EOG"

    def test_eog_alias_eog_resources(self):
        er = resolve_entity("eog resources")
        assert er.context is not None
        assert er.context.ticker == "EOG"

    def test_eog_routes_investment(self):
        assert _would_route_investment("EOG"), "EOG must reach the investment pipeline"

    # ── PSX — Phillips 66 ──────────────────────────────────────────────────────

    def test_psx_bare_ticker_resolves(self):
        er = resolve_entity("PSX")
        assert er.context is not None, "PSX must resolve to Phillips 66"
        assert er.context.ticker == "PSX"

    def test_psx_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for PSX")
        assert er.context is not None
        assert er.context.ticker == "PSX"

    def test_psx_alias_phillips_66(self):
        er = resolve_entity("phillips 66")
        assert er.context is not None
        assert er.context.ticker == "PSX"

    def test_psx_routes_investment(self):
        assert _would_route_investment("PSX"), "PSX must reach the investment pipeline"

    # ── OXY — Occidental Petroleum ────────────────────────────────────────────

    def test_oxy_bare_ticker_resolves(self):
        er = resolve_entity("OXY")
        assert er.context is not None, "OXY must resolve to Occidental Petroleum"
        assert er.context.ticker == "OXY"

    def test_oxy_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for OXY")
        assert er.context is not None
        assert er.context.ticker == "OXY"

    def test_oxy_alias_occidental(self):
        er = resolve_entity("occidental")
        assert er.context is not None
        assert er.context.ticker == "OXY"

    def test_oxy_alias_occidental_petroleum(self):
        er = resolve_entity("occidental petroleum")
        assert er.context is not None
        assert er.context.ticker == "OXY"

    def test_oxy_routes_investment(self):
        assert _would_route_investment("OXY"), "OXY must reach the investment pipeline"

    # ── VLO — Valero Energy ────────────────────────────────────────────────────

    def test_vlo_bare_ticker_resolves(self):
        er = resolve_entity("VLO")
        assert er.context is not None, "VLO must resolve to Valero Energy"
        assert er.context.ticker == "VLO"

    def test_vlo_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for VLO")
        assert er.context is not None
        assert er.context.ticker == "VLO"

    def test_vlo_alias_valero(self):
        er = resolve_entity("valero")
        assert er.context is not None
        assert er.context.ticker == "VLO"

    def test_vlo_alias_valero_energy(self):
        er = resolve_entity("valero energy")
        assert er.context is not None
        assert er.context.ticker == "VLO"

    def test_vlo_routes_investment(self):
        assert _would_route_investment("VLO"), "VLO must reach the investment pipeline"

    # ── D — Dominion Energy ────────────────────────────────────────────────────

    def test_d_bare_ticker_resolves(self):
        er = resolve_entity("D")
        assert er.context is not None, "D must resolve to Dominion Energy"
        assert er.context.ticker == "D"

    def test_d_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for D")
        assert er.context is not None
        assert er.context.ticker == "D"

    def test_d_alias_dominion_energy(self):
        er = resolve_entity("dominion energy")
        assert er.context is not None
        assert er.context.ticker == "D"

    def test_d_alias_dominion(self):
        er = resolve_entity("dominion")
        assert er.context is not None
        assert er.context.ticker == "D"

    def test_d_routes_investment(self):
        assert _would_route_investment("D"), "D must reach the investment pipeline"

    # ── AEP — American Electric Power ─────────────────────────────────────────

    def test_aep_bare_ticker_resolves(self):
        er = resolve_entity("AEP")
        assert er.context is not None, "AEP must resolve to American Electric Power"
        assert er.context.ticker == "AEP"

    def test_aep_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for AEP")
        assert er.context is not None
        assert er.context.ticker == "AEP"

    def test_aep_alias_american_electric_power(self):
        er = resolve_entity("american electric power")
        assert er.context is not None
        assert er.context.ticker == "AEP"

    def test_aep_routes_investment(self):
        assert _would_route_investment("AEP"), "AEP must reach the investment pipeline"

    # ── EXC — Exelon ──────────────────────────────────────────────────────────

    def test_exc_bare_ticker_resolves(self):
        er = resolve_entity("EXC")
        assert er.context is not None, "EXC must resolve to Exelon Corporation"
        assert er.context.ticker == "EXC"

    def test_exc_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for EXC")
        assert er.context is not None
        assert er.context.ticker == "EXC"

    def test_exc_alias_exelon(self):
        er = resolve_entity("exelon")
        assert er.context is not None
        assert er.context.ticker == "EXC"

    def test_exc_alias_exelon_corporation(self):
        er = resolve_entity("exelon corporation")
        assert er.context is not None
        assert er.context.ticker == "EXC"

    def test_exc_routes_investment(self):
        assert _would_route_investment("EXC"), "EXC must reach the investment pipeline"

    # ── TMUS — T-Mobile US ────────────────────────────────────────────────────

    def test_tmus_bare_ticker_resolves(self):
        er = resolve_entity("TMUS")
        assert er.context is not None, "TMUS must resolve to T-Mobile US"
        assert er.context.ticker == "TMUS"

    def test_tmus_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for TMUS")
        assert er.context is not None
        assert er.context.ticker == "TMUS"

    def test_tmus_alias_tmobile(self):
        er = resolve_entity("t-mobile")
        assert er.context is not None
        assert er.context.ticker == "TMUS"

    def test_tmus_alias_tmobile_nohyphen(self):
        er = resolve_entity("tmobile")
        assert er.context is not None
        assert er.context.ticker == "TMUS"

    def test_tmus_alias_tmobile_spaced(self):
        er = resolve_entity("t mobile")
        assert er.context is not None
        assert er.context.ticker == "TMUS"

    def test_tmus_routes_investment(self):
        assert _would_route_investment("TMUS"), "TMUS must reach the investment pipeline"

    # ── CHTR — Charter Communications ────────────────────────────────────────

    def test_chtr_bare_ticker_resolves(self):
        er = resolve_entity("CHTR")
        assert er.context is not None, "CHTR must resolve to Charter Communications"
        assert er.context.ticker == "CHTR"

    def test_chtr_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for CHTR")
        assert er.context is not None
        assert er.context.ticker == "CHTR"

    def test_chtr_alias_charter_communications(self):
        er = resolve_entity("charter communications")
        assert er.context is not None
        assert er.context.ticker == "CHTR"

    def test_chtr_alias_charter(self):
        er = resolve_entity("charter")
        assert er.context is not None
        assert er.context.ticker == "CHTR"

    def test_chtr_alias_spectrum_cable(self):
        er = resolve_entity("spectrum cable")
        assert er.context is not None
        assert er.context.ticker == "CHTR"

    def test_chtr_routes_investment(self):
        assert _would_route_investment("CHTR"), "CHTR must reach the investment pipeline"


# ── Category B: NOW, SNOW, SO — stop-word blockage fix ───────────────────────

class TestCategoryB_StopWordFix:
    """NOW, SNOW, SO were in _COMPANY_DB but blocked by _TICKER_STOP_WORDS.
    After Severity-1b, they resolve directly as exact_ticker."""

    # ── NOW — ServiceNow ──────────────────────────────────────────────────────

    def test_now_bare_ticker_resolves(self):
        er = resolve_entity("NOW")
        assert er.context is not None, "NOW must resolve to ServiceNow (no longer a stop word)"
        assert er.context.ticker == "NOW"

    def test_now_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for NOW")
        assert er.context is not None
        assert er.context.ticker == "NOW"

    def test_now_alias_servicenow_still_works(self):
        er = resolve_entity("servicenow")
        assert er.context is not None
        assert er.context.ticker == "NOW"

    def test_now_routes_investment(self):
        assert _would_route_investment("NOW"), "NOW must reach the investment pipeline"

    def test_now_routes_investment_thesis_query(self):
        assert _would_route_investment("Investment thesis for NOW")

    # ── SNOW — Snowflake ──────────────────────────────────────────────────────

    def test_snow_bare_ticker_resolves(self):
        er = resolve_entity("SNOW")
        assert er.context is not None, "SNOW must resolve to Snowflake (no longer a stop word)"
        assert er.context.ticker == "SNOW"

    def test_snow_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for SNOW")
        assert er.context is not None
        assert er.context.ticker == "SNOW"

    def test_snow_alias_snowflake_still_works(self):
        er = resolve_entity("snowflake")
        assert er.context is not None
        assert er.context.ticker == "SNOW"

    def test_snow_lowercase_weather_does_not_resolve(self):
        """Lowercase 'snow' in a weather context must NOT resolve to Snowflake."""
        er = resolve_entity("Is snow impacting retail foot traffic?")
        # Lowercase "snow" has no alias entry → should not resolve to SNOW
        if er.context is not None:
            assert er.context.ticker != "SNOW", (
                "Lowercase 'snow' in a non-financial sentence must not resolve to Snowflake."
            )

    def test_snow_routes_investment(self):
        assert _would_route_investment("SNOW"), "SNOW must reach the investment pipeline"

    def test_snow_routes_investment_thesis_query(self):
        assert _would_route_investment("Investment thesis for SNOW")

    # ── SO — Southern Company ─────────────────────────────────────────────────

    def test_so_bare_ticker_resolves(self):
        er = resolve_entity("SO")
        assert er.context is not None, "SO must resolve to Southern Company (no longer a stop word)"
        assert er.context.ticker == "SO"

    def test_so_investment_thesis_query_resolves(self):
        er = resolve_entity("Investment thesis for SO")
        assert er.context is not None
        assert er.context.ticker == "SO"

    def test_so_alias_southern_company_still_works(self):
        er = resolve_entity("southern company")
        assert er.context is not None
        assert er.context.ticker == "SO"

    def test_so_routes_investment(self):
        assert _would_route_investment("SO"), "SO must reach the investment pipeline"

    def test_so_routes_investment_thesis_query(self):
        assert _would_route_investment("Investment thesis for SO")


# ── Non-regression: existing companies unaffected ────────────────────────────

class TestNonRegression:
    """Key existing tickers must continue to resolve correctly after the expansion."""

    @pytest.mark.parametrize("ticker,expected_company", [
        ("VZ",    "VZ"),
        ("T",     "T"),
        ("CMCSA", "CMCSA"),
        ("SLB",   "SLB"),
        ("NEE",   "NEE"),
        ("DUK",   "DUK"),
        ("XOM",   "XOM"),
        ("CVX",   "CVX"),
        ("COP",   "COP"),
        ("HON",   "HON"),
        ("BA",    "BA"),
        ("AAPL",  "AAPL"),
        ("MSFT",  "MSFT"),
        ("NVDA",  "NVDA"),
    ])
    def test_existing_ticker_still_resolves(self, ticker, expected_company):
        er = resolve_entity(ticker)
        assert er.context is not None, f"{ticker} must still resolve after Severity-1b expansion"
        assert er.context.ticker == expected_company

    def test_ford_still_resolves_to_f(self):
        """Ford must not be displaced by any new Severity-1b addition."""
        er = resolve_entity("ford")
        assert er.context is not None
        assert er.context.ticker == "F"

    def test_investment_thesis_for_ford_still_resolves(self):
        er = resolve_entity("Investment thesis for Ford Motor")
        assert er.context is not None
        assert er.context.ticker == "F"

    def test_southern_company_alias_matches_so(self):
        """Pre-existing alias "southern company" must still route to SO."""
        er = resolve_entity("southern company")
        assert er.context is not None
        assert er.context.ticker == "SO"
