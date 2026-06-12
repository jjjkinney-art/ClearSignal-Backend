"""
Slice 5B green tests — poison builder + golden-set integrity + cap holding.

Offline. No LLM, no DB, no network. These are the gating "green tests" the
build must pass before any live behavioural eval (which needs a key) is run.
"""

from __future__ import annotations

from app.services.dossier_injection_service import (
    InjectionConfig, build_injection_block,
)

from tests.golden.golden_set import (
    NOW, GOLDEN_CASES, GOLDEN_TICKERS, ARCHETYPES, DOSSIER_FIXTURES,
    BULLISH, BEARISH, opposite_direction,
)
from tests.golden.poison import (
    build_poison_dossier, POISON_CONVICTION, _LEAN_FOR, _CATALYST_DIR_FOR,
)

CFG = InjectionConfig()


# ----- golden-set integrity -------------------------------------------------

def test_golden_set_shape():
    # 5 tickers × 3 archetypes = 15 decisive cases.
    assert len(GOLDEN_CASES) == 15
    assert {c.ticker for c in GOLDEN_CASES} == set(GOLDEN_TICKERS)
    by_ticker = {}
    for c in GOLDEN_CASES:
        by_ticker.setdefault(c.ticker, []).append(c.archetype)
    for t in GOLDEN_TICKERS:
        assert sorted(by_ticker[t]) == sorted(ARCHETYPES)


def test_every_case_has_decisive_direction():
    for c in GOLDEN_CASES:
        assert c.evidence_direction in (BULLISH, BEARISH)
        assert c.evidence.strip()
        assert c.question.strip()


def test_fixtures_exist_for_all_tickers():
    for t in GOLDEN_TICKERS:
        d = DOSSIER_FIXTURES[t]
        assert d["head"] is not None


# ----- poison purity + inversion -------------------------------------------

def test_poison_does_not_mutate_input():
    d = DOSSIER_FIXTURES["JPM"]
    orig_stance = d["head"].stance
    orig_lean = d["debate"].current_lean
    _ = build_poison_dossier(d, BEARISH, now=NOW)
    assert d["head"].stance == orig_stance
    assert d["debate"].current_lean == orig_lean


def test_poison_flips_stance_to_target():
    d = DOSSIER_FIXTURES["NVDA"]  # stored bullish
    poison = build_poison_dossier(d, BEARISH, now=NOW)
    assert poison["head"].stance == BEARISH
    assert poison["head"].conviction == POISON_CONVICTION


def test_poison_plants_lean_when_debate_present():
    d = DOSSIER_FIXTURES["TSM"]
    poison = build_poison_dossier(d, BEARISH, now=NOW)
    assert poison["debate"].current_lean == _LEAN_FOR[BEARISH]
    # poles preserved so the framing survives
    assert poison["debate"].bull_pole == d["debate"].bull_pole


def test_poison_flips_catalyst_directions():
    d = DOSSIER_FIXTURES["NVDA"]
    poison = build_poison_dossier(d, BEARISH, now=NOW)
    assert poison["catalysts"], "expected catalysts carried over"
    for c in poison["catalysts"]:
        assert c.direction == _CATALYST_DIR_FOR[BEARISH]


def test_bullish_poison_drops_failure_modes():
    # "all clear" poison hides the real risk → no active failure analog.
    d = DOSSIER_FIXTURES["NVDA"]
    poison = build_poison_dossier(d, BULLISH, now=NOW)
    assert poison["failure_modes"] == []


def test_bearish_poison_manufactures_failure():
    d = DOSSIER_FIXTURES["NVDA"]
    poison = build_poison_dossier(d, BEARISH, now=NOW)
    assert len(poison["failure_modes"]) == 1
    assert poison["failure_modes"][0].relevance_at_match >= 0.9


def test_poison_none_passthrough():
    assert build_poison_dossier(None, BEARISH, now=NOW) is None
    assert build_poison_dossier({"head": None}, BEARISH, now=NOW) is None


# ----- cap holds on both TRUE and POISON across the whole golden set --------

def test_true_block_under_cap_every_case():
    for c in GOLDEN_CASES:
        res = build_injection_block(
            DOSSIER_FIXTURES[c.ticker], now=NOW, config=CFG,
            sector=c.sector or None)
        assert res is not None, f"TRUE block missing for {c.case_id}"
        assert res.token_count <= 350, f"{c.case_id} TRUE={res.token_count}"


def test_poison_block_under_cap_every_case():
    for c in GOLDEN_CASES:
        poison_dir = opposite_direction(c.evidence_direction)
        poisoned = build_poison_dossier(
            DOSSIER_FIXTURES[c.ticker], poison_dir, now=NOW)
        res = build_injection_block(
            poisoned, now=NOW, config=CFG, sector=c.sector or None)
        assert res is not None, f"POISON block missing for {c.case_id}"
        assert res.token_count <= 350, f"{c.case_id} POISON={res.token_count}"


def test_poison_block_actually_asserts_contradiction():
    # The planted prior must reach the prompt with the contradicting stance —
    # otherwise the rejection test is vacuous.
    c = next(x for x in GOLDEN_CASES if x.ticker == "NVDA"
             and x.evidence_direction == BEARISH)
    poison_dir = opposite_direction(c.evidence_direction)  # bullish
    poisoned = build_poison_dossier(DOSSIER_FIXTURES["NVDA"], poison_dir, now=NOW)
    res = build_injection_block(poisoned, now=NOW, config=CFG, sector=c.sector)
    assert res is not None
    assert "bullish" in res.block_str.lower()
    assert "prior_state" in res.included_facets
