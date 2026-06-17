"""
Tests — Decision Ranking Engine, Phase 13 · Slice 3.

All tests operate on synthetic candidate dicts — no DB, no session.

Covers:
  1.  rank_candidate returns all required output keys
  2.  rank_candidates returns a list sorted by decision_score descending
  3.  rank_candidates returns [] for empty input
  4.  forecast_candidate — decision_score > 0 for a valid candidate
  5.  risk_candidate — decision_score > 0 for a valid candidate
  6.  catalyst_candidate — decision_score > 0 for a valid candidate
  7.  watchlist_candidate — decision_score > 0 for a valid candidate
  8.  portfolio_exposure_candidate — decision_score > 0 for a valid candidate
  9.  delivery_transition_candidate — decision_score > 0 for a valid candidate
  10. similarity_candidate — decision_score > 0 for a valid candidate
  11. sparse candidate (all empty input dicts) — score ≥ 0, no exception
  12. score bounds — all six scores/multipliers within their documented ranges
  13. decision_score always in [0, 1]
  14. monotonicity — higher attention signal → higher decision_score
  15. monotonicity — higher urgency (near-term horizon) → higher decision_score
  16. monotonicity — higher impact (stronger p_positive) → higher decision_score
  17. confidence damping — low evidence count lowers decision_score
  18. uncertainty damping — high uncertainty lowers decision_score
  19. exposure multiplier — owned position amplifies portfolio_exposure score
  20. exposure multiplier — non-portfolio types receive exactly 1.0
  21. deterministic ordering — same input → same ranking across calls
  22. rank_candidates produces correct ordering for 3 candidates
  23. weights sum — weight rows in _WEIGHT_CONFIG sum to 1.0
  24. normalize_score — clamps correctly for out-of-range inputs
  25. AST: no DB or session imports in ranking engine
  26. AST: no advice language in string constants
  27. AST: no session.add / update / delete calls
  28. AST: no conviction/recommendation/order/execution imports
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).parent.parent.parent
_ENGINE = _ROOT / "app" / "services" / "decision_ranking_engine.py"

# ---------------------------------------------------------------------------
# Required output keys
# ---------------------------------------------------------------------------

_REQUIRED_RESULT_KEYS = {
    "candidate_type",
    "entity_type",
    "entity_id",
    "ticker",
    "source_type",
    "source_id",
    "decision_score",
    "attention_score",
    "urgency_score",
    "impact_score",
    "confidence_multiplier",
    "uncertainty_discount",
    "exposure_multiplier",
    "rank_inputs",
    "candidate",
}

# ---------------------------------------------------------------------------
# Synthetic candidate builders (no DB needed)
# ---------------------------------------------------------------------------

def _forecast(*, p_pos=0.70, p_neg=0.20, p_neu=0.10, horizon_days=30,
               direction="strengthening", ftype="thesis_strengthening",
               band_low=0.55, band_high=0.85, ev_count=3) -> dict:
    return {
        "candidate_type": "forecast_candidate",
        "entity_type": "company",
        "entity_id": "NVDA",
        "ticker": "NVDA",
        "source_type": "forecast_vector",
        "source_id": "fv-001",
        "headline": "NVDA signal",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "horizon": "near_term",
            "horizon_days": horizon_days,
            "built_days_ago": 0,
            "p_max": max(p_pos, p_neg),
        },
        "impact_inputs": {
            "p_positive": p_pos,
            "p_negative": p_neg,
            "p_neutral": p_neu,
            "confidence_band_low": band_low,
            "confidence_band_high": band_high,
            "forecast_type": ftype,
        },
        "attention_inputs": {
            "forecast_type": ftype,
            "entity_type": "company",
            "direction": direction,
        },
        "confidence_inputs": {
            "confidence_band_low": band_low,
            "confidence_band_high": band_high,
            "evidence_count": ev_count,
            "forecast_schema": 1,
        },
        "uncertainty_inputs": {
            "band_width": band_high - band_low,
            "p_neutral": p_neu,
        },
        "source_versions": {"company_dossier": "v1"},
        "user_id": None,
    }


def _risk(*, stage=2, relevance=0.75, matched_days=5,
           has_label=True, has_evidence=True) -> dict:
    return {
        "candidate_type": "risk_candidate",
        "entity_type": "failure_mode",
        "entity_id": "fm-001",
        "ticker": "NVDA",
        "source_type": "dossier_failure_mode",
        "source_id": "fm-001",
        "headline": "NVDA risk",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "sequence_stage": stage,
            "matched_days_ago": matched_days,
            "relevance_at_match": relevance,
        },
        "impact_inputs": {
            "relevance_at_match": relevance,
            "sequence_stage": stage,
            "analog_label": "Intel displacement" if has_label else "",
        },
        "attention_inputs": {
            "ticker": "NVDA",
            "analog_id": "analog-001",
            "stage": stage,
        },
        "confidence_inputs": {
            "relevance_at_match": relevance,
            "has_analog_label": has_label,
            "has_stage_evidence": has_evidence,
        },
        "uncertainty_inputs": {
            "matched_days_ago": matched_days,
            "sequence_stage": stage,
        },
        "source_versions": {"dossier_failure_mode": "fm-001"},
        "user_id": None,
    }


def _catalyst(*, direction="bull_trigger", specificity=0.80, conviction=0.60,
               created_days=10, has_stmt=True, has_window=True) -> dict:
    return {
        "candidate_type": "catalyst_candidate",
        "entity_type": "company",
        "entity_id": "cat-001",
        "ticker": "NVDA",
        "source_type": "dossier_catalyst",
        "source_id": "cat-001",
        "headline": "NVDA catalyst",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "direction": direction,
            "expected_window": "Q3 2026",
            "specificity": specificity,
            "created_days_ago": created_days,
        },
        "impact_inputs": {
            "specificity": specificity,
            "conviction_weight": conviction,
            "direction": direction,
        },
        "attention_inputs": {
            "ticker": "NVDA",
            "direction": direction,
            "expected_window": "Q3 2026",
        },
        "confidence_inputs": {
            "specificity": specificity,
            "has_statement": has_stmt,
            "has_expected_window": has_window,
        },
        "uncertainty_inputs": {
            "inverse_specificity": 1.0 - specificity,
            "created_days_ago": created_days,
        },
        "source_versions": {"dossier_catalyst": "cat-001"},
        "user_id": None,
    }


def _watchlist(*, ticker="NVDA", added_days=5, has_name=True) -> dict:
    return {
        "candidate_type": "watchlist_candidate",
        "entity_type": "company",
        "entity_id": "wt-001",
        "ticker": ticker,
        "source_type": "watched_tickers",
        "source_id": "wt-001",
        "headline": f"{ticker} watchlist",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {"added_days_ago": added_days},
        "impact_inputs": {"ticker": ticker},
        "attention_inputs": {
            "ticker": ticker,
            "company_name": "Corp" if has_name else "",
            "added_days_ago": added_days,
        },
        "confidence_inputs": {
            "has_company_name": has_name,
            "active": True,
        },
        "uncertainty_inputs": {"added_days_ago": added_days},
        "source_versions": {"watched_tickers": "wt-001"},
        "user_id": None,
    }


def _portfolio(*, ticker="NVDA", weight=0.10, membership="owned",
                has_weight=True, has_cost=True) -> dict:
    return {
        "candidate_type": "portfolio_exposure_candidate",
        "entity_type": "portfolio",
        "entity_id": "pos-001",
        "ticker": ticker,
        "source_type": "portfolio_positions",
        "source_id": "pos-001",
        "headline": f"{ticker} portfolio",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "membership_class": membership,
            "added_days_ago": 10,
        },
        "impact_inputs": {
            "weight": weight if has_weight else None,
            "shares": 100,
            "cost_basis": 500.0 if has_cost else None,
            "membership_class": membership,
            "portfolio_name": "Test",
        },
        "attention_inputs": {
            "ticker": ticker,
            "membership_class": membership,
            "portfolio_id": "port-001",
        },
        "confidence_inputs": {
            "has_weight": has_weight,
            "has_cost_basis": has_cost,
            "is_default_portfolio": False,
        },
        "uncertainty_inputs": {
            "weight": weight if has_weight else None,
            "added_days_ago": 10,
        },
        "source_versions": {"portfolio_positions": "pos-001"},
        "user_id": None,
    }


def _delivery(*, ticker="NVDA", status="pending", attempts=1,
               severity_rank=3, has_sev=True, has_ref=True) -> dict:
    return {
        "candidate_type": "delivery_transition_candidate",
        "entity_type": "company",
        "entity_id": "dl-001",
        "ticker": ticker,
        "source_type": "delivery_ledger",
        "source_id": "dl-001",
        "headline": "Delivery transition",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "status": status,
            "attempts": attempts,
            "created_days_ago": 0,
            "canonical_severity": "high",
            "severity_rank": severity_rank,
        },
        "impact_inputs": {
            "canonical_severity": "high" if has_sev else None,
            "severity_rank": severity_rank,
            "channel": "in_app",
        },
        "attention_inputs": {
            "target_key": ticker,
            "channel": "in_app",
            "status": status,
        },
        "confidence_inputs": {
            "has_severity": has_sev,
            "attempts": attempts,
            "has_artifact_ref": has_ref,
        },
        "uncertainty_inputs": {
            "attempts": attempts,
            "created_days_ago": 0,
        },
        "source_versions": {"delivery_ledger": "dl-001"},
        "user_id": None,
    }


def _similarity(*, query_key="NVDA", candidate_key="AMD", score=0.82,
                 rank=1, built_days=0, has_contrib=True, has_dis=True) -> dict:
    return {
        "candidate_type": "similarity_candidate",
        "entity_type": "company",
        "entity_id": "edge-001",
        "ticker": query_key,
        "source_type": "similarity_edge",
        "source_id": "edge-001",
        "headline": f"{query_key} similar to {candidate_key}",
        "summary": "summary",
        "evidence_refs": [],
        "urgency_inputs": {
            "score": score,
            "rank": rank,
            "built_days_ago": built_days,
        },
        "impact_inputs": {
            "score": score,
            "rank": rank,
            "query_key": query_key,
            "candidate_key": candidate_key,
            "target_type": "company",
        },
        "attention_inputs": {
            "query_key": query_key,
            "candidate_key": candidate_key,
            "floor_passed": True,
            "score": score,
        },
        "confidence_inputs": {
            "score": score,
            "has_contributions": has_contrib,
            "has_disanalogy": has_dis,
            "score_schema": 1,
        },
        "uncertainty_inputs": {
            "inverse_score": 1.0 - score,
            "built_days_ago": built_days,
            "disanalogy": "Different revenue mix" if has_dis else "",
        },
        "source_versions": {"similarity_edge": "edge-001"},
        "user_id": None,
    }


def _sparse(ctype="forecast_candidate") -> dict:
    """A candidate where all *_inputs dicts are empty — maximum sparseness."""
    return {
        "candidate_type": ctype,
        "entity_type": "company",
        "entity_id": "sparse-001",
        "ticker": "SPARSE",
        "source_type": "unknown",
        "source_id": "sparse-001",
        "headline": "",
        "summary": "",
        "evidence_refs": [],
        "urgency_inputs": {},
        "impact_inputs": {},
        "attention_inputs": {},
        "confidence_inputs": {},
        "uncertainty_inputs": {},
        "source_versions": {},
        "user_id": None,
    }


# ---------------------------------------------------------------------------
# 1. Output keys
# ---------------------------------------------------------------------------

class TestOutputKeys:
    def test_rank_candidate_returns_required_keys(self):
        from app.services.decision_ranking_engine import rank_candidate
        result = rank_candidate(_forecast())
        missing = _REQUIRED_RESULT_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_rank_inputs_has_expected_sub_keys(self):
        from app.services.decision_ranking_engine import rank_candidate
        result = rank_candidate(_forecast())
        ri = result["rank_inputs"]
        assert "w_attention" in ri
        assert "w_urgency" in ri
        assert "w_impact" in ri
        assert "base_score" in ri

    def test_candidate_passthrough(self):
        from app.services.decision_ranking_engine import rank_candidate
        c = _forecast()
        result = rank_candidate(c)
        assert result["candidate"] is c


# ---------------------------------------------------------------------------
# 2–3. rank_candidates behaviour
# ---------------------------------------------------------------------------

class TestRankCandidates:
    def test_returns_list(self):
        from app.services.decision_ranking_engine import rank_candidates
        result = rank_candidates([_forecast(), _watchlist()])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_empty_input_returns_empty_list(self):
        from app.services.decision_ranking_engine import rank_candidates
        assert rank_candidates([]) == []

    def test_sorted_descending_by_decision_score(self):
        from app.services.decision_ranking_engine import rank_candidates
        candidates = [_watchlist(), _forecast(p_pos=0.90, p_neg=0.05)]
        result = rank_candidates(candidates)
        scores = [r["decision_score"] for r in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 4–10. All 7 candidate types produce a positive score
# ---------------------------------------------------------------------------

class TestAllCandidateTypes:
    def test_forecast_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_forecast())
        assert r["decision_score"] > 0

    def test_risk_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_risk())
        assert r["decision_score"] > 0

    def test_catalyst_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_catalyst())
        assert r["decision_score"] > 0

    def test_watchlist_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_watchlist())
        assert r["decision_score"] > 0

    def test_portfolio_exposure_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_portfolio())
        assert r["decision_score"] > 0

    def test_delivery_transition_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_delivery())
        assert r["decision_score"] > 0

    def test_similarity_candidate(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_similarity())
        assert r["decision_score"] > 0


# ---------------------------------------------------------------------------
# 11. Sparse candidate
# ---------------------------------------------------------------------------

class TestSparseCandidates:
    def test_sparse_forecast_does_not_raise(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_sparse("forecast_candidate"))
        assert r["decision_score"] >= 0

    def test_sparse_risk_does_not_raise(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_sparse("risk_candidate"))
        assert r["decision_score"] >= 0

    def test_sparse_unknown_type_does_not_raise(self):
        from app.services.decision_ranking_engine import rank_candidate
        r = rank_candidate(_sparse("unknown_future_type"))
        assert r["decision_score"] >= 0


# ---------------------------------------------------------------------------
# 12–13. Score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds:
    def _all_candidates(self):
        return [
            _forecast(), _risk(), _catalyst(), _watchlist(),
            _portfolio(), _delivery(), _similarity(),
            _sparse("forecast_candidate"),
        ]

    def test_decision_score_in_unit_interval(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.0 <= r["decision_score"] <= 1.0, \
                f"decision_score={r['decision_score']} out of [0,1] for {r['candidate_type']}"

    def test_attention_score_in_unit_interval(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.0 <= r["attention_score"] <= 1.0

    def test_urgency_score_in_unit_interval(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.0 <= r["urgency_score"] <= 1.0

    def test_impact_score_in_unit_interval(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.0 <= r["impact_score"] <= 1.0

    def test_confidence_multiplier_in_range(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.30 <= r["confidence_multiplier"] <= 1.0, \
                f"confidence_multiplier={r['confidence_multiplier']} for {r['candidate_type']}"

    def test_uncertainty_discount_in_range(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.50 <= r["uncertainty_discount"] <= 1.0, \
                f"uncertainty_discount={r['uncertainty_discount']} for {r['candidate_type']}"

    def test_exposure_multiplier_in_range(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in self._all_candidates():
            r = rank_candidate(c)
            assert 0.50 <= r["exposure_multiplier"] <= 1.50, \
                f"exposure_multiplier={r['exposure_multiplier']} for {r['candidate_type']}"


# ---------------------------------------------------------------------------
# 14–16. Monotonicity
# ---------------------------------------------------------------------------

class TestMonotonicity:
    def test_higher_p_positive_raises_forecast_score(self):
        """Higher directional probability → higher impact → higher decision_score."""
        from app.services.decision_ranking_engine import rank_candidate
        low  = rank_candidate(_forecast(p_pos=0.55, p_neg=0.30, p_neu=0.15))
        high = rank_candidate(_forecast(p_pos=0.90, p_neg=0.05, p_neu=0.05))
        assert high["decision_score"] > low["decision_score"]

    def test_near_term_horizon_raises_urgency(self):
        """Shorter horizon → higher urgency_score."""
        from app.services.decision_ranking_engine import compute_urgency_score
        near = _forecast(horizon_days=30)
        far  = _forecast(horizon_days=180)
        assert compute_urgency_score(near) > compute_urgency_score(far)

    def test_near_term_raises_decision_score(self):
        """Near-term forecast should rank higher than long-term, all else equal."""
        from app.services.decision_ranking_engine import rank_candidate
        near = rank_candidate(_forecast(horizon_days=30,  p_pos=0.70, p_neg=0.20))
        far  = rank_candidate(_forecast(horizon_days=180, p_pos=0.70, p_neg=0.20))
        assert near["decision_score"] > far["decision_score"]

    def test_higher_risk_stage_raises_urgency(self):
        """Later failure-mode stage → higher urgency and impact."""
        from app.services.decision_ranking_engine import rank_candidate
        early = rank_candidate(_risk(stage=1, matched_days=5))
        late  = rank_candidate(_risk(stage=5, matched_days=5))
        assert late["decision_score"] > early["decision_score"]

    def test_higher_similarity_score_raises_decision_score(self):
        """Stronger similarity → higher attention, urgency, impact."""
        from app.services.decision_ranking_engine import rank_candidate
        weak   = rank_candidate(_similarity(score=0.50, rank=5))
        strong = rank_candidate(_similarity(score=0.95, rank=1))
        assert strong["decision_score"] > weak["decision_score"]


# ---------------------------------------------------------------------------
# 17. Confidence damping
# ---------------------------------------------------------------------------

class TestConfidenceDamping:
    def test_zero_evidence_lowers_confidence(self):
        from app.services.decision_ranking_engine import compute_confidence_multiplier
        rich   = _forecast(ev_count=5, band_low=0.65, band_high=0.75)
        sparse = _forecast(ev_count=0, band_low=0.10, band_high=0.90)
        assert compute_confidence_multiplier(rich) > compute_confidence_multiplier(sparse)

    def test_confidence_dampens_final_score(self):
        from app.services.decision_ranking_engine import rank_candidate
        rich   = rank_candidate(_forecast(ev_count=5, band_low=0.65, band_high=0.75))
        sparse = rank_candidate(_forecast(ev_count=0, band_low=0.10, band_high=0.90))
        assert rich["decision_score"] > sparse["decision_score"]


# ---------------------------------------------------------------------------
# 18. Uncertainty damping
# ---------------------------------------------------------------------------

class TestUncertaintyDamping:
    def test_high_uncertainty_lowers_discount(self):
        from app.services.decision_ranking_engine import compute_uncertainty_discount
        certain  = _forecast(p_neu=0.05, band_low=0.70, band_high=0.80)
        uncertain = _forecast(p_neu=0.40, band_low=0.10, band_high=0.90)
        assert compute_uncertainty_discount(certain) > compute_uncertainty_discount(uncertain)

    def test_uncertainty_floor_is_0_50(self):
        from app.services.decision_ranking_engine import compute_uncertainty_discount
        # Maximum possible uncertainty: band_width=1.0, p_neutral=1.0
        worst = _forecast(p_pos=0.0, p_neg=0.0, p_neu=1.0, band_low=0.0, band_high=1.0)
        assert compute_uncertainty_discount(worst) >= 0.50

    def test_high_uncertainty_lowers_final_score(self):
        from app.services.decision_ranking_engine import rank_candidate
        certain   = rank_candidate(_forecast(p_neu=0.05, band_low=0.70, band_high=0.80))
        uncertain = rank_candidate(_forecast(p_neu=0.40, band_low=0.10, band_high=0.90))
        assert certain["decision_score"] > uncertain["decision_score"]


# ---------------------------------------------------------------------------
# 19–20. Exposure multiplier
# ---------------------------------------------------------------------------

class TestExposureMultiplier:
    def test_owned_position_amplifies_score(self):
        from app.services.decision_ranking_engine import rank_candidate
        owned    = rank_candidate(_portfolio(weight=0.20, membership="owned"))
        watchlist = rank_candidate(_portfolio(weight=None, membership="watchlist",
                                              has_weight=False))
        assert owned["exposure_multiplier"] > watchlist["exposure_multiplier"]

    def test_owned_with_high_weight_amplifies_decision_score(self):
        from app.services.decision_ranking_engine import rank_candidate
        heavy = rank_candidate(_portfolio(weight=0.30, membership="owned"))
        light = rank_candidate(_portfolio(weight=0.02, membership="watchlist"))
        assert heavy["decision_score"] > light["decision_score"]

    def test_non_portfolio_types_receive_neutral_multiplier(self):
        from app.services.decision_ranking_engine import rank_candidate
        for c in [_forecast(), _risk(), _catalyst(), _watchlist(),
                  _delivery(), _similarity()]:
            r = rank_candidate(c)
            assert r["exposure_multiplier"] == 1.0, \
                f"Expected 1.0 for {c['candidate_type']}, got {r['exposure_multiplier']}"

    def test_exposure_multiplier_ceiling_1_50(self):
        from app.services.decision_ranking_engine import compute_exposure_multiplier
        # Extreme weight: 100%
        extreme = _portfolio(weight=1.0, membership="owned")
        assert compute_exposure_multiplier(extreme) <= 1.50

    def test_exposure_multiplier_floor_0_50(self):
        from app.services.decision_ranking_engine import compute_exposure_multiplier
        # on_radar with no weight
        minimal = _portfolio(weight=None, membership="on_radar", has_weight=False)
        assert compute_exposure_multiplier(minimal) >= 0.50


# ---------------------------------------------------------------------------
# 21–22. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_candidate_same_score(self):
        from app.services.decision_ranking_engine import rank_candidate
        c = _forecast()
        r1 = rank_candidate(c)
        r2 = rank_candidate(c)
        assert r1["decision_score"] == r2["decision_score"]

    def test_rank_candidates_same_order_each_call(self):
        from app.services.decision_ranking_engine import rank_candidates
        candidates = [
            _forecast(p_pos=0.75),
            _risk(stage=3),
            _watchlist(added_days=0),
        ]
        r1 = [x["source_id"] for x in rank_candidates(candidates)]
        r2 = [x["source_id"] for x in rank_candidates(candidates)]
        assert r1 == r2

    def test_three_candidate_ordering(self):
        """A high-signal risk (stage 5) should outrank a weak watchlist."""
        from app.services.decision_ranking_engine import rank_candidates
        high_risk = _risk(stage=5, relevance=0.95, matched_days=1)
        high_risk["source_id"] = "risk-high"
        low_watch = _watchlist(added_days=300)
        low_watch["source_id"] = "watch-low"
        result = rank_candidates([low_watch, high_risk])
        assert result[0]["source_id"] == "risk-high"


# ---------------------------------------------------------------------------
# 23. Weight config invariant
# ---------------------------------------------------------------------------

class TestWeightConfig:
    def test_all_weight_rows_sum_to_one(self):
        from app.services.decision_ranking_engine import _WEIGHT_CONFIG
        for ctype, w in _WEIGHT_CONFIG.items():
            total = w["w_attention"] + w["w_urgency"] + w["w_impact"]
            assert abs(total - 1.0) < 1e-9, \
                f"Weights for {ctype!r} sum to {total}, expected 1.0"


# ---------------------------------------------------------------------------
# 24. normalize_score utility
# ---------------------------------------------------------------------------

class TestNormalizeScore:
    def test_clamps_above_one(self):
        from app.services.decision_ranking_engine import normalize_score
        assert normalize_score(1.5) == 1.0

    def test_clamps_below_zero(self):
        from app.services.decision_ranking_engine import normalize_score
        assert normalize_score(-0.5) == 0.0

    def test_passthrough_in_range(self):
        from app.services.decision_ranking_engine import normalize_score
        assert abs(normalize_score(0.42) - 0.42) < 1e-9

    def test_non_numeric_returns_zero(self):
        from app.services.decision_ranking_engine import normalize_score
        assert normalize_score(None) == 0.0
        assert normalize_score("abc") == 0.0


# ---------------------------------------------------------------------------
# 25–28. AST safety checks
# ---------------------------------------------------------------------------

def _load_tree() -> ast.AST:
    return ast.parse(_ENGINE.read_text(encoding="utf-8"))


def _get_docstring_values(tree: ast.AST) -> set:
    values: set = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                values.add(node.body[0].value.value)
    return values


class TestASTSafety:
    def test_no_sqlalchemy_or_session_imports(self):
        tree = _load_tree()
        forbidden_modules = {"sqlalchemy", "asyncio", "aiosqlite", "app.db"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fm in forbidden_modules:
                        assert fm not in part, \
                            f"Forbidden import {part!r} in ranking engine"

    def test_no_conviction_or_recommendation_imports(self):
        tree = _load_tree()
        forbidden = {
            "conviction_modeler", "conviction",
            "recommendation", "order", "execution",
            "forecast_delivery_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = [a.name for a in getattr(node, "names", [])]
                for part in ([module] + names):
                    for fw in forbidden:
                        assert fw not in part.lower(), \
                            f"Forbidden import {part!r} in ranking engine"

    def test_no_advice_language_in_string_constants(self):
        tree = _load_tree()
        docstring_values = _get_docstring_values(tree)
        banned = ["buy", "sell", "hold", "overweight", "underweight",
                  "recommend", "target price", "position size"]
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if val in docstring_values:
                    continue
                for term in banned:
                    if term in val.lower():
                        snippet = val[:60]
                        offenders.append(repr(term) + " in " + repr(snippet))
        assert not offenders, "Advice language in string constants: " + str(offenders)

    def test_no_session_add_or_db_writes(self):
        src = _ENGINE.read_text(encoding="utf-8")
        assert "session.add(" not in src, "Found session.add() in ranking engine"
        assert ".update(" not in src, "Found .update() in ranking engine"
        assert ".delete(" not in src, "Found .delete() in ranking engine"
