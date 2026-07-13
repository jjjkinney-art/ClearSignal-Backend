"""V0 — Institutional Benchmark Dataset

Canonical ground truth for ClearSignal validation V1–V10.
Each entry encodes what an experienced analyst would consider defensible
for that company.  These are not point estimates — they are ranges and
constraints that any credible investment professional would agree with.

This file is DATA, not code.  It should never import production modules
or be modified by automated processes.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Archetype(str, Enum):
    COMPOUNDER     = "compounder"        # durable franchise, pricing power, recurring revenue
    QUALITY_GROWTH = "quality_growth"     # high-quality business with above-average growth
    QUALITY_CYCLIC = "quality_cyclical"   # good business, cyclical earnings
    STABLE_YIELD   = "stable_yield"       # regulated/utility/REIT, predictable cash flows
    CYCLICAL       = "cyclical"           # commodity or late-cycle industrial
    TURNAROUND     = "turnaround"         # distressed or transitioning business
    SPECULATIVE    = "speculative"        # unproven model, high narrative dependence


class StanceRange(str, Enum):
    ACCUMULATE_PLUS = "accumulate+"       # Aggressive Buy / Buy / Accumulate
    ACCUMULATE_HOLD = "accumulate_hold"   # Accumulate / Hold
    HOLD            = "hold"              # Hold (±Tactical)
    HOLD_AVOID      = "hold_avoid"        # Hold / Avoid
    AVOID_PLUS      = "avoid+"            # Avoid / Sell


class AnalogFamily(str, Enum):
    MULTIPLE_COMPRESSION     = "multiple_compression"
    INVENTORY_CORRECTION     = "inventory_channel_correction"
    PATENT_CLIFF             = "patent_cliff"
    COMPETITIVE_DISPLACEMENT = "competitive_displacement"
    INFRASTRUCTURE_OVERBUILD = "infrastructure_overbuild"
    PLATFORM_TRANSITION      = "platform_transition"
    RATE_SHOCK               = "rate_shock"
    CREDIT_CYCLE             = "credit_cycle_loss"
    CREDIT_EVENT             = "credit_event"
    COMMODITY_SHOCK          = "commodity_shock"
    HYPERGROWTH_DECEL        = "hypergrowth_deceleration"
    REGULATORY_BREAK         = "regulatory_break"
    DEMAND_AIR_POCKET        = "demand_air_pocket"
    NETWORK_FEE_COMPRESSION  = "network_fee_compression"
    MEMBERSHIP_ELASTICITY    = "membership_elasticity_test"
    FRANCHISE_CRISIS         = "franchise_credibility_crisis"
    EXPORT_CONTROL           = "export_control_restriction"
    GOVERNMENT_BUDGET_CUT    = "government_budget_cut"


# ---------------------------------------------------------------------------
# Benchmark entry
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkEntry:
    ticker: str
    company: str
    archetype: Archetype

    # Durability
    durability_range: Tuple[float, float]   # (min, max) acceptable

    # Structured fields (ground truth — what is correct, not what system has)
    moat_types: List[str]
    revenue_model: str
    switching_cost: str                     # none/low/moderate/high/very_high
    cyclicality: str                        # non_cyclical/mild/moderate/highly_cyclical
    capital_intensity: str                  # asset_light/moderate/capital_intensive
    narrative_dependence: str               # none/low/moderate/high/dominant
    binary_risk: str                        # none/low/moderate/high

    # Conviction & stance
    conviction_range: Tuple[int, int]       # (min, max) acceptable score
    expected_stances: List[str]             # acceptable stances

    # Peer group
    peer_group: List[str]                   # tickers of comparable companies

    # Analog families
    appropriate_analogs: List[AnalogFamily]
    inappropriate_analogs: List[AnalogFamily]

    # Thesis
    primary_thesis: str                     # one-sentence core thesis
    thesis_breakers: List[str]              # specific events that would break the thesis

    # Ordering constraints: this company should score ABOVE these tickers
    must_rank_above: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The benchmark
# ---------------------------------------------------------------------------

BENCHMARK: Dict[str, BenchmarkEntry] = {}


def _b(entry: BenchmarkEntry) -> None:
    BENCHMARK[entry.ticker] = entry


# ═══════════════════════════════════════════════════════════════════════════
# COMPOUNDERS — durable franchises with pricing power and recurring revenue
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="V", company="Visa",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.82, 0.90),
    moat_types=["network_effect", "brand", "scale_economy"],
    revenue_model="transaction_toll",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(62, 78),
    expected_stances=["Accumulate", "Buy"],
    peer_group=["MA", "AXP"],
    appropriate_analogs=[AnalogFamily.NETWORK_FEE_COMPRESSION, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="Pure-play payment toll on global consumer spending with 85%+ operating margins and zero credit risk.",
    thesis_breakers=["Real-time payment rails (UPI/FedNow/PIX) bypass card networks at scale", "Antitrust action forcing interchange fee caps globally"],
    must_rank_above=["AXP", "JPM", "GS", "COIN"],
))

_b(BenchmarkEntry(
    ticker="MA", company="Mastercard",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.82, 0.90),
    moat_types=["network_effect", "brand", "scale_economy"],
    revenue_model="transaction_toll",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(62, 78),
    expected_stances=["Accumulate", "Buy"],
    peer_group=["V", "AXP"],
    appropriate_analogs=[AnalogFamily.NETWORK_FEE_COMPRESSION, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Payment network duopoly with Visa; higher cross-border mix provides superior secular growth.",
    thesis_breakers=["India UPI-style real-time payments adopted in EU/US", "Durbin-style interchange regulation on credit cards"],
    must_rank_above=["GS", "BAC", "COIN"],
))

_b(BenchmarkEntry(
    ticker="MSFT", company="Microsoft",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.75, 0.82),
    moat_types=["switching_cost", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost="high", cyclicality="non_cyclical",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 75),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["GOOGL", "AMZN", "ORCL"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.PLATFORM_TRANSITION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Enterprise platform monopoly (365+Azure+GitHub) with AI Copilot upsell driving the next revenue expansion cycle.",
    thesis_breakers=["Azure growth decelerates below 20% for 2 consecutive quarters", "Copilot monetization fails to move ARPU materially"],
    must_rank_above=["INTC", "PLTR", "COIN", "TSLA"],
))

_b(BenchmarkEntry(
    ticker="SPGI", company="S&P Global",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.75, 0.82),
    moat_types=["regulatory", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(60, 75),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["MCO", "BLK"],
    appropriate_analogs=[AnalogFamily.REGULATORY_BREAK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="Ratings oligopoly (with MCO) + S&P index franchise + IHS Markit data creates a triple-moat data compound.",
    thesis_breakers=["SEC eliminates NRSRO designation requirement", "Major ratings miss triggers regulatory overhaul"],
    must_rank_above=["GS", "BAC", "SCHW"],
))

_b(BenchmarkEntry(
    ticker="MCO", company="Moody's",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.75, 0.82),
    moat_types=["regulatory", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(58, 73),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["SPGI", "BLK"],
    appropriate_analogs=[AnalogFamily.REGULATORY_BREAK, AnalogFamily.CREDIT_CYCLE],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    primary_thesis="Ratings duopoly with SPGI; mandatory-use product with 50%+ margins and issuance-cycle tailwind.",
    thesis_breakers=["Blockchain-based credit scoring displaces ratings agencies", "Major ratings failure triggers loss of NRSRO status"],
    must_rank_above=["GS", "BAC", "COIN"],
))

_b(BenchmarkEntry(
    ticker="ADP", company="Automatic Data Processing",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.80, 0.88),
    moat_types=["switching_cost", "scale_economy", "regulatory"],
    revenue_model="subscription",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(60, 75),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["INTU", "SPGI"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Payroll monopoly with regulatory-mandated switching friction; client float generates NII in rate-up environments.",
    thesis_breakers=["Gusto/Rippling capture enterprise payroll at scale", "Zero-rate environment eliminates float income"],
    must_rank_above=["SCHW", "COIN", "PLTR"],
))

_b(BenchmarkEntry(
    ticker="COST", company="Costco",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.65, 0.73),
    moat_types=["brand", "switching_cost", "scale_economy"],
    revenue_model="membership",
    switching_cost="moderate", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 70),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["WMT", "TGT"],
    appropriate_analogs=[AnalogFamily.MEMBERSHIP_ELASTICITY, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Membership model (92%+ renewal) creates predictable high-margin revenue; EDLP pricing power from buyer scale.",
    thesis_breakers=["Renewal rate drops below 88%", "Amazon Prime same-day delivery erodes Costco's convenience advantage"],
    must_rank_above=["TGT", "WMT", "NKE"],
))

_b(BenchmarkEntry(
    ticker="INTU", company="Intuit",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.73, 0.80),
    moat_types=["brand", "switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost="high", cyclicality="non_cyclical",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 70),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["ADP", "CRM"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="TurboTax + QuickBooks + Credit Karma = tax/SMB/fintech franchise with regulatory moat (tax code complexity).",
    thesis_breakers=["IRS launches free filing system that gains mass adoption", "AI-powered competitors automate tax prep at zero cost"],
    must_rank_above=["COIN", "RBLX", "PLTR"],
))

_b(BenchmarkEntry(
    ticker="KO", company="Coca-Cola",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.67, 0.75),
    moat_types=["brand", "scale_economy", "switching_cost"],
    revenue_model="licensing",
    switching_cost="moderate", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(50, 68),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["PG", "MDLZ", "SBUX"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="Global beverage brand franchise with asset-light bottler model; pricing power through brand strength.",
    thesis_breakers=["Sugar regulation materially impairs volumes in multiple markets", "GLP-1 adoption reduces caloric beverage consumption structurally"],
    must_rank_above=["NKE", "SBUX", "DIS"],
))

_b(BenchmarkEntry(
    ticker="MCD", company="McDonald's",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.68, 0.75),
    moat_types=["brand", "scale_economy", "switching_cost"],
    revenue_model="licensing",
    switching_cost="high", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 70),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["SBUX", "KO"],
    appropriate_analogs=[AnalogFamily.FRANCHISE_CRISIS, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Global franchise royalty model; 95% franchised = high-margin recurring rent + royalties with real estate optionality.",
    thesis_breakers=["Franchisee profitability crisis triggers mass closures", "Value perception permanently lost to fast-casual competitors"],
    must_rank_above=["SBUX", "CAVA", "NKE"],
))

# ═══════════════════════════════════════════════════════════════════════════
# QUALITY GROWTH — high-quality businesses with above-average growth
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="AAPL", company="Apple",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.60, 0.68),
    moat_types=["brand", "switching_cost", "scale_economy"],
    revenue_model="product_sale",
    switching_cost="high", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(50, 70),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["MSFT", "GOOGL", "AMZN"],
    appropriate_analogs=[AnalogFamily.DEMAND_AIR_POCKET, AnalogFamily.REGULATORY_BREAK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="2B+ device installed base monetized through Services (72% margin); Apple Intelligence as upgrade catalyst.",
    thesis_breakers=["DOJ forces Google TAC renegotiation ($18-20B/yr at risk)", "EU DMA enforcement reduces App Store take rate below 20%", "China share loss to Huawei accelerates beyond 5% annually"],
    must_rank_above=["INTC", "PLTR", "TSLA"],
))

_b(BenchmarkEntry(
    ticker="GOOGL", company="Alphabet",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.65, 0.72),
    moat_types=["network_effect", "data_advantage", "scale_economy"],
    revenue_model="advertising",
    switching_cost="high", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 72),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["META", "MSFT", "AMZN"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.REGULATORY_BREAK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Search monopoly (90%+ share) + YouTube + Cloud; AI search transition is both risk and opportunity.",
    thesis_breakers=["AI chatbots capture >20% of commercial search queries", "DOJ antitrust forces structural separation of Search/Chrome/Android"],
    must_rank_above=["PLTR", "COIN", "RBLX"],
))

_b(BenchmarkEntry(
    ticker="AMZN", company="Amazon",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.68, 0.76),
    moat_types=["network_effect", "scale_economy", "data_advantage"],
    revenue_model="mixed",
    switching_cost="high", cyclicality="mild",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(48, 68),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["GOOGL", "MSFT", "WMT"],
    appropriate_analogs=[AnalogFamily.INFRASTRUCTURE_OVERBUILD, AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="AWS cloud monopoly (32% share) funds retail flywheel; advertising (high margin) is the underappreciated third leg.",
    thesis_breakers=["AWS growth decelerates below 15% sustained", "Retail margins permanently compressed by competition"],
    must_rank_above=["SHOP", "COIN", "RBLX"],
))

_b(BenchmarkEntry(
    ticker="META", company="Meta Platforms",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.58, 0.66),
    moat_types=["network_effect", "data_advantage", "scale_economy"],
    revenue_model="advertising",
    switching_cost="moderate", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="low", binary_risk="none",
    conviction_range=(52, 72),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["GOOGL", "SNAP"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.REGULATORY_BREAK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="3.2B+ DAP across family of apps monetized via best-in-class ad targeting; Reels closing the TikTok engagement gap.",
    thesis_breakers=["Apple ATT-style privacy change on Android eliminates ad targeting", "TikTok captures majority of 18-34 engagement permanently"],
    must_rank_above=["SNAP", "PLTR", "RBLX"],
))

_b(BenchmarkEntry(
    ticker="AXP", company="American Express",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.78, 0.86),
    moat_types=["network_effect", "brand", "data_advantage"],
    revenue_model="transaction_toll",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(58, 74),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["V", "MA"],
    appropriate_analogs=[AnalogFamily.CREDIT_CYCLE, AnalogFamily.NETWORK_FEE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Premium closed-loop payment network; higher spend-per-card than V/MA but takes credit risk.",
    thesis_breakers=["Credit losses spike above 4% in a recession", "Merchant acceptance gap vs V/MA widens rather than narrows"],
    must_rank_above=["GS", "SCHW", "COIN"],
))

_b(BenchmarkEntry(
    ticker="TMO", company="Thermo Fisher Scientific",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.68, 0.76),
    moat_types=["switching_cost", "scale_economy", "patent"],
    revenue_model="mixed",
    switching_cost="very_high", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 70),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["ABT", "MDT"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    primary_thesis="Life sciences instrumentation monopoly; labs are standardized on TMO equipment with very high switching costs.",
    thesis_breakers=["Pharma R&D spending declines structurally", "China lab equipment market closes to Western suppliers"],
    must_rank_above=["PFE", "MRK", "NKE"],
))

_b(BenchmarkEntry(
    ticker="UNH", company="UnitedHealth Group",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.70, 0.77),
    moat_types=["scale_economy", "data_advantage", "regulatory"],
    revenue_model="mixed",
    switching_cost="high", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="low",
    conviction_range=(55, 72),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["ABBV", "JNJ"],
    appropriate_analogs=[AnalogFamily.REGULATORY_BREAK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="Largest US health insurer + Optum data/analytics/PBM; vertical integration creates cost advantages competitors can't replicate.",
    thesis_breakers=["Medicare-for-All or single-payer legislation advances", "Optum/Change Healthcare DOJ action forces divestiture"],
    must_rank_above=["PFE", "MRK", "GS"],
))

_b(BenchmarkEntry(
    ticker="BLK", company="BlackRock",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.64, 0.72),
    moat_types=["scale_economy", "brand", "data_advantage"],
    revenue_model="licensing",
    switching_cost="high", cyclicality="moderate",
    capital_intensity="asset_light", narrative_dependence="none", binary_risk="none",
    conviction_range=(50, 68),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["SPGI", "KKR", "BX"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="$10T+ AUM franchise anchored by iShares ETF dominance; Aladdin risk platform creates enterprise switching costs.",
    thesis_breakers=["Passive-to-active rotation sustained over multiple years", "Fee compression accelerates below 5bps on core ETFs"],
    must_rank_above=["COIN", "SCHW"],
))

_b(BenchmarkEntry(
    ticker="CRM", company="Salesforce",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.64, 0.72),
    moat_types=["switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="low", binary_risk="none",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["MSFT", "ORCL", "INTU"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.PLATFORM_TRANSITION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Enterprise CRM monopoly with deep workflow integration; Agentforce AI adds upsell vector.",
    thesis_breakers=["Microsoft Dynamics + Copilot captures CRM share at enterprise scale", "Agentforce adoption fails to materialize"],
    must_rank_above=["PLTR", "COIN", "RBLX"],
))

# ═══════════════════════════════════════════════════════════════════════════
# QUALITY CYCLICAL — good business, cyclical earnings
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="NVDA", company="NVIDIA",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.38, 0.48),
    moat_types=["data_advantage", "scale_economy"],
    revenue_model="product_sale",
    switching_cost="high", cyclicality="highly_cyclical",
    capital_intensity="moderate", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(28, 55),
    expected_stances=["Hold", "Avoid", "Accumulate"],
    peer_group=["AMD", "AVGO", "TSM"],
    appropriate_analogs=[AnalogFamily.INVENTORY_CORRECTION, AnalogFamily.INFRASTRUCTURE_OVERBUILD, AnalogFamily.EXPORT_CONTROL],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="AI accelerator monopoly (80%+ GPU share); CUDA ecosystem creates deep developer switching costs.",
    thesis_breakers=["Hyperscaler custom ASICs (TPU, Trainium, Inferentia) capture >30% of AI compute", "Export controls expand to block China revenue entirely"],
    must_rank_above=["INTC", "TSLA"],
))

_b(BenchmarkEntry(
    ticker="TSM", company="TSMC",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.63, 0.72),
    moat_types=["natural_monopoly", "scale_economy", "patent"],
    revenue_model="licensing",
    switching_cost="very_high", cyclicality="moderate",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="low",
    conviction_range=(58, 75),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["ASML", "AVGO"],
    appropriate_analogs=[AnalogFamily.DEMAND_AIR_POCKET, AnalogFamily.EXPORT_CONTROL, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Advanced semiconductor foundry monopoly (90%+ share at ≤5nm); every AI chip goes through TSMC.",
    thesis_breakers=["China-Taiwan conflict disrupts production", "Intel foundry achieves process parity at 2nm"],
    must_rank_above=["INTC", "AMD", "MU"],
))

_b(BenchmarkEntry(
    ticker="AVGO", company="Broadcom",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.60, 0.68),
    moat_types=["switching_cost", "scale_economy", "patent"],
    revenue_model="mixed",
    switching_cost="very_high", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(55, 72),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["QCOM", "TXN", "TSM"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Semiconductor + infrastructure software conglomerate; custom AI ASIC business (Google, Meta) is the growth vector.",
    thesis_breakers=["VMware integration destroys customer relationships", "Custom ASIC customers insource chip design"],
    must_rank_above=["INTC", "MU", "AMD"],
))

_b(BenchmarkEntry(
    ticker="ASML", company="ASML",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.58, 0.65),
    moat_types=["natural_monopoly", "patent"],
    revenue_model="licensing",
    switching_cost="very_high", cyclicality="moderate",
    capital_intensity="capital_intensive", narrative_dependence="low", binary_risk="none",
    conviction_range=(50, 68),
    expected_stances=["Accumulate", "Hold"],
    peer_group=["TSM", "AMAT", "LRCX", "KLAC"],
    appropriate_analogs=[AnalogFamily.DEMAND_AIR_POCKET, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="EUV lithography monopoly; every advanced chip requires ASML machines, with 2-year+ order backlogs.",
    thesis_breakers=["Alternative lithography technology emerges (e.g., nanoimprint at scale)", "WFE spending enters multi-year downcycle"],
    must_rank_above=["INTC", "MU"],
))

_b(BenchmarkEntry(
    ticker="JPM", company="JPMorgan Chase",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.60, 0.68),
    moat_types=["scale_economy", "regulatory", "brand"],
    revenue_model="mixed",
    switching_cost="moderate", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(50, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["BAC", "WFC", "GS"],
    appropriate_analogs=[AnalogFamily.CREDIT_CYCLE, AnalogFamily.CREDIT_EVENT, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Best-in-class universal bank; #1 in IB, trading, commercial banking, and consumer; Dimon premium.",
    thesis_breakers=["Credit losses spike above 3% in a severe recession", "Fintech disintermediation of deposits accelerates"],
    must_rank_above=["GS", "BAC", "WFC", "SCHW"],
))

_b(BenchmarkEntry(
    ticker="BRK.B", company="Berkshire Hathaway",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.63, 0.72),
    moat_types=["brand", "scale_economy", "regulatory"],
    revenue_model="mixed",
    switching_cost="moderate", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(52, 68),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["JPM"],
    appropriate_analogs=[AnalogFamily.CREDIT_CYCLE, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    primary_thesis="Diversified conglomerate (insurance float + operating businesses + $300B+ equity portfolio); succession risk post-Buffett.",
    thesis_breakers=["Buffett succession triggers conglomerate discount", "Insurance underwriting cycle turns sharply negative"],
    must_rank_above=["GS", "COIN", "TSLA"],
))

_b(BenchmarkEntry(
    ticker="HD", company="Home Depot",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.45, 0.55),
    moat_types=["scale_economy", "brand"],
    revenue_model="product_sale",
    switching_cost="moderate", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(42, 60),
    expected_stances=["Hold"],
    peer_group=["LOW", "TGT"],
    appropriate_analogs=[AnalogFamily.RATE_SHOCK, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Pro contractor + DIY retailer; housing turnover is the swing factor; scale advantage vs LOW.",
    thesis_breakers=["Housing turnover stays depressed for 3+ years due to rate lock-in", "Amazon captures significant pro-contractor share"],
    must_rank_above=["LOW", "TGT", "CAVA"],
))

# ═══════════════════════════════════════════════════════════════════════════
# STABLE YIELD — regulated, utility, REIT
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="NEE", company="NextEra Energy",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.66, 0.74),
    moat_types=["regulatory", "scale_economy"],
    revenue_model="subscription",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="low",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["DUK", "SO", "AEP"],
    appropriate_analogs=[AnalogFamily.RATE_SHOCK, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.INVENTORY_CORRECTION],
    primary_thesis="Largest US utility + largest renewable energy developer; regulated FPL provides stable base.",
    thesis_breakers=["Renewable energy subsidies eliminated", "Hurricane causes catastrophic uninsured damage to FPL grid"],
    must_rank_above=["XOM", "CVX", "OXY"],
))

_b(BenchmarkEntry(
    ticker="AWK", company="American Water Works",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.76, 0.84),
    moat_types=["regulatory", "natural_monopoly"],
    revenue_model="subscription",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(48, 63),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["NEE", "ED", "DUK"],
    appropriate_analogs=[AnalogFamily.RATE_SHOCK, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    primary_thesis="Water utility natural monopoly; zero competition, rate-regulated, essential service with infrastructure investment tailwind.",
    thesis_breakers=["Rate case outcomes consistently below cost of capital", "Municipal takeover movement gains political traction"],
    must_rank_above=["XOM", "CVX", "MU"],
))

_b(BenchmarkEntry(
    ticker="AMT", company="American Tower",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.71, 0.79),
    moat_types=["regulatory", "switching_cost"],
    revenue_model="subscription",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(48, 63),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["EQIX", "PLD"],
    appropriate_analogs=[AnalogFamily.RATE_SHOCK, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Global cell tower REIT with 10-year escalator leases; 5G densification drives co-location revenue growth.",
    thesis_breakers=["Satellite-based connectivity (Starlink) reduces tower demand structurally", "India tower pricing stays depressed long-term"],
    must_rank_above=["SPG", "XOM", "OXY"],
))

_b(BenchmarkEntry(
    ticker="EQIX", company="Equinix",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.66, 0.74),
    moat_types=["switching_cost", "scale_economy"],
    revenue_model="subscription",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["AMT", "PLD"],
    appropriate_analogs=[AnalogFamily.RATE_SHOCK, AnalogFamily.INFRASTRUCTURE_OVERBUILD],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Data center colocation REIT; network-effect from interconnection density makes moving prohibitively expensive.",
    thesis_breakers=["Hyperscaler self-build trend eliminates colocation demand", "Power cost inflation outpaces rate escalators"],
    must_rank_above=["SPG", "XOM"],
))

# ═══════════════════════════════════════════════════════════════════════════
# CYCLICAL — commodity exposure, late-cycle industrial
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="XOM", company="ExxonMobil",
    archetype=Archetype.CYCLICAL,
    durability_range=(0.30, 0.40),
    moat_types=["scale_economy"],
    revenue_model="product_sale",
    switching_cost="none", cyclicality="highly_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(28, 50),
    expected_stances=["Hold", "Avoid"],
    peer_group=["CVX", "COP", "OXY"],
    appropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Largest US integrated oil major; revenue swings 30-50% with oil prices; scale provides cost advantage but no pricing power.",
    thesis_breakers=["Oil below $50/bbl sustained for 2+ years", "EV adoption accelerates demand destruction beyond IEA peak-oil timeline"],
    must_rank_above=["OXY"],
))

_b(BenchmarkEntry(
    ticker="CAT", company="Caterpillar",
    archetype=Archetype.CYCLICAL,
    durability_range=(0.38, 0.48),
    moat_types=["scale_economy", "brand"],
    revenue_model="product_sale",
    switching_cost="moderate", cyclicality="highly_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(32, 52),
    expected_stances=["Hold", "Avoid"],
    peer_group=["DE", "HON", "ETN"],
    appropriate_analogs=[AnalogFamily.DEMAND_AIR_POCKET, AnalogFamily.COMMODITY_SHOCK, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Industrial bellwether; construction/mining equipment with global dealer network and aftermarket revenue.",
    thesis_breakers=["Global construction downturn sustained 2+ years", "China infrastructure spending collapses"],
    must_rank_above=["MU", "CAVA"],
))

_b(BenchmarkEntry(
    ticker="GS", company="Goldman Sachs",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.45, 0.53),
    moat_types=["brand", "scale_economy"],
    revenue_model="mixed",
    switching_cost="moderate", cyclicality="highly_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(38, 55),
    expected_stances=["Hold", "Avoid"],
    peer_group=["JPM", "BAC", "MS"],
    appropriate_analogs=[AnalogFamily.CREDIT_CYCLE, AnalogFamily.CREDIT_EVENT, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Elite IB/trading franchise but highly cyclical revenue (IB fees can swing 50%); asset management provides some stability.",
    thesis_breakers=["Prolonged IB fee drought (>8 quarters)", "Trading revenue collapses in low-volatility environment"],
    must_rank_above=["COIN"],
))

_b(BenchmarkEntry(
    ticker="MU", company="Micron Technology",
    archetype=Archetype.CYCLICAL,
    durability_range=(0.20, 0.30),
    moat_types=["scale_economy"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="highly_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(22, 42),
    expected_stances=["Avoid", "Hold"],
    peer_group=["INTC", "TXN"],
    appropriate_analogs=[AnalogFamily.INVENTORY_CORRECTION, AnalogFamily.COMMODITY_SHOCK, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Memory semiconductor oligopoly (with Samsung, SK Hynix); revenue can swing 50%+ in DRAM/NAND cycles.",
    thesis_breakers=["DRAM/NAND oversupply drives ASP below cash cost", "Samsung floods market to gain share"],
    must_rank_above=["CAVA"],
))

# ═══════════════════════════════════════════════════════════════════════════
# SPECULATIVE — unproven model, high narrative dependence
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="TSLA", company="Tesla",
    archetype=Archetype.SPECULATIVE,
    durability_range=(0.14, 0.22),
    moat_types=["brand"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="moderate",
    capital_intensity="capital_intensive", narrative_dependence="dominant", binary_risk="moderate",
    conviction_range=(18, 35),
    expected_stances=["Avoid", "Sell"],
    peer_group=["NIO", "RIVN"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.FRANCHISE_CRISIS, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="EV manufacturer trading at tech multiples; FSD/robotaxi optionality drives valuation far above auto peers.",
    thesis_breakers=["FSD Level 4 approval delayed beyond 2027", "BYD captures majority of global EV market outside US", "Brand damage from CEO political activity reduces demand"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="PLTR", company="Palantir",
    archetype=Archetype.SPECULATIVE,
    durability_range=(0.32, 0.40),
    moat_types=["data_advantage"],
    revenue_model="project_contract",
    switching_cost="moderate", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="high", binary_risk="low",
    conviction_range=(30, 50),
    expected_stances=["Hold", "Avoid"],
    peer_group=["SNOW", "CRM"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.HYPERGROWTH_DECEL],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Government AI/data platform with expanding commercial business; AIP adoption is the bull case.",
    thesis_breakers=["Government contract concentration (top 20 clients >50% of revenue) and budget sequestration", "AIP commercial adoption fails to scale beyond pilot stage"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="COIN", company="Coinbase",
    archetype=Archetype.SPECULATIVE,
    durability_range=(0.38, 0.48),
    moat_types=["regulatory", "brand"],
    revenue_model="transaction_toll",
    switching_cost="low", cyclicality="highly_cyclical",
    capital_intensity="asset_light", narrative_dependence="high", binary_risk="moderate",
    conviction_range=(28, 48),
    expected_stances=["Hold", "Avoid"],
    peer_group=["RBLX"],
    appropriate_analogs=[AnalogFamily.HYPERGROWTH_DECEL, AnalogFamily.REGULATORY_BREAK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Regulated US crypto exchange; revenue drops 80% in crypto winters; regulatory clarity is the structural bull case.",
    thesis_breakers=["SEC classifies majority of crypto tokens as securities", "Crypto winter reduces trading volume below breakeven for 4+ quarters"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="RBLX", company="Roblox",
    archetype=Archetype.SPECULATIVE,
    durability_range=(0.45, 0.55),
    moat_types=["network_effect"],
    revenue_model="transaction_toll",
    switching_cost="moderate", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="high", binary_risk="moderate",
    conviction_range=(22, 42),
    expected_stances=["Avoid", "Hold"],
    peer_group=["COIN", "SNAP"],
    appropriate_analogs=[AnalogFamily.HYPERGROWTH_DECEL, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="UGC gaming platform with 70M+ DAU; monetization per user is the key debate.",
    thesis_breakers=["DAU declines as Gen Alpha ages out", "Bookings/DAU fails to reach profitability threshold"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="CAVA", company="CAVA Group",
    archetype=Archetype.SPECULATIVE,
    durability_range=(0.22, 0.32),
    moat_types=["brand"],
    revenue_model="product_sale",
    switching_cost="none", cyclicality="moderate",
    capital_intensity="moderate", narrative_dependence="high", binary_risk="low",
    conviction_range=(18, 38),
    expected_stances=["Avoid", "Hold"],
    peer_group=["SBUX"],
    appropriate_analogs=[AnalogFamily.HYPERGROWTH_DECEL, AnalogFamily.FRANCHISE_CRISIS],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Fast-casual Mediterranean restaurant chain in early expansion; Chipotle 2.0 thesis requires flawless unit economics at scale.",
    thesis_breakers=["Same-store-sales decelerate below 5% for 2+ quarters", "Unit economics deteriorate as expansion moves beyond core East Coast markets"],
    must_rank_above=[],
))

# ═══════════════════════════════════════════════════════════════════════════
# TURNAROUND
# ═══════════════════════════════════════════════════════════════════════════

_b(BenchmarkEntry(
    ticker="BA", company="Boeing",
    archetype=Archetype.TURNAROUND,
    durability_range=(0.34, 0.44),
    moat_types=["regulatory", "scale_economy"],
    revenue_model="project_contract",
    switching_cost="very_high", cyclicality="highly_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="high", binary_risk="moderate",
    conviction_range=(25, 45),
    expected_stances=["Hold", "Avoid"],
    peer_group=["RTX", "LMT", "GE"],
    appropriate_analogs=[AnalogFamily.FRANCHISE_CRISIS, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Commercial aviation duopoly with Airbus but quality crisis has destroyed cash flow and credibility.",
    thesis_breakers=["Another 737 MAX safety event", "Free cash flow negative for 3+ consecutive years", "Defense contracts shift to competitors due to execution failures"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="INTC", company="Intel",
    archetype=Archetype.TURNAROUND,
    durability_range=(0.35, 0.45),
    moat_types=["scale_economy", "patent"],
    revenue_model="product_sale",
    switching_cost="moderate", cyclicality="moderate",
    capital_intensity="capital_intensive", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(28, 48),
    expected_stances=["Hold", "Avoid"],
    peer_group=["AMD", "NVDA", "TSM"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.PLATFORM_TRANSITION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Foundry turnaround (18A process) is a multi-year bet; if successful, revaluation is massive; if not, secular decline continues.",
    thesis_breakers=["18A process node fails to achieve yield parity with TSMC N3", "Foundry services fail to attract external customers"],
    must_rank_above=[],
))

_b(BenchmarkEntry(
    ticker="DIS", company="Disney",
    archetype=Archetype.TURNAROUND,
    durability_range=(0.38, 0.48),
    moat_types=["brand", "patent"],
    revenue_model="mixed",
    switching_cost="low", cyclicality="moderate",
    capital_intensity="capital_intensive", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(30, 50),
    expected_stances=["Hold", "Avoid"],
    peer_group=["NFLX", "CMCSA"],
    appropriate_analogs=[AnalogFamily.FRANCHISE_CRISIS, AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="IP franchise (Marvel, Star Wars, Pixar) is the moat but parks are capital-intensive and streaming is unprofitable.",
    thesis_breakers=["Disney+ reaches profitability but subscriber growth stalls", "Parks revenue declines due to consumer pushback on pricing"],
    must_rank_above=["CAVA"],
))

# ═══════════════════════════════════════════════════════════════════════════
# Additional important companies (abbreviated format)
# ═══════════════════════════════════════════════════════════════════════════

# --- Pharma ---
_b(BenchmarkEntry(
    ticker="LLY", company="Eli Lilly",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.35, 0.45),
    moat_types=["patent"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="low", binary_risk="moderate",
    conviction_range=(35, 55),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["NVO", "ABBV", "PFE", "MRK"],
    appropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.HYPERGROWTH_DECEL],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.INFRASTRUCTURE_OVERBUILD],
    primary_thesis="GLP-1 franchise (Mounjaro/Zepbound) is fastest-growing drug in history; $100B+ peak revenue potential.",
    thesis_breakers=["GLP-1 safety signal emerges in long-term data", "Oral GLP-1 competitors erode injectable pricing power"],
    must_rank_above=["PFE"],
))

_b(BenchmarkEntry(
    ticker="ABBV", company="AbbVie",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.45, 0.55),
    moat_types=["patent", "brand"],
    revenue_model="product_sale",
    switching_cost="moderate", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="moderate",
    conviction_range=(45, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["LLY", "PFE", "MRK", "JNJ"],
    appropriate_analogs=[AnalogFamily.PATENT_CLIFF],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Post-Humira cliff; Skyrizi+Rinvoq franchise replacing lost revenue; question is whether replacement is 1:1.",
    thesis_breakers=["Skyrizi/Rinvoq fail to fully offset Humira biosimilar erosion", "Pipeline Phase 3 failures in key programs"],
    must_rank_above=["PFE"],
))

_b(BenchmarkEntry(
    ticker="PFE", company="Pfizer",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.38, 0.48),
    moat_types=["patent", "scale_economy"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="low", binary_risk="moderate",
    conviction_range=(32, 50),
    expected_stances=["Hold", "Avoid"],
    peer_group=["LLY", "ABBV", "MRK"],
    appropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Post-COVID cliff recovery; Seagen ADC portfolio acquisition is the pipeline bet.",
    thesis_breakers=["Seagen integration fails to deliver pipeline value", "COVID treatment/vaccine revenue drops to zero with no replacement"],
    must_rank_above=["CAVA"],
))

_b(BenchmarkEntry(
    ticker="MRK", company="Merck",
    archetype=Archetype.QUALITY_CYCLIC,
    durability_range=(0.38, 0.46),
    moat_types=["patent"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="moderate",
    conviction_range=(35, 52),
    expected_stances=["Hold", "Avoid"],
    peer_group=["LLY", "ABBV", "PFE"],
    appropriate_analogs=[AnalogFamily.PATENT_CLIFF],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.MEMBERSHIP_ELASTICITY],
    primary_thesis="Keytruda franchise (~$25B/yr) approaching patent cliff (~2028); pipeline must replace single-product concentration.",
    thesis_breakers=["Keytruda biosimilar competition arrives earlier than expected", "Pipeline fails to produce a Keytruda-scale successor"],
    must_rank_above=["CAVA"],
))

# --- Defense ---
_b(BenchmarkEntry(
    ticker="LMT", company="Lockheed Martin",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.58, 0.66),
    moat_types=["regulatory", "scale_economy"],
    revenue_model="project_contract",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="low",
    conviction_range=(45, 63),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["RTX", "GE", "BA"],
    appropriate_analogs=[AnalogFamily.GOVERNMENT_BUDGET_CUT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="F-35 program monopoly + missile defense franchise; non-cyclical government spending with multi-decade backlogs.",
    thesis_breakers=["Defense budget sequestration", "F-35 program restructured or cancelled"],
    must_rank_above=["BA", "CAT"],
))

_b(BenchmarkEntry(
    ticker="RTX", company="RTX (Raytheon)",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.63, 0.71),
    moat_types=["regulatory", "scale_economy", "patent"],
    revenue_model="project_contract",
    switching_cost="very_high", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="low",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["LMT", "GE"],
    appropriate_analogs=[AnalogFamily.GOVERNMENT_BUDGET_CUT, AnalogFamily.DEMAND_AIR_POCKET],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Defense duopoly (missiles) + Pratt & Whitney jet engines; Geared Turbofan aftermarket drives recurring revenue.",
    thesis_breakers=["GTF powder metal issue extends beyond current fix timeline", "Defense budget cuts target missile programs"],
    must_rank_above=["BA"],
))

# --- Telecom ---
_b(BenchmarkEntry(
    ticker="T", company="AT&T",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.62, 0.70),
    moat_types=["scale_economy", "regulatory"],
    revenue_model="subscription",
    switching_cost="moderate", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(38, 55),
    expected_stances=["Hold"],
    peer_group=["VZ", "TMUS"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Wireless/fiber subscription base with dividend yield; 5G/fiber buildout is the growth driver.",
    thesis_breakers=["Wireless ARPU declines from price war", "Fiber buildout ROI disappoints"],
    must_rank_above=["XOM", "MU"],
))

_b(BenchmarkEntry(
    ticker="VZ", company="Verizon",
    archetype=Archetype.STABLE_YIELD,
    durability_range=(0.67, 0.75),
    moat_types=["scale_economy", "regulatory", "brand"],
    revenue_model="subscription",
    switching_cost="moderate", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(40, 58),
    expected_stances=["Hold"],
    peer_group=["T", "TMUS"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.RATE_SHOCK],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Premium telecom brand with best network quality; dividend yield + fiber/5G growth.",
    thesis_breakers=["TMUS share gains accelerate and VZ loses wireless subscribers", "Fixed wireless cannibalization of fiber investment"],
    must_rank_above=["XOM", "MU"],
))

# --- Consumer Staples ---
_b(BenchmarkEntry(
    ticker="PG", company="Procter & Gamble",
    archetype=Archetype.COMPOUNDER,
    durability_range=(0.50, 0.60),
    moat_types=["brand", "scale_economy"],
    revenue_model="product_sale",
    switching_cost="moderate", cyclicality="non_cyclical",
    capital_intensity="moderate", narrative_dependence="none", binary_risk="none",
    conviction_range=(42, 58),
    expected_stances=["Hold"],
    peer_group=["KO", "MDLZ", "JNJ"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Global consumer staples franchise (Tide, Pampers, Gillette); pricing power through brand strength.",
    thesis_breakers=["Private label share gains accelerate in core categories", "Input cost inflation compresses margins without pricing offset"],
    must_rank_above=["NKE", "TGT"],
))

_b(BenchmarkEntry(
    ticker="WMT", company="Walmart",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.52, 0.60),
    moat_types=["scale_economy", "brand", "data_advantage"],
    revenue_model="product_sale",
    switching_cost="low", cyclicality="non_cyclical",
    capital_intensity="capital_intensive", narrative_dependence="none", binary_risk="none",
    conviction_range=(50, 68),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["COST", "TGT", "AMZN"],
    appropriate_analogs=[AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Largest US retailer with grocery anchor; Walmart+ and advertising/marketplace are the growth vectors.",
    thesis_breakers=["Amazon captures meaningful grocery share", "Walmart+ growth stalls below 30M subscribers"],
    must_rank_above=["TGT", "NKE", "DIS"],
))

# --- NFLX ---
_b(BenchmarkEntry(
    ticker="NFLX", company="Netflix",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.65, 0.73),
    moat_types=["network_effect", "brand", "data_advantage"],
    revenue_model="subscription",
    switching_cost="low", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="low", binary_risk="none",
    conviction_range=(50, 68),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["DIS", "CMCSA"],
    appropriate_analogs=[AnalogFamily.HYPERGROWTH_DECEL, AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Global streaming leader with 260M+ paid subs; ad tier and password-sharing crackdown drive revenue growth.",
    thesis_breakers=["Subscriber saturation in developed markets with no pricing power", "Content cost inflation outpaces revenue growth"],
    must_rank_above=["DIS", "RBLX"],
))

# --- Additional high-search tickers with must_rank_above constraints ---
_b(BenchmarkEntry(
    ticker="ORCL", company="Oracle",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.62, 0.70),
    moat_types=["switching_cost", "scale_economy"],
    revenue_model="licensing",
    switching_cost="very_high", cyclicality="mild",
    capital_intensity="moderate", narrative_dependence="low", binary_risk="none",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["MSFT", "CRM", "SNOW"],
    appropriate_analogs=[AnalogFamily.PLATFORM_TRANSITION, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Enterprise database monopoly with extreme switching costs; OCI cloud transition is the growth catalyst.",
    thesis_breakers=["Cloud-native databases (Snowflake, Databricks) displace Oracle at enterprise scale", "OCI growth stalls below 20%"],
    must_rank_above=["INTC", "COIN"],
))

_b(BenchmarkEntry(
    ticker="PANW", company="Palo Alto Networks",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.64, 0.72),
    moat_types=["switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="low", binary_risk="none",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["CRM", "SNOW"],
    appropriate_analogs=[AnalogFamily.MULTIPLE_COMPRESSION, AnalogFamily.COMPETITIVE_DISPLACEMENT],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="Cybersecurity platform leader; platformization strategy consolidates point products into single vendor.",
    thesis_breakers=["Free tier conversion fails to drive platform adoption", "Major breach traced to PANW product damages brand"],
    must_rank_above=["COIN", "RBLX"],
))

_b(BenchmarkEntry(
    ticker="UBER", company="Uber Technologies",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.60, 0.70),
    moat_types=["network_effect", "data_advantage"],
    revenue_model="transaction_toll",
    switching_cost="low", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(48, 65),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["ABNB", "DASH"],
    appropriate_analogs=[AnalogFamily.REGULATORY_BREAK, AnalogFamily.COMPETITIVE_DISPLACEMENT, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Mobility+delivery platform with network effects; advertising revenue (high margin) is the emerging profit driver.",
    thesis_breakers=["Autonomous vehicles eliminate driver marketplace value", "Gig worker reclassification increases costs structurally"],
    must_rank_above=["COIN", "RBLX"],
))

_b(BenchmarkEntry(
    ticker="SHOP", company="Shopify",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.68, 0.76),
    moat_types=["network_effect", "switching_cost"],
    revenue_model="subscription",
    switching_cost="high", cyclicality="mild",
    capital_intensity="asset_light", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(40, 58),
    expected_stances=["Hold", "Accumulate"],
    peer_group=["AMZN", "MELI"],
    appropriate_analogs=[AnalogFamily.HYPERGROWTH_DECEL, AnalogFamily.MULTIPLE_COMPRESSION],
    inappropriate_analogs=[AnalogFamily.COMMODITY_SHOCK, AnalogFamily.PATENT_CLIFF],
    primary_thesis="E-commerce infrastructure platform; merchant switching costs + Shop Pay + Shopify Fulfillment Network.",
    thesis_breakers=["Enterprise merchant churn accelerates", "Amazon's Buy with Prime captures Shopify merchant GMV"],
    must_rank_above=["COIN", "CAVA"],
))

_b(BenchmarkEntry(
    ticker="ABNB", company="Airbnb",
    archetype=Archetype.QUALITY_GROWTH,
    durability_range=(0.55, 0.65),
    moat_types=["network_effect", "brand"],
    revenue_model="transaction_toll",
    switching_cost="low", cyclicality="moderate",
    capital_intensity="asset_light", narrative_dependence="moderate", binary_risk="none",
    conviction_range=(40, 58),
    expected_stances=["Hold"],
    peer_group=["UBER", "BKNG"],
    appropriate_analogs=[AnalogFamily.REGULATORY_BREAK, AnalogFamily.HYPERGROWTH_DECEL],
    inappropriate_analogs=[AnalogFamily.PATENT_CLIFF, AnalogFamily.COMMODITY_SHOCK],
    primary_thesis="Global travel platform with asset-light model; supply-side moat from 7M+ listings.",
    thesis_breakers=["Municipal short-term rental bans proliferate", "Booking.com captures alternative accommodation share"],
    must_rank_above=["CAVA"],
))


# ---------------------------------------------------------------------------
# Pairwise dominance constraints (extracted from entries + additional)
# ---------------------------------------------------------------------------

PAIRWISE_CONSTRAINTS: List[Tuple[str, str, str]] = []

def _extract_constraints() -> None:
    """Build the full constraint list from must_rank_above fields + structural rules."""
    # From individual entries
    for ticker, entry in BENCHMARK.items():
        for inferior in entry.must_rank_above:
            if inferior in BENCHMARK:
                PAIRWISE_CONSTRAINTS.append((ticker, inferior, f"{ticker} must rank above {inferior}"))

    # Structural rules: every archetype tier has dominance
    compounders = [t for t, e in BENCHMARK.items() if e.archetype == Archetype.COMPOUNDER]
    speculative = [t for t, e in BENCHMARK.items() if e.archetype == Archetype.SPECULATIVE]

    # Every compounder should durability-rank above every speculative
    for c in compounders:
        for s in speculative:
            PAIRWISE_CONSTRAINTS.append((c, s, f"Compounder {c} should rank above speculative {s} on durability"))

_extract_constraints()


# ---------------------------------------------------------------------------
# Stance acceptability map
# ---------------------------------------------------------------------------

ACCEPTABLE_STANCES: Dict[str, List[str]] = {
    ticker: entry.expected_stances for ticker, entry in BENCHMARK.items()
}


# ---------------------------------------------------------------------------
# Analog appropriateness map
# ---------------------------------------------------------------------------

APPROPRIATE_ANALOG_FAMILIES: Dict[str, List[str]] = {
    ticker: [a.value for a in entry.appropriate_analogs] for ticker, entry in BENCHMARK.items()
}

INAPPROPRIATE_ANALOG_FAMILIES: Dict[str, List[str]] = {
    ticker: [a.value for a in entry.inappropriate_analogs] for ticker, entry in BENCHMARK.items()
}
