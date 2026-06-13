"""
Phase 10C · Slice 3 — Intelligence Ranking / Triage tests.

Covers (pure engine; no delivery, no DB, no notifications):
  - critical alert → push_now
  - high alert → push_now or digest according to rules
  - medium → digest
  - low / info → pull_only
  - below user min_severity → suppress
  - stale item demotion
  - duplicate / low-novelty suppression
  - priority_score ordering
  - deterministic output
  - future portfolio payload accepted without special-casing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import severity_model
from app.services.intelligence_ranking_service import (
    RankingDecision,
    RankedIntelligenceItem,
    rank_item,
    rank_items,
    PUSH_SCORE_THRESHOLD,
    STALE_AFTER_HOURS,
)

# A fixed reference time so recency/staleness is deterministic.
NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _alert(
    *,
    ticker="AAPL",
    severity="high",
    priority_score=0.8,
    materiality=0.8,
    relevance=0.9,
    created_at=None,
    source="material_change",
    **extra,
):
    """Build a dict-shaped intelligence item (briefing/portfolio-style)."""
    d = {
        "ticker": ticker,
        "severity": severity,
        "priority_score": priority_score,
        "materiality": materiality,
        "relevance": relevance,
        "created_at": created_at if created_at is not None else _iso(NOW),
        "source": source,
    }
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Severity → delivery class base rules
# ---------------------------------------------------------------------------

class TestSeverityBaseRules:
    def test_critical_pushes(self):
        r = rank_item(_alert(severity="critical"), now=NOW)
        assert r.delivery_class == RankingDecision.PUSH_NOW
        assert r.canonical_severity == "critical"
        assert "pushed" in r.reason_codes

    def test_high_with_strong_score_pushes(self):
        r = rank_item(_alert(severity="high", priority_score=0.9, materiality=0.9), now=NOW)
        assert r.priority_score >= PUSH_SCORE_THRESHOLD
        assert r.delivery_class == RankingDecision.PUSH_NOW

    def test_high_with_weak_score_digests(self):
        # High severity but everything else weak → composite below push threshold.
        r = rank_item(
            _alert(severity="high", priority_score=0.0, materiality=0.0,
                   relevance=0.0),
            now=NOW,
        )
        assert r.priority_score < PUSH_SCORE_THRESHOLD
        assert r.delivery_class == RankingDecision.DIGEST
        assert "high_below_push_threshold" in r.reason_codes

    def test_medium_digests(self):
        r = rank_item(_alert(severity="medium"), now=NOW)
        assert r.delivery_class == RankingDecision.DIGEST
        assert "digested" in r.reason_codes

    def test_low_is_pull_only(self):
        r = rank_item(_alert(severity="low"), now=NOW)
        assert r.delivery_class == RankingDecision.PULL_ONLY

    def test_info_is_pull_only(self):
        r = rank_item(_alert(severity="info"), now=NOW)
        assert r.delivery_class == RankingDecision.PULL_ONLY


# ---------------------------------------------------------------------------
# user min_severity suppression
# ---------------------------------------------------------------------------

class TestMinSeveritySuppression:
    def test_below_min_severity_suppressed(self):
        r = rank_item(_alert(severity="medium"), user_min_severity="high", now=NOW)
        assert r.delivery_class == RankingDecision.SUPPRESS
        assert "below_min_severity" in r.reason_codes

    def test_at_min_severity_not_suppressed(self):
        r = rank_item(_alert(severity="high", priority_score=0.9), user_min_severity="high", now=NOW)
        assert r.delivery_class != RankingDecision.SUPPRESS

    def test_critical_survives_high_floor(self):
        r = rank_item(_alert(severity="critical"), user_min_severity="high", now=NOW)
        assert r.delivery_class == RankingDecision.PUSH_NOW

    def test_info_floor_suppresses_nothing_by_severity(self):
        r = rank_item(_alert(severity="info"), user_min_severity="info", now=NOW)
        assert r.delivery_class != RankingDecision.SUPPRESS

    def test_min_severity_normalized_through_severity_model(self):
        # "alert" is a legacy delivery token → canonical HIGH (severity_model).
        r = rank_item(_alert(severity="medium"), user_min_severity="alert", now=NOW)
        assert r.delivery_class == RankingDecision.SUPPRESS


# ---------------------------------------------------------------------------
# Staleness demotion
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_stale_critical_demotes_to_digest(self):
        old = _iso(NOW - timedelta(hours=STALE_AFTER_HOURS + 1))
        r = rank_item(_alert(severity="critical", created_at=old), now=NOW)
        assert r.delivery_class == RankingDecision.DIGEST
        assert "stale_demoted" in r.reason_codes

    def test_stale_high_push_demotes_to_digest(self):
        old = _iso(NOW - timedelta(hours=STALE_AFTER_HOURS + 1))
        r = rank_item(_alert(severity="high", priority_score=0.95, materiality=0.95,
                             relevance=0.95, created_at=old), now=NOW)
        assert r.delivery_class == RankingDecision.DIGEST
        assert "stale_demoted" in r.reason_codes

    def test_stale_medium_demotes_to_pull_only(self):
        old = _iso(NOW - timedelta(hours=STALE_AFTER_HOURS + 1))
        r = rank_item(_alert(severity="medium", created_at=old), now=NOW)
        assert r.delivery_class == RankingDecision.PULL_ONLY
        assert "stale_demoted" in r.reason_codes

    def test_fresh_item_not_demoted(self):
        r = rank_item(_alert(severity="critical", created_at=_iso(NOW)), now=NOW)
        assert r.delivery_class == RankingDecision.PUSH_NOW
        assert "stale_demoted" not in r.reason_codes


# ---------------------------------------------------------------------------
# Duplicate / low-novelty suppression
# ---------------------------------------------------------------------------

class TestNoveltySuppression:
    def test_explicit_duplicate_suppressed(self):
        r = rank_item(_alert(severity="critical", is_duplicate=True), now=NOW)
        assert r.delivery_class == RankingDecision.SUPPRESS
        assert "duplicate" in r.reason_codes

    def test_low_novelty_suppressed(self):
        r = rank_item(_alert(severity="high", novelty=0.05), now=NOW)
        assert r.delivery_class == RankingDecision.SUPPRESS
        assert "low_novelty" in r.reason_codes

    def test_high_novelty_not_suppressed(self):
        r = rank_item(_alert(severity="high", priority_score=0.9, novelty=1.0), now=NOW)
        assert r.delivery_class != RankingDecision.SUPPRESS

    def test_batch_marks_second_occurrence_duplicate(self):
        a = _alert(severity="critical", content_key="same-key")
        b = _alert(severity="critical", content_key="same-key")
        ranked = rank_items([a, b], now=NOW)
        classes = sorted(r.delivery_class for r in ranked)
        # one pushes, one suppresses
        assert RankingDecision.PUSH_NOW in classes
        assert RankingDecision.SUPPRESS in classes


# ---------------------------------------------------------------------------
# priority_score ordering + determinism
# ---------------------------------------------------------------------------

class TestOrderingAndDeterminism:
    def test_priority_score_in_unit_interval(self):
        for sev in ("critical", "high", "medium", "low", "info"):
            r = rank_item(_alert(severity=sev), now=NOW)
            assert 0.0 <= r.priority_score <= 1.0

    def test_higher_severity_scores_higher_all_else_equal(self):
        crit = rank_item(_alert(severity="critical", priority_score=0.5, materiality=0.5), now=NOW)
        info = rank_item(_alert(severity="info", priority_score=0.5, materiality=0.5), now=NOW)
        assert crit.priority_score > info.priority_score

    def test_rank_items_sorted_descending(self):
        items = [
            _alert(ticker="A", severity="info"),
            _alert(ticker="B", severity="critical"),
            _alert(ticker="C", severity="medium"),
        ]
        ranked = rank_items(items, now=NOW)
        scores = [r.priority_score for r in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0].target == "B"  # critical first

    def test_deterministic_repeated_calls(self):
        item = _alert(severity="high", priority_score=0.77, materiality=0.42)
        r1 = rank_item(item, now=NOW)
        r2 = rank_item(item, now=NOW)
        assert r1 == r2  # frozen dataclass equality
        assert r1.to_dict() == r2.to_dict()

    def test_no_mutation_of_input(self):
        item = _alert(severity="critical", content_key="k")
        snapshot = dict(item)
        rank_items([item, item], now=NOW)  # triggers _with_duplicate path
        assert item == snapshot  # original dict untouched


# ---------------------------------------------------------------------------
# Input type-agnosticism
# ---------------------------------------------------------------------------

class TestInputTypes:
    def test_accepts_watchlist_alert_payload(self):
        from app.services.watchlist_alert_payload import WatchlistAlertPayload
        payload = WatchlistAlertPayload(
            ticker="NVDA", alert_type="THESIS_BREAK", severity="critical",
            title="NVDA: Thesis break", summary="thesis broke",
            source="material_change", created_at=_iso(NOW),
            priority_score=0.9, raw_refs={"materiality_score": 0.85},
        )
        r = rank_item(payload, now=NOW)
        assert r.target == "NVDA"
        assert r.canonical_severity == "critical"
        assert r.delivery_class == RankingDecision.PUSH_NOW
        # materiality pulled from raw_refs without special-casing
        assert r.components["materiality"] == pytest.approx(0.85)

    def test_accepts_briefing_item_dict(self):
        brief_item = {
            "target": "MSFT", "severity": "medium", "source": "briefing",
            "priority_score": 0.4, "created_at": _iso(NOW),
        }
        r = rank_item(brief_item, now=NOW)
        assert r.target == "MSFT"
        assert r.delivery_class == RankingDecision.DIGEST

    def test_accepts_future_portfolio_payload_without_special_casing(self):
        # A payload shape that does not exist yet: portfolio relevance.
        portfolio_item = {
            "target_key": "TSLA",
            "severity": "high",
            "portfolio_weight": 0.95,      # relevance expressed as weight
            "materiality": 0.8,
            "priority_score": 0.85,
            "source": "portfolio_relevance",
            "created_at": _iso(NOW),
        }
        r = rank_item(portfolio_item, now=NOW)
        assert r.target == "TSLA"
        assert r.source == "portfolio_relevance"
        assert r.canonical_severity == "high"
        # ranked through the same path; no portfolio-specific branch
        assert r.delivery_class in (RankingDecision.PUSH_NOW, RankingDecision.DIGEST)
        assert r.components["relevance"] == pytest.approx(0.95)

    def test_missing_optional_signals_still_total(self):
        # Only severity present — formula must still produce a valid result.
        r = rank_item({"ticker": "X", "severity": "high"}, now=NOW)
        assert 0.0 <= r.priority_score <= 1.0
        assert r.delivery_class in RankingDecision.ALL

    def test_unknown_severity_fails_low(self):
        r = rank_item({"ticker": "X", "severity": "garbage"}, now=NOW)
        assert r.canonical_severity == "info"
        assert r.delivery_class == RankingDecision.PULL_ONLY


# ---------------------------------------------------------------------------
# Purity / inertness
# ---------------------------------------------------------------------------

class TestPurity:
    def test_output_is_frozen(self):
        r = rank_item(_alert(severity="high"), now=NOW)
        with pytest.raises(Exception):
            r.priority_score = 0.0  # frozen dataclass

    def test_delivery_class_always_valid(self):
        for sev in ("critical", "high", "medium", "low", "info", "garbage"):
            r = rank_item(_alert(severity=sev), now=NOW)
            assert r.delivery_class in RankingDecision.ALL
