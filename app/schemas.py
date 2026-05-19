"""
Pydantic schemas defining request, context, and response models for the AI analyst backend.

This module introduces strongly typed models to replace the previous blob‑like
string fields.  Lists are used for multi‑item fields such as bull/bear cases,
risks, and catalysts.  Nested models capture the structure of each
specialist agent's output as well as the synthesizer's final summary.
"""

from __future__ import annotations

import uuid as _uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# Import field_validator for pydantic v2; fall back to validator for v1.  In v2
# field_validator replaces the old validator decorator.  We alias validator
# to field_validator when pydantic v2 is not present so that the same
# decorator name works across versions.
try:  # pragma: no cover - pydantic v2
    from pydantic import field_validator  # type: ignore
except ImportError:  # pragma: no cover - pydantic v1
    from pydantic import validator as field_validator  # type: ignore  # noqa: F401


# -----------------------------------------------------------------------------
# Evidence integration models
#
# These typed models capture structured evidence from external data sources.
# They are defined after importing BaseModel to ensure that the class is
# available.  GroundingContext references these models to store normalized
# data such as company profiles, market snapshots, financial statements and
# filings metadata.


class RetrievedEvidence(BaseModel):
    """A single piece of retrieved evidence for a general finance question.

    Produced by retrieve_general_finance_evidence() and injected into the
    general finance and fallback prompts as grounding context.  The LLM
    is instructed to prioritize this evidence over generic abstractions and
    to explain WHY each piece matters for the question asked.

    Fields
    ------
    title       Short headline or title of the source article/data point.
    source      Publication, API, or data provider name.
    summary     1-3 sentence summary of the relevant finding.
    timestamp   ISO-8601 date string (YYYY-MM-DD) of when the data was published.
    relevance_score  0.0–1.0 relevance of this evidence to the question.
                     Scored by the retrieval layer; higher → more relevant.
    """

    title: str = Field(..., description="Short headline or title of the evidence item")
    source: str = Field(..., description="Publication or data provider name")
    summary: str = Field(..., description="1-3 sentence summary of the relevant finding")
    timestamp: str = Field(..., description="Publication date (YYYY-MM-DD)")
    relevance_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Relevance score 0.0–1.0; higher items are shown first in the prompt",
    )


class CompanyProfile(BaseModel):
    """Basic company profile information.

    Fields are optional to allow partial results when data is missing.
    """
    name: Optional[str] = None
    industry: Optional[str] = None
    sector: Optional[str] = None
    description: Optional[str] = None
    ceo: Optional[str] = None
    website: Optional[str] = None
    ticker: Optional[str] = None


class MarketSnapshot(BaseModel):
    """Real‑time quote and market snapshot metrics."""
    price: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    high_52_week: Optional[float] = None
    low_52_week: Optional[float] = None


class FinancialContext(BaseModel):
    """Recent financial statement context."""
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    ebitda: Optional[float] = None
    eps: Optional[float] = None


class FilingContext(BaseModel):
    """Metadata for a single SEC filing."""
    filing_type: Optional[str] = None
    filing_date: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class GroundingContext(BaseModel):
    """Contextual information passed to agents.

    This structure encapsulates known facts and data about the company
    that can be injected into prompts.  It separates supplied facts
    from inferred reasoning to discourage the model from fabricating
    precise numbers.  Fields can be enriched later by external data
    sources (financial APIs, news, etc.).
    """

    company: str
    ticker: Optional[str] = None
    user_question: Optional[str] = None
    known_facts: List[str] = Field(default_factory=list)
    # Legacy financials dictionary retained for backward compatibility.  Use
    # ``financial_context`` for structured financial data.
    financials: Dict[str, float] = Field(default_factory=dict)
    recent_events: List[str] = Field(default_factory=list)
    macro_context: List[str] = Field(default_factory=list)
    source_notes: List[str] = Field(default_factory=list)
    # New structured evidence fields
    company_profile: Optional[CompanyProfile] = None
    market_snapshot: Optional[MarketSnapshot] = None
    financial_context: Optional[FinancialContext] = None
    filings_context: List[FilingContext] = Field(default_factory=list)
    # PRIMARY meaning-native history objects — consumed by monitoring, alerts, learning
    # Keys: "price", "financial", "event", "signal", "alert"
    historical_meanings: Dict[str, Any] = Field(default_factory=dict)


class AnalysisRequest(BaseModel):
    """Schema for incoming analysis requests.

    The caller provides a company name and optional question.  A
    ``GroundingContext`` can also be supplied to enrich the analysis,
    although this is optional in the API layer and may be constructed
    internally based on company metadata.
    """

    company_name: str = Field(..., description="Company name or ticker to analyze")
    user_question: Optional[str] = Field(None, description="Optional user question")
    analysis_depth: Optional[str] = Field(
        "standard", description="Depth of analysis (e.g. standard, deep)")
    output_style: Optional[str] = Field(
        None, description="Optional output style preference")
    context: Optional[GroundingContext] = Field(
        None, description="Optional structured context to ground the analysis")

    # Optional personalization parameters.  These hooks allow callers to
    # indicate areas of focus (e.g. growth, value, macro, risk), how
    # sensitive they are to changes (low, medium, high), and which alert
    # types they care about.  The backend uses these hints to adjust
    # signal prioritization and alert triggering without requiring
    # full user profiles.  All fields are optional and default to None.
    user_focus: Optional[str] = Field(
        None,
        description="Optional focus area for personalization (e.g. growth, value, macro, risk)",
    )
    sensitivity_threshold: Optional[str] = Field(
        None,
        description="Optional sensitivity threshold for alerting (low, medium, high)",
    )
    preferred_alert_types: Optional[List[str]] = Field(
        None,
        description="Optional list of preferred alert types to receive",
    )



class EquityAnalysis(BaseModel):
    """Structured output from the Equity Analyst.

    All list fields represent bullet‑style items returned by the model.
    """

    # Default to empty lists so fallback instances can be created safely
    business_overview: List[str] = Field(default_factory=list)
    bull_case: List[str] = Field(default_factory=list)
    bear_case: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    key_catalysts: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class MacroAnalysis(BaseModel):
    """Structured output from the Macro Analyst."""

    macro_overlay: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class OpportunityAnalysis(BaseModel):
    """Structured output from the Opportunity Scanner."""

    opportunity_summary: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class ResearchAnalysis(BaseModel):
    """Structured output from the Research Synthesizer."""

    research_summary: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class EducationAnalysis(BaseModel):
    """Structured output from the Education/Explanation agent."""

    education_summary: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class AccountingAnalysis(BaseModel):
    """Structured output from the Accounting/Operations analyst."""

    accounting_summary: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    """Structured output from the synthesizer (Head Analyst).

    This model aggregates all specialist outputs and adds ranked lists,
    confidence metrics, and thesis fragility information.  Lists must
    reflect prioritization order where relevant.  Confidence score is
    expressed between 0 and 1.  All list fields default to empty
    lists if the synthesizer omits them.
    """

    business_overview: List[str] = Field(default_factory=list)
    bull_case: List[str] = Field(default_factory=list)
    bear_case: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    key_catalysts: List[str] = Field(default_factory=list)
    macro_overlay: List[str] = Field(default_factory=list)
    opportunity_summary: List[str] = Field(default_factory=list)
    research_summary: List[str] = Field(default_factory=list)
    education_summary: List[str] = Field(default_factory=list)
    accounting_summary: List[str] = Field(default_factory=list)
    key_drivers_ranked: List[str] = Field(default_factory=list)
    key_risks_ranked: List[str] = Field(default_factory=list)
    what_to_monitor: List[str] = Field(default_factory=list)
    what_changes_the_thesis: List[str] = Field(default_factory=list)
    final_verdict: str = Field(default="neutral")
    verdict_reasoning: str = Field(default="")
    confidence_score: float = Field(default=0.0)
    confidence_reasoning: str = Field(default="")
    thesis_fragility: str = Field(default="")
    assumptions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)

    # Post-processing derived fields — populated by the normalization layer,
    # not by the model.  Optional/empty-list defaults so existing callers that
    # construct SynthesisOutput directly are unaffected.
    stance: Optional[str] = Field(
        default=None,
        description="Derived investment stance: bullish/constructive/neutral/cautious/bearish",
    )
    confidence_level: Optional[str] = Field(
        default=None,
        description="Derived confidence level: high/medium/low",
    )
    what_would_change_this_view: List[str] = Field(
        default_factory=list,
        description="2–4 causal events that would change the current stance, derived from signals",
    )

    # In pydantic v2, validators should be defined with field_validator; in
    # pydantic v1, this alias falls back to the standard validator decorator.
    @field_validator("confidence_score")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence_score is within the [0,1] range.

        If the value is None, return 0.0 to provide a safe default.  Otherwise
        raise a ValueError when the provided score is outside the valid
        interval.  This function is decorated as a classmethod to support
        pydantic v1 semantics.
        """
        if v is None:
            return 0.0
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence_score must be between 0 and 1")
        return v


class AnalysisResponse(BaseModel):
    """Final response returned by the /analyze endpoint.

    Contains individual specialist outputs and the synthesized summary.
    """

    company: str
    request_id: str
    equity: EquityAnalysis
    macro: MacroAnalysis
    opportunity: OpportunityAnalysis
    research: ResearchAnalysis
    education: EducationAnalysis
    accounting: AccountingAnalysis
    synthesis: SynthesisOutput

    # Include routing metadata in the analysis response.  This field
    # contains structured information about which agents were selected,
    # which were skipped, the reasons for those decisions, and the
    # routing confidence score.  It defaults to an empty dict to
    # ensure the response is always schema‑safe.
    routing: Dict[str, Any] = Field(default_factory=dict)

    # Temporary debug field — mirrors synthesis.verdict_reasoning at the top
    # level so the frontend can confirm it is present in the serialized response
    # without having to dig into the nested synthesis object.
    # TODO: remove once verdict_reasoning is confirmed non-empty in production.
    debug_verdict_reasoning: str = Field(default="")


class GeneralFinanceAnswer(BaseModel):
    """Structured answer for general finance questions (non-company intents).

    Returned by the general finance agent for market_question,
    investing_education, and portfolio_question intents.  The ``answer``
    field holds a direct 1–2 sentence response; ``bullets`` expand it
    with mechanism, context, and a practical takeaway; ``caveats`` note
    what could change or what the user should watch.
    """

    answer: str = Field(default="", description="Direct 1–2 sentence answer to the question")
    bullets: List[str] = Field(
        default_factory=list,
        description="3–4 elaboration points: mechanism, context, what to watch, takeaway",
    )
    caveats: List[str] = Field(
        default_factory=list,
        description="1–2 honest caveats: what could change this view or what to watch",
    )
    # Internal routing metadata — set by the agent after evidence retrieval so
    # route_question can gate the generic-language fallback on whether real FRED
    # data was available.  Not part of the user-facing API contract; the
    # frontend ignores unknown fields.
    evidence_count: int = Field(
        default=0,
        description="Number of FRED evidence items retrieved for this answer (routing metadata)",
    )


class QuestionRequest(BaseModel):
    """Schema for routing questions to appropriate agents."""

    company_name: str = Field(..., description="Company name or ticker relevant to the question")
    question: str = Field(..., description="User question to route to the appropriate agent")
    intent: Optional[str] = Field(
        None,
        description="Optional intent hint from the frontend classifier: "
                    "market_question | investing_education | portfolio_question | company_analysis",
    )
    context: Optional[GroundingContext] = Field(
        None, description="Optional context to ground the question and classification")


class AgentAnswerResponse(BaseModel):
    """Response schema for question routing endpoint."""

    company: str
    request_id: str
    agents_used: List[str]
    answer: Dict

    # Provide routing metadata for question classification.  This
    # mirrors the routing field on AnalysisResponse and includes
    # selected_agents, skipped_agents, reasons, and confidence.  The
    # field defaults to an empty dict to keep the schema safe when
    # routing information is unavailable.
    routing: Dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# Intelligence upgrade models
#
# These models support advanced reasoning capabilities such as thesis change
# detection and alert generation.  They are optional outputs of higher
# intelligence layers and can be used by monitoring and watchlist services.

class ThesisChangeResult(BaseModel):
    """Summary of changes detected between two analyses.

    This model encapsulates whether the thesis has changed, how severe the
    change is, a human‑readable summary of the changes, a list of
    components that have changed, and the expected impact on the thesis.
    All fields have sensible defaults to ensure that instances are safe to
    construct even when change detection fails or returns no differences.
    """

    has_changed: bool = False
    change_severity: str = "low"
    change_summary: str = "No significant changes detected."
    changed_components: List[str] = Field(default_factory=list)
    impact_on_thesis: str = "No impact."


class Alert(BaseModel):
    """Structured alert with metadata for prioritization and interpretation.

    Alerts are generated by monitoring services when new events or
    significant changes occur.  Each alert includes a type, severity,
    a concise reason, an explanation of the potential impact, and a
    recommended interpretation to guide the user.  Instances are
    Pydantic models to ensure schema safety and support future
    expansion.
    """

    alert_type: str
    severity: str
    reason: str
    impact_explanation: str
    recommended_interpretation: str
    # Interpretive fields describing historical patterns and meaning.  These
    # provide context about the type of pattern the change belongs to (e.g.,
    # cluster, isolated or trend shift), summarise the historical behaviour
    # of similar changes, report the most typical historical outcome, and
    # offer a concise interpretive summary explaining why the user should
    # care.  All fields are optional and may be omitted when no historical
    # data is available.
    pattern_type: Optional[str] | None = None  # cluster / isolated / trend shift
    historical_behavior: Optional[str] | None = None  # summary of outcome counts
    typical_outcome: Optional[str] | None = None  # alert / reanalysis / thesis_change / none
    interpretive_summary: Optional[str] | None = None  # one or two sentence narrative
    why_this_matters: Optional[str] | None = None  # explanation for significance

    # Internal meaning-first fields.  These fields support deeper
    # interpretation of alerts.  ``historical_case_type`` classifies
    # whether similar situations were predominantly alert-heavy,
    # reanalysis-heavy, thesis-change-heavy, noise-heavy or mixed.
    # ``usual_historical_meaning`` conveys the dominant outcome in
    # plain language (e.g., "alert only", "re-analysis", "thesis change",
    # "no action").  ``current_case_interpretation`` describes
    # whether the present change appears to be a continuation,
    # escalation or isolated anomaly.  ``why_this_is_notable``
    # provides a concise reason why the alert is significant.
    historical_case_type: Optional[str] | None = None
    usual_historical_meaning: Optional[str] | None = None
    current_case_interpretation: Optional[str] | None = None
    why_this_is_notable: Optional[str] | None = None

    # Deprecated interpretive fields retained for backward compatibility.  These
    # may be left unset in the final completion pass but remain in the
    # schema to avoid breaking older clients.
    historical_pattern_description: Optional[str] | None = None
    pattern_frequency: Optional[str] | None = None
    historical_outcome_summary: Optional[str] | None = None
    interpretive_significance: Optional[str] | None = None

# -----------------------------------------------------------------------------
# New interpretation-first models introduced in the final completion pass.
# These models capture the primary abstractions used by the backend.  They
# supersede label- and score-based representations and are used internally to
# drive reasoning before any numeric metrics are considered.  Each model
# encapsulates the core meaning of a situation so that downstream logic can
# operate on interpretations rather than raw counts or scores.

class HistoricalMeaning(BaseModel):
    """Meaning-native primary output of history/evidence processing.

    This object is the authoritative description of what a historical domain
    pattern MEANS, not a bundle of metric labels.  It is produced by the
    evidence layer and consumed directly by monitoring, alerts, and learning.

    Raw stats (counts, averages, volatility) are internal to the evidence
    layer and must NOT appear here as primary fields.  They may be attached
    to ``supporting_metrics`` only.

    Fields
    ------
    domain              : "price" | "financial" | "event" | "signal" | "alert"
    situation_archetype : canonical meaning class for this pattern
                          e.g. "persistent-growth", "stress-cluster",
                               "isolated-anomaly", "fading-pattern",
                               "structural-shift", "noise-regime"
    historical_pattern  : one-sentence description of what historically happened
    pattern_stability   : "stable" | "unstable" | "shifting" — is the pattern holding?
    pattern_direction   : "improving" | "deteriorating" | "stable" — trend meaning
    escalation_likelihood : "high" | "medium" | "low" — tendency to worsen
    usual_consequence   : "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary     : full human-readable synthesis (no raw numbers)
    supporting_metrics  : dict of raw stats for transparency only
    """

    domain: str
    situation_archetype: str
    historical_pattern: str
    pattern_stability: str          # "stable" | "unstable" | "shifting"
    pattern_direction: str          # "improving" | "deteriorating" | "stable"
    escalation_likelihood: str      # "high" | "medium" | "low"
    usual_consequence: str          # "thesis_change" | "reanalysis" | "alert" | "noise"
    meaning_summary: str
    supporting_metrics: Optional[Dict[str, Any]] = None


class HistoricalInterpretation(BaseModel):
    """Primary output of historical processing.

    This object summarises a historical pattern in human terms.  It conveys
    what type of situation occurred, how the pattern evolved, what its
    direction and strength were, how similar patterns behaved in the past,
    which outcomes were typical, and provides a concise interpretation.

    Fields default to None when information is unavailable.
    """

    situation_type: Optional[str] = None  # cluster / isolated / trend_shift / other
    pattern_direction: Optional[str] = None  # increasing / decreasing / stable
    pattern_strength: Optional[str] = None  # strong / moderate / weak
    historical_behavior: Optional[str] = None  # summary of how the pattern evolved
    typical_outcome: Optional[str] = None  # alert / reanalysis / thesis_change / noise / none
    interpretation_summary: Optional[str] = None  # human‑readable interpretation


class MonitoringDecision(BaseModel):
    """Primary representation of a monitoring decision.

    This model captures the interpretation-driven decision for an event.  It
    includes the contextual interpretation of the current event, the
    interpretation of historical patterns, an expected outcome based on those
    patterns, the chosen action, a reasoning narrative, a confidence score,
    and any supporting metrics used as secondary inputs.  If the supporting
    metrics were removed, the decision should still be explainable.
    """

    contextual_interpretation: str
    historical_interpretation: Optional[str] = None
    expected_outcome: Optional[str] = None
    action: str
    decision_reason: str
    confidence: float
    supporting_metrics: Optional[Dict[str, Any]] = None


class AlertInterpretation(BaseModel):
    """Primary interpretation used to construct an alert.

    Alerts are derived from meaning first.  This model describes the type of
    situation detected, the dominant historical meaning of similar patterns,
    which outcomes were typical, an interpretation of the current case, and
    why this instance matters.  It also carries a confidence estimate and
    optional supporting metrics for transparency.
    """

    situation_type: Optional[str] = None  # cluster / anomaly / trend_shift / isolated
    historical_meaning: Optional[str] = None  # e.g. "alert only", "re‑analysis", etc.
    typical_outcome: Optional[str] = None  # alert / reanalysis / thesis_change / noise / none
    current_case_interpretation: Optional[str] = None  # continuation / escalation / anomaly
    why_this_matters: Optional[str] = None  # succinct significance statement
    confidence: Optional[float] = None
    supporting_metrics: Optional[Dict[str, Any]] = None


class SignalProfileModel(BaseModel):
    """Primary representation of a signal's behavioural profile.

    Learning assigns each signal to a profile type before considering any
    weights.  This object captures the outcome distribution, the dominant
    outcome, a summary of behaviour and a recommended downstream policy.  It
    serves as the first-order representation of what a signal means.
    """

    profile_type: str  # thesis-driven / reanalysis-driven / alert-driven / noise-driven
    outcome_distribution: Dict[str, int]
    dominant_outcome: str
    outcome_behavior_summary: str
    behavior_policy: str  # highest priority / medium-high priority / medium priority / reduced priority


# =============================================================================
# Investment Intelligence schemas — company-aware multi-agent thesis layer
# =============================================================================

class CompanyContext(BaseModel):
    """Normalised company identity resolved from a user query.

    Produced by company_detection.detect_company() and consumed by every
    investment agent and the thesis synthesiser.  Carries both the canonical
    ticker and human-readable metadata needed to scope evidence retrieval and
    label outputs correctly.
    """

    ticker: str = Field(..., description="Exchange ticker symbol, e.g. 'AAPL'")
    company_name: str = Field(..., description="Canonical company name")
    sector: Optional[str] = Field(None, description="GICS sector (e.g. 'Technology')")
    industry: Optional[str] = Field(None, description="GICS industry group")
    aliases: List[str] = Field(
        default_factory=list,
        description="Input aliases that resolved to this company",
    )


class Signal(BaseModel):
    """A single ranked investment signal extracted from specialist agent analysis.

    Signals are the atomic unit of the decision-intelligence layer.  They
    capture *what matters* in a normalized, comparable form so that the
    signal ranker can deduplicate, merge, and prioritize across all five
    specialist agents before synthesis.

    signal_type values:
        structural  — durable competitive advantage or structural headwind
        cyclical    — business-cycle-driven effect (hardware upgrade, ad spend)
        risk        — specific downside risk with transmission mechanism
        catalyst    — near-term event or data point that moves the thesis
        valuation   — multiple, DCF, or relative-value observation
        macro       — macro regime effect on this specific company
        quality     — FCF conversion, management, capital allocation signal
        noise       — generic or non-actionable — will be filtered out

    time_horizon values: short_term | medium_term | long_term
    direction values:    bullish | bearish | neutral
    """

    signal: str = Field(..., description="1-2 sentence specific signal statement")
    explanation: str = Field(
        default="",
        description="Causal explanation: mechanism → specific P&L/multiple effect",
    )
    impact_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Estimated impact on the investment thesis (0=negligible, 1=thesis-defining)",
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Confidence in this signal given available evidence",
    )
    signal_type: str = Field(
        default="structural",
        description="structural|cyclical|risk|catalyst|valuation|macro|quality|noise",
    )
    time_horizon: str = Field(
        default="medium_term",
        description="short_term|medium_term|long_term",
    )
    direction: str = Field(
        default="neutral",
        description="bullish|bearish|neutral",
    )
    source_agent: str = Field(
        default="",
        description="Agent that produced this signal (valuation/macro/risk/market/quality)",
    )
    evidence_refs: List[str] = Field(
        default_factory=list,
        description="Evidence item titles or numbers that support this signal",
    )
    importance_reason: str = Field(
        default="",
        description="Why this signal matters more than others for the investment decision",
    )
    evidence_origin: str = Field(
        default="",
        description=(
            "Human-readable source of this signal: "
            "'earnings call', 'SEC filing', 'macro rates context', "
            "'estimate revisions', 'news', 'market data'"
        ),
    )
    source_category: str = Field(
        default="",
        description=(
            "Categorical source type: "
            "earnings|filing|macro|news|research|estimate_revision|market_data"
        ),
    )


class CompressedThesis(BaseModel):
    """Compressed decision-intelligence view of an investment thesis.

    Designed for meaning-first, signal-first rendering.  The frontend
    should display this *above* the long-form bull/bear prose.

    Fields are ordered by rendering priority:
      1. direct_answer       — answers the user's exact question
      2. top_signals         — 3 highest-impact signals (signal cards)
      3. one_sentence_thesis — single-sentence position statement
      4. why_it_matters      — causal paragraph explaining stakes
      5. what_changes_this_view — 4 thesis-flipping triggers
    """

    direct_answer: str = Field(
        default="",
        description="2-3 sentences directly answering the user's question with specific mechanisms",
    )
    top_signals: List[Signal] = Field(
        default_factory=list,
        description="Top 3 highest-impact signals ranked by the signal ranker",
    )
    one_sentence_thesis: str = Field(
        default="",
        description="Single sentence capturing the investment position and primary driver",
    )
    why_it_matters: str = Field(
        default="",
        description="1-2 sentences explaining why the top signal is the dominant factor",
    )
    what_changes_this_view: List[str] = Field(
        default_factory=list,
        description="4 company-specific triggers that would materially flip the thesis",
    )


class ValuationView(BaseModel):
    """Structured output of the valuation specialist agent.

    All text fields default to '' so the model can be constructed safely
    even when LLM synthesis is skipped (graceful degradation path).
    ``evidence_used`` lists the titles of evidence items the agent consumed,
    enabling downstream citation tracking.
    """

    pe_assessment: str = Field(default="", description="P/E vs sector and history")
    growth_view: str = Field(default="", description="Revenue and EPS growth trajectory")
    margin_trend: str = Field(default="", description="Operating and net margin trend")
    discount_sensitivity: str = Field(
        default="", description="Valuation sensitivity to discount-rate moves"
    )
    relative_value: str = Field(
        default="", description="Relative value vs sector peers"
    )
    overall: str = Field(default="", description="Summary valuation assessment")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_used: List[str] = Field(
        default_factory=list, description="Evidence titles consumed by this agent"
    )
    signals: List[Signal] = Field(
        default_factory=list,
        description="Structured signals extracted by this agent",
    )


class MacroSensitivity(BaseModel):
    """Structured output of the macro specialist agent.

    Captures how a company's fundamentals and valuation respond to macro
    regimes — rates, inflation, recession, and cyclical turning points.
    """

    rate_sensitivity: str = Field(
        default="", description="Impact of rate moves on valuation and earnings"
    )
    inflation_sensitivity: str = Field(
        default="", description="Pricing power and cost-pass-through ability"
    )
    recession_risk: str = Field(
        default="", description="Revenue and margin vulnerability in a downturn"
    )
    cyclicality: str = Field(
        default="", description="Cyclical vs defensive revenue mix"
    )
    overall: str = Field(default="", description="Summary macro sensitivity view")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_used: List[str] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)


class RiskProfile(BaseModel):
    """Structured output of the risk specialist agent.

    Draws primarily on SEC filing evidence and balance-sheet metrics to
    quantify and characterise the key risks an investor faces.
    """

    debt_risk: str = Field(
        default="", description="Leverage, interest coverage, and refinancing risk"
    )
    competitive_risk: str = Field(
        default="", description="Competitive moat erosion and market-share threats"
    )
    regulatory_risk: str = Field(
        default="", description="Regulatory exposure and compliance burden"
    )
    concentration_risk: str = Field(
        default="", description="Customer, supplier, or geography concentration"
    )
    key_risks: List[str] = Field(
        default_factory=list, description="Top 3-5 risks in bullet form"
    )
    overall: str = Field(default="", description="Summary risk assessment")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_used: List[str] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)


class MarketContext(BaseModel):
    """Structured output of the market specialist agent.

    Captures near-term catalysts, sentiment, and price dynamics from
    recent news and price-change evidence.
    """

    recent_catalysts: List[str] = Field(
        default_factory=list, description="Key catalysts from recent news"
    )
    momentum: str = Field(
        default="", description="Price momentum and technical positioning"
    )
    sentiment: str = Field(
        default="", description="Analyst and market sentiment"
    )
    positioning: str = Field(
        default="", description="Institutional and retail positioning signals"
    )
    overall: str = Field(default="", description="Summary market context")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_used: List[str] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)


class QualityAssessment(BaseModel):
    """Structured output of the quality specialist agent.

    Assesses business durability — competitive moat, management track record,
    capital-allocation discipline, and revenue quality.
    """

    moat: str = Field(
        default="", description="Competitive advantages and their durability"
    )
    management: str = Field(
        default="", description="Management quality and track record"
    )
    capital_allocation: str = Field(
        default="", description="Buybacks, dividends, R&D, and M&A discipline"
    )
    revenue_durability: str = Field(
        default="", description="Recurring vs one-time revenue; customer stickiness"
    )
    operating_quality: str = Field(
        default="", description="Margin consistency, FCF conversion, asset intensity"
    )
    overall: str = Field(default="", description="Summary quality assessment")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_used: List[str] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)


class InvestmentThesis(BaseModel):
    """Synthesised investment thesis produced by the thesis synthesiser.

    Combines outputs from all five specialist agents into a balanced,
    evidence-grounded thesis with explicit bull and bear cases, confidence
    scoring, and a deterministic list of what would change the view.

    Distinct from ``SynthesisOutput`` (which is the legacy company-analysis
    synthesis): ``InvestmentThesis`` is the output of the new multi-agent
    investment intelligence pipeline.
    """

    ticker: str = Field(..., description="Ticker symbol")
    company_name: str = Field(..., description="Canonical company name")
    bull_thesis: str = Field(default="", description="Bull case narrative")
    bear_thesis: str = Field(default="", description="Bear case narrative")
    key_drivers: List[str] = Field(
        default_factory=list, description="Top 3-5 value drivers"
    )
    key_risks: List[str] = Field(
        default_factory=list, description="Top 3-5 investment risks"
    )
    valuation_view: str = Field(
        default="", description="Valuation summary from the valuation agent"
    )
    macro_sensitivity: str = Field(
        default="", description="Macro sensitivity summary"
    )
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_reasoning: str = Field(
        default="", description="Why the confidence level was assigned"
    )
    what_changes_the_thesis: List[str] = Field(
        default_factory=list,
        description="Events or data that would materially change this view",
    )
    direct_answer: str = Field(
        default="",
        description=(
            "Direct answer to the user's exact question (1-3 sentences). "
            "Must be populated when original_user_question is supplied. "
            "Rendered above the broader conclusion in the UI."
        ),
    )
    conclusion: str = Field(
        default="", description="One-paragraph investment conclusion"
    )
    evidence_count: int = Field(
        default=0, description="Total evidence items consumed across all agents"
    )
    generated_at: str = Field(
        default="", description="ISO-8601 UTC timestamp of generation"
    )
    # Governance flags set by the consistency checker
    consistency_warnings: List[str] = Field(
        default_factory=list,
        description="Deterministic contradictions flagged by the governance layer",
    )
    # Signal prioritization layer (Phase 1-4)
    top_signals: List[Signal] = Field(
        default_factory=list,
        description="Top 3 highest-impact signals ranked across all agents — render above prose",
    )
    top_risks: List[Signal] = Field(
        default_factory=list,
        description="Top risk-direction signals ranked by severity",
    )
    secondary_signals: List[Signal] = Field(
        default_factory=list,
        description="Secondary signals (lower impact, but informative)",
    )
    one_sentence_thesis: str = Field(
        default="",
        description="Single sentence capturing the core investment position",
    )
    compressed_thesis: Optional[CompressedThesis] = Field(
        default=None,
        description="Compressed decision-intelligence view for meaning-first UI rendering",
    )
    # ── Temporal intelligence (Refinement 4) ──────────────────────────────────
    # Extension points for timeline memory. When no prior thesis exists all three
    # fields default safely so existing rendering is unaffected.
    what_changed: List[str] = Field(
        default_factory=list,
        description=(
            "Specific changes from the prior thesis for this ticker, if one exists. "
            "Empty list when no prior thesis is available."
        ),
    )
    thesis_trend: str = Field(
        default="unclear",
        description=(
            "strengthening | weakening | stable | unclear — direction of the thesis "
            "relative to the prior version. 'unclear' when no prior thesis exists."
        ),
    )
    change_drivers: List[str] = Field(
        default_factory=list,
        description=(
            "Company-specific events or data that are driving the thesis trend. "
            "Empty list when no prior thesis is available."
        ),
    )

    # ── Cognition quality fields ───────────────────────────────────────────────
    core_debate: str = Field(
        default="",
        description=(
            "The single central analytical question the market is debating for this ticker. "
            "Everything else in the thesis should orbit around this. "
            "Example: 'Can Services growth offset duration pressure at current multiples?' "
            "Example: 'Is AI demand already fully priced, or is the runway underestimated?' "
            "Example: 'Does regulatory risk now matter more than the growth trajectory?'"
        ),
    )
    core_market_debate: str = Field(
        default="",
        description=(
            "The live, unresolved market positioning question for this ticker — "
            "phrased as a PM would frame it in an IC meeting. "
            "Focuses on what the market has/has not priced, consensus vs non-consensus, "
            "and what would change positioning. NOT explanatory or academic. "
            "Example: 'Is Services growth durable enough to offset hardware cyclicality?' "
            "Example: 'Is Nvidia demand structural or peak-cycle behavior?' "
            "Example: 'Can Meta sustain margin discipline while reaccelerating capex?' "
            "Example: 'Is the market underestimating rate duration risk for Apple?'"
        ),
    )
    dominant_dimension: str = Field(
        default="",
        description="Dominant analytical frame for this thesis (macro/valuation/regulatory/operational/capital_allocation/competitive/behavioral)",
    )


class AlertCondition(BaseModel):
    """A condition to watch that triggers an alert when its threshold is crossed.

    Used by the monitoring layer to evaluate live readings against declared
    thresholds.  Completely distinct from the existing ``Alert`` model (which
    represents a triggered alert); ``AlertCondition`` is the *rule* while
    ``Alert`` is the *event*.
    """

    condition_id: str = Field(
        default="", description="Unique identifier for this condition"
    )
    type: str = Field(
        ...,
        description=(
            "Condition type, e.g. 'yield_curve_reinversion', "
            "'margin_compression', 'debt_increase', 'guidance_weakness', "
            "'volatility_spike'"
        ),
    )
    threshold: float = Field(
        default=0.0, description="Numeric threshold value"
    )
    direction: str = Field(
        default="crosses",
        description="'above', 'below', or 'crosses' (triggers on sign change)",
    )
    ticker: Optional[str] = Field(
        None, description="Company ticker scope (None = macro condition)"
    )
    topic: Optional[str] = Field(
        None, description="FRED topic scope, e.g. 'yields', 'inflation'"
    )
    description: str = Field(
        default="", description="Human-readable description of this condition"
    )


class AlertEvent(BaseModel):
    """A triggered alert event produced when an AlertCondition is met.

    Carries the current value, threshold, condition metadata, and a
    human-readable message so consumers can act without re-reading the
    original condition.
    """

    condition_id: str = Field(default="")
    type: str
    ticker: Optional[str] = None
    topic: Optional[str] = None
    current_value: float
    threshold: float
    direction: str
    triggered_at: str = Field(description="ISO-8601 UTC timestamp")
    message: str = Field(description="Human-readable alert message")


class CompanyKnowledgeProfile(BaseModel):
    """Curated business-intelligence profile for a specific publicly-traded company.

    Stored in the company knowledge database and injected into every
    specialist agent prompt to force company-specific, non-generic reasoning.
    Also used by the depth guard to verify that synthesised theses reference
    actual business-model terms rather than sector-level clichés.

    Design
    ------
    - ``business_model``: 1-2 sentence plain-English description.
    - ``primary_revenue_drivers``: ordered from largest to smallest (e.g.
      for Apple: iPhone, Services, Mac, …).
    - ``recurring_revenue_sources``: specific recurring/subscription lines.
    - ``rate_sensitivity_note``: a precise paragraph about how interest-rate
      moves hit *this* company's earnings and valuation — not a generic
      "growth stocks are rate-sensitive" statement.
    - ``inflation_pass_through``: pricing power and cost-pass-through ability.
    - ``recession_behavior``: what actually happens to revenue and margins
      when the economy contracts.
    - ``major_risks``: company-specific risk factors (not sector clichés).
    - ``valuation_style``: how the market values this company (P/E, DCF,
      EV/Sales, sum-of-parts, etc.) and why.
    - ``key_metrics``: the handful of data points analysts track most closely.
    - ``competitive_advantages``: specific moat sources (not "strong brand").
    - ``business_model_keywords``: used by the depth guard — if fewer than
      3 of these appear in the synthesised thesis, a depth warning is emitted.
    """

    ticker: str = Field(..., description="Ticker symbol (uppercase)")
    company_name: str = Field(..., description="Full canonical company name")

    # ── Business model ────────────────────────────────────────────────────────
    business_model: str = Field(
        ..., description="1-2 sentence description of how the company earns money"
    )
    primary_revenue_drivers: List[str] = Field(
        default_factory=list,
        description="Revenue segments ordered largest to smallest",
    )
    recurring_revenue_sources: List[str] = Field(
        default_factory=list,
        description="Specific subscription/contracted/recurring revenue lines",
    )

    # ── Macro sensitivity ─────────────────────────────────────────────────────
    rate_sensitivity_note: str = Field(
        default="",
        description=(
            "Company-specific paragraph on how interest-rate moves affect "
            "earnings, valuation multiple, and balance sheet"
        ),
    )
    inflation_pass_through: str = Field(
        default="",
        description="Pricing power and cost-pass-through ability for this company",
    )
    recession_behavior: str = Field(
        default="",
        description="What happens to revenue and margins when GDP contracts",
    )

    # ── Risk ─────────────────────────────────────────────────────────────────
    major_risks: List[str] = Field(
        default_factory=list,
        description="Company-specific risk factors (not generic sector risks)",
    )

    # ── Valuation ────────────────────────────────────────────────────────────
    valuation_style: str = Field(
        default="",
        description=(
            "How the market prices this company (P/E, DCF, EV/Sales, "
            "sum-of-parts) and the key assumptions that drive the multiple"
        ),
    )
    key_metrics: List[str] = Field(
        default_factory=list,
        description="KPIs analysts track most closely for this company",
    )

    # ── Quality / moat ───────────────────────────────────────────────────────
    competitive_advantages: List[str] = Field(
        default_factory=list,
        description="Specific moat sources — not generic phrases",
    )

    # ── Depth guard ──────────────────────────────────────────────────────────
    business_model_keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Company-specific nouns the depth guard requires in synthesised "
            "theses (e.g. 'iPhone', 'CUDA', 'Azure')"
        ),
    )


# =============================================================================
# WATCHLIST + THESIS MEMORY FOUNDATION
# =============================================================================


class ThesisSnapshot(BaseModel):
    """Point-in-time snapshot of an InvestmentThesis for comparison and history.

    Stored in the timeline layer keyed by ticker.  Every time a new thesis is
    generated for a watchlisted company, a snapshot is saved so the diff engine
    can compare consecutive versions and detect material changes.

    Hashes are deterministic fingerprints of the signal and risk lists — if
    either hash changes between snapshots the corresponding dimension has moved.
    """

    snapshot_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="UUID for this snapshot",
    )
    ticker: str = Field(..., description="Ticker symbol (uppercase)")
    company_name: str = Field(default="", description="Canonical company name")
    timestamp: str = Field(
        default="",
        description="ISO-8601 UTC timestamp of generation (auto-set when empty)",
    )

    # ── Core thesis fields ────────────────────────────────────────────────────
    one_sentence_thesis: str = Field(default="", description="Hero thesis sentence")
    direct_answer: str = Field(default="", description="Direct answer to user's question")
    bull_thesis: str = Field(default="", description="Bull case narrative")
    bear_thesis: str = Field(default="", description="Bear case narrative")
    conclusion: str = Field(default="", description="Investment conclusion paragraph")

    # ── Ranked signals ────────────────────────────────────────────────────────
    top_signals: List["Signal"] = Field(
        default_factory=list,
        description="Top bullish/neutral signals at snapshot time",
    )
    top_risks: List["Signal"] = Field(
        default_factory=list,
        description="Top risk signals at snapshot time",
    )
    key_drivers: List[str] = Field(
        default_factory=list,
        description="Ranked investment drivers at snapshot time",
    )
    key_risks_text: List[str] = Field(
        default_factory=list,
        description="Plain-text risk descriptions at snapshot time",
    )

    # ── Confidence ────────────────────────────────────────────────────────────
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_reasoning: str = Field(default="")

    # ── Temporal intelligence ─────────────────────────────────────────────────
    thesis_trend: str = Field(
        default="unclear",
        description="strengthening | weakening | stable | inflecting | unclear",
    )
    change_drivers: List[str] = Field(
        default_factory=list,
        description="Drivers of the thesis trend at snapshot time",
    )
    what_changed: List[str] = Field(
        default_factory=list,
        description="Changes from the prior snapshot",
    )

    # ── Fingerprints (deterministic) ─────────────────────────────────────────
    signal_hash: str = Field(
        default="",
        description="SHA-256 of sorted top_signals descriptions — changes when signal set moves",
    )
    risk_hash: str = Field(
        default="",
        description="SHA-256 of sorted top_risks descriptions — changes when risk set moves",
    )

    # ── Analytical frame ──────────────────────────────────────────────────────
    dominant_dimension: str = Field(default="", description="Dominant analytical dimension at snapshot time")
    core_debate: str = Field(default="", description="Central market debate at snapshot time")
    core_market_debate: str = Field(default="", description="Live positioning question at snapshot time")
    drift_state: str = Field(
        default="",
        description="strengthening | weakening | unchanged | bifurcating | repricing | transition | unclear",
    )


class WatchlistEntry(BaseModel):
    """A tracked ticker in the persistent watchlist.

    Stores lightweight metadata and pointers to the latest snapshot so the
    watchlist view can render a full Bloomberg-lite row without loading the
    entire snapshot history.
    """

    ticker: str = Field(..., description="Ticker symbol (uppercase)")
    company_name: str = Field(default="", description="Canonical company name")
    added_at: str = Field(
        default="",
        description="ISO-8601 UTC timestamp when ticker was added to watchlist",
    )
    last_updated: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp of the most recent snapshot save",
    )
    snapshot_count: int = Field(
        default=0,
        description="Total number of snapshots stored for this ticker",
    )
    has_material_change: bool = Field(
        default=False,
        description="True when the most recent diff flagged a material change",
    )

    # ── Latest snapshot summary (denormalised for fast rendering) ─────────────
    latest_thesis_trend: str = Field(
        default="unclear",
        description="Thesis trend from the most recent diff",
    )
    latest_confidence: float = Field(
        default=0.0,
        description="Confidence score from the most recent snapshot",
    )
    latest_one_sentence: str = Field(
        default="",
        description="Hero thesis from the most recent snapshot",
    )
    dominant_signal: str = Field(
        default="",
        description="Label of the #1 ranked signal in the most recent snapshot",
    )
    dominant_risk: str = Field(
        default="",
        description="Label of the #1 ranked risk in the most recent snapshot",
    )
    notes: str = Field(default="", description="Optional analyst notes")

    # ── Thesis intelligence (denormalised for fast rendering) ────────────────
    what_changed_summary: str = Field(
        default="",
        description="PM-language summary of what changed since the prior thesis",
    )
    drift_state: str = Field(
        default="",
        description="strengthening | weakening | unchanged | bifurcating | repricing | transition | unclear",
    )
    dominant_dimension: str = Field(
        default="",
        description="Dominant analytical frame from the most recent snapshot",
    )
    core_debate: str = Field(
        default="",
        description="Central market debate from the most recent snapshot",
    )

    # ── Alert intelligence (Phase I) ─────────────────────────────────────────
    recent_alert_count: int = Field(
        default=0,
        description="Number of alerts in the last 7 days",
    )
    materiality_level: str = Field(
        default="",
        description="high | medium | low | none — from most recent MaterialChangeEvent",
    )
    thesis_stability: str = Field(
        default="stable",
        description="stable | drifting | shifting | breaking — derived from recent diffs",
    )
    latest_change_narrative: str = Field(
        default="",
        description="PM-language 1-sentence description of latest change (not a percentage)",
    )
    debate_focus: str = Field(
        default="",
        description="valuation | product_competition | regulatory | margin | macro — current debate type",
    )
    alert_priority: str = Field(
        default="",
        description="critical | high | medium | ignore — highest priority of recent alerts",
    )


class ThesisDiff(BaseModel):
    """Structured diff between two consecutive ThesisSnapshot objects.

    Produced by ``thesis_memory_service.compare_thesis_snapshots()``.
    All fields default to safe empties so callers can safely access any
    attribute even when no meaningful change was detected.
    """

    # ── Change narrative ──────────────────────────────────────────────────────
    what_changed: List[str] = Field(
        default_factory=list,
        description="Plain-English descriptions of what moved between snapshots",
    )
    thesis_trend: str = Field(
        default="unclear",
        description=(
            "strengthening | weakening | stable | inflecting | unclear — "
            "direction of the thesis relative to the prior snapshot"
        ),
    )
    change_drivers: List[str] = Field(
        default_factory=list,
        description="Specific factors driving the detected trend",
    )

    # ── Material shift ────────────────────────────────────────────────────────
    material_shift_detected: bool = Field(
        default=False,
        description="True when the diff meets at least one material-change threshold",
    )
    severity: str = Field(
        default="low",
        description="high | medium | low — overall severity of the detected changes",
    )

    # ── Confidence delta ──────────────────────────────────────────────────────
    confidence_change: float = Field(
        default=0.0,
        description="Current confidence minus previous confidence (positive = stronger)",
    )

    # ── Signal-level changes ──────────────────────────────────────────────────
    new_risks: List[str] = Field(
        default_factory=list,
        description="Risk descriptions present in current but not in previous snapshot",
    )
    removed_risks: List[str] = Field(
        default_factory=list,
        description="Risk descriptions present in previous but not in current snapshot",
    )
    strengthening_signals: List[str] = Field(
        default_factory=list,
        description="Signals that gained rank or appeared in current snapshot",
    )
    weakening_signals: List[str] = Field(
        default_factory=list,
        description="Signals that lost rank or disappeared in current snapshot",
    )
    top_signal_replaced: bool = Field(
        default=False,
        description="True when the #1 ranked signal changed between snapshots",
    )
    trend_flipped: bool = Field(
        default=False,
        description="True when thesis_trend reversed vs the previous snapshot's trend",
    )
    drift_state: str = Field(
        default="unclear",
        description="Extended thesis drift classification: strengthening | weakening | unchanged | bifurcating | repricing | transition | unclear",
    )

    # ── Core debate tracking (Phase G — Market Debate Hierarchy) ──────────────
    core_debate_shifted: bool = Field(
        default=False,
        description=(
            "True when the core_market_debate question materially changed between snapshots. "
            "A debate shift means the fulcrum variable changed, not just the risk weighting."
        ),
    )
    prev_core_debate: str = Field(
        default="",
        description="core_debate from the previous snapshot (populated when core_debate_shifted is True)",
    )
    curr_core_debate: str = Field(
        default="",
        description="core_debate from the current snapshot (populated when core_debate_shifted is True)",
    )

    # ── Snapshot references ───────────────────────────────────────────────────
    previous_snapshot_id: Optional[str] = Field(default=None)
    current_snapshot_id: Optional[str] = Field(default=None)


class MaterialChangeEvent(BaseModel):
    """A detected material change in an investment thesis.

    Emitted by ``thesis_memory_service.detect_material_change()`` when a
    ThesisDiff crosses at least one severity threshold.  Stored in the
    timeline layer as entry_type="material_change".
    """

    event_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="UUID for this event",
    )
    ticker: str = Field(..., description="Ticker symbol")
    severity: str = Field(
        ...,
        description="high | medium | low",
    )
    summary: str = Field(..., description="One-sentence description of the change")
    drivers: List[str] = Field(
        default_factory=list,
        description="Specific drivers identified in the diff",
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of detection",
    )
    change_type: str = Field(
        ...,
        description=(
            "thesis_weakened | thesis_strengthened | new_structural_risk | "
            "confidence_collapse | trend_flip | top_signal_replaced | stable"
        ),
    )

    # ── Snapshot references ───────────────────────────────────────────────────
    previous_snapshot_id: Optional[str] = Field(default=None)
    current_snapshot_id: Optional[str] = Field(default=None)

    # ── Quantitative context ──────────────────────────────────────────────────
    confidence_change: float = Field(
        default=0.0,
        description="Confidence delta that triggered (or contributed to) this event",
    )
    thesis_trend_changed: bool = Field(
        default=False,
        description="True when the thesis_trend direction changed in this diff",
    )
    materiality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "0.0–1.0 composite materiality score. "
            "≥0.7 = high structural change, 0.4–0.7 = medium, <0.4 = cosmetic/wording. "
            "Drives alert suppression for noise-level changes."
        ),
    )
    change_category: str = Field(
        default="",
        description=(
            "Human-readable change category: "
            "'market_repriced' | 'thesis_broke' | 'thesis_strengthened' | "
            "'new_risk_emerged' | 'cosmetic' — PM-facing classification."
        ),
    )


class TimelineEvent(BaseModel):
    """A structured timeline event for thesis history visualization."""

    event_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    ticker: str
    event_type: str  # thesis_shift | market_repriced | earnings_event | new_risk | regime_change | narrative_transition | catalyst_confirmed | catalyst_failed
    title: str       # Short display title (≤60 chars)
    body: str        # 1-2 sentence description in PM language
    severity: str = Field(default="medium")  # critical | high | medium | low
    timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)  # extra context
    # optional references
    source_material_change_id: Optional[str] = Field(default=None)
    source_snapshot_id: Optional[str] = Field(default=None)


class AlertPriority(BaseModel):
    """Alert priority classification."""

    alert_id: str
    ticker: str
    priority: str   # critical | high | medium | ignore
    priority_score: float  # 0.0-1.0 composite
    reason: str     # Why this priority level


class AlertRule(BaseModel):
    """A declarative alert rule evaluated against a ThesisDiff.

    Rules are pure-function conditions: given a diff, return True if the
    condition is met.  No production infrastructure is required — rules are
    evaluated in-process and the caller decides what to do with the result.

    condition_key maps to a registered evaluator in
    ``thesis_memory_service.ALERT_RULE_EVALUATORS``.
    """

    rule_id: str = Field(..., description="Unique rule identifier")
    name: str = Field(..., description="Human-readable rule name")
    description: str = Field(
        default="", description="What this rule watches for"
    )
    condition_key: str = Field(
        ...,
        description=(
            "Key into ALERT_RULE_EVALUATORS: "
            "thesis_weakens | confidence_collapses | new_structural_risk | "
            "trend_flip | top_signal_replaced | thesis_strengthens"
        ),
    )
    threshold: Optional[float] = Field(
        default=None,
        description="Optional numeric threshold (e.g. 0.10 for 10pp confidence drop)",
    )
    severity: str = Field(
        default="medium",
        description="high | medium | low — severity of alerts fired by this rule",
    )
