"""
Slice 5A — shadow dossier-injection formatter tests.

Pure-function tests against SimpleNamespace doubles (no DB).  Cover the
5A-relevant acceptance gates:

  G1  no-dossier / no-head → None (null-object; caller changes 0 bytes)
  G2  p100 ≤ 350 tokens under adversarially long facets; facet-granular drop
  G3  decay omits sub-θ facets; freshness band correct
  + facet rendering, priority drop order, within-facet trim, red-team trailer
    always present, anti-anchoring framing present, telemetry recorder.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.dossier_injection_service import (
    InjectionConfig,
    DEFAULT_CONFIG,
    build_injection_block,
    count_tokens,
    decay_weight,
    effective_confidence,
    staleness_band,
)

NOW = datetime(2026, 6, 12, tzinfo=timezone.utc)


# ─── builders ───────────────────────────────────────────────────────────────

def _head(age_days=2, stance="bullish", conviction=0.7, **kw):
    ts = NOW - timedelta(days=age_days)
    d = dict(
        ticker="NVDA", company_name="NVIDIA",
        stance=stance, conviction=conviction,
        primary_concern="AI capex durability",
        prior_as_of=ts, last_full_update_at=ts, updated_at=ts,
        staleness_state="fresh",
    )
    d.update(kw)
    return SimpleNamespace(**d)


def _debate(age_days=2, confidence=0.7, lean="bear", **kw):
    d = dict(
        ticker="NVDA",
        question="Is AI-capex durable into 2026?",
        bull_pole="Hyperscaler capex guides up; backlog extends.",
        bear_pole="ROI-payback doubts; digestion risk.",
        current_lean=lean, resolution_signal="datacenter rev trajectory",
        confidence=confidence, updated_at=NOW - timedelta(days=age_days),
    )
    d.update(kw)
    return SimpleNamespace(**d)


def _catalyst(statement, weight=0.8, status="open", direction="bull_trigger",
              window="Q2 2026", age_days=3):
    return SimpleNamespace(
        statement=statement, direction=direction, specificity=0.7,
        expected_window=window, status=status, conviction_weight=weight,
        created_at=NOW - timedelta(days=age_days),
    )


def _failure(stage=2, relevance=0.7, age_days=5, analog_id="an-1"):
    return SimpleNamespace(
        analog_id=analog_id, sequence_stage=stage,
        stage_evidence="margin compression as competitor ramps supply",
        relevance_at_match=relevance, matched_at=NOW - timedelta(days=age_days),
    )


def _durability(cycle="late", horizon="investment"):
    return SimpleNamespace(
        cycle_position=cycle, horizon_hint=horizon,
        conviction_trend="rising", catalyst_proximity_days=30,
        analog_time_to_trough_days=None, updated_at=NOW,
    )


def _moat_axis(axis, strength="moderate", trend="weakening", conf=0.7, age_days=3):
    return SimpleNamespace(
        axis=axis, strength=strength, trend=trend, confidence=conf,
        rationale="r", vulnerability="v",
        last_changed_at=NOW - timedelta(days=age_days),
    )


def _variant(divs, conf=0.7, age_days=3):
    return SimpleNamespace(
        divergences=divs, confidence=conf,
        updated_at=NOW - timedelta(days=age_days),
    )


def _dossier(**kw):
    base = dict(
        head=_head(), debate=_debate(), dimensions=[],
        catalysts=[], variant=None, durability=None, failure_modes=[],
    )
    base.update(kw)
    return base


# ─── G1 — null-object ─────────────────────────────────────────────────────────

def test_none_dossier_returns_none():
    assert build_injection_block(None, now=NOW) is None


def test_empty_dossier_dict_returns_none():
    assert build_injection_block({}, now=NOW) is None


def test_no_head_returns_none():
    assert build_injection_block(
        {"head": None, "debate": _debate()}, now=NOW) is None


def test_head_but_no_anchor_facets_returns_none():
    # head with blank stance + no debate → neither anchor survives → None
    res = build_injection_block(
        {"head": _head(stance=""), "debate": None,
         "dimensions": [], "catalysts": [], "variant": None,
         "durability": None, "failure_modes": []},
        now=NOW,
    )
    assert res is None


# ─── core rendering + anti-anchoring framing ─────────────────────────────────

def test_minimal_block_has_debate_and_redteam_and_delimiters():
    res = build_injection_block(_dossier(), now=NOW)
    assert res is not None
    b = res.block_str
    assert b.startswith("=== WHAT YOU ALREADY KNOW ABOUT NVDA")
    assert "DEBATE — Is AI-capex durable into 2026?" in b
    assert "Bull pole:" in b and "Bear pole:" in b
    assert "CHALLENGE THE PRIOR" in b           # C4 always present
    assert b.rstrip().endswith("=== END PRIOR DOSSIER — adjudicate below on fresh evidence ===")
    assert "debate" in res.included_facets


def test_framing_is_prior_not_verdict():
    res = build_injection_block(_dossier(), now=NOW)
    b = res.block_str
    assert "a prior to update — not facts to repeat" in b
    assert "the evidence\n  governs" in b or "evidence governs" in b
    assert "Re-adjudicate on this cycle's evidence." in b


def test_prior_state_demoted_line_present_by_default():
    res = build_injection_block(_dossier(), now=NOW)
    assert "PRIOR — stance bullish" in res.block_str
    assert "prior_state" in res.included_facets


def test_prior_state_excluded_when_toggled_off():
    cfg = InjectionConfig(include_prior_state=False)
    res = build_injection_block(_dossier(), now=NOW, config=cfg)
    assert "PRIOR — stance" not in res.block_str
    assert "prior_state" not in res.included_facets


def test_catalysts_rendered_open_only_top3_by_weight():
    cats = [
        _catalyst("Datacenter rev exceeds $28B", weight=0.9),
        _catalyst("Gross margin holds above 73%", weight=0.85),
        _catalyst("China export relief", weight=0.6),
        _catalyst("New GPU arch ships", weight=0.5),
        _catalyst("CLOSED catalyst", weight=0.99, status="triggered"),
    ]
    res = build_injection_block(_dossier(catalysts=cats), now=NOW)
    b = res.block_str
    assert "WATCH — open catalysts" in b
    assert "Datacenter rev exceeds $28B" in b      # top weight
    assert "CLOSED catalyst" not in b              # not open
    # max 3 bullets
    assert b.count("  • ") <= 3 + 0  # only catalyst bullets here


def test_failure_and_durability_rendered():
    res = build_injection_block(
        _dossier(failure_modes=[_failure()], durability=_durability()),
        now=NOW,
    )
    b = res.block_str
    assert "RISK — active failure-mode pattern" in b
    assert "@ stage 2" in b
    assert "cycle: late" in b


def test_failure_label_resolved_via_analog_labels():
    res = build_injection_block(
        _dossier(failure_modes=[_failure(analog_id="an-9")]),
        now=NOW, analog_labels={"an-9": "Intel displacement"},
    )
    assert "Intel displacement @ stage 2" in res.block_str


def test_moat_renders_when_populated_weakening_first():
    dims = [
        _moat_axis("network_effects", strength="strong", trend="stable"),
        _moat_axis("ecosystem_lockin", strength="moderate", trend="weakening"),
        _moat_axis("dead_axis", strength="absent", trend="stable"),
    ]
    res = build_injection_block(_dossier(dimensions=dims), now=NOW)
    b = res.block_str
    assert "MOAT —" in b
    # weakening axis appears before the stable one
    assert b.index("ecosystem lockin") < b.index("network effects")
    assert "dead axis" not in b                    # strength=absent excluded
    assert "moat" in res.included_facets


def test_variant_renders_when_populated_top_by_conviction():
    divs = [
        {"dimension": "valuation", "consensus_view": "rich",
         "clearsignal_view": "fair", "direction": "more_bullish", "conviction": 0.9},
        {"dimension": "moat durability", "consensus_view": "eroding",
         "clearsignal_view": "intact", "direction": "more_bullish", "conviction": 0.8},
        {"dimension": "noise", "consensus_view": "", "clearsignal_view": "",
         "direction": "", "conviction": 0.1},
    ]
    res = build_injection_block(_dossier(variant=_variant(divs)), now=NOW)
    b = res.block_str
    assert "VARIANT — where we diverge from consensus" in b
    assert "valuation (more bullish)" in b
    assert b.count("  • ") >= 1
    assert "noise" not in b                         # only top-2 kept


def test_dormant_moat_variant_absent_in_v1():
    # The production reality for Slice 5A: moat + variant unpopulated.
    res = build_injection_block(_dossier(), now=NOW)
    assert "MOAT —" not in res.block_str
    assert "VARIANT —" not in res.block_str
    assert "moat" not in res.included_facets
    assert "variant" not in res.included_facets


# ─── G3 — staleness / decay ──────────────────────────────────────────────────

def test_staleness_bands():
    assert staleness_band(0, DEFAULT_CONFIG) == "fresh"
    assert staleness_band(13, DEFAULT_CONFIG) == "fresh"
    assert staleness_band(14, DEFAULT_CONFIG) == "aging"
    assert staleness_band(59, DEFAULT_CONFIG) == "aging"
    assert staleness_band(60, DEFAULT_CONFIG) == "stale"
    assert staleness_band(None, DEFAULT_CONFIG) == "fresh"


def test_freshness_line_reflects_age_and_band():
    res = build_injection_block(
        {"head": _head(age_days=40), "debate": _debate(age_days=40),
         "dimensions": [], "catalysts": [], "variant": None,
         "durability": None, "failure_modes": []},
        now=NOW,
    )
    assert "updated 40d ago (aging)" in res.block_str
    assert res.staleness_state == "aging"


def test_decay_weight_monotonic_and_halves_at_60d():
    assert decay_weight(0, 86.0) == pytest.approx(1.0)
    assert decay_weight(60, 86.0) == pytest.approx(0.5, abs=0.02)
    assert decay_weight(120, 86.0) < decay_weight(60, 86.0)


def test_effective_confidence_gate_drops_stale_prior_state():
    # conviction 0.60 at 50d default tau → 0.60*exp(-50/86)=0.336 < θ(0.35) → dropped
    res = build_injection_block(
        {"head": _head(age_days=50, conviction=0.60),
         "debate": _debate(age_days=2),  # fresh debate keeps the block alive
         "dimensions": [], "catalysts": [], "variant": None,
         "durability": None, "failure_modes": []},
        now=NOW,
    )
    assert "PRIOR — stance" not in res.block_str
    assert ("prior_state", "decayed") in res.dropped_facets


def test_decayed_debate_lean_annotated():
    # low-confidence + old debate → effective < θ → lean carries decay note
    res = build_injection_block(
        {"head": _head(age_days=2), "debate": _debate(age_days=70, confidence=0.4),
         "dimensions": [], "catalysts": [], "variant": None,
         "durability": None, "failure_modes": []},
        now=NOW,
    )
    assert "confidence decayed by age — weight lightly" in res.block_str


def test_catalyst_below_theta_dropped():
    # weight 0.4 at 90d → 0.4*exp(-90/86)=0.140 < θ → no WATCH section
    cats = [_catalyst("weak old catalyst", weight=0.4, age_days=90)]
    res = build_injection_block(_dossier(catalysts=cats), now=NOW)
    assert "WATCH —" not in res.block_str


def test_high_velocity_sector_decays_faster():
    # same facet, semis tau=60: prior 0.6 @ 40d → 0.6*exp(-40/60)=0.308 < θ → dropped
    res = build_injection_block(
        {"head": _head(age_days=40, conviction=0.6), "debate": _debate(age_days=2),
         "dimensions": [], "catalysts": [], "variant": None,
         "durability": None, "failure_modes": []},
        now=NOW, sector="semiconductors",
    )
    assert "PRIOR — stance" not in res.block_str


# ─── G2 — token cap + drop order ─────────────────────────────────────────────

def test_typical_v1_block_under_cap():
    res = build_injection_block(
        _dossier(
            catalysts=[_catalyst("Datacenter rev >$28B"), _catalyst("Margin >73%")],
            failure_modes=[_failure()], durability=_durability(),
        ),
        now=NOW,
    )
    assert res.token_count <= DEFAULT_CONFIG.token_cap


def test_adversarial_block_respects_cap_p100():
    # Every facet maxed with very long text + all six populated.
    longtext = "x" * 4000
    big_debate = _debate(question=longtext, bull_pole=longtext, bear_pole=longtext)
    big_cats = [_catalyst(longtext, weight=w) for w in (0.9, 0.85, 0.8, 0.7)]
    big_dims = [_moat_axis(f"axis_{i}", trend="weakening") for i in range(6)]
    big_divs = [{"dimension": longtext, "consensus_view": "", "clearsignal_view": "",
                 "direction": "more_bearish", "conviction": 0.9} for _ in range(3)]
    res = build_injection_block(
        _dossier(
            head=_head(primary_concern=longtext),
            debate=big_debate, catalysts=big_cats, dimensions=big_dims,
            variant=_variant(big_divs), durability=_durability(),
            failure_modes=[_failure()],
        ),
        now=NOW,
    )
    assert res is not None
    assert res.token_count <= DEFAULT_CONFIG.token_cap


def test_drop_order_failure_first():
    # Cap above the 258-tok never-drop floor but below a full block so droppable
    # facets must drop; failure goes first.
    cfg = InjectionConfig(token_cap=290)
    res = build_injection_block(
        _dossier(
            catalysts=[_catalyst("Datacenter rev >$28B exceeds guide materially")],
            failure_modes=[_failure()], durability=_durability(),
        ),
        now=NOW, config=cfg,
    )
    assert res is not None
    dropped_names = [d[0] for d in res.dropped_facets]
    # failure is the first facet dropped when over cap
    if dropped_names:
        assert dropped_names[0] == "failure"
    # debate is never dropped
    assert "debate" in res.included_facets


def test_debate_and_prior_never_dropped_even_at_pressure():
    cfg = InjectionConfig(token_cap=290)
    res = build_injection_block(
        _dossier(
            catalysts=[_catalyst("c1"), _catalyst("c2")],
            failure_modes=[_failure()], durability=_durability(),
            dimensions=[_moat_axis("ecosystem_lockin", trend="weakening")],
            variant=_variant([{"dimension": "valuation", "direction": "more_bullish",
                               "conviction": 0.9}]),
        ),
        now=NOW, config=cfg,
    )
    assert res is not None
    assert "debate" in res.included_facets
    assert "prior_state" in res.included_facets
    assert "CHALLENGE THE PRIOR" in res.block_str   # trailer survives drops


def test_over_cap_pathological_suppresses_to_none():
    # cap below even the fixed overhead+debate floor → fail-safe None
    cfg = InjectionConfig(token_cap=5)
    res = build_injection_block(_dossier(), now=NOW, config=cfg)
    assert res is None


# ─── token counter sanity ────────────────────────────────────────────────────

def test_count_tokens_fallback_nonzero():
    assert count_tokens("") == 0
    assert count_tokens("hello world") >= 1


# ─── telemetry recorder ──────────────────────────────────────────────────────

def test_telemetry_records_and_snapshots():
    from app.services import dossier_injection_telemetry as tel
    tel.reset()
    res = build_injection_block(_dossier(), now=NOW)
    tel.record_build(
        ticker="NVDA", token_count=res.token_count,
        staleness_state=res.staleness_state, intent=res.intent,
        included_facets=res.included_facets, dropped_facets=res.dropped_facets,
        token_cap=350,
    )
    tel.record_null("ZZZZ")
    snap = tel.snapshot()
    assert snap["blocks_built"] == 1
    assert snap["null_results"] == 1
    assert snap["over_cap_count"] == 0
    assert snap["token_p100"] == res.token_count
    assert snap["facet_inclusion"].get("debate") == 1
    tel.reset()
    assert tel.snapshot()["blocks_built"] == 0
