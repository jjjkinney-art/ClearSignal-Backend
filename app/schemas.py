"""
Pydantic schemas defining request, context, and response models for the AI analyst backend.

This module introduces strongly typed models to replace the previous blob‑like
string fields.  Lists are used for multi‑item fields such as bull/bear cases,
risks, and catalysts.  Nested models capture the structure of each
specialist agent's output as well as the synthesizer's final summary.
"""

from __future__ import annotations

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
