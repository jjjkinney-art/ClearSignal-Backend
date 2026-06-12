"""
Phase 9G · Slice 5B — golden-set definition.

Two things live here:

1. **Dossier fixtures** — one per golden ticker, built in the exact shape that
   ``dossier_repo.get_full_dossier`` returns and that
   ``dossier_injection_service.build_injection_block`` reads (attribute access on
   head / debate / catalysts / failure_modes / durability).  These mirror the
   facet composition observed in the Slice 5A production shadow run (e.g. NVDA /
   META have no core-debate row yet; JPM / COST / TSM do).

2. **Golden cases** — 5 tickers × 3 question archetypes (thesis-break,
   deterioration/improvement, valuation/compression).  Each case carries a
   *decisive* current-cycle evidence fixture and the unambiguous direction that
   evidence points (``evidence_direction``).  The POISON condition asserts the
   OPPOSITE direction with high conviction, so a correct model must follow the
   fresh evidence and reject the planted prior.

Pure data + light constructors.  No DB, no network, no LLM.  Imports only the
injection service (clean on Python 3.9 via ``from __future__ import annotations``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

# Fixed reference clock so fixtures, decay, and freshness are fully deterministic.
NOW: datetime = datetime(2026, 6, 12, tzinfo=timezone.utc)

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"

GOLDEN_TICKERS = ["NVDA", "JPM", "COST", "META", "TSM"]

ARCHETYPE_THESIS_BREAK = "thesis_break"
ARCHETYPE_TRAJECTORY = "deterioration_improvement"
ARCHETYPE_VALUATION = "valuation_compression"
ARCHETYPES = [ARCHETYPE_THESIS_BREAK, ARCHETYPE_TRAJECTORY, ARCHETYPE_VALUATION]


def _days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


# ===========================================================================
# Dossier fixtures (production shape: SimpleNamespace doubles)
# ===========================================================================

def _head(ticker: str, stance: str, conviction: float, concern: str,
          age_days: int = 6) -> SimpleNamespace:
    ts = _days_ago(age_days)
    return SimpleNamespace(
        ticker=ticker,
        stance=stance,
        conviction=conviction,
        primary_concern=concern,
        prior_as_of=ts,
        last_full_update_at=ts,
        updated_at=ts,
    )


def _debate(question: str, bull: str, bear: str, lean: str,
            confidence: float = 0.6, age_days: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        question=question,
        bull_pole=bull,
        bear_pole=bear,
        current_lean=lean,
        confidence=confidence,
        updated_at=_days_ago(age_days),
    )


def _catalyst(statement: str, direction: str, window: str,
              weight: float = 0.7, age_days: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        statement=statement,
        direction=direction,
        expected_window=window,
        status="open",
        conviction_weight=weight,
        created_at=_days_ago(age_days),
    )


def _failure(analog_id: str, stage: int, evidence: str,
             relevance: float = 0.6, age_days: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        analog_id=analog_id,
        sequence_stage=stage,
        stage_evidence=evidence,
        relevance_at_match=relevance,
        matched_at=_days_ago(age_days),
    )


def _durability(cycle: str, horizon: str, age_days: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        cycle_position=cycle,
        horizon_hint=horizon,
        updated_at=_days_ago(age_days),
    )


def _dossier(head, debate=None, catalysts=None, failure_modes=None,
             durability=None) -> Dict[str, Any]:
    return {
        "head": head,
        "debate": debate,
        "dimensions": [],          # moat — dormant in reduced-v1
        "catalysts": catalysts or [],
        "variant": None,           # variant_perception — dormant in reduced-v1
        "durability": durability,
        "failure_modes": failure_modes or [],
    }


def build_dossier_fixtures() -> Dict[str, Dict[str, Any]]:
    """Realistic per-ticker dossiers grounded in the 5A shadow facet mix."""
    return {
        # NVDA — no core-debate row yet (matches 5A telemetry); prior + catalysts + failure.
        "NVDA": _dossier(
            head=_head("NVDA", BULLISH, 0.78,
                       "hyperscaler capex digestion risk"),
            debate=None,
            catalysts=[
                _catalyst("Blackwell ramp absorbs data-center demand",
                          "positive", "next 2 quarters", 0.8),
                _catalyst("Sovereign-AI orders broaden customer base",
                          "positive", "FY26", 0.6),
            ],
            failure_modes=[
                _failure("capex_digestion_2019", 2,
                         "order lead-times shortening at two hyperscalers"),
            ],
            durability=_durability("mid-cycle", "12-18 months"),
        ),
        # JPM — full debate present.
        "JPM": _dossier(
            head=_head("JPM", BULLISH, 0.66, "net-interest-margin compression"),
            debate=_debate(
                "Is JPM's NII durable as rates fall?",
                "fortress balance sheet + deposit franchise defends NII",
                "rate cuts compress NIM faster than loan growth offsets",
                "lean_bull"),
            catalysts=[
                _catalyst("Credit-loss reserves stabilise", "positive",
                          "next quarter", 0.65),
            ],
            failure_modes=[
                _failure("credit_normalization_2007", 1,
                         "card net charge-offs ticking up off lows"),
            ],
            durability=_durability("late-cycle", "6-12 months"),
        ),
        # COST — full debate present.
        "COST": _dossier(
            head=_head("COST", BULLISH, 0.71, "valuation rich vs history"),
            debate=_debate(
                "Does membership pricing power justify a premium multiple?",
                "renewal rates + fee hikes compound durable FCF",
                "35x+ earnings leaves no margin for a traffic slowdown",
                "balanced"),
            catalysts=[
                _catalyst("Membership fee increase lifts high-margin revenue",
                          "positive", "FY26", 0.72),
            ],
            failure_modes=[
                _failure("multiple_compression_2000", 1,
                         "P/E at 95th percentile of 10-year range"),
            ],
            durability=_durability("late-cycle", "12+ months"),
        ),
        # META — no core-debate row yet (matches 5A telemetry).
        "META": _dossier(
            head=_head("META", BULLISH, 0.69, "AI capex with uncertain ROI"),
            debate=None,
            catalysts=[
                _catalyst("AI-driven ad targeting lifts pricing", "positive",
                          "next 2 quarters", 0.7),
                _catalyst("Reality Labs losses widen", "negative", "FY26", 0.55),
            ],
            failure_modes=[
                _failure("capex_without_roi_2022", 1,
                         "capex guide raised again with flat segment margin"),
            ],
            durability=_durability("mid-cycle", "12-18 months"),
        ),
        # TSM — full debate present.
        "TSM": _dossier(
            head=_head("TSM", BULLISH, 0.74, "geopolitical concentration risk"),
            debate=_debate(
                "Does TSM's process lead widen or narrow vs Intel Foundry?",
                "N2/A16 lead + ecosystem lock-in compounds pricing power",
                "Taiwan concentration + Intel 18A closing the gap",
                "lean_bull"),
            catalysts=[
                _catalyst("N2 ramp on schedule with strong yields", "positive",
                          "FY26", 0.78),
            ],
            failure_modes=[
                _failure("geo_concentration_risk", 1,
                         "single-region capacity for leading-edge nodes"),
            ],
            durability=_durability("mid-cycle", "18+ months"),
        ),
    }


DOSSIER_FIXTURES: Dict[str, Dict[str, Any]] = build_dossier_fixtures()


# ===========================================================================
# Golden cases
# ===========================================================================

@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    ticker: str
    archetype: str
    question: str
    # Decisive current-cycle facts handed to synthesis as the fresh evidence.
    evidence: str
    # Unambiguous direction the fresh evidence points.  POISON asserts the
    # opposite with high conviction; a correct model follows THIS.
    evidence_direction: str
    # Short note describing what a continuity-preserving, non-anchored answer
    # looks like (used in the human-readable report, not in scoring math).
    expected_behaviour: str = ""
    sector: str = field(default="")


def _cases() -> List[GoldenCase]:
    return [
        # ---- NVDA ----------------------------------------------------------
        GoldenCase(
            "NVDA_break", "NVDA", ARCHETYPE_THESIS_BREAK,
            "Does NVDA's AI-infrastructure thesis still hold this quarter?",
            "Two of the four largest hyperscalers cut FY capex guidance; "
            "data-center revenue decelerated to +3% QoQ from +28%; channel "
            "shows Blackwell order lead-times shortening.",
            BEARISH,
            "Acknowledge prior bull stance, then conclude the thesis is "
            "weakening on this cycle's deceleration — do not defend the prior.",
            sector="semiconductors",
        ),
        GoldenCase(
            "NVDA_traj", "NVDA", ARCHETYPE_TRAJECTORY,
            "Is NVDA's competitive position improving or deteriorating?",
            "Gross margin expanded 180bps; sovereign-AI backlog up 40% with "
            "three new national customers; no credible competing accelerator "
            "shipped at volume this cycle.",
            BULLISH,
            "Confirm the prior while citing the fresh margin/backlog data as "
            "the reason — continuity without merely repeating the prior.",
            sector="semiconductors",
        ),
        GoldenCase(
            "NVDA_val", "NVDA", ARCHETYPE_VALUATION,
            "Is NVDA's valuation multiple at risk of compression?",
            "Forward P/E re-rated to the 90th percentile of its 5-year range "
            "while forward EPS revisions turned negative for the first time "
            "in six quarters.",
            BEARISH,
            "Flag compression risk from the fresh re-rating + negative "
            "revisions, even though the stored prior is bullish.",
            sector="semiconductors",
        ),
        # ---- JPM -----------------------------------------------------------
        GoldenCase(
            "JPM_break", "JPM", ARCHETYPE_THESIS_BREAK,
            "Has the bull case for JPM broken given the rate path?",
            "Two consecutive quarters of NII guide-downs; card net charge-offs "
            "rose 60bps above the prior peak; reserve build accelerated.",
            BEARISH,
            "Re-adjudicate the lean_bull debate against deteriorating credit "
            "and NII — conclude the bull case is impaired this cycle.",
            sector="financials",
        ),
        GoldenCase(
            "JPM_traj", "JPM", ARCHETYPE_TRAJECTORY,
            "Is JPM's earnings power improving or deteriorating?",
            "Deposit costs stabilised, loan growth reaccelerated to +7%, and "
            "credit reserves were released as charge-offs came in below plan.",
            BULLISH,
            "Confirm improvement using the fresh deposit/loan/credit data; "
            "keep the debate framing but resolve it toward the bull pole.",
            sector="financials",
        ),
        GoldenCase(
            "JPM_val", "JPM", ARCHETYPE_VALUATION,
            "Is JPM cheap or is the multiple set to compress?",
            "Trades at 1.1x tangible book vs a 1.9x cycle peak; ROTCE held "
            "above 18% and buyback was re-authorised at a larger size.",
            BULLISH,
            "Argue the multiple looks defensible/cheap on the fresh ROTCE + "
            "capital-return data — do not import a bearish prior if one is planted.",
            sector="financials",
        ),
        # ---- COST ----------------------------------------------------------
        GoldenCase(
            "COST_break", "COST", ARCHETYPE_THESIS_BREAK,
            "Is COST's membership-compounding thesis intact?",
            "Renewal rate fell 120bps for the first time in a decade; traffic "
            "growth went negative in two regions; a fee increase was deferred.",
            BEARISH,
            "Treat the balanced-debate prior as a starting point, then conclude "
            "the compounding thesis is cracking on the fresh renewal/traffic data.",
            sector="staples",
        ),
        GoldenCase(
            "COST_traj", "COST", ARCHETYPE_TRAJECTORY,
            "Is COST's unit economics trajectory improving or deteriorating?",
            "Membership fee increase took effect with renewal rates holding at "
            "93%; e-commerce comps accelerated to +20%; gross margin up 50bps.",
            BULLISH,
            "Confirm improving trajectory on the fresh fee/renewal/margin data; "
            "acknowledge but do not just echo the prior.",
            sector="staples",
        ),
        GoldenCase(
            "COST_val", "COST", ARCHETYPE_VALUATION,
            "Is COST's premium multiple at risk of compression?",
            "Forward P/E sits at the 97th percentile of its 10-year range while "
            "forward EPS growth decelerated to high-single-digits.",
            BEARISH,
            "Flag compression risk on the fresh re-rating vs decelerating "
            "growth, even though the stored stance is bullish.",
            sector="staples",
        ),
        # ---- META ----------------------------------------------------------
        GoldenCase(
            "META_break", "META", ARCHETYPE_THESIS_BREAK,
            "Has META's AI-ROI thesis broken this quarter?",
            "Capex guide raised a third time while ad pricing decelerated and "
            "Reality Labs losses widened past consensus; segment margin flat.",
            BEARISH,
            "Conclude the AI-ROI question is unresolved/deteriorating on the "
            "fresh capex-vs-margin data — do not defend the bullish prior.",
            sector="ai_infra",
        ),
        GoldenCase(
            "META_traj", "META", ARCHETYPE_TRAJECTORY,
            "Is META's core advertising trajectory improving or deteriorating?",
            "Ad impressions +24% with pricing +10%; AI-targeting lifted "
            "conversion; operating margin expanded 300bps year over year.",
            BULLISH,
            "Confirm improving core-ad trajectory using the fresh "
            "impressions/pricing/margin data.",
            sector="ai_infra",
        ),
        GoldenCase(
            "META_val", "META", ARCHETYPE_VALUATION,
            "Is META's multiple cheap or set to compress?",
            "Trades at 14x forward earnings ex-Reality-Labs with FCF inflecting "
            "up and a fresh buyback authorisation; multiple below 5-year median.",
            BULLISH,
            "Argue the multiple looks cheap on the fresh FCF/capital-return data; "
            "resist a planted bearish prior.",
            sector="ai_infra",
        ),
        # ---- TSM -----------------------------------------------------------
        GoldenCase(
            "TSM_break", "TSM", ARCHETYPE_THESIS_BREAK,
            "Is TSM's process-leadership thesis at risk this cycle?",
            "Intel 18A reportedly hit yield parity with N3; a top customer "
            "dual-sourced leading-edge orders; N2 ramp slipped a quarter.",
            BEARISH,
            "Re-adjudicate the lean_bull process-lead debate against the fresh "
            "Intel-parity + N2-slip evidence — conclude the lead is narrowing.",
            sector="semiconductors",
        ),
        GoldenCase(
            "TSM_traj", "TSM", ARCHETYPE_TRAJECTORY,
            "Is TSM's pricing power improving or deteriorating?",
            "N2 wafer pricing raised 15% with full pre-booking; leading-edge "
            "utilisation at 100%; no customer pushed back on the price increase.",
            BULLISH,
            "Confirm improving pricing power using the fresh N2 pricing/booking "
            "data; keep the debate framing but resolve toward the bull pole.",
            sector="semiconductors",
        ),
        GoldenCase(
            "TSM_val", "TSM", ARCHETYPE_VALUATION,
            "Is TSM's multiple discounting too much geopolitical risk?",
            "Trades at a 35% forward-P/E discount to US fab peers despite "
            "higher ROIC and accelerating leading-edge revenue mix.",
            BULLISH,
            "Argue the discount looks excessive on the fresh ROIC/mix data; "
            "resist importing an over-bearish geopolitical prior.",
            sector="semiconductors",
        ),
    ]


GOLDEN_CASES: List[GoldenCase] = _cases()


def opposite_direction(direction: str) -> str:
    if direction == BULLISH:
        return BEARISH
    if direction == BEARISH:
        return BULLISH
    return NEUTRAL
