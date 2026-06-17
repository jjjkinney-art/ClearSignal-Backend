"""
Forecast Constants — Phase 12 · Slice 4.

Single source of truth for all constants shared across the forecasting layer:
  - Allowed forecast types and horizons
  - Mandatory disclaimer (must appear verbatim in every explanation)
  - Banned advice phrases (checked before any explanation is stored)
  - Allowed confidence labels and horizon labels

Design rules
------------
  - This module has ZERO imports (not even stdlib), so it can be safely imported
    from any Phase 12 service without risk of circular imports.
  - All constants are immutable (frozenset / tuple / str).
  - Adding or removing a constant here is the only place that changes behaviour
    across the entire forecasting layer.

Safety invariants
-----------------
  - MANDATORY_DISCLAIMER must appear verbatim in every forecast explanation.
  - BANNED_ADVICE_PHRASES are checked recursively on all user-facing prose fields
    before a forecast may be stored or delivered.
  - No constant in this module encodes a price target, expected return,
    buy/sell/hold rating, or investment recommendation.
"""

# ---------------------------------------------------------------------------
# Forecast types and horizons
# ---------------------------------------------------------------------------

ALLOWED_FORECAST_TYPES: frozenset = frozenset({
    "thesis_strengthening",
    "thesis_weakening",
    "risk_emergence",
    "catalyst_realization",
    "similarity_outcome",
    "regime_transition",
})

ALLOWED_HORIZONS: frozenset = frozenset({30, 90, 180})

HORIZON_LABELS: dict = {
    30: "near_term",
    90: "medium_term",
    180: "long_term",
}

ALLOWED_CONFIDENCE_LABELS: frozenset = frozenset({"low", "medium", "high"})

# ---------------------------------------------------------------------------
# Mandatory disclaimer
# Must appear verbatim in the `disclaimer` field of every forecast explanation.
# ---------------------------------------------------------------------------

MANDATORY_DISCLAIMER: str = (
    "These probabilities describe historical pattern frequencies and are not "
    "investment advice, price targets, or recommendations to buy or sell any "
    "security. Past patterns do not guarantee future outcomes."
)

# ---------------------------------------------------------------------------
# Banned advice phrases
# Case-insensitive substring matches.  Any of these appearing in user-facing
# prose fields (why, invalidators, evidence descriptions) must cause the
# explanation to be rejected by validate_forecast_explanation.
#
# Each entry is a complete phrase that unambiguously signals investment advice
# or an equity analyst rating — not individual words that have legitimate uses.
# ---------------------------------------------------------------------------

BANNED_ADVICE_PHRASES: tuple = (
    # Price target language
    "price target",
    "target price",
    "12-month target",
    "12 month target",
    "price objective",
    "expected price",
    # Expected return language
    "expected return",
    "return of ",          # "return of 20%" patterns
    "upside of ",          # "upside of 35%"
    "downside of ",
    "upside potential of",
    # Recommendation language
    "buy recommendation",
    "sell recommendation",
    "hold recommendation",
    "investment recommendation",
    "recommend buying",
    "recommend selling",
    "recommend holding",
    "we recommend",
    "i recommend",
    "you should buy",
    "you should sell",
    "you should hold",
    # Analyst rating language
    "strong buy",
    "strong sell",
    "overweight",
    "underweight",
    "outperform rating",
    "underperform rating",
    "market perform",
    "upgrade to buy",
    "downgrade to sell",
    "upgrade to",
    "downgrade to",
    "initiate with a",
    "rating of buy",
    "rating of sell",
    # Advice framing
    "investment advice",
    "financial advice",
    "this is not financial advice",  # disclaimer-mimicking language in content
    "not financial advice",
    "should be purchased",
    "should be sold",
)

# ---------------------------------------------------------------------------
# Forecast type display names (for prose generation)
# ---------------------------------------------------------------------------

FORECAST_TYPE_DISPLAY: dict = {
    "thesis_strengthening": "thesis strengthening",
    "thesis_weakening": "thesis weakening",
    "risk_emergence": "risk emergence",
    "catalyst_realization": "catalyst realization",
    "similarity_outcome": "peer similarity outcome",
    "regime_transition": "regime transition",
}

# ---------------------------------------------------------------------------
# Per-type invalidator templates
# These are the conditions that would negate a forecast of a given type.
# They must be factual, non-advisory, and free of banned phrases.
# ---------------------------------------------------------------------------

INVALIDATOR_TEMPLATES: dict = {
    "thesis_strengthening": (
        "Company fails to execute on the catalysts underpinning the thesis before "
        "the forecast horizon elapses.",
        "Macro or sector conditions deteriorate significantly, reducing the probability "
        "of conviction strengthening.",
        "Primary concern re-escalates materially before the thesis can consolidate.",
        "A new adverse development emerges that was not present at the time of scoring.",
    ),
    "thesis_weakening": (
        "The primary risk factor is remediated or resolved before the forecast horizon.",
        "A management transition or restructuring successfully addresses the underlying concern.",
        "New positive operating evidence contradicts the pattern established by historical analogs.",
        "A structural improvement in the company's risk profile occurs before the horizon.",
    ),
    "risk_emergence": (
        "Regulatory or legal resolution removes the identified risk factor from the picture.",
        "Company raises capital or completes a refinancing that addresses the financial risk.",
        "New positive operating data contradicts the historical base rate established by analogs.",
        "Sector or macro conditions improve in a way that reduces the risk probability.",
    ),
    "catalyst_realization": (
        "The catalyst event is delayed beyond the stated forecast horizon.",
        "A competing or offsetting event emerges that neutralises the catalyst.",
        "Company guidance or management commentary indicates the catalyst has been deferred.",
        "External conditions change in a way that removes the preconditions for the catalyst.",
    ),
    "similarity_outcome": (
        "The company exhibits a materially different trajectory from the identified similar entities.",
        "A structural difference between this company and its similarity peers becomes apparent.",
        "Similarity peer outcomes diverge significantly from the historical pattern frequency.",
        "New data updates the similarity score such that the peer set is no longer valid.",
    ),
    "regime_transition": (
        "Macro conditions stabilise and remain in the current regime beyond the horizon.",
        "Policy actions (monetary or fiscal) reverse the preconditions for a regime shift.",
        "The historical pattern frequency for regime transition does not manifest in this cycle.",
        "Sector-specific factors insulate this entity from a broader regime shift.",
    ),
}

# Invalidators that apply regardless of forecast type
GENERIC_INVALIDATORS: tuple = (
    "New material information fundamentally changes the risk profile.",
    "A structural break in the macro regime occurs outside the parameters of available analogs.",
)
