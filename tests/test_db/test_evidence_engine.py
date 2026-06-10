"""
Phase 9F — Historical Evidence Engine tests.

All tests are pure-Python (no DB) except seed/retrieval integration tests.
The critical acceptance test:
  Query "What would break the Nvidia bull case?" must retrieve Cisco 2000
  (infrastructure_overbuild) BEFORE NVDA 2018 (demand_air_pocket), because
  mechanism similarity > ticker similarity for a capex_cycle concern.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Minimal analog stub for pure-Python tests
# ---------------------------------------------------------------------------

class _AnalogStub:
    """Minimal HistoricalAnalog-compatible object for unit tests."""

    def __init__(self, **kwargs):
        self.label = kwargs.get("label", "test")
        self.episode = kwargs.get("episode", "")
        self.entity_ticker = kwargs.get("entity_ticker")
        self.sector = kwargs.get("sector", "technology")
        self.business_model = kwargs.get("business_model", "semiconductor_fabless")
        self.quality_rating = kwargs.get("quality_rating", "strong")
        self.mechanism = kwargs.get("mechanism", "infrastructure_overbuild")
        self.concern_tags = kwargs.get("concern_tags", [])
        self.valuation_regime = kwargs.get("valuation_regime", "peak_multiple")
        self.growth_phase = kwargs.get("growth_phase", "deceleration")
        self.macro_regime = kwargs.get("macro_regime", "hiking")
        self.drawdown_pct = kwargs.get("drawdown_pct", -0.57)
        self.time_to_trough_days = kwargs.get("time_to_trough_days", 365)
        self.time_to_recover_days = kwargs.get("time_to_recover_days")
        self.outcome_summary = kwargs.get("outcome_summary", "Outcome.")
        self.why_relevant = kwargs.get("why_relevant", "Relevant.")
        self.disanalogy = kwargs.get("disanalogy", "Disanalogy.")
        self.base_rate_note = kwargs.get("base_rate_note", "")
        self.data_confidence = kwargs.get("data_confidence", "strong")
        self.source_note = kwargs.get("source_note", "")


# ---------------------------------------------------------------------------
# build_fingerprint unit tests
# ---------------------------------------------------------------------------

def test_build_fingerprint_extracts_tags():
    from app.evidence_engine import build_fingerprint

    thesis = {
        "concern_tags": ["capex_cycle", "valuation_risk"],
        "bull_thesis": "Strong AI demand drives GPU sales.",
        "bear_thesis": "Customer capex cycle could turn.",
        "conclusion": "Bullish.",
        "confidence_score": 0.72,
    }
    fp = build_fingerprint("What would break the bull case?", thesis, ticker="NVDA")
    assert "capex_cycle" in fp.concern_tags
    assert "valuation_risk" in fp.concern_tags
    assert "infrastructure_overbuild" in fp.inferred_mechanisms


def test_build_fingerprint_infers_sector():
    from app.evidence_engine import build_fingerprint

    thesis = {
        "concern_tags": ["valuation_risk"],
        "company_name": "NVIDIA Corporation — GPU semiconductor",
        "bull_thesis": "GPU chip demand is strong.",
        "bear_thesis": "Valuation risk.",
        "conclusion": "Bullish.",
    }
    fp = build_fingerprint("GPU capex question", thesis, ticker="NVDA")
    assert fp.sector == "technology"


def test_build_fingerprint_infers_macro_hiking():
    from app.evidence_engine import build_fingerprint

    thesis = {
        "concern_tags": ["interest_rate_risk"],
        "macro_sensitivity": {"rate hike": "negative"},
        "bull_thesis": "...",
        "bear_thesis": "Rate hike risk.",
        "conclusion": "...",
    }
    fp = build_fingerprint("What if the Fed keeps hiking rates?", thesis)
    assert fp.macro_regime == "hiking"


def test_build_fingerprint_empty_thesis():
    from app.evidence_engine import build_fingerprint

    fp = build_fingerprint("", {})
    assert fp.concern_tags == []
    assert fp.inferred_mechanisms == []


# ---------------------------------------------------------------------------
# _score_analog unit tests
# ---------------------------------------------------------------------------

def test_score_analog_perfect_match():
    """Analog with identical tags/mechanism/regime scores near 1.0 after penalty."""
    from app.evidence_engine import _score_analog, SetupFingerprint, DISANALOGY_PENALTY

    analog = _AnalogStub(
        concern_tags=["capex_cycle", "valuation_risk"],
        mechanism="infrastructure_overbuild",
        sector="technology",
        business_model="semiconductor_fabless",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
        quality_rating="strong",
    )
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        business_model="semiconductor_fabless",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    score = _score_analog(analog, fp)
    # All weights sum to 1.0 + 0.02 quality boost - DISANALOGY_PENALTY
    assert score > 0.70, f"Expected high score, got {score}"
    assert score <= 1.0


def test_score_analog_no_overlap():
    """Analog with zero tag overlap and different mechanism scores near floor or below."""
    from app.evidence_engine import _score_analog, SetupFingerprint, RELEVANCE_FLOOR

    analog = _AnalogStub(
        concern_tags=["currency_risk"],
        mechanism="commodity_shock",
        sector="energy",
        business_model="integrated_oil",
        valuation_regime="neutral",
        growth_phase="mature",
        macro_regime="neutral",
    )
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        business_model="semiconductor_fabless",
        valuation_regime="peak_multiple",
        growth_phase="hypergrowth",
        macro_regime="hiking",
    )
    score = _score_analog(analog, fp)
    assert score < RELEVANCE_FLOOR, f"Expected low score, got {score}"


def test_score_analog_sibling_mechanism():
    """infrastructure_overbuild ↔ inventory_channel_correction: partial 0.5 credit."""
    from app.evidence_engine import _score_analog, SetupFingerprint

    analog = _AnalogStub(
        concern_tags=["supply_chain_risk"],
        mechanism="inventory_channel_correction",
        sector="technology",
        business_model="semiconductor_fabless",
    )
    fp = SetupFingerprint(
        concern_tags=["supply_chain_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        business_model="semiconductor_fabless",
    )
    score = _score_analog(analog, fp)
    # Should get partial mechanism credit (0.5 × 0.30 = 0.15)
    assert score > 0.10, f"Expected sibling partial credit, got {score}"


# ---------------------------------------------------------------------------
# retrieve_historical_analogs — diversity and floor tests
# ---------------------------------------------------------------------------

def test_retrieve_empty_analogs():
    from app.evidence_engine import retrieve_historical_analogs, SetupFingerprint

    fp = SetupFingerprint(concern_tags=["capex_cycle"], inferred_mechanisms=["infrastructure_overbuild"])
    result = retrieve_historical_analogs([], fp)
    assert result == []


def test_retrieve_below_floor_returns_empty():
    """All low-scoring analogs → empty list."""
    from app.evidence_engine import retrieve_historical_analogs, SetupFingerprint

    analogs = [
        _AnalogStub(
            concern_tags=["currency_risk"],
            mechanism="commodity_shock",
            sector="energy",
            quality_rating="moderate",
        )
    ]
    fp = SetupFingerprint(
        concern_tags=["capex_cycle"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
    )
    result = retrieve_historical_analogs(analogs, fp)
    assert result == [], "Below-floor analog should return empty list"


def test_retrieve_diversity_one_per_mechanism():
    """Two analogs with same mechanism → only top-scored one returned."""
    from app.evidence_engine import retrieve_historical_analogs, SetupFingerprint

    a1 = _AnalogStub(
        label="A1", mechanism="infrastructure_overbuild",
        concern_tags=["capex_cycle", "valuation_risk"],
        sector="technology", valuation_regime="peak_multiple",
        growth_phase="deceleration", macro_regime="hiking",
    )
    a2 = _AnalogStub(
        label="A2", mechanism="infrastructure_overbuild",
        concern_tags=["capex_cycle"],
        sector="technology", valuation_regime="peak_multiple",
    )
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    result = retrieve_historical_analogs([a1, a2], fp)
    mechanisms = [r["mechanism"] for r in result]
    assert mechanisms.count("infrastructure_overbuild") == 1, (
        "Diversity rule: at most one analog per mechanism"
    )


def test_retrieve_result_structure():
    """Retrieved analogs include all required payload fields."""
    from app.evidence_engine import retrieve_historical_analogs, SetupFingerprint

    analog = _AnalogStub(
        label="Cisco 2000",
        mechanism="infrastructure_overbuild",
        concern_tags=["capex_cycle", "valuation_risk"],
        sector="technology",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    result = retrieve_historical_analogs([analog], fp)
    assert len(result) == 1
    r = result[0]
    required_fields = [
        "label", "mechanism", "outcome_summary", "why_relevant",
        "disanalogy", "relevance_score", "drawdown_pct",
    ]
    for f in required_fields:
        assert f in r, f"Missing field: {f}"
    assert 0.0 <= r["relevance_score"] <= 1.0


# ---------------------------------------------------------------------------
# CRITICAL ACCEPTANCE TEST
# "What would break the Nvidia bull case?" must retrieve Cisco 2000 BEFORE NVDA 2018
# because mechanism similarity (infrastructure_overbuild via capex_cycle) > ticker match
# ---------------------------------------------------------------------------

def test_cisco_before_nvda_2018_on_bull_case_question():
    """
    ACCEPTANCE TEST: Cisco 2000 must rank higher than NVDA 2018 for
    "What would break the Nvidia bull case?" with capex_cycle concern.

    The principle: mechanism similarity > ticker similarity.
    Cisco = infrastructure_overbuild (primary match for capex_cycle).
    NVDA 2018 = demand_air_pocket (secondary match).
    """
    from app.evidence_engine import retrieve_historical_analogs, SetupFingerprint

    cisco_2000 = _AnalogStub(
        label="Cisco Systems 2000 — telecom infrastructure overbuild",
        entity_ticker="CSCO",
        mechanism="infrastructure_overbuild",
        concern_tags=["capex_cycle", "valuation_risk", "concentration_risk"],
        sector="technology",
        business_model="infrastructure_supplier",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
        quality_rating="strong",
        drawdown_pct=-0.89,
    )

    nvda_2018 = _AnalogStub(
        label="NVIDIA 2018 — crypto mining demand air pocket",
        entity_ticker="NVDA",
        mechanism="demand_air_pocket",
        concern_tags=["supply_chain_risk", "valuation_risk", "macro_slowdown_risk"],
        sector="technology",
        business_model="semiconductor_fabless",
        valuation_regime="peak_multiple",
        growth_phase="hypergrowth",
        macro_regime="hiking",
        quality_rating="strong",
        drawdown_pct=-0.57,
    )

    # Fingerprint for: "What would break the Nvidia bull case?" with capex_cycle concern
    # capex_cycle maps to infrastructure_overbuild (primary)
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        ticker="NVDA",
        sector="technology",
        business_model="semiconductor_fabless",
        valuation_regime="peak_multiple",
        growth_phase="hypergrowth",
        macro_regime="hiking",
    )

    # With both analogs available
    results = retrieve_historical_analogs([cisco_2000, nvda_2018], fp)

    assert len(results) >= 1, "Should retrieve at least one analog"
    assert len(results) <= 2, "Should retrieve at most 2 (one per mechanism)"

    labels = [r["label"] for r in results]
    mechanisms = [r["mechanism"] for r in results]

    # Cisco must appear
    assert any("Cisco" in lbl for lbl in labels), (
        f"Cisco 2000 must be retrieved. Got: {labels}"
    )

    # Cisco must rank first (index 0)
    assert "Cisco" in results[0]["label"], (
        f"Cisco 2000 must rank FIRST. Got first: '{results[0]['label']}'. "
        f"Mechanism match > ticker match is the core design principle."
    )

    # Verify the mechanism
    assert results[0]["mechanism"] == "infrastructure_overbuild", (
        f"First result must be infrastructure_overbuild. Got: {results[0]['mechanism']}"
    )


# ---------------------------------------------------------------------------
# Scoring weight sanity
# ---------------------------------------------------------------------------

def test_scoring_weights_sum_correctly():
    """Verify concern_tag_jaccard weight dominates when tags are identical."""
    from app.evidence_engine import _score_analog, SetupFingerprint, DISANALOGY_PENALTY

    analog = _AnalogStub(
        concern_tags=["capex_cycle", "valuation_risk", "concentration_risk"],
        mechanism="infrastructure_overbuild",
        sector="technology",
        quality_rating="moderate",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    fp = SetupFingerprint(
        concern_tags=["capex_cycle", "valuation_risk", "concentration_risk"],
        inferred_mechanisms=["infrastructure_overbuild"],
        sector="technology",
        valuation_regime="peak_multiple",
        growth_phase="deceleration",
        macro_regime="hiking",
    )
    score = _score_analog(analog, fp)
    # Expected: 0.40*1.0 + 0.30*1.0 + 0.15 + 0.05 + 0.05 - DISANALOGY_PENALTY
    expected = 0.40 + 0.30 + 0.15 + 0.05 + 0.05 - DISANALOGY_PENALTY
    assert abs(score - expected) < 0.02, (
        f"Scoring weights off: expected ~{expected:.3f}, got {score:.3f}"
    )


# ---------------------------------------------------------------------------
# DB integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seed_and_retrieve_analogs(db_session):
    """Seed JSON loads correctly; get_all_analogs returns seeded rows."""
    from app.db.repositories.evidence_repo import seed_analogs, get_all_analogs

    inserted = await seed_analogs(db_session)
    await db_session.commit()

    assert inserted > 0, "Should insert analogs from seed JSON"

    rows = await get_all_analogs(db_session)
    assert len(rows) >= 20, f"Expected at least 20 seeded analogs, got {len(rows)}"

    labels = [r.label for r in rows]
    assert any("Cisco" in lbl for lbl in labels), "Cisco 2000 should be seeded"
    assert any("NVDA" in lbl or "NVIDIA" in lbl for lbl in labels), "NVDA 2018 should be seeded"


@pytest.mark.asyncio
async def test_seed_idempotent(db_session):
    """Calling seed_analogs twice inserts nothing on second call."""
    from app.db.repositories.evidence_repo import seed_analogs

    first = await seed_analogs(db_session)
    await db_session.commit()
    second = await seed_analogs(db_session)
    await db_session.commit()

    assert first > 0
    assert second == 0, "Second seed call must insert 0 rows (idempotent)"


@pytest.mark.asyncio
async def test_acceptance_cisco_before_nvda_via_db(db_session):
    """Full DB-backed acceptance test: Cisco 2000 ranks before NVDA 2018."""
    from app.db.repositories.evidence_repo import seed_analogs, get_all_analogs
    from app.evidence_engine import build_fingerprint, retrieve_historical_analogs

    await seed_analogs(db_session)
    await db_session.commit()

    all_analogs = await get_all_analogs(db_session)

    # Simulate: "What would break the Nvidia bull case?" with capex cycle concern
    thesis = {
        "concern_tags": ["capex_cycle", "valuation_risk"],
        "bull_thesis": "AI infrastructure spending drives GPU demand.",
        "bear_thesis": "Hyperscaler capex cycle risk.",
        "conclusion": "Bullish at peak multiple.",
        "confidence_score": 0.78,
        "company_name": "NVIDIA",
    }
    fp = build_fingerprint(
        "What would break the Nvidia bull case?",
        thesis,
        ticker="NVDA",
    )

    results = retrieve_historical_analogs(all_analogs, fp)

    assert len(results) >= 1, "Should find at least one historical analog"
    assert any("Cisco" in r["label"] for r in results), (
        f"Cisco 2000 must be in results. Got: {[r['label'] for r in results]}"
    )
    assert "Cisco" in results[0]["label"], (
        f"Cisco 2000 must rank FIRST (mechanism > ticker similarity). "
        f"Got: {results[0]['label']}"
    )
