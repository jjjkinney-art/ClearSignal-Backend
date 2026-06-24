"""Company knowledge database mapping tickers to CompanyKnowledgeProfile instances.

This module provides curated, company-specific business intelligence for a
set of major publicly-traded companies.  The profiles are injected into every
specialist agent prompt to force non-generic, company-specific reasoning and
are also consumed by the depth guard to verify that synthesised theses
reference actual business-model terms rather than sector-level clichés.

Public API
----------
get_knowledge_profile(ticker)         → Optional[CompanyKnowledgeProfile]
get_profile_for_company(company)      → Optional[CompanyKnowledgeProfile]
list_known_tickers()                  → List[str]
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..schemas import CompanyContext, CompanyKnowledgeProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge database
# ---------------------------------------------------------------------------

_KNOWLEDGE_DB: Dict[str, CompanyKnowledgeProfile] = {}


def _register(profile: CompanyKnowledgeProfile) -> None:
    """Add a profile to the in-memory database, keyed by uppercase ticker."""
    _KNOWLEDGE_DB[profile.ticker.upper()] = profile


# ── Apple (AAPL) ──────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AAPL",
    company_name="Apple Inc.",
    business_model=(
        "Apple designs and sells premium consumer electronics (iPhone, Mac, iPad, "
        "Apple Watch, AirPods) and a growing portfolio of digital services (App Store, "
        "iCloud, Apple Music, Apple TV+, Apple Pay) monetised through the 2B+ active "
        "device installed base.  Apple Intelligence — the on-device AI feature suite "
        "launching across iPhone 16 and M-series Macs — is positioned as the primary "
        "catalyst for an upgrade supercycle, embedding generative AI capabilities "
        "(writing tools, image generation, Siri with ChatGPT integration) that create "
        "a compelling reason to upgrade for the 600M+ iPhones on older hardware."
    ),
    primary_revenue_drivers=[
        "iPhone (~52% of revenue) — upgrade cycle driven by Apple Intelligence AI features",
        "Services (~25% of revenue, ~72% gross margin) — App Store, iCloud, Apple TV+, "
        "Apple Music, Apple Pay, Google TAC (~$18-20B/yr search default payment)",
        "Mac (~8%) — M-series chip leadership; halo from Apple Intelligence",
        "iPad (~7%)",
        "Wearables / Home / Accessories (~8%) — Apple Watch, AirPods, Vision Pro",
    ],
    recurring_revenue_sources=[
        "App Store commissions (15–30% take rate on $90B+ annual App Store GMV)",
        "iCloud storage subscriptions (1B+ paid iCloud users)",
        "Apple One bundle (Music, TV+, Arcade, Fitness+)",
        "AppleCare extended warranty (~$10B/yr high-margin)",
        "Apple Pay / Tap-to-Pay interchange participation",
        "Google TAC (search default on Safari, ~$18–20B/yr — at risk from DOJ antitrust)",
    ],
    rate_sensitivity_note=(
        "Apple's premium ~28-30x P/E multiple is DCF-sensitive; a 100 bps rise in the "
        "10-year Treasury compresses the fair-value multiple by roughly 2-3 turns on "
        "standard DCF mechanics.  However, Services revenue (>25% of revenue, ~72% gross "
        "margin) grows with the 2B+ active installed base largely independent of rate "
        "moves.  Hardware unit demand is consumer-credit sensitive in rate-hike cycles "
        "(higher financing costs reduce upgrade propensity).  The $165B+ gross cash "
        "balance earns incremental interest income (~$5B/yr at current rates) as a "
        "partial offset.  Net cash position is approximately zero after netting debt."
    ),
    inflation_pass_through=(
        "Strong pricing power: Apple has raised iPhone ASPs from ~$695 in 2016 to "
        ">$900 by 2023 without significant unit-demand destruction, underpinned by "
        "ecosystem lock-in.  COGS are partially protected by long-term TSMC supply "
        "agreements, though NAND and DRAM component inflation does compress hardware "
        "margins in upcycles.  Services segment has near-zero marginal cost, so "
        "inflationary pressures affect Services margins minimally."
    ),
    recession_behavior=(
        "iPhone is a considered purchase; unit volumes declined ~4% in the 2022-23 "
        "slowdown but revenue was protected by mix-shift toward Pro models.  Services "
        "revenue is sticky and continued to grow through that period.  Mac and iPad are "
        "more discretionary and saw steeper declines.  Apple's ~$90B/yr free cash flow "
        "and fortress balance sheet allow it to sustain buybacks through downturns, "
        "providing EPS support."
    ),
    major_risks=[
        "China revenue concentration (~19% of total) and supply-chain risk; TSMC "
        "manufactures all A/M-series chips in Taiwan; Huawei competing for China iPhone share",
        "EU Digital Markets Act (DMA) enforcement forcing App Store sideloading and "
        "reducing take rates — estimated 3-5% Services revenue headwind if take rate falls",
        "Google TAC payment (~$18-20B/yr) at risk if DOJ antitrust action forces Search "
        "default competition — would be the largest single Services revenue shock in history",
        "Apple Intelligence underwhelming adoption — if AI features don't drive upgrade "
        "propensity, the supercycle thesis collapses and iPhone volumes stagnate",
        "Vision Pro tepid demand at $3,499 — AR/VR not yet a mass market platform",
    ],
    valuation_style=(
        "Market prices AAPL on a blended P/E (~28-30x) with significant weight on "
        "Services segment via a sum-of-parts: hardware traded at ~15x, Services at "
        "~35-40x (software multiple), weighted by mix.  As Services becomes a larger "
        "share, the blended multiple expands structurally.  Buyback yield (~3-4%/yr) "
        "provides meaningful EPS accretion that partially offsets multiple compression "
        "in rising-rate environments.  Apple Intelligence-driven supercycle could "
        "justify 30-33x if iPhone ASP lifts and Services attach rate improves."
    ),
    key_metrics=[
        "iPhone unit volumes and ASP (Apple Intelligence upgrade propensity)",
        "Services revenue growth rate and gross margin (~72%)",
        "Active installed base (2B+ devices)",
        "Gross margin (overall target ~44-46%)",
        "Free cash flow ($85-95B/yr range)",
        "Share buybacks (>$85B/yr authorized)",
        "China revenue % of total",
        "App Store GMV, take rate, and DMA compliance cost",
        "Apple Intelligence feature adoption rate (new metric)",
    ],
    competitive_advantages=[
        "Tightly integrated hardware-software-services ecosystem that raises switching costs",
        "A/M-series chip vertical integration delivering best-in-class perf-per-watt and "
        "enabling on-device Apple Intelligence AI processing with privacy advantage",
        "Brand loyalty with ~90%+ iPhone retention in upgrade cycles",
        "App Store platform network effect (developer supply × user demand)",
        "Privacy positioning as differentiator vs Android and cloud-AI competitors",
        "Google TAC relationship provides $18-20B/yr risk-free Services revenue floor",
    ],
    business_model_keywords=[
        "iPhone", "Services", "App Store", "iCloud", "installed base", "buyback",
        "China", "Mac", "AppleCare", "ecosystem", "TSMC", "Tim Cook", "M-series",
        "TAC", "sideloading", "Apple Intelligence", "DMA", "Vision Pro", "AI supercycle",
        "on-device AI", "wearables", "EU Digital Markets Act",
    ],
    moat_type=["brand", "switching_cost", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Nvidia (NVDA) ─────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="NVDA",
    company_name="NVIDIA Corporation",
    business_model=(
        "NVIDIA designs GPUs and system-on-chip processors, licensing its CUDA parallel "
        "computing platform to hyperscalers and enterprises for AI training and inference, "
        "while also serving the gaming, automotive, and professional visualization markets.  "
        "The current product cycle — the Blackwell architecture (B100/B200/GB200 GPUs, "
        "NVL72 rack-scale systems) — represents NVIDIA's largest generational leap, with "
        "GB200 delivering 30x inference throughput vs H100 at similar TCO.  The inference "
        "vs training split is shifting: inference workloads (serving deployed AI models) "
        "are growing faster than training workloads, expanding NVIDIA's addressable market "
        "beyond model training to production inference infrastructure.  NIM microservices "
        "(NVIDIA Inference Microservices) represent an emerging software revenue stream, "
        "monetising the CUDA ecosystem as API calls rather than just hardware shipments."
    ),
    primary_revenue_drivers=[
        "Data Center (~87% of revenue) — Blackwell B100/B200/GB200 GPU clusters "
        "(replacing H100/H200), DGX/HGX systems, InfiniBand + Ethernet networking "
        "(Quantum InfiniBand and Spectrum Ethernet via Mellanox)",
        "Gaming (~9% — GeForce RTX consumer GPUs; AI-enhanced DLSS drives refresh cycle)",
        "Professional Visualization (~2%)",
        "Automotive (<2% — DRIVE platform; NVIDIA DRIVE Thor for next-gen vehicles)",
        "Emerging software / NIM microservices — growing but currently <1% of revenue",
    ],
    recurring_revenue_sources=[
        "CUDA software ecosystem (developer lock-in creates high switching costs)",
        "NVIDIA AI Enterprise software subscription",
        "NIM (NVIDIA Inference Microservices) cloud API monetisation",
        "DGX Cloud (managed GPU cluster service)",
    ],
    rate_sensitivity_note=(
        "NVDA trades at an elevated ~35-45x forward P/E, making the DCF-derived "
        "intrinsic value highly sensitive to discount-rate assumptions — a 100 bps rise "
        "compresses the fair-value range by ~5-8 turns on a long-duration growth model.  "
        "However, the near-term earnings power is driven by hyperscaler CapEx budgets "
        "(Microsoft, Meta, Google, Amazon) rather than credit conditions, insulating "
        "fundamental demand from rate moves in the short run.  NVDA has minimal debt "
        "($9B long-term) and generates ~$60B+ in annual free cash flow, so refinancing "
        "risk is negligible."
    ),
    inflation_pass_through=(
        "Extremely strong: NVDA has repeatedly raised H100/H200 GPU prices ($30K → $35K+) "
        "while maintaining a >75% gross margin, reflecting monopoly pricing power in AI "
        "accelerators.  TSMC foundry cost inflation is largely passed through to customers "
        "with minimal margin impact due to the absence of viable substitutes."
    ),
    recession_behavior=(
        "Data Center revenue from hyperscalers is sticky even in mild recessions as AI "
        "infrastructure buildout is multi-year committed CapEx.  Gaming is more cyclical "
        "(declined ~27% in fiscal 2023).  A severe credit crunch could delay hyperscaler "
        "CapEx, but NVDA's backlog and lead times (12+ months) provide revenue visibility "
        "that buffers near-term demand shocks."
    ),
    major_risks=[
        "US export restrictions on H100/A100 GPUs to China (historically ~20-25% of "
        "Data Center revenue) — BIS rules limit NVDA's ability to sell advanced chips to China",
        "Custom ASIC competition from hyperscaler in-house chips (Google TPU v5, Amazon "
        "Trainium2, Microsoft Maia) reducing GPU TAM at margin",
        "AMD MI300X gaining traction in inference workloads as a viable CUDA alternative",
        "TSMC CoWoS advanced packaging capacity is a supply constraint on HBM-attached GPUs",
        "Concentration: top 4 hyperscalers (~40-50% of Data Center revenue)",
    ],
    valuation_style=(
        "Market applies a growth-at-any-price framework: forward P/E ~35-45x with "
        "P/S ~20x justified by 100%+ revenue growth rates.  As growth normalises, the "
        "market will likely transition to a FCF yield framework (~2-3% yield at current "
        "prices implies the market expects sustained $60B+ FCF).  Sum-of-parts analysis "
        "assigns a software/platform premium to CUDA and NIM recurring revenue."
    ),
    key_metrics=[
        "Data Center revenue quarterly growth rate",
        "Gross margin (target 74-75%+)",
        "H100/H200/B100 GPU shipment volumes",
        "Hyperscaler CapEx commentary (proxy demand signal)",
        "China revenue % post-export restriction",
        "Free cash flow ($55-65B/yr range)",
        "CUDA developer ecosystem size (6M+ registered developers)",
    ],
    competitive_advantages=[
        "CUDA parallel computing platform with 15+ years of developer investment creates "
        "extremely high switching costs",
        "Full-stack approach: GPU silicon + NVLink interconnect + InfiniBand networking + "
        "software stack (cuDNN, TensorRT, NIM)",
        "First-mover advantage in AI training (H100 dominates training workloads by >80% share)",
        "Jensen Huang's roadmap cadence (annual new GPU generation) vs 18-24 month AMD cycle",
    ],
    business_model_keywords=[
        "GPU", "CUDA", "H100", "H200", "data center", "hyperscaler", "AI accelerator",
        "NIM", "export restrictions", "Jensen Huang", "InfiniBand",
        "Blackwell", "HBM", "GB200", "B200", "NVL72", "inference", "training",
        "Blackwell cycle", "NIM microservices", "custom ASIC", "CUDA ecosystem",
    ],
    moat_type=["data_advantage", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="high",
    customer_concentration="moderate",
    capital_intensity="moderate",
    earnings_cyclicality="highly_cyclical",
    narrative_dependence="moderate",
    binary_risk_level="none",
))


# ── Microsoft (MSFT) ──────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="MSFT",
    company_name="Microsoft Corporation",
    business_model=(
        "Microsoft generates revenue through three segments: Intelligent Cloud (Azure "
        "hyperscale cloud + enterprise server software), Productivity & Business Processes "
        "(Microsoft 365 subscriptions, LinkedIn, Dynamics), and More Personal Computing "
        "(Windows OEM, Xbox, Surface, Bing/Search advertising)."
    ),
    primary_revenue_drivers=[
        "Intelligent Cloud (~43% of revenue — Azure IaaS/PaaS/AI services, SQL Server, "
        "Windows Server)",
        "Productivity & Business Processes (~32% — Microsoft 365, Exchange, SharePoint, "
        "Teams, LinkedIn, Dynamics 365)",
        "More Personal Computing (~25% — Windows OEM, Xbox Game Pass, Surface, Bing, "
        "Activision games)",
    ],
    recurring_revenue_sources=[
        "Microsoft 365 commercial seat-based subscription (~350M+ paid seats)",
        "Azure consumption-based billing (pay-as-you-go + committed-use contracts)",
        "Dynamics 365 CRM/ERP SaaS subscriptions",
        "Xbox Game Pass subscription (~34M subscribers)",
        "LinkedIn Talent Solutions and Premium subscriptions",
        "GitHub Copilot enterprise subscriptions",
    ],
    rate_sensitivity_note=(
        "MSFT trades at ~30-33x forward P/E.  A 100 bps rise in the 10-year Treasury "
        "compresses fair-value by ~3-4 turns in a standard DCF.  However, ~85%+ of "
        "revenue is recurring (subscription or consumption), providing strong earnings "
        "floor regardless of rate moves.  MSFT has $143B+ in short-term investments and "
        "cash, earning incremental interest income of ~$4-5B/yr at current rates.  Net "
        "debt is effectively zero after netting the cash balance against $45B of long-term "
        "debt.  Enterprise IT budgets are relatively rate-insensitive for mission-critical "
        "cloud workloads."
    ),
    inflation_pass_through=(
        "Strong pricing power: Microsoft raised Microsoft 365 commercial prices 20% in "
        "2022 (first increase in a decade) with minimal churn, demonstrating platform "
        "indispensability.  Azure is consumption-based so nominal revenue inflates with "
        "compute costs.  LinkedIn advertising is somewhat macro-sensitive."
    ),
    recession_behavior=(
        "Microsoft 365 churn is very low even in recessions because it is mission-critical "
        "productivity infrastructure.  Azure consumption can slow as customers optimise "
        "workloads but does not contract sharply.  Advertising (Bing, LinkedIn) and Xbox "
        "hardware face headwinds in recessions.  Overall, MSFT is among the most "
        "recession-resilient large-cap tech companies."
    ),
    major_risks=[
        "Azure growth deceleration vs AWS and Google Cloud — market share competition "
        "is intensifying",
        "OpenAI investment ($13B+) — concentration risk on a single AI partner; model "
        "commoditisation could reduce Azure AI differentiation",
        "Antitrust scrutiny of Microsoft 365 bundling (Teams unbundling in EU/UK)",
        "Activision Blizzard integration execution risk and content pipeline dependency",
        "China geopolitical exposure (LinkedIn exited China; Azure has limited China presence)",
    ],
    valuation_style=(
        "Priced on forward P/E (~30-33x) with a software-quality premium.  EV/FCF is "
        "the preferred metric (~30-35x FCF given ~$85B/yr FCF).  Sum-of-parts: Azure "
        "valued at ~20-25x revenue (cloud multiple), Microsoft 365 at ~12-15x revenue "
        "(mature SaaS), gaming/advertising at lower multiples.  AI Copilot revenue "
        "upsell (~$30/seat premium) is the key near-term incremental revenue opportunity."
    ),
    key_metrics=[
        "Azure revenue growth rate (constant currency)",
        "Microsoft 365 commercial ARPU and seat count",
        "Intelligent Cloud operating income margin (~43%)",
        "Free cash flow ($85-90B/yr range)",
        "Copilot seat adoption across M365 and GitHub",
        "LinkedIn revenue growth rate",
        "Capital expenditure (AI infrastructure buildout, ~$50B/yr)",
    ],
    competitive_advantages=[
        "Microsoft 365 + Azure combined platform creates enterprise-wide switching costs "
        "(Active Directory, identity, compliance, data residency)",
        "GitHub Copilot occupies developer workflow at the code-creation level",
        "Teams embedded in enterprise workflows post-pandemic",
        "Azure Arc and hybrid cloud strategy allows on-prem workload migration",
        "OpenAI partnership gives Azure first-mover AI services advantage",
    ],
    business_model_keywords=[
        "Azure", "Microsoft 365", "Copilot", "Teams", "OpenAI", "LinkedIn", "GitHub",
        "Activision", "Dynamics", "Xbox Game Pass", "Intelligent Cloud", "seat", "CapEx",
        "Satya Nadella", "M365 Copilot", "Azure OpenAI Service", "GitHub Copilot",
        "Productivity & Business Processes", "More Personal Computing",
        "Copilot monetization", "Azure OpenAI", "AI Copilot",
    ],
    moat_type=["switching_cost", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Tesla (TSLA) ──────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="TSLA",
    company_name="Tesla, Inc.",
    business_model=(
        "Tesla designs, manufactures, and sells battery-electric vehicles (Model 3/Y/S/X/Cybertruck) "
        "through a direct-to-consumer model, while also operating a high-margin Energy Generation "
        "& Storage segment (Powerwall, Megapack) and a nascent Software & Services revenue line "
        "(FSD, Supercharging, insurance)."
    ),
    primary_revenue_drivers=[
        "Automotive — vehicle sales (~80% of revenue, led by Model 3/Y mass market)",
        "Energy Generation & Storage (~10% — Megapack utility-scale battery, Powerwall)",
        "Services & Other (~10% — Supercharging, body shop, used vehicle sales, FSD)",
    ],
    recurring_revenue_sources=[
        "Full Self-Driving (FSD) subscriptions ($99/mo) — software margin approaches 100%",
        "Supercharger network revenue (now open to non-Tesla EVs via NACS standard)",
        "Tesla insurance (underwritten by Tesla in several US states)",
        "Autopilot OTA updates and feature unlocks",
    ],
    rate_sensitivity_note=(
        "Tesla is acutely rate-sensitive on two dimensions: (1) vehicle financing — most "
        "EV purchases are financed, and a 100 bps rate rise meaningfully increases monthly "
        "payments, reducing affordability in the mass-market Model 3/Y segment; (2) "
        "valuation — TSLA trades at an elevated P/E of ~60-80x on an AI/autonomous-driving "
        "premium that is highly sensitive to long-duration cash flows being discounted at "
        "higher rates.  Each 100 bps rate increase compresses the DCF-implied fair value "
        "by ~10-15% in growth-scenario models.  Tesla does not have significant corporate "
        "debt, so refinancing risk is low."
    ),
    inflation_pass_through=(
        "Mixed: Tesla repeatedly cut vehicle prices in 2023-24 to defend volume share, "
        "showing limited pricing power in the automotive commodity phase.  Raw-material "
        "cost inflation (lithium, nickel, cobalt) directly compresses automotive gross "
        "margins, which fell from ~30% in 2022 to ~17-18% by 2024.  Megapack benefits "
        "from long-term contracted prices."
    ),
    recession_behavior=(
        "Vehicles are large consumer purchases that contract in severe downturns; prior "
        "recessions saw US auto sales decline significantly.  Tesla's Megapack/Energy "
        "backlog (multi-year committed utility orders) is relatively resilient given "
        "long-term infrastructure purchase commitments.  The direct-sales model creates "
        "cyclical exposure to automotive demand cycles, though price flexibility "
        "provides some volume defense at the cost of margin."
    ),
    major_risks=[
        "Intensifying EV competition from BYD (China), Hyundai/Kia, and legacy OEMs "
        "(GM Silverado EV, Ford F-150 Lightning) eroding ASP and market share",
        "FSD regulatory approval risk — full autonomy requires NHTSA/DMV certification "
        "that has repeatedly been delayed",
        "Elon Musk key-person risk and brand dilution from his political activities",
        "China market risk (~23% of revenue) — BYD competition and potential tariff retaliation",
        "Automotive gross margin compression from pricing wars vs cost reduction targets",
    ],
    valuation_style=(
        "TSLA is valued as a hybrid of automotive company (6-8x EV/EBITDA), software/AI "
        "platform (30-50x P/E on FSD/Robotaxi execution potential), and energy storage "
        "business (15-20x EV/EBITDA on Megapack).  The market-implied Robotaxi/FSD "
        "earnings contribution is embedded in the current P/E — removing that potential "
        "implies the auto business alone would be worth ~$100-120/share.  The premium "
        "above that level reflects the expected long-term contribution from autonomous "
        "driving at scale."
    ),
    key_metrics=[
        "Vehicle deliveries (quarterly, vs consensus)",
        "Automotive gross margin (ex-credits and regulatory credits)",
        "Megapack GWh deployed",
        "FSD subscription attach rate",
        "Free cash flow",
        "China deliveries and BYD competitive gap",
        "Elon Musk AI ventures conflict of interest (xAI, Grok)",
    ],
    competitive_advantages=[
        "Supercharger network (largest fast-charging network; NACS becoming the US standard)",
        "Gigafactory vertical integration reduces cell costs vs incumbent OEMs",
        "Over-the-air software update capability across entire fleet",
        "FSD neural network trained on the largest real-world driving dataset (~6B miles)",
        "Energy margin leverage: Megapack gross margins >25% and expanding",
    ],
    business_model_keywords=[
        "Model 3", "Model Y", "Cybertruck", "FSD", "Autopilot", "Megapack", "Supercharger",
        "Gigafactory", "BYD", "Robotaxi", "Elon Musk", "NACS", "energy storage",
        "China", "automotive gross margin",
    ],
    moat_type=["brand"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="capital_intensive",
    earnings_cyclicality="moderate",
    narrative_dependence="dominant",
    binary_risk_level="moderate",
))


# ── Alphabet / Google (GOOGL) ─────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="GOOGL",
    company_name="Alphabet Inc.",
    business_model=(
        "Alphabet generates the majority of revenue through Google Search advertising "
        "(keyword auction model), with growing contributions from YouTube ads, Google Cloud "
        "IaaS/PaaS, and Google Network / AdSense partner properties.  Moonshot bets "
        "(Waymo, DeepMind, Verily) are housed in the Other Bets segment."
    ),
    primary_revenue_drivers=[
        "Google Search & Other (~57% of revenue — keyword auction advertising)",
        "Google Network / AdSense (~10% — partner display advertising)",
        "YouTube Ads (~10% — video advertising)",
        "Google Cloud (~12% and growing — GCP IaaS/PaaS, Vertex AI, Workspace SaaS)",
        "Other (Google Play, Pixel hardware, YouTube Premium) (~8%)",
        "Other Bets (<1%)",
    ],
    recurring_revenue_sources=[
        "Google Workspace (Gmail, Drive, Meet) per-seat subscriptions",
        "YouTube Premium subscription",
        "Google One storage subscription",
        "Google Cloud committed-use and long-term contracts",
        "Play Store developer fee (15-30% take rate)",
    ],
    rate_sensitivity_note=(
        "GOOGL trades at ~22-25x forward P/E, more moderate than pure-growth tech, "
        "reflecting the advertising cyclicality baked into the multiple.  A 100 bps rate "
        "rise compresses fair-value by ~2-3 turns.  Alphabet's $110B+ net cash position "
        "earns ~$5B/yr in interest income.  Advertising spend is the primary fundamental "
        "sensitivity — recession risk to ad budgets is more material than rate-driven "
        "multiple compression."
    ),
    inflation_pass_through=(
        "Search CPCs (cost-per-click) are auction-determined and tend to inflate with "
        "advertiser budgets; inflation in the broader economy can increase e-commerce "
        "advertising spend.  YouTube CPMs are more volatile and cyclical.  Cloud revenue "
        "is relatively inflation-insensitive on committed contracts."
    ),
    recession_behavior=(
        "Digital advertising is cyclical: Google Search declined in Q3/Q4 2022 as "
        "advertisers cut budgets.  However, Google Search is the last-to-be-cut ad "
        "channel (performance-based ROI is measurable) vs brand/display advertising.  "
        "YouTube is more cyclical than Search.  Cloud revenue is contractually sticky."
    ),
    major_risks=[
        "Generative AI (ChatGPT/Perplexity) threatens Search query volume by providing "
        "direct answers without ad-monetisable click-through",
        "DOJ antitrust case on Search default agreements (could force structural changes "
        "to Google's distribution deals — Safari, Android default)",
        "Google Cloud margin ramp is slow vs AWS and Azure (GCP operating margin ~10-12% "
        "vs AWS ~30%+)",
        "EU regulatory pressure: GDPR fines, DMA (mandated interoperability, app stores)",
        "Waymo capital intensity with long commercialisation runway",
    ],
    valuation_style=(
        "GOOGL is priced at ~22-25x forward P/E with a large FCF yield (~4-5%), making it "
        "one of the cheaper mega-cap tech names.  Google Cloud is valued separately at "
        "10-15x revenue by sum-of-parts analysts, adding meaningful upside if margin "
        "expands.  The Search advertising business is valued at 15-20x EBIT (mature "
        "advertising platform).  Net cash ($110B+) adds ~$8-9/share of safety margin."
    ),
    key_metrics=[
        "Google Search revenue growth (constant currency)",
        "YouTube ad revenue growth",
        "Google Cloud revenue growth and operating margin",
        "Paid clicks and cost-per-click trends",
        "Operating income margin (Alphabet-level, targeting 30%+)",
        "Free cash flow ($60-70B/yr)",
        "Waymo robotaxi commercialisation milestones",
        "AI Overviews query monetisation rate",
    ],
    competitive_advantages=[
        "Google Search has >90% global query share with 25+ years of index and ranking "
        "data that is nearly impossible to replicate",
        "Android/Chrome distribution guarantees Google's AI assistant default placement "
        "on 3B+ devices",
        "YouTube is the world's second-largest search engine by query volume",
        "DeepMind / Google Brain AI research pipeline (Gemini, AlphaCode)",
        "DoubleClick ad-tech stack dominates publisher monetisation infrastructure",
    ],
    business_model_keywords=[
        "Search", "YouTube", "Google Cloud", "GCP", "Gemini", "Waymo", "DeepMind",
        "Android", "DOJ antitrust", "Workspace", "Vertex AI", "advertising CPC",
        "Sundar Pichai", "Other Bets",
    ],
    moat_type=["network_effect", "data_advantage", "scale_economy"],
    revenue_model="advertising",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Amazon (AMZN) ─────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AMZN",
    company_name="Amazon.com, Inc.",
    business_model=(
        "Amazon operates three distinct profit pools: AWS cloud computing (the primary "
        "earnings engine), North America and International e-commerce marketplaces "
        "(retail + third-party seller services + advertising), and a growing advertising "
        "business monetising the purchase-intent signal of 200M+ Prime members.  "
        "The primary investment thesis is AWS margin expansion: AWS operating margins "
        "expanded from ~27% in 2023 toward 35-38% as CapEx moderates and revenue "
        "scales, generating $100B+ in annualized operating income at scale.  Advertising "
        "($56B+ annual, near-100% incremental margin) is the second profit engine.  "
        "AMZN is best valued on an FCF yield or EV/FCF basis (~25-30x FCF), not P/E, "
        "because retail losses obscure the AWS + Advertising earning power."
    ),
    primary_revenue_drivers=[
        "Online Stores (~22% of revenue — first-party retail)",
        "Third-Party Seller Services (~24% — marketplace fulfillment and commissions)",
        "AWS (~17% of revenue, ~65-70% of operating income — AWS margin expanding "
        "toward 35-38% as generative AI workloads on Bedrock accelerate)",
        "Advertising Services (~8% and growing ~20%+/yr — sponsored products, brands; "
        "near-100% incremental margin — Amazon's second profit engine)",
        "Subscription Services (~7% — Prime membership $139/yr, music, video, "
        "Amazon Pharmacy benefits)",
        "Physical Stores (~4% — Whole Foods)",
    ],
    recurring_revenue_sources=[
        "Prime membership ($139/yr in the US) — ~200M global subscribers",
        "AWS committed-use contracts (1-3 year Enterprise Discount Program)",
        "Advertising repeat spend from endemic e-commerce advertisers",
        "Fulfillment by Amazon (FBA) recurring seller fees",
    ],
    rate_sensitivity_note=(
        "AMZN trades at a high P/E (~35-45x) but FCF-based valuation is more appropriate: "
        "~25-30x FCF given ~$55-60B annual FCF.  A 100 bps rate rise compresses the DCF "
        "by ~3-5 turns.  AWS enterprise CapEx commitments are multi-year and insensitive "
        "to short-term rate moves.  Retail margins are thin; higher rates slow e-commerce "
        "consumer spending.  Amazon carries ~$65B of long-term debt, but at fixed rates "
        "across maturities, limiting near-term refinancing exposure."
    ),
    inflation_pass_through=(
        "AWS pricing is largely contract-based with annual escalators.  Advertising CPM "
        "and CPC are auction-based and tend to rise with inflation.  Retail is a "
        "price-competitive marketplace; Amazon absorbs shipping/labor cost inflation "
        "through operational efficiency (robotics, delivery density).  Prime has been "
        "raised twice ($99→$119→$139) with minimal churn."
    ),
    recession_behavior=(
        "AWS is sticky and resilient: enterprise cloud workloads are mission-critical "
        "and essentially non-discretionary infrastructure — hard to turn off, though "
        "optimisation deals are common in stress periods.  Retail e-commerce benefits "
        "from trade-down from specialty retail and brick-and-mortar in recessions "
        "(Amazon gains market share as a value channel; e-commerce is a secular "
        "channel shift, not a cyclical one).  Advertising is more cyclical — "
        "branded advertising cuts faster than performance marketing."
    ),
    major_risks=[
        "AWS market share competition from Microsoft Azure (gaining vs AWS in enterprise) "
        "and Google Cloud (gaining in AI-native workloads)",
        "FTC antitrust pressure on Prime bundling and marketplace seller practices",
        "Last-mile delivery cost inflation (labor, fuel) compressing thin retail margins",
        "Alexa/voice-AI relevance in a generative-AI world dominated by LLMs",
        "India and international e-commerce losses; regulatory barriers in India",
    ],
    valuation_style=(
        "Best valued on an EV/FCF basis (~25-30x FCF) or sum-of-parts: AWS at ~15-20x "
        "revenue (cloud comps), Advertising at ~20-25x revenue (high-growth ad network), "
        "Retail at 0.5-1x revenue (thin-margin distribution).  The implied 'retail for "
        "free' thesis frames the investment case: pay for AWS+Advertising at fair "
        "multiples, receive the retail flywheel and logistics network as a strategic "
        "option at no incremental cost."
    ),
    key_metrics=[
        "AWS revenue growth rate and operating margin (~30%+)",
        "Advertising revenue growth rate",
        "North America retail operating income",
        "Free cash flow ($55-65B/yr target)",
        "Prime member count (~200M global)",
        "Third-party seller revenue share of marketplace GMV",
        "Fulfillment cost per unit",
    ],
    competitive_advantages=[
        "AWS proprietary chip stack (Graviton for compute, Trainium for AI training, "
        "Inferentia for inference) reduces silicon cost vs NVDA-GPU reliance",
        "Prime flywheel: fast shipping → more buyers → more sellers → lower per-unit costs",
        "Fulfillment network (1,100+ warehouses) creates last-mile moat",
        "Advertising business has the highest purchase-intent signal in digital ad",
    ],
    business_model_keywords=[
        "AWS", "Prime", "Marketplace", "Advertising", "Fulfillment", "Graviton",
        "Trainium", "Andy Jassy", "Whole Foods", "FTC", "third-party sellers",
        "Bedrock", "same-day delivery", "AWS margin", "FCF yield", "Trainium3",
        "Inferentia3", "Amazon Bedrock", "advertising margin", "EV/FCF",
    ],
    moat_type=["network_effect", "scale_economy", "data_advantage"],
    revenue_model="mixed",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="capital_intensive",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Meta Platforms (META) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="META",
    company_name="Meta Platforms, Inc.",
    business_model=(
        "Meta generates ~98% of revenue from digital advertising across the Family of Apps "
        "(Facebook, Instagram, WhatsApp, Messenger), monetising 3.27B+ daily active users "
        "via a machine-learning ad-targeting engine, while investing heavily in Reality Labs "
        "(Quest VR headsets, Ray-Ban smart glasses, metaverse) at significant operating losses."
    ),
    primary_revenue_drivers=[
        "Family of Apps advertising (~98% of revenue — Facebook Feed, Reels, Instagram, "
        "Stories, Marketplace)",
        "Reality Labs (<2% of revenue — Quest VR headsets, Ray-Ban glasses hardware)",
    ],
    recurring_revenue_sources=[
        "Recurring advertiser relationships (performance marketing with measurable ROI)",
        "WhatsApp Business API fees (emerging, growing in emerging markets)",
        "Meta Verified subscription (emerging)",
    ],
    rate_sensitivity_note=(
        "META trades at ~22-25x forward P/E with a high FCF yield (~4-5%).  A 100 bps "
        "rate rise has a moderate DCF impact (~2-3 turns).  More material is the "
        "advertising cyclicality: digital ad spending is a leading indicator of economic "
        "confidence, and META ad revenue fell ~1% in 2022 — the first annual decline in "
        "the company's history — during the rate-hike cycle.  META carries minimal debt "
        "relative to its $50B+ FCF capacity."
    ),
    inflation_pass_through=(
        "Advertising CPMs and CPCs are auction-determined; inflation in the broader "
        "economy can increase e-commerce advertising budgets (higher product prices → "
        "higher ROAS payoffs).  Content moderation and data-center infrastructure costs "
        "inflate with wages/energy, but Meta's AI efficiency improvements (Llama models "
        "for ad ranking) have reduced cost-per-impression."
    ),
    recession_behavior=(
        "Performance advertising (Meta's primary product) is more resilient than brand "
        "advertising because advertisers can measure ROI directly — it is cut later in a "
        "recession.  However, 2022 proved Meta is not recession-immune: combination of "
        "ATT/iOS privacy changes and macro slowdown caused two consecutive revenue "
        "declines.  Meta responded with 'Year of Efficiency' cost cuts ($10B in savings)."
    ),
    major_risks=[
        "Apple ATT (App Tracking Transparency) removed ~$10B in annual advertising "
        "revenue by degrading cross-app tracking — partial recovery via Meta's on-device "
        "learning, but permanent structural headwind",
        "TikTok competition for user time and advertiser budgets among 18-34 demographic",
        "Reality Labs cumulative losses ($45B+ since 2020) with uncertain commercialisation "
        "timeline for the metaverse",
        "EU GDPR enforcement limiting behavioral targeting in Europe",
        "FTC antitrust lawsuit seeking to unwind Instagram and WhatsApp acquisitions",
    ],
    valuation_style=(
        "META is priced at ~22-25x forward P/E — cheap relative to FAANG peers — "
        "reflecting the Reality Labs drag and ad revenue cyclicality risk.  The Family of "
        "Apps business alone could be valued at 25-30x P/E (high-quality duopoly ad "
        "platform with Google).  Reality Labs operating losses (~$15B/yr) depress blended "
        "earnings.  FCF yield (~4-5%) is attractive vs peers."
    ),
    key_metrics=[
        "Daily Active People (DAP) across Family of Apps",
        "Average revenue per user (ARPU) — especially US/Europe vs Rest of World",
        "Ad impressions growth and average price per impression",
        "Reality Labs quarterly operating loss",
        "Free cash flow ($50-60B/yr range)",
        "Reels monetisation rate vs Feed (closing the gap)",
        "AI-driven ad conversion rate improvements (Advantage+ suite)",
    ],
    competitive_advantages=[
        "3.27B+ daily active users creates an unmatched audience scale for ad targeting",
        "Closed-loop e-commerce advertising (Shops + Instagram checkout) provides full "
        "attribution without third-party cookies",
        "Llama open-source AI strategy reduces frontier model costs while building ecosystem",
        "WhatsApp's 2B+ users are an undermonetised advertising and commerce platform",
    ],
    business_model_keywords=[
        "Facebook", "Instagram", "WhatsApp", "Reels", "Reality Labs", "Quest", "ATT",
        "Advantage+", "Llama", "Mark Zuckerberg", "DAP", "ARPU", "metaverse",
        "TikTok", "FTC",
    ],
    moat_type=["network_effect", "data_advantage", "scale_economy"],
    revenue_model="advertising",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="low",
    binary_risk_level="none",
))


# ── JPMorgan Chase (JPM) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="JPM",
    company_name="JPMorgan Chase & Co.",
    business_model=(
        "JPMorgan Chase is the largest US bank by assets (~$3.9T), operating across "
        "Consumer & Community Banking (retail deposits, credit cards, mortgages), "
        "Commercial Banking, the Corporate & Investment Bank (M&A, trading, capital "
        "markets), and Asset & Wealth Management."
    ),
    primary_revenue_drivers=[
        "Consumer & Community Banking (~45% of net revenue — deposit NII, credit cards, "
        "home lending, auto)",
        "Corporate & Investment Bank (~35% — fixed income trading, equity trading, "
        "investment banking fees, markets)",
        "Commercial Banking (~10%)",
        "Asset & Wealth Management (~10% — AUM-based fees)",
    ],
    recurring_revenue_sources=[
        "Net Interest Income (NII) — deposit spread revenue tied to Fed Funds rate",
        "Card Services interchange revenue and revolving credit spreads",
        "Asset Management fees on $3.6T AUM",
        "Commercial Banking revolving credit facility fees",
    ],
    rate_sensitivity_note=(
        "JPM is a direct beneficiary of rate increases: each 100 bps rise in the Fed "
        "Funds rate adds approximately $2-3B to annualised NII through deposit repricing "
        "(assets reprice faster than liabilities).  Conversely, rate cuts compress NII "
        "as deposit margins narrow.  JPM's deposit beta (how much of a rate cut passes "
        "through to depositors) is ~30-40%, meaning the bank retains 60-70% of rate "
        "benefit.  Investment banking (M&A, IPO) is inversely correlated with rates via "
        "deal financing costs — high rates suppress deal volume."
    ),
    inflation_pass_through=(
        "Banks benefit indirectly from inflation: higher nominal GDP and spending inflate "
        "card volumes and loan balances.  Wage inflation is JPM's largest cost (~50% "
        "of non-interest expense is compensation) and compresses efficiency ratio.  "
        "Credit card interchange is percentage-based, so inflation in purchase amounts "
        "raises fee revenue proportionally."
    ),
    recession_behavior=(
        "Recessions increase credit losses: JPM builds reserves (provision expense "
        "spikes) and net charge-offs rise.  In 2008-09, JPM proved resilient relative to "
        "peers — it was better-capitalised and acquired Bear Stearns and WaMu at distressed "
        "prices, demonstrating that essential banking infrastructure can gain share through "
        "crises.  JPM's CET1 ratio (~15%) provides a large capital buffer.  Investment "
        "banking revenue is more cyclical in credit-driven recessions (no M&A/IPO activity), "
        "but deposit and card fee revenues remain resilient as non-discretionary payment "
        "infrastructure."
    ),
    major_risks=[
        "Credit loss cycle: consumer credit card delinquencies rising from post-pandemic "
        "lows; subprime card segment is most vulnerable",
        "Basel III Endgame rules (initially proposed to raise RWA by ~25%) could "
        "force capital retention and reduce buyback capacity",
        "Commercial real estate (CRE) office loan losses — JPM has ~$15B exposure to "
        "office CRE, which faces structural vacancy headwinds",
        "Rate cut cycle compressing NII after peak-rate NII tailwind",
        "Competition from fintech/digital wallets (Cash App, PayPal, Chime) in consumer banking",
    ],
    valuation_style=(
        "Banks are valued on P/TBV (price-to-tangible book value) and P/E.  JPM trades "
        "at ~2.0-2.2x TBV (premium to peers due to superior ROTCE of ~17-19%) and "
        "~12-14x forward P/E.  ROTCE is the primary valuation driver — sustainably above "
        "15% justifies a >1.5x TBV multiple."
    ),
    key_metrics=[
        "Net Interest Income (NII) — absolute and management guidance",
        "Net Interest Margin (NIM)",
        "ROTCE (Return on Tangible Common Equity) target 17%+",
        "CET1 capital ratio (~15% actual vs ~12% regulatory minimum)",
        "Provision for credit losses / net charge-off rate",
        "Investment banking fee wallet share",
        "Efficiency ratio (expenses / revenue)",
    ],
    competitive_advantages=[
        "Scale: largest US bank by assets enables lowest-cost deposit funding",
        "Bulge-bracket investment bank with #1 or #2 market share in most product areas",
        "Jamie Dimon's 20-year track record of superior through-cycle capital allocation",
        "Chase consumer franchise: 80M US consumer households with strong cross-sell",
    ],
    business_model_keywords=[
        "NII", "NIM", "CET1", "ROTCE", "credit card", "deposit beta", "investment banking",
        "provision", "Basel III", "Jamie Dimon", "CRE", "trading revenue", "wealth management",
        "Fed Funds", "charge-off",
    ],
    moat_type=["scale_economy", "regulatory", "brand"],
    revenue_model="mixed",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Berkshire Hathaway (BRK.B) ────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="BRK.B",
    company_name="Berkshire Hathaway Inc.",
    business_model=(
        "Berkshire Hathaway is a diversified holding company that owns wholly-acquired "
        "operating businesses (BNSF railroad, GEICO insurance, Berkshire Hathaway Energy, "
        "manufacturing and retail subsidiaries) alongside a publicly-traded equity portfolio "
        "worth ~$300B+, generating float from the insurance underwriting operations to "
        "fund investments at near-zero cost."
    ),
    primary_revenue_drivers=[
        "Insurance (GEICO auto, BH Reinsurance, General Re) — float generation engine",
        "BNSF Railway (~$23B revenue) — bulk commodity and intermodal freight",
        "Berkshire Hathaway Energy (~$22B revenue) — regulated utilities and renewables",
        "Manufacturing (Precision Castparts, Lubrizol, IMC) and Retailing (McLane, Nebraska "
        "Furniture Mart, See's Candies)",
        "Equity portfolio (~$300B+, led by Apple, American Express, Coca-Cola, Bank of America)",
    ],
    recurring_revenue_sources=[
        "Insurance underwriting premiums (float: $165B+ of insurance float invested at BRK cost)",
        "BNSF railroad rate-adjusted contracts",
        "Utility rate-case-regulated returns at BH Energy",
        "Apple dividends (~$870M/yr based on position size)",
    ],
    rate_sensitivity_note=(
        "Berkshire's $165B insurance float earns more as short-term rates rise: "
        "Buffett confirmed each 100 bps rise adds ~$1.5-2B to annualised investment "
        "income from the float portfolio (invested primarily in T-bills and short-duration "
        "fixed income).  BH Energy's regulated utility subsidiaries have rate-case "
        "mechanisms that pass through cost of capital changes to customers over time.  "
        "The equity portfolio is not immune to valuation multiple compression in rate hikes, "
        "but BRK itself is valued at a smaller premium to book than pure-growth equities."
    ),
    inflation_pass_through=(
        "GEICO auto insurance premiums are reset at renewal, allowing inflation to pass "
        "through within 6-12 months (GEICO struggled with claims severity inflation in "
        "2022-23 before returning to underwriting profit).  BNSF rates are indexed to "
        "rail price indices.  See's Candies is the textbook example of pricing power — "
        "Buffett has raised box prices consistently above inflation for 50 years."
    ),
    recession_behavior=(
        "Berkshire is among the most recession-resilient companies: insurance float "
        "earns regardless of economic conditions, BNSF is a backbone infrastructure "
        "asset, and the equity portfolio is owned at low cost basis allowing multi-decade "
        "holding through volatility.  BRK's $150B+ cash/T-bill buffer allows Buffett to "
        "deploy capital at distressed prices during recessions (as in 2008-09 Goldman "
        "Sachs/GE preferred investments)."
    ),
    major_risks=[
        "GEICO competitive position vs Progressive (telematics-based pricing — GEICO was "
        "late to adopt usage-based insurance, ceding market share in 2021-23)",
        "BNSF long-term rail volumes declining in coal (secular trend) and dependent "
        "on recovery in agricultural exports",
        "BH Energy wildfire liability exposure in California and Oregon utilities",
        "Succession: Warren Buffett (94) and Charlie Munger (deceased 2023); Greg Abel "
        "designated successor but track record as capital allocator is unproven at BRK scale",
        "Apple concentration: Apple is ~45% of the equity portfolio; significant "
        "Apple drawdown would compress BRK's book value",
    ],
    valuation_style=(
        "BRK is valued at 1.4-1.6x P/B (price-to-book), which is the traditional Buffett "
        "yardstick — he has repurchased stock when trading below 1.2x book.  The 'look-"
        "through' earnings framework adds BRK's proportionate share of investee earnings "
        "to reported operating EPS.  Intrinsic value estimates range from 1.0x to 1.3x "
        "of the sum-of-parts: operating businesses (14-16x EBIT) + equity portfolio (mark-"
        "to-market) + excess cash."
    ),
    key_metrics=[
        "Float ($165B+) and investment income earned on float",
        "Operating earnings per share (Buffett's preferred metric, excludes investment gains)",
        "GEICO combined ratio (target <96% underwriting profit)",
        "BNSF operating ratio (expenses/revenue)",
        "Book value per share growth vs S&P 500 (the Buffett benchmark)",
        "Cash/T-bill balance as an indicator of deployment readiness",
        "Apple position % of equity portfolio",
    ],
    competitive_advantages=[
        "Insurance float: $165B+ of near-zero-cost investable capital that compounds "
        "over decades — the core Berkshire moat",
        "Warren Buffett's reputation lowers the cost of acquisitions (sellers accept "
        "lower prices for cultural fit and autonomy preservation)",
        "Decentralised operating model — acquired subsidiary CEOs are empowered with "
        "minimal interference, retaining entrepreneurial culture",
        "Balance-sheet strength ($150B+ cash) allows Berkshire to act as a 'financial "
        "institution of last resort' in market panics",
    ],
    business_model_keywords=[
        "GEICO", "BNSF", "float", "BH Energy", "Warren Buffett", "Greg Abel",
        "insurance underwriting", "See's Candies", "combined ratio", "book value",
        "Apple position", "operating earnings", "Precision Castparts", "T-bills",
    ],
))


# ── Visa (V) ──────────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="V",
    company_name="Visa Inc.",
    business_model=(
        "Visa operates a four-party payments network connecting 15,000+ financial "
        "institution clients (issuers and acquirers) with 130M+ merchant locations globally, "
        "charging a network service fee on $14T+ of annual payment volume without taking "
        "credit risk, as the actual lending is done by issuing banks."
    ),
    primary_revenue_drivers=[
        "Service revenues (~33% — assessed on payment volume in prior quarter)",
        "Data processing revenues (~40% — transactions processed on the VisaNet network)",
        "International transaction revenues (~22% — cross-border volume premium)",
        "Other revenues (~5% — licensing, consulting, value-added services)",
    ],
    recurring_revenue_sources=[
        "Payment volume-linked service fees (structurally grows with GDP and e-commerce shift)",
        "Transaction processing fees (each card swipe/dip/tap on VisaNet)",
        "Cross-border transaction premium (higher margin as travel/international trade recover)",
        "Visa Direct real-time money transfer fees (emerging P2P and B2B segment)",
    ],
    rate_sensitivity_note=(
        "Visa is modestly rate-sensitive via two channels: (1) DCF sensitivity — Visa "
        "trades at ~29-31x forward P/E, a premium multiple where 100 bps rate rise "
        "compresses fair value by ~3-4 turns; (2) consumer credit — higher rates slow "
        "consumer spending growth, mildly reducing payment volume momentum.  Visa does "
        "NOT take credit risk (that sits with issuing banks), so credit losses do not "
        "affect Visa's P&L directly.  Visa's $20B+ of long-term debt is at fixed rates "
        "across long maturities, limiting refinancing exposure."
    ),
    inflation_pass_through=(
        "Visa is a near-perfect inflation hedge: service fees are charged as a percentage "
        "of nominal payment volume, so higher prices (inflation) mechanically increase "
        "Visa's revenue even if real transaction volumes are flat.  A 5% inflation rate "
        "with flat real volumes adds ~5% to Visa's top line with minimal cost increase "
        "(network marginal cost is near zero)."
    ),
    recession_behavior=(
        "Consumer spending declines in recessions reduce payment volume.  In 2009, US "
        "payment volume fell ~4%.  Cross-border volumes collapse in recessions (travel "
        "stops).  However, Visa's shift from cash to card (penetration gain) partially "
        "offsets volume weakness — each recession accelerates digital payments adoption "
        "as businesses require contactless/online payment capability."
    ),
    major_risks=[
        "Merchant antitrust litigation over interchange fee levels (ongoing class actions "
        "in the US; potential forced fee reduction could reduce issuer incentive to issue "
        "Visa cards)",
        "Real-time payments infrastructure (FedNow, UPI in India, PIX in Brazil) bypassing "
        "the Visa network entirely for domestic consumer P2P and bill payments",
        "Regulatory fee caps (EU interchange cap at 0.3%, potential US legislation)",
        "Mastercard competition for issuer partnerships and merchant exclusivity",
        "Crypto/stablecoin payment rails (long-term secular disruption risk)",
    ],
    valuation_style=(
        "Visa is valued at ~29-31x forward P/E and ~25-28x EV/FCF, pricing in the "
        "structural shift from cash to digital payments (still ~50% of global consumer "
        "transactions in cash) as a long-duration secular growth driver.  The 'tollbooth' "
        "metaphor captures the asset-light model: near-zero marginal cost for each "
        "additional transaction processed on VisaNet."
    ),
    key_metrics=[
        "Payment volume (US and international, constant currency)",
        "Processed transactions (total count)",
        "Cross-border volume growth rate (highest margin segment)",
        "Net revenue growth rate",
        "Operating margin (~65-67%, highest of any S&P 500 company)",
        "Buyback yield (~3-4%/yr)",
        "Visa Direct transaction volume growth",
    ],
    competitive_advantages=[
        "VisaNet processes 65,000+ transactions per second with 99.999% uptime — "
        "no competing network matches this reliability at scale",
        "Network effect: more issuers → more cardholders → more merchants → more issuers",
        "Visa brand acceptance guarantee: consumers expect Visa cards to work everywhere",
        "Issuer incentives (rewards funding, marketing support) lock in multi-year agreements",
    ],
    business_model_keywords=[
        "VisaNet", "payment volume", "cross-border", "interchange", "issuer",
        "acquirer", "Visa Direct", "FedNow", "merchant", "Ryan McInerney",
        "cash displacement", "contactless", "network effect",
    ],
    moat_type=["network_effect", "brand", "scale_economy"],
    revenue_model="transaction_toll",
    switching_cost_level="very_high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Johnson & Johnson (JNJ) ───────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="JNJ",
    company_name="Johnson & Johnson",
    business_model=(
        "Johnson & Johnson is a global pharmaceutical and MedTech company following the "
        "2023 spin-off of Kenvue (consumer health).  The remaining two segments are "
        "Innovative Medicine (branded pharmaceuticals: oncology, immunology, cardiovascular) "
        "and MedTech (surgical robots, orthopaedics, vision care, electrophysiology)."
    ),
    primary_revenue_drivers=[
        "Innovative Medicine / Pharmaceuticals (~55% of revenue — Darzalex, Stelara, "
        "Erleada, Tremfya, Rybrevant)",
        "MedTech (~45% of revenue — Ottava surgical robot, Abiomed heart pumps, "
        "Depuy Synthes orthopaedics, Biosense Webster EP catheters)",
    ],
    recurring_revenue_sources=[
        "Ongoing pharmaceutical prescriptions (chronic disease treatments create "
        "multi-year patient adherence)",
        "MedTech consumables and procedure-driven recurring revenue (disposable catheters, "
        "orthopedic implant follow-on procedures)",
    ],
    rate_sensitivity_note=(
        "JNJ trades at a defensive ~15-17x forward P/E — modest rate sensitivity on "
        "DCF mechanics.  A 100 bps rate rise compresses fair value by ~1-2 turns. "
        "JNJ's ~$22B of long-term debt is largely at fixed rates with staggered maturities.  "
        "Healthcare spending is non-cyclical; hospital procedure volumes are driven by "
        "patient need, not interest rates.  JNJ's AAA credit rating (one of two remaining "
        "in the S&P 500) gives it lowest-cost access to debt markets regardless of rate level."
    ),
    inflation_pass_through=(
        "Branded pharmaceuticals have strong pricing power: biologics like Darzalex are "
        "priced at thousands of dollars per infusion with limited payer pushback on "
        "unmet medical needs.  MedTech pricing is under more pressure from hospital GPO "
        "contracts.  Stelara faced biosimilar pricing pressure from 2025 as exclusivity "
        "expired."
    ),
    recession_behavior=(
        "Highly defensive: cancer patients do not defer chemotherapy; rheumatoid arthritis "
        "patients do not stop biologics.  MedTech procedure volumes can be slightly "
        "deferred (elective orthopaedic) but not cancelled.  JNJ maintained dividend "
        "growth through every recession since 1963 (Dividend King with 62+ years of "
        "consecutive increases)."
    ),
    major_risks=[
        "Stelara (~$10B revenue in 2023) facing biosimilar competition beginning 2025 "
        "— represents the largest single patent cliff in JNJ history",
        "Talc litigation: $6.5B settlement (currently in legal proceedings) for talc-"
        "based baby powder asbestos claims; ongoing liability uncertainty",
        "Innovative Medicine pipeline concentration in BCMA/CD38 oncology space",
        "MedTech margin pressure from hospital budget cuts and GPO contract renegotiations",
        "Kenvue spin-off reduces consumer segment diversification",
    ],
    valuation_style=(
        "JNJ is valued as a defensive healthcare compounder: ~15-17x P/E with a "
        "2.8-3.2% dividend yield.  Drug pipeline is valued via probability-adjusted NPV "
        "of late-stage candidates.  Sum-of-parts: Pharma at ~15x EBIT (branded pharma "
        "multiple), MedTech at ~20x EBIT (premium for robot and EP catheter growth)."
    ),
    key_metrics=[
        "Darzalex sales and market share in multiple myeloma",
        "Stelara biosimilar erosion rate post-2025",
        "Innovative Medicine operational sales growth (ex-COVID vaccines)",
        "MedTech procedure volume recovery and Ottava robot launch milestones",
        "Pipeline: Phase 3 readouts (Rybrevant/Lazertinib MARIPOSA-2, Talquetamab)",
        "Free cash flow ($18-20B/yr)",
        "Dividend growth track record (62 consecutive years)",
    ],
    competitive_advantages=[
        "Best-in-class biologics manufacturing scale at Janssen sites across the world",
        "Biosense Webster Carto mapping system is the standard-of-care in cardiac EP "
        "ablation with high switching costs for electrophysiologists",
        "AAA credit rating provides lowest-cost capital for licensing/M&A deals",
        "Diversified oncology pipeline across CAR-T, bispecifics, and small molecules",
    ],
    business_model_keywords=[
        "Darzalex", "Stelara", "biosimilar", "Innovative Medicine", "MedTech",
        "Kenvue", "talc litigation", "Ottava", "Biosense Webster", "Janssen",
        "Erleada", "Tremfya", "oncology", "Dividend King", "Abiomed",
    ],
    moat_type=["patent", "brand", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="low",
))


# ── ExxonMobil (XOM) ─────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="XOM",
    company_name="ExxonMobil Corporation",
    business_model=(
        "ExxonMobil is an integrated oil & gas supermajor operating across Upstream "
        "(crude and natural gas production, led by the Permian Basin and Guyana assets), "
        "Product Solutions / Downstream (refining and marketing), and Chemical segments, "
        "with a growing Low Carbon Solutions unit targeting CCS and hydrogen."
    ),
    primary_revenue_drivers=[
        "Upstream E&P (~70% of earnings — Permian Basin, Guyana Stabroek block, LNG)",
        "Product Solutions / Downstream (~20% — refinery margins on crude-to-product spread)",
        "Chemical (~10% — polyethylene, polypropylene margins)",
        "Low Carbon Solutions / Other (<1%)",
    ],
    recurring_revenue_sources=[
        "Long-term LNG offtake agreements (Mozambique, Papua New Guinea LNG)",
        "Permian production royalties and working interest (low decline rate resource)",
        "Chemical long-term supply agreements with industrial customers",
    ],
    rate_sensitivity_note=(
        "XOM is valued primarily on commodity price (Brent/WTI crude) rather than interest "
        "rate.  A 100 bps rate rise has two competing effects: (1) compresses the DCF "
        "fair-value by 1-2 turns in P/E; (2) but higher rates often accompany inflation "
        "and stronger commodity prices, which lift earnings.  XOM's ~$40B of long-term "
        "debt is at fixed rates across long maturities; net debt is near zero after "
        "netting $30B+ in cash.  Capital-intensive projects require stable long-term "
        "financing; ExxonMobil's AAA-equivalent balance sheet insulates it from credit "
        "market tightness."
    ),
    inflation_pass_through=(
        "Oil and gas are commodity-priced in USD globally; inflation in costs (drilling, "
        "labor, steel) is a headwind but XOM offsets it through scale and Permian "
        "efficiency (breakeven ~$35/bbl WTI).  Refining crack spreads are independent "
        "of crude price, providing a downstream inflation hedge."
    ),
    recession_behavior=(
        "Oil demand is highly cyclical: global oil demand fell ~9 mb/d in 2020 (COVID), "
        "causing XOM's first annual loss since the 1930s and a dividend freeze.  However, "
        "XOM's low-cost Permian and Guyana assets are among the last barrels to be "
        "shut in on a cost basis.  Post-2020, XOM returned to dividend growth and added "
        "Pioneer Natural Resources ($60B acquisition) to deepen its Permian position."
    ),
    major_risks=[
        "Brent/WTI crude oil price decline below $60/bbl, which compresses Upstream "
        "profitability and strains the dividend commitment",
        "Long-term energy transition: EV adoption reducing gasoline demand in the 2030s",
        "Pioneer integration risk ($60B acquisition in 2024; cultural and operational "
        "integration of 10,000+ employees and 850K+ net Permian acres)",
        "Guyana project execution risk (Yellowtail and Hammerhead phases)",
        "Chemical segment margin compression from Asian (Chinese) polyethylene overcapacity",
    ],
    valuation_style=(
        "XOM is valued on EV/EBITDA (~6-8x), P/CF (price-to-cash-flow, ~9-11x), and "
        "dividend yield (~3.3-3.7%).  Commodity cyclicality means the market applies a "
        "through-cycle commodity price assumption ($65-75/bbl Brent) rather than spot "
        "price.  Sum-of-parts: Upstream assets (Permian + Guyana NAV), Downstream "
        "(replacement-cost refinery value), Chemical (specialty vs commodity premium)."
    ),
    key_metrics=[
        "Brent/WTI crude oil price (primary earnings driver)",
        "Upstream production volumes (mboe/d) — Permian growth target 1.5 mb/d by 2027",
        "Structural cost reduction vs 2019 baseline ($9B+ achieved)",
        "Refinery utilisation rate and crack spread",
        "Free cash flow breakeven oil price (~$45-50/bbl Brent)",
        "Pioneer integration synergy realisation ($2B/yr target)",
        "Dividend growth per share (41+ consecutive years)",
    ],
    competitive_advantages=[
        "Permian Basin acreage (1.4M+ net acres post-Pioneer) with $35/bbl breakeven — "
        "lowest-cost oil basin in the world",
        "Guyana Stabroek block: one of the largest oil discoveries of the decade "
        "(11B+ barrels recoverable) operated as JV with Hess/CNOOC",
        "Integrated model: Upstream barrel flows to ExxonMobil refineries at transfer "
        "pricing, capturing full margin stack",
        "Chemical integration: Permian gas provides feedstock advantage in ethane cracking",
    ],
    business_model_keywords=[
        "Permian Basin", "Guyana", "Stabroek", "Pioneer", "upstream", "Brent",
        "WTI", "crack spread", "LNG", "Darren Woods", "Low Carbon Solutions",
        "breakeven", "refinery", "Chemical", "dividend growth",
    ],
))


# ── Costco Wholesale (COST) ───────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="COST",
    company_name="Costco Wholesale Corporation",
    business_model=(
        "Costco operates membership-only warehouse clubs selling general merchandise, "
        "groceries, and private-label Kirkland Signature goods at thin margins (~2% net), "
        "with the membership fee (~$5B annually) constituting essentially all operating profit. "
        "The business is structurally defensive: members pre-pay for access, driving 92-93% "
        "North American and ~90% global renewal rates regardless of macroeconomic conditions."
    ),
    primary_revenue_drivers=[
        "Membership fees (~$5B/yr — the primary source of operating profit, near 100% gross margin)",
        "Merchandise sales (~$240B/yr — sold at near-cost, generating traffic and renewals)",
        "Kirkland Signature private label (~30% of sales, highest margin merchandise tier)",
        "E-commerce and ancillary services (gasoline, pharmacy, optical, travel)",
    ],
    recurring_revenue_sources=[
        "Annual warehouse membership fee — $65 (Gold Star) / $130 (Executive): ~92-93% "
        "North American renewal rate sustained across multiple economic cycles",
        "Executive membership fee surcharge (~45% of members, driving upgrade attach)",
        "Kirkland Signature repeat purchases: private-label brand loyalty creates predictable "
        "merchandise revenue distinct from commodity retail",
        "Costco Travel and ancillary services: members return 2-4x per week on average",
    ],
    rate_sensitivity_note=(
        "Costco's consumer is primarily middle-to-upper-income households for whom rate "
        "moves have limited spending impact.  Membership fee renewal is non-discretionary for "
        "loyal members.  Higher rates modestly increase inventory financing costs but Costco "
        "carries lean inventory (~29 days) and has no meaningful long-term debt relative to "
        "cash generation.  Real estate (owned warehouses) benefits from inflation over time."
    ),
    inflation_pass_through=(
        "Costco's buying scale and private label allow cost pass-through without losing members. "
        "Historically, Costco raised membership fees every 5-7 years (most recently in 2024) "
        "with near-zero impact on renewal rates — pricing power derived from value perception, "
        "not contractual lock-in.  Kirkland Signature absorbs supplier cost increases better "
        "than branded equivalents."
    ),
    recession_behavior=(
        "Highly recession-resilient and often counter-cyclical: members trade down from "
        "specialty grocers and premium retailers to Costco bulk buying during downturns. "
        "Membership renewal rates remained above 90% through the 2008-09 financial crisis "
        "and COVID-19 disruption.  Consumer staples and essentials dominate the merchandise "
        "mix.  The treasure-hunt format sustains visit frequency even when spending per "
        "trip declines marginally."
    ),
    major_risks=[
        "Membership fee hike cadence risk — fee increases every 5-7 years are priced into "
        "the stock; any delay compresses earnings growth vs expectations",
        "E-commerce competition (Amazon, Walmart) eroding discretionary non-food categories",
        "International expansion execution risk (higher shrink, lower renewal rates outside "
        "North America historically)",
        "Real estate concentration (large-format warehouses constrain format flexibility)",
        "Valuation premium: Costco trades at 45-55x P/E — any deceleration in comparable "
        "store sales or fee income reprices the stock sharply",
    ],
    valuation_style=(
        "Costco is valued as a high-quality compounder on P/E (45-55x) and EV/EBITDA (~35x), "
        "pricing continued mid-single-digit SSS growth and periodic membership fee increases. "
        "The market pays a structural premium for the business model's predictability and "
        "recession resilience.  Durable compounders of this quality rarely offer margin of safety "
        "on a traditional DCF — the multiple reflects the scarcity of this business model quality."
    ),
    key_metrics=[
        "Comparable store sales growth (Americas, International)",
        "Membership renewal rate (North America, International)",
        "New warehouse openings (and payback period)",
        "E-commerce penetration and growth",
        "Membership fee income growth",
        "Kirkland Signature as % of net sales",
        "Gross margin % (merchandise only, ex-membership)",
    ],
    competitive_advantages=[
        "Membership model creates pre-paid customer relationship and near-100% margin fee income — "
        "economic alignment between Costco's success and member satisfaction",
        "Kirkland Signature private label: #1 consumer packaged goods brand by revenue in the US, "
        "commanding premium to national brands at Costco-level prices",
        "Scale-driven buying power: 300M+ members globally enable negotiated pricing below "
        "any competing retailer in most categories",
        "Physical warehouse format generates mission-critical treasure-hunt traffic frequency "
        "that no digital substitute replicates",
        "Institutional trust and member loyalty: Costco NPS is among the highest of any retailer; "
        "membership churn is structurally low regardless of macro environment",
    ],
    business_model_keywords=[
        "membership fee", "renewal rate", "Kirkland Signature", "warehouse", "comparable store",
        "executive membership", "treasure hunt", "bulk buying", "private label",
        "membership income", "ancillary", "gasoline", "e-commerce penetration",
    ],
    moat_type=["brand", "switching_cost", "scale_economy"],
    revenue_model="membership",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── ASML Holding (ASML) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="ASML",
    company_name="ASML Holding N.V.",
    business_model=(
        "ASML is the sole supplier of extreme ultraviolet (EUV) lithography machines — "
        "equipment that semiconductor manufacturers (TSMC, Samsung, Intel) must use to "
        "fabricate leading-edge chips at 7nm and below.  ASML also makes deep ultraviolet "
        "(DUV) immersion systems, used at mature nodes.  The installed base of ~5,000+ "
        "systems generates a high-margin recurring service revenue stream independent of "
        "new system shipments."
    ),
    primary_revenue_drivers=[
        "EUV system sales (~€30,000–€40,000 per system, High-NA EUV at ~€300M+ per unit) — "
        "~50% of revenue at leading-edge",
        "DUV (deep ultraviolet) system sales — mature and advanced nodes, China exposure",
        "Installed Base Management (service and upgrades) — ~40% gross margin, predictable",
        "Metrology and inspection tools (HMI / Hermes Microvision)",
    ],
    recurring_revenue_sources=[
        "Installed Base Management (IBM) service contracts: multi-year maintenance and "
        "field-service agreements across 5,000+ installed systems — recurring, high-margin",
        "EUV refurbishment and upgrade revenue: existing EUV systems upgraded to newer "
        "optical generations, extending revenue without new system sale",
        "Reticle (photomask) inspection revenue via HMI subsidiary",
        "Application software licenses for lithography process optimization",
    ],
    rate_sensitivity_note=(
        "ASML trades at 25-35x forward P/E — long-duration cash flows make it modestly "
        "rate-sensitive.  A 100 bps rate rise compresses fair value by ~3-5 turns.  ASML's "
        "balance sheet is conservative with €4B+ net cash.  Semiconductor CapEx cycles (which "
        "drive ASML orders) are driven by technology roadmap and memory cycle, not interest rates.  "
        "Rate sensitivity is primarily a valuation/DCF effect, not a demand effect."
    ),
    inflation_pass_through=(
        "Strong pricing power: ASML has no competitor for EUV — customers cannot substitute. "
        "High-NA EUV pricing is set by ASML on a cost-plus basis with monopoly premium. "
        "Service contract pricing inflates annually.  DUV faces more competitive pressure "
        "from Nikon/Canon at mature nodes but remains dominant at leading edge."
    ),
    recession_behavior=(
        "Semiconductor CapEx is cyclical: DRAM and NAND fabs defer orders during inventory "
        "corrections, as occurred in 2023.  However, ASML's multi-year order backlog "
        "(€40B+ at peak) and long system lead times dampen the cycle impact.  Logic CapEx "
        "from TSMC, Samsung, and Intel for leading-edge EUV is more secular than memory. "
        "Service revenue is resilient regardless of new system demand — installed systems "
        "require maintenance to continue running."
    ),
    major_risks=[
        "China export controls: Dutch/US government EUV and advanced DUV export restrictions "
        "permanently removed China as a leading-edge customer (was ~15% of revenue in 2023)",
        "Semiconductor CapEx cycle: customer (TSMC, Samsung, Intel) order cuts during "
        "inventory correction directly reduce ASML system shipments with 12-18 month lag",
        "Technology risk: High-NA EUV ramp slower or more expensive than guided",
        "Customer concentration: top 3 customers (TSMC, Samsung, Intel) represent ~80% of revenue",
        "Geopolitical Taiwan risk: TSMC is ASML's largest customer; Taiwan Strait conflict "
        "would disrupt semiconductor supply chain fundamentally",
    ],
    valuation_style=(
        "ASML is valued as a technology compounder with monopoly characteristics: "
        "25-35x forward P/E and 25-30x EV/EBITDA, pricing the continued EUV TAM expansion "
        "through Moore's Law progression and High-NA transition.  The monopoly in EUV "
        "justifies a structural premium above semiconductor equipment peers."
    ),
    key_metrics=[
        "EUV system shipments (units per quarter)",
        "Installed Base Management (IBM) revenue and margins",
        "Order book / backlog (€B)",
        "High-NA EUV shipment cadence and margin ramp",
        "Gross margin % (system vs service mix matters)",
        "China DUV revenue (post export controls)",
        "TSMC 3nm and 2nm ramp timing",
    ],
    competitive_advantages=[
        "EUV monopoly: ASML is the only company in the world that can manufacture EUV "
        "lithography systems — 20+ years of R&D and €6B+ invested to reach this position",
        "Installed base lock-in: 5,000+ systems cannot be replaced with competitor equipment; "
        "service and upgrade revenue is captive",
        "High-NA EUV: next-generation technology also being developed exclusively by ASML, "
        "extending the monopoly for another decade",
        "Ecosystem dependencies: the entire semiconductor supply chain (photoresist makers, "
        "reticle shops, process equipment makers) is built around ASML specifications",
    ],
    business_model_keywords=[
        "EUV", "DUV", "High-NA", "lithography", "installed base", "TSMC", "Samsung",
        "Intel", "IBM revenue", "service", "backlog", "Moore's Law", "China export",
        "semiconductor CapEx", "Nikon", "photomask",
    ],
    moat_type=["natural_monopoly", "patent"],
    revenue_model="licensing",
    switching_cost_level="very_high",
    customer_concentration="concentrated",
    capital_intensity="capital_intensive",
    earnings_cyclicality="moderate",
    narrative_dependence="low",
    binary_risk_level="none",
))


# ── Palantir Technologies (PLTR) ───────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="PLTR",
    company_name="Palantir Technologies Inc.",
    business_model=(
        "Palantir sells data analytics, AI, and decision-intelligence software platforms: "
        "Gotham (US government and intelligence agencies), Foundry (commercial enterprise "
        "data integration), and AIP (AI Platform, launched 2023, integrating large language "
        "models into enterprise workflows).  Revenue is recognized on multi-year software "
        "contracts, with government work representing ~55% and commercial ~45% of revenue. "
        "The company reached GAAP profitability in 2023 for the first time."
    ),
    primary_revenue_drivers=[
        "US Government (intelligence, defense) — Gotham contracts, high margin, "
        "long-duration (~55-60% of total revenue)",
        "US Commercial (AIP bootcamps, Foundry enterprise) — fastest-growing segment, "
        "customer acquisition through 'bootcamp' model",
        "International Government — allies and non-US governments, lower growth",
        "International Commercial — smaller, slower, less strategic",
    ],
    recurring_revenue_sources=[
        "Multi-year government software contracts (often 3-5 year commitments with JEDI, "
        "Army Vantage, and classified programs) — provides revenue visibility",
        "Foundry enterprise SaaS renewals and seat expansions",
        "AIP commercial bootcamp conversions to multi-year Foundry/AIP licenses",
    ],
    rate_sensitivity_note=(
        "PLTR trades at 60-100x forward revenue and 300-400x trailing GAAP P/E — extreme "
        "long-duration valuation makes it highly rate-sensitive.  A 100 bps rate rise "
        "compresses the implied fair value by 15-25% in DCF models.  PLTR has no debt and "
        "significant cash, so direct rate impact on financials is minimal — the sensitivity "
        "is entirely valuation multiple compression."
    ),
    inflation_pass_through=(
        "Limited pricing power at current scale: government contracts are typically fixed-price "
        "or cost-plus, and commercial contracts are negotiated on a per-customer basis. "
        "AIP represents a premium over Foundry pricing but is still early in commercial adoption."
    ),
    recession_behavior=(
        "Government contracts are relatively recession-resistant — US defense and intelligence "
        "spending is bipartisan and counter-cyclical.  Commercial adoption of Foundry/AIP "
        "may slow as enterprises defer IT CapEx.  PLTR's commercial customer count is still "
        "small and early-stage, creating adoption risk if enterprise budgets tighten.  "
        "The stock is highly speculative during recessions given its extreme multiple."
    ),
    major_risks=[
        "Commercial AIP adoption pace: the entire re-rating thesis depends on AIP driving "
        "a step-change in US commercial customer count — still in early-stage adoption "
        "with limited evidence of enterprise-wide deployments at scale",
        "Valuation: 60-100x revenue prices in a decade of hyper-growth; any deceleration "
        "in AIP adoption reprices the stock sharply",
        "US Government contract concentration: losing a major classified program "
        "would remove a large, predictable revenue block",
        "Competition from hyperscalers (Microsoft Copilot, Amazon Bedrock, Google Vertex) "
        "offering similar AI workflow capabilities at lower cost",
        "Leadership concentration: Peter Thiel and Alex Karp are central to the government "
        "relationship network; management continuity is existential to the franchise",
    ],
    valuation_style=(
        "PLTR is valued on a revenue multiple (EV/Revenue 30-60x) with a premium embedded "
        "for AIP commercial adoption driving software-like margins at scale.  The commercial "
        "segment growth rate and bootcamp conversion rate are the key valuation drivers.  "
        "On any normalized earnings basis, the stock carries an AI-expansion growth premium — "
        "most of the value reflects the scenario where AIP becomes a category-defining "
        "enterprise software category."
    ),
    key_metrics=[
        "US Commercial customer count and growth rate",
        "Net dollar retention (NRR) by segment",
        "AIP bootcamp conversion rate to multi-year deals",
        "US Government contract backlog and renewal rate",
        "Total remaining deal value (TRV)",
        "Rule of 40 (growth rate + GAAP operating margin)",
        "Stock-based compensation as % of revenue (historically very high)",
    ],
    competitive_advantages=[
        "Forward-deployed engineers: Palantir embeds software engineers at customer sites, "
        "creating deep integration and high switching costs once Foundry is in production",
        "Government trust network: classified clearances and long-term intelligence "
        "relationships are not easily replicable by hyperscalers",
        "Ontology-based data model: Foundry's ontology layer creates proprietary data "
        "structures that are expensive to migrate away from",
    ],
    business_model_keywords=[
        "Gotham", "Foundry", "AIP", "bootcamp", "US Government", "US Commercial",
        "intelligence", "defense", "ontology", "forward-deployed", "Peter Thiel",
        "Alex Karp", "GAAP profitability", "net dollar retention", "TRV", "bootcamp conversion",
    ],
    moat_type=["data_advantage"],
    revenue_model="project_contract",
    switching_cost_level="moderate",
    customer_concentration="concentrated",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="high",
    binary_risk_level="low",
))


# ── Broadcom (AVGO) ────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AVGO",
    company_name="Broadcom Inc.",
    business_model=(
        "Broadcom designs high-performance semiconductors and infrastructure software. "
        "The semiconductor segment (~75% of revenue) supplies custom AI ASICs for "
        "hyperscalers (Google TPU, Meta MTIA), networking silicon (Ethernet switching: "
        "Tomahawk, Trident, Jericho; PCIe/SAS storage controllers; wireless combo chips "
        "for Apple iPhone), and Fibre Channel HBAs.  The infrastructure software segment "
        "(~25% of revenue post-VMware acquisition) provides virtualisation (VMware vSphere, "
        "NSX), mainframe tools (CA Technologies), and security (Symantec).  Capital "
        "allocation is dividend-focused with moderate buybacks — NOT a $90B buyback program."
    ),
    primary_revenue_drivers=[
        "Custom AI ASIC / XPU for hyperscalers (~25-30% of semiconductor revenue, "
        "growing fastest — Google TPU v5/v6, Meta MTIA Gen 2, Apple neural engines)",
        "Networking switching silicon — Tomahawk (merchant Ethernet), Trident (enterprise), "
        "Jericho2/3 (service-provider scale-up/out routing) (~20% of semi revenue)",
        "VMware virtualisation and cloud infrastructure software (~25% of total revenue, "
        "high recurring subscription margin post-2024 conversion)",
        "Wireless connectivity chips for Apple iPhone (WiFi, Bluetooth, UWB combo) "
        "(~15% of semi revenue — Apple concentration risk)",
        "Storage controllers, PCIe switches, Fibre Channel HBAs (~10-15% of semi revenue)",
    ],
    recurring_revenue_sources=[
        "VMware subscription conversions (vSphere+, vSAN+, VCF bundles) — multi-year "
        "enterprise contracts, >90% renewal rates historically",
        "CA Technologies mainframe tool subscriptions (highly sticky — decades of "
        "installed base with high switching costs)",
        "Custom ASIC multi-year co-design contracts with hyperscalers (Google, Meta, Apple) "
        "— typically 3-5 year design engagements with volume commitments",
        "Symantec enterprise security software subscriptions",
    ],
    rate_sensitivity_note=(
        "Broadcom trades at ~22-28x forward P/E (semiconductor + software blend).  "
        "A 100 bps rate move compresses the multiple by roughly 2-3 turns via DCF "
        "mechanics.  AVGO carries significant acquisition debt (~$70-75B post-VMware "
        "2023 acquisition) — higher rates directly increase interest expense and reduce "
        "FCF available for deleveraging and dividends.  Unlike Apple, Broadcom does NOT "
        "have a fortress net-cash position; it is a net-debt company actively deleveraging. "
        "The dividend (~3-4% yield at typical price) is supported by strong FCF (~$18-20B/yr) "
        "but is NOT backed by a $90B buyback — Broadcom's capital return is dividend-first, "
        "with buybacks playing a secondary and smaller role."
    ),
    inflation_pass_through=(
        "Moderate: custom ASIC contracts are typically cost-plus or priced with margin "
        "protection, and switching costs are high (hyperscaler TPU co-design takes 18-24 "
        "months — customers cannot easily switch silicon vendors mid-cycle).  Merchant "
        "switching silicon faces more pricing pressure from Marvell and Intel.  VMware "
        "pricing has faced pushback from enterprise customers resisting the perpetual-to- "
        "subscription conversion, which creates near-term churn risk."
    ),
    recession_behavior=(
        "Data-center spending (AI infrastructure) has been counter-cyclical through "
        "recent slowdowns — hyperscaler AI CapEx continued growing even as enterprise "
        "IT spend contracted.  Enterprise VMware licenses are sticky but large-enterprise "
        "budget freezes could slow new vSphere deployments.  iPhone wireless chips are "
        "consumer-demand sensitive — Apple iPhone unit declines directly pressure "
        "AVGO's wireless semiconductor revenue.  FCF is robust (~$18-20B/yr) and "
        "supports deleveraging and dividends through downturns."
    ),
    major_risks=[
        "Custom ASIC concentration: Google (~20% of semiconductor revenue) and Meta "
        "co-design hyperscaler XPU chips.  If hyperscalers in-source ASIC design "
        "(as Amazon with Trainium/Inferentia) or consolidate on fewer vendors, AVGO "
        "loses a high-margin, high-growth revenue stream",
        "Apple iPhone wireless chip concentration (~15% of semi revenue): Apple is "
        "actively designing its own wireless chips in-house — AVGO faces a 3-5yr risk "
        "of losing the Apple wireless socket, potentially a ~$4-5B revenue headwind",
        "VMware integration execution: converting VMware perpetual licenses to "
        "subscriptions is creating enterprise pushback; churn from price-sensitive "
        "customers could slow software revenue ramp",
        "M&A integration debt burden: post-VMware acquisition debt of ~$70-75B "
        "requires sustained deleveraging; a revenue shortfall would constrain "
        "both deleveraging and dividend sustainability",
        "Nvidia GPU competition: Nvidia's networking portfolio (InfiniBand, Spectrum-X "
        "Ethernet) competes with Broadcom's Tomahawk/Jericho in AI data-center fabric",
    ],
    valuation_style=(
        "AVGO is valued on a blended semiconductor + software P/E (~22-28x forward), "
        "with the software segment (VMware, CA, Symantec) often valued at a SaaS-like "
        "multiple and the semiconductor segment at a cyclical hardware multiple.  "
        "Sum-of-parts: semiconductor at ~18-22x EV/EBITDA, software at ~20-25x EV/EBITDA. "
        "Key re-rating catalyst: AI ASIC revenue inflecting above $10B quarterly run rate, "
        "proving hyperscaler custom silicon is a sustainable, growing moat.  "
        "De-rating risk: hyperscaler in-sourcing or Apple wireless socket loss."
    ),
    key_metrics=[
        "AI ASIC / custom XPU quarterly revenue run rate (primary AI inflection signal)",
        "VMware subscription ARR and renewal rate (software segment health)",
        "Net leverage ratio (debt/EBITDA) and deleveraging trajectory",
        "Free cash flow conversion (FCF/EBITDA) — supports dividend and debt repayment",
        "Jericho and Tomahawk Ethernet switch design wins at hyperscalers",
        "Apple wireless chip socket retention vs. in-house Apple chip timeline",
        "Semiconductor revenue ex-Apple (shows structural AI/data-center growth)",
        "Total semiconductor revenue: data-center vs. broadband vs. networking split",
    ],
    competitive_advantages=[
        "Custom ASIC co-design moat: multi-year TPU/XPU co-design partnerships with "
        "Google and Meta create 2-3 year lead time advantage; re-sourcing would require "
        "full silicon re-spin at 18-24 month cycle time",
        "Jericho2/3 networking silicon: the only merchant silicon capable of line-rate "
        "400G/800G routing at service-provider scale with sub-1 microsecond latency — "
        "Cisco and Juniper both rely on Jericho for service-provider routing",
        "VMware virtualisation installed base: 90%+ of Fortune 1000 run VMware; "
        "switching to KVM/OpenStack requires 12-24 months of re-architecture",
        "Patent portfolio and standards participation: Broadcom co-chairs PCIe, "
        "Ethernet, and Fibre Channel standards bodies — creates technology leverage "
        "over competitors and customers",
    ],
    business_model_keywords=[
        "custom ASIC", "XPU", "TPU", "AI ASIC", "Jericho", "Tomahawk", "Trident",
        "VMware", "vSphere", "VCF", "networking silicon", "Ethernet switching",
        "hyperscaler", "PCIe", "Fibre Channel", "wireless combo chip",
        "CA Technologies", "Symantec", "deleveraging", "FCF", "subscription conversion",
    ],
    moat_type=["switching_cost", "scale_economy", "patent"],
    revenue_model="mixed",
    switching_cost_level="very_high",
    customer_concentration="concentrated",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── AMD (AMD) ─────────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AMD",
    company_name="Advanced Micro Devices, Inc.",
    business_model=(
        "AMD is a fabless semiconductor company that designs high-performance CPUs "
        "(EPYC server, Ryzen consumer), GPUs and AI accelerators (Instinct MI300/MI325 "
        "series, Radeon gaming), and adaptive compute (Xilinx FPGAs/Versal). All "
        "manufacturing is outsourced to TSMC. AMD competes with Intel in x86 CPUs and "
        "NVIDIA in GPUs/AI accelerators."
    ),
    primary_revenue_drivers=[
        "Data Center (~55% of revenue): EPYC server CPUs + Instinct/MI300 AI accelerators",
        "Client (~25%): Ryzen consumer and mobile CPUs",
        "Gaming (~10%): Radeon GPUs + semi-custom (PlayStation/Xbox SoCs)",
        "Embedded (~10%): Xilinx FPGAs, Versal adaptive SoCs (Xilinx acquisition 2022)",
    ],
    recurring_revenue_sources=[
        "Semi-custom SoC royalties from platform agreements "
        "(PlayStation 5, Xbox Series X — 7-10 year life cycles with committed volumes)",
        "Hyperscaler EPYC CPU deployment through committed server refresh "
        "cycles with Azure, AWS, and Google Cloud",
    ],
    rate_sensitivity_note=(
        "AMD is valued as a high-growth semiconductor play (~40-60x forward P/E at peak "
        "AI cycle). Rate rises compress the growth multiple disproportionately vs. mature "
        "chip peers. However AMD's near-term EPS revisions are driven more by EPYC share "
        "gains vs Intel and MI300X AI ramp than by macro rate cycles."
    ),
    inflation_pass_through=(
        "AMD has moderate pricing power. EPYC CPUs command a price premium vs Intel Xeon "
        "on performance-per-watt, allowing ASP increases. Consumer Ryzen pricing is more "
        "competitive. TSMC wafer cost increases (CHIPS Act surcharges) compress gross "
        "margins if not offset by mix shift to higher-margin data center products."
    ),
    recession_behavior=(
        "AMD has uneven performance across segments in downturns. Data Center (EPYC + "
        "Instinct) is relatively resilient as hyperscaler AI investment continues on a "
        "multi-year build-out. Client (Ryzen) and Gaming (Radeon, semi-custom) are "
        "consumer-sensitive and can decline meaningfully in severe downturns. The "
        "overall business has cyclical exposure to semiconductor demand inventory cycles."
    ),
    major_risks=[
        "NVIDIA CUDA ecosystem lock-in: ROCm (AMD's CUDA alternative) is years behind "
        "in software maturity and ISV support — limits MI300X adoption beyond inference",
        "Intel competitive response: Arrow Lake and Clearwater Forest server CPUs target "
        "AMD EPYC market share gains; Granite Rapids already competitive at high core counts",
        "China revenue (~25% of total): Instinct AI chips face U.S. export controls (MI308 "
        "downclocked for China compliance); revenue at risk if restrictions tighten",
        "TSMC single-source concentration: all advanced node production at TSMC N3/N4/N5; "
        "any TSMC capacity disruption (geopolitical, natural disaster) directly impacts AMD",
        "AI accelerator market concentration: over 80% of AI GPU market controlled by "
        "NVIDIA; AMD is the credible alternative but still single-digit market share",
    ],
    valuation_style=(
        "AMD trades on a forward EV/Sales and P/E basis relative to the AI accelerator "
        "market opportunity. The market prices AMD as 'the credible NVIDIA alternative' "
        "at a discount (~30-40x forward P/E vs NVIDIA ~50-60x). Key re-rating catalysts: "
        "MI300X/MI325X quarterly revenue run-rate surpassing $5-8B (proving AI GPU "
        "franchise), EPYC server CPU market share sustainably above 30%. De-rating risk: "
        "NVIDIA Blackwell supply normalization squeezes MI300X window; ROCm software "
        "adoption stalls; China export control escalation."
    ),
    key_metrics=[
        "Data Center revenue quarterly run-rate (EPYC + Instinct combined)",
        "MI300X/Instinct AI accelerator quarterly shipments and ASP vs H100/H200",
        "EPYC server CPU market share (target: 30%+ vs Intel Xeon)",
        "Gross margin trajectory: mix shift from client/gaming to data center",
        "ROCm software adoption: PyTorch/JAX support, ISV certifications",
        "China Data Center revenue (export control exposure)",
        "Embedded (Xilinx) revenue recovery from inventory correction",
    ],
    competitive_advantages=[
        "EPYC performance-per-watt leadership: Zen 4/5 architecture outperforms Intel "
        "Xeon on TCO metrics, driving hyperscaler adoption (AWS Graviton alternative, "
        "Azure, Google Cloud EPYC deployments)",
        "MI300X memory bandwidth advantage: 192GB HBM3 unified memory makes MI300X the "
        "best-in-class accelerator for large-model inference (fits entire LLaMA-70B in "
        "a single GPU without fragmentation — NVIDIA H100 requires 2+ GPUs)",
        "Lisa Su execution track record: turned AMD from near-bankruptcy (2015) to #2 "
        "semiconductor company by market cap via disciplined product roadmap execution",
    ],
    business_model_keywords=[
        "EPYC", "MI300", "Instinct", "Ryzen", "ROCm", "CDNA", "RDNA",
        "Zen 5", "Xilinx", "Versal", "HBM", "inference", "data center GPU",
        "server CPU", "semi-custom", "Lisa Su", "fabless",
    ],
    moat_type=["data_advantage", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="moderate",
    capital_intensity="moderate",
    earnings_cyclicality="highly_cyclical",
    narrative_dependence="moderate",
    binary_risk_level="none",
))

# ── UnitedHealth Group (UNH) ─────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="UNH",
    company_name="UnitedHealth Group Incorporated",
    business_model=(
        "UnitedHealth Group operates through two segments: UnitedHealthcare (health "
        "insurance — Medicare Advantage, Medicaid, commercial employer plans) and Optum "
        "(health services — OptumHealth care delivery, OptumRx pharmacy benefit management, "
        "OptumInsight data/analytics). Optum now contributes ~55% of operating earnings "
        "and is the primary margin-expansion engine."
    ),
    primary_revenue_drivers=[
        "UnitedHealthcare Insurance Premiums (~$280B revenue): Medicare Advantage "
        "(~50% of UHC membership), Medicaid, commercial employer/individual plans",
        "Optum Health (~$100B): care delivery clinics, surgery centers, physician groups",
        "OptumRx (~$120B): pharmacy benefit management — 3rd largest PBM in U.S.",
        "OptumInsight (~$15B): healthcare data analytics, technology services, consulting",
    ],
    recurring_revenue_sources=[
        "Medicare Advantage premium payments (CMS-contracted, annual rate-setting)",
        "Employer group insurance premiums (annual contract renewals, ~85% retention)",
        "Medicaid managed care contracts (state-contracted, multi-year)",
        "OptumRx long-term PBM contracts with employers and health plans",
    ],
    rate_sensitivity_note=(
        "UNH is relatively rate-insensitive on the revenue side — insurance premiums "
        "and PBM contracts are set annually via negotiation, not tied to interest rates. "
        "Higher rates modestly benefit UNH's investment income on its float (~$50B+ "
        "investment portfolio). A rate-rise environment is broadly neutral to mildly "
        "positive. Higher rates increase UNH's pension and benefit obligation discounting."
    ),
    inflation_pass_through=(
        "UNH has strong inflation pass-through via annual premium repricing. Medical cost "
        "inflation (pharmaceutical, labor, utilization) is embedded into next-year premium "
        "bids. The key risk is intra-year Medical Loss Ratio (MLR) spikes when actual costs "
        "exceed actuarial projections — UNH targets 83-86% MLR. GLP-1 drug cost inflation "
        "(Ozempic/Wegovy) is a current headwind not yet fully priced into premiums."
    ),
    recession_behavior=(
        "UNH is defensive in recessions. Medicare Advantage membership is recession-proof "
        "(demographic demand). Employer group plans can decline if unemployment rises "
        "(members lose employer coverage). Medicaid membership typically GROWS in recessions "
        "as income thresholds are met. Optum care delivery is relatively stable."
    ),
    major_risks=[
        "MLR normalization: post-COVID utilization suppression has reversed; medical cost "
        "trend above 6% threatens 2024-2025 EPS guidance if premiums under-priced",
        "CMS Medicare Advantage rate cuts: annual CMS rate-setting directly impacts "
        "MA premium revenue; 2024 CMS rate announcement below expectations caused ~15% "
        "stock decline — ongoing regulatory risk",
        "DOJ antitrust investigation: vertical integration of UnitedHealthcare + Optum "
        "Health (insurer owning care delivery) under DOJ scrutiny; Change Healthcare "
        "acquisition scrutiny set precedent",
        "Change Healthcare cyberattack (2024): $1.6B+ direct costs, reputational damage, "
        "cash flow disruption — raised concerns about IT infrastructure resilience",
        "Political/legislative risk: Medicare Advantage pricing reform, PBM transparency "
        "legislation (Pharmacy Benefit Manager Reform Act), drug pricing regulation",
        "GLP-1 drug cost surge: Ozempic, Wegovy, Mounjaro creating insurance cost "
        "inflation exceeding actuarial assumptions across plans",
    ],
    valuation_style=(
        "UNH trades at 18-22x forward P/E, a premium to managed care peers (CVS, CI, "
        "HUM) justified by Optum's high-margin health services mix and consistent 13-16% "
        "EPS CAGR. Key re-rating catalyst: MLR normalization proving actuarial accuracy, "
        "Optum revenue exceeding $200B (demonstrating vertical integration value). "
        "De-rating risk: sustained MLR above 86%, CMS MA rate reductions, DOJ breakup "
        "action. Sum-of-parts: UnitedHealthcare at ~12x earnings + Optum at ~22x earnings."
    ),
    key_metrics=[
        "Medical Loss Ratio (MLR): UHC consolidated target 83.0-86.0%",
        "STAR ratings: CMS quality ratings that determine Medicare Advantage bonus payments",
        "Optum operating earnings as % of UNH total (target >55%)",
        "Medicare Advantage membership growth (organic, not just via acquisitions)",
        "OptumRx scripts dispensed and PBM market share",
        "Days Claims Payable (DCP): balance sheet indicator of claims reserve adequacy",
        "Adjusted EPS guidance and medical cost trend per management guidance",
    ],
    competitive_advantages=[
        "Scale and data moat: UNH processes 1.8B+ claims annually — largest healthcare "
        "data asset in the U.S., enabling better risk adjustment and actuarial accuracy",
        "Optum vertical integration: owning care delivery (OptumHealth) + PBM (OptumRx) "
        "+ data (OptumInsight) creates cost savings vs competitors who outsource these",
        "Medicare Advantage STAR ratings: UNH consistently achieves 4+ STAR ratings "
        "which generate CMS bonus payments (~$4-8B annually) funding price competitive "
        "MA benefits — a reinforcing quality moat",
        "Employer group retention: ~90%+ annual employer renewal rate across large group "
        "plans; switching costs (claims history, network rebuilding) are high",
    ],
    business_model_keywords=[
        "Optum", "OptumRx", "OptumHealth", "OptumInsight",
        "Medicare Advantage", "Medicaid", "MLR", "medical loss ratio",
        "STAR rating", "PBM", "pharmacy benefit", "UnitedHealthcare",
        "Andrew Witty", "Change Healthcare", "GLP-1",
    ],
))

# ── Taiwan Semiconductor Manufacturing (TSM) ─────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="TSM",
    company_name="Taiwan Semiconductor Manufacturing Company Limited",
    business_model=(
        "TSMC is the world's largest pure-play semiconductor foundry — it manufactures "
        "chips designed by fabless customers (Apple, NVIDIA, AMD, Qualcomm, Broadcom) "
        "and does not sell its own branded products. Revenue = wafer volume × ASP. "
        "TSMC holds ~60% of global foundry market share and is the only company "
        "with commercially available N3 (3nm) and N2 (2nm) process nodes at scale."
    ),
    primary_revenue_drivers=[
        "Advanced nodes N3/N5/N7 (~60-65% of wafer revenue; highest ASP, >55% gross margin)",
        "Apple (~25% of revenue): sole supplier for A-series/M-series chips at N3",
        "HPC/AI segment (~50% of revenue): NVIDIA, AMD, Broadcom, Intel Foundry customers",
        "CoWoS advanced packaging (~$8-12B run-rate): HBM-on-substrate stacking for AI GPUs",
        "Mature nodes N28/N40/N65 (~35-40%): automotive, IoT, analog, lower-margin",
    ],
    recurring_revenue_sources=[
        "Apple long-term service contract for advanced node chip supply "
        "(A-series/M-series at N3 — annual renewal with committed wafer volumes)",
        "NVIDIA AI GPU wafer allocation agreements (H100/H200/Blackwell, "
        "12-18 month lead times with subscription-style capacity commitments)",
        "CoWoS advanced packaging pre-paid capacity reservations from hyperscalers",
        "Long-term NRE (non-recurring engineering) maintenance contracts "
        "for custom process development and process node co-engineering",
    ],
    rate_sensitivity_note=(
        "TSMC is a capital-intensive manufacturer with $40B+ annual capex. High interest "
        "rates increase the cost of debt financing for fab construction (Arizona, Japan, "
        "Germany fabs). TSMC's balance sheet carries significant long-term debt for "
        "international expansion. Rate rises also pressure the growth multiple on TSMC's "
        "Taiwan-listed ADR; as a high-capex industrial compounder it behaves like a "
        "growth infrastructure stock in rate-sensitive environments."
    ),
    inflation_pass_through=(
        "TSMC has strong long-run pricing power — it is the only N3/N2 supplier, giving "
        "customers no alternative. TSMC raised N3 wafer prices ~6% in 2023 and N5 prices "
        "~6% in 2022. However, pricing negotiations are annual and customers (Apple, "
        "NVIDIA) have leverage via volume concentration. Labor and energy inflation in "
        "Taiwan is modest; Arizona fab labor costs are 2-3x Taiwan equivalent."
    ),
    recession_behavior=(
        "TSMC has cyclical exposure through smartphone (Apple) and PC (AMD, Intel) end "
        "markets, which decline in recessions. However, AI/HPC demand has become a "
        "secular, resilient structural offset — hyperscaler AI capex is a multi-year "
        "build-out that is relatively recession-resistant. In 2022-2023 inventory "
        "correction, TSMC revenue declined ~15% then recovered strongly. Advanced node "
        "revenue is more resilient and mission-critical to customers than mature node "
        "revenue; no viable N3/N2 alternative exists, making TSMC essentially essential "
        "infrastructure for the global semiconductor industry."
    ),
    major_risks=[
        "Taiwan geopolitical risk: Taiwan Strait tensions or military conflict would "
        "directly threaten TSMC's primary manufacturing base (~90% of capacity in Taiwan); "
        "U.S./Netherlands export controls on EUV tools limit TSMC China expansion",
        "Arizona fab execution risk: TSMC Arizona N3 ramp delayed by 2+ years; labor "
        "costs 4-5x Taiwan equivalent; CHIPS Act subsidy uncertainty post-2024 election",
        "Customer concentration: Apple ~25% of revenue — iPhone unit volume directly "
        "impacts TSMC utilization; Apple in-sourcing risk for modem chips",
        "Samsung foundry competition: Samsung 3GAE process competes at advanced nodes "
        "for Qualcomm and Google Tensor chips; Intel 18A is a longer-term threat",
        "EUV equipment concentration: ASML is the sole EUV supplier; equipment delays "
        "or export restrictions on ASML tools constrain TSMC's advanced node ramp",
        "CoWoS capacity bottleneck: AI GPU demand is constrained by CoWoS packaging "
        "capacity shortfall — a positive demand signal but execution risk for ramp",
    ],
    valuation_style=(
        "TSMC trades at 18-25x forward P/E, premium to foundry peers (GlobalFoundries, "
        "Samsung) justified by advanced node monopoly and AI tailwind. Key re-rating "
        "catalysts: CoWoS capacity scaling to meet AI GPU demand, N2 volume ramp on "
        "schedule, Arizona fab proving cost competitiveness. De-rating risk: Apple "
        "guidance cut reducing Q4 wafer orders, geopolitical escalation in Taiwan Strait, "
        "CHIPS Act subsidy reduction. ADR premium to Taiwan shares reflects geopolitical "
        "discount; TSMC trades at a 20-30% discount to its 'deserved' multiple because "
        "of Taiwan risk overhang."
    ),
    key_metrics=[
        "Advanced node revenue mix (N3+N5+N7 as % of total wafer revenue)",
        "CoWoS advanced packaging quarterly revenue and capacity utilization",
        "Gross margin: target 53-55%+; Arizona dilution impact per management guidance",
        "Capex guidance ($38-42B annually): measures fab investment intensity",
        "AI/HPC revenue as % of total (structural growth driver vs smartphone cyclicality)",
        "N2 volume ramp timeline: key indicator of next-generation node execution",
        "TSMC Arizona fab utilization rate and cost-per-wafer vs Taiwan equivalent",
    ],
    competitive_advantages=[
        "Advanced node monopoly: TSMC is the only foundry producing N3 and N2 at "
        "commercial scale; Samsung and Intel alternatives are at least 1-2 generations "
        "behind on yield and throughput — customers cannot multi-source",
        "Customer-specific process tuning: TSMC co-develops process variants for Apple "
        "(TSMC A16), NVIDIA (CoWoS-S/L), and AMD (N3E) — creating deep switching costs "
        "as re-qualification at Samsung or Intel requires 12-24 months",
        "CoWoS advanced packaging monopoly: 80%+ of AI GPU CoWoS packaging for "
        "NVIDIA/AMD done at TSMC; this is a new strategic position in the AI value chain "
        "beyond pure wafer manufacturing",
        "Manufacturing yield leadership: TSMC's N3 yield is materially higher than "
        "Samsung 3GAE, translating to better chip economics for customers — a "
        "self-reinforcing moat as customers stay for better economics",
    ],
    business_model_keywords=[
        "foundry", "N3", "N5", "N2", "CoWoS", "advanced packaging",
        "wafer", "TSMC", "Taiwan", "Apple", "NVIDIA", "AMD",
        "fabless", "HBM", "CHIPS Act", "Arizona", "CC Wei",
        "advanced node", "EUV", "ASML",
    ],
    moat_type=["natural_monopoly", "scale_economy", "patent"],
    revenue_model="licensing",
    switching_cost_level="very_high",
    customer_concentration="concentrated",
    capital_intensity="capital_intensive",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="low",
))


# ── Goldman Sachs (GS) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="GS",
    company_name="The Goldman Sachs Group, Inc.",
    business_model=(
        "Goldman Sachs is a global investment banking and financial services firm "
        "operating across four segments: Global Banking & Markets (investment banking "
        "advisory/underwriting + FICC and equities trading), Asset & Wealth Management "
        "(AWM, ~$2.8T AUS), Platform Solutions (consumer cards and transaction banking), "
        "and the legacy Marcus consumer banking business (being wound down). Revenue is "
        "highly variable, driven by deal activity, market volatility, and AUM flows."
    ),
    primary_revenue_drivers=[
        "FICC (Fixed Income, Currencies & Commodities) trading (~25-30% of revenue) — "
        "rates, credit, FX, commodities intermediation; highest in volatile markets",
        "Equities trading (~20%) — prime brokerage, derivatives, cash equities",
        "Investment Banking fees (~15-20%) — M&A advisory, ECM/DCM underwriting; "
        "highly cyclical with deal activity",
        "Asset & Wealth Management (~25%) — management fees on $2.8T+ AUS, incentive "
        "fees from alternatives (private equity, hedge fund, real estate)",
        "Platform Solutions / Transaction Banking (~5-10%) — growing transaction "
        "banking and institutional cash management",
    ],
    recurring_revenue_sources=[
        "AWM management fees (~$2.8T AUS × ~0.5% blended fee = ~$14B recurring)",
        "Transaction banking float and service fees",
        "Prime brokerage financing revenue (relatively stable vs trading P&L)",
        "Carried interest and incentive fees from alternatives (multi-year lockup funds)",
    ],
    rate_sensitivity_note=(
        "GS benefits from higher rates via two channels: (1) FICC trading activity "
        "increases when rates and credit spreads are volatile; (2) higher rates increase "
        "net interest income on the balance sheet and client cash balances. However, higher "
        "rates compress M&A deal volumes (higher cost of capital reduces LBO viability) "
        "and slow ECM issuance. Net effect: GS benefits from rate volatility more than "
        "rate level. Extended low-rate, low-volatility periods compress trading revenues."
    ),
    inflation_pass_through=(
        "GS has limited direct inflation exposure — fee revenue is transaction-based, "
        "not cost-plus. High inflation typically accompanies Fed tightening and rate "
        "volatility, which increases FICC trading opportunities. The primary inflation "
        "impact is on compensation: ~40% of revenues flow to employee comp, and talent "
        "competition with hedge funds and PE firms keeps compensation elevated."
    ),
    recession_behavior=(
        "Mixed recession dynamics: M&A and ECM revenues decline sharply (corporate "
        "management freezes strategic activity); FICC trading revenues can INCREASE "
        "in credit/rates dislocations (GS profited in 2008-2009 FICC). AWM faces "
        "AUM outflows in severe downturns. Historically, GS has navigated recessions "
        "through FICC gains that partially offset IB revenue declines."
    ),
    major_risks=[
        "M&A cycle dependence: deal volumes are highly correlated with CEO confidence "
        "and equity market levels — a sustained bear market cuts IB revenues 40-60%",
        "Marcus/consumer banking losses: GS spent $3B+ building Marcus consumer bank "
        "then began strategic retreat; lingering credit card losses (Apple Card, GM Card) "
        "drag on ROTCE",
        "Regulatory capital requirements: Basel III Endgame SCB requirements could "
        "require GS to hold more capital, reducing ROTCE from ~14% toward ~12%",
        "Key-man and talent risk: GS's business model depends on relationship bankers "
        "and traders; talent attrition to hedge funds and PE firms is structural",
        "FICC revenue volatility: in calm markets GS's trading revenues can fall 20-30% "
        "year-over-year, making EPS highly unpredictable",
    ],
    valuation_style=(
        "GS is valued on P/TBV (price-to-tangible book value) and ROTCE vs cost of equity. "
        "At a sustained ROTCE of 14-16%, GS deserves ~1.3-1.5x TBV. Below 13% ROTCE "
        "the stock approaches 1.0x TBV. The IB cycle premium: when M&A volumes recover "
        "to normalized levels, GS's IB wallet share (~8%) drives EPS upside. Key "
        "re-rating catalyst: exit from Marcus consumer losses + IB cycle recovery. "
        "De-rating risk: sustained low-volatility market reduces FICC revenue + ongoing "
        "consumer credit losses."
    ),
    key_metrics=[
        "ROTCE (Return on Tangible Common Equity) — management target 14-16%",
        "M&A advisory fee revenue and deal backlog",
        "FICC net revenues per quarter",
        "AWM AUS (Assets Under Supervision) and management fee margin",
        "Marcus / Platform Solutions net credit losses (drag on ROTCE)",
        "CET1 capital ratio vs SCB requirement",
        "Comp-to-revenue ratio (~40% target)",
    ],
    competitive_advantages=[
        "Top-2 M&A advisory market share: GS's relationship banking franchise and "
        "brand attract CEO-level mandates; switching costs for long-standing clients "
        "are high (decade-long banker relationships)",
        "FICC trading infrastructure: decades of technology investment and balance "
        "sheet capacity give GS execution quality advantages in credit, rates, and FX",
        "AWM private alternatives platform: GS Alternatives has $450B+ in illiquid "
        "strategies with high-fee structures and long lockup periods",
        "Global network and regulatory relationships: GS has operated in 40+ countries "
        "for decades, giving multinational clients a one-stop cross-border solution",
    ],
    business_model_keywords=[
        "FICC", "investment banking", "M&A advisory", "ECM", "DCM", "ROTCE",
        "Marcus", "Asset & Wealth Management", "AWM", "AUS", "deal activity",
        "trading revenue", "net interest income", "prime brokerage",
        "David Solomon", "IB wallet", "capital markets", "carried interest",
    ],
))


# ── Netflix (NFLX) ────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="NFLX",
    company_name="Netflix, Inc.",
    business_model=(
        "Netflix is the world's largest subscription video-on-demand (SVOD) service with "
        "~270M+ global paid subscribers across 190+ countries. Revenue comes from tiered "
        "monthly subscriptions (Standard with Ads at $7-8/mo, Standard at $15, Premium "
        "at $23) and growing advertising revenue from its ad-supported tier launched in "
        "November 2022. Netflix owns ~$32B of content assets (original programming, "
        "licensed titles) amortized over estimated useful lives."
    ),
    primary_revenue_drivers=[
        "Subscription revenue (~97%): ~270M paid members × ~$17 average monthly revenue "
        "per membership = ~$38B annual revenue; mix shift toward premium and ad-tier",
        "Advertising revenue (<3% but fastest-growing): ad-supported tier ARPU "
        "growing as advertiser interest ramps; targeting 2026-2027 material contribution",
        "Password-sharing crackdown: enforced paid-sharing policy (2023) converted "
        "~30M+ borrower households into paid subscribers, accelerating member growth",
        "International expansion: LATAM, APAC, EMEA are key subscriber growth regions; "
        "local content investment drives retention",
    ],
    recurring_revenue_sources=[
        "Monthly streaming plan fees (~2-3% monthly churn for paid tier customers)",
        "Pre-paid annual plan billings from long-term plan customers (lower churn than monthly)",
    ],
    rate_sensitivity_note=(
        "Netflix is a growth stock valued at 30-40x forward P/E — moderate rate sensitivity "
        "via DCF discount rate compression. A 100 bps rate rise compresses the multiple ~3-4 "
        "turns. More importantly, Netflix's business fundamentals are relatively rate-insensitive: "
        "consumer entertainment spending is sticky, and Netflix's $7-23/mo tiers are "
        "defensible against consumer cutbacks. Content financing is at fixed rates. "
        "Higher rates modestly increase Netflix's cost of debt on its $14B+ debt load."
    ),
    inflation_pass_through=(
        "Netflix has demonstrated pricing power: raised US Standard price from $11 to $15 "
        "(2019-2022) with minimal churn. The ad-supported tier launch at $7 created a "
        "price-tiered moat. Key risk: consumer subscription fatigue — multiple streaming "
        "services competing for the same wallet. ARPU growth is the primary indicator of "
        "pricing power. Content cost inflation (talent, production) is the key cost pressure."
    ),
    recession_behavior=(
        "Historically resilient: Netflix is a relative-value entertainment option vs "
        "live events, theaters, and travel. In 2020 recession, paid members accelerated "
        "+26M. In 2022 reset, Netflix lost 200K subscribers (first decline) then recovered "
        "via password sharing enforcement. Key risk: consumers trade down from Standard "
        "($15) to Ad ($7), reducing ARPU even if membership holds."
    ),
    major_risks=[
        "Streaming competition: Disney+ ($7-14), Amazon Prime Video ($9), Max ($10), "
        "Apple TV+ ($10) all compete for the same consumer budget; competition intensifies "
        "as studios recapture content from licensing deals",
        "Content amortization cycle: Netflix spends $17-18B/yr on content; if hit rates "
        "decline, subscriber growth slows and the market re-rates the content ROI",
        "Password-sharing crackdown: one-time subscriber bump from 2023 enforcement "
        "will not repeat; future growth depends on organic demand and international",
        "ARPU pressure from ad-tier mix shift: if subscribers trade down to $7 ad-tier, "
        "ARPU compresses unless ad revenue per user scales to compensate",
        "Gaming and live content: Netflix is investing in games and live events "
        "(WWE Raw, NFL Christmas games) — execution risk on new content categories",
    ],
    valuation_style=(
        "Netflix is valued on EV/FCF and P/E as it transitions from growth-at-all-costs "
        "to a profitable FCF-generative business. 2024-2025 FCF target $6-8B+ supports "
        "a 20-25x FCF multiple. Key re-rating catalysts: advertising revenue reaching "
        "$3-5B+ run-rate (proving the ad model), operating margin sustaining above 25%, "
        "continued subscriber growth above 200M. De-rating risk: stalled ARPU growth "
        "(subscribers grow but revenue per user flat/down), content miss (no breakout hits), "
        "Disney+ bundling acceleration taking market share."
    ),
    key_metrics=[
        "Paid subscribers (global total and net adds per quarter)",
        "Average revenue per membership (ARM / ARPU) by region",
        "Paid sharing / password crackdown conversion progress",
        "Ad-supported tier membership and advertising revenue per user",
        "Operating margin (target 26-28% by 2026)",
        "Free cash flow ($6-8B target range)",
        "Content spend ($17-18B/yr) and content amortization rate",
        "Engagement hours per subscriber (indicates retention quality)",
    ],
    competitive_advantages=[
        "Scale and recommendation algorithm: 270M+ subscribers generate 250M+ daily "
        "viewing hours of data; Netflix's recommendation engine (responsible for 80%+ "
        "of viewed content) requires this data density to function — competitors at "
        "50-100M subscribers cannot replicate this flywheel",
        "Original content IP ownership: Netflix owns its originals permanently (Stranger "
        "Things, Squid Game, Wednesday) — competitors depend on licensing deals that "
        "expire; Netflix's owned library grows each year",
        "Global infrastructure: operating in 190+ countries with localized payment "
        "processing, content compliance, and subtitling at a scale no competitor "
        "matches (Disney+ is in ~80 countries, Max in ~65)",
    ],
    business_model_keywords=[
        "subscriber", "paid sharing", "password crackdown", "ad-supported tier",
        "ARPU", "ARM", "content amortization", "engagement", "streaming",
        "Squid Game", "Stranger Things", "Wednesday", "original content",
        "operating margin", "free cash flow", "international expansion",
        "Ted Sarandos", "Greg Peters", "ad tier", "live content",
    ],
))


# ── Eli Lilly (LLY) ──────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="LLY",
    company_name="Eli Lilly and Company",
    business_model=(
        "Eli Lilly is a global pharmaceutical company whose portfolio is being reshaped "
        "by GLP-1 receptor agonists: Mounjaro (tirzepatide, approved diabetes 2022) and "
        "Zepbound (tirzepatide, approved obesity 2023) are the fastest-growing drugs in "
        "pharmaceutical history. The company also has key franchises in oncology "
        "(Verzenio/abemaciclib), immunology (Taltz, Olumiant), and neuroscience "
        "(Kisunla for Alzheimer's). Trulicity (dulaglutide) is a legacy GLP-1 in "
        "structural decline as patients switch to tirzepatide."
    ),
    primary_revenue_drivers=[
        "Mounjaro (tirzepatide injection, Type 2 diabetes) — peak sales potential "
        "$20-25B; fastest-growing diabetes drug ever; dual GIP/GLP-1 agonist",
        "Zepbound (tirzepatide injection, obesity/weight management) — peak sales "
        "potential $25B+; obesity market is multi-decade secular opportunity (1B+ obese "
        "globally, <5% treated pharmacologically)",
        "Verzenio / abemaciclib (CDK4/6 inhibitor, breast cancer) — ~$4B+ revenue, "
        "gaining share vs Pfizer Ibrance in adjuvant setting",
        "Kisunla (donanemab, Alzheimer's) — newly approved 2024; addressing amyloid "
        "plaque; $10B+ peak potential if uptake mirrors early Alzheimer's treatment",
        "Trulicity (dulaglutide, legacy GLP-1) — declining ~30%+ as patients switch "
        "to tirzepatide; material revenue headwind through 2026",
    ],
    recurring_revenue_sources=[
        "Chronic disease prescriptions (tirzepatide patients need indefinite dosing — "
        "diabetes/obesity are not cured, creating multi-decade recurring revenue)",
        "Oncology maintenance therapy (Verzenio in adjuvant breast cancer is 2 years "
        "of continuous therapy, generating predictable revenue)",
        "PBM access agreements (Mounjaro/Zepbound have Express Scripts and CVS "
        "formulary coverage — formulary position drives prescribing)",
    ],
    rate_sensitivity_note=(
        "LLY trades at 40-60x forward P/E — one of the highest multiples in large-cap "
        "pharma — because the market is pricing in multi-decade GLP-1 revenue compounding. "
        "A 100 bps rate rise compresses the multiple by ~5-8 turns in a standard DCF "
        "with a 25-30 year GLP-1 revenue tail. However, LLY's near-term fundamentals "
        "(Mounjaro/Zepbound production ramp, obesity market penetration) are more thesis-"
        "defining than interest rate moves. Lilly has a strong A+ credit rating with "
        "manageable $10B+ net debt relative to $50B+ annual revenue trajectory."
    ),
    inflation_pass_through=(
        "Strong pharmaceutical pricing power: Mounjaro list price ~$1,000/mo, Zepbound "
        "~$1,060/mo — premium pricing justified by clinical outcomes (15% body weight "
        "loss vs ~6% for GLP-1 mono). The primary pricing risk is political: the "
        "Inflation Reduction Act (IRA) will allow CMS to negotiate Part D prices for "
        "small-molecule drugs starting 2025 and biologics starting 2028. LLY's injectables "
        "(tirzepatide) are biologics exempt until 2028+, providing pricing protection."
    ),
    recession_behavior=(
        "Defensive/mixed: Diabetes and obesity treatments have strong clinical necessity "
        "driving persistence. However, GLP-1 drugs are expensive and high out-of-pocket "
        "costs may cause discontinuation in severe recessions. The obesity indication "
        "(Zepbound) may be more discretionary than diabetes (Mounjaro). Chronic "
        "conditions like breast cancer (Verzenio) are recession-proof."
    ),
    major_risks=[
        "Tirzepatide manufacturing capacity constraint: LLY is rapidly expanding "
        "manufacturing (Indiana, North Carolina, Germany plants) but capacity shortages "
        "have already limited Zepbound/Mounjaro prescription fulfillment",
        "GLP-1 competitive landscape: Novo Nordisk semaglutide (Ozempic/Wegovy) has "
        "established brand; new entrants (oral semaglutide, Amgen AMG-133, Structure "
        "Therapeutics) could intensify competition",
        "Trulicity decline: ~$3B+ revenue declining 30%+ annually as patients switch "
        "to tirzepatide — represents a near-term earnings headwind partially offsetting "
        "Mounjaro/Zepbound ramp",
        "IRA drug pricing risk: future CMS negotiation could reduce peak tirzepatide "
        "revenue if biologics are reclassified or regulation expands",
        "Alzheimer's market risk: Kisunla requires IV infusion + amyloid PET scan "
        "confirmation — access and reimbursement pathways are being established",
    ],
    valuation_style=(
        "LLY trades at 40-60x forward P/E and ~15-20x forward revenue — extreme "
        "multiples justified only if Mounjaro/Zepbound achieve $30-50B combined peak "
        "sales. DCF analysis uses a 20-30 year revenue tail for tirzepatide in "
        "diabetes, obesity, NASH, and cardiovascular indications. Key re-rating "
        "catalyst: Zepbound SURMOUNT-MMO cardiovascular outcomes data (reduces "
        "MACE), oral tirzepatide approval, manufacturing capacity normalization. "
        "De-rating risk: oral GLP-1 competitor approval, payer formulary restrictions, "
        "Mounjaro/Zepbound supply constraints limiting market penetration speed."
    ),
    key_metrics=[
        "Mounjaro quarterly revenue and prescription growth (TRx, NRx)",
        "Zepbound quarterly revenue and new prescription volume",
        "Tirzepatide manufacturing fill rate vs demand",
        "Trulicity revenue decline rate (earnings headwind measure)",
        "Verzenio sales growth and market share in adjuvant breast cancer",
        "Kisunla (donanemab) launch uptake and reimbursement coverage",
        "Pipeline: oral tirzepatide Phase 3 results, retatrutide Phase 3",
        "Operating margin trajectory (guided 40%+ long-term)",
    ],
    competitive_advantages=[
        "Tirzepatide clinical superiority: dual GIP/GLP-1 mechanism produces ~15% "
        "body weight loss vs ~12-13% for semaglutide (Ozempic/Wegovy) in head-to-head "
        "trials — the best weight loss drug ever approved, commanding premium positioning",
        "First-mover advantage in tirzepatide: multi-year manufacturing scale-up "
        "head start vs competitors; patients and physicians build familiarity with LLY products",
        "Pipeline depth: Phase 3 programs in NASH, sleep apnea, heart failure, renal "
        "disease (all with tirzepatide) could expand TAM to $100B+ across indications",
        "Oncology franchise: Verzenio CDK4/6 inhibitor is gaining on Ibrance in the "
        "$10B+ breast cancer market through adjuvant label expansion",
    ],
    business_model_keywords=[
        "Mounjaro", "tirzepatide", "Zepbound", "GLP-1", "GIP", "obesity",
        "weight loss", "Verzenio", "abemaciclib", "Kisunla", "donanemab",
        "Alzheimer's", "Trulicity", "dulaglutide", "semaglutide", "retatrutide",
        "manufacturing capacity", "IRA", "Dave Ricks", "diabetes",
    ],
    moat_type=["patent"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="low",
    binary_risk_level="moderate",
))


# ── Novo Nordisk (NVO) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="NVO",
    company_name="Novo Nordisk A/S",
    business_model=(
        "Novo Nordisk is a Danish pharmaceutical company and the global leader in "
        "GLP-1 receptor agonist therapy. Its two blockbuster drugs — Ozempic "
        "(semaglutide weekly injection, diabetes) and Wegovy (semaglutide high-dose, "
        "obesity) — are the most prescribed GLP-1 therapies globally. Novo also holds "
        "a dominant position in insulin therapy (Tresiba, Levemir, NovoLog/NovoRapid). "
        "The company is developing next-generation obesity therapies including "
        "CagriSema (cagrilintide + semaglutide combination) and oral semaglutide."
    ),
    primary_revenue_drivers=[
        "GLP-1 diabetes (Ozempic, Rybelsus oral semaglutide) — ~55% of revenue; "
        "Ozempic is the #1 prescribed injectable GLP-1 globally",
        "GLP-1 obesity (Wegovy high-dose semaglutide) — fastest-growing segment; "
        "peak sales potential $20-30B; approved in US/EU/UK",
        "Insulin franchise (Tresiba, Levemir, NovoLog, NovoRapid) — ~25% of revenue; "
        "mature/declining market but high-margin durable cash flow",
        "Rare disease (Haemophilia — Alhemo, Mim8; Rare blood disorders) — ~5% of revenue",
    ],
    recurring_revenue_sources=[
        "Chronic disease prescriptions (diabetes and obesity patients require indefinite "
        "treatment — high refill rates and long-duration therapy)",
        "Insulin biosimilar competition partially offset by Ozempic/Wegovy growth "
        "(formulary access across Medicare/Medicaid guarantees minimum volume)",
    ],
    rate_sensitivity_note=(
        "NVO trades at 25-35x forward P/E as a European pharma compounder. A 100 bps "
        "rate rise compresses the ADR multiple ~3-4 turns. NVO is a Danish krone-denominated "
        "business — USD/DKK FX movements affect ADR valuations. NVO's balance sheet is "
        "conservatively financed with net cash/modest leverage. The primary valuation "
        "driver is Ozempic/Wegovy revenue trajectory, not interest rates."
    ),
    inflation_pass_through=(
        "Strong pricing power in the US market: Ozempic list price ~$936/mo, Wegovy ~$1,349/mo. "
        "PBM formulary negotiations apply; net price after rebates is lower. In Europe, "
        "NVO faces tendered pricing with more constrained ASPs. The SELECT trial results "
        "(Wegovy reduces cardiovascular events 20%) have strengthened NVO's formulary "
        "negotiating position with payers. Manufacturing cost inflation (fill-finish, "
        "active ingredient) is manageable given high drug margins (~85%+)."
    ),
    recession_behavior=(
        "Defensive: Ozempic (diabetes) prescriptions are medically necessary and largely "
        "recession-proof. Wegovy (obesity, purely elective perception) may see more "
        "out-of-pocket discontinuation in severe downturns. Overall, NVO's diabetes "
        "franchise provides a recession-resistant earnings floor while obesity provides "
        "the cyclical-growth optionality."
    ),
    major_risks=[
        "Tirzepatide (Lilly Mounjaro/Zepbound) competitive risk: LLY's tirzepatide "
        "demonstrated ~15% weight loss vs ~12-13% for semaglutide in SURMOUNT-5 "
        "head-to-head trial — NVO must compete on tolerability, dosing convenience, "
        "and oral formulations",
        "CagriSema execution risk: Phase 3 REDEFINE-1 results showed ~22.7% weight "
        "loss but missed the pre-specified superiority threshold vs Wegovy — may limit "
        "re-rating potential vs tirzepatide",
        "Manufacturing capacity constraints: global Ozempic/Wegovy shortage has limited "
        "prescription fills; NVO is investing DKK 65B+ in manufacturing expansion",
        "US drug pricing: IRA negotiation risk for semaglutide; Ozempic biologics "
        "exclusivity runs until 2031, but biosimilar entry planning is underway",
        "Obesity market saturation risk: payer coverage constraints and GLP-1 cost keep "
        "penetration below 5% of eligible patients — market growth depends on coverage "
        "expansion",
    ],
    valuation_style=(
        "NVO trades at 25-35x forward P/E as a large-cap European healthcare compounder "
        "with US-market execution risk. The obesity TAM (1B+ obese globally) supports "
        "long duration DCF. Key re-rating catalysts: oral semaglutide approval and uptake "
        "(expands TAM beyond injectable-tolerant patients), CagriSema Phase 3 proving "
        "~25%+ weight loss. De-rating risk: tirzepatide head-to-head superiority driving "
        "formulary preference switches, CagriSema Phase 3 miss, US pricing regulation."
    ),
    key_metrics=[
        "Ozempic quarterly revenue and prescription market share (vs Mounjaro)",
        "Wegovy quarterly revenue and net adds (obesity market penetration)",
        "Oral semaglutide (Rybelsus) prescription growth",
        "CagriSema Phase 3 REDEFINE weight loss data vs Wegovy",
        "Manufacturing supply normalization (fill-and-finish output)",
        "Insulin franchise revenue trend (structural decline rate)",
        "Operating margin trajectory (guided ~46%+ long-term)",
        "SELECT cardiovascular outcomes data impact on payer coverage",
    ],
    competitive_advantages=[
        "Semaglutide first-mover and brand leadership: Ozempic/Wegovy are prescribed "
        "to ~30M+ patients globally — the brand recognition, physician familiarity, "
        "and patient community (social media 'Ozempic' brand) create switching costs",
        "SELECT cardiovascular outcomes trial: Wegovy is the ONLY obesity drug with "
        "proven 20% reduction in MACE (major adverse cardiovascular events) — this "
        "transforms obesity treatment from cosmetic to cardiovascular prevention, "
        "unlocking broader payer coverage",
        "Oral semaglutide (Rybelsus) platform: NVO leads in oral GLP-1 formulation; "
        "a successful high-dose oral obesity tablet would open a massive new patient "
        "population that avoids injections",
        "Decades of diabetes manufacturing expertise: NVO has manufactured insulin "
        "and injectable GLP-1 for 100+ years — unique fill-finish scale and quality "
        "systems give NVO a manufacturing reliability advantage vs pharma new entrants",
    ],
    business_model_keywords=[
        "Ozempic", "Wegovy", "semaglutide", "GLP-1", "obesity", "diabetes",
        "Rybelsus", "CagriSema", "cagrilintide", "SELECT trial", "MACE",
        "Mounjaro competition", "insulin", "Tresiba", "cardiovascular outcomes",
        "manufacturing capacity", "Lars Fruergaard Jørgensen", "weight loss",
        "oral semaglutide", "SURMOUNT", "REDEFINE",
    ],
    moat_type=["patent"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="low",
    binary_risk_level="moderate",
))


# ── Oracle (ORCL) ─────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="ORCL",
    company_name="Oracle Corporation",
    business_model=(
        "Oracle is an enterprise software and cloud infrastructure company.  Its three "
        "core businesses are: (1) Oracle Cloud Infrastructure (OCI), a hyperscale IaaS/PaaS "
        "competing with AWS, Azure, and GCP; (2) Oracle Fusion Cloud Applications (ERP, HCM, "
        "SCM, CX) and NetSuite (SMB ERP), delivered as multi-tenant SaaS; and (3) a massive "
        "installed base of on-premise Oracle Database licenses and Exadata engineered systems "
        "that generate ~$9B/yr in high-margin support revenue largely independent of new sales."
    ),
    primary_revenue_drivers=[
        "Cloud services & license support (~77% of revenue, ~85% gross margin — Oracle "
        "Database, Fusion ERP/HCM, NetSuite, OCI subscription, technical support)",
        "Cloud license & on-premise license (~11% — new perpetual/term license sales)",
        "Hardware (~5% — Exadata engineered systems, SPARC servers)",
        "Services (~7% — consulting and managed cloud services)",
    ],
    recurring_revenue_sources=[
        "Oracle Database and Technology license support contracts (>95% annual renewal rate "
        "— installed base spans Fortune 500 mission-critical systems)",
        "Fusion Cloud ERP/HCM/SCM SaaS subscriptions (multi-year, typically 3-5 year terms)",
        "NetSuite ERP subscriptions (~25-30% annual growth, SMB market)",
        "OCI consumption-based billing (hyperscaler workloads, Oracle Dedicated Region)",
        "MySQL HeatWave cloud database subscriptions",
    ],
    rate_sensitivity_note=(
        "Oracle trades at ~20-25x forward P/E — moderate rate sensitivity via DCF mechanics. "
        "A 100 bps rate rise compresses fair value by ~2-3 turns.  Oracle carries ~$85-90B "
        "of long-term debt (largely taken on via Sun Microsystems, PeopleSoft, Cerner "
        "acquisitions) — higher rates modestly increase interest expense on floating-rate "
        "tranches.  However, Oracle's ~$18-20B annual FCF comfortably services this debt. "
        "Enterprise IT spend on database and ERP infrastructure is relatively rate-insensitive "
        "as these are mission-critical systems customers cannot switch off."
    ),
    inflation_pass_through=(
        "Strong pricing power: Oracle has raised support contract prices 4-6% annually for "
        "decades on the installed base without meaningful customer attrition.  Fusion Cloud "
        "contract pricing is negotiated, but customers migrating from on-premise to SaaS "
        "accept higher per-seat costs for reduced infrastructure overhead.  OCI is priced at "
        "a deliberate 30-40% discount to AWS to gain market share in training AI workloads."
    ),
    recession_behavior=(
        "Oracle's support revenue (~$9B/yr, >85% gross margin) is highly defensive — "
        "Fortune 500 companies cannot turn off Oracle Database during a recession.  License "
        "new sales are more cyclical.  Cloud SaaS (Fusion, NetSuite) is stickier than "
        "on-premise licenses.  OCI consumption can be deferred.  Cerner healthcare IT "
        "(acquired 2022) adds recession-resilient federal/hospital revenue."
    ),
    major_risks=[
        "OCI competitive positioning vs AWS, Azure, Google Cloud — Oracle is a distant #4 "
        "in hyperscale IaaS despite significant CapEx investment and aggressive pricing",
        "Cerner integration execution: $28B Cerner acquisition (2022) requires multi-year "
        "migration of 25,000+ hospital clients to Oracle Health cloud — behind schedule",
        "Database disintermediation: open-source PostgreSQL, MySQL, and cloud-native DBs "
        "(Amazon Aurora, Google Spanner) erode Oracle Database growth in new workloads",
        "License support cannibalization: as customers migrate to Fusion Cloud, high-margin "
        "support revenue from on-premise licenses gradually declines",
        "Larry Ellison key-person risk: Ellison is executive chairman, CTO, and owns ~40% "
        "of Oracle shares — his strategic decisions are unchecked",
    ],
    valuation_style=(
        "Oracle trades at ~20-25x forward P/E and ~20x EV/FCF.  The market prices Oracle "
        "as a combination of a high-quality installed-base annuity (support revenue) and a "
        "cloud growth optionality premium (OCI + Fusion).  AI tailwind: Oracle's OCI GPU "
        "clusters are attracting AI training workloads as AWS/Azure face capacity shortages — "
        "this is the key re-rating catalyst driving Oracle's ~40%+ stock appreciation since 2023."
    ),
    key_metrics=[
        "Cloud revenue (OCI + Fusion + NetSuite combined growth rate)",
        "Remaining performance obligations (RPO) — contractual backlog indicator",
        "Database license support renewal rate (>95% target)",
        "OCI quarterly revenue and capacity utilization",
        "Fusion ERP cloud application customer count and ARPU",
        "Cerner / Oracle Health cloud migration progress",
        "Free cash flow ($18-20B/yr range)",
        "Net leverage ratio (target below 4x EBITDA)",
    ],
    competitive_advantages=[
        "Oracle Database installed base moat: the world's most deployed enterprise relational "
        "database — 40+ years of mission-critical adoption creates extremely high switching "
        "costs (schema migrations take years and cost $100M+ at large enterprises)",
        "Exadata engineered systems: Oracle hardware + software stack delivers 10-100x "
        "Database performance vs standard x86 — enterprises requiring maximum OLTP throughput "
        "have no equivalent option",
        "Fusion Cloud vertical integration: Oracle designs silicon (Oracle SPARC), OS "
        "(Oracle Linux), hypervisor (Oracle VM), and application layer (Fusion ERP) — "
        "a full-stack cloud that no hyperscaler can match in enterprise ERP",
        "OCI GPU capacity advantage for AI: OCI's RDMA networking fabric (800Gbps "
        "Cluster Networking) and NVIDIA H100/H200 allocation position Oracle as the "
        "preferred hyperscaler for GPU-dense AI training workloads",
    ],
    business_model_keywords=[
        "Oracle Database", "OCI", "Fusion", "NetSuite", "Exadata", "Cerner",
        "Oracle Health", "HCM", "ERP", "SCM", "cloud infrastructure", "license support",
        "Larry Ellison", "Safra Catz", "RPO", "remaining performance obligations",
        "autonomous database", "MySQL",
    ],
))


# ── Bank of America (BAC) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="BAC",
    company_name="Bank of America Corporation",
    business_model=(
        "Bank of America is the second-largest US bank by assets (~$3.3T), operating across "
        "four segments: Consumer Banking (retail deposits, checking/savings, consumer loans, "
        "Zelle P2P), Global Wealth & Investment Management (Merrill Lynch wealth management "
        "and private bank, ~$3.8T AUM), Global Banking (corporate/commercial lending, "
        "investment banking, treasury services), and Global Markets (FICC and equities trading)."
    ),
    primary_revenue_drivers=[
        "Consumer Banking (~35% of net revenue — NII on deposits/loans, card fees, "
        "service charges, home equity)",
        "Global Wealth & Investment Management / GWIM (~25% — Merrill Lynch advisory "
        "fees, Private Bank, brokerage commissions on $3.8T AUM)",
        "Global Banking (~20% — commercial banking NII, investment banking fees, "
        "treasury management, leasing)",
        "Global Markets (~20% — FICC trading, equities trading, sales and trading revenue)",
    ],
    recurring_revenue_sources=[
        "Net Interest Income (NII) from deposit spread — largest component of revenue",
        "Merrill Lynch fee-based advisory accounts (~60% of GWIM client assets in "
        "fee-based relationships, providing recurring AUM-percentage fees)",
        "Card services interchange revenue (consumer and commercial credit/debit cards)",
        "Treasury management fees (cash management, payments, trade finance for corporate clients)",
    ],
    rate_sensitivity_note=(
        "BAC is among the most rate-sensitive large US banks.  Management estimates each "
        "100 bps parallel shift in the yield curve adds approximately $1.8-2.5B to "
        "annualised NII — BAC is heavily asset-sensitive due to its large floating-rate "
        "loan portfolio and deposit base that reprices slowly.  Conversely, rate cuts "
        "compress NII significantly.  The key BAC-specific issue is Accumulated Other "
        "Comprehensive Income (AOCI): BAC holds a large HTM (held-to-maturity) bond "
        "portfolio with unrealised losses of $100B+ at peak-rate — these losses are "
        "excluded from regulatory capital but represent an opportunity cost vs peers "
        "who redeployed capital at higher yields."
    ),
    inflation_pass_through=(
        "Banks benefit indirectly from inflation via higher nominal loan balances and card "
        "spend volumes.  BAC's Merrill Lynch wealth management revenue is asset-valued — "
        "equity market inflation increases AUM and fee revenue.  Primary cost pressure "
        "is employee compensation (~50%+ of non-interest expense), which inflates with "
        "wages.  BAC has consistently targeted positive operating leverage (revenue growth "
        "exceeding expense growth) via efficiency ratio improvement."
    ),
    recession_behavior=(
        "BAC builds loan loss reserves in recessions (provision expense spikes, compressing "
        "earnings).  The consumer banking segment faces card and home equity delinquency "
        "increases.  GWIM AUM declines with equity markets.  Global Banking IB fees fall "
        "with deal activity.  BAC's CET1 ratio (~12-13%) provides a meaningful capital "
        "buffer.  CEO Brian Moynihan's 'responsible growth' framework targets maintained "
        "through-cycle profitability above a minimum ROTCE threshold."
    ),
    major_risks=[
        "AOCI HTM bond portfolio: $100B+ unrealised losses in rising-rate environment "
        "reduce BAC's ability to deploy capital and create earnings opportunity cost "
        "vs peers who didn't lock into long-duration bonds at pandemic-era low rates",
        "Consumer credit normalisation: credit card and auto delinquencies rising from "
        "post-pandemic lows; subprime card exposure is the most vulnerable segment",
        "Rate cut cycle: BAC's significant asset sensitivity means rate cuts directly "
        "reduce NII — each 25 bps cut reduces NII by ~$0.5-0.8B annualised",
        "Basel III Endgame capital requirements: potentially ~20% RWA increase would "
        "force additional capital retention and reduce buyback capacity",
        "Merrill Lynch competitive dynamics: Morgan Stanley/UBS Wealth Management "
        "competing aggressively for high-net-worth financial advisors",
    ],
    valuation_style=(
        "BAC trades at ~1.1-1.4x P/TBV (tangible book value) and ~11-13x forward P/E, "
        "at a discount to JPM (~2x TBV) reflecting AOCI concerns and slightly lower "
        "ROTCE (~12-14% vs JPM ~17-19%).  Key re-rating catalyst: AOCI HTM maturity "
        "reducing unrealised losses over time, sustained NII above $14B/quarter, ROTCE "
        "approaching 15% which would justify 1.5-1.7x TBV multiple."
    ),
    key_metrics=[
        "Net Interest Income (NII) — quarterly absolute and management guidance",
        "Net Interest Margin (NIM) — impacted by deposit repricing mix",
        "ROTCE (Return on Tangible Common Equity) — target 15%+",
        "CET1 capital ratio (~12-13% actual vs ~10% regulatory minimum)",
        "GWIM AUM and net new assets ($3.8T+ target)",
        "Provision for credit losses and net charge-off rate by segment",
        "AOCI unrealised HTM portfolio losses (balance sheet risk metric)",
        "Efficiency ratio (expenses/revenue) — target below 60%",
    ],
    competitive_advantages=[
        "Merrill Lynch wealth franchise: 19,000+ financial advisors managing $3.8T+ AUM "
        "— one of the two dominant US wirehouse platforms (with Morgan Stanley)",
        "Consumer banking deposit franchise: 69M+ consumer and small business clients "
        "provide a low-cost deposit base that funds loans at higher spreads",
        "Scale and digital banking: Zelle P2P, digital banking platform with 57M+ verified "
        "digital users creates low-cost distribution vs brick-and-mortar competitors",
        "Responsible Growth track record: consistent quarterly profitability since 2014 "
        "under Brian Moynihan's multi-year strategy with strong through-cycle earnings",
    ],
    business_model_keywords=[
        "Merrill Lynch", "GWIM", "NII", "NIM", "CET1", "ROTCE",
        "consumer banking", "AOCI", "HTM", "deposit beta", "Global Markets",
        "Global Banking", "Brian Moynihan", "responsible growth",
        "Zelle", "wealth management", "private bank", "trading revenue",
    ],
))


# ── Verizon Communications (VZ) ───────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="VZ",
    company_name="Verizon Communications Inc.",
    business_model=(
        "Verizon is a US wireless and wireline telecommunications company.  The Consumer "
        "segment (~75% of revenue) provides wireless postpaid/prepaid mobile services, Fios "
        "fiber broadband and TV, and fixed wireless access (FWA) home broadband.  The "
        "Business segment (~25%) serves enterprise, mid-market, and government customers "
        "with wireless, private 5G networks, and wireline connectivity.  Verizon's "
        "competitive differentiation is its C-band 5G network quality, claimed to deliver "
        "the best urban/suburban 5G performance among US carriers."
    ),
    primary_revenue_drivers=[
        "Consumer wireless postpaid services (~50% of total revenue — ~98M postpaid "
        "phone connections, highest ARPA of any US carrier)",
        "Consumer wireline — Fios fiber (~15% — ~8M Fios internet subscribers, ~3M Fios "
        "TV; fiber broadband adding value in MDU/suburban markets)",
        "Fixed Wireless Access (FWA) home broadband — fastest-growing consumer segment; "
        "targeting 4-5M FWA subs by 2025 using 5G/4G LTE spectrum",
        "Business wireless and wireline (~25% — enterprise mobility, private 5G MEC, "
        "government FirstResponder Network Authority adjacent services)",
    ],
    recurring_revenue_sources=[
        "Wireless postpaid device payment plan and service fee monthly billings (~$36-40 "
        "ARPA) — very high switching costs due to device payoff lock-in and 24-month "
        "payment plans",
        "Fios internet monthly broadband service fees (96%+ retention rate in Fios "
        "footprint; internet-only strategy in established fiber markets)",
    ],
    rate_sensitivity_note=(
        "Verizon carries ~$150B of total debt (including long-term spectrum financing and "
        "operating lease obligations) — one of the largest corporate debt loads in the S&P 500. "
        "A 100 bps rise in rates increases annual interest expense by ~$0.5-1B on floating-rate "
        "debt tranches.  The stock typically yields 6-7% — a high dividend yield relative to "
        "10-year Treasuries; rising rates narrow this spread and may reduce VZ's appeal to "
        "income-seeking investors, compressing the P/E multiple.  Free cash flow (~$18-19B) "
        "comfortably covers the ~$11B annual dividend, providing fundamental support."
    ),
    inflation_pass_through=(
        "Verizon has demonstrated wireless pricing power: MyPlan architecture enabled "
        "ARPA increases of ~3-5% in 2023-24 as customers added premium plan tiers.  "
        "Network operating costs (power, spectrum lease, maintenance) inflate with CPI. "
        "Handset upgrade subsidy costs are volume-dependent.  The primary inflation defense "
        "is ARPA mix-shift toward higher-tier plans (premium unlimited, add-ons)."
    ),
    recession_behavior=(
        "Wireless service is largely stable — consumers maintain phone plans even "
        "in recessions, though some downgrade to lower-tier plans.  Fios broadband "
        "retention stays high as internet connectivity is a household staple.  Device "
        "upgrade volumes slow in recessions as consumers extend device life, reducing "
        "equipment revenue but improving service margin mix.  Business wireline may "
        "see enterprise spending deferrals.  VZ's dividend is well-covered by FCF."
    ),
    major_risks=[
        "T-Mobile competitive threat: T-Mobile's 5G mid-band coverage advantage and "
        "competitive pricing are driving postpaid phone net adds at T-Mobile's expense "
        "— VZ has lost postpaid net add momentum vs T-Mobile in 2022-24",
        "Spectrum cost: VZ spent ~$45B+ on C-band licenses (2021) and must continue "
        "investing $8-10B/yr in CapEx for 5G network build — elevating debt burden",
        "Lead cable sheathing liability: potential remediation costs for legacy "
        "lead-jacketed cables across the network (industry-wide regulatory risk)",
        "FWA market saturation: fixed wireless access is a land-grab between VZ, T-Mobile, "
        "and cable operators; addressable market is homes without fiber access",
        "Legacy wireline decline: business wireline revenue declining structurally as "
        "enterprise customers migrate to IP and wireless connectivity",
    ],
    valuation_style=(
        "VZ trades at ~9-11x forward P/E and is valued primarily on dividend yield "
        "(6-7%) and EV/EBITDA (~7-8x) — a classic utility-like telecom multiple. "
        "The market prices VZ as a high-yield dividend stock, not a growth story. "
        "Key re-rating catalyst: postpaid phone net add recovery above zero, ARPA "
        "growth demonstrating MyPlan monetisation, debt leverage reduction below 2.5x "
        "EBITDA.  De-rating risk: T-Mobile continuing to outgrow VZ, dividend coverage "
        "declining, spectrum cost escalation."
    ),
    key_metrics=[
        "Wireless postpaid phone net adds (key competitive metric vs T-Mobile, AT&T)",
        "ARPA (average revenue per account) and ARPU (per user) growth",
        "Fios internet net adds (indicates fiber broadband competitiveness)",
        "Fixed Wireless Access (FWA) subscribers (FWA growth target 4-5M)",
        "Total wireless service revenue growth rate",
        "Free cash flow ($18-19B annual target for dividend sustainability)",
        "Net leverage ratio (total debt/adjusted EBITDA — target 2.25x-2.5x)",
        "C-band 5G coverage milestones and densification progress",
    ],
    competitive_advantages=[
        "Network quality leadership in urban/suburban markets: C-band 5G deployment "
        "delivers best-in-class latency and throughput in Tier 1 markets; enterprise "
        "customers pay a premium for network reliability (911 and mission-critical apps)",
        "Postpaid customer base loyalty: ~98M postpaid phone connections with industry-"
        "leading ARPA; device payment plan lock-in creates 24-month customer stickiness",
        "MyPlan customizable architecture: allows ARPA upsell via digital content "
        "add-ons (streaming, cloud, perks) without requiring plan tier changes",
    ],
    business_model_keywords=[
        "wireless postpaid", "Fios", "C-band", "5G", "MyPlan", "ARPA",
        "fixed wireless access", "FWA", "spectrum", "postpaid net adds",
        "Hans Vestberg", "enterprise 5G", "network quality", "broadband",
        "dividend", "free cash flow", "T-Mobile competition",
    ],
))


# ── AT&T (T) ──────────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="T",
    company_name="AT&T Inc.",
    business_model=(
        "AT&T is a US wireless and broadband company following its 2022 divestiture of "
        "WarnerMedia (merged into Warner Bros. Discovery).  The refocused AT&T operates "
        "two segments: Mobility (wireless postpaid/prepaid — largest US carrier by "
        "subscribers ~115M+) and Consumer Wireline (AT&T Fiber broadband + DIRECTV-linked "
        "legacy TV).  The Business Wireline segment serves enterprise and government "
        "customers with connectivity, cybersecurity, and managed services.  AT&T's "
        "strategic priority is fiber expansion (30M+ passings target by 2025) via AT&T Fiber."
    ),
    primary_revenue_drivers=[
        "Mobility services (~55% of revenue — postpaid/prepaid wireless service revenue; "
        "~115M subscriber base including FirstNet first-responder network)",
        "Consumer Wireline — AT&T Fiber (~20% — fiber broadband subscriptions growing "
        "at 15-20%/yr; ~10M+ AT&T Fiber customers; ARPU ~$70+/mo)",
        "Business Wireline (~20% — enterprise connectivity, cybersecurity, managed "
        "services; structural decline in legacy copper/DSL)",
        "Wireless equipment (~5% — device sale revenue at near-zero margin)",
    ],
    recurring_revenue_sources=[
        "Wireless postpaid service fee billings (high-stickiness monthly recurring revenue "
        "— ~$55-60 ARPU on postpaid phone accounts)",
        "AT&T Fiber broadband monthly service fees (near-100% retention in fiber "
        "footprint; internet-only strategy following DIRECTV stake reduction)",
    ],
    rate_sensitivity_note=(
        "AT&T carries ~$130-140B of total debt — one of the highest in the S&P 500, "
        "a legacy of failed media acquisitions (DirecTV $48B, WarnerMedia $85B). "
        "A 100 bps rise in rates increases annualised interest expense by ~$0.5B on "
        "floating-rate tranches.  More importantly, AT&T's ~6-7% dividend yield competes "
        "directly with rising Treasury yields for income-seeking investors — rate rises "
        "reduce T's relative yield attractiveness and compress its P/E multiple.  FCF "
        "guidance of $17-18B/yr must cover the ~$8B annual dividend and debt reduction."
    ),
    inflation_pass_through=(
        "AT&T has pricing power in wireless: raised unlimited plan prices 10-15% in "
        "2023 with modest churn impact.  Fiber broadband ARPU has been rising as the "
        "legacy DSL base migrates to higher-priced fiber plans.  Network operating "
        "costs (power, maintenance, labor) inflate with CPI — margin management is "
        "a key investor focus."
    ),
    recession_behavior=(
        "Wireless service is largely stable for most consumers who retain mobile plans "
        "even during downturns, though some downgrade to prepaid tiers.  AT&T Fiber "
        "broadband provides connectivity infrastructure with low churn.  Business "
        "wireline sees enterprise spending deferrals in severe contractions.  AT&T's "
        "dividend coverage is the key financial stress test in a downturn."
    ),
    major_risks=[
        "Debt burden and deleveraging pace: AT&T must reduce net debt from ~$130B toward "
        "$100B by 2025 — free cash flow generation is the primary constraint; any FCF "
        "miss threatens the deleveraging timeline",
        "Fiber overbuild competition: Comcast, Charter, and Google Fiber are overbulding "
        "AT&T's fiber footprint, increasing churn in established markets",
        "Lead sheathing cable liability: potential remediation of legacy lead-clad cables "
        "could represent a multi-billion dollar liability (shared across industry)",
        "Legacy business wireline decline: copper/DSL enterprise revenue declining "
        "structurally, offsetting fiber broadband growth",
        "DIRECTV complexity: AT&T still owns ~70% of DIRECTV — satellite TV secular "
        "decline creates a drag on earnings and balance sheet",
    ],
    valuation_style=(
        "AT&T trades at ~9-11x forward P/E and ~7-8x EV/EBITDA, valued as a "
        "high-yield dividend utility.  The stock's 6-7% dividend yield is the primary "
        "investor proposition.  Key re-rating catalysts: debt leverage below 2.5x "
        "EBITDA, AT&T Fiber subscribers surpassing 15M (validating fiber ROI), "
        "wireless service revenue re-acceleration.  De-rating risk: FCF miss from "
        "fiber buildout CapEx overrun, DIRECTV value impairment, T-Mobile/Verizon "
        "taking postpaid market share."
    ),
    key_metrics=[
        "Wireless postpaid phone net adds (key competitive metric vs Verizon/T-Mobile)",
        "AT&T Fiber net adds and subscriber count (target 15M+ by 2025)",
        "AT&T Fiber ARPU growth (~$70+/mo target)",
        "Free cash flow ($17-18B annual guidance — covers dividend and debt paydown)",
        "Net leverage ratio (target 2.5x EBITDA by end-2025)",
        "FirstNet subscriber count and revenue contribution",
        "Wireless service revenue growth rate",
        "Business Wireline revenue trend (rate of legacy decline vs fiber enterprise growth)",
    ],
    competitive_advantages=[
        "FirstNet first-responder network: sole carrier contracted to build the national "
        "public safety broadband network — creates sticky government/first-responder "
        "subscriber base and federal deferred revenue stream",
        "Fiber broadband quality: AT&T Fiber's gigabit symmetric internet service "
        "delivers superior speeds vs cable HFC in overlapping markets — strong NPS "
        "and low churn once customers switch to fiber",
        "Wireless network scale: 115M+ subscriber base provides spectrum amortisation "
        "advantage and enterprise bundle leverage (wireless + fiber + 5G)",
    ],
    business_model_keywords=[
        "AT&T Fiber", "FirstNet", "wireless postpaid", "ARPU", "fiber broadband",
        "DIRECTV", "WarnerMedia", "Business Wireline", "free cash flow",
        "John Stankey", "deleveraging", "debt reduction", "5G", "postpaid net adds",
        "C-band", "fiber passings", "dividend", "net leverage",
    ],
))


# ── Comcast (CMCSA) ───────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="CMCSA",
    company_name="Comcast Corporation",
    business_model=(
        "Comcast operates through three major segments: (1) Connectivity & Platforms — "
        "Xfinity cable broadband (the largest US cable broadband provider, ~32M customers), "
        "Xfinity Mobile (MVNO using Verizon network + WiFi), linear TV, and business "
        "connectivity; (2) NBCUniversal — broadcast networks (NBC, Telemundo), cable channels "
        "(MSNBC, CNBC, USA), filmed entertainment (Universal Pictures), theme parks (Universal "
        "Studios), and Peacock streaming; (3) Sky — European satellite TV and broadband "
        "serving UK, Italy, Germany (~21M customers)."
    ),
    primary_revenue_drivers=[
        "Connectivity & Platforms broadband (~40% of total revenue — Xfinity internet "
        "service, ~32M residential and SMB broadband customers at $70-85/mo ARPU)",
        "NBCUniversal (~25% — advertising, theme park admissions, distribution fees, "
        "Universal filmed entertainment)",
        "Xfinity Mobile wireless (~7% and growing — ~7M subscriber lines, MVNO model "
        "on Verizon network, high-margin bundle upsell)",
        "Video/linear TV (~15% — declining; cord-cutting continues ~3-4% annual sub loss)",
        "Sky (~13% — European broadband, satellite TV, content rights)",
    ],
    recurring_revenue_sources=[
        "Broadband monthly subscription fees (Xfinity internet — ~96% retention rate; "
        "essential infrastructure for remote work and streaming)",
        "Xfinity Mobile recurring service revenue (bundled with broadband at minimal "
        "incremental cost — very high incremental margin on mobile adds)",
        "Theme park revenue per visit (Universal Studios, Wizarding World of Harry Potter; "
        "Epic Universe opening 2025)",
        "NBCUniversal cable network affiliate fees (retransmission consent payments from "
        "pay-TV distributors — multi-year, inflation-escalating contracts)",
        "Peacock streaming subscriptions (ad-supported and premium tiers; ~36M paid subs)",
    ],
    rate_sensitivity_note=(
        "Comcast carries ~$95-100B of total debt.  A 100 bps rate rise increases annual "
        "interest expense by ~$0.3-0.5B on floating-rate exposure.  Comcast's broadband "
        "and theme park businesses generate robust FCF ($15-17B/yr), providing strong "
        "debt-service capacity.  The cable broadband business trades at a utility-like "
        "multiple (~12-15x EV/EBITDA) that is modestly DCF-sensitive.  Higher rates "
        "also increase the cost of NBCU content financing."
    ),
    inflation_pass_through=(
        "Broadband ARPU has been raised 3-5% annually for a decade with minimal customer "
        "loss — internet service is a near-essential utility with few viable alternatives "
        "outside AT&T Fiber overbuild zones.  Theme park ticket pricing grows annually "
        "above CPI (Universal has raised prices 10%+ in 2023-24).  Content production "
        "costs (talent, below-the-line labor) inflate with wages.  NBCUniversal advertising "
        "revenue is cyclical and acutely sensitive to the ad market."
    ),
    recession_behavior=(
        "Broadband is essential infrastructure — churn is extremely low even in recessions. "
        "Theme parks are discretionary; attendance fell sharply in 2020 but recovered "
        "strongly post-COVID with record per-capita spending.  Linear TV advertising "
        "is cyclical.  Peacock streaming investments create near-term FCF headwinds "
        "that are financed by broadband cash flow."
    ),
    major_risks=[
        "Broadband competition from fiber overbuild: AT&T Fiber and T-Mobile FWA are "
        "taking market share in Comcast's cable footprint — broadband net adds have gone "
        "negative in some recent quarters",
        "Cord-cutting acceleration: linear TV revenue declining 4-6%/yr as subscribers "
        "leave cable for streaming; Comcast must offset with broadband ARPU and Peacock",
        "Peacock content investment ROI: Comcast is investing $3-4B/yr in Peacock content "
        "— the streaming business remains unprofitable and subscriber growth has slowed "
        "vs Disney+ and Netflix",
        "Epic Universe execution and ROI: $7B+ theme park investment in Orlando opening "
        "2025 — execution risk and competitive dynamics with Walt Disney World",
        "NBC broadcast rights expiration: NFL Thursday Night Football, Olympics contracts "
        "require expensive renewals that inflate content cost structure",
    ],
    valuation_style=(
        "Comcast trades at ~12-14x forward P/E and ~7-8x EV/EBITDA — a cable utility "
        "multiple that discounts the NBCUniversal content complexity.  Sum-of-parts: "
        "broadband business alone at 12-15x EBITDA (~$120-140B), NBCU at 8-10x EBITDA "
        "($30-40B), Sky at 7-9x EBITDA ($15-20B).  The conglomerate discount is "
        "significant — broadband alone is worth more than Comcast's market cap on some "
        "analyses.  Buybacks (~$10B/yr) provide meaningful EPS support."
    ),
    key_metrics=[
        "Broadband net adds (residential + business; turning negative is a red flag)",
        "Broadband ARPU growth (~3-5%/yr target)",
        "Xfinity Mobile subscriber count and line growth",
        "Peacock subscriber count and ARPU (ad-supported vs. premium mix)",
        "Theme park attendance and per capita spending (Universal Studios)",
        "Free cash flow ($15-17B annual range)",
        "Total capital return to shareholders (buyback + dividend)",
        "Linear TV subscriber decline rate (cord-cutting pace)",
    ],
    competitive_advantages=[
        "HFC cable network moat: Comcast's hybrid fiber-coaxial plant reaches ~60M+ US "
        "homes — the only near-gigabit broadband option for most of its footprint; fiber "
        "overbuild is occurring but is expensive and slow, limiting competition",
        "Xfinity Mobile bundle economics: selling wireless service on Verizon's MVNO at "
        "minimal incremental cost to broadband customers — ~85%+ incremental EBITDA "
        "margin on mobile adds, dramatically improving bundle economics",
        "NBCUniversal theme park IP: Wizarding World, Nintendo World, Minions, and Epic "
        "Universe create must-visit physical experiences that generate $6-8B/yr in "
        "high-margin recurring revenue with pricing power",
        "Scale in content distribution: Comcast distributes content across cable network, "
        "streaming (Peacock), broadcast (NBC), and Sky — giving content creators "
        "multi-platform exposure in deal negotiations",
    ],
    business_model_keywords=[
        "Xfinity", "broadband", "Peacock", "NBCUniversal", "Sky", "Universal Studios",
        "Epic Universe", "Xfinity Mobile", "cord-cutting", "ARPU",
        "Brian Roberts", "theme parks", "cable network", "HFC",
        "affiliate fees", "fiber overbuild", "linear TV", "streaming",
    ],
))


# ── Procter & Gamble (PG) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="PG",
    company_name="The Procter & Gamble Company",
    business_model=(
        "Procter & Gamble is the world's largest consumer packaged goods (CPG) company, "
        "selling household and personal care products across five business segments: "
        "Fabric & Home Care (Tide, Gain, Downy, Febreze, Dawn, Cascade — ~35% of sales), "
        "Baby/Feminine/Family Care (Pampers, Always, Tampax, Charmin, Bounty — ~26%), "
        "Beauty (Pantene, Head & Shoulders, Olay, SK-II, Old Spice — ~19%), "
        "Grooming (Gillette, Venus, Braun razors and appliances — ~9%), and "
        "Health Care (Oral-B toothbrushes/toothpaste, Pepto-Bismol, Metamucil, Vicks — ~11%).  "
        "P&G sells through 180+ countries, with North America ~45% of revenue."
    ),
    primary_revenue_drivers=[
        "Fabric & Home Care (~35% of revenue — Tide market share leader; pricing power "
        "through super-premium formulations; Febreze/Downy/Dawn brand loyalty)",
        "Baby/Feminine/Family Care (~26% — Pampers #1 global diaper brand in premium "
        "segment; Always/Tampax feminine care market leader in US/Europe)",
        "Beauty (~19% — SK-II ultra-premium prestige skin care (China exposure); "
        "Pantene/Head & Shoulders hair care mass-market leadership)",
        "Health Care (~11% — Oral-B electric toothbrush market leader; Vicks/DayQuil OTC "
        "pharma with resilient demand)",
        "Grooming (~9% — Gillette global leader in blade cartridge, though market share "
        "eroded by Dollar Shave Club/direct-to-consumer competitors)",
    ],
    recurring_revenue_sources=[
        "Repeat consumable purchases: Tide, Pampers, Oral-B refills are repeat weekly/monthly "
        "household purchases with near-zero switching cost consideration",
        "Blade cartridge system revenue: Gillette razor system creates recurring cartridge "
        "replacement revenue (installed base of razors drives refill attach)",
        "Amazon Subscribe & Save and retail subscription programs amplifying repeat purchase "
        "frequency and reducing churn",
    ],
    rate_sensitivity_note=(
        "P&G trades at ~22-26x forward P/E — a quality defensive premium.  A 100 bps rate "
        "rise compresses the multiple by ~2-3 turns.  P&G carries ~$25-28B long-term debt "
        "at mostly fixed rates, limiting refinancing exposure.  Consumer staples like P&G "
        "are rate-sensitive mainly via valuation (higher rates reduce the present value of "
        "stable, long-duration cash flows) rather than fundamental business sensitivity.  "
        "P&G's ~$9-10B annual FCF and ~2.5% dividend yield are directly compared to "
        "risk-free rates by income investors."
    ),
    inflation_pass_through=(
        "P&G has strong pricing power: the company executed ~10%+ cumulative price increases "
        "in 2022-2023 across most categories, absorbing commodity inflation (pulp, resin, "
        "titanium dioxide) while maintaining volume.  Historical evidence: P&G has raised "
        "prices in 38 of the last 40 years.  The 2023-24 shift from pricing-led to volume-led "
        "growth indicates pricing ceiling reached in some categories — P&G must now grow "
        "through premium mix/innovation rather than list price increases."
    ),
    recession_behavior=(
        "Consumer staples are highly defensive: households continue purchasing Tide, Pampers, "
        "and Oral-B products through recessions, though they may trade down to store brands "
        "in severe downturns.  P&G demonstrated recession resilience in 2009 (organic revenue "
        "growth positive), 2020 (accelerated purchases during COVID).  SK-II (luxury skin "
        "care, primarily China) is more discretionary and recession-vulnerable."
    ),
    major_risks=[
        "Volume pressure from price elasticity: cumulative pricing increases have driven "
        "consumers toward private-label alternatives in Fabric Care and Baby Care — "
        "market share loss to store brands (Kirkland, Amazon Basics) is a structural risk",
        "SK-II China exposure (~$2B+ revenue): SK-II ultra-premium skin care brand has "
        "significant China revenue sensitivity to consumer confidence and competitive "
        "pressure from local Chinese beauty brands (C-beauty)",
        "Gillette market share erosion: Dollar Shave Club (Unilever), Harry's, and "
        "direct-to-consumer brands continue taking blade cartridge share",
        "Innovation execution: P&G must continuously innovate (premium formulations, "
        "sustainable packaging, concentrated formats) to justify price premiums vs private label",
        "Input cost inflation: pulp, resin, surfactants, and titanium dioxide are the "
        "primary COGS components — commodity cycles create margin volatility",
    ],
    valuation_style=(
        "P&G trades at a defensive premium multiple of ~22-26x forward P/E and ~22-24x "
        "EV/EBITDA, pricing in the brand portfolio durability, pricing power, and recession "
        "resilience.  FCF yield (~3-4%) is the primary return driver alongside ~2.5% dividend "
        "yield.  P&G has paid and grown its dividend for 68 consecutive years (Dividend King). "
        "Sum-of-parts analysis values the brand portfolio at 5-7x revenue for the leading "
        "brands in each category."
    ),
    key_metrics=[
        "Organic sales growth (pricing % + volume % decomposition — volume growth recovering "
        "post-pricing cycle is the key near-term metric)",
        "Gross margin recovery (post-commodity inflation; heading toward 52-54% target)",
        "Market share by category (Nielsen/Circana — Tide, Pampers, Gillette share trends)",
        "SK-II sales growth (China travel retail and prestige beauty indicator)",
        "Free cash flow (~$14-15B/yr range)",
        "Dividend growth rate (68 consecutive years of increases)",
        "Emerging markets organic growth (India, Middle East, Africa offsetting China)",
        "Jon Moeller CEO organic growth framework guidance",
    ],
    competitive_advantages=[
        "Brand equity depth: P&G has 23 brands with >$1B in annual revenue — each "
        "is the #1 or #2 market share holder in its category, providing retailer shelf "
        "negotiating leverage and premium pricing support",
        "R&D investment scale: $2B+ annual R&D investment enables patent-protected "
        "formulation superiority (e.g., Tide PODS detergent concentration vs powder) "
        "that private-label manufacturers cannot easily replicate",
        "Global distribution scale: P&G products reach 5B+ consumers across 180 "
        "countries through a network of retailers, distributors, and e-commerce platforms "
        "that gives new product launches instant global reach",
        "Dividend King status: 68+ consecutive years of dividend growth demonstrates "
        "through-cycle pricing power and FCF durability — an unmatched operational track record",
    ],
    business_model_keywords=[
        "Tide", "Pampers", "Gillette", "SK-II", "Oral-B", "Pantene",
        "Fabric Care", "Beauty", "Grooming", "organic sales growth",
        "pricing", "volume", "private label", "Jon Moeller", "Dividend King",
        "gross margin", "commodity", "consumer staples", "brand equity",
    ],
    moat_type=["brand", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── SLB (Schlumberger) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SLB",
    company_name="SLB (formerly Schlumberger Limited)",
    business_model=(
        "SLB is the world's largest oilfield services company, providing technology, "
        "integrated project management, and information solutions to the global oil and "
        "gas industry.  The company operates through four divisions: Digital & Integration "
        "(AI-powered reservoir intelligence, cloud data platforms — Delfi, Lumi), "
        "Reservoir Performance (well stimulation, completions, intervention), "
        "Well Construction (drilling, cementing, well integrity), and "
        "Production Systems (surface/subsea production equipment, artificial lift, "
        "integrated production management).  ~80% of revenue is generated internationally "
        "(Middle East, Africa, Asia Pacific, Europe/CIS) vs North America onshore."
    ),
    primary_revenue_drivers=[
        "Well Construction (~35% of revenue — drilling fluids, directional drilling, "
        "completion tools; offshore and onshore market leader)",
        "Production Systems (~25% — surface production equipment, subsea trees, "
        "manifolds; high-margin long-cycle offshore equipment)",
        "Digital & Integration (~20% — Delfi digital platform, Lumi data analytics, "
        "integrated project management contracts, AI reservoir characterization)",
        "Reservoir Performance (~20% — pressure pumping/fracturing, wireline formation "
        "evaluation, reservoir sampling and testing)",
    ],
    recurring_revenue_sources=[
        "Long-cycle international offshore contracts (integrated project management "
        "with NOCs — multi-year, fixed-fee with performance bonuses)",
        "Delfi/Lumi digital SaaS license fees (cloud-based reservoir characterization "
        "tools with growing recurring revenue from NOC and E&P customers)",
    ],
    rate_sensitivity_note=(
        "SLB is primarily correlated with oil price and E&P CapEx rather than interest "
        "rates.  A 100 bps rate rise has minimal direct impact on SLB's earnings; the "
        "relevant sensitivity is Brent crude price — SLB management has guided that the "
        "current cycle is sustainable above $60/bbl Brent due to structural underinvestment "
        "in energy supply.  SLB carries ~$10-12B of long-term debt at mostly fixed rates.  "
        "Higher rates increase the cost of NOC and E&P customer project financing, "
        "potentially delaying project FIDs (final investment decisions) at the margin."
    ),
    inflation_pass_through=(
        "Moderate: SLB has pricing leverage in tight service markets (offshore deepwater "
        "requires specialized equipment and expertise) but faces pushback in North America "
        "onshore (highly commoditized pressure pumping market).  Technology differentiation "
        "via Digital & Integration allows higher-margin contracts.  Input cost inflation "
        "(steel, energy, labor) is partially passed through via pricing on new contracts."
    ),
    recession_behavior=(
        "Oilfield services revenue is highly correlated with E&P capital budgets, which "
        "are oil-price dependent.  A severe oil price correction (~50%+ from peak) triggers "
        "customer budget cuts within 2-3 quarters, directly reducing SLB revenue.  "
        "Long-cycle international projects (deepwater, LNG) are more resilient than "
        "short-cycle North America onshore.  SLB's 2020 revenue fell ~28% as COVID "
        "crashed oil demand — the company cut 21,000 jobs to manage costs.  Digital "
        "segment provides some counter-cyclical cushion."
    ),
    major_risks=[
        "Oil price collapse: Brent/WTI below $65/bbl would trigger E&P budget cuts "
        "reducing SLB drilling and completions revenue; breakeven is ~$45-50/bbl Brent "
        "for international project profitability",
        "North America onshore competitive intensity: pressure pumping is highly "
        "commoditized with low barriers to entry; EBITDA margins ~20% vs international ~25%",
        "National oil company (NOC) concentration: Saudi Aramco, ADNOC, PDVSA, and "
        "other NOCs represent ~40% of revenue — political/geopolitical NOC budget changes "
        "directly impact SLB results",
        "Energy transition risk: long-term decline in fossil fuel investment reduces "
        "the global oilfield services TAM over a 10-20 year horizon",
        "Digital competition from Halliburton, Baker Hughes, and pure-play tech companies "
        "offering reservoir analytics at lower price points",
    ],
    valuation_style=(
        "SLB trades at ~14-18x forward P/E and ~10-12x EV/EBITDA — a cyclical industrial "
        "multiple with an oil-services premium for international exposure.  The Digital "
        "& Integration segment justifies a partial tech multiple as SaaS-like subscription "
        "revenue grows.  Key re-rating catalyst: Digital segment reaching >25% of revenue "
        "and demonstrating margin accretion, sustained international E&P cycle supporting "
        "multi-year earnings growth.  De-rating risk: oil price decline, Middle East "
        "geopolitical disruption reducing NOC CapEx."
    ),
    key_metrics=[
        "International revenue growth (Middle East/Asia/Africa — core growth engine)",
        "EBITDA margin by division (target 25%+ blended; Digital highest margin)",
        "Digital & Integration revenue growth rate (proxy for software transition progress)",
        "North America vs International revenue mix (international = higher margin)",
        "Offshore vs onshore revenue mix (offshore = higher pricing leverage)",
        "Free cash flow conversion (FCF/Net Income target >80%)",
        "Oil price (Brent WTI) — primary macro driver of E&P CapEx decisions",
        "Subsea backlog and book-to-bill ratio",
    ],
    competitive_advantages=[
        "Deepwater technology leadership: SLB's subsea Production Systems and directional "
        "drilling tools are the preferred choice for technically complex ultra-deepwater "
        "projects — differentiated from Halliburton and Baker Hughes in sub-salt formations",
        "Delfi/Lumi digital tools: cloud-native reservoir characterization with AI-powered "
        "geology and geomechanics that integrates disparate NOC data sources — creates "
        "switching costs once data is ingested",
        "International NOC relationships: 60+ years of operating in challenging basins "
        "(Saudi Arabia, Russia, Iraq, Kazakhstan) builds institutional trust that no "
        "new entrant can replicate quickly",
    ],
    business_model_keywords=[
        "oilfield services", "Delfi", "Lumi", "Well Construction", "Production Systems",
        "Reservoir Performance", "digital", "Digital & Integration", "deepwater",
        "offshore", "directional drilling", "reservoir characterization",
        "NOC", "Olivier Le Peuch", "artificial lift", "subsea",
        "international", "E&P", "Brent", "completions",
    ],
))


# ---------------------------------------------------------------------------
# Severity-2 profiles — 13 companies scoring Q:1–3 in 50-company validation
# (commit 001092e baseline run, 2026-06-02)
# ---------------------------------------------------------------------------

_register(CompanyKnowledgeProfile(
    ticker="HON",
    company_name="Honeywell International Inc.",
    business_model=(
        "Honeywell is a diversified industrial technology company with four segments: "
        "Aerospace Technologies (jet engines, avionics, defense electronics — ~37% of "
        "revenue), Industrial Automation (process automation, sensing, connected "
        "buildings — ~28%), Building Automation (fire, security, HVAC controls, "
        "building management systems — ~22%), and Energy and Sustainability Solutions "
        "(UOP refining catalysts, renewable fuels, carbon capture — ~13%).  Honeywell "
        "sells high-margin software-enabled products and long-cycle aftermarket services "
        "across multiple verticals, with recurring revenue from installed-base maintenance "
        "contracts and software subscriptions.  CEO Vimal Kapur is executing a 'Honeywell "
        "Accelerator' operating system focused on organic growth, margin expansion, and "
        "capital returns.  In 2024 Honeywell announced plans to spin off the Advanced "
        "Materials business and explore separation of its Aerospace segment."
    ),
    primary_revenue_drivers=[
        "Aerospace Technologies (~37%): commercial aerospace OEM and aftermarket "
        "(Garrett turbochargers, avionics suites, auxiliary power units, cabin "
        "environmental controls); defense electronics, cockpit systems",
        "Industrial Automation (~28%): Experion distributed control systems, "
        "process automation software, measurement/sensing for oil & gas and "
        "chemicals; Honeywell Forge IIoT analytics platform",
        "Building Automation (~22%): fire detection, access control, HVAC controls, "
        "Niagara building management platform; Healthy Buildings air quality monitoring",
        "Energy and Sustainability Solutions (~13%): UOP licensing (refining "
        "catalysts, polypropylene process technology), sustainable aviation fuel "
        "technology, connected worker safety solutions",
    ],
    recurring_revenue_sources=[
        "Aerospace aftermarket parts and MRO services (~60% of Aero segment) — "
        "long-term repair/overhaul contracts with airlines and MRO shops",
        "Software subscriptions: Honeywell Forge, Experion, Niagara framework "
        "— connected buildings and industrial automation recurring license fees",
        "UOP technology licensing and catalyst royalties — repeat business "
        "as refineries replace catalysts on fixed maintenance cycles",
        "Long-term defense maintenance contracts and government program of "
        "record revenues (multi-year DoD and NATO platform production)",
    ],
    rate_sensitivity_note=(
        "Honeywell has moderate interest rate sensitivity.  Higher rates raise the "
        "cost of commercial aerospace financing (reducing airline orders at the margin), "
        "but Honeywell's long-cycle defense and aftermarket revenue buffers the impact.  "
        "The building automation segment benefits from infrastructure investment; rate "
        "hikes can delay commercial construction, softening new building installations.  "
        "Honeywell carries ~$16B of long-term debt at mostly fixed rates, so a 100 bps "
        "rate rise has minimal near-term interest expense impact."
    ),
    inflation_pass_through=(
        "Strong in aerospace: OEM contracts index to raw material and labor cost "
        "escalators; aftermarket pricing is set at OEM + markup on proprietary parts.  "
        "Moderate in process automation: long-term contracts with pricing renegotiation "
        "at renewal.  UOP catalyst pricing is tied to feedstock commodity indices, "
        "providing natural inflation pass-through.  Overall, Honeywell's technology "
        "differentiation supports above-inflation price increases in most segments."
    ),
    recession_behavior=(
        "Partially defensive: defense electronics and government aftermarket are "
        "recession-resistant.  Commercial aerospace new OEM orders decline in recessions "
        "(airlines defer capex), but installed-base aftermarket (MRO/parts) remains "
        "relatively stable as existing fleets must be maintained.  Process automation "
        "and building automation experience order softness when industrial CapEx is cut.  "
        "Honeywell's diversification across aerospace, buildings, and industrials reduces "
        "cyclicality relative to pure-play industrial peers."
    ),
    major_risks=[
        "Commercial aerospace cycle: new aircraft production cuts by Boeing/Airbus "
        "reduce Honeywell OEM revenue; Honeywell Aerospace Technologies is ~30% OEM",
        "Boeing 737 MAX and 787 production disruptions directly impact Honeywell "
        "avionics and auxiliary power unit shipments",
        "Spin-off execution risk: separating Advanced Materials and potentially "
        "Aerospace creates dis-synergy risk and management distraction during transition",
        "Industrial automation competition from Emerson, ABB, Siemens, and "
        "Rockwell Automation in process control and building management systems",
        "UOP refining technology long-term headwind from energy transition as "
        "refinery capex shrinks with declining fossil fuel demand",
        "China exposure (~10% of revenue): geopolitical risk of export controls "
        "limiting sales of avionics and process automation to Chinese customers",
    ],
    valuation_style=(
        "Honeywell trades at ~20-24x forward P/E and ~15x EV/EBITDA — an industrial "
        "conglomerate with a software/technology premium versus pure-play cyclicals.  "
        "The portfolio transformation narrative (higher-margin software, aerospace "
        "aftermarket, sustainability) supports the premium versus diversified industrials.  "
        "Key re-rating catalyst: successful spin-offs unlocking sum-of-parts value; "
        "Aerospace segment trading at 25x+ as a pure-play.  De-rating risk: "
        "commercial aerospace OEM weakness, missed margin expansion targets."
    ),
    key_metrics=[
        "Organic revenue growth by segment (Aerospace, Industrial Automation, "
        "Building Automation, Energy Solutions)",
        "Segment margin expansion (target 25%+ adjusted EBIT margin long-term)",
        "Honeywell Forge and connected software ARR growth",
        "Aerospace aftermarket vs OEM revenue split (aftermarket more stable)",
        "UOP licensing backlog and catalyst cycle timing",
        "Free cash flow conversion (target 100%+ of net income)",
        "Spin-off progress: Advanced Materials separation timeline",
        "Defense backlog and book-to-bill ratio",
    ],
    competitive_advantages=[
        "Avionics and cockpit technology: Honeywell's Primus Epic and Anthem "
        "integrated cockpit suites are standard on thousands of business jets "
        "and regional aircraft, creating deep OEM-to-aftermarket lock-in",
        "Niagara building automation framework: open-protocol BMS platform "
        "with 500M+ connected data points — the industry standard for integrating "
        "disparate building systems, used by integrators worldwide",
        "UOP technology moat: 100+ years of refining and petrochemical process "
        "IP (Selexol, Benficat, Oleflex) with proprietary catalysts requiring "
        "Honeywell replacement — high switching costs once a plant is licensed",
        "Honeywell Forge IIoT: industrial analytics platform connecting millions "
        "of sensors across refineries and industrial plants, generating data "
        "network effects that deepen customer switching costs",
    ],
    business_model_keywords=[
        "Vimal Kapur", "Honeywell Accelerator", "Aerospace Technologies",
        "Industrial Automation", "Building Automation", "Energy and Sustainability",
        "UOP", "Experion", "Niagara", "Honeywell Forge", "avionics", "auxiliary power unit",
        "process automation", "connected buildings", "aftermarket", "spin-off",
        "Advanced Materials", "sustainable aviation fuel", "SAF",
        "Garrett", "defense electronics", "IIoT",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="CRM",
    company_name="Salesforce Inc.",
    business_model=(
        "Salesforce is the world's largest CRM software company, providing cloud-based "
        "customer relationship management, sales automation, marketing, analytics, and "
        "AI-powered enterprise software.  The company operates through a unified "
        "'Customer 360' platform spanning Sales Cloud, Service Cloud, Marketing Cloud, "
        "Commerce Cloud, Data Cloud, and MuleSoft integration middleware.  In 2025 "
        "Salesforce launched Agentforce — autonomous AI agents embedded across the "
        "platform that perform tasks without human intervention.  The revenue model is "
        "subscription-based SaaS with multi-year enterprise contracts (average contract "
        "term 2-3 years), creating predictable recurring revenue.  Marc Benioff "
        "(founder and CEO) has positioned Salesforce as the leading 'agentic AI' "
        "enterprise platform.  Key acquisitions include Slack ($27.7B), Tableau ($15.7B), "
        "and MuleSoft ($6.5B), which are integrated into the Data Cloud ecosystem."
    ),
    primary_revenue_drivers=[
        "Sales Cloud (~23% of subscription revenue): CRM opportunity and pipeline "
        "management, Einstein Sales AI, revenue intelligence",
        "Service Cloud (~22%): customer service automation, Einstein bots, "
        "digital engagement, field service management",
        "Platform & Other / Data Cloud (~19%): Salesforce Platform (Force.com), "
        "Heroku, MuleSoft integration, Data Cloud CDP (customer data platform)",
        "Marketing & Commerce Cloud (~15%): Marketing Cloud engagement, "
        "Pardot B2B marketing, Commerce Cloud order management",
        "Slack (~10%): enterprise messaging, workflow automation, channel-based "
        "collaboration replacing email in enterprise workflows",
        "Tableau (~7%): business intelligence and data visualization",
    ],
    recurring_revenue_sources=[
        "Multi-year enterprise SaaS contract fees (~93% of total revenue) — "
        "average annual contract value $150K+; Fortune 500 customers auto-renew",
        "Agentforce usage-based revenue: AI agent 'conversations' priced per "
        "1,000 interactions (~$2/conversation) — new consumption-based layer atop license fees",
    ],
    rate_sensitivity_note=(
        "Salesforce is a long-duration growth asset — higher rates directly "
        "compress its P/E multiple (DCF present value of future cash flows declines).  "
        "Operationally, higher rates raise enterprise IT budget scrutiny; CFOs "
        "pressure software vendors on ROI, slowing deal cycles.  However, Salesforce's "
        "mission-critical CRM seat penetration creates sticky renewals even in tight "
        "budget environments.  Net revenue retention ~105-110% reflects upsell resilience."
    ),
    inflation_pass_through=(
        "Strong: Salesforce has shifted from volume-based growth to price-led "
        "growth.  In FY2023-24 the company raised list prices ~9% on core clouds, "
        "expanded premium Einstein AI add-on modules at higher price points, and "
        "introduced consumption-based Agentforce pricing.  Near-zero marginal cost "
        "of software delivery means inflation in labor costs is manageable through "
        "productivity; gross margins consistently 75%+."
    ),
    recession_behavior=(
        "Moderately resilient: CRM seat licenses are deeply embedded in enterprise "
        "sales and service operations — removing Salesforce disrupts core revenue "
        "workflows, making churn during recessions relatively low (~5-8% gross churn).  "
        "However, new logo growth slows, deal cycles extend, and seat expansion "
        "contracts face renegotiation.  Salesforce's FY2024 'profitable growth' pivot "
        "(operating margin expansion from 3% to 30%) demonstrated the company can "
        "prioritize profitability over headcount growth when macro tightens."
    ),
    major_risks=[
        "AI disruption: Microsoft Copilot (embedded in Teams/Office) and SAP/Oracle "
        "AI integrated suites could reduce CRM standalone value proposition",
        "Agentforce monetization uncertainty: usage-based consumption pricing "
        "ramp is unpredictable; enterprise adoption requires workflow redesign",
        "Macro-driven deal elongation: enterprise software purchasing freezes "
        "during recessions disproportionately hit new logo and expansion bookings",
        "Salesforce's acquisitions (Slack, Tableau, MuleSoft) have underperformed "
        "revenue growth expectations relative to acquisition price",
        "Competition from HubSpot (SMB CRM), Microsoft Dynamics (enterprise), "
        "and vertical SaaS CRM providers eroding market share at the edges",
    ],
    valuation_style=(
        "Salesforce trades at ~25-30x forward P/E and ~20-25x EV/FCF — a "
        "profitable growth multiple reflecting 15-17% revenue growth and 30%+ "
        "non-GAAP operating margins.  The Agentforce AI agent monetization "
        "represents a potential step-change in ARPU that could re-rate the stock "
        "toward 30x+ if consumption revenue ramps.  Key metrics: cRPO (current "
        "remaining performance obligations) as forward revenue indicator, "
        "Agentforce paid seats/conversations, and Data Cloud ARR growth."
    ),
    key_metrics=[
        "Current remaining performance obligations (cRPO) — leading indicator "
        "of near-term bookings health",
        "Net revenue retention rate (target 105-110%+) — measures upsell/expansion",
        "Non-GAAP operating margin (target 33%+ in FY2025)",
        "Agentforce paid customer count and conversation volume",
        "Data Cloud net new logos and ARR",
        "Free cash flow margin (target 30%+)",
        "Attrition rate and logo churn by customer size",
    ],
    competitive_advantages=[
        "Customer 360 suite breadth: Sales + Service + Marketing + Data Cloud "
        "integrated on a single interface forces competitors to replicate an entire "
        "suite rather than displace a single point solution — the largest moat",
        "Trailhead community and AppExchange ecosystem: 10M+ certified Salesforce "
        "developers and administrators create a massive talent pool and switching cost — "
        "enterprises cannot easily retrain their Salesforce-skilled workforce",
        "Data Cloud advantage: Salesforce has more enterprise customer interaction "
        "data than any single competitor (1 trillion+ records processed daily) — "
        "powers more accurate AI models for Einstein and Agentforce",
    ],
    business_model_keywords=[
        "Agentforce", "Customer 360", "Sales Cloud", "Service Cloud", "Data Cloud",
        "MuleSoft", "Tableau", "Slack", "Marc Benioff", "Einstein AI",
        "CRM", "remaining performance obligations", "RPO", "cRPO",
        "net revenue retention", "autonomous agents", "agentic AI",
        "Trailhead", "AppExchange", "non-GAAP operating margin",
        "Marketing Cloud", "Commerce Cloud",
    ],
    moat_type=["switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="low",
    binary_risk_level="none",
))

_register(CompanyKnowledgeProfile(
    ticker="AXP",
    company_name="American Express Company",
    business_model=(
        "American Express operates as a closed-loop payments network and premium "
        "charge card issuer, combining the roles of card network, card issuer, and "
        "merchant acquirer in a single vertically integrated business.  Unlike Visa/MC "
        "open networks, AmEx directly owns the customer relationship on both sides of "
        "the transaction — issuing cards to consumers (particularly premium and "
        "affluent segments) and signing merchants directly.  Revenue splits roughly: "
        "discount revenue / merchant fees (~50%), net interest income on card loans "
        "and revolving balances (~20%), net card fees (~20%), and other (~10%).  "
        "CEO Stephen Squeri has repositioned AmEx around younger, premium customers — "
        "millennials and Gen Z now represent 75%+ of new card acquisitions.  "
        "The Platinum Card, Gold Card, Business Platinum, and Blue Cash Preferred "
        "are cornerstone products with high annual fee ($250-$695) offset by "
        "premium travel, dining, and lifestyle benefits."
    ),
    primary_revenue_drivers=[
        "Discount revenue / merchant fees (~50%): ~2.4% merchant discount rate "
        "on billed business — premium card acceptance fees from airlines, hotels, "
        "luxury retail, and restaurants; higher than Visa/MC network fees",
        "Net card fees (~20%): $695 Platinum Card, $250 Gold Card, $595 Business "
        "Platinum, $0 Blue Cash — structural shift to fee-based revenue "
        "as premium card holders pay annual fees for curated benefits",
        "Net interest income (~20%): interest on revolving balances — AmEx "
        "underweights revolving borrowers vs traditional issuers (lower credit losses)",
        "Travel and lifestyle benefits partnerships: Delta SkyMiles cobrand "
        "(11M+ cardholders), Hilton Honors, Marriott Bonvoy — cobrands pay AmEx "
        "per acquisition and per transaction",
    ],
    recurring_revenue_sources=[
        "Annual card fees from 145M+ cards in force ($695 Platinum + $250 Gold "
        "creates a near-annuity from cardholders who value the benefits ecosystem)",
        "Delta, Hilton, Marriott cobrand revenue share — multi-year cobrand "
        "agreements with high switching costs (Delta deal renewed through 2029+)",
        "Corporate card program fees from Fortune 500 T&E (travel and entertainment) "
        "management programs — multi-year enterprise contracts",
        "Merchant financing and working capital products — AmEx Business Lending "
        "provides revolving credit to SMB card members",
    ],
    rate_sensitivity_note=(
        "American Express has meaningful interest rate sensitivity on both sides.  "
        "Rising rates increase AmEx's net interest income on card member loans "
        "(floating rate assets repriced upward).  However, higher rates also increase "
        "funding costs (AmEx issues commercial paper and medium-term notes to fund "
        "its balance sheet).  Net: AmEx is modestly rate-sensitive on NII.  "
        "More importantly, rate hikes slow discretionary consumer and T&E spending "
        "(the primary driver of billed business) — a macro headwind to discount revenue."
    ),
    inflation_pass_through=(
        "Natural inflation hedge on discount revenue: higher nominal spending "
        "volumes (airfares, hotel rates, restaurant prices) directly increase AmEx's "
        "percentage-of-spend revenue.  Annual card fee increases ($550→$695 Platinum "
        "in 2023) have been absorbed with minimal churn, demonstrating premium "
        "cardholders' inelastic demand.  Labor and marketing cost inflation is a "
        "headwind but manageable given AmEx's 35%+ pre-tax margin."
    ),
    recession_behavior=(
        "Counter-intuitively resilient due to premium customer base: AmEx's "
        "affluent cardholders have higher job security, lower leverage, and "
        "maintain spending during mild recessions.  However, T&E billed business "
        "(airlines, hotels, restaurants) is highly cyclical and collapsed 60% "
        "during COVID.  Corporate card spending tracks GDP closely.  AmEx "
        "historically shows lower credit losses than mass-market issuers in "
        "recessions due to affluent, lower-leverage cardholder profile."
    ),
    major_risks=[
        "Consumer spending slowdown: T&E billed business (travel, dining) is "
        "the highest-margin revenue stream and most cyclically sensitive",
        "Merchant acceptance friction: ~10% of US merchants still don't accept "
        "AmEx due to higher discount fees — limits TAM vs Visa/Mastercard",
        "Cobrand partner risk: Delta SkyMiles, Hilton Honors are renegotiated "
        "periodically; losing a major cobrand would be a material revenue hit",
        "Credit quality deterioration: rising delinquencies among younger "
        "cardholders (millennial/Gen Z focus) could increase provision expense",
        "Regulation: Durbin Amendment extension to credit cards could cap "
        "interchange fees, directly threatening discount revenue",
    ],
    valuation_style=(
        "AmEx trades at ~16-20x forward P/E — a premium to most-market card "
        "issuers, discount to Visa/Mastercard.  The closed-loop network premium "
        "reflects better data, higher merchant fees, and lower credit losses.  "
        "Key re-rating driver: evidence that millennial/Gen Z cardholders maintain "
        "Platinum/Gold fee payment rates at historical affluent-tier levels.  "
        "EPS growth driven by billed business growth + net card fee expansion "
        "+ NII as card loans grow."
    ),
    key_metrics=[
        "Billed business (total spend on AmEx cards — key revenue driver)",
        "Net card fees growth (annual fee revenue — high-margin recurring)",
        "Cardmember spending per card (reflects premium cardholder engagement)",
        "Net interest yield on card member loans",
        "Provision for credit losses and net write-off rate",
        "Cards in force by product tier (Platinum, Gold, Green, Blue)",
        "New card acquisitions and millennial/Gen Z share",
        "T&E vs everyday spending split (T&E is higher-margin)",
    ],
    competitive_advantages=[
        "Closed-loop network data advantage: AmEx sees both sides of every "
        "transaction (merchant and cardholder), enabling superior fraud detection, "
        "targeted offers, and 10x the merchant analytics of open-network competitors",
        "Premium brand equity: the Centurion Card (Amex Black) and Platinum Card "
        "are aspirational status symbols with pricing power that Visa/MC cannot "
        "replicate — cardholders pay $695/year for membership in the AmEx ecosystem",
        "Benefits ecosystem partnerships: Centurion Lounges, Fine Hotels & Resorts, "
        "Global Lounge Collection — curated benefits AmEx controls and continuously "
        "upgrades, making the card incrementally more valuable each year",
        "Corporate T&E program lock-in: AmEx's Business Travel and Global Corporate "
        "Payments serve thousands of Fortune 500 companies with integrated expense "
        "management — 5-10 year enterprise contracts with high switching costs",
    ],
    business_model_keywords=[
        "billed business", "discount revenue", "net card fees", "closed loop",
        "Stephen Squeri", "Platinum Card", "Gold Card", "Centurion",
        "millennial", "Gen Z", "T&E", "travel and entertainment",
        "Delta SkyMiles", "cobrand", "merchant acceptance",
        "card member spending", "cards in force", "Amex", "American Express",
        "net interest income", "premium cardholder",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="NKE",
    company_name="Nike Inc.",
    business_model=(
        "Nike is the world's largest designer, marketer, and distributor of athletic "
        "footwear, apparel, and equipment.  The company does not manufacture products "
        "directly — it designs products and outsources production to contract factories "
        "in Vietnam (~50%), Indonesia (~20%), and China (~20%).  Revenue channels: "
        "Nike Direct (DTC) including Nike.com, Nike App, and company-owned stores "
        "generates ~45% of total revenue and ~2x the gross margin of wholesale; "
        "wholesale through retailers (Foot Locker, Dick's Sporting Goods, Nordstrom) "
        "provides ~55%.  CEO Elliott Hill returned in October 2024 (replacing John Donahoe) "
        "to restore focus on sport performance, wholesale channel health, and "
        "product innovation.  Key brands: Nike, Jordan Brand (licensed NBA, NFL, "
        "MLB uniforms), Converse (~10% of revenue).  Primary competitor: On Running, "
        "Hoka, New Balance (gaining premium market share); adidas, Puma, Under Armour."
    ),
    primary_revenue_drivers=[
        "Footwear (~68% of revenue): Air Max, Air Force 1, Jordan franchise, "
        "React and ZoomX running platforms; Jordan Brand accounts for "
        "$6.5B+ and growing faster than core Nike brand",
        "Apparel (~27%): performance training apparel, Dri-FIT, Jordan Brand "
        "apparel, Club America/PSG/Chelsea licensed kits",
        "Equipment (~5%): balls, bags, protective gear",
        "Nike Direct (DTC): Nike.com, SNKRS app, Nike App — higher ASP "
        "and gross margin vs wholesale; ~45% revenue share growing",
    ],
    recurring_revenue_sources=[
        "Nike digital ecosystem (300M+ registered users): Nike app and SNKRS drive "
        "higher repeat purchase frequency and first-party data capture vs wholesale",
        "Jordan Brand licensing to NBA, NFL, MLB: exclusive team and league uniform "
        "agreements renewed with escalating fees",
    ],
    rate_sensitivity_note=(
        "Nike has limited direct interest rate sensitivity — the company carries "
        "moderate debt and generates strong free cash flow ($4-5B annually) that "
        "funds dividends and buybacks.  Indirectly, higher rates compress consumer "
        "discretionary spending, particularly for premium footwear ($150+ ASP).  "
        "Rate hikes also increase Nike's hedging costs on foreign currency (Nike "
        "reports in USD but generates ~55% of revenue internationally).  "
        "Valuation compression from higher discount rates is the primary impact "
        "on the growth-oriented multiple."
    ),
    inflation_pass_through=(
        "Moderate: Nike has raised average selling prices 15-20% over the past "
        "3 years on core franchises (Air Force 1, Jordan 1) while maintaining "
        "demand — demonstrating brand pricing power.  However, excess inventory "
        "cycles (2022-23) forced promotional activity, degrading gross margins.  "
        "Input cost inflation (labor, materials, freight) has been partially offset "
        "by DTC channel mix shift (higher margin), strategic pricing, and "
        "cost reduction under the 'Win Now' restructuring program."
    ),
    recession_behavior=(
        "Nike's top-franchise silhouettes (Air Force 1, Jordan 1, Dunk) have "
        "cultural cachet that sustains demand in mild recessions — limited-edition "
        "drops maintain pricing power.  In deeper recessions, consumers trade down "
        "to lower-priced athletic brands (New Balance, adidas, Hoka's lower-end lines).  "
        "Jordan Brand's premium positioning makes it slightly more resilient than core "
        "Nike in downturns.  China represents ~16% of revenue with periodic "
        "geopolitical headwinds impacting China Direct."
    ),
    major_risks=[
        "Share loss to On Running, Hoka, New Balance in premium performance "
        "running: Nike ceded meaningful market share in the $150+ performance "
        "running category between 2020-2024, now attempting a comeback with "
        "Vomero 18 and Pegasus Premium",
        "DTC strategy reversal: Elliott Hill is reinvesting in wholesale "
        "channel health, but rebuilding retailer relationships after 2021-23 "
        "inventory push may take 2-3 years",
        "China geopolitical risk: CITIC backlash from nationalist sentiment "
        "(Chinese consumers prefer Li-Ning, Anta) reduces China Direct potential",
        "Excess inventory cycles: seasonal over-ordering creates markdown "
        "pressure on gross margins every 2-3 years",
        "Labor and sustainability scrutiny: Vietnamese factory labor practices "
        "and carbon footprint are ESG concerns that can affect brand perception",
    ],
    valuation_style=(
        "Nike trades at ~25-30x forward P/E — a premium consumer discretionary "
        "brand multiple reflecting the Jordan franchise pricing power and DTC "
        "mix-shift gross margin opportunity.  The Elliott Hill turn-around "
        "narrative could re-rate the stock toward 32-35x on gross margin "
        "recovery (target return to 46%+ gross margin from current ~44%).  "
        "De-rating risk: continued share loss in performance running, "
        "China weakness, or failure to reignite Jordan innovation pipeline."
    ),
    key_metrics=[
        "Revenue by geography (North America, Europe Middle East & Africa, "
        "China, Asia Pacific Latin America)",
        "Nike Direct vs wholesale revenue split and gross margin differential",
        "Gross margin % (key indicator of DTC mix, pricing, and factory cost)",
        "Inventory growth vs revenue growth (excess inventory signals margin risk)",
        "Jordan Brand revenue growth (premium segment health indicator)",
        "Nike Membership size and purchase frequency",
        "Average selling price (ASP) trends in footwear",
        "China Direct revenue growth (largest single-market swing factor)",
    ],
    competitive_advantages=[
        "Jordan Brand franchise: Michael Jordan's lifetime deal (Nike pays Jordan "
        "~$256M/year) locks in cultural capital that no competitor can replicate — "
        "Jordan retros sell out globally without marketing spend",
        "Athlete endorsement depth: LeBron James, Cristiano Ronaldo, Kylian Mbappé, "
        "Travis Scott — Nike spends $3.5B/year on athletes, creating a moat "
        "competitors cannot economically bridge",
        "SNKRS and consumer data: 300M+ registered user profiles with purchase history "
        "and wishlist data enable hyper-targeted launch allocation and demand "
        "forecasting impossible for DTC-light brands",
    ],
    business_model_keywords=[
        "Jordan Brand", "Nike Direct", "DTC", "SNKRS", "Air Max", "Air Force 1",
        "Elliott Hill", "John Donahoe", "Dunk", "React", "ZoomX",
        "Dri-FIT", "Nike Membership", "wholesale", "Converse",
        "gross margin", "inventory", "China Direct", "performance running",
        "Vomero", "Pegasus", "Win Now", "organic growth",
    ],
    moat_type=["brand", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="low",
    binary_risk_level="none",
))

_register(CompanyKnowledgeProfile(
    ticker="BA",
    company_name="The Boeing Company",
    business_model=(
        "Boeing is a global commercial aircraft manufacturer and defense contractor "
        "with three segments: Commercial Airplanes (BCA — ~45% of revenue), "
        "Defense Space & Security (BDS — ~35%), and Global Services (BGS — ~20%).  "
        "BCA designs and sells narrow-body (737 MAX) and wide-body (787 Dreamliner, "
        "777X) commercial jets to airlines globally; BDS produces military aircraft "
        "(F-15, F/A-18, P-8), satellites, and launch systems; BGS provides aftermarket "
        "maintenance, training, and parts.  CEO Kelly Ortberg (appointed September 2024) "
        "is executing a stabilization plan following the 737 MAX 9 door plug blowout "
        "(January 2024), a seven-week IAM machinist strike (2024), and multiple FAA "
        "production rate limitations.  Boeing's long-term order backlog exceeds 5,600 "
        "aircraft (~$500B), providing multi-year revenue visibility once production "
        "rates normalize."
    ),
    primary_revenue_drivers=[
        "Commercial Airplanes (~45%): 737 MAX 8/9/10 (narrow-body workhorse — "
        "target production rate 38/month by 2025, currently ~25/month post-strike); "
        "787 Dreamliner (wide-body — 5/month production target); 777X (next-gen "
        "wide-body — delayed until 2025+)",
        "Defense Space & Security (~35%): F-15EX Eagle II, F/A-18 Super Hornet, "
        "P-8 Poseidon, KC-46 Pegasus tanker, Space Launch System (SLS), "
        "Starliner crewed spacecraft (development challenges)",
        "Global Services (~20%): aftermarket parts, MRO contracts, pilot/tech "
        "training, modifications — highest-margin segment with recurring revenue",
    ],
    recurring_revenue_sources=[
        "BGS aftermarket parts and MRO: Boeing is the sole-source supplier "
        "for most proprietary 737 and 787 replacement parts — highly recurring, "
        "high-margin (~20% operating margin vs BCA near-breakeven currently)",
        "Long-term US DoD programs: F-15 production, KC-46 tanker, and other "
        "multi-year defense programs provide stable government revenue stream",
    ],
    rate_sensitivity_note=(
        "Boeing has extremely high interest rate sensitivity currently due to its "
        "distressed balance sheet.  Boeing carries ~$53B of long-term debt (post-strike, "
        "post-quality crisis capital raises) and is generating significant FCF deficits "
        "(-$13B in 2024 estimated).  Rising rates increase refinancing costs on "
        "debt maturing in 2025-2027.  Additionally, airline customers finance new "
        "aircraft deliveries — higher rates increase financing costs for airlines, "
        "potentially leading to delivery deferrals, reducing Boeing's cash receipts."
    ),
    inflation_pass_through=(
        "Limited near-term: Boeing's fixed-price defense contracts (KC-46, SLS) "
        "have created billions in cost overruns as labor and materials inflated — "
        "Boeing cannot pass through inflation on legacy fixed-price contracts.  "
        "Commercial aircraft pricing is negotiated at order placement (orders from "
        "2020-2023 were placed at pre-inflation prices, compressing delivery margins).  "
        "New orders benefit from higher list prices; Boeing's 737 MAX list price "
        "has increased ~30% since 2019."
    ),
    recession_behavior=(
        "Highly cyclical: commercial aircraft orders collapse during recessions "
        "as airline traffic falls and carriers cancel/defer deliveries.  However, "
        "Boeing's $500B+ backlog provides 6-8 years of delivery coverage even "
        "with order freezes — near-term delivery rates are more important than "
        "new orders.  Defense revenue (~35%) provides counter-cyclical stability.  "
        "BGS aftermarket is resilient — airlines must maintain existing fleets "
        "regardless of new order activity.  Boeing's 2024 challenges are "
        "company-specific (quality, strike) rather than demand-driven."
    ),
    major_risks=[
        "FAA production certification: Boeing remains under enhanced FAA "
        "oversight with production rate caps on 737 MAX — the path to 38/month "
        "(the earnings recovery target) requires sustained quality metrics "
        "over 6-12 months of demonstrated compliance",
        "Fixed-price defense contract losses: KC-46 Pegasus, Starliner, and "
        "T-7A Red Hawk development programs have collectively lost $10B+ in "
        "pre-tax charges — structural exposure to cost overruns on legacy contracts",
        "Balance sheet stress: $53B of debt with $10B+ annual interest/debt "
        "service requires FCF recovery and potential equity dilution via "
        "additional share issuance",
        "Competitive threat: Airbus A320neo family has taken Boeing's market "
        "share in narrow-body during MAX crises — airlines have diversified away "
        "from Boeing-only fleets",
        "777X certification delay: 777X cost program is 5+ years behind "
        "original schedule, risking large customer defections to A350-1000",
    ],
    valuation_style=(
        "Boeing trades on normalized earnings potential — current earnings are "
        "severely depressed.  On normalization (~38/month 737 + 5/month 787 by "
        "2026-2027), Boeing could generate $10-12/share EPS vs current loss.  "
        "The stock trades at a large discount to historical multiples (20-22x "
        "normalized P/E on $10 EPS = $200-220 price target range widely cited).  "
        "Key risk: capital raises diluting the normalized EPS; delivery "
        "schedule slippage extending the FCF deficit further."
    ),
    key_metrics=[
        "737 MAX monthly production rate (current ~25, target 38/month)",
        "787 Dreamliner monthly production rate (current 3-4, target 5/month)",
        "Free cash flow (deeply negative, target return to positive by 2025-2026)",
        "Net debt and debt-to-EBITDA (leverage recovery timeline)",
        "Commercial backlog (5,600+ aircraft, ~$500B)",
        "BDS fixed-price contract charges (KC-46, T-7A, Starliner)",
        "FAA audit findings and certification milestones",
        "Deliveries per quarter (revenue recognizes at delivery)",
    ],
    competitive_advantages=[
        "737 and 787 installed base: 10,000+ Boeing jets in service create a "
        "captive aftermarket parts and services revenue stream — airlines cannot "
        "easily switch to Airbus-sourced parts for Boeing aircraft",
        "Defense duopoly: Boeing is one of two US prime defense contractors "
        "(with Lockheed Martin) for major manned aircraft programs — sole-source "
        "supplier status on F-15, P-8, and KC-46 programs provides pricing power",
        "Pilot training ecosystem: Boeing's pilot simulators and training centers "
        "worldwide create switching costs — airlines that operate 737 MAX have "
        "invested in Boeing-specific training infrastructure",
    ],
    business_model_keywords=[
        "737 MAX", "787 Dreamliner", "777X", "Kelly Ortberg", "FAA",
        "production rate", "IAM strike", "backlog", "Commercial Airplanes",
        "Defense Space Security", "Global Services", "KC-46", "Starliner",
        "fixed-price contract", "free cash flow", "deliveries",
        "narrow-body", "wide-body", "quality crisis", "door plug",
        "Airbus competition", "F-15", "P-8",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="WMT",
    company_name="Walmart Inc.",
    business_model=(
        "Walmart is the world's largest retailer by revenue, operating through four "
        "business segments: Walmart US (~65% of revenue), Sam's Club (~12%), "
        "Walmart International (~22%), and the rapidly-growing Walmart Global "
        "Advertising / Marketplace (~1%).  The core value proposition — everyday low "
        "prices (EDLP) enabled by supply chain scale — serves over 240M customers "
        "weekly across 10,500+ stores and online channels.  CEO Doug McMillon has "
        "transformed Walmart into an omnichannel retailer: Walmart+ membership "
        "(100M+ members in the US), InHome delivery, online grocery pickup, and "
        "the Walmart Connect advertising platform.  The emerging high-margin revenue "
        "streams (advertising, marketplace seller fees, data monetization via Walmart "
        "Luminate) are restructuring the profit model toward higher-margin business "
        "lines atop the low-margin retail base.  Flipkart (India, ~77% owned) and "
        "Walmex (Mexico/Central America) are Walmart's highest-growth international assets."
    ),
    primary_revenue_drivers=[
        "Walmart US grocery (~60% of US revenue): Walmart is the #1 US grocery "
        "retailer by market share — EDLP grocery drives traffic for higher-margin "
        "general merchandise; fresh food, private label Great Value / Bettergoods",
        "Sam's Club membership fees and merchandise: warehouse club model "
        "with $50-$110 annual membership generating high-margin recurring income; "
        "Scan & Go digital checkout raising member engagement",
        "Walmart+ subscription: $12.95/month ($98/year) — unlimited free delivery, "
        "fuel discounts, Paramount+ streaming — growing premium membership base",
        "Walmart Connect advertising platform: ~$3-4B in annual high-margin "
        "advertising revenue from CPG brands paying for sponsored search and "
        "display ads in Walmart's physical and digital channels",
    ],
    recurring_revenue_sources=[
        "Walmart+ subscriptions (~$3B+ annual run rate) — monthly/annual "
        "membership with high retention among grocery-loyal households",
        "Sam's Club membership fees (~$2B annually) — near-100% gross margin "
        "line that grows with membership and renewal rate",
        "Walmart Luminate data licensing: CPG companies pay for POS scan data, "
        "customer basket analytics, and predictive replenishment insights",
        "Marketplace seller fees: 3P seller GMV growing 30%+ as Walmart builds "
        "Amazon-like marketplace; seller fees are high-margin revenue",
    ],
    rate_sensitivity_note=(
        "Walmart benefits from a flight-to-value in high-rate environments: "
        "consumer spending pressure drives trade-down from premium grocers (Whole "
        "Foods, Publix) and specialty retailers to Walmart EDLP.  Walmart's "
        "consumer base over-indexes in lower-income households that react strongly "
        "to rate/inflation pressure by switching to value channels.  "
        "Walmart's balance sheet is investment-grade; rate impact on debt "
        "service is minimal.  Higher rates compress Walmart's P/E given its "
        "growth-oriented multiple (~25-30x) vs its grocery-anchored earnings base."
    ),
    inflation_pass_through=(
        "Strong competitive advantage during inflation: Walmart's scale "
        "($600B+ annual purchasing) gives it leverage to hold supplier cost "
        "increases below inflation.  Private label (Great Value, Equate, "
        "Sam's Member's Mark) expands in inflationary cycles as consumers "
        "trade down from national brands.  Rollback pricing investments absorb "
        "some inflation to maintain price gaps vs competitors."
    ),
    recession_behavior=(
        "Counter-cyclical: Walmart gains grocery market share in recessions "
        "and inflationary environments as consumers trade down to EDLP.  "
        "General merchandise (electronics, apparel) declines in recessions, "
        "but grocery resilience offsets GM weakness.  Walmart's 2009 recession "
        "performance (+3% comp growth) and 2022-23 inflation benefit demonstrate "
        "the defensive positioning.  Sam's Club membership retention is very "
        "high during recessions — warehouse club value proposition strengthens."
    ),
    major_risks=[
        "Amazon grocery competition: Amazon Fresh and Whole Foods growing; "
        "Amazon Prime delivery convenience competes directly with Walmart+",
        "General merchandise margin compression from excess inventory cycles "
        "and promotional activity needed to clear discretionary goods",
        "Flipkart valuation risk: India e-commerce competitive intensity from "
        "Amazon India, JioMart, and Reliance Retail — Flipkart margins remain "
        "deeply negative",
        "Shrink and theft: organized retail crime increasing shrink as a "
        "percentage of sales, particularly in urban locations",
        "Wage inflation: Walmart raised US store associate minimum wage to "
        "$15/hour+ — ongoing labor cost pressure in a tight job market",
    ],
    valuation_style=(
        "Walmart trades at ~25-30x forward P/E — a premium to traditional "
        "grocery retail (15x) justified by the advertising/marketplace/data "
        "earnings mix shift toward higher-margin businesses.  Walmart is "
        "increasingly valued as a technology/media company layered on top "
        "of its retail operations.  EPS growth ~10-12% driven by operating "
        "leverage, advertising growth, and international (Flipkart, Walmex) optionality."
    ),
    key_metrics=[
        "Walmart US comparable sales growth (store + eComm)",
        "eCommerce penetration (target 25%+ of Walmart US revenue)",
        "Walmart+ membership count and renewal rate",
        "Sam's Club comparable sales and membership income",
        "Global advertising revenue (Walmart Connect + Sam's) — high-margin indicator",
        "Gross margin % (structural improvement from ad/marketplace mix shift)",
        "Operating income by segment",
        "Flipkart GMV and path to profitability",
    ],
    competitive_advantages=[
        "Supply chain scale: Walmart's $600B annual purchasing volume creates "
        "procurement leverage no retailer can match — private label manufacturing "
        "relationships, direct sourcing, and CPFR (collaborative planning, "
        "forecasting, replenishment) with top CPG suppliers",
        "Physical-digital convergence: 90% of US consumers live within 10 miles "
        "of a Walmart — enables same-day grocery delivery, pickup, and pharmacy "
        "services that pure-play e-commerce cannot replicate cost-effectively",
        "First-party consumer data: 240M weekly customers, 100M+ Walmart+ "
        "members, Scan & Go at Sam's Club — the most comprehensive US consumer "
        "basket data outside Amazon",
        "EDLP pricing model: Walmart's always-on low pricing strategy builds "
        "customer trust and eliminates the promotional cycle that erodes "
        "competitors' margins",
    ],
    business_model_keywords=[
        "Doug McMillon", "Walmart+", "EDLP", "Sam's Club", "Flipkart",
        "Walmex", "Walmart Connect", "Walmart Luminate", "InHome",
        "everyday low prices", "Great Value", "Bettergoods", "Member's Mark",
        "comp sales", "eCommerce", "grocery", "advertising",
        "marketplace", "pickup and delivery", "private label",
        "scan and go",
    ],
    moat_type=["scale_economy", "brand", "data_advantage"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="capital_intensive",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))

_register(CompanyKnowledgeProfile(
    ticker="KO",
    company_name="The Coca-Cola Company",
    business_model=(
        "Coca-Cola is a global beverage brand company operating an asset-light "
        "concentrate/syrup model.  The company manufactures and sells branded "
        "concentrates and syrups to licensed bottling partners worldwide "
        "(Coca-Cola FEMSA, Coca-Cola Europacific Partners, Arca Continental, "
        "Swire Coca-Cola), who produce, bottle, and distribute the finished "
        "beverages.  This model generates industry-leading operating margins (~30%) "
        "with minimal capital requirements.  CEO James Quincey has repositioned "
        "Coca-Cola around a 'total beverage company' strategy: Sparkling Soft "
        "Drinks (Coke, Sprite, Fanta — ~50%), Juice/Dairy/Plant-based (~15%), "
        "Hydration/Sports/Coffee/Tea (~25%), and Emerging categories (~10%).  "
        "Pricing discipline and revenue growth management (RGM) have driven "
        "consistent organic growth through a mix of volume and price/mix."
    ),
    primary_revenue_drivers=[
        "Sparkling soft drinks concentrate (~50% of net operating revenue): "
        "Coke trademark (Original, Zero Sugar, Coke Light), Sprite, Fanta, "
        "Schweppes — pricing leverage from global brand scale",
        "Juice, Dairy, Plant-based (~15%): Minute Maid, Simply, Innocent, "
        "fairlife ultra-filtered milk — higher-growth premium segments",
        "Hydration, Sports, Coffee, Tea (~25%): Powerade, Smartwater, "
        "Aquarius, Georgia Coffee (Japan), Honest Tea, Fuze Tea",
        "Monster Energy equity investment (~17% ownership): AmRest joint "
        "ventures and Monster distribution agreement contributing equity income",
    ],
    recurring_revenue_sources=[
        "Concentrate/syrup supply agreements with bottlers — multi-decade "
        "franchise agreements create a perpetual revenue stream tied to "
        "bottler sales volume; Coca-Cola sets concentrate price annually",
        "Fountain/post-mix syrup: McDonald's, Subway, Burger King, Wendy's "
        "and other QSR chains are long-term fountain customers with "
        "proprietary dispensing equipment creating switching costs",
        "Refranchising income: Coca-Cola receives licensing fees and "
        "equity income from its partially-owned bottling partners globally",
        "Powerade and Smartwater retail distribution through bottler network "
        "— brand growth translates to royalty-equivalent economics",
    ],
    rate_sensitivity_note=(
        "Coca-Cola is a classic defensive, low-interest-rate-sensitivity business.  "
        "Revenue is primarily US-dollar concentrate (priced to bottlers in USD) "
        "but 60%+ of income comes from international markets with translation "
        "FX risk.  A 100 bps rate rise minimally impacts Coca-Cola's operations "
        "but compresses its premium multiple (Coke trades at 22-25x P/E as a "
        "quasi-bond/defensive equity).  Coke carries ~$35B of long-term debt; "
        "most is fixed-rate so refinancing risk is limited near-term."
    ),
    inflation_pass_through=(
        "Very strong over time: Coca-Cola has raised concentrate prices to "
        "bottlers consistently above inflation — the brand's cultural status "
        "gives pricing power few consumer staples companies match.  Coke Zero "
        "Sugar's 10%+ price premium to Diet Coke demonstrates successful "
        "premiumization.  In 2021-2023, Coca-Cola implemented 12-14% price "
        "increases globally with volume declines of only 1-3%, a highly "
        "favorable price elasticity outcome."
    ),
    recession_behavior=(
        "Highly defensive: carbonated soft drinks are affordable treats — "
        "a $2 Coke at McDonald's is one of the last discretionary items "
        "consumers eliminate.  Vending, fountain, and grocery channel "
        "resilience across economic cycles has been demonstrated across "
        "multiple recessions.  Coca-Cola returned to dividend growth through "
        "the 2008-2009 recession and COVID (62+ consecutive years of "
        "dividend increases — Dividend King status).  Latin America and "
        "Africa volumes tend to grow even in US recessions."
    ),
    major_risks=[
        "Health and wellness secular shift: sugar/calorie concerns reducing "
        "sparkling category volume in developed markets; growth requires "
        "accelerating Zero Sugar (currently 15% of trademark volume) and "
        "premium water/sports categories",
        "Bottler dependency: if major bottlers (CCEP, FEMSA) face financial "
        "stress or consolidate, Coca-Cola's distribution execution is at risk",
        "Emerging market currency volatility: ~60% of revenue from international "
        "markets with devaluing currencies (Argentina, Nigeria, Egypt) — "
        "FX translation headwind can mask organic growth",
        "Water scarcity and sustainability pressure: production requires "
        "significant water; regulatory and reputational risk in water-stressed regions",
        "Sugar and plastic packaging regulations in multiple markets "
        "(sugar taxes in UK, Mexico, South Africa) reduce demand",
    ],
    valuation_style=(
        "Coca-Cola trades at ~22-25x forward P/E — a defensive consumer staples "
        "premium reflecting its Dividend King status, brand durability, and "
        "near-monopoly positioning in global sparkling beverages.  "
        "Organic revenue growth of 5-8% (price/mix + volume) drives mid-single-digit "
        "EPS growth + 3% dividend yield = total return of 8-10%.  "
        "Re-rating catalyst: fairlife ultra-premium dairy scaling to $1B+; "
        "Zero Sugar reaching 25%+ of trademark volume.  De-rating risk: "
        "sugar tax acceleration, volume share loss to Pepsi in fountain."
    ),
    key_metrics=[
        "Organic revenue growth (price/mix + volume — key performance indicator)",
        "Unit case volume by category and geography",
        "Price/mix realization (quarterly — measures pricing execution)",
        "Comparable EPS growth in constant currency",
        "Refranchising progress and bottler system health",
        "Coke Zero Sugar volume growth % (premiumization indicator)",
        "fairlife net revenue (premium dairy — new growth engine)",
        "Free cash flow and dividend growth rate",
    ],
    competitive_advantages=[
        "Coca-Cola brand: among the world's 3 most recognized brands — "
        "120+ years of cultural relevance, McDonald's partnership, FIFA/Olympics "
        "sponsorship, and universal distribution in 200+ countries creates an "
        "unassailable brand moat",
        "Bottler network system: 300+ franchise bottling partners with "
        "exclusive territorial rights, pre-built cold chain, and established "
        "trade relationships — Coca-Cola's concentrate model requires no capital "
        "to access this $40B+ global distribution machine",
        "Fountain channel lock-in: McDonald's, Subway, Burger King, and major "
        "stadium/cinema chains use proprietary Coke fountain equipment — "
        "switching costs are high (equipment replacement, customer habit disruption)",
        "Premiumization platform: Smartwater, fairlife, innocent (UK), and Costa "
        "Coffee provide entry points across premium beverage categories where "
        "Pepsi has limited equivalent scale",
    ],
    business_model_keywords=[
        "James Quincey", "concentrate", "bottler", "unit case volume",
        "organic revenue growth", "price/mix", "Coke Zero Sugar",
        "Sprite", "Fanta", "fairlife", "Smartwater", "Minute Maid",
        "CCEP", "FEMSA", "refranchising", "fountain", "McDonald's",
        "Dividend King", "sparkling", "trademark Coke",
        "hydration", "sports", "still beverages",
    ],
    moat_type=["brand", "scale_economy", "switching_cost"],
    revenue_model="licensing",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))

_register(CompanyKnowledgeProfile(
    ticker="CVX",
    company_name="Chevron Corporation",
    business_model=(
        "Chevron is a global integrated energy company operating across the entire "
        "oil and gas value chain: Upstream (exploration, production — ~80% of earnings), "
        "Downstream (refining, marketing — ~15%), and Chemicals/Other (~5%).  "
        "CEO Mike Wirth runs Chevron with a 'returns-focused capital discipline' "
        "strategy: growing production in the Permian Basin (DJ Basin, Gulf of Mexico), "
        "expanding international LNG and deepwater assets (Tengiz Kazakhstan expansion "
        "— TCO project, Gorgon/Wheatstone LNG Australia), and returning excess capital "
        "to shareholders via aggressive buybacks and dividend growth.  "
        "The proposed Hess acquisition ($53B, regulatory dispute with ExxonMobil "
        "over Guyana assets) would add high-value Guyana deepwater barrels.  "
        "Chevron's 'TCOP' (total cost of production) target of $35-40/BOE "
        "provides significant free cash flow at $65+ Brent."
    ),
    primary_revenue_drivers=[
        "Permian Basin upstream: Chevron targets 1M+ BOE/day from Permian "
        "by 2025 — lowest-cost shale basin in the world (~$10-15/BOE operating cost)",
        "TCO (Tengizchevroil) Kazakhstan: Tengiz Future Growth Project (FGP) "
        "adding 260,000 BOE/day; TCO is one of the world's largest oil fields",
        "Australia LNG (Gorgon, Wheatstone): long-term JCC-linked LNG contracts "
        "supplying Asian utilities — premium pricing above spot LNG",
        "Gulf of Mexico deepwater: Anchor, Whale, and Jack/St. Malo projects "
        "providing long-cycle barrels at $15-20/BOE finding cost",
    ],
    recurring_revenue_sources=[
        "Long-term LNG sales agreements (Gorgon/Wheatstone) with JCC-linked "
        "pricing — Tokyo Gas, Osaka Gas, Chubu Electric, JERA are counterparties "
        "on 20-year take-or-pay contracts",
        "Downstream refinery throughput: El Segundo, Richmond, El Paso, and "
        "Pascagoula refineries with integrated marketing margin",
        "Chevron Phillips Chemical joint ventures — polyethylene and polypropylene "
        "capacity generating equity income",
    ],
    rate_sensitivity_note=(
        "Chevron is primarily correlated with Brent/WTI crude prices and LNG "
        "spot prices rather than interest rates directly.  Higher rates slow "
        "global economic activity, reducing petroleum demand and oil prices "
        "at the margin.  Chevron carries ~$25B of long-term debt at mostly "
        "fixed rates; near-term interest expense impact of rate hikes is modest.  "
        "Higher rates also reduce project NPVs, but Chevron's capital allocation "
        "framework uses a $60-70/bbl long-run price deck for investment hurdles — "
        "a more binding constraint than the interest rate environment."
    ),
    inflation_pass_through=(
        "Natural energy price inflation hedge: Chevron's upstream revenue moves "
        "directly with oil and LNG prices.  Higher inflation typically coincides "
        "with higher commodity prices, directly benefiting Chevron's revenue.  "
        "Cost inflation (oilfield services, labor, steel) is the offsetting risk — "
        "Chevron's multi-year Permian development contracts and TCO FGP have "
        "experienced significant cost overruns ($48B original TCO estimate "
        "increased to $50B+)."
    ),
    recession_behavior=(
        "Highly cyclical with significant balance sheet resilience: Chevron "
        "maintained its dividend through COVID (oil went negative in April 2020) "
        "and through the 2015-16 oil price crash, funded by balance sheet.  "
        "Management commits to dividend continuity with net debt ratio of <30%.  "
        "In oil price downturns, Chevron reduces upstream CapEx, cutting discretionary "
        "development spending while protecting base production cash flow from "
        "existing producing fields.  Permian shale's flexible capital intensity "
        "(6-month payback at $60+ WTI) allows rapid CapEx cuts."
    ),
    major_risks=[
        "Oil price decline: Brent/WTI below $60/bbl compresses Chevron FCF "
        "significantly; below $50/bbl dividend coverage becomes stretched",
        "Hess acquisition risk: ExxonMobil claims preferential rights to Hess's "
        "Guyana stake — if arbitration goes against Chevron, the Hess deal "
        "may collapse and Chevron loses its Guyana growth position",
        "TCO project execution: Tengiz FGP has had multi-year delays and cost "
        "overruns; first oil from FGP expansion is the biggest near-term catalyst",
        "Energy transition long-term headwind: global policy shift toward EVs "
        "and renewables reduces petroleum demand over a 10-20 year horizon",
        "California refinery regulatory risk: Richmond and El Segundo refineries "
        "face increasing state environmental regulation",
    ],
    valuation_style=(
        "Chevron trades at ~12-14x forward P/E and 8-10x EV/EBITDA — a cyclical "
        "energy multiple reflective of oil price uncertainty.  At $80 Brent "
        "Chevron generates ~$20B FCF, supporting $12B+ in buybacks and dividends.  "
        "The Hess deal premium (if successful) would add 10-15% to long-term "
        "NAV through Guyana asset quality.  Key metrics: FCF yield at current oil "
        "price, production growth ex-TCO, and Permian unit operating costs."
    ),
    key_metrics=[
        "Net oil equivalent production (BOE/day, targeting 3.3M BOE/day by 2027)",
        "Free cash flow at strip oil price ($70-80 Brent deck)",
        "Permian Basin production growth and unit operating costs",
        "TCO FGP progress (first oil from FGP expansion)",
        "Return on capital employed (ROCE) vs majors",
        "Dividend per share growth rate (target 5-6% annual growth)",
        "Net debt ratio (target <20% net debt to capital)",
        "Buyback program execution ($10-15B annual)",
    ],
    competitive_advantages=[
        "Permian Basin scale: Chevron is one of the three largest Permian producers "
        "with >3M net acres and 15+ years of inventory at competitive costs — "
        "lower finding costs and break-even than international deepwater alternatives",
        "TCO / Tengiz asset: Chevron's 50% stake in the Tengiz field (Kazakhstan) "
        "is one of the world's lowest-cost large oil fields — FGP expansion adds "
        "260K BOE/day at $20/BOE finding cost, among the best new-production economics globally",
        "Australia LNG position: Gorgon and Wheatstone represent 50+ mtpa of LNG "
        "capacity with long-term Asian utility contracts — a premium stranded asset "
        "that Chevron has operated for decades with high HSE and operational standards",
        "Balance sheet conservatism: AA-rated balance sheet with $20B+ liquidity "
        "allows dividend maintenance through oil price cycles while competitors "
        "cut dividends — a differentiated trust factor for income investors",
    ],
    business_model_keywords=[
        "Mike Wirth", "Permian Basin", "TCO", "Tengiz", "Hess",
        "Guyana", "Gorgon", "Wheatstone", "LNG", "BOE",
        "free cash flow", "buyback", "capital discipline", "TCOP",
        "refining", "downstream", "net debt ratio", "ROCE",
        "DJ Basin", "Gulf of Mexico", "Anchor", "Whale",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="SCHW",
    company_name="The Charles Schwab Corporation",
    business_model=(
        "Charles Schwab is the largest publicly traded US broker-dealer and "
        "bank, serving 34M+ active brokerage accounts and $9T+ in client assets.  "
        "The company operates across three business lines: Investor Services "
        "(retail self-directed investing and robo-advisory), Advisor Services "
        "(custody and trading for ~12,000 independent RIAs), and Banking/Lending "
        "(client cash, margin lending, pledged asset lending, mortgage).  "
        "Schwab's revenue model is fundamentally interest-rate sensitive: Net "
        "Interest Revenue (~55% of total revenue) from cash sweep balances "
        "(client uninvested cash earns Fed Funds-linked income), margin loans, "
        "and bank securities portfolios.  CEO Rick Wurster (2024 successor to "
        "Walt Bettinger) is managing the TD Ameritrade integration (acquired "
        "2020, $26B) while navigating elevated bank sweep outflows that compressed "
        "NII in 2022-24 as clients moved cash to money market funds."
    ),
    primary_revenue_drivers=[
        "Net Interest Revenue (~55%): bank sweep deposit income — when Fed "
        "Funds rate is high, Schwab earns the spread between what it pays on "
        "client cash sweeps (near-zero historically) and what it earns on "
        "Treasuries and mortgage-backed securities (~4.5%)",
        "Asset Management and Administration (~25%): Schwab's proprietary ETFs "
        "(SCHB, SCHD — $500B+), mutual fund fees, Schwab Intelligent Portfolios "
        "(robo-advisory, $72B AUM), and advisor platform fees from RIA custody",
        "Trading Revenue (~15%): commission-free equity trading (since Oct 2019) "
        "with PFOF (payment for order flow) on equity options and crypto",
        "Bank Lending (~5%): margin loans, pledged asset lines, "
        "home equity, and Rocket Mortgage referral partnership",
    ],
    recurring_revenue_sources=[
        "RIA custody fees: Schwab serves ~12,000 independent registered "
        "investment advisors on its Advisor Services platform — sticky, "
        "recurring custody/clearing fees based on AUM and transaction volume",
        "Schwab ETF management fees: $500B+ in proprietary Schwab ETFs "
        "(SCHB, SCHD, SCHF, SCHX) generate 3-5 bps management fees",
        "Schwab Intelligent Portfolios Premium ($30/month subscription): "
        "robo-advisory with unlimited CFP access — growing recurring SaaS-like revenue",
        "Mutual Fund OneSource platform fees: revenue sharing from third-party "
        "funds available on the no-transaction-fee platform",
    ],
    rate_sensitivity_note=(
        "Schwab is among the most interest-rate-sensitive major financial companies.  "
        "Net interest revenue is directly tied to the federal funds rate and the "
        "yield curve — a 25 bps Fed cut reduces Schwab's NII by ~$100M annually.  "
        "In 2022-24, as rates rose, clients moved $150B+ of low-yield bank sweeps "
        "into Treasuries and money market funds (cash sorting), reducing Schwab's "
        "deposit base and forcing the company to borrow at higher rates via FHLB "
        "advances.  Schwab carries a large fixed-income HTM (held-to-maturity) "
        "securities portfolio with unrealized losses at high rate levels."
    ),
    inflation_pass_through=(
        "Indirect: Schwab's primary benefit from inflation is the associated "
        "higher interest rates that expand NII margins.  Trading revenue is "
        "relatively inflation-neutral (commission-free equity, PFOF on options).  "
        "Asset management fees grow with market levels (AUM-based fee model)."
    ),
    recession_behavior=(
        "Mixed: in equity market downturns, Schwab AUM-based management fees "
        "decline with market values, and client activity/trading often spikes "
        "then declines.  However, Schwab gains market share during volatile "
        "periods as investors actively trade (trading revenue increases in "
        "volatility).  Credit quality on margin loans typically deteriorates "
        "in recessions as stock collateral falls.  Net: Schwab is mildly "
        "counter-cyclical on trading but pro-cyclical on AUM-based fees."
    ),
    major_risks=[
        "Cash sorting: elevated Fed Funds rates drive continued client cash "
        "outflows from bank sweeps to money market funds, reducing NII permanently "
        "unless Schwab raises sweep rates (which compresses margin)",
        "PFOF regulatory risk: SEC or congressional action to ban payment for "
        "order flow would eliminate ~$800M of Schwab's annual trading revenue",
        "TD Ameritrade integration risk: merging TD's thinkorswim platform and "
        "client base while retaining RIA relationships is complex; client "
        "attrition during system migrations",
        "HTM unrealized losses: Schwab's fixed-income securities portfolio "
        "has $14B+ unrealized losses that reduce tangible book value; "
        "forced sale would crystallize losses",
        "Interest rate cuts: Fed rate normalization reduces NII, compressing "
        "earnings growth in 2025-2026",
    ],
    valuation_style=(
        "Schwab trades at ~18-22x forward P/E — a financial services multiple "
        "that discounts near-term NII compression (cash sorting + potential "
        "rate cuts) against long-term earnings power as the industry leader in "
        "retail brokerage and RIA custody.  Normalized EPS ($4-5/share) on "
        "full TD integration and stabilized sweep balances would support a "
        "20x multiple = $80-100 stock price.  Key metric: bank sweep "
        "balance stabilization (the single most important forward indicator)."
    ),
    key_metrics=[
        "Net new assets (NNA) — organic growth indicator; target $400B+ annually",
        "Bank sweep deposit balances (the cash sorting indicator)",
        "Net interest margin (NIM) and net interest revenue",
        "Client assets by channel (retail vs RIA vs bank)",
        "TD Ameritrade integration milestones and cost synergy capture",
        "Daily average revenue trades (DARTs) — trading activity",
        "Schwab ETF AUM growth",
        "Net interest-bearing assets and FHLB borrowings",
    ],
    competitive_advantages=[
        "Scale in RIA custody: Schwab's Advisor Services platform has $4T+ "
        "in RIA assets under custody — the largest custodian globally, ahead "
        "of Fidelity Institutional and Pershing; switching costs for RIAs are "
        "very high (portfolio management system integrations, client data migration)",
        "Brand trust in retail investing: Schwab pioneered commission-free trading "
        "and low-cost index investing — the brand is synonymous with investor-first "
        "positioning among self-directed investors",
        "thinkorswim platform (from TD): professional-grade options and futures "
        "trading platform with advanced analytics — the preferred tool for active "
        "retail traders, creating an ecosystem of experienced users",
        "Bank integration: Schwab Bank's ability to sweep client cash and cross-sell "
        "banking products to brokerage clients creates revenue synergies Fidelity "
        "(privately held) and Robinhood cannot yet replicate at scale",
    ],
    business_model_keywords=[
        "Rick Wurster", "net interest revenue", "bank sweep", "cash sorting",
        "TD Ameritrade", "thinkorswim", "RIA", "advisor services",
        "net new assets", "NNA", "Schwab ETF", "SCHD", "SCHB",
        "payment for order flow", "PFOF", "margin lending",
        "Schwab Intelligent Portfolios", "HTM portfolio",
        "FHLB", "sweep deposits", "client assets",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="MDLZ",
    company_name="Mondelez International Inc.",
    business_model=(
        "Mondelez International is the world's largest snacking company, "
        "selling branded biscuits, chocolate, gum, candy, and cheese/grocery "
        "products in 150+ countries.  The company was spun off from Kraft Foods "
        "in 2012.  Core brands: Oreo (biscuits — world's best-selling cookie), "
        "Cadbury (chocolate — UK and Commonwealth markets), Milka (Europe), "
        "Toblerone, Chips Ahoy!, Ritz, belVita, Triscuit, Halls.  CEO Dirk Van "
        "de Put has pursued a 'local first' strategy — building brand relevance "
        "in emerging markets (India, China, Brazil, Mexico) where the middle class "
        "is adopting Western-style snacking.  Revenue model: ~80% from biscuits "
        "(50%) and chocolate (30%); geographic split ~40% developed markets "
        "(North America, W. Europe) and ~60% emerging markets."
    ),
    primary_revenue_drivers=[
        "Biscuits (~50%): Oreo (global), Chips Ahoy!, Ritz, belVita, Triscuit, "
        "TUC, LU — Oreo alone is a $5B+ brand globally with market leading "
        "positions in >50 countries",
        "Chocolate (~30%): Cadbury Dairy Milk (UK/Australia), Milka (Europe), "
        "Toblerone, Côte d'Or — Cadbury is the #1 chocolate brand in the "
        "UK and second globally after Mars",
        "Gum and Candy (~10%): Trident, Chiclets, Halls cough drops",
        "Cheese, Grocery, and Other (~10%): Velveeta (licensed from Kraft), "
        "Philadelphia cream cheese (licensed), Oscar Mayer",
    ],
    recurring_revenue_sources=[
        "Oreo brand in Asia Pacific and emerging markets — secular snacking "
        "adoption drives recurring category volume growth",
        "Cadbury Dairy Milk in India: MDL is the category leader and gaining "
        "market share in a $3B+ and growing Indian chocolate market",
        "Belg (Belgium) and Kraft brands manufactured under license for "
        "European grocery retail with annual supply agreements",
        "E-commerce and gifting channels (Cadbury UK, Oreo Asia) — "
        "growing DTC gifting and seasonal chocolate revenue streams",
    ],
    rate_sensitivity_note=(
        "Mondelez has low direct interest rate sensitivity.  The company carries "
        "~$13B of long-term debt at mostly fixed rates; a 100 bps rate rise "
        "has minimal near-term impact on earnings.  Indirectly, consumer spending "
        "pressure from higher rates could reduce premium chocolate and gum spending "
        "(consumers trade down to private label).  EM currency weakness (associated "
        "with rate differentials) creates FX translation headwinds on the ~40% "
        "of revenue from emerging markets."
    ),
    inflation_pass_through=(
        "The critical near-term issue for Mondelez is cocoa price inflation.  "
        "Cocoa futures surged to $12,000+/MT in 2024 from $2,500/MT in 2022 — "
        "the worst cocoa price crisis in 50 years due to West African crop failures.  "
        "Mondelez is attempting to pass through cocoa inflation via product price "
        "increases (reducing pack sizes, raising list prices), but the pace of "
        "pass-through lags the raw material cost curve by 6-12 months, compressing "
        "gross margins in the interim."
    ),
    recession_behavior=(
        "Moderately defensive: chocolate and biscuits are affordable, habitual "
        "indulgences that consumers maintain in mild recessions.  'Lipstick effect' "
        "dynamics support premium confectionery.  However, severe recessions "
        "cause trade-down to private label in developed markets.  Emerging markets "
        "(40% of revenue) are less recession-correlated to developed market cycles — "
        "India and Africa chocolate demand is driven by middle-class formation "
        "independent of US/EU recession dynamics."
    ),
    major_risks=[
        "Cocoa price crisis: $12,000+/MT cocoa in 2024 (from $2,500 in 2022) "
        "dramatically increases COGS for Cadbury and Milka products; "
        "volume elasticity constrains price recovery speed",
        "Private label competition: in developed markets (US, UK, Germany), "
        "retailer own-brand biscuits and chocolate are gaining share as "
        "consumers seek value alternatives to branded products",
        "GLP-1 weight loss drug headwind: Ozempic/Wegovy use reduces "
        "snacking frequency — potential long-term headwind to confectionery demand",
        "Emerging market currency volatility: ~40% of revenue in "
        "inflation-prone EM currencies creates FX translation risk",
        "Health and wellness trend: sugar reduction requirements and "
        "packaging regulation in EU markets",
    ],
    valuation_style=(
        "Mondelez trades at ~18-22x forward P/E — a quality consumer staples "
        "growth multiple reflecting Oreo's global market leader status and "
        "EM snacking growth.  Near-term multiple compression from cocoa inflation "
        "compressing gross margins has created a 'transitory margin headwind' "
        "discount.  Long-term re-rating potential from EM chocolate market "
        "expansion in India, China, and Southeast Asia."
    ),
    key_metrics=[
        "Organic net revenue growth (pricing + volume — key Mondelez KPI)",
        "Gross margin % (critical: cocoa cost pass-through indicator)",
        "Volume/mix performance by region",
        "Emerging market revenue growth (India, China, Brazil)",
        "Oreo brand net revenue growth by geography",
        "Cadbury brand performance in UK and India",
        "Cocoa hedging coverage (% of next 12-month needs hedged)",
        "Free cash flow conversion and dividend growth",
    ],
    competitive_advantages=[
        "Oreo brand global reach: Oreo is sold in 100+ countries and is the "
        "world's best-selling cookie — Nabisco manufacturing licenses and "
        "local production partnerships create a network that would take decades "
        "to build from scratch; in China, Oreo is the most trusted imported food brand",
        "Cadbury/Dairy Milk in Commonwealth markets: the #1 chocolate brand "
        "in the UK, Australia, and India with century-old brand equity that "
        "Mars and Ferrero cannot easily displace",
        "Emerging market distribution depth: Mondelez has built direct-to-trade "
        "distribution networks in India (750,000+ retail outlets), China, and "
        "Brazil that give it reach in small-format retail unavailable to many competitors",
        "Innovation pipeline: Oreo collaborations (limited-edition flavors with "
        "cultural relevance — Pokemon, Lady Gaga, Olympics) maintain cultural "
        "currency and drive trial purchases without cannibalization of core sales",
    ],
    business_model_keywords=[
        "Oreo", "Cadbury", "Milka", "Toblerone", "Chips Ahoy!",
        "Dirk Van de Put", "snacking", "biscuits", "chocolate",
        "cocoa inflation", "Dairy Milk", "belVita", "Ritz",
        "emerging markets", "organic revenue growth", "volume/mix",
        "India chocolate", "private label", "gross margin",
        "GLP-1 headwind", "pack size",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="COP",
    company_name="ConocoPhillips",
    business_model=(
        "ConocoPhillips is the world's largest pure-play E&P (exploration and "
        "production) company — it produces oil, natural gas, and LNG but does "
        "not operate refineries or retail fuel stations (unlike integrated majors "
        "Exxon and Chevron).  CEO Ryan Lance has built Conoco around a 'returns-of-"
        "and-returns-on-capital' framework: Tier 1 resource quality (breakeven <$40/BOE "
        "across most of the portfolio), capital discipline (CapEx grows ~5% annually "
        "regardless of oil price), and shareholder returns (3-tier distribution — "
        "ordinary dividend + variable dividend + buybacks).  Key assets: Permian Basin "
        "(Delaware Basin, Midland Basin), Eagle Ford Shale, Bakken, Alaska (North "
        "Slope — largest Alaska oil producer), Norway North Sea, and Qatar LNG "
        "(via Qatargas JV).  The Marathon Oil acquisition ($22.5B, 2024) added "
        "240,000 BOE/day in Permian and Eagle Ford."
    ),
    primary_revenue_drivers=[
        "Lower 48 US production (Permian, Eagle Ford, Bakken — ~55% of production): "
        "short-cycle shale with 6-12 month capital-to-production cycle; "
        "breakeven $35-40/BOE WTI equivalent",
        "Alaska (North Slope, ~15%): Prudhoe Bay, Kuparuk River, Greater Mooses "
        "Tooth — long-life conventional production; Willow project adds 180K BOE/day",
        "International LNG and conventional (~30%): Qatar LNG (Qatargas "
        "train 3 — long-term 20-year SPA contracts), Norway, Australia, Malaysia",
        "Marathon Oil acquired assets (2024): DJ Basin, Permian additions, "
        "International Eagle Ford equivalent in South Texas",
    ],
    recurring_revenue_sources=[
        "Qatar LNG long-term SPAs (sale and purchase agreements): 20-year "
        "take-or-pay contracts with JCC-linked LNG pricing to Japanese and "
        "Korean utilities — >$2B annual recurring FCF at $10/mmbtu LNG",
        "Alaska North Slope base production: Prudhoe Bay and Kuparuk have "
        "operated for 40+ years — stable, low-decline conventional production "
        "with committed offtake from TAPS (Trans-Alaska Pipeline System)",
        "Norway Johan Sverdrup JV (Equinor-operated): long-life, low-breakeven "
        "North Sea production from the world's most carbon-efficient oil field",
    ],
    rate_sensitivity_note=(
        "ConocoPhillips is correlated with WTI and LNG spot prices rather than "
        "interest rates directly.  The company carries ~$18B of long-term debt "
        "(including Marathon Oil acquisition debt), mostly fixed-rate.  "
        "Higher rates marginally increase financing costs on variable-rate "
        "credit facilities but do not meaningfully impact Conoco's FCF at $70+ WTI.  "
        "Rate hikes slow global growth, reducing petroleum demand and putting "
        "pressure on oil prices — the primary indirect risk."
    ),
    inflation_pass_through=(
        "Natural resource inflation hedge: Conoco's upstream revenue moves "
        "with oil/gas prices.  Input cost inflation (oilfield services, steel, "
        "labor) compresses unit margins but Conoco has multi-year service "
        "agreements at fixed rates for Permian drilling programs.  LNG SPAs "
        "with JCC indexing to oil prices provide natural inflation pass-through "
        "on the gas side."
    ),
    recession_behavior=(
        "Cyclical but balance-sheet-resilient: Conoco maintained its ordinary "
        "dividend through COVID (canceled only the variable component) and "
        "through the 2015-16 oil crash — a differentiated record vs peers.  "
        "The 3-tier return framework (ordinary dividend + variable + buyback) "
        "allows capital flexibility during downturns.  At $60 WTI, Conoco "
        "covers its ordinary dividend and base CapEx; at $40 WTI, the company "
        "has balance sheet to sustain the dividend for 2+ years."
    ),
    major_risks=[
        "Oil price: Brent/WTI below $55/BOE compresses FCF to near zero on "
        "the ordinary dividend commitment; below $45 requires balance sheet drawdown",
        "Marathon acquisition integration: absorbing 15,000+ new Permian and "
        "Eagle Ford wells requires seamless operating system integration to "
        "maintain capital efficiency metrics",
        "Alaska Willow project execution: the 180K BOE/day Willow Arctic project "
        "has faced environmental/legal challenges and cost escalation risk",
        "Qatar LNG counterparty risk: Conoco's JCC-priced LNG SPAs are "
        "dependent on Qatargas political stability and Qatar Petroleum cooperation",
        "Energy transition: long-term peak oil demand reduces the long-run "
        "resource value of COP's reserves",
    ],
    valuation_style=(
        "Conoco trades at ~12-15x forward P/E and 8-10x EV/EBITDA — the "
        "premium E&P multiple justified by Tier 1 cost of supply and rigorous "
        "capital returns framework.  The sum-of-parts NAV model at $75 WTI "
        "broadly supports current trading levels.  Re-rating catalyst: "
        "Marathon integration delivering promised $500M synergies and Willow "
        "project on-schedule; de-rating risk: oil price below $60, Alaska "
        "permitting reversal."
    ),
    key_metrics=[
        "Production growth (BOE/day — target +5% CAGR)",
        "Cost of supply (breakeven WTI per BOE — Tier 1 target <$40/BOE)",
        "Free cash flow at strip price ($70-80 WTI deck)",
        "Return of capital (ordinary dividend + variable dividend + buyback)",
        "Permian production growth (largest growth engine)",
        "Alaska North Slope production and Willow progress",
        "LNG volumes and realized LNG price vs JCC formula",
        "Net debt and leverage ratio post-Marathon acquisition",
    ],
    competitive_advantages=[
        "Tier 1 cost of supply: ConocoPhillips screens among the lowest cost "
        "of supply per barrel in the industry (~$35/BOE average portfolio breakeven) "
        "— provides free cash flow at oil prices where competitors are burning cash",
        "Balance sheet strength: Conoco is AA-rated with net cash or minimal "
        "net debt; has never missed an ordinary dividend in modern history — "
        "attracts long-only institutional investors seeking energy exposure "
        "without balance sheet risk",
        "Variable return model: the 3-tier return framework (ordinary + variable "
        "+ buyback) is the most explicit capital discipline framework among E&P "
        "peers — investors can model returns at different oil price scenarios",
        "Alaska sovereign asset: North Slope production is one of the most "
        "geopolitically stable oil producing regions — no OPEC+ exposure, "
        "US territory, multi-decade production history",
    ],
    business_model_keywords=[
        "Ryan Lance", "cost of supply", "Permian Basin", "Eagle Ford",
        "Bakken", "Alaska", "North Slope", "Willow", "Marathon Oil",
        "Qatar LNG", "JCC", "three-tier return", "variable dividend",
        "ordinary dividend", "BOE", "free cash flow", "Tier 1",
        "capital discipline", "TAPS", "Johan Sverdrup",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="RTX",
    company_name="RTX Corporation",
    business_model=(
        "RTX Corporation (formerly Raytheon Technologies) is a global aerospace "
        "and defense company formed by the merger of United Technologies and "
        "Raytheon in 2020.  Three segments: Collins Aerospace (~33% of revenue — "
        "aircraft systems, avionics, interiors, nacelles), Pratt & Whitney (~38% — "
        "commercial and military jet engines), and Raytheon (~29% — missiles, "
        "radar, electronic warfare, integrated air and missile defense).  "
        "CEO Chris Calio (2023 successor to Greg Hayes) is managing two concurrent "
        "crises: the Pratt & Whitney GTF (geared turbofan) powder metal defect "
        "requiring the inspection and removal of ~3,000 CFM56/GTF engines from "
        "service (costing $3-7B in charges), and Raytheon's solid-track record "
        "amid unprecedented global demand for Patriot missiles, Stingers, and "
        "Javelin systems given Russia-Ukraine and Middle East conflicts."
    ),
    primary_revenue_drivers=[
        "Pratt & Whitney commercial aftermarket (~40% of P&W revenue): "
        "GTF and V2500 engine overhaul, parts, and maintenance — highest "
        "margin segment within P&W once GTF inspection charges normalize",
        "Collins Aerospace aftermarket (~50% of Collins revenue): proprietary "
        "avionics, cockpit systems, actuation, and nacelle replacement "
        "parts — sole-source supplier for most OEM hardware",
        "Raytheon defense bookings: Patriot PAC-3, Stinger, Javelin, "
        "SPY-6 radar, Tomahawk cruise missiles — record backlog driven "
        "by NATO rearmament and US DoD modernization",
        "Military engine revenue (F135 for F-35, F117 for C-17, military "
        "upgrade/sustainment) — multi-decade program of record",
    ],
    recurring_revenue_sources=[
        "Engine flight hours: Pratt & Whitney's 'power by the hour' or "
        "Fleet Management Programs (FMP) charge airlines per flight hour "
        "for GTF and V2500 engine maintenance — recurring, high-margin",
        "Collins line-replaceable unit (LRU) aftermarket: airlines are "
        "required to use OEM-approved parts for FAA/EASA certification "
        "— Collins is sole-source supplier creating a captive aftermarket",
        "Raytheon Missiles & Defense production program of record revenue: "
        "Patriot, Stinger, Javelin — multi-year DoD/FMS (foreign military "
        "sales) contracts approved through the ITAR export process",
    ],
    rate_sensitivity_note=(
        "RTX is moderately interest-rate sensitive.  The company carries ~$30B "
        "of long-term debt (post-merger integration) at mostly fixed rates.  "
        "Commercial aerospace financing costs for airline customers (737 MAX, "
        "A320neo delivery financing) can affect narrowbody engine demand at the "
        "margin.  Defense contract funding from the US government is independent "
        "of interest rates.  Valuation compression from higher discount rates "
        "affects RTX's growth-oriented aerospace aftermarket multiple."
    ),
    inflation_pass_through=(
        "Defense segment: cost-plus contracts pass through inflation to the "
        "DoD (most RTX development programs).  Fixed-price production contracts "
        "(Javelin, Patriot production lots) face margin pressure from labor "
        "and material inflation.  Pratt & Whitney: commercial OEM contracts "
        "have cost escalation provisions; aftermarket pricing has inflation "
        "clauses.  GTF powder metal recall charges are a one-time extraordinary "
        "cost, not structural inflation."
    ),
    recession_behavior=(
        "Significantly defensive: ~50% of revenue is US government defense "
        "funding (largely insulated from economic cycles).  Commercial aerospace "
        "aftermarket is resilient (airlines must maintain existing fleets in "
        "service regardless of recession); new OEM engine deliveries decline "
        "in severe recessions as airlines defer aircraft orders.  "
        "Raytheon benefits from geopolitical tension which drives NATO "
        "rearmament spending independent of US economic conditions."
    ),
    major_risks=[
        "Pratt & Whitney GTF powder metal recall: ~3,000 engines require "
        "premature shop visits for high-pressure turbine disc inspection; "
        "total cost estimate $3-7B over 2023-2025; creates AOG (aircraft on "
        "ground) risk for airline customers and fleet utilization disruption",
        "Pratt military engine competition: GE's F414 engine competing for "
        "next-gen programs; NGAD (next generation air dominance) engine selection",
        "Supply chain constraints: aerospace aerostructures and castings "
        "bottlenecks limit Collins and Pratt production ramp capacity",
        "Defense program budget risk: US DoD budget sequestration or "
        "continuing resolutions delay new contract awards",
        "F-35 program reliance: ~$2B annual revenue from F135 engine; "
        "any slowdown in F-35 procurement reduces P&W sustainment revenue",
    ],
    valuation_style=(
        "RTX trades at ~18-22x forward P/E — an aerospace/defense conglomerate "
        "multiple with a discount to pure-play commercial aerospace (Collins "
        "Aerospace intrinsically worth 22-25x) offset by Raytheon defense at "
        "17-18x.  Sum-of-parts analysis suggests the three segments are worth "
        "more separated than together.  Re-rating catalyst: GTF powder metal "
        "charges fully quantified, P&W aftermarket recovery, and record Raytheon "
        "backlog converting to revenue.  De-rating risk: GTF charges exceed "
        "guidance, commercial aerospace cycle turns negative."
    ),
    key_metrics=[
        "Pratt & Whitney GTF powder metal recall progress (engine inspections "
        "completed, total cost vs guidance)",
        "Collins Aerospace organic revenue growth and aftermarket mix",
        "Raytheon Missiles & Defense bookings and book-to-bill ratio",
        "Defense backlog ($67B+ — record levels)",
        "Commercial engine deliveries (GTF, V2500)",
        "Adjusted EPS and free cash flow conversion",
        "DoD budget alignment with key programs (Patriot, Javelin, SPY-6)",
        "Engine flight hours growth (Pratt aftermarket indicator)",
    ],
    competitive_advantages=[
        "Pratt & Whitney GTF engine monopoly on A220, A320neo family: "
        "GTF (LEAP-1A competes on A320neo, but CFM and Pratt split the market "
        "~50/50 — on A220, Pratt is sole-source with no CFMI option) creates "
        "a decades-long aftermarket captive revenue stream for 5,000+ delivered engines",
        "Collins avionics and nacelle monopoly positions: Collins is sole-source "
        "supplier of avionics suites on most Boeing and Airbus programs — "
        "no competitive re-sourcing risk due to FAA certification requirements",
        "Patriot missile system dominance: the world's most widely deployed "
        "integrated air and missile defense system in 19+ countries — "
        "interoperability requirements make Patriot the NATO standard; "
        "allies buying Patriot creates decades of ammunition and upgrade revenue",
        "Defense electronics integration depth: Raytheon's SPY-6 AMDR (Air "
        "and Missile Defense Radar) and Coyote counter-UAS are embedded in "
        "US Navy and Army programs that have no competitive alternative",
    ],
    business_model_keywords=[
        "Pratt & Whitney", "Collins Aerospace", "Raytheon", "Chris Calio",
        "geared turbofan", "GTF", "powder metal", "A320neo", "A220",
        "Patriot", "Stinger", "Javelin", "SPY-6", "F135", "F-35",
        "Greg Hayes", "aftermarket", "power by the hour",
        "program of record", "defense backlog", "FMS",
        "missiles", "electronic warfare",
    ],
))

_register(CompanyKnowledgeProfile(
    ticker="NEE",
    company_name="NextEra Energy Inc.",
    business_model=(
        "NextEra Energy is the world's largest producer of wind and solar energy "
        "and the parent company of Florida Power & Light (FPL), the largest regulated "
        "electric utility in the United States, and NextEra Energy Resources (NEER), "
        "the world's largest generator of renewable energy from wind and solar.  "
        "CEO John Ketchum manages two distinct businesses: FPL (~65% of earnings) — "
        "a Florida rate-regulated utility serving 12M+ customers with a committed "
        "capital plan to add ~20 GW of new solar and battery storage to the FPL rate base "
        "through 2026+; and NEER (~35% of earnings) — an unregulated merchant/contracted "
        "renewable IPP that builds and operates wind farms, solar parks, and battery "
        "storage for utilities, corporations, and munis under 15-20 year PPAs (power "
        "purchase agreements).  NEE also holds a ~60% limited partner interest in "
        "NextEra Energy Partners (NEP), a publicly traded renewable yieldco."
    ),
    primary_revenue_drivers=[
        "Florida Power & Light regulated return on equity (~65% of EBIT): "
        "FPL earns a ~10-11% allowed ROE on its rate base (~$65B and growing "
        "rapidly with solar/battery addition); customer growth in Florida (fastest- "
        "growing large utility customer base in the US) supports rate base expansion",
        "NextEra Energy Resources wind and solar contracted (~25% of EBIT): "
        "NEER operates 30+ GW of operating wind/solar and signs 15-20 year PPAs "
        "with investment-grade utilities and corporate offtakers — essentially "
        "'contracted bonds' with residual value upside",
        "NextEra Energy Partners (NEP) distributions: NEE collects LP distributions "
        "from the NEP yieldco (~10% of earnings); NEP owns operational wind/solar "
        "assets acquired from NEER",
        "Nuclear baseload (St. Lucie, Turkey Point): FPL operates nuclear plants "
        "providing low-cost baseload power to Florida customers",
    ],
    recurring_revenue_sources=[
        "FPL regulated rate base revenue: Florida PSC cost-of-service regulation "
        "provides near-guaranteed subscription-like revenue regardless of economic "
        "cycle — FPL earns an allowed ROE on every dollar of rate base investment",
        "NEER long-term multi-year contract PPAs: 15-20 year fixed-price or "
        "CPI-linked power purchase agreements with rated utilities (Duke, ConEd, "
        "Xcel) — contractual cash flows for the full life of each wind/solar project",
        "NEP distributions: NEP pays quarterly distributions to NEE from its "
        "operating wind and solar assets; distributions have grown 12-15% annually",
        "Renewable development backlog: NEER has a record 30+ GW of signed "
        "long-term maintenance service contract commitments — years of visible "
        "future contracted earnings",
    ],
    rate_sensitivity_note=(
        "NextEra Energy is the most interest-rate-sensitive utility.  Both FPL "
        "(cost of equity for rate case filings) and NEER (NPV of long-term PPAs "
        "discounted at higher rates) are negatively impacted by rate hikes.  "
        "NEE carries ~$65B of long-term debt; a 100 bps rate rise increases "
        "annual interest expense ~$300-400M on floating rate facilities and "
        "refinancing of short-duration debt.  The stock trades as a 'bond "
        "proxy' — rising interest rates compress NEE's premium multiple, "
        "as its 3% dividend yield becomes less attractive vs 5% risk-free rates."
    ),
    inflation_pass_through=(
        "Partial: FPL regulated rate filings index O&M costs to a Florida-specific "
        "inflation formula — some cost increases are automatically recoverable.  "
        "NEER's PPAs often include CPI-linked escalators (2-3% annual increase) "
        "for newer contracts.  Construction cost inflation (steel, turbines, "
        "panels) squeezes development margins on new project builds before "
        "the signed PPA is locked in.  Equipment supply chains (solar panels, "
        "wind turbines) have experienced significant cost deflation 2023-2025 "
        "offsetting inflation in labor and interconnection costs."
    ),
    recession_behavior=(
        "Highly defensive and counter-cyclical: utility earnings are economically "
        "insensitive and essentially non-discretionary — consumers and businesses "
        "pay electric bills in recessions.  FPL residential and commercial customers "
        "continue to pay bills regardless of economic conditions; Florida's customer "
        "growth (retirees, in-migration) provides secular, resilient structural volume "
        "support independent of the business cycle.  NEER's contracted renewable "
        "generation revenue is fixed by multi-year PPAs regardless of spot power "
        "prices or economic conditions.  NEE is widely held as a counter-cyclical "
        "defensive income stock; the dividend has grown every year for 30+ consecutive "
        "years, including through the 2008-09 and 2020 recessions."
    ),
    major_risks=[
        "Interest rate sensitivity: NEE is among the most rate-sensitive equities "
        "in the S&P 500 — the stock declined 40%+ in 2022-23 as rates rose; "
        "the 'growth utility' premium compresses when rates are high",
        "NextEra Energy Partners (NEP) distribution cut risk: NEP paused "
        "distribution growth in 2023 due to high interest rates squeezing "
        "leveraged yieldco economics — NEE must backstop NEP or accept "
        "reputational damage from partner defaults",
        "Hurricane exposure: FPL's Florida territory faces 10+ named storms "
        "annually; significant hurricane damage requires storm cost recovery "
        "filings and can delay rate case timelines",
        "Construction cost overruns: renewable project builds face interconnection "
        "queue delays, materials cost inflation, and workforce shortages",
        "Regulatory rate case risk: Florida PSC rate cases must be filed every "
        "4 years; failure to receive allowed ROE increases compresses FPL earnings",
    ],
    valuation_style=(
        "NEE trades at ~20-25x forward P/E — a 'growth utility' premium "
        "vs regulated utility peers (12-15x) reflecting NEER's 15-20% "
        "renewable earnings growth and FPL's above-average rate base expansion.  "
        "The premium contracts and expands with interest rates.  "
        "At 5%+ risk-free rates, NEE's 3% dividend yield is less compelling; "
        "at 3% risk-free, the premium expands significantly.  "
        "Key re-rating catalysts: NEP recovery, power demand growth from data "
        "centers and AI creating incremental renewable PPA demand in Florida."
    ),
    key_metrics=[
        "FPL rate base growth (target ~$10B/year capital investment)",
        "NEER renewable backlog (contracted but not built — >30 GW)",
        "Adjusted EPS growth (target 6-8% CAGR through 2026)",
        "FPL allowed ROE vs earned ROE in rate case filings",
        "Wind and solar GW additions per year",
        "NEP distribution per unit and coverage ratio",
        "Power purchase agreement (PPA) execution (new signings GW/year)",
        "FPL customer growth and Florida population migration trends",
    ],
    competitive_advantages=[
        "NEER development scale: 30+ GW of new renewable projects per year "
        "in development and construction — the largest renewable development "
        "platform in the world, with procurement scale reducing turbine/panel "
        "costs 15-20% vs smaller IPPs",
        "FPL Florida monopoly with growth demographics: regulated utility "
        "serving the fastest-growing large state in the US — population "
        "in-migration from northeastern US guarantees customer base expansion "
        "for decades, compounding rate base growth organically",
        "Financing advantage: AA-rated balance sheet and NEP yieldco create "
        "a lower cost of capital for renewable project development than merchant "
        "IPPs or smaller regulated utilities — critical for winning competitive "
        "PPA solicitations",
        "Technology and O&M efficiency: NEE's scale in wind and solar O&M "
        "(1,000+ wind projects maintained in-house) provides 20-30% lower "
        "operations cost per MWh vs competitors, enabling lower PPA bids",
    ],
    business_model_keywords=[
        "John Ketchum", "Florida Power & Light", "FPL", "NextEra Energy Resources",
        "NEER", "NextEra Energy Partners", "NEP", "power purchase agreement",
        "PPA", "wind", "solar", "battery storage", "rate base",
        "regulated utility", "renewable energy", "CPI escalator",
        "allowed ROE", "rate case", "yieldco", "GW backlog",
        "hurricane", "interconnection", "AI data center demand",
    ],
))


# ── Palo Alto Networks (PANW) ─────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="PANW",
    company_name="Palo Alto Networks Inc.",
    business_model=(
        "Palo Alto Networks executes a 'platformization' strategy — consolidating "
        "customers from point products onto three integrated platforms: Strata "
        "(network security/NGFW), Prisma Cloud (cloud-native application security), "
        "and Cortex (AI-driven SOC automation via XSIAM).  Revenue is ~78% "
        "subscription/services and ~22% product hardware."
    ),
    primary_revenue_drivers=[
        "Strata network security — next-gen firewalls + Prisma Access SASE (~45% of revenue)",
        "Prisma Cloud CNAPP — cloud workload, container, and code security (~20%)",
        "Cortex XSIAM / XDR — AI-driven SOC replacing legacy SIEM (~15%)",
        "Product hardware appliances (~22% — declining mix as SaaS grows)",
    ],
    recurring_revenue_sources=[
        "Next-gen security ARR (cNGS ARR) — primary growth KPI, >$4.2B growing ~30% y/y",
        "Remaining Performance Obligation (RPO) — contracted future revenue visibility",
        "Prisma Cloud CSPM/CWPP subscription seats",
        "Cortex XSIAM platform multi-year enterprise contracts",
    ],
    rate_sensitivity_note=(
        "PANW trades at ~50-65x forward earnings. A 100 bps rate rise compresses "
        "the DCF-derived multiple significantly. However, cybersecurity spend is "
        "non-discretionary — enterprise security budgets are the last to be cut, "
        "providing fundamental resilience even as the multiple compresses."
    ),
    inflation_pass_through=(
        "Strong pricing power — cybersecurity is mandatory spending. The "
        "platformization strategy temporarily compresses billings (free capacity "
        "offered to consolidating customers) but builds long-term ARR stickiness "
        "and total-cost-of-ownership advantages."
    ),
    recession_behavior=(
        "Cybersecurity is the most resilient sub-sector of enterprise IT. "
        "Platformization — consolidating from many point vendors to save budget — "
        "actually accelerates in downturns as CISOs seek to reduce vendor spend. "
        "PANW saw billings decelerate but not decline through 2023-24."
    ),
    major_risks=[
        "Microsoft Security — $20B+ business bundled with Azure/M365 competes on "
        "price; enterprises can get 'good enough' security free with MSFT licenses",
        "CrowdStrike competition in XDR/endpoint and XSIAM mindshare",
        "Platformization billings headwind — free capacity offers suppress "
        "near-term billings and revenue, creating a 3-6 quarter trough",
        "Nikesh Arora key-person risk as architect of platformization strategy",
    ],
    valuation_style=(
        "Valued on EV/FCF (~40-60x) and EV/ARR. cNGS ARR growth and RPO expansion "
        "are the primary re-rating metrics. Re-rating catalyst: platformization "
        "billings recovery and XSIAM displacing SIEM at scale."
    ),
    key_metrics=[
        "Next-gen security ARR (cNGS ARR)",
        "Remaining Performance Obligation (RPO)",
        "Billings growth rate",
        "Platformization customer count (>1,000 target)",
        "Free cash flow margin (~37-38%)",
        "XSIAM customer count and ACV",
    ],
    competitive_advantages=[
        "Integrated platform: Strata + Prisma + Cortex share Cortex Data Lake — "
        "unified telemetry enables AI threat correlation that point products cannot match",
        "Largest NGFW installed base (~80,000 customers) — switching costs and "
        "cross-sell foundation for Prisma Cloud and Cortex upsell",
        "AI-native XSIAM — first mover replacing $4B+ annual SIEM market",
    ],
    business_model_keywords=[
        "platformization", "SASE", "Prisma Cloud", "Cortex", "XSIAM", "XDR",
        "next-generation firewall", "NGFW", "Strata", "cNGS ARR", "RPO",
        "CNAPP", "CSPM", "zero trust", "Nikesh Arora", "billings",
        "cloud-native security", "SOC", "network security",
    ],
))


# ── Walt Disney Company (DIS) ─────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="DIS",
    company_name="The Walt Disney Company",
    business_model=(
        "Disney monetizes its IP portfolio (Marvel, Star Wars, Pixar, Disney Classic, "
        "ESPN) across two segments: Entertainment (streaming via Disney+/Hulu/ESPN+, "
        "theatrical, linear TV via ABC/ESPN/FX) and Experiences (theme parks, cruise "
        "line, consumer products).  CEO Bob Iger returned in 2022 to restructure "
        "streaming toward profitability while preserving the parks cash engine."
    ),
    primary_revenue_drivers=[
        "Experiences — Walt Disney World, Disneyland, international parks, cruise "
        "line (~40% of revenue, ~60% of operating income)",
        "Entertainment DTC — Disney+, Hulu, ESPN+ streaming (~35%); "
        "DTC segment reached profitability in fiscal 2024",
        "Linear Networks — ESPN, ABC, FX, NatGeo (~25%; declining with cord-cutting "
        "but ESPN still generates $3B+ operating income annually)",
    ],
    recurring_revenue_sources=[
        "Disney+ and Hulu subscription fees (~230M+ combined subscribers)",
        "ESPN+ streaming subscriptions",
        "Annual pass holders at Walt Disney World and Disneyland",
        "Disney Cruise Line advance bookings (12-18 month window)",
        "Consumer products licensing royalties (Marvel, Star Wars, Disney brand)",
    ],
    rate_sensitivity_note=(
        "Net debt of ~$40B means higher rates increase interest expense directly. "
        "Parks capex (new rides, ships) is funded at prevailing rates, raising "
        "project hurdle rates. The stock trades at ~20-24x EPS — moderately "
        "rate-sensitive multiple."
    ),
    inflation_pass_through=(
        "Strong in parks: Disney raised single-day ticket prices from ~$110 (2019) "
        "to $189+ (2024) at peak without demand destruction, aided by Genie+ and "
        "Lightning Lane capacity tools. Streaming raised prices aggressively in "
        "2023-24 with limited churn aided by password-sharing crackdown."
    ),
    recession_behavior=(
        "Parks are aspirational — families plan Disney trips years in advance and "
        "prioritize them in household budgets. Per-capita spending in parks rose "
        "through 2022-23. Theatrical releases are volatile. Streaming is relatively "
        "sticky. Linear TV advertising is highly cyclical."
    ),
    major_risks=[
        "ESPN cord-cutting — linear ESPN subscriber base eroding; ESPN standalone "
        "streaming launch requires careful rights negotiation and consumer pricing",
        "Streaming profitability sustainability — content costs (Marvel, Star Wars) "
        "must be managed against subscriber growth targets",
        "China parks — Shanghai Disneyland faces geopolitical and consumer sentiment risk",
        "Marvel/Star Wars IP fatigue — franchise output must balance quantity vs quality",
        "Activist investor pressure on cost structure and CEO succession timeline",
    ],
    valuation_style=(
        "Sum-of-parts: Experiences at ~14-16x EBITDA, DTC at a Netflix-like "
        "revenue multiple once profitably scaled, Linear at a declining cash "
        "flow multiple. Key re-rating: ESPN streaming success and DTC margin expansion."
    ),
    key_metrics=[
        "Disney+ paid subscribers and ARPU",
        "DTC segment operating income",
        "Parks per-capita spending and attendance",
        "ESPN subscribers (linear + streaming combined)",
        "Free cash flow (target $8B+/yr)",
        "Total debt and deleveraging trajectory",
    ],
    competitive_advantages=[
        "IP portfolio depth — Marvel, Star Wars, Pixar, Disney Classic: no competitor "
        "can match the multi-generational, cross-demographic appeal of this library",
        "Theme park experiential moat — Disney parks command 2-3x ticket premiums; "
        "new rides take 5-7 years and $1-2B to build, preventing replication",
        "Franchise synergy flywheel — single IP generates theatrical, streaming, parks, "
        "consumer products revenue simultaneously across all channels",
    ],
    business_model_keywords=[
        "Disney+", "Hulu", "ESPN", "ESPN+", "Bob Iger", "Marvel", "Star Wars",
        "Pixar", "Walt Disney World", "Disneyland", "theme park", "cruise",
        "DTC", "direct-to-consumer", "cord-cutting", "ARPU", "Genie+",
        "Lightning Lane", "ABC", "content spending", "IP", "franchise",
    ],
))


# ── Uber Technologies (UBER) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="UBER",
    company_name="Uber Technologies Inc.",
    business_model=(
        "Uber operates a global two-sided marketplace connecting riders to drivers "
        "(Mobility) and consumers to restaurants/couriers (Delivery/Uber Eats), "
        "plus a freight logistics brokerage (Freight).  Revenue is the net take rate "
        "on Gross Bookings — ~27-29% on Mobility and ~18-19% on Delivery after "
        "paying driver incentives.  Advertising (~$1B+ run rate) is a high-margin "
        "emerging revenue layer on top of the marketplace."
    ),
    primary_revenue_drivers=[
        "Mobility (~57% of Gross Bookings) — global ride-hailing; US, LatAm, "
        "Europe, APAC; highest take rate and margin segment",
        "Delivery (~41% of Gross Bookings) — Uber Eats food + grocery/alcohol delivery",
        "Freight (~2%) — digital freight brokerage; volatile with trucking cycle",
        "Advertising (~$1B+ run rate, rapidly growing) — high-margin CPM/CPC ads",
    ],
    recurring_revenue_sources=[
        "Uber One membership (~30M+ members, $9.99/month) — reduces churn, "
        "increases Mobility and Eats frequency",
        "Restaurant sponsored listings on Uber Eats",
        "Uber for Business corporate travel management contracts",
    ],
    rate_sensitivity_note=(
        "UBER trades at ~25-35x forward EBITDA after its shift to profitability. "
        "Higher rates modestly compress the multiple. More critically, higher "
        "rates increase driver vehicle financing costs — can tighten driver supply "
        "and raise incentive spend, compressing take rates. UBER has net cash "
        "and minimal direct interest expense sensitivity."
    ),
    inflation_pass_through=(
        "Mixed: dynamic pricing algorithms pass fuel and cost increases to riders, "
        "but consumer price sensitivity limits sustained fare increases. Driver pay "
        "inflation is structural in tight supply markets. Advertising revenue is "
        "fully incremental at near-100% margin."
    ),
    recession_behavior=(
        "Mobility is semi-discretionary — commuters and non-car-owners still need "
        "rides but leisure trips decline. Gig-economy driver supply increases in "
        "recessions as workers seek flexible income, easing supply constraints and "
        "potentially improving take rates. Delivery showed resilience in downturns."
    ),
    major_risks=[
        "Autonomous vehicle disruption — Waymo, Tesla Robotaxi could disintermediate "
        "Uber's driver network; Uber's counter is to be the AV distribution platform",
        "Driver classification — AB5-type laws could force employee classification, "
        "adding ~30% to driver costs and destroying the gig-economy model",
        "Delivery margin pressure — DoorDash, Instacart compete aggressively in food delivery",
        "Regulatory market exits (UK, EU driver pay rules)",
    ],
    valuation_style=(
        "Valued on EV/EBITDA (~25-35x) and FCF yield as it reaches sustained "
        "profitability. Gross Bookings growth, take-rate expansion, and advertising "
        "revenue are the primary re-rating levers."
    ),
    key_metrics=[
        "Monthly Active Platform Consumers (MAPC)",
        "Gross Bookings by segment",
        "Take rate (Mobility and Delivery)",
        "Adjusted EBITDA and free cash flow",
        "Trips per MAPC (frequency)",
        "Uber One membership count",
        "Advertising revenue run rate",
    ],
    competitive_advantages=[
        "Global network density — 7B+ annual trips across 70+ countries; higher "
        "density → shorter wait times → more demand → self-reinforcing local network effect",
        "Cross-platform data flywheel — Mobility + Delivery in one app enables "
        "Uber One bundling; pure-play competitors (DoorDash, Lyft) lack this",
        "AV optionality without AV R&D cost — Waymo partnership provides upside "
        "from autonomous cost reductions without $10B+ internal development burn",
    ],
    business_model_keywords=[
        "Mobility", "Delivery", "Uber Eats", "Gross Bookings", "take rate",
        "MAPC", "trips", "Uber One", "advertising", "autonomous vehicle",
        "Waymo", "driver incentives", "Dara Khosrowshahi", "ride-sharing",
        "gig economy", "food delivery", "freight", "surge pricing", "AB5",
    ],
    moat_type=["network_effect", "data_advantage"],
    revenue_model="transaction_toll",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="moderate",
    binary_risk_level="none",
))


# ── Intel Corporation (INTC) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="INTC",
    company_name="Intel Corporation",
    business_model=(
        "Intel is an integrated device manufacturer (IDM) designing and fabricating "
        "semiconductors across client computing (CCG), data center and AI (DCAI), "
        "network and edge (NEX), Intel Foundry Services (IFS), and Mobileye (ADAS). "
        "The IDM 2.0 strategy bets that in-house manufacturing — specifically the "
        "18A process node — will close the gap with TSMC by 2025-26 and attract "
        "external foundry customers."
    ),
    primary_revenue_drivers=[
        "Client Computing Group (CCG) — Core Ultra CPUs for laptops/desktops (~40% "
        "of revenue; AI PC cycle with NPU-enabled Meteor/Lunar Lake is the catalyst)",
        "Data Center & AI (DCAI) — Xeon server CPUs + Gaudi AI accelerators (~25%; "
        "AMD EPYC taking share rapidly)",
        "Intel Foundry Services (IFS) — external wafer fabrication (early stage)",
        "Network & Edge (NEX) (~15%)",
        "Mobileye (~7% — ADAS/autonomous driving EyeQ chips)",
    ],
    recurring_revenue_sources=[
        "Multi-year OEM supply agreements (HP, Dell, Lenovo PC partnerships)",
        "Hyperscaler Xeon server refresh cycles (2-4 year replacement cadence)",
        "Intel Foundry long-term wafer agreements (18A process commitments)",
        "Mobileye EyeQ automotive production programs (multi-year design wins)",
    ],
    rate_sensitivity_note=(
        "INTC trades at ~20-25x depressed forward P/E. Rising rates raise the cost "
        "of the massive CapEx program ($20-25B/yr for IDM 2.0), partially offset by "
        "$8.5B CHIPS Act grants. Higher rates increase the hurdle rate for IFS "
        "foundry profitability and stress the balance sheet during negative FCF years."
    ),
    inflation_pass_through=(
        "Limited: Intel has lost pricing power in server CPUs to AMD EPYC and in "
        "AI accelerators to NVIDIA. PC CPU pricing faces pressure from AMD in "
        "consumer and ARM/Qualcomm Snapdragon X in AI PC. Cost inflation cannot "
        "be passed through when market share is being lost simultaneously."
    ),
    recession_behavior=(
        "PC market has cyclical sensitivity — CCG revenue collapsed in 2022-23 "
        "post-COVID. Server CPU refreshes decelerate in downturns.  Intel's "
        "fixed-cost manufacturing base creates significant operating leverage.  "
        "However, the secular demand for AI PC and the growing Intel Foundry "
        "external wafer business provide a resilient long-term demand foundation "
        "that partially offsets near-term cyclical pressure."
    ),
    major_risks=[
        "18A node execution — any yield or performance shortfall vs TSMC destroys "
        "the IFS thesis and strands $100B+ of committed CapEx",
        "AMD EPYC structural share gains — AMD taking 20%+ of x86 server CPU market",
        "ARM architecture disruption — Apple M-series, Qualcomm Snapdragon X prove "
        "ARM outperforms x86 on perf/watt in AI PCs, threatening CCG's core franchise",
        "Gaudi AI commercial traction — NVIDIA H100/B100 dominance leaves Intel "
        "fighting for scraps; without hyperscaler adoption Intel misses the AI buildout",
        "FCF negative during investment cycle — cash burn and balance sheet stress",
    ],
    valuation_style=(
        "Deep value / turnaround — valued on normalized EPS 2-3 years out. Bull case: "
        "18A works, IFS wins foundry customers, re-rates to hybrid IDM/foundry multiple. "
        "Bear case: IDM 2.0 fails, Intel splits into fabless designer + divested foundry."
    ),
    key_metrics=[
        "18A process node yield rate vs TSMC N2 equivalent",
        "DCAI revenue and Gaudi AI accelerator bookings",
        "AMD server CPU market share (inverse Intel indicator)",
        "IFS external revenue and wafer starts",
        "CCG ASP and AI PC attach rate",
        "Gross margin trajectory (compressed below 40%)",
        "CapEx and FCF (negative during investment phase)",
    ],
    competitive_advantages=[
        "x86 installed base — billions of lines of x86-optimized enterprise software "
        "create migration friction; server workloads cannot easily switch to ARM/AMD",
        "Western IDM geopolitical value — only US-headquartered advanced fab; CHIPS "
        "Act and EU sovereignty demand provide structural IFS customer pipeline if 18A delivers",
        "Mobileye ADAS leadership — EyeQ platform with multi-year OEM design win "
        "pipelines; SuperVision/Chauffeur autonomy platforms in development",
    ],
    business_model_keywords=[
        "IDM 2.0", "Intel Foundry", "IFS", "18A", "Intel 3", "Gaudi", "Xeon",
        "Core Ultra", "Meteor Lake", "Lunar Lake", "CCG", "DCAI",
        "Mobileye", "EyeQ", "CHIPS Act", "Pat Gelsinger", "process node",
        "AI PC", "AMD EPYC", "server CPU", "wafer", "ARM competition",
    ],
))


# ── Mastercard Inc. (MA) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="MA",
    company_name="Mastercard Inc.",
    business_model=(
        "Mastercard operates the world's second-largest open-loop payment network, "
        "earning net revenue as a small percentage of Gross Dollar Volume (GDV) "
        "processed across its network — via assessments, data processing fees, and "
        "cross-border transaction fees.  Completely asset-light: Mastercard never "
        "takes credit risk; it is a toll road on global consumer and commercial spending."
    ),
    primary_revenue_drivers=[
        "Domestic assessments (~30% of net revenue) — basis points on domestic GDV switched",
        "Cross-border volume fees (~30%, highest margin) — premium fee on international "
        "transactions at 4-6x domestic rate; most economically sensitive segment",
        "Transaction processing fees (~25%) — per-transaction authorization/clearing fee",
        "Value-added services (~15%) — cyber/intelligence (NuData, RiskRecon), "
        "data analytics, loyalty, open banking (Vocalink)",
    ],
    recurring_revenue_sources=[
        "Network participation fees from ~3,200 issuing banks",
        "Multi-year incentive agreements with major issuers (JPM, Citi) — "
        "volume rebates recorded as contra-revenue",
        "Mastercard Cyber & Intelligence annual contracts",
        "Government and B2B payment services via Mastercard Track and Send",
    ],
    rate_sensitivity_note=(
        "MA trades at ~32-38x forward EPS. Higher rates historically correlate "
        "with economic expansion and strong consumer spending — NET POSITIVE for "
        "GDV growth. Unlike banks, MA has zero credit risk and no NIM compression. "
        "The primary rate sensitivity is multiple compression, not fundamentals."
    ),
    inflation_pass_through=(
        "Exceptional: Mastercard earns a percentage of transaction VALUE — inflation "
        "inflates nominal GDV mechanically, increasing MA revenue without any volume "
        "change. High-inflation environments are among the most favorable revenue "
        "backdrops for payment networks."
    ),
    recession_behavior=(
        "Cyclical on GDV growth — consumer spending slows in downturns. Cross-border "
        "travel (premium-fee segment) is most economically sensitive. The secular "
        "cash-to-card shift provides structural tailwind. MA maintained strong FCF "
        "through the 2020 COVID collapse. Overall earnings are highly resilient."
    ),
    major_risks=[
        "Account-to-account (A2A) disintermediation — FedNow, PIX, UPI, SEPA Instant "
        "bypass the four-party card network; if A2A reaches consumer scale at "
        "merchant checkout, GDV could shift without MA earning a fee",
        "Regulatory interchange caps — EU, Australia, Durbin Amendment reduce issuer "
        "economics, potentially reducing premium card issuance that drives high GDV",
        "Big Tech closed-loop networks — Apple Pay/Google Pay use MA rails today "
        "but could develop independent networks over time",
        "Sovereign payment nationalism — Russia exclusion (2022) showed geopolitical "
        "risk of network access being severed in large markets",
    ],
    valuation_style=(
        "Premium multiple (~32-38x P/E) justified by asset-light model (>55% operating "
        "margin), secular GDV growth, and oligopoly franchise with Visa. "
        "Re-rating via value-added services reaching 20%+ growth and open banking "
        "platform (Vocalink) monetization."
    ),
    key_metrics=[
        "Gross Dollar Volume (GDV) — domestic and cross-border",
        "Switched transaction count and growth",
        "Cross-border volume as % of GDV",
        "Value-added services (VAS) revenue growth",
        "Net revenue yield on GDV",
        "Rebates and incentives as % of gross revenue",
        "Operating margin (>55%)",
    ],
    competitive_advantages=[
        "Two-sided oligopoly with Visa — controls ~80% of global general-purpose "
        "card volume; no new entrant has built a competing global acceptance network "
        "in 60 years",
        "Cross-border premium — international transactions earn 4-6x domestic rates; "
        "globalization of e-commerce disproportionately benefits MA",
        "Tokenization platform — 25B+ card credentials tokenized; issuers rely on "
        "MA's token infrastructure, deepening network stickiness",
    ],
    business_model_keywords=[
        "GDV", "gross dollar volume", "cross-border", "switched transactions",
        "assessments", "tokenization", "NuData", "Vocalink", "open banking",
        "Mastercard Send", "contactless", "B2B payments", "value-added services",
        "rebates", "incentives", "account-to-account", "interchange",
        "payment network", "FedNow", "real-time payments",
    ],
    moat_type=["network_effect", "brand", "scale_economy"],
    revenue_model="transaction_toll",
    switching_cost_level="very_high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── BlackRock Inc. (BLK) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="BLK",
    company_name="BlackRock Inc.",
    business_model=(
        "BlackRock is the world's largest asset manager with ~$10-11T AUM, earning "
        "fee revenue as a basis-point percentage of assets under management.  The "
        "iShares ETF franchise is the largest passive investment platform globally. "
        "Technology services (Aladdin risk-management platform) and alternatives "
        "(private credit, infrastructure, hedge funds) are higher-margin, faster-growing "
        "segments diversifying away from fee-compressed passive indexing."
    ),
    primary_revenue_drivers=[
        "Investment advisory and administration fees (~85% of revenue) — blended "
        "basis-point fee on $10T+ AUM; mix between passive ETFs (~4bps), active (~30bps), "
        "and alternatives (~75-100bps) determines blended revenue yield",
        "Technology services — Aladdin platform (~9% of revenue, growing ~10%/yr) "
        "licensed to 200+ asset managers, insurers, pension funds globally",
        "Distribution fees and advisory (~6%)",
    ],
    recurring_revenue_sources=[
        "iShares ETF management fees — ~$6T in AUM at ~4bps average = ~$2.4B annually",
        "Aladdin annual contract value (ACV) — multi-year enterprise SaaS contracts "
        "with 90%+ renewal rates across 200+ institutional clients",
        "Alternatives management fees (private credit, infrastructure, real estate) — "
        "typically 1-1.5% on committed capital",
        "Performance fees from alternatives (carried interest above hurdle rates)",
    ],
    rate_sensitivity_note=(
        "BLK trades at ~20-24x forward EPS. Higher rates are a DOUBLE-EDGED sword: "
        "Rising rates reduce equity AUM (market beta drag on stock/bond AUM) but "
        "increase money market fund inflows (BlackRock manages large MMF complex). "
        "Higher rates make Aladdin risk modeling more critical, driving platform demand. "
        "Alternatives AUM (private credit) actually BENEFITS from higher rates — "
        "direct lending earns wider spreads. Net rate sensitivity is near-neutral."
    ),
    inflation_pass_through=(
        "Asset management fees are contractually percentage-of-AUM — nominal AUM "
        "grows with inflation over time, passively inflating fee revenue. Fee "
        "compression in passive is structural and ongoing (iShares fees compressed "
        "from ~10bps to ~4bps over a decade). Alternatives command durable higher fees."
    ),
    recession_behavior=(
        "AUM falls with markets — in the 2022 bear market, BLK AUM fell ~$1.4T "
        "and revenue declined. However, Aladdin revenues are subscription-based and "
        "counter-cyclical (risk software is most valuable in downturns). "
        "Net inflows historically remain positive even as markets fall, as clients "
        "continue adding money; it is existing AUM repricing that hurts revenue."
    ),
    major_risks=[
        "Market beta risk — S&P 500 correction of 30% would reduce equity AUM "
        "by ~$1T+ and compress fee revenue meaningfully",
        "Fee compression in passive — Vanguard, Fidelity zero-fee funds pressure "
        "iShares to cut fees; structural long-term margin headwind",
        "Alternatives performance risk — private credit and infrastructure fund "
        "returns must justify the 75-100bps fees vs liquid alternatives",
        "ESG backlash — state pension fund withdrawals ($billions) from BlackRock "
        "over ESG investing stance (Texas, Florida, other red states)",
        "GIP acquisition integration — $3B acquisition of Global Infrastructure "
        "Partners must deliver AUM growth to justify the price",
    ],
    valuation_style=(
        "BLK valued on P/E (~20-24x) and EV/EBITDA, with premium for Aladdin's "
        "technology business (SaaS multiple). Key re-rating: alternatives AUM "
        "crossing $400B+ (driving fee mix improvement) and Aladdin revenue growing "
        "above 15% (proving technology platform is a durable second segment)."
    ),
    key_metrics=[
        "Total AUM ($T) and net new asset flows",
        "AUM mix: passive vs active vs alternatives",
        "Blended basis-point fee rate (revenue yield on AUM)",
        "Aladdin ACV and technology services revenue growth",
        "Alternatives AUM and fundraising pace",
        "Operating margin (target ~44-46%)",
        "Performance fees (alternatives carried interest)",
    ],
    competitive_advantages=[
        "iShares ETF network effect — largest ETF AUM creates tightest bid-ask "
        "spreads and highest liquidity, attracting more assets in a self-reinforcing cycle; "
        "no competitor can replicate the $6T iShares liquidity premium",
        "Aladdin platform stickiness — Aladdin manages risk and operations for "
        "$20T+ of third-party assets; switching costs are massive (re-implementation "
        "takes 2-3 years and hundreds of millions in transition cost)",
        "Alternatives scale — $300B+ alternatives AUM (private credit, infrastructure, "
        "hedge funds) provides high-margin fee revenue that passive competitors lack",
    ],
    business_model_keywords=[
        "AUM", "iShares", "Aladdin", "ETF", "passive", "active", "alternatives",
        "private credit", "infrastructure", "Larry Fink", "GIP", "net flows",
        "basis point", "fee rate", "BlackRock Solutions", "ESG",
        "money market fund", "Preqin", "eFront", "asset management",
    ],
    moat_type=["scale_economy", "brand", "data_advantage"],
    revenue_model="licensing",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Philip Morris International (PM) ─────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="PM",
    company_name="Philip Morris International Inc.",
    business_model=(
        "Philip Morris International sells tobacco and nicotine products internationally "
        "(ex-USA) — combustible cigarettes (Marlboro and local brands) still generating "
        "the majority of revenue, but rapidly transitioning to smoke-free alternatives: "
        "IQOS heated tobacco devices and HeatSticks consumables, ZYN nicotine pouches "
        "(via Swedish Match acquisition, 2022), and Veev e-vapor.  The smoke-free "
        "transformation targets >50% of revenue from smoke-free products by mid-2025."
    ),
    primary_revenue_drivers=[
        "IQOS / HeatSticks (heated tobacco) — fastest-growing segment; Japan, Italy, "
        "Germany, Korea, Eastern Europe are core IQOS markets; consumable blades "
        "drive recurring revenue (~35%+ of net revenue growing to ~50%+)",
        "Combustible cigarettes (Marlboro and local brands) — declining volume but "
        "strong pricing power in international markets (~55% of net revenue, declining)",
        "ZYN nicotine pouches (Swedish Match) — US and Nordic markets; highest "
        "margin product; ZYN is the leading nicotine pouch brand in the US (~30%+)",
    ],
    recurring_revenue_sources=[
        "IQOS HeatStick blade consumables — users who buy IQOS devices generate "
        "recurring blade purchases at ~$6-8/pack equivalent ASP",
        "ZYN can subscriptions via PMI Direct and retail re-purchase",
        "Combustible cigarette re-purchase (daily habit with high repurchase frequency)",
    ],
    rate_sensitivity_note=(
        "PM trades at ~15-18x forward EPS with a 5-6% dividend yield — a value/yield "
        "profile. Higher rates compress bond-proxy multiples like PM. "
        "The $26B Swedish Match acquisition was funded with debt; higher rates "
        "increase interest expense directly. PM reports in USD but generates most "
        "revenue outside the US — a stronger dollar compresses reported earnings "
        "even when local-currency business is healthy."
    ),
    inflation_pass_through=(
        "Exceptional pricing power on both combustibles and smoke-free: "
        "tobacco is addictive — demand is inelastic to price changes. PM has "
        "consistently raised combustible cigarette prices above inflation globally. "
        "IQOS HeatStick pricing has been stable with room to increase as "
        "the heated tobacco category matures and brand loyalty deepens."
    ),
    recession_behavior=(
        "Tobacco is one of the most recession-resistant consumer staples categories. "
        "Cigarette demand showed minimal volume decline in every prior recession — "
        "the addictive product profile insulates demand. PM's geographic diversification "
        "across Europe, Asia, and LatAm further reduces single-market cyclicality."
    ),
    major_risks=[
        "Regulatory crackdown on heated tobacco — FDA, EU, and individual-country "
        "regulators could restrict IQOS marketing, flavors, or sales (e.g., "
        "Australia plain packaging, EU TPD revision)",
        "ZYN FDA regulatory risk — FDA review of nicotine pouches could impose "
        "restrictions or marketing bans that curb the fastest-growing segment",
        "FX headwinds — yen, euro, and EM currency weakness directly compresses "
        "USD-reported earnings (100 bps EUR/USD move = ~$0.04 EPS impact)",
        "Combustible volume decline accelerating faster than smoke-free revenue offsets",
        "Swedish Match debt integration — $26B acquisition debt levels interest coverage",
    ],
    valuation_style=(
        "PM valued on P/E (~15-18x) and dividend yield (~5-6%). The smoke-free "
        "transformation is a re-rating catalyst — as smoke-free revenue share crosses "
        "50%, the multiple could expand from a 'tobacco' discount to a 'consumer "
        "staples growth' premium (~20-22x). ZYN US success is the near-term "
        "sentiment driver."
    ),
    key_metrics=[
        "IQOS shipment volumes (HeatStick blades) and IQOS user count",
        "Smoke-free net revenue as % of total (target >50%)",
        "ZYN can shipments and US market share",
        "Combustible volume decline rate vs price/mix benefit",
        "FX-neutral net revenue growth",
        "Operating margin and FCF (supports $8B+ annual dividend)",
        "Swedish Match net debt reduction trajectory",
    ],
    competitive_advantages=[
        "IQOS first-mover in heated tobacco — launched in 2014; $10B+ invested in "
        "device development and regulatory science; 22M+ IQOS users globally; "
        "BAT and JTI remain years behind in product quality and user base",
        "Marlboro brand equity — among the most valuable consumer brands globally; "
        "pricing power in premium combustibles funds the smoke-free transition R&D",
        "ZYN nicotine pouch category leadership — ZYN launched in the US in 2016 "
        "and holds ~75% of a $4B+ and rapidly growing category; brand loyalty "
        "and distribution create durable leadership",
    ],
    business_model_keywords=[
        "IQOS", "HeatSticks", "heated tobacco", "smoke-free", "ZYN",
        "Swedish Match", "nicotine pouch", "Marlboro", "Japan market",
        "combustible", "HTU", "Heets", "Terea", "Veev", "e-vapor",
        "Alain Nassar", "FX", "dividend", "smoke-free transformation",
        "nicotine", "blade consumable",
    ],
))


# ── United Parcel Service (UPS) ───────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="UPS",
    company_name="United Parcel Service Inc.",
    business_model=(
        "UPS operates the world's largest package delivery network and a growing "
        "healthcare/specialized logistics business.  Revenue comes from US Domestic "
        "Package (~62%), International Package (~22%), and Supply Chain Solutions "
        "(~16% — healthcare logistics, UPS Capital, freight brokerage).  "
        "CEO Carol Tomé is executing a 'better not bigger' strategy — prioritizing "
        "revenue quality (revenue per piece) over volume growth."
    ),
    primary_revenue_drivers=[
        "US Domestic Package — ground and air delivery; SMB mix (higher yield) "
        "and healthcare expansion are the revenue quality levers (~62% of revenue)",
        "International Package — export/import ground and air in Europe, Asia, Americas "
        "(~22%); higher margin than domestic",
        "Supply Chain Solutions — healthcare logistics (Marken clinical trials, "
        "specialty pharma), UPS Capital (insurance/financing), freight (~16%)",
    ],
    recurring_revenue_sources=[
        "Annual volume agreements with major shippers (negotiated each fall)",
        "Healthcare cold-chain logistics (multi-year specialty pharma supply agreements)",
    ],
    rate_sensitivity_note=(
        "UPS trades at ~16-20x forward EPS. Higher rates modestly increase the cost "
        "of fleet financing (large truck and aircraft fleet) and pension liabilities. "
        "More importantly, higher rates slow e-commerce growth (consumer credit "
        "sensitivity) which directly reduces package volume demand. UPS is more "
        "sensitive to economic growth than to the rate cycle directly."
    ),
    inflation_pass_through=(
        "Moderate: UPS charges fuel surcharges (pass-through) and has implemented "
        "general rate increases (GRI) of 5-6.9% annually since 2021. However, "
        "contract customers negotiate caps. Revenue per piece improvement is the "
        "primary pricing strategy — shifting mix toward SMB and healthcare "
        "from lower-yield consumer e-commerce."
    ),
    recession_behavior=(
        "Package volume is economically sensitive — industrial production and "
        "B2B shipments decline in recessions; consumer e-commerce demand is more "
        "resilient through moderate slowdowns.  The 2022-23 post-COVID normalization "
        "hit UPS volume severely as e-commerce normalized.  Healthcare logistics "
        "provides revenue stability as clinical supply chains continue regardless "
        "of economic conditions."
    ),
    major_risks=[
        "Amazon building its own delivery network (AMZN Logistics) — Amazon is "
        "reducing UPS dependency; Amazon was ~11% of UPS revenue and declining",
        "Teamsters contract cost increases — 2023 Teamsters contract adds significant "
        "driver labor cost; annual pay escalation baked into 5-year agreement",
        "Volume loss to FedEx and regional carriers in e-commerce",
        "E-commerce structural volume pressure from customer mix improvement "
        "strategy reducing low-yield volume",
        "Softening industrial production dragging B2B package volumes",
    ],
    valuation_style=(
        "UPS valued on P/E (~16-20x) and EV/EBITDA. The stock tracks earnings "
        "per piece (revenue/margin quality) and volume inflection points. "
        "Re-rating catalyst: healthcare logistics reaching $20B revenue and "
        "demonstrating a higher-margin, less-cyclical business mix."
    ),
    key_metrics=[
        "Average daily volume (ADV) — domestic and international",
        "Revenue per piece (yield) — most important quality metric",
        "Adjusted operating margin by segment",
        "Healthcare logistics revenue and margin",
        "SMB volume as % of domestic mix",
        "Free cash flow and dividend coverage",
        "Teamsters labor cost per delivery",
    ],
    competitive_advantages=[
        "Integrated air-ground network — UPS owns 280+ aircraft and 125,000+ "
        "ground vehicles; the cost to replicate this integrated network exceeds "
        "$100B; regional competitors cannot match overnight/2-day coverage nationally",
        "ORION and EDGE route optimization — proprietary algorithms reduce driver "
        "miles; EDGE scheduling AI creates 10-15% productivity improvement vs "
        "manual scheduling, enabling the 'better not bigger' margin expansion",
        "Healthcare logistics specialization — Marken (clinical trial logistics), "
        "temperature-controlled shipping, and regulatory expertise create a "
        "defensible healthcare moat that pure-play parcel competitors lack",
    ],
    business_model_keywords=[
        "average daily volume", "ADV", "revenue per piece", "revenue quality",
        "ground", "SurePost", "healthcare logistics", "Marken", "UPS Capital",
        "ORION", "EDGE", "SMB", "Teamsters", "Carol Tomé", "peak surcharge",
        "better not bigger", "air freight", "international package",
        "supply chain", "e-commerce", "Amazon",
    ],
))


# ── Deere & Company (DE) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="DE",
    company_name="Deere & Company",
    business_model=(
        "Deere manufactures and finances precision agricultural, construction, and "
        "turf equipment.  The company is transitioning to a technology-led model: "
        "autonomous tractors, the See & Spray precision herbicide system, JDLink "
        "telematics, and Operations Center farm management software create a SaaS "
        "layer atop equipment sales.  John Deere Financial provides equipment "
        "financing, adding a recurring interest income stream."
    ),
    primary_revenue_drivers=[
        "Production & Precision Agriculture (PPA) — large row-crop equipment "
        "(8R tractors, S-series combines, ExactEmerge planters) for US/Brazil "
        "large farms (~50% of equipment revenue)",
        "Small Agriculture & Turf — smaller tractors, turf/utility; more "
        "consumer-facing and consumer credit sensitive (~20%)",
        "Construction & Forestry — excavators, bulldozers, road machinery; "
        "infrastructure construction cycle dependent (~25%)",
        "John Deere Financial — equipment financing portfolio (~5% of revenue, "
        "~15% of operating income; interest income grows with higher rates)",
    ],
    recurring_revenue_sources=[
        "JDLink telematics subscriptions — remote diagnostics and fleet management",
        "Operations Center farm management software subscriptions",
        "See & Spray Ultimate and autonomy software licenses (emerging)",
        "John Deere Financial lease and loan portfolio (recurring interest income)",
        "Extended warranty and dealer maintenance agreements",
    ],
    rate_sensitivity_note=(
        "DE trades at ~15-20x mid-cycle earnings. Higher rates have two opposing "
        "effects: John Deere Financial earns higher interest income (positive), "
        "but higher financing costs reduce farmer equipment purchase propensity "
        "(negative). Farm income is the dominant demand driver — corn, soybean, "
        "and wheat prices determine whether farmers can afford new $600K+ combines."
    ),
    inflation_pass_through=(
        "Historically strong: Deere has raised large-ag equipment prices 20-40% "
        "cumulatively since 2021 with minimal demand destruction due to record "
        "farm income. However, in a farm income down-cycle, pricing power reverts "
        "as farmers defer replacement purchases. Steel and component inflation "
        "compresses margins in upcycles before price increases catch up."
    ),
    recession_behavior=(
        "Highly cyclical in construction but semi-defensive in large ag: US crop "
        "farmers must eventually replace equipment regardless of macro, driven by "
        "age of fleet and productivity needs. However, with the equipment fleet "
        "currently newer than historical averages (post-2021 buying surge), "
        "replacement demand is likely to trough in 2024-26 as dealers destock."
    ),
    major_risks=[
        "Ag cycle downturn — corn/soybean prices falling from recent highs would "
        "reduce farm income and defer equipment replacement; dealer inventory "
        "destocking is already underway in 2024-25",
        "Precision ag technology commoditization — CNH (Case IH/New Holland) "
        "and AGCO (Fendt) are investing heavily in autonomy and digital platforms",
        "Autonomous regulation — self-driving farm equipment requires USDA/state "
        "approval pathways that may slow the 8R autonomous commercialization",
        "Trade policy risk — US-China tariffs on soybeans reduce farm income "
        "and equipment demand; Brazil farm expansion is a partial offset",
        "Interest rate cycle via John Deere Financial credit losses in downturns",
    ],
    valuation_style=(
        "DE valued on P/E against mid-cycle earnings power (~$20-25/share normalized). "
        "The market prices a technology optionality premium atop the cyclical base — "
        "if See & Spray and autonomous 8R tractor generate $5-10/share of SaaS-like "
        "earnings, the multiple expands significantly beyond traditional ag-equipment peers."
    ),
    key_metrics=[
        "Net equipment sales by segment (PPA, Small Ag, Construction)",
        "Operating margin by segment",
        "Equipment order book and dealer inventory days",
        "Precision agriculture SaaS attached rate (Operations Center users)",
        "See & Spray Ultimate acres treated",
        "John Deere Financial portfolio quality (delinquencies)",
        "Farm income indicators (USDA corn/soybean price and farm cash receipts)",
    ],
    competitive_advantages=[
        "Installed base and dealer network — 5,000+ North American dealer locations "
        "with trained technicians; switching from John Deere mid-farm-season means "
        "losing Deere-specific service support in harvest-critical moments",
        "Precision ag data flywheel — Operations Center has 400M+ acres of farm "
        "data; AI models trained on this proprietary dataset improve crop yield "
        "recommendations, increasing SaaS value and switching costs",
        "See & Spray technology — patented computer-vision system that spots and "
        "targets individual weeds, reducing herbicide use 77%+; no competitor "
        "has a commercially deployed equivalent at scale",
    ],
    business_model_keywords=[
        "Production & Precision Agriculture", "PPA", "8R tractor", "ExactEmerge",
        "JDLink", "Operations Center", "See & Spray", "John Deere Financial",
        "autonomy", "precision agriculture", "combine", "row crop",
        "farm income", "corn", "soybean", "John May", "dealer inventory",
        "SaaS", "ag cycle", "construction machinery",
    ],
))


# ── Duke Energy Corporation (DUK) ─────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="DUK",
    company_name="Duke Energy Corporation",
    business_model=(
        "Duke Energy is a large regulated electric and gas utility serving "
        "8.2M+ electric customers across the Carolinas, Florida, Indiana, Ohio, "
        "and Kentucky.  Earnings are driven by rate-base growth — capital investment "
        "in grid modernization, renewable energy (solar, wind, battery storage), "
        "and EV infrastructure earns a regulated return (allowed ROE ~9.5-10%). "
        "The clean energy transition plan calls for retiring coal and building "
        "40+ GW of renewable generation by 2035."
    ),
    primary_revenue_drivers=[
        "Duke Energy Carolinas + Duke Energy Progress (NC/SC) — largest segment; "
        "growing rate base with solar, transmission grid hardening (~40% of earnings)",
        "Duke Energy Florida — regulated utility in Florida; rate base growing "
        "with strong population in-migration and solar buildout (~20%)",
        "Duke Energy Indiana + Ohio + Kentucky — Midwest utilities; coal retirement "
        "and renewable replacement driving capital deployment (~25%)",
        "Duke Energy Gas Utilities — Piedmont Natural Gas (NC/SC) and gas distribution (~15%)",
    ],
    recurring_revenue_sources=[
        "Regulated electric distribution tariffs — cost-of-service rates set "
        "by state utility commissions (NC, SC, FL, IN, OH, KY)",
        "Regulated natural gas distribution revenue (Piedmont)",
        "Power purchase agreement (PPA) revenue from renewable generation sold "
        "to industrial and commercial customers",
    ],
    rate_sensitivity_note=(
        "DUK trades at ~16-19x forward EPS — a defensive utility multiple. "
        "Duke's stock is highly sensitive to interest rates because: 1) its "
        "4%+ dividend yield competes directly with 10-year Treasury yields "
        "(when T-yield rises, utility yield premium shrinks); 2) Duke carries "
        "$65B+ of long-term debt — higher refinancing rates increase interest "
        "expense over time; 3) the WACC used in rate cases rises, theoretically "
        "supporting higher allowed ROE in future rate cases (partial offset)."
    ),
    inflation_pass_through=(
        "Limited but structured: Duke recovers fuel costs through fuel adjustment "
        "clauses (pass-through to customers). Capital cost inflation is recovered "
        "through rate base (CapEx added to rate base earns allowed ROE) but with "
        "a multi-year regulatory lag — cost overruns reduce earned ROE until "
        "the next rate case. Construction cost inflation on the renewable buildout "
        "is the primary near-term risk."
    ),
    recession_behavior=(
        "Highly defensive — regulated utility revenue is essentially fixed "
        "regardless of economic conditions. Duke's service territories include "
        "residential, commercial, and industrial customers; residential bills are "
        "inelastic. Industrial load could decline modestly in a deep recession. "
        "Duke has generated positive EPS in every recession in its history."
    ),
    major_risks=[
        "Regulatory rate case risk — NC/SC utility commissions are the primary "
        "earnings governors; disallowances of CapEx, below-allowed ROE outcomes, "
        "or formula rate rejection could compress earnings",
        "Coal retirement stranded costs — retiring coal plants before the end "
        "of their depreciable lives creates potential for stranded cost disputes "
        "where regulators may disallow recovery",
        "Clean energy capital execution risk — $65B+ of planned CapEx by 2035 "
        "requires reliable access to capital markets and regulatory approval; "
        "interest rate increases raise the cost of financing this build",
        "Hurricane exposure (Carolinas, Florida) — storm damage CapEx can "
        "temporarily compress earned ROE before cost recovery through securitization",
        "New nuclear SMR optionality — Duke is studying SMRs; if constructed, "
        "cost overruns are the primary risk",
    ],
    valuation_style=(
        "Classic regulated utility valuation: P/E (~16-19x), EV/EBITDA (~12-15x), "
        "and dividend yield (~4-5%). The stock trades at a premium/discount to "
        "utility peers based on rate base growth rate, regulatory relationship quality, "
        "and balance sheet strength. Rate base CAGR of 6-7% supports 5-7% EPS CAGR."
    ),
    key_metrics=[
        "Rate base growth (target 6-7% CAGR) by jurisdiction",
        "Adjusted EPS growth (target 5-7% CAGR)",
        "CapEx plan execution ($65B+ through 2028)",
        "Allowed vs earned ROE by subsidiary",
        "Renewable GW additions per year",
        "Dividend coverage ratio (payout ~65-70%)",
        "Long-term debt maturity schedule and refinancing risk",
        "Industrial load growth (data center and manufacturing)",
    ],
    competitive_advantages=[
        "Regulated monopoly franchise in high-growth Sun Belt territories — "
        "Carolinas and Florida demographic tailwinds create organic load growth "
        "without Duke needing to compete for customers",
        "Scale in renewable procurement — $65B+ renewable buildout provides "
        "procurement leverage on solar panels and wind turbines; small utilities "
        "cannot achieve comparable cost reductions",
        "Integrated utility vertical — Duke owns generation, transmission, "
        "and distribution in most service territories, allowing vertically-integrated "
        "recovery of clean energy transition capital across all components",
    ],
    business_model_keywords=[
        "Duke Energy Carolinas", "Duke Energy Florida", "Duke Energy Progress",
        "Piedmont Natural Gas", "rate base", "capex", "clean energy transition",
        "coal retirement", "solar", "wind", "battery storage", "grid modernization",
        "Lynn Good", "allowed ROE", "rate case", "regulated utility",
        "IRP", "CPCN", "fuel adjustment", "data center load",
    ],
))


# ── Airbnb Inc. (ABNB) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="ABNB",
    company_name="Airbnb Inc.",
    business_model=(
        "Airbnb operates a global home-sharing and experiences marketplace — hosts list "
        "properties and experiences; guests book them.  Revenue is service fees charged "
        "to both hosts (~3% of booking value) and guests (~14-16%), netting to a "
        "~18-19% take rate on Gross Booking Value (GBV).  The model is fully "
        "asset-light — Airbnb owns no properties.  CEO Brian Chesky is pursuing "
        "profitable growth: expanding Rooms (private room in host's home), Experiences, "
        "and Co-host network to grow supply affordably."
    ),
    primary_revenue_drivers=[
        "Nights and experiences booked — volume driver; ~500M+ nights/yr globally",
        "Average Daily Rate (ADR) — ~$170-180 globally; mix toward urban and "
        "international markets is the ADR expansion lever",
        "Take rate on GBV (~18-19%) — service fee from hosts + guests",
        "GBV growth = nights × ADR",
    ],
    recurring_revenue_sources=[
        "Host platform access — hosts re-list properties every year",
        "Superhost loyalty program — top hosts retain annual Superhost status, "
        "reducing churn from high-quality supply",
        "Repeat guest booking — 50%+ of bookings from repeat users",
    ],
    rate_sensitivity_note=(
        "ABNB trades at ~25-35x forward EBITDA — a platform premium. "
        "Higher rates reduce consumer discretionary travel spending (negative for "
        "GBV). However, Airbnb benefits from the shift to longer stays and remote "
        "work — these trips are less interest-rate sensitive than vacation travel. "
        "ABNB has $11B+ of cash and no debt — completely insulated from direct "
        "interest expense sensitivity."
    ),
    inflation_pass_through=(
        "Partial: ADR has risen with inflation as host pricing follows hotel "
        "comparable rates. However, Airbnb faces consumer substitution risk at "
        "very high ADRs — if Airbnb prices match hotels but without hotel-quality "
        "service guarantees, consumers revert to hotels. Chesky's affordable "
        "Rooms strategy is a deliberate response to the affordability perception gap."
    ),
    recession_behavior=(
        "Travel is economically sensitive, but Airbnb's value proposition (often "
        "cheaper than comparable hotels) allows it to gain share in downturns as "
        "consumers trade down from luxury hotels.  Long-stay bookings (28+ nights) "
        "from remote workers are relatively resilient during economic softness.  "
        "The 2020 COVID collapse was the most severe stress test — Airbnb recovered "
        "to pre-COVID GBV levels by 2021."
    ),
    major_risks=[
        "Short-term rental regulation — NYC, Barcelona, Paris, Amsterdam, and 100+ "
        "cities have imposed or are considering STR restrictions that reduce "
        "host supply; regulatory attrition is the single largest supply-side risk",
        "Booking.com and Expedia competition — alternative accommodation segments "
        "on OTA platforms are growing, reducing Airbnb's differentiation",
        "Host supply growth slowdown — adding quality supply in dense urban markets "
        "is increasingly difficult as regulatory barriers and host economics tighten",
        "Guest safety/liability incidents — high-profile incidents create reputational "
        "damage and could trigger regulatory response",
        "Travel demand cyclicality in APAC where growth is most important",
    ],
    valuation_style=(
        "ABNB valued on EV/EBITDA (~25-35x) and FCF yield. "
        "The stock rewards nights growth × ADR expansion = GBV acceleration. "
        "FCF margin (~35-40% of revenue) is already best-in-class for travel platforms. "
        "Re-rating catalysts: Rooms and Experiences becoming meaningful new verticals "
        "that expand TAM beyond traditional vacation home rental."
    ),
    key_metrics=[
        "Nights and experiences booked",
        "Gross Booking Value (GBV)",
        "Average Daily Rate (ADR)",
        "Take rate on GBV",
        "Active listings count",
        "Free cash flow margin (~35-40%)",
        "Long-stay share (28+ nights) of total nights",
        "Geographic mix: APAC penetration",
    ],
    competitive_advantages=[
        "Supply-side brand recognition — 7M+ active listings globally; Airbnb is "
        "the default destination for hosts listing unique properties or spare rooms; "
        "network effects make the marketplace increasingly winner-take-most",
        "Unique inventory — treehouses, castles, private islands, Rooms in local "
        "hosts' homes; Booking.com and Expedia cannot replicate this inventory type "
        "because it requires host community trust and a peer-to-peer cultural fit",
        "Asset-light FCF machine — with no property ownership, Airbnb generates "
        "~35-40% FCF margins as revenue scales; fixed costs are primarily engineering "
        "and trust/safety, creating strong operating leverage",
    ],
    business_model_keywords=[
        "GBV", "gross booking value", "nights booked", "ADR", "average daily rate",
        "take rate", "host", "co-host", "Superhost", "Brian Chesky",
        "Rooms", "Experiences", "long stay", "APAC", "STR regulation",
        "free cash flow", "asset-light", "OTA", "vacation rental",
        "Airbnb-friendly apartments", "unique stays",
    ],
))


# ── Emerson Electric Co. (EMR) ────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="EMR",
    company_name="Emerson Electric Co.",
    business_model=(
        "Emerson has transformed from a diversified industrial conglomerate into a "
        "pure-play industrial automation and technology company.  Following the Copeland "
        "HVAC divestiture (2023) and AspenTech stake acquisition, Emerson operates "
        "two segments: Intelligent Devices (process/hybrid automation sensors, final "
        "control, measurement) and Software & Control (AspenTech simulation software, "
        "DeltaV distributed control system, Ovation DCS for power).  "
        "CEO Lal Karsanbhai leads the portfolio transformation."
    ),
    primary_revenue_drivers=[
        "Intelligent Devices (~60% of revenue) — process automation measurement "
        "(Rosemount sensors, Micro Motion flowmeters), final control (Fisher valves, "
        "Bettis actuators), discrete automation (ASCO valves)",
        "Software & Control (~40% of revenue) — AspenTech simulation/optimization "
        "software, DeltaV distributed control systems, Ovation DCS for power",
        "Service & solutions (~ongoing MRO) — maintenance, calibration, and "
        "aftermarket parts for installed Fisher, Rosemount, and DeltaV installed base",
    ],
    recurring_revenue_sources=[
        "AspenTech annual subscription licenses (80%+ recurring software revenue)",
        "Emerson service contracts for installed DeltaV and Ovation DCS systems",
        "Fisher valve MRO parts and maintenance (large installed base in refining, LNG)",
        "Rosemount sensor calibration and service agreements",
    ],
    rate_sensitivity_note=(
        "EMR trades at ~20-24x forward P/E. Higher rates do not directly impact "
        "Emerson's business model, but capital project delays by oil/gas, chemical, "
        "and power generation customers (who fund large automation CapEx) are "
        "interest-rate sensitive. Sustained high rates slow industrial project FIDs "
        "(final investment decisions), reducing automation order intake."
    ),
    inflation_pass_through=(
        "Good: Emerson supplies mission-critical instrumentation and control systems "
        "for safety-critical processes (LNG trains, refineries, power plants) — "
        "customers cannot easily switch suppliers mid-project due to qualification "
        "cycles (18-24 months for process instrument re-qualification). Pricing "
        "power is moderate-to-strong in sole-sourced instruments."
    ),
    recession_behavior=(
        "Industrial automation is capex-cycle sensitive — new plant construction "
        "(greenfield) orders are discretionary. However, MRO (maintenance, repair, "
        "operations) spending on existing Emerson-installed DeltaV/Fisher systems "
        "is more resilient as plant operators must maintain control system integrity. "
        "AspenTech software renewal rates are sticky even in downturns."
    ),
    major_risks=[
        "Process industry CapEx cycle — oil/gas, chemical, and LNG final investment "
        "decisions drive automation backlog; energy price weakness defers projects",
        "AspenTech integration and minority buyout — Emerson owns ~57% of AspenTech; "
        "future buyout of minority creates execution and valuation risk",
        "Competition from ABB, Siemens, Honeywell in DCS — all are investing heavily "
        "in industrial automation; price competition on large DCS projects is intense",
        "Energy transition timing — LNG automation is a key growth driver; if LNG "
        "FIDs slow due to energy policy changes, Emerson's order book contracts",
    ],
    valuation_style=(
        "EMR valued on P/E (~20-24x) and EV/EBITDA (~14-17x). The automation "
        "software mix improvement (AspenTech) and margin expansion post-portfolio "
        "transformation are the primary re-rating levers. "
        "Re-rating catalyst: Intelligent Devices margin reaching 25%+ and "
        "AspenTech growing ARR at 10%+ consistently."
    ),
    key_metrics=[
        "Orders growth and backlog by segment",
        "Intelligent Devices operating margin (target ~24-25%)",
        "AspenTech ARR growth and renewal rate",
        "Software & Control segment margin",
        "Organic sales growth (underlying demand ex-currency)",
        "Free cash flow conversion (>100% net income)",
        "Energy transition project wins (LNG, hydrogen, CCUS automation)",
    ],
    competitive_advantages=[
        "Fisher valve installed base — Fisher controls the largest share of "
        "safety-critical final control valves in global LNG, refining, and "
        "petrochemical processes; re-qualification cycles of 18-24 months mean "
        "customers rarely switch suppliers on operating plants",
        "DeltaV DCS ecosystem — Emerson's DeltaV is the leading DCS in life "
        "sciences (FDA 21 CFR Part 11 compliance) and a top-3 platform in "
        "refining and chemicals; multi-decade installed base creates replacement cycles",
        "AspenTech simulation monopoly — AspenTech's Aspen HYSYS and AspenOne "
        "are the de facto standard for process engineering simulation in "
        "oil/gas and chemicals; switching costs are measured in re-training "
        "thousands of engineers",
    ],
    business_model_keywords=[
        "DeltaV", "Ovation", "AspenTech", "HYSYS", "intelligent devices",
        "final control", "Fisher", "Rosemount", "Micro Motion", "Bettis",
        "ASCO", "process automation", "DCS", "distributed control",
        "Lal Karsanbhai", "LNG automation", "industrial automation",
        "Plantweb", "backlog", "MRO", "energy transition",
    ],
))


# ── American Electric Power (AEP) ─────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AEP",
    company_name="American Electric Power Company Inc.",
    business_model=(
        "AEP is one of the largest regulated electric utilities in the US, serving "
        "5.6M+ customers across 11 states (Texas, Ohio, West Virginia, Oklahoma, "
        "Indiana, Michigan, Arkansas, Louisiana, Virginia, Kentucky, and New Mexico). "
        "AEP operates the nation's largest transmission system (40,000+ circuit miles). "
        "Earnings are rate-base driven — capital invested in grid hardening, clean "
        "energy transition, and transmission expansion earns a regulated allowed ROE."
    ),
    primary_revenue_drivers=[
        "AEP Texas Central (~15% of earnings) — retail distribution in Texas; "
        "transmission-only in ERCOT; data center load growth tailwind",
        "AEP Ohio (~15%) — distribution utility; formula rate with annual updates",
        "Appalachian Power (VA/WV) (~12%) — regulated generation and distribution",
        "Southwestern Electric Power (SWEPCO, TX/LA/AR) (~10%)",
        "AEP Indiana Michigan and Public Service Company of Oklahoma combined (~20%)",
        "Transmission (AEP Transmission Holdco) (~20% of earnings, growing fastest)",
    ],
    recurring_revenue_sources=[
        "Regulated distribution tariffs set by 11 state utility commissions",
        "FERC-regulated transmission revenue (formula rates, transmission projects)",
        "Power purchase agreement revenue from renewable generation",
    ],
    rate_sensitivity_note=(
        "AEP trades at ~14-17x forward EPS — a mid-tier utility multiple. "
        "AEP carries $45B+ of long-term debt — one of the highest leverage ratios "
        "in the regulated utility sector. Higher rates directly increase AEP's "
        "refinancing costs and reduce FCF available for dividends. "
        "The dividend yield (~4-5%) competes with Treasury yields — rate rises "
        "compress the yield spread that justifies the utility premium."
    ),
    inflation_pass_through=(
        "Structured: AEP recovers fuel costs via fuel adjustment clauses (pass-through). "
        "Construction cost inflation is recovered through rate base additions, but "
        "with a regulatory lag until the next rate case in each of 11 jurisdictions. "
        "Multi-state regulatory complexity creates longer average lag than single-state peers."
    ),
    recession_behavior=(
        "Highly defensive — regulated utility revenues are quasi-fixed. Industrial "
        "load (manufacturing, mining in WV, TX) could decline modestly in recessions. "
        "Data center load growth in Texas and Ohio is incremental and counter-cyclical. "
        "AEP has positive EPS in every economic cycle historically."
    ),
    major_risks=[
        "Multi-state regulatory risk — 11 states create 11 different regulatory "
        "relationships; an unfavorable rate case in Ohio or Texas can materially "
        "impact earnings; WV and OK regulators are more challenging than FL or OH",
        "High leverage — $45B+ debt with rising rate environment increases "
        "refinancing costs; AEP's credit rating headroom is narrower than peers",
        "Coal retirement cost recovery — AEP has the largest remaining coal fleet "
        "of any major US utility; stranded cost risk from early coal retirements",
        "Transmission project execution — MISO and SPP transmission expansion "
        "projects require multi-state approval and can experience cost overruns",
        "ERCOT deregulation structure limits rate base growth in Texas distribution",
    ],
    valuation_style=(
        "Regulated utility P/E (~14-17x) and EV/EBITDA (~11-13x). AEP trades "
        "at a slight discount to utility peers due to higher leverage and coal "
        "exposure. Re-rating catalyst: coal fleet retirement completion and "
        "data center load growth in Texas and Ohio driving above-average "
        "rate base investment."
    ),
    key_metrics=[
        "Rate base growth by state (~7-8% CAGR target)",
        "Adjusted EPS growth (target 6-8% CAGR)",
        "Transmission revenue and FERC-approved project backlog",
        "CapEx plan execution ($43B+ through 2028)",
        "Long-term debt / EBITDA leverage ratio",
        "Allowed vs earned ROE by subsidiary",
        "Industrial load trends (TX data centers, WV industrial)",
    ],
    competitive_advantages=[
        "Largest transmission system in the US — 40,000+ circuit miles covering "
        "two-thirds of the Eastern Interconnection; transmission projects earn "
        "FERC-authorized returns with formula rates, providing predictable income",
        "Texas data center load growth — AEP Texas serves the rapidly growing "
        "Dallas-Fort Worth metroplex and data center corridor; incremental data "
        "center load earns distribution revenue at high incremental margins",
        "Vertically integrated position in most states — owning generation, "
        "transmission, and distribution allows recovery of clean energy transition "
        "capital across all three components of the regulated stack",
    ],
    business_model_keywords=[
        "AEP Texas", "AEP Ohio", "SWEPCO", "Appalachian Power", "transmission",
        "rate base", "capex", "formula rate", "FERC", "MISO", "SPP",
        "coal retirement", "renewable", "solar", "wind", "Bill Fehrman",
        "allowed ROE", "rate case", "data center load", "grid hardening",
        "regulated utility", "ERCOT",
    ],
))


# ── Exelon Corporation (EXC) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="EXC",
    company_name="Exelon Corporation",
    business_model=(
        "Exelon is the largest regulated transmission and distribution (T&D) utility "
        "in the US following the 2022 spinoff of Constellation Energy (power generation). "
        "Exelon operates six regulated utilities: ComEd (Illinois, 4M customers), "
        "PECO (Pennsylvania, 1.7M), BGE (Maryland, 1.3M), Pepco (DC/Maryland, 0.9M), "
        "Atlantic City Electric (NJ, 0.6M), and Delmarva Power (DE/MD, 0.5M). "
        "Earnings are 100% regulated — no merchant generation exposure."
    ),
    primary_revenue_drivers=[
        "ComEd (Illinois) (~35% of earnings) — distribution utility under "
        "multi-year rate plans (MYRP) and performance-based rates; largest single subsidiary",
        "PECO (Pennsylvania) (~20%) — electric and gas distribution",
        "BGE (Maryland) (~18%) — electric and gas distribution; "
        "formula rate with annual true-up",
        "Pepco Holdings (DC, MD, DE, NJ) (~27%) — Pepco, Atlantic City Electric, "
        "Delmarva Power; serving DC government and mid-Atlantic corridor",
    ],
    recurring_revenue_sources=[
        "Regulated electric and gas distribution tariffs set by IL, PA, MD, DC, "
        "NJ, DE utility commissions",
        "ComEd performance-based rate (formula rate annual reconciliation)",
        "FERC-regulated transmission revenue",
        "BGE formula rate annual updates (MD PSC)",
    ],
    rate_sensitivity_note=(
        "EXC trades at ~15-18x forward EPS — a pure-play regulated utility multiple. "
        "EXC's sensitivity to rates is primarily through multiple compression: "
        "its 3.5-4% dividend yield competes with Treasuries. EXC carries ~$35B+ "
        "of long-term debt — rising refinancing costs directly increase interest "
        "expense. ComEd's multi-year rate plan (MYRP) provides earnings certainty "
        "but MYRP renewal risk is a regulatory headwind every 4-5 years."
    ),
    inflation_pass_through=(
        "Moderate: fuel and power procurement costs pass through to customers via "
        "tariff adjustment mechanisms. Capital cost inflation is added to rate base "
        "and recovered over time, but with regulatory lag. ComEd's formula rate "
        "provides faster cost recovery than traditional rate cases."
    ),
    recession_behavior=(
        "Highly defensive — T&D utility revenue is essentially volume-insensitive "
        "for residential customers; commercial and industrial load could decline "
        "modestly. Exelon's urban service territories (Chicago, DC, Philadelphia, "
        "Baltimore) have structural demand stability. EPS has been positive through "
        "every economic cycle."
    ),
    major_risks=[
        "ComEd Illinois regulatory risk — multi-year rate plan (MYRP) renewal by "
        "Illinois Commerce Commission in 2025-26 is the single largest earnings risk; "
        "performance metrics (reliability, EV charging) determine allowed ROE",
        "ComEd federal investigation legacy — corruption investigation related to "
        "previous management; ongoing compliance requirements add cost",
        "Interest rate pressure on utility multiples — EXC's premium to book value "
        "is sensitive to changes in the utility multiple benchmark",
        "EV and AMI capital recovery — smart meters and EV infrastructure CapEx "
        "requires timely rate case recovery across six jurisdictions",
        "Regulatory lag across six jurisdictions — each state has different "
        "rate case timing and cost recovery mechanisms",
    ],
    valuation_style=(
        "Pure-play regulated utility valued on P/E (~15-18x) and EV/EBITDA (~11-13x). "
        "EXC trades at a premium to utility peers due to the pure T&D profile "
        "(no commodity/generation risk). Re-rating catalyst: ComEd MYRP renewal "
        "confirming allowed ROE and performance incentive structure; "
        "data center and EV load growth in Chicago and DC driving above-average CapEx."
    ),
    key_metrics=[
        "Rate base growth by utility (~7-8% CAGR)",
        "Adjusted EPS growth (target 5-7% CAGR)",
        "ComEd MYRP allowed ROE and performance achievement",
        "CapEx execution ($29B+ through 2028)",
        "Dividend payout ratio and coverage",
        "Credit ratings (target BBB+/A-)",
        "EV charging infrastructure expansion",
        "Data center load growth (Chicago, DC corridors)",
    ],
    competitive_advantages=[
        "Largest urban T&D footprint — serving Chicago, DC, Philadelphia, Baltimore, "
        "and coastal NJ provides unmatched concentration of high-density, high-value "
        "customers that generate strong revenue per circuit mile",
        "Pure T&D business model — no merchant generation risk; pure regulated "
        "earnings are valued at a premium multiple vs integrated utilities with "
        "commodity exposure",
        "ComEd multi-year rate plan (MYRP) — formula rate with annual true-up "
        "provides faster cost recovery and revenue certainty than traditional "
        "rate cases; reduces regulatory lag significantly vs peers",
    ],
    business_model_keywords=[
        "ComEd", "PECO", "BGE", "Pepco", "Atlantic City Electric", "Delmarva",
        "T&D", "transmission and distribution", "rate base", "capex",
        "MYRP", "multi-year rate plan", "formula rate", "Calvin Butler",
        "Illinois Commerce Commission", "AMI", "smart meters",
        "EV charging", "grid modernization", "data center load",
        "performance-based rate", "regulated utility",
    ],
))


# ── Southern Company (SO) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SO",
    company_name="Southern Company",
    business_model=(
        "Southern Company is a large regulated utility holding company providing "
        "electric and natural gas service across Georgia, Alabama, Mississippi, "
        "and Illinois.  Key subsidiaries: Georgia Power (electric, 2.7M customers), "
        "Alabama Power (electric, 1.5M), Mississippi Power, Southern Natural Gas, "
        "and Nicor Gas (Illinois natural gas distribution).  The completion of "
        "Vogtle Units 3 & 4 — the first new US nuclear reactors in 30+ years — "
        "adds 2,234 MW of carbon-free baseload generation to Georgia Power's fleet."
    ),
    primary_revenue_drivers=[
        "Georgia Power (~40% of earnings) — regulated electric utility serving "
        "metro Atlanta and statewide Georgia; rate base growing with renewable "
        "additions, transmission, and Vogtle nuclear capital recovery",
        "Alabama Power (~25%) — regulated electric utility in Alabama; "
        "coal retirement and renewable transition driving capital deployment",
        "Southern Natural Gas + Southern Company Gas (~20%) — interstate gas "
        "transmission + Nicor Gas distribution in Illinois (4M customers)",
        "Southern Power (~10%) — wholesale competitive generation (solar/wind IPP)",
        "Mississippi Power + other (~5%)",
    ],
    recurring_revenue_sources=[
        "Regulated electric distribution tariffs (Georgia PSC, Alabama PSC, MS PSC)",
        "FERC-regulated interstate natural gas transmission (Southern Natural Gas)",
        "Nicor Gas distribution tariffs (Illinois ICC)",
        "Southern Power wholesale power purchase agreements (multi-year PPAs)",
    ],
    rate_sensitivity_note=(
        "SO trades at ~16-19x forward EPS — a premium utility multiple reflecting "
        "the attractive Georgia/Alabama service territories. SO carries $55B+ of "
        "long-term debt, inflated by the $35B+ Vogtle construction financing. "
        "Higher rates increase interest expense directly and narrow the yield "
        "spread between SO's 3.5-4% dividend and 10-year Treasuries, compressing "
        "the utility valuation premium."
    ),
    inflation_pass_through=(
        "Structured: fuel costs pass through via adjustment clauses. Vogtle "
        "construction cost recovery is structured through Georgia Power rate cases "
        "and Georgia PSC certificates of public convenience and necessity (CPCN). "
        "Operating cost inflation on Vogtle (now in-service) is recovered through "
        "the next Georgia Power rate case."
    ),
    recession_behavior=(
        "Highly defensive — Georgia and Alabama regulated utility revenues are "
        "quasi-fixed. Metro Atlanta commercial and industrial load could soften "
        "in a deep recession. Nicor Gas distribution in Illinois serves "
        "residential heating load which is weather-driven and recession-resistant. "
        "Southern Company generated positive EPS through every recession historically."
    ),
    major_risks=[
        "Vogtle operational risk — Units 3 & 4 are now in service but operating "
        "a new AP1000 nuclear design introduces first-of-kind operating learning "
        "curve; unplanned outages would require replacement power at market prices",
        "Georgia PSC rate case risk — Vogtle capital recovery and return on "
        "equity are set by the Georgia Public Service Commission; disallowance "
        "of construction cost overruns is the primary downside scenario",
        "Alabama PSC coal retirement costs — Alabama Power has a large coal fleet; "
        "accelerated retirement creates stranded cost recovery risk",
        "Nicor Gas Illinois regulatory risk — Illinois Commerce Commission is "
        "one of the more challenging gas utility regulators",
        "Interest expense on Vogtle debt — ~$35B+ of construction debt must be "
        "serviced and gradually amortized through Georgia Power rates",
    ],
    valuation_style=(
        "Premium regulated utility P/E (~16-19x) and EV/EBITDA (~13-15x). "
        "SO commands a premium to utility peers for: 1) Georgia Power's "
        "high-growth metro Atlanta service territory; 2) Vogtle nuclear baseload "
        "providing long-lived carbon-free generation; 3) strong regulatory "
        "relationship with Georgia PSC historically. Re-rating catalyst: "
        "Vogtle operating smoothly for 2+ years and data center load growth "
        "in Georgia driving accelerated rate base investment."
    ),
    key_metrics=[
        "Georgia Power rate base growth and allowed ROE",
        "Vogtle Units 3 & 4 capacity factors (target ~90%)",
        "Adjusted EPS growth (target 5-7% CAGR)",
        "CapEx plan by subsidiary ($40B+ through 2028)",
        "Long-term debt and Vogtle cost recovery schedule",
        "Data center load growth in Georgia",
        "Dividend coverage and payout ratio",
        "Nicor Gas Illinois rate case outcomes",
    ],
    competitive_advantages=[
        "Georgia Power metro Atlanta monopoly — Atlanta is one of the fastest-growing "
        "US metros with a booming data center corridor (Google, Microsoft, Meta, AWS "
        "have significant Georgia data center capacity); load growth drives incremental "
        "rate base investment without regulatory risk",
        "Vogtle nuclear fleet — AP1000 nuclear units provide 2,234 MW of carbon-free "
        "baseload at near-zero marginal cost; in an carbon-constrained environment, "
        "nuclear baseload is a scarcity asset that no competitor can quickly replicate",
        "Southern Company Gas scale — Nicor Gas distribution serving 4M Illinois "
        "customers is one of the largest US gas distribution systems, providing "
        "scale in gas system upgrades and customer service efficiency",
    ],
    business_model_keywords=[
        "Vogtle", "Georgia Power", "Alabama Power", "Mississippi Power",
        "Nicor Gas", "Southern Natural Gas", "Daniel Tucker",
        "nuclear", "AP1000", "rate base", "regulated", "capex",
        "clean energy", "coal retirement", "carbon-free", "solar",
        "Georgia PSC", "CPCN", "allowed ROE", "rate case",
        "data center", "Atlanta", "load growth", "battery storage",
    ],
))


# ── AbbVie Inc. (ABBV) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="ABBV",
    company_name="AbbVie Inc.",
    business_model=(
        "AbbVie is a research-based specialty biopharmaceutical company generating revenue "
        "primarily through its immunology franchise (Skyrizi, Rinvoq, Humira), neuroscience "
        "portfolio (Vraylar, Ubrelvy, Atogepant), and the Allergan Aesthetics platform "
        "(Botox Cosmetic, Juvederm, Botox Therapeutic) acquired in 2020.  The post-Humira "
        "transition is well advanced: Skyrizi and Rinvoq together are on track for combined "
        "revenue exceeding $24B by 2027, more than replacing Humira's peak earnings contribution."
    ),
    primary_revenue_drivers=[
        "Skyrizi (risankizumab) — IL-23 inhibitor approved for plaque psoriasis, PsA, "
        "Crohn's disease, and ulcerative colitis; multi-indication launch drives >$12B target",
        "Rinvoq (upadacitinib) — selective JAK1 inhibitor approved in RA, PsA, AS, UC, "
        "atopic dermatitis, Crohn's; fastest-growing drug in AbbVie's portfolio",
        "Humira — eroding from biosimilar competition (US LOE 2023) but still >$8B; "
        "ex-US protected by local patent schedules through 2025–2027",
        "Allergan Aesthetics (~$6.5B) — Botox Cosmetic and Juvederm filler portfolio; "
        "Botox Therapeutic serves migraine, spasticity, and overactive bladder indications",
        "Neuroscience (~$4B+) — Vraylar (bipolar/MDD), Ubrelvy/Atogepant (migraine); "
        "CGRP antagonist class is a durable recurring prescription category",
    ],
    recurring_revenue_sources=[
        "Skyrizi and Rinvoq patient adherence programs — biologic specialty drugs with "
        "12-month initiation and maintenance therapy cycles; adherence rates above 85% "
        "once patients respond, creating predictable recurring prescription revenue",
        "Botox Therapeutic maintenance injection schedule — patients receive injections "
        "every 12 weeks for chronic migraine, spasticity, and overactive bladder; "
        "physician practice loyalty and reimbursement infrastructure create a sticky cycle",
        "Allergan Aesthetics loyalty platform — Botox Cosmetic and Juvederm multi-session "
        "treatment protocols through the Allē loyalty program (8M+ enrolled members) "
        "with repeat-visit economics similar to a subscription model",
        "Neuroscience CGRP preventive prescriptions — Ubrelvy and Atogepant are oral "
        "CGRP blockers taken daily or on-demand; preventive migraine therapy is a "
        "multi-year maintenance category with high refill persistence",
    ],
    rate_sensitivity_note=(
        "AbbVie's ~11-13x forward P/E is already low relative to large-cap pharma peers, "
        "reflecting the Humira biosimilar overhang.  DCF sensitivity to the 10-year rate "
        "is moderate — the pipeline's NPV is not a long-duration growth optionality story; "
        "Skyrizi and Rinvoq are already approved and revenue-generating.  The company "
        "carries ~$60B of debt (from the Allergan acquisition) at fixed rates averaging "
        "~3.5%, providing insulation from near-term refinancing pressure.  A rising-rate "
        "environment increases interest expense on any floating tranche (~$5B) modestly. "
        "The dividend (~4.5% yield) is supported by >$20B annual free cash flow, making "
        "the yield sustainable independent of rate level."
    ),
    inflation_pass_through=(
        "Strong: AbbVie's branded biologic and specialty drug portfolio commands list prices "
        "set through the US commercial and managed-care rebate framework.  The Inflation "
        "Reduction Act (IRA) drug pricing negotiation program applies to Medicare Part D "
        "high-expenditure drugs — Skyrizi and Rinvoq are subject to pricing negotiation "
        "in later program phases.  However, biologic manufacturing cost inflation is "
        "manageable relative to AbbVie's 80%+ gross margins.  International pricing "
        "(ex-US) is reference-priced and government-negotiated, with less inflation "
        "pass-through than the US commercial channel."
    ),
    recession_behavior=(
        "Highly resilient — specialty pharmaceuticals for autoimmune disease, aesthetics, "
        "and neurology are non-discretionary and essential for patients already on therapy. "
        "Prescription volumes for chronic-disease biologics (Skyrizi, Rinvoq, Humira) are "
        "stable through economic cycles: patients do not stop treatment due to recessions. "
        "The Botox Therapeutic segment (migraine, spasticity) is medically driven and "
        "defensive.  Allergan Aesthetics (cosmetic Botox, Juvederm) has mild cyclical "
        "exposure as an elective medical aesthetic — but repeat patients show high loyalty. "
        "AbbVie maintained its dividend and grew EPS through every economic downturn in its "
        "corporate history."
    ),
    major_risks=[
        "Humira revenue erosion from biosimilar competition — US biosimilars launched in "
        "2023 with over 10 entrants; AbbVie's protected international markets expire "
        "through 2025–2027, creating a multi-year revenue headwind requiring Skyrizi/Rinvoq "
        "ramp to fully offset the biosimilar impact",
        "IRA Medicare drug pricing negotiation for Skyrizi and Rinvoq — these drugs are "
        "candidates for negotiation in Phase 3+ of the IRA program (post-2026); the net "
        "price reduction (currently unknown) could reduce AbbVie's US immunology revenue "
        "and require pricing strategy adjustment in Medicare accounts",
        "Oncology pipeline execution: AbbVie has invested significantly in oncology "
        "(NavitoclaxPlus ADC platform, ABBV-CLS-484 PD-1 combinations) but the competitive "
        "oncology market requires multiple Phase III readouts to demonstrate differentiation "
        "— this pipeline is an upside optionality layer, not a near-term earnings driver",
        "Allergan Aesthetics sensitivity to consumer confidence: cosmetic Botox and "
        "Juvederm filler volumes declined 4-8% during the 2022-23 consumer spending "
        "deceleration; a consumer-led recession could reduce aesthetics revenue mid-single-digits",
        "Neuroscience CNS pipeline setbacks: AbbVie has multiple late-stage psychiatric "
        "and neurological programs (emraclidine for schizophrenia, others); a Phase III "
        "readout below efficacy thresholds would require pipeline capital reallocation "
        "but would not impair the core immunology or aesthetics business",
    ],
    valuation_style=(
        "AbbVie trades at 11-13x forward P/E and approximately 9-11x forward EBITDA, "
        "reflecting the Humira LOE overhang that depressed the multiple below large-cap "
        "pharma peers.  As the market recognizes Skyrizi and Rinvoq's combined trajectory "
        "toward $24B+ by 2027, the multiple should re-rate toward 14-16x — the typical "
        "large-cap pharma range for a company with durable earnings visibility.  "
        "The ~4.5% dividend yield adds to total return and is supported by >$20B annual "
        "free cash flow.  Sum-of-parts: immunology franchise (~$16-18B FCF at run-rate), "
        "aesthetics (~$2B FCF), and neuroscience (~$1.5B FCF) support the current "
        "enterprise multiple with potential upside from oncology pipeline milestones."
    ),
    key_metrics=[
        "Skyrizi net revenue by indication (psoriasis, IBD, PsA)",
        "Rinvoq net revenue and patient share in atopic dermatitis and RA",
        "Humira LOE erosion curve (US biosimilar market share)",
        "Allergan Aesthetics volume growth (Botox unit sales, Juvederm fill rates)",
        "Combined Skyrizi + Rinvoq trajectory toward $24B by 2027 AbbVie guidance",
        "Free cash flow (>$20B/yr target) and debt repayment schedule",
        "Adjusted EPS growth (targeting 5-8% CAGR post-LOE trough)",
        "IRA negotiation list inclusion timeline for Skyrizi/Rinvoq",
    ],
    competitive_advantages=[
        "Biologic immunology franchise depth: Skyrizi (IL-23) and Rinvoq (JAK1) cover "
        "overlapping indications in dermatology, rheumatology, and gastroenterology, "
        "giving AbbVie commercial leverage and label extension optionality across "
        "autoimmune therapeutic categories that pure-play competitors cannot match",
        "Botox brand durability: Allergan's Botox has >50% aesthetic injector market "
        "share built over 30 years; physician training relationships, the Allē loyalty "
        "program, and dosing expertise create a switching-cost moat against biosimilar "
        "Botox entrants (Daxxify, Jeuveau)",
        "Established specialty pharma commercial infrastructure: AbbVie's patient support "
        "programs (myAbbVie Assist), prior-authorization navigation, and specialty pharmacy "
        "relationships lower barriers for new drug launches into the same physician "
        "networks that already prescribe Humira, Skyrizi, and Rinvoq",
        "CGRP neurology leadership: Ubrelvy (gepant acute) and Atogepant (gepant preventive) "
        "have established neurologist prescribing patterns in a migraine market that is "
        "growing as awareness and diagnosis rates increase; neurologist loyalty to "
        "established CGRP agents reduces new entrant attack success",
        "Manufacturing and supply chain: AbbVie's large-molecule biologic manufacturing "
        "facilities (North Chicago, Puerto Rico) provide strategic resilience; the Humira "
        "biosimilar entry required >10 competitors years of investment to replicate — "
        "the manufacturing moat is structural, not just patent-based",
    ],
    business_model_keywords=[
        "Skyrizi", "Rinvoq", "Humira", "biosimilar", "AbbVie", "Allergan",
        "Botox", "Juvederm", "immunology", "IL-23", "JAK1", "aesthetics",
        "Vraylar", "Ubrelvy", "Atogepant", "CGRP", "neuroscience",
        "autoimmune", "IBD", "psoriasis", "atopic dermatitis", "IRA negotiation",
        "Allē", "patient adherence", "specialty pharmacy", "LOE",
    ],
    moat_type=["patent", "brand"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="moderate",
))


# ── Prologis, Inc. (PLD) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="PLD",
    company_name="Prologis, Inc.",
    business_model=(
        "Prologis is the world's largest industrial real estate investment trust, "
        "owning and operating approximately 1.2 billion square feet of logistics and "
        "distribution facilities across 19 countries.  The business model centers on "
        "leasing high-throughput warehouses and distribution centers to e-commerce "
        "operators, third-party logistics providers, and manufacturers at locations "
        "adjacent to major ports, airports, and dense urban consumption centers — "
        "locations that cannot be replicated.  Prologis generates development profit "
        "by building new facilities at yields above its cost of capital and earns "
        "recurring NOI growth from multi-year lease escalators averaging 3-4%/yr."
    ),
    primary_revenue_drivers=[
        "Same-store rental NOI growth (~55% of total revenue) — contractual rent "
        "escalators (3-4%/yr) on 5-7 year average lease terms drive predictable growth",
        "New lease commencements at market rent (~20% above in-place rents at many "
        "locations) as leases expire and reset to current market levels",
        "Development pipeline starts (~$5-7B/yr at 6-8% stabilized yields) — Prologis "
        "develops on its owned land bank and sells stabilized assets at a gain or holds "
        "for recurring NOI",
        "Third-party capital management (co-investment ventures with sovereign wealth "
        "funds, pension funds) generates management fees and promote income",
        "PLD Essentials platform — energy, sustainable solutions, and supply chain "
        "services sold to Prologis tenants beyond the physical lease",
    ],
    recurring_revenue_sources=[
        "Multi-year lease agreements (average 5-7 year initial terms) with contractual "
        "rent escalators of 3-4%/yr embedded into base rent — Prologis's lease structure "
        "is the industrial REIT equivalent of a multi-year contract with predictable "
        "annual step-ups",
        "PLD Essentials subscription platform — on-site solar generation, EV charging, "
        "LED retrofits, and energy management services sold as recurring subscription "
        "packages to tenants in Prologis buildings; ~$1B+ addressable revenue by 2027",
        "Fund management and co-investment fees from third-party capital ventures "
        "(PELF, PELP, Prologis Japan Fund) — asset management fees of 0.5-1.0% on "
        "$80B+ of third-party AUM generate high-margin, recurring advisory income",
        "Development fee income — Prologis earns construction management and development "
        "fees from its co-investment fund vehicles during the development phase of "
        "new speculative and build-to-suit projects",
    ],
    rate_sensitivity_note=(
        "Prologis trades at ~20-24x forward AFFO, reflecting the scarcity premium of "
        "its irreplaceable port-adjacent land bank.  Industrial REIT AFFO multiples "
        "are moderately rate-sensitive (longer-duration cash flows), but Prologis's "
        "3-4% annual rent escalators provide a natural inflation/rate hedge that "
        "mitigates pure DCF compression.  The ~$35B of long-term debt (largely fixed "
        "at sub-3% from the low-rate issuance window) insulates near-term interest "
        "expense from rising rates.  A sustained rate-elevated environment compresses "
        "the AFFO multiple but also reduces competitive development activity, which "
        "tightens market rents and supports Prologis's NOI growth trajectory."
    ),
    inflation_pass_through=(
        "Excellent: Prologis's lease escalators (3-4%/yr) are contractually embedded and "
        "provide direct inflation pass-through on the existing portfolio.  New leases are "
        "signed at current market rents — in high-demand coastal markets (Southern "
        "California, New Jersey, Seattle), market rents have increased 40-60% above "
        "in-place rents, creating substantial embedded NOI upside.  Construction cost "
        "inflation increases new development cost but simultaneously creates barriers "
        "to competitive supply, supporting market rent levels in Prologis's core markets."
    ),
    recession_behavior=(
        "Highly resilient — logistics and e-commerce infrastructure is non-discretionary "
        "for Prologis's tenant base.  Amazon, FedEx, UPS, DHL, and large 3PLs require "
        "distribution capacity regardless of economic cycles.  During the 2020 COVID "
        "shock, Prologis's occupancy never fell below 95% and rent collections stayed "
        "above 97%.  E-commerce growth is a secular demand driver — every $1B increase "
        "in e-commerce sales requires approximately 1.25M sqft of logistics space.  "
        "The near-term risk is overbuilding: speculative supply additions in 2022-23 "
        "reduced absorption in some Sun Belt markets, temporarily softening market rents "
        "below prior peaks.  However, coastal and port-adjacent markets (LA, NJ) remain "
        "structurally constrained with near-zero available land."
    ),
    major_risks=[
        "Supply over-delivery in Sun Belt and secondary markets — Prologis and peers "
        "significantly expanded speculative development in 2021-22, creating temporary "
        "absorption shortfalls in Phoenix, Dallas, and Chicago where land constraints "
        "are less severe than coastal markets",
        "Interest rate sensitivity on AFFO yield — as Treasury rates rise, the AFFO "
        "yield spread to risk-free narrows, compressing Prologis's premium AFFO multiple "
        "and making acquisitions and development less accretive on an IRR basis",
        "E-commerce demand normalization — the COVID-driven e-commerce pull-forward "
        "caused Amazon and 3PL tenants to contract excess space in 2022-23; if secular "
        "e-commerce penetration growth plateaus, new supply absorption slows",
        "Near-shoring and manufacturing reshoring complexity — while near-shoring "
        "is a long-term driver of domestic distribution demand, the transition adds "
        "uncertainty to net new lease demand timing and mix",
        "Currency risk from international operations (~25% of NOI from Japan, Europe, "
        "Latin America) — a strengthening US dollar reduces international NOI contribution "
        "on an as-reported basis",
    ],
    valuation_style=(
        "Prologis is priced at 20-24x forward AFFO, a premium to net lease and retail "
        "REITs, reflecting the irreplaceability of its port-adjacent portfolio and "
        "the embedded rent growth from in-place-to-market rent spreads.  The development "
        "pipeline adds NAV-accretive returns above the cost of capital — the spread "
        "between stabilized yield (~6-7%) and cap rate (~4-5%) generates meaningful "
        "equity creation per development cycle.  Same-store NOI growth of 4-6%/yr, "
        "combined with a 3% AFFO yield, supports double-digit total return expectations "
        "at current pricing.  The near-term re-rating catalyst is absorption of the "
        "2022-23 supply overhang and confirmation of rent growth acceleration in 2025-26."
    ),
    key_metrics=[
        "Same-store NOI growth (target 4-6%/yr)",
        "In-place to market rent spread (embedded lease mark-to-market upside)",
        "Development starts (volume, stabilized yield vs cost of capital spread)",
        "Occupancy rate (target 95-97%)",
        "Net lease commencements vs expirations (absorption of Sun Belt supply)",
        "PLD Essentials platform revenue ramp",
        "Leverage (Debt/EBITDA target ~5x)",
        "Third-party capital AUM and fee income",
    ],
    competitive_advantages=[
        "Port-adjacent land bank irreplaceability: Prologis owns infill industrial land "
        "within 30 minutes of the Ports of Los Angeles/Long Beach, Port of NY/NJ, and "
        "major Southeast Asia-facing ports — this land cannot be replicated as entitlement "
        "timelines for new industrial sites in these markets exceed 10-15 years",
        "Largest global logistics network: Prologis's 19-country platform allows "
        "multinational tenants (Amazon, DHL, Ceva Logistics) to standardize facility "
        "formats and lease terms globally under a single relationship — a convenience "
        "no regional REIT competitor can offer",
        "PLD Essentials recurring services platform: the addition of energy, sustainability, "
        "and supply chain analytics services as recurring revenue streams diversifies "
        "Prologis's earnings beyond physical rent and provides switching costs for tenants "
        "already integrated into the Prologis energy management infrastructure",
        "Development entitlement pipeline: Prologis has a land bank and pre-entitled "
        "sites for 200M+ sqft of future development — delivering 3-5 years of competitive "
        "advantage before competing developers can enter the same submarkets",
        "Tenant concentration in logistics essential players: Amazon (~7% of revenue), "
        "FedEx, UPS, DHL, and XPO Logistics are investment-grade tenants with operational "
        "necessity to occupy industrial real estate near consumers — providing stable "
        "occupancy even in periods of broader REIT demand softness",
    ],
    business_model_keywords=[
        "Prologis", "industrial REIT", "logistics", "e-commerce", "port-adjacent",
        "same-store NOI", "rent escalator", "AFFO", "development pipeline",
        "PLD Essentials", "infill", "3PL", "Amazon", "FedEx", "Sun Belt",
        "absorption", "mark-to-market rent", "NOI growth", "entitlement",
        "co-investment", "build-to-suit", "cap rate", "land bank",
    ],
))


# ── Equinix, Inc. (EQIX) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="EQIX",
    company_name="Equinix, Inc.",
    business_model=(
        "Equinix is the world's largest carrier-neutral data center operator, running "
        "260+ International Business Exchange (IBX) data centers across 70+ metro areas "
        "in 33 countries.  The core thesis is the interconnection platform: Equinix "
        "collocates enterprise, cloud, and network customers in the same physical "
        "facilities, enabling direct private cross-connects between parties at low "
        "latency and high bandwidth.  Each new customer added to an IBX campus increases "
        "the interconnection density — a network flywheel that competitor data centers "
        "cannot replicate without Equinix's existing ecosystem.  Revenue is structured "
        "as monthly recurring fees for colocation (power + space) and interconnection "
        "(cross-connect + virtual fabric charges)."
    ),
    primary_revenue_drivers=[
        "Colocation (~75% of revenue) — recurring monthly fees for space (cabinets/cages) "
        "and power (kW) in Equinix IBX data centers; average contract term 3-5 years",
        "Interconnection (~15% of revenue, >25% gross margin) — cross-connect fees for "
        "physical fiber connections and Equinix Fabric virtual connections between "
        "co-located customers; 460,000+ interconnections with near-zero marginal cost",
        "Managed infrastructure services (~10%) — Smart Hands (on-site technical support), "
        "remote hands, equipment installation, and power management services",
        "xScale hyperscaler JV pre-leased capacity — Equinix develops hyperscale campuses "
        "for Microsoft Azure, Google Cloud, and AWS through JV structures, contributing "
        "development profit and management fee income",
    ],
    recurring_revenue_sources=[
        "Multi-year colocation contracts (average 3-5 year terms) with annual escalators "
        "of 2-3% — Equinix's base colocation MRR is locked in through long-term leases; "
        "churn rates below 3% annually on the installed base",
        "Interconnection subscription fees — physical cross-connects and Equinix Fabric "
        "virtual connections are billed monthly as recurring subscription-like services; "
        "460,000+ connections in place generate predictable MRR with near-100% margin "
        "on incremental connection additions",
        "Managed infrastructure service contracts — Smart Hands and remote managed "
        "services billed under rolling service contract agreements renewed annually "
        "or upon facility renewal; the operational dependency creates high renewal rates",
        "xScale joint venture management fees — ongoing asset management and "
        "development oversight fees from JV vehicles (Equinix-GIC JV, others) "
        "contribute high-margin recurring advisory income tied to deployed AUM",
    ],
    rate_sensitivity_note=(
        "EQIX trades at ~25-30x forward AFFO, pricing in the recurring-revenue quality "
        "and AI-driven demand tailwind.  As a long-duration REIT, the AFFO multiple is "
        "moderately rate-sensitive — a 100 bps rise in the 10-year compresses the fair "
        "AFFO multiple by approximately 2-3 turns on standard DCF mechanics.  However, "
        "Equinix's MRR growth of 8-10%/yr and interconnection pricing power partially "
        "offset multiple compression.  The balance sheet carries ~$18B of long-term debt, "
        "largely issued at fixed rates during low-rate windows.  Refinancing risk is "
        "manageable as debt matures in a laddered schedule through 2035+."
    ),
    inflation_pass_through=(
        "Moderate-to-strong: Equinix's multi-year colocation contracts include 2-3% "
        "annual escalators that provide partial pass-through of operating cost inflation. "
        "Power costs are a significant operating expense (~25% of revenue) — rising "
        "electricity prices in Europe and Singapore have created short-term margin "
        "compression.  However, Equinix has implemented power cost surcharges on "
        "new and renewing contracts in high-cost markets.  The interconnection segment "
        "is nearly 100% gross margin with no direct inflation exposure."
    ),
    recession_behavior=(
        "Mission-critical and highly resilient — enterprise digital infrastructure "
        "spending continued to grow through the 2008-09 and 2020 recessions as "
        "organizations accelerated cloud migration.  Equinix colocation is non-discretionary "
        "for financial services, network carriers, and cloud platforms that operate "
        "24/7 — a bank cannot move its trading infrastructure out of Equinix New York "
        "LD4 or NY5 during a recession.  Interconnection revenue is especially sticky: "
        "the cost of moving physical cross-connects to a competing facility (rewiring, "
        "testing, disruption) far exceeds the incremental cost savings.  Secular AI "
        "and cloud migration trends are recession-resistant multi-year demand drivers."
    ),
    major_risks=[
        "Hyperscaler competition: Amazon (AWS), Microsoft Azure, and Google are building "
        "their own large-scale data center campuses in major metros, potentially reducing "
        "their incremental colocation demand from Equinix as they internalize more workloads",
        "Power constraints in key markets: Northern Virginia (the world's largest data "
        "center market) and Singapore face utility grid constraints that limit new "
        "data center development — Equinix's expansion pipeline may be gated by power "
        "availability even where demand is robust",
        "Europe geopolitical and regulatory risk: GDPR data residency requirements, "
        "EU energy regulations, and the European Cloud Infrastructure Regulation create "
        "compliance complexity for Equinix's pan-European platform",
        "Premium AFFO multiple compression risk: at 25-30x AFFO, Equinix is priced for "
        "sustained 8-10%/yr MRR growth; a deceleration to 5-6% from supply additions "
        "or demand normalization would compress the multiple significantly",
        "Customer concentration in financial services and cloud: Equinix's top 20 customers "
        "represent a significant portion of interconnection revenue — a consolidation in "
        "the financial services sector (megabank merger) could reduce interconnection "
        "density in key IBX campuses",
    ],
    valuation_style=(
        "Equinix is priced at 25-30x forward AFFO, reflecting the recurring-revenue "
        "quality of its colocation and interconnection model and the AI infrastructure "
        "demand tailwind.  MRR growth of 8-10%/yr drives the premium AFFO multiple vs "
        "net lease or retail REITs.  The interconnection flywheel — each new customer "
        "increases the density of peering options for all others — is the structural "
        "justification for the AFFO premium.  Hyperscaler xScale pre-commitment provides "
        "forward revenue visibility on new campus development.  At current pricing, the "
        "AFFO yield (~3-4%) is low, reflecting the market's expectation of sustained "
        "double-digit MRR growth from AI infrastructure spending acceleration."
    ),
    key_metrics=[
        "Monthly Recurring Revenue (MRR) growth and churn rate",
        "Interconnection revenue growth and cross-connect additions",
        "AFFO per share growth (target 8-10%/yr)",
        "Utilization rate by region (Americas, EMEA, Asia-Pacific)",
        "xScale hyperscaler pre-commitment and JV deployment pace",
        "Power capacity additions vs demand pipeline",
        "Cabinet billing density (kW/cabinet)",
        "EBITDA margin trend and power cost pass-through execution",
    ],
    competitive_advantages=[
        "Carrier-neutral interconnection ecosystem: 1,800+ network service providers "
        "connect inside Equinix campuses — this density creates a locked-in ecosystem "
        "where every enterprise, cloud, and network customer is reachable without "
        "traversing the public internet; this network of networks cannot be replicated "
        "by a new entrant starting from zero",
        "Network density flywheel: each new customer co-located in an IBX campus "
        "increases the interconnection options for all existing customers, making "
        "Equinix's facilities progressively more valuable as the ecosystem grows; "
        "competitor data centers with lower density cannot offer equivalent "
        "interconnection reach at comparable latency",
        "Global platform breadth: 260+ data centers across 70+ metros on 5 continents "
        "enable multinational enterprises to standardize on Equinix for cross-border "
        "interconnection — a capability no regional data center operator can replicate",
        "AI infrastructure positioning: GPU cluster colocation and distributed training "
        "infrastructure demand is driving a new wave of enterprise and hyperscaler "
        "colocation demand that favors Equinix's power-dense IBX campus architecture "
        "and its proximity to network on-ramps for AI model serving",
        "Real estate scarcity in tech metro markets: Equinix owns or controls data "
        "center campuses in Northern Virginia, Chicago, Singapore, Amsterdam, and "
        "Frankfurt — markets with severe power and land constraints that prevent "
        "competitive new supply from matching Equinix's established ecosystem footprint",
    ],
    business_model_keywords=[
        "EQIX", "Equinix", "IBX", "International Business Exchange", "colocation",
        "interconnection", "MRR", "cross-connect", "Equinix Fabric", "carrier-neutral",
        "xScale", "Smart Hands", "AFFO", "data center", "peering", "AI infrastructure",
        "Northern Virginia", "Singapore", "Amsterdam", "cloud on-ramp",
        "network density", "hyperscaler", "power density", "monthly recurring",
    ],
))


# ── Occidental Petroleum Corporation (OXY) ───────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="OXY",
    company_name="Occidental Petroleum Corporation",
    business_model=(
        "Occidental Petroleum is a large integrated oil and gas company with three "
        "operating segments: Oil and Gas (the Permian Basin E&P core), OxyChem "
        "(chlorovinyls and performance chemicals — one of North America's largest "
        "chlorine and caustic soda producers), and Midstream & Marketing.  The 2024 "
        "CrownRock acquisition ($12B) added 94,000 net acres in the Midland Basin, "
        "making OXY one of the top three Permian producers by volume.  Berkshire "
        "Hathaway holds a ~28% common equity stake plus $10B of preferred stock, "
        "providing a strategic balance sheet anchor.  OXY's emerging Carbon Capture, "
        "Utilization, and Storage (CCUS) platform — including the Stratos Direct Air "
        "Capture plant (1 MtCO₂/yr capacity) — represents a long-term emissions-reduction "
        "business line that does not yet contribute to free cash flow."
    ),
    primary_revenue_drivers=[
        "Permian Basin Oil and Gas production (~65% of earnings) — Midland and Delaware "
        "Basin oil at ~1.3 MMboe/d post-CrownRock; realized oil price is the primary "
        "earnings lever; breakeven ~$40/bbl WTI on a cash basis",
        "OxyChem (~20% of earnings) — chlorovinyls (PVC, VCM, EDC) and performance "
        "chemicals for industrial markets; earnings diversify OXY's pure-play E&P risk",
        "International operations (~10%) — Middle East/North Africa production sharing "
        "agreements (UAE, Oman, Algeria) provide production and cash flow outside the US",
        "Midstream & Marketing (~5%) — Western Midstream Partners (WES) equity stake "
        "provides gathering, processing, and transportation fee income",
    ],
    recurring_revenue_sources=[
        "Permian Basin oil and gas production revenue — continuous daily production from "
        "the Midland Basin Wolfcamp and Spraberry formations; volumes are predictable "
        "from existing well inventory, providing revenue continuity across commodity cycles",
        "Western Midstream Partners (WES) midstream fee income — OXY's equity stake in "
        "WES generates quarterly distribution income from fee-based gathering and "
        "processing of third-party and OXY production in the DJ and Delaware Basins",
    ],
    rate_sensitivity_note=(
        "OXY carries approximately $18-20B of long-term debt post-CrownRock, with a "
        "target leverage ratio of 1.0x Net Debt/EBITDA at $70/bbl WTI.  Rising rates "
        "increase refinancing costs on maturing debt tranches, slowing deleveraging "
        "progress.  The stock trades at 4-6x EV/EBITDA through-cycle, a commodity-sector "
        "multiple that is less sensitive to discount rate changes than growth stocks.  "
        "However, as a capital-intensive producer, OXY's development drilling program "
        "is funded by internal cash flow; rising rates increase the hurdle rate for "
        "incremental Permian development decisions."
    ),
    inflation_pass_through=(
        "Partial: OXY's E&P revenue moves directly with oil and gas commodity prices, "
        "which have historically risen with broad inflation cycles.  However, oilfield "
        "services costs (drilling, completion, sand, water disposal) also inflate in "
        "commodity upcycles, partially offsetting E&P margin expansion.  OxyChem "
        "has moderate pricing power — chlorine-caustic soda pricing is market-driven "
        "with a 6-12 month lag relative to energy feedstock costs.  The CCUS "
        "business has contractual carbon removal pricing (45Q tax credit floor)."
    ),
    recession_behavior=(
        "Cyclical and commodity-dependent — OXY's earnings are closely tied to WTI oil "
        "prices.  Permian Basin production volumes are stable (OXY does not shut in "
        "wells in mild downturns), but realizations fluctuate with oil prices — a $10/bbl "
        "WTI decline reduces annual EBITDA by approximately $600-700M.  OxyChem provides a "
        "partially defensive earnings contribution — chemicals demand is less correlated "
        "to oil prices than E&P revenue, offering resilience in energy downturns while "
        "industrial chemicals demand softens in broader recessions.  OXY suspended its "
        "common dividend in 2020 during COVID — demonstrating the cyclical exposure to "
        "oil price dislocations.  The Berkshire preferred dividend ($800M/yr) is a fixed "
        "senior cash obligation that reduces financial flexibility in downturns."
    ),
    major_risks=[
        "Commodity price risk — OXY's earnings are leveraged to WTI oil prices; a "
        "sustained decline to $55-60/bbl WTI would constrain free cash flow below "
        "the Berkshire preferred dividend obligation and slow the CrownRock deleveraging "
        "timeline significantly",
        "CrownRock leverage burden — the $12B acquisition added substantial debt to the "
        "balance sheet; Net Debt/EBITDA above 2.0x at cycle-trough oil prices creates "
        "refinancing pressure and could require equity issuance or asset sales if oil "
        "markets deteriorate before the deleveraging plan is complete",
        "CCUS technology and commercialization uncertainty — Stratos Direct Air Capture "
        "is the first commercial-scale DAC facility; capital cost per tonne of CO₂ "
        "removed remains significantly above the 45Q credit level, requiring further "
        "scale and cost reduction before CCUS contributes positive FCF",
        "Permian Basin water management costs — high-volume unconventional production "
        "generates large quantities of produced water requiring disposal and recycling; "
        "increasing regulatory scrutiny on wastewater injection wells adds operational "
        "cost and potential production curtailment risk",
        "Berkshire preferred cost and governance — the $10B preferred stock carries an "
        "$800M/yr dividend obligation that is senior to common equity; while Berkshire's "
        "28% ownership provides strategic support, the preferred term restricts OXY's "
        "capital allocation flexibility relative to peers with cleaner capital structures",
    ],
    valuation_style=(
        "OXY is priced on an EV/EBITDA multiple (4-6x through-cycle) and free cash flow "
        "yield (~7-10% at $75/bbl WTI), consistent with large-cap US E&P peers.  The "
        "Berkshire Hathaway 28% equity stake and $10B preferred holding provide a "
        "structural balance sheet backstop — Berkshire's continued accumulation at "
        "various price levels signals long-term confidence in OXY's Permian Basin "
        "position and earnings durability.  The CrownRock acquisition premium to "
        "current market pricing reflects the strategic scarcity of Midland Basin "
        "tier-1 acreage.  The CCUS program is not in current EV/EBITDA models — "
        "it represents an incremental long-term business if DAC costs decline to "
        "the $100-150/tonne range.  Free cash flow allocation priority: debt repayment "
        "first, dividend restoration second, buybacks and CCUS capital third."
    ),
    key_metrics=[
        "WTI oil price (primary earnings driver)",
        "Permian Basin net production (MMboe/d, targeting 1.4+ post-CrownRock integration)",
        "Free cash flow at various WTI price decks ($65, $70, $75, $80/bbl scenarios)",
        "Net Debt/EBITDA ratio (target 1.0x at $70/bbl; current post-CrownRock ~2.0x+)",
        "OxyChem earnings contribution (PVC and caustic soda pricing)",
        "Berkshire preferred retirement timeline and common dividend reinstatement",
        "WES distribution coverage ratio",
        "Stratos DAC plant availability and cost per tonne of CO₂ removed",
    ],
    competitive_advantages=[
        "Permian Basin tier-1 acreage position: the CrownRock acquisition secured 94,000 "
        "net acres in the core Midland Basin with breakeven costs below $40/bbl WTI — "
        "among the lowest in the US unconventional industry; this acreage position "
        "cannot be acquired at current market prices given the scarcity of remaining "
        "tier-1 blocks in the core Midland formation",
        "OxyChem integrated chemicals: as one of North America's largest chlorine and "
        "caustic soda producers, OxyChem provides earnings diversification against "
        "pure-play E&P volatility and generates FCF through oil price downturns when "
        "industrial chemical markets are less correlated to energy prices",
        "CCUS technology leadership: OXY's 1PointFive subsidiary and the Stratos "
        "Direct Air Capture plant give it first-mover operational experience in DAC "
        "technology — a potential long-term strategic advantage if carbon removal "
        "markets develop and DAC costs decline toward commercial viability",
    ],
    business_model_keywords=[
        "OXY", "Occidental", "Permian Basin", "Midland Basin", "CrownRock",
        "OxyChem", "WTI", "breakeven", "EV/EBITDA", "FCF yield",
        "Berkshire Hathaway", "preferred stock", "CCUS", "Direct Air Capture",
        "Stratos", "Western Midstream", "WES", "deleveraging", "chlorovinyls",
        "PVC", "caustic soda", "45Q", "production volumes",
    ],
))


# ── American Tower Corporation (AMT) ─────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AMT",
    company_name="American Tower Corporation",
    business_model=(
        "American Tower is the largest independent owner-operator of wireless "
        "communications tower infrastructure in the world, with approximately 40,000 "
        "macro cell towers in the United States and more than 100,000 international "
        "tower sites across Africa, Asia, Latin America, and Europe.  Revenue is "
        "generated through long-term non-cancellable tower lease agreements with wireless "
        "carriers (AT&T, T-Mobile, Verizon in the US; Airtel, Jio, Claro, others "
        "internationally), earning monthly rent for each tenant antenna on the tower. "
        "Each tower can host multiple tenants — adding a second or third tenant at near-"
        "zero marginal cost creates extremely high incremental EBITDA margins (~90%+)."
    ),
    primary_revenue_drivers=[
        "US tower leasing (~40% of revenue) — long-term leases with AT&T, T-Mobile, "
        "and Verizon averaging 10-15 years with annual escalators of 3%",
        "International tower leasing (~55% of revenue) — tower portfolios in India, "
        "Africa, Latin America, and Europe with local carrier leases tied to "
        "inflation-linked or fixed escalators",
        "Data centers (CoreSite) (~5% of revenue) — 25 data centers in 8 US markets "
        "following partial disposition of the CoreSite portfolio",
    ],
    recurring_revenue_sources=[
        "US non-cancellable tower lease revenue — AT&T, T-Mobile, and Verizon pay "
        "fixed monthly rents under master lease agreements that are contractually "
        "non-cancellable with 10-15 year initial terms and built-in annual escalators; "
        "the three major carriers represent ~65-70% of US tower revenue",
        "International tower lease income — inflation-linked escalators on African "
        "and Latin American leases provide recurring revenue with partial currency "
        "and inflation hedge; Asia (India) tower leases are tied to multi-year "
        "spectrum deployment commitments by Airtel and Jio",
    ],
    rate_sensitivity_note=(
        "AMT is one of the most rate-sensitive REITs in the index.  The tower REIT "
        "model discounts long-dated, relatively stable AFFO streams over 30-50 year "
        "tower asset lives — making the AFFO multiple highly sensitive to the 10-year "
        "Treasury level.  Each 100 bps increase in the 10-year rate compresses AMT's "
        "fair AFFO multiple by approximately 2-3 turns.  The CoreSite acquisition "
        "($10B in 2022) added significantly to AMT's leverage at the peak of the "
        "low-rate cycle, inflating Net Debt/EBITDA to 7-8x and creating a dual "
        "headwind of rate-driven AFFO multiple compression and higher refinancing costs. "
        "The current pricing reflects this leverage-rate double impact — an AFFO yield "
        "of 4-5% offering thin spread over 10-year Treasuries at elevated rate levels."
    ),
    inflation_pass_through=(
        "Good for US towers: the 3% annual escalator on US leases is contractually "
        "embedded and provides inflation pass-through above current targets.  "
        "International escalators are inflation-linked in many markets (Africa, "
        "Latin America), providing stronger real-rate protection.  However, "
        "ground rent costs (AMT leases the land under ~80% of US towers) also "
        "escalate with inflation, partially offsetting lease revenue inflation gains."
    ),
    recession_behavior=(
        "Tower lease revenue is highly resilient and stable — wireless carriers are contractually "
        "obligated to pay rent regardless of economic conditions; 5G densification "
        "capex commitments by AT&T and T-Mobile are multi-year government spectrum "
        "license requirements, not discretionary spending.  Occupancy rates on US "
        "towers stayed above 97% through 2008-09 and COVID.  However, AMT's high "
        "leverage (~7-8x Net Debt/EBITDA from the CoreSite acquisition cycle) "
        "introduces financial risk in prolonged rate-elevated or credit-tightening "
        "environments — the debt service burden limits dividend growth and share "
        "buyback capacity relative to a lower-leveraged tower operator."
    ),
    major_risks=[
        "Carrier consolidation risk — T-Mobile's Sprint acquisition led to incremental "
        "tower lease churn as Sprint/T-Mobile rationalized overlapping sites; further "
        "carrier M&A (DISH dissolution, US Cellular acquisitions) could trigger "
        "another round of lease terminations and renegotiations",
        "CoreSite legacy leverage — the $10B CoreSite data center acquisition added "
        "debt at near-peak valuations in 2022; with data center dispositions, the "
        "debt burden relative to tower AFFO is still elevated at 7-8x Net Debt/EBITDA, "
        "constraining AMT's financial flexibility vs peers Crown Castle and SBA",
        "Foreign exchange headwinds — approximately 50% of AMT revenue is generated "
        "internationally; depreciation of African (Nigerian naira, South African rand), "
        "Latin American (Brazilian real, Chilean peso), and emerging market currencies "
        "reduces reported USD revenue significantly in strong-dollar environments",
        "5G small cell and CBRS spectrum deployment — hyperscaler-driven small cell "
        "deployment and private network buildout favors street furniture and neutral "
        "host models over AMT's macro cell tower economics; Crown Castle's US fiber "
        "small cell portfolio is better positioned for dense urban 5G densification",
        "International regulatory risk — tower operations in Nigeria, South Africa, "
        "India, and Brazil are subject to local spectrum allocation, tower sharing "
        "mandates, and currency repatriation restrictions that can impair the "
        "economics of AMT's international tower portfolios",
    ],
    valuation_style=(
        "American Tower is priced on a P/AFFO multiple (~20-22x) and forward AFFO "
        "yield (~4-5%).  The tower REIT historically commanded a 25-30x P/AFFO "
        "premium reflecting the non-cancellable lease structure and multi-year 5G "
        "densification demand runway.  The CoreSite leverage cycle compressed the "
        "multiple from 28-30x to ~20x — the current P/AFFO reflects the elevated "
        "debt profile rather than any structural deterioration in tower fundamentals. "
        "At current pricing, the AFFO yield offers limited spread over 10-year "
        "Treasuries, making AMT a rate-duration trade as much as a tower infrastructure "
        "business.  The deleveraging pathway (CoreSite dispositions, organic AFFO "
        "growth, debt repayment) is the key re-rating catalyst."
    ),
    key_metrics=[
        "AFFO per share growth (organic, ex-FX)",
        "Net Debt/EBITDA ratio (target <6x; current ~7-8x post-CoreSite)",
        "US tower leasing revenue growth and churn rate",
        "International tower revenue (ex-FX growth vs currency headwinds)",
        "CoreSite AFFO contribution and disposition progress",
        "AFFO yield vs 10-year Treasury spread",
        "New tenant additions (colocations) per quarter",
        "Ground rent escalation vs lease revenue escalation",
    ],
    competitive_advantages=[
        "US macro tower portfolio scale: 40,000+ sites with 95%+ multi-tenant "
        "occupancy in a market where new tower permitting requires 18-24 months and "
        "local zoning restrictions severely limit new tower construction; Prologis's "
        "US market position is effectively a regulated infrastructure monopoly in "
        "many local markets",
        "Non-cancellable master lease agreements: AT&T, T-Mobile, and Verizon are "
        "locked into 10-15 year non-cancellable leases with built-in 3% escalators "
        "— a contractual revenue floor that no competitive new tower entrant can "
        "displace without the carrier physically relocating antenna equipment",
        "International emerging market tower presence: 100,000+ international towers "
        "in high-density urban markets where smartphone penetration and data consumption "
        "are growing rapidly provide exposure to secular wireless data demand growth "
        "that is structurally independent of US market maturity",
    ],
    business_model_keywords=[
        "American Tower", "AMT", "tower lease", "carrier", "AFFO", "P/AFFO",
        "AT&T", "T-Mobile", "Verizon", "colocation", "CoreSite", "5G",
        "densification", "master lease", "escalator", "Net Debt/EBITDA",
        "international towers", "Africa", "India", "Latin America",
        "Crown Castle", "small cell", "non-cancellable", "ground rent",
    ],
))


# ── Realty Income Corporation (O) ─────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="O",
    company_name="Realty Income Corporation",
    business_model=(
        "Realty Income is the largest publicly traded net lease REIT, owning more than "
        "15,000 single-tenant commercial properties net leased to approximately 1,500 "
        "tenants across retail, convenience, industrial, and gaming categories.  Under "
        "the triple-net lease structure, tenants pay base rent plus all property taxes, "
        "maintenance, and insurance — creating a highly predictable, low-volatility AFFO "
        "stream.  Realty Income markets itself as 'The Monthly Dividend Company,' "
        "having paid 607+ consecutive monthly dividends with 30+ consecutive annual "
        "dividend increases (S&P 500 Dividend Aristocrat).  Scale is the primary "
        "competitive advantage — Realty Income can access lower borrowing costs and "
        "better tenant relationships than smaller net lease peers."
    ),
    primary_revenue_drivers=[
        "US net lease retail rent (~65% of revenue) — convenience, drug store, home "
        "improvement, quick service restaurant, grocery, and discount retail tenants; "
        "Dollar General, Walgreens, 7-Eleven, and FedEx are the largest tenants",
        "US industrial and gaming net lease rent (~15%) — industrial tenants (FedEx "
        "distribution, Amazon fulfillment) and gaming properties (Bellagio, MGM Grand "
        "Las Vegas) diversify beyond traditional retail formats",
        "International (UK and Europe) net lease (~20%) — post-Spirit Realty merger "
        "and Encore UK expansion; European tenants provide geographic diversification "
        "and euro-denominated AFFO",
    ],
    recurring_revenue_sources=[
        "Triple-net lease rent from single-tenant retail and industrial properties — "
        "long-term leases (average initial term 10-15 years) with contractual escalators "
        "of 1-2%/yr; lease expirations are staggered, and Realty Income's 99% historical "
        "occupancy provides revenue continuity through the lease cycle",
        "Monthly AFFO distributions supported by 99% occupancy and diversified tenant "
        "base — Realty Income's AFFO per share has grown in every year since its 1994 "
        "NYSE listing, supported by the structural predictability of triple-net lease cash "
        "flows regardless of property operating costs or tax fluctuations",
    ],
    rate_sensitivity_note=(
        "Realty Income is structurally rate-sensitive — the stock is held as a bond "
        "proxy by yield-seeking institutional investors, and its AFFO yield of 5-6% "
        "is compared directly to 10-year Treasury rates.  As the 10-year rate rises "
        "toward 4.5-5%, the AFFO yield spread compresses and Realty Income's premium "
        "P/AFFO multiple contracts, reducing the stock price even if underlying AFFO "
        "grows.  Realty Income issues long-term unsecured bonds to fund acquisitions — "
        "in rising-rate environments, the acquisition spread (cap rate minus borrowing "
        "cost) narrows, slowing AFFO-accretive deal activity.  The company carries "
        "~$25B of long-term debt, largely at fixed rates with a laddered maturity "
        "schedule through 2040+."
    ),
    inflation_pass_through=(
        "Moderate: Realty Income's leases include 1-2% annual escalators that partially "
        "offset inflation but lag CPI in high-inflation environments.  Some leases "
        "include CPI-linked bumps, providing better inflation protection on a minority "
        "of the portfolio.  Tenant health is the more direct inflation exposure — if "
        "consumer inflation erodes discretionary spending, Realty Income's retail "
        "tenants (convenience, drug store, QSR) tend to be non-discretionary and "
        "see limited traffic impact."
    ),
    recession_behavior=(
        "Highly defensive overall — Realty Income's tenant base is concentrated in "
        "non-discretionary categories: Dollar General, Dollar Tree, 7-Eleven, "
        "Walgreens, and grocery-anchored formats that serve everyday spending needs. "
        "Occupancy held above 98% during the 2008-09 recession and the 2020 COVID "
        "shock (some temporary rent deferral agreements were negotiated with fitness "
        "and theater tenants).  However, Realty Income remains exposed to tenant "
        "financial health — a wave of retail tenant bankruptcies (Bed Bath & Beyond, "
        "Rite Aid) temporarily elevated vacancy and required re-tenanting costs that "
        "reduced AFFO in the short term.  The pharmacy format faces structural headwinds "
        "from e-commerce prescription delivery (Amazon Pharmacy) and GLP-1 drug impacts."
    ),
    major_risks=[
        "Interest rate sensitivity on AFFO yield spread — at elevated 10-year Treasury "
        "rates (4.5-5%), Realty Income's AFFO yield offers thin spread over risk-free, "
        "compressing the P/AFFO multiple and limiting the accretion from acquisition-led "
        "AFFO growth",
        "Pharmacy and drug store tenant structural risk — Walgreens (~4% of rent) and "
        "CVS (~1%) face structural headwinds from Amazon Pharmacy, e-commerce "
        "prescription delivery, and GLP-1 drug adoption reducing pharmacy visit "
        "frequency; Walgreens has been closing hundreds of locations",
        "Retail tenant bankruptcy risk — Realty Income's concentration in retail formats "
        "exposes AFFO to sporadic large-tenant bankruptcies (Rite Aid, Bed Bath & Beyond) "
        "requiring re-tenanting at potentially lower rents or with capital expenditure",
        "Spirit Realty and Encore UK integration complexity — the Spirit merger and "
        "European expansion added portfolio concentration in previously unfamiliar "
        "geographies and tenant profiles; integration discipline and European market "
        "dynamics differ from the core US net lease thesis",
        "AFFO payout ratio constraints — Realty Income pays out ~75% of AFFO as "
        "dividends, leaving limited retained earnings for organic balance sheet "
        "strengthening; growth depends on continuous access to the capital markets "
        "at favorable borrowing costs",
    ],
    valuation_style=(
        "Realty Income is priced on a P/AFFO multiple (~15-17x) and AFFO yield (~5-6%), "
        "with institutional investors comparing the dividend yield directly to "
        "10-year Treasuries and investment-grade corporate bond yields.  In low-rate "
        "environments (2015-2021), Realty Income commanded a 20-22x AFFO premium for "
        "its Dividend Aristocrat status and 99% occupancy track record.  At current "
        "rate levels, the P/AFFO has compressed to 15-17x — fairly priced as an income "
        "vehicle if rates stabilize, but subject to further multiple compression if "
        "the 10-year rate rises above 5%.  The monthly dividend track record (607+ "
        "consecutive payments) and investment-grade tenant base support the current "
        "AFFO yield floor compared to lower-credit net lease peers."
    ),
    key_metrics=[
        "AFFO per share growth (target 3-5%/yr)",
        "Occupancy rate (target 98-99%)",
        "Lease spreads on renewals vs expirations",
        "AFFO yield vs 10-year Treasury spread",
        "Acquisition volume and cap rate spread vs borrowing cost",
        "Walgreens and pharmacy tenant concentration and rent coverage",
        "UK and European portfolio performance",
        "Monthly dividend coverage ratio (AFFO payout ratio)",
    ],
    competitive_advantages=[
        "Investment-grade tenant base: approximately 85% of Realty Income rent is paid "
        "by tenants rated investment-grade (BBB- or above) or with investment-grade "
        "parent companies — the credit quality is structurally superior to smaller "
        "net lease peers that accept sub-investment-grade tenants for higher cap rates",
        "Dividend Aristocrat track record: 607+ consecutive monthly dividends and 30+ "
        "consecutive annual dividend increases provide institutional yield mandates with "
        "predictability that creates a stable investor base and supports the P/AFFO premium",
        "Scale-driven borrowing cost advantage: Realty Income's $60B+ enterprise size "
        "and investment-grade balance sheet (Baa1/BBB+) allows it to borrow at 20-50 "
        "basis points below smaller net lease peers — a persistent acquisition spread "
        "advantage that compounds over a multi-decade acquisition program",
    ],
    business_model_keywords=[
        "Realty Income", "net lease", "triple-net", "AFFO", "P/AFFO",
        "monthly dividend", "Dividend Aristocrat", "Dollar General", "Walgreens",
        "7-Eleven", "occupancy", "lease escalator", "investment-grade tenant",
        "Spirit Realty", "Encore UK", "cap rate", "acquisition spread",
        "pharmacy", "convenience", "payout ratio", "bond proxy",
    ],
))


# ── Simon Property Group, Inc. (SPG) ─────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SPG",
    company_name="Simon Property Group, Inc.",
    business_model=(
        "Simon Property Group is the largest US mall REIT, owning 95+ premium malls, "
        "Premium Outlet centers, and The Mills properties across the US, Canada, and "
        "international partnerships in Asia and Europe.  Simon's thesis is that Class A "
        "destination malls and premium outlet centers in prime trade areas are resilient "
        "against e-commerce disruption because they serve an experiential function — "
        "dining, entertainment, and social commerce — that cannot be substituted by "
        "online shopping.  Revenue is generated primarily through base rent and "
        "percentage rent participation in tenant sales, with the premium outlet channel "
        "(Simon Premium Outlets, The Mills) showing stronger traffic and sales than "
        "enclosed mall formats."
    ),
    primary_revenue_drivers=[
        "Class A mall and Premium Outlet base rent (~70% of revenue) — long-term "
        "lease agreements with specialty retail, anchor department stores, dining, "
        "and entertainment tenants; Simon's top properties command the highest "
        "rent per square foot of any US mall operator",
        "Percentage rent participation (~10%) — above-breakpoint sales trigger "
        "additional rent tied to tenant performance; strong consumer spending "
        "environments boost percentage rent meaningfully",
        "Premium Outlets and The Mills (~20%) — Simon Premium Outlets (Woodbury Common, "
        "Sawgrass Mills, others) benefit from tourist and outlet shopper traffic that "
        "is partially insulated from direct e-commerce competition on luxury goods",
    ],
    recurring_revenue_sources=[
        "Base mall rent from Class A and Premium Outlet tenants — long-term lease "
        "agreements (typically 5-10 year initial terms) with fixed annual rent steps; "
        "Simon's occupancy above 94% provides revenue continuity across lease cycles",
        "Percentage rent participation tied to tenant sales performance — recurring "
        "quarterly revenue from above-breakpoint tenant sales in Premium Outlet and "
        "Class A mall locations; this revenue stream is tied to consumer spending trends",
    ],
    rate_sensitivity_note=(
        "Simon Property Group carries ~$30B of long-term debt and trades at ~12-14x "
        "forward FFO — a discount to industrial and net lease REITs reflecting the "
        "structural e-commerce risk premium on enclosed mall assets.  As a "
        "capital-intensive REIT, Simon's cost of debt refinancing matters: the company "
        "issued a significant portion of its long-term debt at 2-4% rates in 2020-22, "
        "and future refinancing at 5-6% would increase interest expense.  The FFO "
        "multiple is moderately rate-sensitive — Simon's strong anchor redevelopment "
        "pipeline adds long-dated FFO uplift that is discounted at the prevailing rate."
    ),
    inflation_pass_through=(
        "Moderate: Simon's fixed annual rent steps (typically 2-3%/yr) provide partial "
        "inflation pass-through below CPI in high-inflation environments.  Percentage "
        "rent rises with nominal tenant sales, which inflate with consumer prices, "
        "providing an indirect inflation link.  Construction and redevelopment costs "
        "(anchor box conversions) inflate significantly — Simon's transformation of "
        "department store anchors to mixed-use has become more expensive, though "
        "incremental FFO from the redeveloped space is also inflation-adjusted."
    ),
    recession_behavior=(
        "Partially resilient — Simon's Class A mall and Premium Outlet properties "
        "maintained occupancy above 93% through the 2020 COVID shock (after temporary "
        "closures) and have recovered strongly.  Premium Outlets provide a partially "
        "defensive revenue base: they are less discretionary than traditional malls — "
        "value-seeking shoppers and international tourists "
        "sustain Woodbury Common and Las Vegas Premium Outlets through economic "
        "downturns.  However, Simon's enclosed mall tenant base includes discretionary "
        "apparel retailers (Gap, H&M, Forever 21) that experience meaningful same-store "
        "sales declines in recessions, reducing percentage rent and putting pressure on "
        "lease renewal spreads.  Department store anchor closures (Macy's, JCPenney) "
        "require costly re-tenanting and temporary income gaps."
    ),
    major_risks=[
        "E-commerce structural pressure on apparel — apparel and footwear (Simon's "
        "two largest tenant categories) continue to lose share to online retailers; "
        "while Simon's Class A properties are more resilient than B and C malls, the "
        "structural shift in discretionary apparel spending toward e-commerce creates "
        "ongoing lease renewal headwinds and lower long-term base rent growth",
        "Department store anchor closures — Macy's, Nordstrom, and JCPenney closures "
        "require Simon to invest $100-300M per anchor box in redevelopment to convert "
        "spaces to mixed-use; during the multi-year redevelopment, the space is "
        "temporarily vacant and generates no rent, impairing near-term FFO",
        "REIT leverage at 6-7x Debt/EBITDA — Simon's balance sheet leverage is higher "
        "than industrial and net lease REITs, limiting financial flexibility in "
        "rate-elevated environments and reducing the FFO multiple vs lower-leverage peers",
        "Consumer discretionary sensitivity — Simon's Class A mall tenant base "
        "includes significant discretionary retail exposure (fashion, electronics, "
        "luxury accessories) that softens in consumer spending contractions",
        "Redevelopment execution risk — converting large anchor boxes to mixed-use "
        "(hotel, residential, entertainment, office) requires complex zoning, "
        "construction management, and tenanting; delays or cost overruns impair the "
        "projected FFO return on the redevelopment capital",
    ],
    valuation_style=(
        "Simon Property Group trades at ~12-14x forward FFO and an AFFO yield of "
        "5-7%, at a discount to industrial and net lease REITs reflecting the mall "
        "format risk premium.  The market prices SPG as a high-quality mall operator "
        "with meaningful redevelopment upside potential — Premium Outlet occupancy "
        "above 98% and Class A mall demand justify a premium to the broader mall peer "
        "group, but not to industrial or net lease formats.  The near-term re-rating "
        "catalyst is confirmation that department store anchor redevelopments generate "
        "projected FFO spreads and that tenant diversification toward experiential "
        "formats (dining, fitness, healthcare, co-working) is offsetting apparel lease "
        "headwinds in the portfolio."
    ),
    key_metrics=[
        "Comparable property NOI growth (same-store)",
        "Occupancy rate (Class A malls vs Premium Outlets)",
        "Lease spreads on renewals (new rent vs expiring rent)",
        "Percentage rent as % of total revenue (consumer spending indicator)",
        "Anchor redevelopment pipeline: number of boxes in progress and projected FFO yield",
        "Malls Debt/EBITDA leverage ratio",
        "Dividend coverage ratio (FFO payout ratio)",
        "International Premium Outlet traffic and sales productivity",
    ],
    competitive_advantages=[
        "Class A trophy mall portfolio irreplaceability: Simon's top 50 properties "
        "(Woodbury Common, Sawgrass Mills, The Forum Shops at Caesars) are high-traffic "
        "destination assets in major MSAs that cannot be replicated — new enclosed mall "
        "development in the US has been effectively zero since 2007, making Simon's "
        "existing Class A portfolio a structural scarcity asset",
        "Simon Premium Outlets and The Mills dominant position: the premium outlet "
        "channel is more resilient than traditional mall formats, benefiting from "
        "international tourist traffic and brand manufacturer use of outlet channels "
        "for inventory management; Simon's outlet portfolio has the highest sales "
        "productivity per square foot of any outlet operator in the US",
        "Tenant diversification toward experiential formats: Simon has redirected "
        "anchor re-tenanting toward dining, entertainment, healthcare, and fitness "
        "tenants — uses that are e-commerce resistant and drive traffic for the "
        "in-line retailers; more than 25% of rent now comes from non-apparel tenants",
    ],
    business_model_keywords=[
        "Simon Property Group", "SPG", "Class A mall", "Premium Outlets",
        "Woodbury Common", "Sawgrass Mills", "enclosed mall", "AFFO", "FFO",
        "anchor redevelopment", "Macy's", "Nordstrom", "apparel",
        "percentage rent", "same-store NOI", "occupancy", "experiential",
        "P/FFO", "Dividend Aristocrat", "e-commerce", "outlet channel",
        "redevelopment", "mixed-use", "luxury retail",
    ],
))


# ---------------------------------------------------------------------------
# Phase 6 — Coverage Expansion  (35 new profiles)
# ---------------------------------------------------------------------------

# ── Financials ───────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="WFC",
    company_name="Wells Fargo & Company",
    business_model=(
        "Wells Fargo is one of the four largest US commercial banks, operating "
        "consumer banking, commercial banking, corporate and investment banking, "
        "and wealth and investment management.  Revenue is generated through net "
        "interest income on loans and deposits, fee-based services, and mortgage "
        "origination and servicing.  The company operates under a Federal Reserve "
        "asset cap imposed in 2018, limiting balance sheet growth until the cap "
        "is lifted."
    ),
    primary_revenue_drivers=[
        "Net interest income (~55%) — spread on $950B+ loan and securities portfolio "
        "funded by $1.3T deposit base; NII is highly sensitive to interest-rate moves",
        "Fee-based services (~30%) — wealth management advisory fees, card fees, "
        "deposit and treasury management fees, and mortgage banking income",
        "Mortgage banking (~15%) — origination and servicing income from one of the "
        "largest US mortgage platforms; cyclically sensitive to rates and housing",
    ],
    recurring_revenue_sources=[
        "Net interest income from the commercial and consumer loan portfolio "
        "generates recurring spread revenue tied to floating-rate benchmarks",
        "Fee-based banking services including deposit fees, wire transfer fees, "
        "and wealth advisory income provide repeating non-interest revenue",
    ],
    rate_sensitivity_note=(
        "Wells Fargo is among the most asset-sensitive large US banks; rising rates "
        "substantially boost NII while falling rates compress spread income.  "
        "The Fed asset cap limits deposit repricing optionality.  "
        "P/TBV and P/E are the primary valuation anchors."
    ),
    inflation_pass_through=(
        "Moderate: loan repricing tracks floating-rate benchmarks providing "
        "partial inflation pass-through; operating cost inflation (salaries, "
        "technology) is a partial offset."
    ),
    recession_behavior=(
        "Wells Fargo generates stable net interest income from its diversified "
        "loan book and demonstrates resilient fee-based revenue from its retail "
        "banking franchise.  However, commercial and consumer credit quality has "
        "cyclical exposure to economic downturns, elevating loan-loss provisions."
    ),
    major_risks=[
        "Federal Reserve asset cap — WFC cannot grow its balance sheet beyond "
        "~$1.95T until the Fed lifts the 2018 consent order; this constrains "
        "loan growth and deposit gathering relative to unrestricted peers",
        "Credit cycle exposure — consumer and commercial loan charge-offs rise "
        "materially in recessions; CRE office and auto lending are elevated-risk "
        "pockets given current vacancy and rate dynamics",
        "Mortgage banking revenue volatility — origination volume collapses in "
        "high-rate environments, reducing non-interest income significantly "
        "and creating earnings variability",
        "Regulatory and reputational overhang — ongoing consent orders and "
        "heightened scrutiny from regulators raise compliance costs and "
        "constrain strategic flexibility vs peers",
    ],
    valuation_style=(
        "WFC trades at 1.1-1.4x tangible book and 10-12x forward earnings, "
        "a discount to JPM reflecting the asset cap and execution uncertainty.  "
        "The re-rating catalyst is Federal Reserve removal of the consent order, "
        "which would allow balance sheet growth and improve P/TBV toward peers.  "
        "FCF yield supports a growing dividend and buyback program."
    ),
    key_metrics=[
        "Net interest margin (NIM) and net interest income growth",
        "Efficiency ratio (non-interest expense / revenue)",
        "Return on tangible common equity (ROTCE)",
        "Net charge-off rate by loan category",
        "Tangible book value per share growth",
    ],
    competitive_advantages=[
        "Dominant retail deposit franchise with 4,200+ branches and $1.3T deposit "
        "base providing low-cost funding across US consumer and commercial segments",
        "Leading US mortgage origination and servicing platform with deep "
        "geographic penetration and servicer scale across conforming and jumbo loans",
        "Established commercial banking relationships across middle market, "
        "large corporate, and government segments providing diversified fee income",
    ],
    business_model_keywords=[
        "WFC", "Wells Fargo", "net interest income", "NIM", "asset cap",
        "consent order", "mortgage banking", "P/TBV", "ROTCE", "deposit",
        "commercial banking", "wealth management", "loan loss provision",
        "Federal Reserve", "tangible book",
    ],
))

# ── Semiconductors ───────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="QCOM",
    company_name="Qualcomm Incorporated",
    business_model=(
        "Qualcomm operates two core segments: QCT (chips — Snapdragon SoCs, "
        "modems, RF, IoT, and automotive) and QTL (patent licensing — royalties "
        "from smartphone OEMs on handset ASPs).  QTL is high-margin (~70% EBIT) "
        "and contributes disproportionately to earnings despite lower revenue share.  "
        "Qualcomm is expanding beyond smartphones into automotive (Snapdragon Digital "
        "Chassis) and IoT/PC segments to diversify from handset dependence."
    ),
    primary_revenue_drivers=[
        "QCT chip revenue (~85%) — Snapdragon SoCs for Android flagships, modems "
        "for Apple, automotive infotainment and ADAS chips; cyclical with handset cycles",
        "QTL licensing revenue (~15%) — per-device royalties from smartphone OEMs; "
        "highly recurring, asset-light, and high-margin",
        "Automotive chip revenue — growing contribution from Snapdragon Digital "
        "Chassis for cockpit, ADAS, and C-V2X connectivity systems",
    ],
    recurring_revenue_sources=[
        "QTL patent royalty income from global smartphone OEM licensing agreements "
        "generates high-margin recurring fee revenue tied to handset unit volumes",
        "Snapdragon SoC chip orders from Android and automotive OEM customers "
        "provide quarterly revenue tied to device production cycles",
    ],
    rate_sensitivity_note=(
        "Qualcomm is not directly rate-sensitive.  EV/EBITDA and P/E are primary "
        "valuation anchors.  Higher rates reduce the present-value of licensing "
        "streams and compress semiconductor multiples broadly."
    ),
    inflation_pass_through=(
        "Moderate: QTL royalties are ASP-linked, providing some inflation "
        "pass-through.  QCT chip pricing is competitive; input cost inflation "
        "from TSMC foundry pricing flows through with a lag."
    ),
    recession_behavior=(
        "Qualcomm generates stable QTL royalty income from its patent portfolio "
        "and demonstrates resilient licensing cash flows through handset cycles.  "
        "However, QCT chip revenue has cyclical exposure to smartphone replacement "
        "demand and OEM inventory correction periods."
    ),
    major_risks=[
        "Apple modem in-housing — Apple is developing its own 5G modem and plans "
        "to reduce QCOM modem dependence; this creates a meaningful revenue "
        "cliff risk as Apple transitions away from Snapdragon X modems",
        "Smartphone market concentration — ~60% of QCT revenue is handset-exposed; "
        "weak global smartphone upgrade cycles (2022-23 pattern) reduce chip "
        "volumes and create earnings volatility",
        "QTL licensing dispute risk — Qualcomm's patent licensing model has faced "
        "antitrust challenges globally; adverse legal outcomes could impair royalty "
        "rates or licensee compliance",
        "China market dependency — Qualcomm derives ~60% of revenue from China-based "
        "OEMs; US-China trade restrictions and Huawei dynamics create geopolitical risk",
    ],
    valuation_style=(
        "QCOM trades at 12-16x forward earnings and 8-10x EV/EBITDA, at a discount "
        "to fabless peers reflecting Apple modem risk and handset concentration.  "
        "The automotive and IoT re-rating thesis requires execution on non-handset "
        "TAM expansion.  FCF yield and dividend growth support the investment case."
    ),
    key_metrics=[
        "QCT chip revenue by end market (handset, auto, IoT)",
        "QTL licensing revenue and royalty rate per device",
        "Automotive pipeline bookings (multi-year design wins)",
        "Apple modem revenue as % of QCT",
        "EV/EBITDA vs. fabless semiconductor peers",
    ],
    competitive_advantages=[
        "Snapdragon mobile SoC leadership in Android premium and mid-range segments "
        "with deep ecosystem integration across camera, AI, and connectivity IP",
        "QTL patent licensing portfolio covering essential 3G/4G/5G standards "
        "providing recurring, high-margin royalty income with global enforceability",
        "Automotive semiconductor expansion with Snapdragon Digital Chassis "
        "design wins at BMW, Stellantis, GM, and other Tier-1 automakers",
    ],
    business_model_keywords=[
        "QCOM", "Qualcomm", "Snapdragon", "QTL", "QCT", "5G modem",
        "patent royalty", "Apple modem", "Snapdragon Digital Chassis",
        "handset SoC", "automotive semiconductor", "P/E", "EV/EBITDA",
        "fabless", "RF front-end",
    ],
    moat_type=["patent", "data_advantage"],
    revenue_model="licensing",
    switching_cost_level="moderate",
    customer_concentration="concentrated",
    capital_intensity="moderate",
    earnings_cyclicality="highly_cyclical",
    narrative_dependence="low",
    binary_risk_level="low",
))


_register(CompanyKnowledgeProfile(
    ticker="TXN",
    company_name="Texas Instruments Incorporated",
    business_model=(
        "Texas Instruments is the global leader in analog and embedded "
        "semiconductors, shipping 80,000+ products to 100,000+ customers across "
        "industrial, automotive, personal electronics, communications, and "
        "enterprise end markets.  TI's differentiation lies in its 300mm "
        "manufacturing advantage (lowest cost per chip in analog), its vast "
        "product catalog providing revenue diversity, and its direct-to-customer "
        "sales model that builds long-duration design-win relationships."
    ),
    primary_revenue_drivers=[
        "Analog chips (~75%) — power management, signal chain, amplifiers, "
        "and data converters sold to industrial and automotive OEMs; long "
        "product lifecycles and high customer switching costs",
        "Embedded processors (~25%) — microcontrollers and digital signal "
        "processors for industrial control, motor drive, and automotive ADAS",
        "Industrial and automotive end markets (~65% combined) — structural "
        "share shift toward higher-margin, longer-cycle customers",
    ],
    recurring_revenue_sources=[
        "Long-term industrial and automotive customer design wins generate "
        "recurring analog chip order flow over 5-10 year product lifecycles",
        "Direct-to-customer sales program provides repeat quarterly order "
        "revenue from OEM production schedules and safety-stock replenishment",
    ],
    rate_sensitivity_note=(
        "TI is not directly rate-sensitive.  P/E and FCF yield are primary "
        "valuation anchors.  TI's capital return policy (60-80% FCF to "
        "dividends+buybacks) is a key valuation support."
    ),
    inflation_pass_through=(
        "Good: TI's 300mm internal manufacturing provides structural cost "
        "advantages vs. peers sourcing from TSMC; pricing power on "
        "proprietary analog products supports margin stability in inflation."
    ),
    recession_behavior=(
        "Texas Instruments generates stable revenue from its diverse industrial "
        "and automotive customer base and demonstrates resilient through-cycle "
        "cash flows.  However, industrial CapEx and automotive production schedules "
        "have cyclical sensitivity to economic slowdowns and inventory corrections."
    ),
    major_risks=[
        "Analog semiconductor inventory cycle — the 2022-24 inventory correction "
        "showed that even diversified analog demand can experience multi-quarter "
        "destocking; recovery timelines are difficult to predict precisely",
        "Industrial CapEx sensitivity — factory automation and industrial "
        "equipment purchasing is procyclical; TI's 65%+ industrial/auto mix "
        "creates above-average cyclical earnings sensitivity",
        "300mm capacity expansion timing — TI's $15B+ US fab investment "
        "(Sherman, Texas) adds substantial depreciation ahead of demand "
        "recovery, pressuring near-term FCF and ROIC",
        "Competitive pricing pressure — ADI and Microchip compete directly "
        "in analog; while TI has manufacturing advantages, price competition "
        "limits long-run pricing power in commoditized analog products",
    ],
    valuation_style=(
        "TI trades at 25-35x forward P/E and 20-25x EV/EBITDA — a structural "
        "premium to analog peers reflecting FCF conversion quality and capital "
        "return commitment.  The investment thesis centers on through-cycle "
        "FCF yield of 3-5% and consistent dividend growth.  P/FCF is the most "
        "reliable valuation anchor given TI's manufacturing investment cycle."
    ),
    key_metrics=[
        "Revenue by end market (industrial, automotive, personal electronics)",
        "Gross margin and operating margin through the cycle",
        "Free cash flow per share and FCF conversion",
        "Capital return (dividends + buybacks) as % of FCF",
        "300mm wafer capacity utilization",
    ],
    competitive_advantages=[
        "300mm analog wafer manufacturing cost structure — TI's in-house "
        "300mm fabs produce analog chips at significantly lower cost per die "
        "than peers relying on external 200mm foundries",
        "Broadest analog product catalog with 80,000+ SKUs enabling "
        "single-source supply relationships with industrial OEMs at scale",
        "Direct-to-customer sales model with dedicated field application "
        "engineers building multi-year design-in relationships at OEM accounts",
    ],
    business_model_keywords=[
        "TXN", "Texas Instruments", "analog semiconductor", "embedded processor",
        "300mm", "industrial", "automotive", "power management", "signal chain",
        "design win", "FCF yield", "P/E", "capital return", "ADI", "Microchip",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="MU",
    company_name="Micron Technology, Inc.",
    business_model=(
        "Micron is the only US-based manufacturer of DRAM and NAND memory, "
        "operating fabs in Idaho, Virginia, Japan, Taiwan, and Singapore.  "
        "DRAM (~65% of revenue) serves data center servers, mobile phones, "
        "and PCs.  NAND (~35%) serves SSDs for enterprise storage, client PCs, "
        "and mobile.  Micron is the primary supplier of HBM3E (high-bandwidth "
        "memory) for NVIDIA H100/H200 GPUs, creating a high-value AI data "
        "center revenue stream alongside the commodity memory cycle."
    ),
    primary_revenue_drivers=[
        "DRAM (~65%) — server DRAM for hyperscale data centers, mobile LPDRAM "
        "for smartphones, PC DRAM; pricing is highly cyclical with supply/demand",
        "NAND (~35%) — enterprise SSDs, client SSDs, managed NAND for mobile; "
        "NAND pricing is more volatile than DRAM due to lower market concentration",
        "HBM3E for AI workloads — sole US-source HBM supplier for NVIDIA A100/H100 "
        "GPU clusters; high-ASP, margin-accretive, and supply-constrained",
    ],
    recurring_revenue_sources=[
        "DRAM supply contracts with hyperscale cloud providers and server OEM "
        "customers provide quarterly volume commitments at market pricing",
        "NAND SSD supply agreements with PC OEM and enterprise storage accounts "
        "generate recurring order flow tied to production schedules",
    ],
    rate_sensitivity_note=(
        "Micron is not directly rate-sensitive.  P/E, EV/EBITDA on normalized "
        "earnings, and P/book are the primary valuation anchors across the memory "
        "cycle.  Capital-intensive fabs require ongoing debt financing."
    ),
    inflation_pass_through=(
        "Low on commodity memory (pricing is market-driven, not cost-plus).  "
        "HBM3E pricing is more favorable and partially cost-plus given supply constraints."
    ),
    recession_behavior=(
        "Micron generates stable production volumes from its global DRAM and NAND "
        "fabs and demonstrates resilient long-run demand from secular data growth.  "
        "However, memory ASPs have severe cyclical exposure to supply-demand imbalances, "
        "resulting in dramatic revenue and margin swings across the memory cycle."
    ),
    major_risks=[
        "Memory pricing cycle — DRAM and NAND ASPs can fall 50-70% in down cycles "
        "as oversupply from Samsung and SK Hynix floods the market; Micron's "
        "earnings swing dramatically with the industry supply/demand balance",
        "Samsung and SK Hynix competitive intensity — Korean memory manufacturers "
        "have historically cross-subsidized memory operations through downturns, "
        "prolonging pricing pressure beyond what supply reduction discipline would imply",
        "China geopolitical risk — Micron's China revenue (~10-15%) was "
        "restricted by Chinese regulators in 2023; further restrictions or "
        "fab access limitations pose material revenue risk",
        "HBM capacity execution — Micron's ramp of HBM3E capacity for AI "
        "customers requires complex packaging and testing; yield and delivery "
        "execution determine whether Micron captures its full AI allocation",
    ],
    valuation_style=(
        "MU trades at 8-15x forward P/E on normalized mid-cycle earnings, with "
        "peak-cycle P/E artificially low and trough-cycle P/E meaninglessly high.  "
        "The investment thesis requires a view on the memory cycle timing and "
        "HBM3E TAM expansion from AI infrastructure.  EV/normalized EBITDA and "
        "P/book are more reliable through-cycle anchors than trailing multiples."
    ),
    key_metrics=[
        "DRAM and NAND ASP trends (quarter-over-quarter)",
        "Gross margin by segment (DRAM vs. NAND vs. HBM)",
        "HBM3E revenue and market share vs. Samsung and SK Hynix",
        "Inventory days (industry and Micron-specific destocking progress)",
        "Capital expenditure as % of revenue vs. depreciation",
    ],
    competitive_advantages=[
        "Only US-headquartered DRAM and NAND manufacturer with geopolitical "
        "importance for US semiconductor supply chain independence",
        "HBM3E leadership for AI GPU memory — Micron is the primary non-Korean "
        "HBM supplier for NVIDIA, capturing margin-accretive AI memory demand",
        "1-beta DRAM node technology maintaining competitive cost structure "
        "with Samsung and SK Hynix at advanced process nodes",
    ],
    business_model_keywords=[
        "MU", "Micron", "DRAM", "NAND", "HBM3E", "memory cycle",
        "high-bandwidth memory", "NVIDIA", "server DRAM", "enterprise SSD",
        "Samsung", "SK Hynix", "P/book", "normalized earnings", "EV/EBITDA",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="AMAT",
    company_name="Applied Materials, Inc.",
    business_model=(
        "Applied Materials is the world's largest semiconductor equipment company "
        "by revenue, providing deposition (CVD, PVD, ALD), etch, CMP, "
        "metrology/inspection, and thermal processing tools.  Customers include "
        "TSMC, Samsung, Intel, and SK Hynix.  Applied's breadth across the "
        "wafer fabrication flow — from deposition through inspection — provides "
        "more complete process coverage than any single competitor.  Advanced "
        "packaging equipment is a fast-growing incremental segment."
    ),
    primary_revenue_drivers=[
        "Semiconductor Systems (~75%) — front-end wafer fabrication equipment "
        "for logic, DRAM, and NAND; revenue highly correlated with WFE spend",
        "Applied Global Services (~20%) — spare parts, consumables, and "
        "process support; more stable than equipment revenue across the cycle",
        "Display (~5%) — equipment for OLED and LCD display manufacturing",
    ],
    recurring_revenue_sources=[
        "Spare parts and consumable orders from the global installed base of "
        "deposition and etch tools generate recurring revenue between equipment cycles",
        "Process support and equipment upgrade programs at leading-edge fabs "
        "provide annual revenue from installed tool performance optimization",
    ],
    rate_sensitivity_note=(
        "AMAT is not directly rate-sensitive.  EV/EBITDA and P/E on normalized "
        "WFE spend are the primary valuation anchors.  Higher rates reduce "
        "semiconductor CapEx budgets over time, creating an indirect headwind."
    ),
    inflation_pass_through=(
        "Good: semiconductor equipment is custom-configured and high-value; "
        "AMAT has pricing power on new tool configurations and aftermarket "
        "parts given captive installed base relationships."
    ),
    recession_behavior=(
        "Applied Materials generates stable services revenue from its global "
        "installed base and demonstrates resilient long-run demand from secular "
        "semiconductor content growth.  However, WFE (wafer fabrication equipment) "
        "spending has cyclical sensitivity to fab utilization and chipmaker CapEx budgets."
    ),
    major_risks=[
        "WFE spending cycle — semiconductor equipment revenue can decline 20-30% "
        "in down cycles as chipmakers defer capacity additions; 2022-23 showed "
        "memory WFE cuts of 40-50% while logic/foundry was more resilient",
        "TSMC/Samsung customer concentration — top 2-3 customers represent "
        "a large portion of systems revenue; changes in their CapEx outlook "
        "have an outsized impact on AMAT's quarterly revenue",
        "China export controls — AMAT's China revenue (~30%) is subject to BIS "
        "advanced chip equipment restrictions; escalation of controls would "
        "impair China systems revenue materially",
        "ASML EUV dependency — leading-edge logic nodes increasingly use EUV "
        "patterning from ASML, creating a segment where AMAT cannot participate "
        "directly and must rely on etch/deposition adjacencies",
    ],
    valuation_style=(
        "AMAT trades at 15-20x forward P/E and 12-15x EV/EBITDA on normalized "
        "WFE spending, with premium reflecting services mix and process breadth.  "
        "The investment thesis is secular semiconductor content growth (AI, EVs, "
        "advanced packaging) driving above-GDP WFE spend over a 5-7 year cycle.  "
        "FCF yield and buyback capacity support the multiple."
    ),
    key_metrics=[
        "WFE (wafer fabrication equipment) market share by process step",
        "Services revenue as % of total (cycle stability indicator)",
        "China revenue as % of total (export control exposure)",
        "Backlog and order book vs. prior quarter",
        "Gross margin trend by segment (Systems vs. Services)",
    ],
    competitive_advantages=[
        "Broadest equipment portfolio spanning deposition, etch, CMP, "
        "and inspection — enabling single-vendor process integration across "
        "the wafer fabrication flow for logic, DRAM, and NAND",
        "Large installed base creating a captive aftermarket for parts, "
        "consumables, and upgrades — more predictable than new tool revenue",
        "Advanced packaging equipment leadership in hybrid bonding, "
        "RDL deposition, and die-to-wafer bonding for AI chiplet architectures",
    ],
    business_model_keywords=[
        "AMAT", "Applied Materials", "semiconductor equipment", "WFE",
        "deposition", "CVD", "ALD", "etch", "CMP", "metrology",
        "TSMC", "advanced packaging", "EV/EBITDA", "P/E", "wafer fab",
    ],
    moat_type=["scale_economy", "patent"],
    revenue_model="product_sale",
    switching_cost_level="high",
    customer_concentration="concentrated",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


_register(CompanyKnowledgeProfile(
    ticker="LRCX",
    company_name="Lam Research Corporation",
    business_model=(
        "Lam Research is the global leader in plasma etch and CVD/ALD "
        "deposition equipment, holding approximately 45% of the global etch "
        "market.  Lam's tools are essential for 3D NAND manufacturing (etch "
        "depth is the key process challenge) and for advanced logic nodes "
        "where high-aspect-ratio etch is critical.  Customer Support Business "
        "Group (CSBG) — spare parts, upgrades, and service — contributes "
        "~35% of revenue with above-average margin stability."
    ),
    primary_revenue_drivers=[
        "Systems revenue (~65%) — plasma etch, CVD, and ALD tools sold to "
        "NAND, DRAM, and logic fabs; highly correlated with NAND WFE spend",
        "Customer Support Business Group (~35%) — chamber parts, upgrades, "
        "and process support; more recurring and cycle-resilient than systems",
        "3D NAND etch intensity — each additional storage layer in 3D NAND "
        "requires incremental Lam etch and deposition steps, providing a "
        "structural growth driver from NAND stack height increases",
    ],
    recurring_revenue_sources=[
        "Chamber component and replacement parts revenue from the global "
        "installed base of etch and CVD tools at NAND and logic fabs",
        "Fab process support and equipment upgrade orders from existing "
        "customer accounts seeking yield improvement on installed tool fleets",
    ],
    rate_sensitivity_note=(
        "LRCX is not directly rate-sensitive.  EV/EBITDA and P/E on normalized "
        "NAND and logic WFE are primary valuation anchors.  Capital return "
        "via buybacks supports per-share earnings growth."
    ),
    inflation_pass_through=(
        "Good: Lam's custom etch chambers and chamber parts have limited "
        "commodity substitutes; aftermarket pricing is captive to installed base."
    ),
    recession_behavior=(
        "Lam Research generates stable CSBG revenue from its installed tool base "
        "and demonstrates resilient long-run demand from 3D NAND layer count growth.  "
        "However, NAND WFE spending has cyclical exposure to memory pricing cycles "
        "and fab utilization decisions by Samsung, SK Hynix, and Micron."
    ),
    major_risks=[
        "NAND WFE cycle — Lam's revenue is more NAND-concentrated than AMAT "
        "or KLAC; memory capex cuts of 40-50% in down cycles create above-average "
        "revenue headwinds relative to logic-weighted semiconductor equipment peers",
        "Customer concentration — Samsung and SK Hynix together represent "
        ">40% of Lam revenue; Korean memory capex decisions drive material "
        "quarterly revenue variability",
        "China export controls — Lam's China revenue (~30%) is subject to BIS "
        "restrictions on advanced NAND and DRAM equipment; further tightening "
        "would impair systems revenue materially",
        "3D NAND technology transitions — if chipmakers slow NAND layer count "
        "increases (QLC/PLC) or transition to alternative memory architectures, "
        "etch intensity per wafer pass could grow slower than expected",
    ],
    valuation_style=(
        "LRCX trades at 18-22x forward P/E and 13-16x EV/EBITDA on normalized "
        "NAND WFE, with premium to peers reflecting etch dominance and CSBG mix.  "
        "The investment thesis is 3D NAND layer count increasing to 400+ layers "
        "requiring disproportionate etch intensity and Lam tool additions.  "
        "FCF conversion and buyback capacity support capital return."
    ),
    key_metrics=[
        "NAND WFE market share (etch + deposition)",
        "CSBG revenue as % of total (cycle resilience metric)",
        "China revenue as % of total (export control sensitivity)",
        "3D NAND average layer count in customer fabs (etch intensity driver)",
        "Gross margin by segment (Systems vs. CSBG)",
    ],
    competitive_advantages=[
        "~45% global etch market share with deep process integration at all "
        "major NAND and logic fabs, creating high switching costs for established "
        "process recipes built around Lam chamber performance",
        "Co-development relationships with TSMC, Samsung, and Micron at "
        "leading nodes — Lam engineers are embedded in customer process "
        "development labs, creating early-node design-win advantages",
        "CSBG installed base monetization — 60,000+ installed tools worldwide "
        "generating captive, recurring parts and upgrade revenue with "
        "above-systems-average gross margin",
    ],
    business_model_keywords=[
        "LRCX", "Lam Research", "plasma etch", "CVD", "ALD", "3D NAND",
        "CSBG", "chamber parts", "NAND WFE", "Samsung", "SK Hynix",
        "EV/EBITDA", "P/E", "etch market share", "layer count",
    ],
    moat_type=["scale_economy", "patent"],
    revenue_model="product_sale",
    switching_cost_level="high",
    customer_concentration="concentrated",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── Healthcare ───────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="MRK",
    company_name="Merck & Co., Inc.",
    business_model=(
        "Merck is a global pharmaceutical leader with Keytruda (pembrolizumab) "
        "as the world's best-selling cancer immunotherapy, Gardasil (HPV vaccine), "
        "Lagevrio (COVID antiviral), and a broad pipeline in oncology, vaccines, "
        "and infectious disease.  Animal health (Merck Animal Health) contributes "
        "~10% of revenue with durable companion animal and livestock franchises.  "
        "Keytruda loss-of-exclusivity in 2028 is the primary medium-term transition "
        "risk, partially mitigated by MK-7684A and other successor programs."
    ),
    primary_revenue_drivers=[
        "Keytruda (~45% of revenue) — approved in 40+ cancer indications across "
        "1L/2L monotherapy and combination regimens; standard of care in NSCLC, "
        "melanoma, MSI-H, and expanding rapidly in earlier-stage settings",
        "Gardasil HPV vaccine (~15%) — global standard of care for HPV prevention; "
        "particularly strong in China through Zhifei distribution agreement",
        "Animal health, Lagevrio, and hospital products (~40%) — diversified "
        "revenue streams providing stability across oncology growth cycles",
    ],
    recurring_revenue_sources=[
        "Keytruda patient adherence to long-term maintenance immunotherapy protocols "
        "drives recurring prescription refill volume across approved indications",
        "Gardasil multi-year contract vaccine supply agreements with national "
        "immunization programs and school-based vaccination campaigns",
        "Animal health subscription-based preventive care (Bravecto, NexGard, "
        "Nobivac) drives recurring companion animal and livestock pharmaceutical revenue",
        "Oncology maintenance therapy dosing cycles across Merck hospital and "
        "specialty pharmacy accounts deliver predictable infusion center volume",
    ],
    rate_sensitivity_note=(
        "Merck is not directly rate-sensitive.  P/E and FCF yield are the primary "
        "valuation anchors.  Keytruda LOE in 2028 compresses the P/E multiple vs "
        "peers with longer-dated pipeline coverage; FCF yield of 4-6% supports "
        "the base case even in a post-Keytruda revenue step-down scenario."
    ),
    inflation_pass_through=(
        "Good: branded pharmaceuticals have historically held pricing power above "
        "CPI.  The IRA drug price negotiation applies to Keytruda from ~2028, "
        "introducing some pricing risk on the post-LOE biologics franchise."
    ),
    recession_behavior=(
        "Merck's pharmaceutical demand is stable through economic cycles as oncology "
        "and vaccine treatments are essential.  Keytruda immunotherapy demonstrates "
        "resilient utilization from non-elective cancer care decisions.  Merck's "
        "medicines serve mission-critical therapeutic areas with secular demand from "
        "aging global populations and expanding cancer screening programs."
    ),
    major_risks=[
        "Keytruda loss-of-exclusivity in 2028 — Keytruda generates ~$25B+ annually "
        "and faces biosimilar competition from 2028; the revenue cliff requires "
        "successful pipeline launches (MK-7684A, subcutaneous formulation) to offset",
        "IRA drug price negotiation — Keytruda is subject to Medicare price "
        "negotiation from ~2028, which may reduce oncology reimbursement and "
        "compress the peak sales trajectory in the US market",
        "China Gardasil headwind — Zhifei distribution channel destocking and "
        "China national HPV vaccination program policy changes created a $3B+ "
        "revenue shortfall in 2023-24, with limited visibility on recovery timing",
        "Pipeline execution risk — successor programs (MK-7684A TIGIT combo, "
        "islatravir HIV, sotatercept) need to demonstrate Phase 3 efficacy to "
        "bridge the post-Keytruda revenue gap; development setbacks are costly",
        "Animal health competitive pressure — Zoetis and Elanco compete aggressively "
        "in companion animal parasiticides; Bravecto chewable faces growing competition",
    ],
    valuation_style=(
        "MRK trades at 11-15x forward earnings and a FCF yield of 5-7%, embedding "
        "a significant discount for Keytruda LOE risk in 2028.  The investment thesis "
        "requires confidence in MK-7684A and subcutaneous Keytruda as durable revenue "
        "bridges.  P/E relative to sector is depressed by the LOE discount; "
        "an investor taking a positive view on the pipeline is paid to wait."
    ),
    key_metrics=[
        "Keytruda revenue by indication and line of therapy",
        "Gardasil China volume and channel inventory normalization",
        "Pipeline Phase 3 readouts (MK-7684A, islatravir, sotatercept)",
        "Animal health revenue growth vs. Zoetis",
        "FCF yield and dividend growth sustainability post-2028",
    ],
    competitive_advantages=[
        "Keytruda oncology franchise — dominant PD-1 immunotherapy with 40+ "
        "approved indications, massive clinical trial investment, and physician "
        "familiarity creating switching resistance even as biosimilars approach",
        "Gardasil HPV vaccine global leadership — only vaccine approved for "
        "9-valent HPV prevention with established school-based vaccination programs "
        "across 130+ countries and expanding adolescent immunization coverage",
        "Merck Animal Health companion animal scale — Bravecto oral flea/tick, "
        "NexGard heartworm prevention, and Nobivac vaccines provide recurring "
        "veterinarian-dispensed revenue with loyal pet owner adherence",
        "Global biologic manufacturing network — large-scale fermentation and "
        "fill-finish capacity supports Keytruda supply and future biologic pipeline",
        "Regulatory expertise and oncology clinical development capability — "
        "Merck's oncology clinical infrastructure has produced more approvals "
        "than any pharma peer in the past decade",
    ],
    business_model_keywords=[
        "MRK", "Merck", "Keytruda", "pembrolizumab", "Gardasil", "HPV vaccine",
        "Lagevrio", "oncology", "immunotherapy", "PD-1", "NSCLC", "melanoma",
        "animal health", "Bravecto", "LOE", "FCF yield", "P/E", "biosimilar",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="ABT",
    company_name="Abbott Laboratories",
    business_model=(
        "Abbott is a diversified healthcare company spanning medical devices "
        "(FreeStyle Libre CGM, cardiac rhythm, electrophysiology, vascular), "
        "diagnostics (core laboratory, rapid testing, molecular), nutrition "
        "(Similac, Ensure, PediaSure), and established pharmaceuticals.  "
        "FreeStyle Libre continuous glucose monitoring is the world's most "
        "widely used CGM system, generating high-margin, recurring sensor "
        "revenue from 6+ million active users.  Diversification across "
        "four segments provides resilience against single-segment headwinds."
    ),
    primary_revenue_drivers=[
        "Medical devices (~50%) — FreeStyle Libre CGM, Electrophysiology "
        "(EnSite X), cardiac rhythm management, and neuromodulation; "
        "Libre alone represents ~$6B revenue and growing double-digits",
        "Diagnostics (~25%) — core laboratory immunoassay and clinical "
        "chemistry analyzers, rapid COVID/flu/RSV point-of-care tests, "
        "and molecular diagnostics (Alinity m); base lab business is recurring",
        "Nutrition (~15%) and Established Pharma (~10%) — pediatric/adult "
        "nutritionals and branded generics in emerging markets",
    ],
    recurring_revenue_sources=[
        "FreeStyle Libre CGM sensor subscription programs drive recurring "
        "consumable purchases as diabetic patients replace sensors every 14 days",
        "Hospital diagnostic reagent service contract agreements for Alinity "
        "and Architect analyzer installed base generate recurring reagent pulls",
        "Patient adherence to continuous nutrition therapy (Similac, Ensure, "
        "PediaSure) drives repeat institutional and retail purchasing",
        "Medical device maintenance agreements for cardiac monitoring and "
        "vascular intervention installed base in hospital systems",
    ],
    rate_sensitivity_note=(
        "Abbott is not directly rate-sensitive.  P/E and EV/EBITDA are "
        "the primary valuation anchors.  FreeStyle Libre's international "
        "revenue (~60% of Libre) creates currency translation exposure."
    ),
    inflation_pass_through=(
        "Good: Libre sensor pricing is above commodity; diagnostic reagent "
        "pricing has cost-plus components; nutrition products carry brand premiums."
    ),
    recession_behavior=(
        "Abbott's medical device and diagnostic utilization is stable through "
        "economic cycles as patient care is essential.  FreeStyle Libre CGM "
        "adoption is resilient given the non-elective nature of diabetic management.  "
        "Abbott's diversified business model provides mission-critical products "
        "across multiple healthcare segments with secular demand from chronic "
        "disease prevalence and aging populations."
    ),
    major_risks=[
        "FreeStyle Libre competition from Dexcom G7 — Dexcom's G7 and G6 "
        "compete directly in the CGM market; Libre's price advantage and "
        "over-the-counter positioning are key differentiators but market "
        "share competition is intensifying in the US",
        "Diabetes technology disruption from GLP-1 drugs — widespread adoption "
        "of GLP-1 agonists (Ozempic, Wegovy) in Type 2 diabetes may reduce "
        "CGM adoption rates and long-run Libre addressable market",
        "Post-COVID diagnostics normalization — Abbott's rapid COVID testing "
        "contributed $7B+ in peak revenue; the normalization to endemic testing "
        "levels created a multi-year revenue reset in the diagnostics segment",
        "Nutrition quality control risk — Abbott's Sturgis formula plant "
        "shutdown in 2022 demonstrated vulnerability to regulatory action "
        "on manufacturing quality, with multi-quarter revenue and reputational impact",
    ],
    valuation_style=(
        "ABT trades at 22-27x forward earnings and 16-20x EV/EBITDA, at a "
        "premium to diversified medical device peers reflecting Libre CGM "
        "growth and multi-segment resilience.  The investment thesis centers "
        "on Libre doubling its active user base and electrophysiology (pulse "
        "field ablation) becoming a $1B+ incremental revenue contributor.  "
        "FCF yield of 3-4% supports dividend growth and capital return."
    ),
    key_metrics=[
        "FreeStyle Libre revenue and active user count",
        "Diagnostics base business revenue ex-COVID rapid tests",
        "Electrophysiology revenue (EP ablation market share)",
        "Nutrition segment margin recovery",
        "EV/EBITDA vs. diversified healthcare peers",
    ],
    competitive_advantages=[
        "FreeStyle Libre CGM global market leadership with 6+ million active "
        "users — the most widely used continuous glucose monitor globally with "
        "sensor form factor advantages over Dexcom",
        "Diagnostics installed base of Alinity and Architect analyzers in "
        "hospital core laboratories creating captive reagent pull revenue with "
        "high switching costs for clinical laboratory operators",
        "Consumer nutrition brand equity (Similac, Ensure, PediaSure) with "
        "pediatric and adult nutritional dominance in institutional and retail "
        "channels across developed and emerging markets",
        "Electrophysiology procedural technology leadership — Volt PFA and "
        "EnSite X mapping system position Abbott for EP ablation market share "
        "gains in atrial fibrillation treatment",
        "Diversified business model provides single-company exposure to "
        "medical devices, diagnostics, nutrition, and pharma — unique "
        "multi-segment resilience vs. pure-play device or diagnostics peers",
    ],
    business_model_keywords=[
        "ABT", "Abbott", "FreeStyle Libre", "CGM", "Dexcom", "Alinity",
        "Similac", "Ensure", "cardiac rhythm", "electrophysiology",
        "diabetes monitoring", "diagnostics", "P/E", "EV/EBITDA", "pulse field ablation",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="TMO",
    company_name="Thermo Fisher Scientific Inc.",
    business_model=(
        "Thermo Fisher is the world's leading life science tools and services "
        "company, providing analytical instruments, reagents and consumables, "
        "biopharma contract manufacturing (CMO), CRO services, and specialty "
        "diagnostics.  Revenue is generated through four segments: Life Science "
        "Solutions, Analytical Instruments, Specialty Diagnostics, and "
        "Laboratory Products.  Approximately 50% of revenue is recurring "
        "(reagents, consumables, services) providing stability across capital "
        "equipment cycles."
    ),
    primary_revenue_drivers=[
        "Life Science Solutions (~35%) — PCR reagents, cell culture media, "
        "antibodies, gene expression; highly recurring consumable pull",
        "Pharma Services (CMO/CRO) (~20%) — contract drug manufacturing and "
        "clinical services for biopharma customers; multi-year contract revenue",
        "Analytical Instruments (~20%) — mass spectrometers, chromatography, "
        "electron microscopes; capital equipment with aftermarket support",
        "Laboratory Products and Services (~25%) — lab supplies, clinical trials "
        "logistics, and Fisher Scientific channel distribution",
    ],
    recurring_revenue_sources=[
        "Research reagent and consumable subscription programs at biopharma "
        "and academic accounts provide highly recurring laboratory supply revenue",
        "Biopharmaceutical contract manufacturing multi-year contract agreements "
        "for drug substance and drug product supply to pharma developers",
        "Analytical instrument service contract agreements covering preventive "
        "maintenance and calibration of mass spec and chromatography systems",
        "Laboratory equipment maintenance agreements for installed base of "
        "chromatography, spectroscopy, and electron microscopy systems",
    ],
    rate_sensitivity_note=(
        "Thermo Fisher is not directly rate-sensitive.  P/E and EV/EBITDA are "
        "primary valuation anchors.  Higher rates slow biopharma capital deployment "
        "and VC-funded biotech spending, creating an indirect demand headwind."
    ),
    inflation_pass_through=(
        "Good: proprietary reagents and consumables carry pricing power; "
        "CMO services include cost-pass-through provisions; "
        "Fisher Scientific channel distribution has commodity components."
    ),
    recession_behavior=(
        "Life science research spending is mission-critical for drug development "
        "pipelines.  Biopharma CMO and clinical manufacturing demand is resilient "
        "to economic cycles.  Laboratory consumable utilization is stable due to "
        "ongoing research programs.  Diagnostic testing volumes are essential for "
        "healthcare delivery with secular growth from outsourced biopharma services "
        "and multi-omics research."
    ),
    major_risks=[
        "Biopharma CapEx and R&D spending cycle — large pharma and biotech "
        "can defer instrument purchases and reduce lab supply orders in budget "
        "constraint periods; 2022-24 biopharma funding drought created instrument "
        "and consumable headwinds above base business",
        "Academic and government funding variability — NIH funding levels and "
        "grant cycle timing affect instrument and reagent purchasing; budget "
        "continuing resolutions create order timing uncertainty",
        "China market slowdown — TMO's China revenue (~10%) decelerated sharply "
        "in 2022-23 as local competitors gained share and COVID testing demand "
        "normalized; China instruments market remains soft",
        "PPD CRO business integration — acquisition of PPD added contract research "
        "capabilities but also integration execution requirements and exposure "
        "to biotech funding cycles for drug development program initiation",
    ],
    valuation_style=(
        "TMO trades at 22-28x forward earnings and 15-18x EV/EBITDA, at a premium "
        "to instrument peers reflecting CMO/CRO mix, recurring consumable base, "
        "and M&A integration discipline.  The investment thesis requires "
        "biopharma spending normalization and instrument cycle recovery.  "
        "FCF yield of 3-4% supports capital allocation flexibility."
    ),
    key_metrics=[
        "Life Science Solutions organic growth (reagents and consumables)",
        "Pharma Services revenue growth and CMO order book",
        "Analytical Instruments bookings vs. prior quarter",
        "China revenue growth (biopharma spend recovery)",
        "Adjusted EPS growth and FCF conversion",
    ],
    competitive_advantages=[
        "Instrumentation installed base stickiness — analytical instruments "
        "are integrated into research workflows; switching costs from software, "
        "methods, and training lock in Thermo Fisher's mass spec and chromatography "
        "customers for 7-10+ year replacement cycles",
        "Biopharma CMO/CRO scale — Thermo Fisher's Patheon CMO and PPD CRO "
        "capabilities create an end-to-end outsourcing partner for drug development, "
        "differentiated from pure instrument vendors",
        "Consumables captivity — proprietary cell culture media, PCR reagents, "
        "and antibodies sold through Fischer Scientific create recurring pull "
        "from laboratories with limited switching alternatives",
        "Acquisition integration track record — Thermo Fisher has successfully "
        "integrated Life Technologies, PPD, and other acquisitions, demonstrating "
        "serial M&A compounding capability",
        "Global laboratory supply chain scale — Fisher Scientific distribution "
        "serves 300,000+ customers with next-day delivery of 750,000+ lab products, "
        "creating unmatched distribution breadth",
    ],
    business_model_keywords=[
        "TMO", "Thermo Fisher", "life science tools", "reagent", "consumable",
        "biopharma CMO", "CRO", "mass spectrometry", "chromatography",
        "Fisher Scientific", "PCR", "cell culture", "P/E", "EV/EBITDA",
        "biomanufacturing", "Patheon",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="PFE",
    company_name="Pfizer Inc.",
    business_model=(
        "Pfizer is a global pharmaceutical company with a portfolio spanning "
        "oncology (Ibrance, Xtandi partnership, Lorbrena), vaccines (Prevnar, "
        "Comirnaty), antivirals (Paxlovid, Nirmatrelvir), hospital products, "
        "and internal medicine.  Revenue peaked in 2022 from COVID vaccine and "
        "Paxlovid sales (~$55B), then normalized sharply.  The $43B Seagen "
        "acquisition (2023) added an ADC oncology platform.  Pfizer is executing "
        "cost reduction and pipeline prioritization to offset the post-COVID "
        "revenue step-down."
    ),
    primary_revenue_drivers=[
        "Oncology (~25%) — Ibrance CDK4/6, Xtandi co-promotion, Eliquis "
        "co-ownership, and Seagen ADC portfolio (Padcev, Tukysa, Adcetris)",
        "Vaccines (~20%) — Prevnar 20 pneumococcal, Comirnaty COVID-19 vaccine "
        "(declining); Abrysvo RSV vaccine (new launch)",
        "Hospital and antivirals (~20%) — Paxlovid COVID antiviral (endemic "
        "demand), Sulperazon, Zyvox, and IV hospital products",
        "Internal medicine, rare disease, and Seagen integration (~35%)",
    ],
    recurring_revenue_sources=[
        "Branded prescription refill volume from Ibrance, Eliquis, and Prevnar "
        "commercial franchises provides recurring revenue from established products",
        "Government and hospital contracted pharmaceutical supply agreements "
        "generate institutional purchasing volume across multiple product categories",
    ],
    rate_sensitivity_note=(
        "Pfizer is not directly rate-sensitive.  P/E and EV/EBITDA on normalized "
        "post-COVID earnings are the primary valuation anchors.  The stock trades "
        "at trough multiples reflecting pipeline execution uncertainty."
    ),
    inflation_pass_through=(
        "Moderate: branded pharmaceuticals carry pricing power, partially offset "
        "by IRA Medicare negotiation and PBM rebate dynamics."
    ),
    recession_behavior=(
        "Pfizer generates stable revenue from its established pharmaceutical "
        "franchise and demonstrates resilient prescription volumes from defensive "
        "medicine categories.  However, COVID-related product demand has cyclical "
        "exposure to variant dynamics and government procurement decisions."
    ),
    major_risks=[
        "Post-COVID revenue normalization — Comirnaty and Paxlovid revenue "
        "declined from $35B+ peak to $10B+ endemic run rate; the gap must be "
        "filled by pipeline launches and Seagen integration contribution",
        "Seagen ADC integration execution — $43B acquisition requires oncology "
        "commercial execution across Padcev, Tukysa, and Adcetris ADCs; "
        "ADC market competition is intensifying from AstraZeneca and Daiichi",
        "Loss of exclusivity wave — multiple Pfizer products face LOE through "
        "2030 including Xeljanz, Vyndaqel, and elranatamab; biosimilar entries "
        "create revenue headwinds concurrent with Seagen integration costs",
        "IRA drug price negotiation — Eliquis (co-owned with BMS) is subject "
        "to Medicare price negotiation, reducing one of Pfizer's most important "
        "revenue contributors",
    ],
    valuation_style=(
        "PFE trades at 9-12x forward P/E and 8-10x EV/EBITDA on normalized "
        "earnings, near trough multiples for a large-cap pharmaceutical.  "
        "The dividend yield of 5-6% provides income support while the pipeline "
        "recovery plays out.  EV/EBITDA relative to LOE-adjusted peers is the "
        "most appropriate through-cycle metric given revenue step-down dynamics."
    ),
    key_metrics=[
        "Paxlovid and Comirnaty revenue (endemic trajectory vs. guidance)",
        "Seagen ADC portfolio sales growth (Padcev, Tukysa, Adcetris)",
        "Adjusted cost savings progress vs. $4B target",
        "Late-stage pipeline readouts (danuglipron, marstacimab, others)",
        "Dividend coverage ratio (FCF vs. dividend payout)",
    ],
    competitive_advantages=[
        "Global pharmaceutical manufacturing and distribution scale — Pfizer's "
        "100+ manufacturing sites and cold-chain logistics supported the fastest "
        "vaccine rollout in history",
        "Prevnar pneumococcal vaccine franchise — Prevnar 20 maintains market "
        "leadership in the $6B+ pneumococcal vaccine market with pediatric "
        "and adult immunization schedule entrenchment",
        "Seagen ADC oncology pipeline — Padcev, Tukysa, and Adcetris provide "
        "exposure to the high-growth ADC oncology segment with multiple approved "
        "indications and pipeline combinations",
    ],
    business_model_keywords=[
        "PFE", "Pfizer", "Paxlovid", "Comirnaty", "Prevnar", "Ibrance",
        "Eliquis", "Seagen", "ADC", "oncology", "COVID antiviral",
        "P/E", "EV/EBITDA", "LOE", "dividend yield",
    ],
    moat_type=["patent", "scale_economy"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="low",
    binary_risk_level="moderate",
))


_register(CompanyKnowledgeProfile(
    ticker="MDT",
    company_name="Medtronic plc",
    business_model=(
        "Medtronic is the world's largest pure-play medical device company, "
        "operating in Cardiovascular (~40%), Neuroscience (~25%), Medical "
        "Surgical (~25%), and Diabetes (~10%).  Products include pacemakers, "
        "defibrillators, spinal cord stimulators, robotic surgery (Hugo), "
        "insulin pumps, and surgical energy tools.  Revenue is ~55% US and "
        "~45% international.  The company is executing a multi-year efficiency "
        "program while managing the Hugo robotic surgery ramp against Intuitive's "
        "da Vinci dominance."
    ),
    primary_revenue_drivers=[
        "Cardiovascular (~40%) — cardiac rhythm management (pacemakers, ICDs, "
        "CRT), structural heart (TAVR with Evolut), coronary and peripheral "
        "vascular; relatively stable with procedure volume growth",
        "Neuroscience (~25%) — spinal cord stimulation, deep brain stimulation, "
        "ENT, and cranial neurosurgery; procedure-dependent revenue",
        "Medical Surgical (~25%) — surgical energy, monitoring, robotics (Hugo); "
        "hospital CapEx sensitive segment",
        "Diabetes (~10%) — insulin pumps (MiniMed) and CGM (Guardian sensor); "
        "facing competitive pressure from Abbott FreeStyle Libre",
    ],
    recurring_revenue_sources=[
        "Long-term hospital purchasing agreements for cardiac rhythm management "
        "systems and neuromodulation devices provide volume commitment revenue",
        "Device replacement cycle revenue from implanted cardiac pacemakers, "
        "ICDs, and spinal cord stimulators with 5-10 year battery replacement "
        "timing creates predictable upgrade volume",
    ],
    rate_sensitivity_note=(
        "Medtronic is not directly rate-sensitive.  P/E and EV/EBITDA are "
        "primary valuation anchors.  Currency translation is a material factor "
        "given 45%+ international revenue.  MDT trades at a discount to peers "
        "reflecting execution uncertainty on Hugo robotics and diabetes."
    ),
    inflation_pass_through=(
        "Moderate: medical device pricing faces hospital GPO pressure; "
        "implantable devices have more pricing power than commodity devices."
    ),
    recession_behavior=(
        "Medtronic generates stable procedure volumes from its cardiac and "
        "neuromodulation device franchises and demonstrates resilient hospital "
        "purchasing from the defensive nature of arrhythmia and pain therapy.  "
        "However, hospital CapEx for Hugo robotic surgery and large capital "
        "equipment has cyclical sensitivity to hospital budget constraints."
    ),
    major_risks=[
        "Hugo robotic surgery ramp vs. Intuitive Surgical's da Vinci — "
        "Medtronic's Hugo system needs to gain surgeon adoption in a market "
        "where Intuitive has dominant installed base and training entrenchment",
        "Diabetes segment competitive pressure — Abbott FreeStyle Libre and "
        "Dexcom are taking CGM share from Medtronic Guardian; insulin pump "
        "market is also pressured by Insulet OmniPod",
        "Hospital CapEx and elective procedure volume sensitivity — hospital "
        "staffing shortages and budget pressures delay robotic surgery capital "
        "purchases and reduce elective spine and ENT procedure volumes",
        "Currency translation headwinds — MDT's 45%+ international revenue "
        "creates USD appreciation headwinds that reduce reported earnings "
        "and complicate multi-year guidance delivery",
    ],
    valuation_style=(
        "MDT trades at 14-17x forward P/E and 12-14x EV/EBITDA, at a discount "
        "to the medical device peer group reflecting Hugo execution risk and "
        "diabetes competitive pressure.  The re-rating catalyst is Hugo "
        "procedure volume acceleration and diabetes segment stabilization.  "
        "FCF yield of 4-5% and a 3%+ dividend yield support income investors."
    ),
    key_metrics=[
        "Hugo robotic surgery procedure volume and installed base growth",
        "Cardiovascular revenue growth vs. ABBV and Edwards Lifesciences",
        "Diabetes revenue trend (MiniMed vs. Abbott Libre and Tandem)",
        "Adjusted operating margin improvement trajectory",
        "FCF conversion and dividend sustainability",
    ],
    competitive_advantages=[
        "Cardiac rhythm management leadership — pacemakers, ICDs, and CRT "
        "devices with decades of installed base, clinical evidence, and "
        "electrophysiologist training entrenchment",
        "Spinal cord stimulation and deep brain stimulation — proprietary "
        "neurostimulation technology with multi-year clinical outcome data "
        "differentiating from competition",
        "Global medical device commercial infrastructure — 90+ country presence "
        "with direct sales forces and hospital relationship depth enabling "
        "cross-selling across cardiovascular, neuro, and surgical portfolios",
    ],
    business_model_keywords=[
        "MDT", "Medtronic", "cardiac rhythm management", "pacemaker", "ICD",
        "Hugo robotic surgery", "spinal cord stimulation", "MiniMed", "TAVR",
        "Evolut", "deep brain stimulation", "P/E", "EV/EBITDA", "da Vinci",
    ],
))

# ── Consumer ──────────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="HD",
    company_name="The Home Depot, Inc.",
    business_model=(
        "Home Depot is the world's largest home improvement retailer, "
        "operating 2,300+ US stores and serving both DIY consumers and "
        "professional contractors (Pro).  Pro customers (~55% of sales) are "
        "the structural growth driver — tradespeople, property managers, and "
        "MRO contractors who spend at higher basket sizes and return more "
        "frequently.  HD Supply (sold in 2020) and Pro ecosystem investments "
        "are deepening the professional relationship through credit, delivery, "
        "and job-site services."
    ),
    primary_revenue_drivers=[
        "Pro contractor revenue (~55%) — licensed trades (plumbers, electricians, "
        "painters) and property managers purchasing lumber, fixtures, MRO, and "
        "installation materials; Pro ARPU 3-5x higher than DIY customers",
        "DIY consumer (~45%) — home repair, lawn and garden, paint, appliances; "
        "discretionary renovation spending is housing-market sensitive",
        "Interconnected (digital + stores) — ~15% of sales initiated online; "
        "buy-online-pickup-in-store and same-day delivery for Pro accounts",
    ],
    recurring_revenue_sources=[
        "Pro Xtra loyalty membership program drives recurring professional "
        "contractor purchasing through volume discounts and job lot quantity pricing",
        "Contractor and property manager maintenance supply purchasing for "
        "repair-and-replace and preventive upkeep drives repeat basket transactions",
        "Home installation service contract revenue from kitchen, bath, "
        "flooring, and roofing program installations in existing homes",
        "HD Pro subscription account relationships with commercial customers "
        "generate multi-location procurement volume and loyalty",
    ],
    rate_sensitivity_note=(
        "Home Depot is meaningfully rate-sensitive — higher mortgage rates "
        "suppress existing home turnover, which is the primary demand driver "
        "for home improvement spending.  The 'lock-in effect' (homeowners "
        "staying put rather than selling) temporarily supports repair spend "
        "but reduces renovation appetite.  EV/EBITDA and P/E are the anchors."
    ),
    inflation_pass_through=(
        "Good: lumber, building materials, and branded product pricing "
        "is market-driven; HD passes commodity inflation through prices "
        "and benefits from nominal pricing on lumber super-cycles."
    ),
    recession_behavior=(
        "Home Depot's home maintenance and repair spending is resilient as "
        "homeowners maintain essential property upkeep regardless of the "
        "economic cycle.  Pro contractor demand is stable driven by repair "
        "and remodel activity.  HD's MRO supplies are defensive must-replace "
        "categories.  Secular aging of the US housing stock supports replacement "
        "demand with mission-critical plumbing, electrical, and HVAC needs."
    ),
    major_risks=[
        "Housing market slowdown — existing home sales below 4M units "
        "suppress renovation project initiation; Fed rate hikes 2022-24 "
        "created the longest US housing market freeze in modern history",
        "Consumer spending contraction — DIY discretionary renovation "
        "spending (kitchen/bath remodels, large projects) declines "
        "materially in consumer uncertainty environments",
        "Lowe's competitive pressure — LOW is a direct format competitor "
        "with a comparable Pro push; geographic and format competition "
        "limits HD's pricing power in overlapping markets",
        "Commodity input cost volatility — lumber and building materials "
        "deflation reduces transaction values and comps even on flat unit volumes",
    ],
    valuation_style=(
        "HD trades at 22-28x forward P/E and 16-20x EV/EBITDA, at a premium "
        "to Lowe's reflecting Pro ecosystem depth and execution consistency.  "
        "The investment thesis requires housing market normalization — each "
        "200bps decline in the 30-year mortgage rate adds 500K+ existing home "
        "sales and an estimated $1-2B in incremental HD revenue.  "
        "FCF yield of 2-3% supports a growing dividend and buyback program."
    ),
    key_metrics=[
        "Comparable-store sales growth (overall and Pro vs. DIY)",
        "Average ticket and transactions per store",
        "Pro customer mix as % of total sales",
        "US existing home sales (leading demand indicator)",
        "Operating leverage (margin expansion at positive comp)",
    ],
    competitive_advantages=[
        "Scale purchasing power — HD's $160B+ revenue provides the lowest "
        "vendor cost-of-goods across every building material and tool category, "
        "enabling everyday-low-pricing and category leadership",
        "Pro ecosystem depth — Pro Xtra loyalty, dedicated Pro sales desk, "
        "job-site delivery, tool rental, and volume pricing create multi-touch "
        "switching costs for professional contractors at scale",
        "Private label product mix — HDX, Husky, Glacier Bay, and Vigoro "
        "brands command premium margins while providing HD exclusive SKUs "
        "unavailable at competing home improvement retailers",
        "Supply chain and distribution infrastructure — 25+ distribution "
        "centers and direct-to-job-site delivery for Pro orders enable "
        "same-day and next-day fulfillment at store footprint scale",
        "Store network density and brand equity — 2,300+ US stores within "
        "10 miles of ~90% of US households, creating unmatched convenience "
        "for repair and maintenance urgency purchasing",
    ],
    business_model_keywords=[
        "HD", "Home Depot", "Pro Xtra", "Pro contractor", "MRO",
        "home improvement", "repair and remodel", "lumber", "building materials",
        "housing market", "Lowe's", "P/E", "EV/EBITDA", "existing home sales",
        "FCF yield", "tool rental",
    ],
    moat_type=["scale_economy", "brand"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))


_register(CompanyKnowledgeProfile(
    ticker="MCD",
    company_name="McDonald's Corporation",
    business_model=(
        "McDonald's is the world's largest fast food franchisor with 40,000+ "
        "restaurants in 100+ countries, approximately 95% franchised.  Revenue "
        "comes from royalties and rents from franchisees (~65%) and "
        "company-operated restaurant sales (~35%).  The franchise model generates "
        "high-margin, asset-light royalty income while franchisees bear food "
        "cost, labor, and capital investment risk.  Digital ordering and "
        "loyalty (MyMcDonald's Rewards) is a strategic investment to drive "
        "frequency and personalized offers."
    ),
    primary_revenue_drivers=[
        "Franchise revenues (~65%) — royalties (% of franchisee system sales) "
        "and rent from franchised restaurant properties; high-margin, recurring",
        "Company-operated restaurant sales (~35%) — fully owned locations "
        "in select markets; more volatile with food cost and labor dynamics",
        "International growth — 70%+ of restaurants outside the US; "
        "IOM (International Operated Markets) and IDL segments provide "
        "geographic diversification across Europe, APAC, and LatAm",
    ],
    recurring_revenue_sources=[
        "Franchise royalty fee income from global franchisee system sales "
        "generates recurring, asset-light revenue tied to restaurant traffic",
        "Long-term rent income from franchised restaurant properties "
        "owned by McDonald's provides contracted lease revenue",
    ],
    rate_sensitivity_note=(
        "McDonald's is moderately rate-sensitive due to $40B+ debt load "
        "used to fund its real estate model and buybacks.  Rising rates "
        "increase interest expense and compress the EV/EBITDA multiple.  "
        "P/E and FCF yield are primary valuation anchors."
    ),
    inflation_pass_through=(
        "Good: franchisee-level menu price increases pass food and labor "
        "inflation to consumers; McDonald's royalties are % of system sales "
        "and therefore benefit from nominal price increases."
    ),
    recession_behavior=(
        "McDonald's franchise royalty income is stable across consumer spending "
        "cycles and demonstrates resilient traffic from value-seeking consumers "
        "trading down to quick-service dining.  However, premium-priced menu "
        "items and delivery orders have cyclical sensitivity to consumer "
        "spending patterns and competitive fast-casual alternatives."
    ),
    major_risks=[
        "Value perception and traffic headwinds — 2024 consumer pushback on "
        "fast food price increases created comparable transaction declines; "
        "McDonald's needs to balance franchisee economics with consumer "
        "affordability to restore traffic growth",
        "Franchisee profitability pressure — rising labor costs, food "
        "inflation, and equipment investments squeeze franchisee cash-on-cash "
        "returns, potentially reducing network expansion ambitions",
        "Brand reputation and food safety incidents — any system-wide food "
        "safety issue creates immediate traffic deterioration and lasting "
        "brand damage, as demonstrated by the 2024 E. coli outbreak",
        "Digital and delivery competitive intensity — Chipotle, Chick-fil-A, "
        "and delivery aggregators compete for the same consumer occasions; "
        "loyalty program ROI requires ongoing investment to maintain frequency",
    ],
    valuation_style=(
        "MCD trades at 22-28x forward P/E and 20-24x EV/EBITDA, commanding "
        "a premium for franchise model quality and global scale.  The dividend "
        "yield of 2-2.5% and consistent payout growth attract income investors.  "
        "EV/EBITDA relative to QSR peers is the most reliable cross-cycle anchor."
    ),
    key_metrics=[
        "Global comparable sales growth (US vs. IOM vs. IDL)",
        "Average unit volume (AUV) by market",
        "Digital sales as % of system sales",
        "Franchisee cash-on-cash returns",
        "Net restaurant count growth",
    ],
    competitive_advantages=[
        "Franchise royalty model — 95% franchised structure generates "
        "high-margin recurring income while franchisees absorb capital "
        "and operational risk",
        "Global brand recognition — McDonald's Golden Arches is among the "
        "most recognized brands globally, enabling rapid market entry and "
        "consumer trust",
        "Real estate portfolio — McDonald's ownership of prime restaurant "
        "locations provides rent income and embedded asset appreciation "
        "independent of food service revenues",
    ],
    business_model_keywords=[
        "MCD", "McDonald's", "franchise royalty", "QSR", "quick-service",
        "MyMcDonald's Rewards", "system sales", "IOM", "IDL", "Big Mac",
        "franchisee", "P/E", "EV/EBITDA", "same-store sales", "traffic",
    ],
    moat_type=["brand", "scale_economy", "switching_cost"],
    revenue_model="licensing",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


_register(CompanyKnowledgeProfile(
    ticker="SBUX",
    company_name="Starbucks Corporation",
    business_model=(
        "Starbucks is the world's largest premium coffeehouse chain with "
        "36,000+ stores globally, split between company-operated (~51%) and "
        "licensed (~49%).  Revenue is generated from company-operated beverage "
        "and food sales, licensed store royalties, and consumer packaged goods "
        "licensing.  The Starbucks Rewards loyalty program (34M+ active US "
        "members) drives frequency and digital ordering.  China (~18% of stores) "
        "is a high-growth but execution-challenged market."
    ),
    primary_revenue_drivers=[
        "US company-operated stores (~60% of revenue) — beverages, food, "
        "and merchandise at ~17,000 US locations; traffic and ticket "
        "driven by Rewards loyalty and customization",
        "International (~30%) — China company-operated stores and licensed "
        "stores across Japan, UK, Canada, and Southeast Asia",
        "Channel Development (~10%) — Nestlé Global Coffee Alliance royalties "
        "from Starbucks-branded products sold in grocery and foodservice",
    ],
    recurring_revenue_sources=[
        "Licensed store and royalty fee income from international licensed "
        "partner locations provides recurring asset-light revenue",
        "Repeat customer coffee purchases through Starbucks Rewards loyalty "
        "program generate high-frequency recurring store traffic",
    ],
    rate_sensitivity_note=(
        "Starbucks is not directly rate-sensitive.  P/E and EV/EBITDA are "
        "primary valuation anchors.  Highly leveraged capital structure "
        "($15B+ net debt) from aggressive buyback program limits financial "
        "flexibility and increases refinancing cost sensitivity."
    ),
    inflation_pass_through=(
        "Good: premium positioning allows menu price increases; coffee bean "
        "cost inflation is partially hedged; labor cost inflation is a "
        "challenge given barista wage increases and unionization pressure."
    ),
    recession_behavior=(
        "Starbucks generates stable loyalty-driven repeat visits from its "
        "core premium coffee customer base and demonstrates resilient revenue "
        "from habitual morning occasion purchasing.  However, premium beverage "
        "spending has cyclical sensitivity to consumer budget pressure and "
        "trade-down to home brewing and value quick-service alternatives."
    ),
    major_risks=[
        "China execution challenges — Starbucks China faced traffic declines "
        "from local competitor (Luckin Coffee) share gains, economic softness, "
        "and consumer nationalism; China revenue recovery is uncertain",
        "US traffic headwinds — 2023-24 comparable transaction declines "
        "from mobile order congestion, barista speed issues, and value "
        "perception misalignment require operational turnaround execution",
        "Unionization and labor cost pressure — Starbucks Workers United "
        "organizing campaigns increase labor cost, reduce operational flexibility, "
        "and create brand management complications",
        "Premium positioning competitive pressure — Dutch Bros, Blackrock Coffee, "
        "and QSR value coffee from McDonald's and Dunkin' compete for "
        "occasions at the $5-7 beverage price point",
    ],
    valuation_style=(
        "SBUX trades at 20-26x forward P/E and 16-19x EV/EBITDA, at a discount "
        "to historic norms reflecting traffic weakness and China uncertainty.  "
        "The investment thesis requires new CEO Brian Niccol's operational "
        "improvements to restore US comparable transaction growth and China "
        "strategic clarity.  Dividend yield of 2.5-3% provides income support."
    ),
    key_metrics=[
        "US comparable transaction growth (vs. ticket growth)",
        "China comparable sales growth and operating margin",
        "Active Rewards members and digital order % of transactions",
        "Store operating margin (US company-operated)",
        "New store openings vs. closures by market",
    ],
    competitive_advantages=[
        "Starbucks Rewards loyalty ecosystem — 34M+ active US members "
        "drive above-average visit frequency, pre-ordering, and personalized "
        "marketing that creates switching costs vs. independent coffeehouses",
        "Brand premium positioning and customization culture — Starbucks "
        "has created a beverage customization culture that drives ticket "
        "inflation and consumer attachment to the personalized drink experience",
        "Nestlé Global Coffee Alliance — $7.15B upfront from Nestlé provides "
        "CPG distribution royalties and expands Starbucks brand reach into "
        "grocery and foodservice channels without capital investment",
    ],
    business_model_keywords=[
        "SBUX", "Starbucks", "Starbucks Rewards", "loyalty", "premium coffee",
        "China", "licensed store", "Nestlé", "Brian Niccol", "comparable sales",
        "barista", "P/E", "EV/EBITDA", "mobile order", "Dutch Bros",
    ],
    moat_type=["brand", "scale_economy"],
    revenue_model="licensing",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


_register(CompanyKnowledgeProfile(
    ticker="TGT",
    company_name="Target Corporation",
    business_model=(
        "Target is a large-format general merchandise retailer operating "
        "~1,950 US stores, positioning between mass market (Walmart) and "
        "specialty retail.  ~50% of revenue is from food and essentials; "
        "~50% from discretionary categories (apparel, home, electronics, "
        "toys).  Target Circle loyalty and the RedCard (debit/credit) "
        "drive repeat visits and provide a ~5% discount funded by "
        "reduced interchange cost.  Same-day services (Drive Up, Shipt, "
        "Order Pickup) have become a competitive differentiation."
    ),
    primary_revenue_drivers=[
        "Food and essentials (~50%) — grocery, beverages, household "
        "essentials, personal care, and pharmacy; stable and traffic-driving",
        "Discretionary categories (~50%) — apparel, home furnishings, "
        "electronics, toys, beauty, and sporting goods; higher-margin "
        "but more economically sensitive",
        "Same-day fulfillment — Drive Up curbside and Shipt same-day "
        "delivery have driven incremental visit frequency from convenience-focused shoppers",
    ],
    recurring_revenue_sources=[
        "Recurring consumer staple and essential purchases from Target's "
        "food, household, and personal care categories drive repeat traffic",
        "Target Circle loyalty program repeat volume from 100M+ enrolled "
        "members generates habitual visit patterns and basket size lift",
    ],
    rate_sensitivity_note=(
        "Target is not directly rate-sensitive.  P/E and EV/EBITDA are "
        "primary valuation anchors.  Higher rates reduce housing activity "
        "which is correlated with home furnishings category spending."
    ),
    inflation_pass_through=(
        "Moderate: Target competes on price with Walmart and Amazon; "
        "aggressive margin protection during inflation required costly "
        "inventory markdowns in 2022-23 that impaired profitability."
    ),
    recession_behavior=(
        "Target generates stable same-store traffic from its everyday "
        "grocery and household essential categories and demonstrates resilient "
        "guest loyalty through its Target Circle program.  However, Target's "
        "apparel and home merchandise mix has cyclical sensitivity to "
        "consumer spending patterns and discretionary purchase timing."
    ),
    major_risks=[
        "Inventory management and merchandise execution — Target's 2022 "
        "inventory overhang required $1B+ in markdowns and drove significant "
        "margin compression; a repeat requires difficult merchandising bets",
        "Walmart and Amazon competitive pricing pressure — both competitors "
        "have structural advantages (Walmart's grocery density, Amazon's "
        "Prime ecosystem) that constrain Target's price positioning latitude",
        "Shrink and retail theft — Target has cited elevated shrink in urban "
        "stores as a margin headwind; store closures in high-shrink markets "
        "risk undermining its urban and suburban footprint strategy",
        "Discretionary category spending shifts — weakening consumer sentiment "
        "accelerates trade-down within Target's own categories and to value "
        "competitors, particularly in apparel and home decor",
    ],
    valuation_style=(
        "TGT trades at 13-17x forward P/E and 9-12x EV/EBITDA, at a "
        "discount to Walmart reflecting higher discretionary mix and "
        "margin execution uncertainty.  The investment thesis requires "
        "operating margin recovery to the 6%+ range and same-store sales "
        "growth outperformance vs. mass-market peers.  "
        "Dividend yield of 3-4% provides income support."
    ),
    key_metrics=[
        "Comparable sales growth (traffic vs. ticket)",
        "Gross margin (inventory management and shrink indicator)",
        "Operating margin vs. guidance range",
        "Same-day services penetration (Drive Up, Shipt, Order Pickup)",
        "Own-brand (private label) sales as % of total",
    ],
    competitive_advantages=[
        "Own-brand private label strength — Good & Gather, Cat & Jack, "
        "Threshold, and Brightroom provide differentiated, margin-accretive "
        "exclusive products unavailable at competitors",
        "RedCard loyalty ecosystem — 5% discount drives payment capture, "
        "reduces interchange costs, and creates habitual Target-first "
        "purchase behavior among enrolled members",
        "Same-day fulfillment model — store-as-hub Drive Up and Shipt same-day "
        "delivery provides e-commerce convenience without dedicated fulfillment "
        "center infrastructure costs",
    ],
    business_model_keywords=[
        "TGT", "Target", "Target Circle", "Drive Up", "Shipt", "RedCard",
        "private label", "Good & Gather", "general merchandise", "same-day",
        "Walmart", "Amazon", "P/E", "EV/EBITDA", "operating margin",
    ],
))

# ── Industrials ───────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="ETN",
    company_name="Eaton Corporation plc",
    business_model=(
        "Eaton is a global power management company serving electrical, "
        "aerospace, vehicle, and hydraulics markets.  The Electrical Americas "
        "and Electrical Global segments (~65% of EBIT) provide switchgear, "
        "UPS systems, circuit breakers, power distribution units, and EV "
        "charging infrastructure.  Data center power management is Eaton's "
        "fastest-growing end market.  Aerospace provides hydraulics, actuation, "
        "and fuel systems for commercial and military aircraft."
    ),
    primary_revenue_drivers=[
        "Electrical Americas (~40%) — power distribution, UPS, surge protection, "
        "and EV charging; driven by data center build-out and grid hardening",
        "Electrical Global (~25%) — industrial switchgear, building electrical, "
        "and power quality products across Europe, Asia, and Middle East",
        "Aerospace (~15%) — hydraulic actuation, fuel management, and "
        "environmental control systems for Boeing, Airbus, and defense programs",
        "Vehicle and eMobility (~20%) — powertrain components and EV "
        "charging solutions for commercial and light vehicle manufacturers",
    ],
    recurring_revenue_sources=[
        "Electrical infrastructure multi-year contract projects for data center "
        "operators, utilities, and industrial facilities provide sustained project revenue",
        "UPS system and switchgear maintenance agreements covering installed base "
        "of critical power equipment in data centers and hospitals",
        "Aerospace component service contract revenue from commercial airline "
        "and defense program overhaul and spares programs",
        "Power monitoring and analytics subscription programs for building "
        "management systems and industrial energy optimization platforms",
    ],
    rate_sensitivity_note=(
        "Eaton is not directly rate-sensitive.  EV/EBITDA and P/E are primary "
        "valuation anchors.  Data center and grid investment cycles are the "
        "key demand drivers, less sensitive to interest rates than consumer "
        "or housing markets."
    ),
    inflation_pass_through=(
        "Good: electrical components and switchgear carry pricing power "
        "from backlog dynamics and lead times; Eaton raised prices substantially "
        "in 2021-23 with limited volume impact."
    ),
    recession_behavior=(
        "Eaton's electrical infrastructure demand is mission-critical for data "
        "centers, utilities, and hospitals.  Power management systems are "
        "essential for uninterrupted operations in critical facilities.  "
        "Secular electrification tailwinds from AI data center growth, EV charging, "
        "and grid hardening provide resilient demand independent of economic cycles.  "
        "Eaton's stable backlog and aerospace aftermarket provide earnings visibility."
    ),
    major_risks=[
        "Data center CapEx cycle risk — hyperscale data center construction "
        "programs are subject to AI infrastructure spending confidence; a "
        "pullback in cloud CapEx commitments would reduce electrical backlog",
        "Utility grid investment pacing — IRA-driven transmission and grid "
        "hardening investment requires utility rate case approvals and financing; "
        "delays reduce backlog conversion timing",
        "Aerospace OEM production rate variability — Boeing and Airbus delivery "
        "rate reductions impact Eaton's aerospace systems volume; "
        "the 737 MAX production resumption and 787 ramp are key variables",
        "Competitive intensity from Schneider Electric and ABB — both European "
        "peers compete directly in switchgear and UPS; Eaton's North America "
        "market leadership faces competition in global expansion markets",
    ],
    valuation_style=(
        "ETN trades at 25-32x forward P/E and 18-22x EV/EBITDA, at a premium "
        "to industrial peers reflecting data center electrical exposure and "
        "secular electrification tailwinds.  The investment thesis requires "
        "continued AI infrastructure investment driving data center electrical "
        "backlog growth.  FCF yield of 2-3% supports dividend growth."
    ),
    key_metrics=[
        "Electrical Americas organic revenue growth and backlog",
        "Data center revenue as % of Electrical Americas",
        "Aerospace systems revenue growth vs. OEM production rates",
        "EV charging unit shipments and market share",
        "Operating margin by segment (Electrical vs. Aerospace)",
    ],
    competitive_advantages=[
        "Data center power management leadership — Eaton's UPS systems, "
        "PDUs, and row-based power distribution are the default specification "
        "for hyperscale and colocation data centers globally",
        "Electrical systems expertise and certification — Eaton's switchgear, "
        "circuit breakers, and panelboards are specified by architects and "
        "engineers for decades-long service in mission-critical installations",
        "Aerospace component certification and installed base — Eaton holds "
        "FAA/EASA certification for hydraulics, fuel, and actuation systems "
        "on commercial and military aircraft, creating multi-decade aftermarket",
        "Grid infrastructure positioning — Eaton's transformer, medium-voltage "
        "switchgear, and grid automation products are essential for utility "
        "transmission and distribution hardening programs",
        "Electrification and EV charging portfolio — Eaton's commercial EV "
        "charging infrastructure and eMobility drivetrain components position "
        "it for the multi-decade vehicle electrification transition",
    ],
    business_model_keywords=[
        "ETN", "Eaton", "power management", "UPS", "switchgear", "data center",
        "electrical infrastructure", "grid hardening", "EV charging", "aerospace",
        "Schneider Electric", "ABB", "P/E", "EV/EBITDA", "electrification",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="CAT",
    company_name="Caterpillar Inc.",
    business_model=(
        "Caterpillar is the world's largest manufacturer of construction and "
        "mining equipment, diesel and natural gas engines, industrial gas "
        "turbines, and diesel-electric locomotives.  Three segments: "
        "Construction Industries (~40%), Resource Industries/Mining (~25%), "
        "and Energy & Transportation (~35%).  Cat Financial provides equipment "
        "financing to dealers and customers.  The dealer network (3,800+ dealers) "
        "provides distribution, parts, and service coverage globally."
    ),
    primary_revenue_drivers=[
        "Construction Industries (~40%) — excavators, backhoe loaders, "
        "compact equipment for construction, infrastructure, and quarrying",
        "Resource Industries (~25%) — large mining trucks (793, 797), "
        "electric rope shovels, and underground mining equipment",
        "Energy & Transportation (~35%) — reciprocating engines for gas "
        "compression, oil and gas, marine, rail, and power generation",
    ],
    recurring_revenue_sources=[
        "Dealer network replacement part and component orders from global "
        "operating machine fleet generate recurring aftermarket revenue",
        "Cat Financial dealer and customer financing income from equipment "
        "loans and leases provides recurring fee and interest income",
    ],
    rate_sensitivity_note=(
        "Caterpillar is moderately rate-sensitive — higher rates increase "
        "Cat Financial cost of funds and reduce equipment financing affordability.  "
        "EV/EBITDA on normalized mid-cycle earnings and P/E are the primary anchors."
    ),
    inflation_pass_through=(
        "Good: Caterpillar has substantial pricing power on large mining "
        "equipment and passed 15-20%+ price increases in 2021-23 "
        "while maintaining volume."
    ),
    recession_behavior=(
        "Caterpillar generates stable aftermarket parts revenue from its "
        "global operating machine fleet and demonstrates resilient services "
        "income from dealer network maintenance activities.  However, new "
        "equipment orders have cyclical exposure to construction and mining "
        "CapEx cycles that can decline 30-40% in severe downturns."
    ),
    major_risks=[
        "Construction and mining CapEx cycle — equipment orders are highly "
        "procyclical; infrastructure spending slowdowns and commodity price "
        "declines can cause multi-quarter order cancellations and dealer "
        "inventory destocking",
        "China construction slowdown — real estate sector weakness in China "
        "has reduced excavator demand significantly; China recovery "
        "timeline remains uncertain given property market deleveraging",
        "Commodity price sensitivity — mining equipment demand is directly "
        "correlated with commodity prices (copper, gold, coal, iron ore); "
        "prolonged commodity bear markets reduce miner CapEx conviction",
        "Electrification transition — battery-electric construction and "
        "mining equipment will eventually replace diesel; Caterpillar "
        "must invest in zero-emission products while defending diesel margins",
    ],
    valuation_style=(
        "CAT trades at 16-22x forward P/E and 12-15x EV/EBITDA on mid-cycle "
        "normalized earnings, with peak-cycle P/E artificially compressed.  "
        "Mid-cycle EV/EBITDA and FCF yield are the most reliable valuation "
        "anchors.  Dividend growth history and buyback capacity support "
        "capital return to shareholders through the cycle."
    ),
    key_metrics=[
        "Order backlog by segment (Construction, Mining, Energy & Transport)",
        "Dealer inventory months of supply",
        "Services revenue as % of total (cycle resilience)",
        "OPACC (operating profit after capital charge) by segment",
        "Cat Financial portfolio quality (30-day past due rates)",
    ],
    competitive_advantages=[
        "Global dealer distribution network — 3,800+ dealers in 190+ countries "
        "provide unmatched parts availability, service coverage, and customer "
        "proximity for machine uptime support",
        "Cat Financial captive financing — provides equipment affordability "
        "to dealers and customers while generating recurring interest income "
        "and building Caterpillar's equipment ecosystem stickiness",
        "Brand and price premium — Caterpillar commands 10-20% price premiums "
        "vs. Komatsu, Deere, and Hitachi on large mining equipment due to "
        "reliability reputation and resale value",
    ],
    business_model_keywords=[
        "CAT", "Caterpillar", "excavator", "mining truck", "Cat Financial",
        "dealer network", "construction equipment", "aftermarket", "Komatsu",
        "mid-cycle", "P/E", "EV/EBITDA", "CapEx cycle", "Resource Industries",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="GE",
    company_name="GE Aerospace",
    business_model=(
        "GE Aerospace (formerly General Electric) is a pure-play jet engine "
        "manufacturer following the spinoffs of GE HealthCare (2023) and "
        "GE Vernova power and energy (2024).  GE Aerospace provides LEAP "
        "and GE9X engines for commercial aircraft, T700/T408 engines for "
        "military rotorcraft, and F110/F404 turbofans for fighter jets.  "
        "The Services segment (~70% of operating profit) includes spare parts, "
        "overhaul, and long-term shop visit billing for the 40,000+ installed "
        "commercial engine fleet — highly recurring and high-margin."
    ),
    primary_revenue_drivers=[
        "Commercial Engines (~30% of revenue) — LEAP-1A/1B for A320neo and "
        "737 MAX, GE9X for 777X; new engine deliveries tied to aircraft build rates",
        "Commercial Services (~45%) — spare parts and shop visits for installed "
        "LEAP, CF6, GE90, and CFM56 engine fleets; revenue tied to flight hours",
        "Defense Engines and Services (~25%) — T700 for Black Hawk, F110 for "
        "F-16, T408 for CH-53K; long-term government program revenue",
    ],
    recurring_revenue_sources=[
        "Commercial jet engine spare parts revenue from installed base of "
        "40,000+ LEAP, CF6, GE90, and CFM56 engines across global airlines",
        "Long-term engine shop visit billing tied to flight hours across "
        "commercial airline fleets at CFM International and GE direct accounts",
    ],
    rate_sensitivity_note=(
        "GE Aerospace is not directly rate-sensitive.  P/E and EV/EBITDA "
        "are primary valuation anchors.  Commercial airline capacity expansion "
        "drives flight hour growth and aftermarket demand."
    ),
    inflation_pass_through=(
        "Good: engine spare parts and shop visit pricing is contractually "
        "indexed to inflation and labor rates in long-term service agreements."
    ),
    recession_behavior=(
        "GE Aerospace generates stable defense engine revenue from multi-year "
        "government contracts and demonstrates resilient aftermarket services "
        "from the non-deferrable nature of engine overhauls.  However, "
        "commercial engine deliveries have cyclical exposure to airline "
        "CapEx programs and aircraft narrowbody production rates."
    ),
    major_risks=[
        "Boeing production rate risk — GE Aerospace's LEAP-1B is the sole "
        "engine on the 737 MAX; Boeing production disruptions directly "
        "reduce new engine deliveries and delay installed base growth",
        "LEAP durability and services revenue timing — higher-than-expected "
        "LEAP engine durability (fewer shop visits) delays services revenue "
        "growth relative to the installed base size",
        "CFM RISE open-fan development — the next-generation open-fan "
        "architecture requires substantial R&D investment (Safran partnership) "
        "with long-dated payback and technology execution risk",
        "Commercial aviation demand volatility — airline traffic is "
        "sensitive to recession, geopolitical events, and pandemic disruptions; "
        "flight hour reductions directly impair aftermarket revenue",
    ],
    valuation_style=(
        "GE Aerospace trades at 28-35x forward P/E and 20-25x EV/EBITDA, "
        "at a premium to defense peers reflecting commercial services mix "
        "and LEAP installed base growth.  The investment thesis centers on "
        "shop visit volume acceleration as the LEAP fleet ages into first "
        "overhaul cycles.  FCF yield of 3-4% supports capital return."
    ),
    key_metrics=[
        "Commercial engine shipments (LEAP-1A/1B and GE9X)",
        "Shop visit growth and average shop visit revenue",
        "Spare parts revenue and flight hour trends",
        "Defense engine revenue and program backlog",
        "Free cash flow conversion from earnings",
    ],
    competitive_advantages=[
        "LEAP engine installed base — 3,000+ LEAP engines in service on "
        "A320neo and 737 MAX fleets create a growing captive aftermarket "
        "for spare parts and shop visits at above-average margins",
        "GE90 and GE9X widebody dominance — the GE90 powers 100% of "
        "777 classics and the GE9X is the sole engine on the 777X, "
        "providing a captive aftermarket on the world's largest widebody fleet",
        "CFM International joint venture with Safran — the world's largest "
        "jet engine company by deliveries, combining GE and Safran technology "
        "to provide LEAP and CFM56 engines to the global narrowbody fleet",
    ],
    business_model_keywords=[
        "GE", "GE Aerospace", "LEAP engine", "GE9X", "CFM", "Safran",
        "shop visit", "aftermarket", "Boeing", "737 MAX", "A320neo",
        "T700", "defense engines", "P/E", "EV/EBITDA", "flight hours",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="LMT",
    company_name="Lockheed Martin Corporation",
    business_model=(
        "Lockheed Martin is the world's largest defense contractor by revenue, "
        "operating in Aeronautics (F-35, F-22, C-130J), Missiles and Fire "
        "Control (PAC-3, HIMARS, Javelin), Rotary and Mission Systems "
        "(Black Hawk, Sikorsky, Aegis), and Space Systems (GPS, missile "
        "defense).  Approximately 70% of revenue comes from the US government; "
        "30% from international FMS (Foreign Military Sales).  The F-35 "
        "program (~25% of revenue) is the backbone of both production and "
        "long-term sustainment revenue."
    ),
    primary_revenue_drivers=[
        "Aeronautics (~40%) — F-35 Lightning II production (100-140 aircraft/yr "
        "target) and sustainment, F-22 modernization, C-130J tanker deliveries",
        "Missiles and Fire Control (~20%) — PAC-3 Patriot interceptors, "
        "HIMARS rocket artillery, Javelin missiles; elevated demand from "
        "Ukraine conflict and global rearmament",
        "Rotary and Mission Systems (~25%) — Black Hawk, CH-53K, Sikorsky "
        "helicopters, Aegis naval combat systems, and cybersecurity programs",
        "Space Systems (~15%) — GPS III satellites, Next-Gen OPIR missile "
        "warning, ground-based missile defense, and classified programs",
    ],
    recurring_revenue_sources=[
        "US government defense program appropriations provide recurring "
        "annual funding for F-35 production, PAC-3 interceptors, and "
        "classified programs through multi-year budgeted authorizations",
        "Sustainment and modification order revenue from fielded fleets "
        "of F-35, C-130J, Black Hawk, and Aegis systems provide predictable "
        "aftermarket activity from existing defense inventories",
    ],
    rate_sensitivity_note=(
        "Lockheed Martin is not directly rate-sensitive.  P/E and EV/EBITDA "
        "are primary valuation anchors.  Defense budget politics and NATO "
        "spending commitments (2% GDP target) drive long-term demand outlook."
    ),
    inflation_pass_through=(
        "Moderate: US government cost-plus and fixed-price development "
        "contracts have different inflation exposure; FFP production "
        "contracts limit cost pass-through on mature programs."
    ),
    recession_behavior=(
        "Lockheed Martin generates stable US government revenue from "
        "multi-year defense program appropriations and demonstrates "
        "resilient international FMS order flow from NATO and allied partners.  "
        "However, defense budget authorization has cyclical dependency on "
        "congressional appropriations and continuing resolutions that can "
        "delay program starts and delivery schedules."
    ),
    major_risks=[
        "F-35 program execution and cost overruns — TR-3 software and Block "
        "4 capability delays have slowed deliveries and increased per-unit "
        "cost; failure to resolve production technical issues impairs "
        "both near-term revenue and long-run sustainment economics",
        "US defense budget pressure — debt ceiling negotiations and "
        "discretionary spending caps constrain defense topline growth; "
        "continuing resolutions prevent multi-year procurement commitments",
        "Fixed-price development contract losses — LMT's CH-53K and "
        "classified program fixed-price development contracts have generated "
        "significant charges when technical complexity exceeds initial estimates",
        "Sikorsky rotorcraft competition — Bell V-280 Valor (Textron) "
        "won the FLRAA program over Sikorsky-Boeing SB>1, reducing "
        "Lockheed's share of the US Army helicopter replacement market",
    ],
    valuation_style=(
        "LMT trades at 16-20x forward P/E and 13-16x EV/EBITDA, at a "
        "slight discount to RTX reflecting F-35 program uncertainty and "
        "lower commercial aerospace exposure.  The dividend yield of 2.5-3% "
        "and consistent buybacks support shareholder returns.  "
        "FCF yield of 5-6% is an attractive anchor for defense income investors."
    ),
    key_metrics=[
        "F-35 deliveries and TR-3 software certification progress",
        "PAC-3 and HIMARS order backlog from NATO and allied partners",
        "Total backlog (12-month and total) as a revenue coverage ratio",
        "Free cash flow conversion from earnings",
        "International FMS revenue as % of total",
    ],
    competitive_advantages=[
        "F-35 program sole-source position — Lockheed is the only F-35 "
        "manufacturer globally; once a nation operates F-35s, sustainment "
        "revenue flows to LMT for decades with no alternative supplier",
        "Aegis combat system and integrated air defense — Aegis is the "
        "US Navy's and allied navies' primary surface ship combat system "
        "with a captive multi-decade upgrade and sustainment program",
        "Missiles and fire control franchise — PAC-3 Patriot, HIMARS, "
        "Javelin, and THAAD are the core Western precision strike and air "
        "defense systems, with demand accelerating from global rearmament",
    ],
    business_model_keywords=[
        "LMT", "Lockheed Martin", "F-35", "PAC-3", "HIMARS", "Aegis",
        "Javelin", "Black Hawk", "Sikorsky", "defense contractor",
        "FMS", "sustainment", "P/E", "EV/EBITDA", "defense budget",
    ],
))

# ── Energy ────────────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="PSX",
    company_name="Phillips 66",
    business_model=(
        "Phillips 66 is a diversified downstream energy company operating "
        "refining (~60% of operating income), midstream (Phillips 66 Partners "
        "NGL fractionation and pipelines), chemicals (CPChem joint venture "
        "with Chevron), and marketing and specialties.  The NGL/midstream "
        "and CPChem segments provide fee-based and margin-resilient income "
        "streams that differentiate PSX from pure refining peers."
    ),
    primary_revenue_drivers=[
        "Refining (~55%) — 12 US and European refineries processing crude "
        "oil into gasoline, diesel, jet fuel, and petrochemicals; "
        "profitability driven by crack spreads",
        "Midstream (~20%) — NGL fractionation, pipelines, and terminal "
        "operations via DCP Midstream and WRB Refining JV",
        "Chemicals (~15%) — CPChem JV with Chevron producing ethylene, "
        "polyethylene, and specialty chemicals globally",
        "Marketing and Specialties (~10%) — branded fuel marketing and "
        "lubricant specialties",
    ],
    recurring_revenue_sources=[
        "Midstream NGL fractionation throughput fee income from pipeline "
        "and terminal capacity agreements provides contracted revenue",
        "CPChem chemical manufacturing income from capacity utilization "
        "generates recurring integrated margin contribution",
    ],
    rate_sensitivity_note=(
        "PSX is not directly rate-sensitive.  EV/EBITDA on through-cycle "
        "normalized earnings and P/E are primary anchors.  "
        "Refining margins are driven by crude spreads and product demand."
    ),
    inflation_pass_through=(
        "Good on refining: product prices pass through to consumers; "
        "moderate on chemicals and midstream where contracts limit repricing."
    ),
    recession_behavior=(
        "Phillips 66 generates stable midstream fee income from its NGL "
        "pipeline and fractionation capacity and demonstrates resilient "
        "transportation fuel demand from domestic driving activity.  However, "
        "refining crack spreads have cyclical exposure to global crude oil "
        "markets and regional product demand balances."
    ),
    major_risks=[
        "Refining margin compression — crack spreads are highly volatile "
        "and can compress to near-zero in periods of oversupply or demand "
        "weakness, eliminating refining segment earnings",
        "Refinery asset disposition and complexity management — PSX's "
        "European refinery footprint creates geographic complexity and "
        "exposure to European energy policy transitions",
        "CPChem commodity chemical cycle — ethylene and polyethylene "
        "margins are cyclical; new capacity additions (especially from "
        "the Middle East) can suppress margins for multiple years",
        "Energy transition risk — declining long-run gasoline demand from "
        "EV adoption reduces refined product demand; PSX's renewable fuels "
        "positioning (Rodeo Renewables) mitigates but doesn't eliminate this",
    ],
    valuation_style=(
        "PSX trades at 8-12x forward P/E and 6-9x EV/EBITDA on normalized "
        "mid-cycle refining margins.  The diversified model (refining + "
        "midstream + chemicals) commands a modest premium to pure refining "
        "peers.  Dividend yield of 3-4% and buybacks support capital return.  "
        "FCF yield is highly variable with crack spread cycles."
    ),
    key_metrics=[
        "Refining utilization and crack spreads (capture rate)",
        "CPChem operating rate and ethylene margin",
        "Midstream NGL pipeline throughput volumes",
        "Return on capital employed (ROCE) through the cycle",
        "Dividend coverage and buyback capacity at mid-cycle earnings",
    ],
    competitive_advantages=[
        "Diversified downstream model providing midstream and chemicals "
        "income streams that buffer pure refining margin volatility",
        "CPChem joint venture with Chevron providing integrated petrochemical "
        "capacity with global ethylene and polyethylene distribution",
        "US Gulf Coast refining complexity — PSX's Sweeny and Lake Charles "
        "refineries have high Nelson complexity indices enabling processing "
        "of discounted heavy and sour crude grades",
    ],
    business_model_keywords=[
        "PSX", "Phillips 66", "refining", "crack spread", "CPChem", "NGL",
        "midstream", "ethylene", "DCP Midstream", "Rodeo Renewables",
        "P/E", "EV/EBITDA", "downstream energy", "petrochemical",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="EOG",
    company_name="EOG Resources, Inc.",
    business_model=(
        "EOG Resources is a leading US independent E&P company focused on "
        "low-cost unconventional oil and gas development in the Permian Basin "
        "(Delaware and Midland), Eagle Ford, Utica, and Dorado (natural gas).  "
        "EOG differentiates through proprietary data analytics (EOG's 'college "
        "of petroleum engineering' culture), premium drilling inventory, and "
        "capital discipline — targeting double-premium return thresholds "
        "of 60%+ at conservative oil price assumptions."
    ),
    primary_revenue_drivers=[
        "Crude oil (~55% of revenue) — Permian and Eagle Ford production "
        "at sub-$40/bbl full-cycle breakeven; oil volumes growing mid-single digits",
        "Natural gas and NGLs (~30%) — Dorado dry gas discovery and "
        "associated gas from oil plays; Dorado is a multi-decade gas resource",
        "Crude oil differentials and marketing — EOG's own gathering, "
        "treating, and marketing infrastructure reduces differential exposure",
    ],
    recurring_revenue_sources=[
        "Crude oil production volumes from Permian and Eagle Ford unconventional "
        "wells provide recurring commodity revenue from continuous drilling programs",
        "Natural gas and NGL sales from Dorado and associated gas assets "
        "generate recurring revenue as production grows with development activity",
    ],
    rate_sensitivity_note=(
        "EOG is not directly rate-sensitive.  EV/EBITDA on mid-cycle oil prices "
        "and FCF yield are the primary valuation anchors.  "
        "Capital discipline at sub-$50 oil targets a self-funding model."
    ),
    inflation_pass_through=(
        "Limited: EOG sells at market prices; operational efficiency "
        "improvements partially offset oilfield service cost inflation."
    ),
    recession_behavior=(
        "EOG Resources generates stable production from its unconventional "
        "oil and gas assets and demonstrates resilient free cash flow from "
        "its low-cost, high-return drilling inventory.  However, realized "
        "oil and gas prices have cyclical exposure to global commodity "
        "markets, and EOG reduces drilling activity when returns fall "
        "below its premium thresholds."
    ),
    major_risks=[
        "Oil price cycle — WTI at $50/bbl compresses EOG's FCF significantly; "
        "sustained sub-$55 oil would require rig count cuts and dividend "
        "coverage pressure on the regular plus special dividend program",
        "Permian Basin depletion and inventory quality — premium Tier 1 "
        "locations are finite; as EOG moves to Tier 2 inventory, per-well "
        "returns and breakevens will gradually deteriorate",
        "Takeaway infrastructure constraints — Permian crude and gas "
        "takeaway capacity expansions are necessary to prevent basis blowouts; "
        "Waha gas hub differentials can go deeply negative in peak production periods",
        "Regulatory and environmental risk — methane regulations, produced "
        "water disposal rules, and federal lands permitting create "
        "operational and development uncertainty",
    ],
    valuation_style=(
        "EOG trades at 10-14x forward P/E and 5-7x EV/EBITDA at mid-cycle "
        "oil prices, with a total dividend yield (regular plus variable) of "
        "3-5%.  FCF yield at $75 WTI is a key investment anchor; EOG targets "
        "25-30% FCF return to shareholders.  EV/2P reserves provides a "
        "net asset valuation cross-check."
    ),
    key_metrics=[
        "Oil production growth rate vs. capital budget",
        "Well-level rate of return at flat $60/bbl WTI",
        "Premium inventory runway (remaining double-premium wells)",
        "Regular plus special dividend capacity at current oil prices",
        "Dorado natural gas reserves and development pace",
    ],
    competitive_advantages=[
        "Premium drilling inventory in Permian Basin and Eagle Ford — "
        "EOG's proprietary exploration identified high-return acreage positions "
        "with sub-$30/bbl full-cycle costs in core development areas",
        "Capital return discipline with double-premium investment threshold — "
        "EOG only drills wells returning 60%+ at $40 oil, resulting in "
        "above-peer cash returns and balance sheet strength through cycles",
        "Dorado dry gas discovery — multi-decade natural gas resource in "
        "South Texas with low development costs positioning EOG for "
        "LNG export market growth",
    ],
    business_model_keywords=[
        "EOG", "EOG Resources", "Permian Basin", "Eagle Ford", "Dorado",
        "unconventional E&P", "double-premium", "WTI", "shale", "Delaware Basin",
        "special dividend", "FCF yield", "EV/EBITDA", "natural gas",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="DVN",
    company_name="Devon Energy Corporation",
    business_model=(
        "Devon Energy is a US-focused independent E&P company operating "
        "in the Delaware Basin (Permian), Eagle Ford, Anadarko, Powder "
        "River Basin, and Williston Basin.  Devon pioneered the fixed-plus-"
        "variable dividend framework in 2021, sharing cash flow directly "
        "with shareholders in high-price environments.  Delaware Basin "
        "represents ~55% of production and is the primary growth engine."
    ),
    primary_revenue_drivers=[
        "Oil production (~65% of revenue) — Delaware Basin and Eagle Ford "
        "crude oil at competitive breakeven costs; volumes growing low-single "
        "digits on maintenance-level capital",
        "Natural gas and NGLs (~35%) — Anadarko and associated gas from "
        "oil plays; Midland Basin natural gas has Waha hub price exposure",
        "Fixed-plus-variable dividend — cash flow above fixed costs "
        "returns 10% of discretionary cash to shareholders as variable dividends",
    ],
    recurring_revenue_sources=[
        "Crude oil production revenue from Delaware Basin and Anadarko Basin "
        "assets provides recurring commodity revenue from ongoing development",
        "Fixed-plus-variable dividend payout sharing production economics "
        "with shareholders generates predictable base income at mid-cycle prices",
    ],
    rate_sensitivity_note=(
        "Devon is not directly rate-sensitive.  EV/EBITDA at mid-cycle oil "
        "and FCF yield are primary valuation anchors.  "
        "WTI at $65-70 supports the fixed dividend at maintenance production."
    ),
    inflation_pass_through=(
        "Limited: oil sells at market; operating cost inflation from oilfield "
        "services is partially offset by operational efficiency improvements."
    ),
    recession_behavior=(
        "Devon Energy generates stable oil and gas production from its "
        "Delaware and Anadarko Basin assets and demonstrates resilient cash "
        "generation from its low-breakeven cost structure.  However, realized "
        "oil prices have cyclical exposure to global demand and supply "
        "dynamics, compressing DVN's variable dividend in weak commodity environments."
    ),
    major_risks=[
        "WTI oil price sensitivity — Devon's variable dividend collapses "
        "at sub-$55 WTI; at $50 oil, the payout model provides only the "
        "fixed $0.22/quarter dividend with minimal variable component",
        "Delaware Basin acreage concentration — 55%+ of production from "
        "one basin creates geographic concentration; any infrastructure, "
        "regulatory, or operational issue has outsized impact",
        "Waha gas price exposure — associated gas from Permian production "
        "is priced at Waha hub, which can trade deeply negative in periods "
        "of takeaway constraint, impairing realized gas prices",
        "M&A integration risk — Devon's acquisition of RimRock and other "
        "bolt-on acreage requires integration without disrupting core "
        "Delaware Basin development efficiency",
    ],
    valuation_style=(
        "DVN trades at 8-12x forward P/E and 4-6x EV/EBITDA at mid-cycle "
        "oil.  Total dividend yield (fixed plus variable) of 4-7% at $75 WTI "
        "is the primary income investment anchor.  FCF yield drives the "
        "variable dividend and buyback capacity above the fixed payout."
    ),
    key_metrics=[
        "Delaware Basin oil production growth and well-level returns",
        "Total dividend payout (fixed plus variable) at current strip pricing",
        "FCF generation at $60/$70/$80 WTI scenarios",
        "Net debt reduction pace and leverage ratio",
        "Waha natural gas differential to Henry Hub",
    ],
    competitive_advantages=[
        "Delaware Basin low-cost acreage with sub-$35/bbl full-cycle "
        "breakeven on core development locations providing strong returns "
        "at mid-cycle commodity prices",
        "Fixed-plus-variable dividend framework — share of cash flow return "
        "aligns shareholders with commodity price upside and provides "
        "transparent capital return policy",
        "Scale in Anadarko and Powder River basins providing diversified "
        "production base beyond Delaware concentration",
    ],
    business_model_keywords=[
        "DVN", "Devon Energy", "Delaware Basin", "Anadarko", "Eagle Ford",
        "fixed-plus-variable dividend", "WTI", "shale E&P", "Permian",
        "variable dividend", "FCF yield", "EV/EBITDA", "Waha",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="MPC",
    company_name="Marathon Petroleum Corporation",
    business_model=(
        "Marathon Petroleum is the largest US petroleum refiner by throughput "
        "capacity (~3M bpd across 13 refineries) and a midstream MLP general "
        "partner through MPLX LP.  The Refining & Marketing segment processes "
        "crude oil into gasoline, distillates, and asphalt.  MPLX provides "
        "gathering, processing, fractionation, and transportation services "
        "with fee-based, more predictable cash flows than refining."
    ),
    primary_revenue_drivers=[
        "Refining & Marketing (~85%) — refined product sales at Midwest, "
        "Gulf Coast, and West Coast refineries; profitability depends on "
        "regional crack spreads and crude oil differentials",
        "Midstream via MPLX (~15% of operating income) — NGL gathering, "
        "fractionation, and pipeline fee income; more stable than refining",
        "Speedway (sold 2021) — retail fuel and convenience store network "
        "was divested to 7-Eleven; MPC is now a pure refining + midstream story",
    ],
    recurring_revenue_sources=[
        "Refinery throughput revenues from crude oil processing capacity "
        "at 13 US petroleum refineries serving domestic product markets",
        "MPLX midstream pipeline and storage fee income from long-term "
        "gathering, fractionation, and transportation capacity agreements",
    ],
    rate_sensitivity_note=(
        "MPC is not directly rate-sensitive.  EV/EBITDA on mid-cycle "
        "refining margins is the primary valuation anchor.  "
        "MPLX distributions provide partial yield support through the cycle."
    ),
    inflation_pass_through=(
        "Good on refining: refined product prices pass through to consumers; "
        "moderate on MPLX fee-based contracts."
    ),
    recession_behavior=(
        "Marathon Petroleum generates stable MPLX midstream fee income from "
        "its pipeline and fractionation capacity agreements and demonstrates "
        "resilient transportation fuel demand from domestic driving activity.  "
        "However, refining crack spreads have cyclical exposure to crude "
        "oil market dynamics and regional refined product supply balances."
    ),
    major_risks=[
        "Refining margin cycle — crack spreads in MPC's Midwest and Gulf "
        "Coast markets can compress sharply in periods of global product "
        "oversupply or demand destruction, eliminating refining profitability",
        "Crude oil differential exposure — MPC's Midwest refineries process "
        "WTI Midland and Canadian heavy crudes; differential narrowing reduces "
        "the feedstock advantage vs. coastal and European refiners",
        "Renewable fuel transition — California Low Carbon Fuel Standard and "
        "federal RFS mandates create compliance cost and transition risk "
        "for conventional petroleum refiners",
        "MPLX unit price risk — MPC's MPLX GP interest creates balance "
        "sheet and earnings exposure to MPLX unit price fluctuations",
    ],
    valuation_style=(
        "MPC trades at 7-11x forward P/E and 5-8x EV/EBITDA on normalized "
        "mid-cycle crack spreads.  The MPLX distribution yield and MPC's "
        "buyback capacity provide income and capital return support.  "
        "Refining mid-cycle EV/EBITDA cross-checked with MPLX GP interest "
        "provides the most consistent through-cycle valuation anchor."
    ),
    key_metrics=[
        "Refining throughput and capture rate vs. benchmark crack spreads",
        "MPLX distributable cash flow and coverage ratio",
        "Cumulative buyback capacity at current cash flow",
        "Midcontinent vs. Gulf Coast crack spread trends",
        "Renewable diesel and sustainable aviation fuel capacity investments",
    ],
    competitive_advantages=[
        "Largest US refiner scale providing procurement, logistics, and "
        "optimization advantages across 3M bpd of combined capacity",
        "MPLX midstream integration — fee-based NGL and pipeline income "
        "buffers pure refining margin volatility and provides stable cash flows",
        "Midwest refining positioning — access to discounted WTI Midland "
        "and Canadian heavy crude enhances feedstock economics vs. coastal peers",
    ],
    business_model_keywords=[
        "MPC", "Marathon Petroleum", "refining", "MPLX", "crack spread",
        "NGL", "throughput", "Midwest refining", "distillate", "gasoline",
        "P/E", "EV/EBITDA", "midstream", "Canadian crude",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="VLO",
    company_name="Valero Energy Corporation",
    business_model=(
        "Valero is the world's largest independent petroleum refiner by "
        "throughput capacity (~3.2M bpd across 15 refineries in US, Canada, "
        "and UK).  Valero's refinery network spans Gulf Coast, West Coast, "
        "Mid-Continent, and international locations.  Diamond Green Diesel "
        "(50/50 JV with Darling Ingredients) is the world's largest renewable "
        "diesel facility, providing a growing low-carbon revenue stream "
        "that differentiates VLO from pure petroleum refining peers."
    ),
    primary_revenue_drivers=[
        "Refining (~90%) — distillate, gasoline, jet fuel, and petrochemicals "
        "from complex Gulf Coast and international refineries; "
        "profitability dependent on crack spreads and crude differentials",
        "Renewable Diesel via Diamond Green (~7%) — renewable diesel produced "
        "from animal fats and vegetable oils sold under LCFS and RIN credits",
        "Ethanol (~3%) — corn ethanol production from 11 US plants generating "
        "RIN credits and commodity ethanol revenue",
    ],
    recurring_revenue_sources=[
        "Refinery throughput revenues from 15 petroleum refineries and "
        "two ethanol plants processing commodity feedstocks into finished fuels",
        "Diamond Green Diesel renewable processing fee income from "
        "continuous renewable diesel production at Port Arthur and Norco facilities",
    ],
    rate_sensitivity_note=(
        "Valero is not directly rate-sensitive.  EV/EBITDA on mid-cycle "
        "crack spreads is the primary valuation anchor.  "
        "Diamond Green Diesel adds diversification from LCFS and RIN credit values."
    ),
    inflation_pass_through=(
        "Good: refined product prices pass through energy inflation to consumers; "
        "Diamond Green renewable diesel benefits from LCFS credit prices."
    ),
    recession_behavior=(
        "Valero generates stable throughput revenue from its diverse refinery "
        "network and demonstrates resilient transportation fuel demand from "
        "domestic vehicle miles traveled.  However, global refining crack "
        "spreads have cyclical exposure to crude oil supply dynamics and "
        "regional refined product demand fluctuations."
    ),
    major_risks=[
        "Refining margin cycle — global crack spreads drove exceptional "
        "2022-23 earnings but normalized in 2024; further normalization "
        "or global recession would reduce VLO's earnings sharply",
        "LCFS and RIN credit value volatility — Diamond Green Diesel "
        "profitability depends on California LCFS credit prices and "
        "federal RIN values, which are subject to regulatory changes",
        "Energy transition risk — long-run EV adoption reduces transportation "
        "fuel demand; VLO's renewable diesel pivot mitigates but does not "
        "eliminate the risk of secular petroleum demand decline",
        "Gulf Coast hurricane and infrastructure risk — VLO's concentration "
        "in the US Gulf Coast creates geographic weather and infrastructure "
        "disruption exposure",
    ],
    valuation_style=(
        "VLO trades at 7-10x forward P/E and 5-7x EV/EBITDA on normalized "
        "mid-cycle crack spreads, near the low end of the refining peer group.  "
        "Dividend yield of 3-4% and buyback capacity at cycle earnings provide "
        "capital return.  Diamond Green Diesel provides upside to LCFS credit "
        "pricing.  EV/normalized EBITDA is the most reliable through-cycle anchor."
    ),
    key_metrics=[
        "Throughput capacity utilization and capture rate",
        "Diamond Green Diesel production volumes and blended margin",
        "Gulf Coast 3-2-1 crack spread vs. actual capture",
        "LCFS credit prices ($/tonne CO2)",
        "Capital return (dividends + buybacks) as % of FCF at mid-cycle",
    ],
    competitive_advantages=[
        "World's largest independent refiner scale — 3.2M bpd capacity "
        "provides unmatched procurement, optimization, and crude flexibility "
        "across the refining portfolio",
        "Diamond Green Diesel low-carbon positioning — world's largest "
        "renewable diesel facility provides differentiated access to "
        "LCFS credits and renewable fuel standards compliance value",
        "Gulf Coast heavy crude processing expertise — Valero's complex "
        "Gulf Coast refineries can process the widest range of cheap "
        "heavy sour crudes, providing structural feedstock advantage",
    ],
    business_model_keywords=[
        "VLO", "Valero", "refining", "crack spread", "Diamond Green Diesel",
        "renewable diesel", "LCFS", "RIN", "Gulf Coast", "throughput",
        "P/E", "EV/EBITDA", "ethanol", "mid-cycle",
    ],
))

# ── Utilities ─────────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="SRE",
    company_name="Sempra",
    business_model=(
        "Sempra is a diversified energy infrastructure company with three "
        "segments: SoCalGas (Southern California gas distribution), SDG&E "
        "(San Diego electric and gas distribution), and Sempra Infrastructure "
        "(LNG export terminals and Mexico natural gas pipelines).  Port Arthur "
        "LNG and Cameron LNG are Sempra's primary infrastructure growth "
        "drivers, positioning the company as a key US LNG export facilitator "
        "for European and Asian energy security customers."
    ),
    primary_revenue_drivers=[
        "SoCalGas and SDG&E (~55%) — regulated gas and electric distribution "
        "utility with CPUC-authorized rate of return; captive Southern California "
        "customer base",
        "Sempra Infrastructure (~30%) — LNG export terminal fee income from "
        "Port Arthur LNG and Cameron LNG; long-term offtake agreements "
        "with major energy companies",
        "Oncor Texas utility (equity investment, ~15%) — regulated electric "
        "distribution in fast-growing Texas, providing earnings growth",
    ],
    recurring_revenue_sources=[
        "SoCalGas and SDG&E CPUC-regulated rate base revenues from captive "
        "residential and commercial customers provide recurring utility earnings",
        "Sempra Infrastructure LNG export terminal fee income from long-term "
        "offtake capacity reservations at Port Arthur and Cameron LNG facilities",
    ],
    rate_sensitivity_note=(
        "Sempra is rate-sensitive: regulated utilities earn CPUC-authorized "
        "returns tied to cost of capital; rising rates increase the authorized "
        "ROE but also the discount rate applied to future earnings, compressing "
        "P/E.  LNG infrastructure provides partial rate insensitivity."
    ),
    inflation_pass_through=(
        "Good: CPUC rate cases allow cost recovery including inflation in "
        "O&M and CapEx.  LNG offtake contracts are indexed to commodity prices."
    ),
    recession_behavior=(
        "Sempra generates stable regulated utility revenues from its captive "
        "Southern California gas and electric distribution territory and "
        "demonstrates resilient LNG terminal fee income from long-term offtake "
        "commitments.  However, Sempra Infrastructure project development has "
        "cyclical sensitivity to LNG demand expectations and partner financing."
    ),
    major_risks=[
        "SoCalGas wildfire and methane liability — Southern California Gas "
        "serves the densest US natural gas distribution territory; pipeline "
        "safety incidents (Aliso Canyon 2015) created $1B+ liabilities and "
        "regulatory scrutiny that continues to affect capital program approval",
        "Port Arthur LNG development risk — the $13B+ Port Arthur LNG Phase 1 "
        "is a complex infrastructure project; cost overruns, permitting delays, "
        "or offtake counterparty credit issues could impair returns",
        "California energy policy risk — California's aggressive decarbonization "
        "policy creates long-run demand risk for SoCalGas gas distribution "
        "as the state mandates electrification of buildings and appliances",
        "Oncor regulatory risk — Texas utility earnings depend on PUCT rate "
        "decisions; storm recovery and grid hardening costs add uncertainty",
    ],
    valuation_style=(
        "SRE trades at 14-18x forward P/E and 12-15x EV/EBITDA, at a premium "
        "to pure US utilities reflecting LNG infrastructure growth optionality.  "
        "Dividend yield of 3-4% provides income support.  "
        "Regulated utility P/E is supplemented by LNG terminal NPV analysis "
        "for the infrastructure segment."
    ),
    key_metrics=[
        "SoCalGas and SDG&E authorized rate base growth",
        "Port Arthur LNG Phase 1 construction progress and offtake agreements",
        "Oncor rate base and Texas customer growth",
        "EPS growth trajectory from infrastructure segment ramp",
        "Dividend coverage ratio from operating cash flows",
    ],
    competitive_advantages=[
        "Southern California monopoly gas distribution franchise — SoCalGas "
        "is the largest US natural gas distribution utility with an irreplaceable "
        "service territory in Los Angeles and surrounding counties",
        "Port Arthur LNG export scale — Sempra's LNG export capacity positions "
        "it as a strategic US LNG infrastructure provider for European and "
        "Asian energy security diversification",
        "Oncor Texas growth exposure — equity investment in Oncor provides "
        "access to high-growth Texas electric utility earnings without "
        "direct operational risk",
    ],
    business_model_keywords=[
        "SRE", "Sempra", "SoCalGas", "SDG&E", "Port Arthur LNG", "Cameron LNG",
        "Oncor", "CPUC", "utility", "LNG export", "regulated rate base",
        "P/E", "EV/EBITDA", "dividend yield", "California",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="PCG",
    company_name="PG&E Corporation",
    business_model=(
        "PG&E Corporation is the parent of Pacific Gas and Electric Company, "
        "a regulated electric and natural gas utility serving 16 million "
        "people across 70,000 square miles in Northern and Central California.  "
        "PG&E emerged from bankruptcy in 2020 following wildfire liability "
        "from the 2017-18 Camp Fire and North Bay Fires.  The company "
        "is executing a massive grid hardening program (~$50B over 10 years) "
        "to reduce ignition risk while building out EV charging and clean "
        "energy transmission infrastructure."
    ),
    primary_revenue_drivers=[
        "Electric distribution (~65%) — CPUC-regulated rate base revenues "
        "from 5.5 million electric customers in Northern California; rate "
        "base growing rapidly from grid hardening and undergrounding",
        "Natural gas distribution (~25%) — regulated gas distribution "
        "for 4.6 million gas customers; gas distribution faces long-run "
        "electrification headwind in California",
        "Electric transmission (~10%) — FERC-regulated transmission "
        "infrastructure providing bulk power delivery",
    ],
    recurring_revenue_sources=[
        "CPUC-regulated electric distribution rate base revenues from "
        "Northern California residential and commercial customer accounts",
        "Natural gas transmission and distribution fee income from "
        "PG&E's Northern California service territory captive accounts",
    ],
    rate_sensitivity_note=(
        "PG&E is meaningfully rate-sensitive: its CPUC-authorized ROE is "
        "benchmarked to interest rates; higher rates compress P/E multiples "
        "and increase cost of equity for the large ongoing CapEx program.  "
        "The $50B grid hardening investment requires continuous external financing."
    ),
    inflation_pass_through=(
        "Good: CPUC rate cases allow capital and O&M cost recovery; "
        "wildfire insurance and undergrounding cost recovery is the "
        "key regulatory battleground."
    ),
    recession_behavior=(
        "PG&E generates stable regulated utility revenue from its captive "
        "Northern California customer base and demonstrates resilient "
        "electric and gas distribution income from the non-elective nature "
        "of energy use.  However, PG&E's capital recovery timeline has "
        "cyclical sensitivity to CPUC rate case decisions and financing conditions."
    ),
    major_risks=[
        "Wildfire liability recurrence — despite grid hardening, PG&E "
        "still faces ignition risk in high-fire-threat districts; a major "
        "wildfire caused by PG&E infrastructure could trigger catastrophic "
        "liability exceeding the California Wildfire Fund backstop",
        "CPUC rate case disallowances — California regulators routinely "
        "disallow portions of PG&E's requested rate base additions; "
        "undergrounding cost recovery is particularly contentious",
        "Financing requirement scale — PG&E's $50B+ grid hardening program "
        "requires sustained equity and debt issuance, diluting existing "
        "shareholders and increasing balance sheet leverage",
        "Gas distribution decline — California's mandated building "
        "electrification will reduce PG&E gas customers over time, "
        "requiring rate base reclassification and stranded asset risk",
    ],
    valuation_style=(
        "PCG trades at 11-15x forward P/E and 10-13x EV/EBITDA, at a "
        "discount to California utilities reflecting wildfire recurrence "
        "and financing overhang risk.  The investment thesis requires "
        "confidence in the California Wildfire Fund backstop and CPUC "
        "support for grid hardening cost recovery.  Dividend yield of 2-3%."
    ),
    key_metrics=[
        "Grid hardening capital spend (miles undergrounded per year)",
        "CPUC rate case outcomes and authorized rate base growth",
        "Wildfire ignition metrics (EPSS and outage statistics)",
        "California Wildfire Fund coverage adequacy",
        "EPS growth trajectory from rate base expansion",
    ],
    competitive_advantages=[
        "Northern California monopoly electric and gas franchise — "
        "PG&E serves the Bay Area, Silicon Valley, and Central Valley "
        "with no competitive alternative for distribution service",
        "Grid hardening capital investment program — $50B+ in grid "
        "modernization creates a multi-decade regulated rate base growth "
        "opportunity that supports EPS compounding",
        "Clean energy infrastructure positioning — PG&E's transmission "
        "infrastructure is essential for Northern California's renewable "
        "energy integration and EV charging expansion",
    ],
    business_model_keywords=[
        "PCG", "PG&E", "CPUC", "wildfire", "grid hardening", "undergrounding",
        "Northern California", "Bay Area", "California Wildfire Fund",
        "regulated utility", "P/E", "EV/EBITDA", "rate base", "electrification",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="WEC",
    company_name="WEC Energy Group, Inc.",
    business_model=(
        "WEC Energy Group is a Midwest regulated electric and natural gas "
        "utility holding company serving 4.6 million customers across "
        "Wisconsin, Illinois, Michigan, and Minnesota through subsidiaries "
        "We Energies, WPS, MG&E, and North Shore Gas.  WEC is "
        "consistently ranked among the top utility operators for regulatory "
        "relationships, operations reliability, and dividend growth, earning "
        "premium multiple vs. peers.  Clean energy investments (wind, solar, "
        "battery storage) provide rate base growth opportunity."
    ),
    primary_revenue_drivers=[
        "Wisconsin electric and gas (~70%) — We Energies and WPS serve "
        "Milwaukee and Green Bay metro areas with PSCW-regulated earnings",
        "Illinois and Michigan gas (~20%) — Peoples Energy and North Shore "
        "Gas serve Chicago area with ICC-regulated earnings",
        "Infrastructure and investment (~10%) — equity investments in "
        "American Transmission Company and wind/solar generation assets",
    ],
    recurring_revenue_sources=[
        "Regulated electric distribution revenues from Wisconsin and Illinois "
        "service territories under multi-year approved rate structures",
        "Natural gas distribution fee income from captive residential and "
        "commercial accounts across the Midwest service territory",
    ],
    rate_sensitivity_note=(
        "WEC is rate-sensitive: P/E compression occurs as bond yields "
        "rise and utility dividend yields become less competitive.  "
        "PSCW and ICC authorized returns track long-term treasury yields "
        "with a regulatory lag.  P/E of 19-23x is typical in normal "
        "rate environments."
    ),
    inflation_pass_through=(
        "Good: fuel and purchased power cost recovery clauses pass "
        "energy commodity inflation through to customers; O&M inflation "
        "is partially recovered in rate cases."
    ),
    recession_behavior=(
        "WEC Energy generates stable regulated utility revenues from its "
        "Midwest residential and commercial customer base and demonstrates "
        "resilient earnings from the PSCW and ICC regulatory compacts.  "
        "However, industrial customer electric demand has cyclical sensitivity "
        "to Midwest manufacturing activity and economic conditions."
    ),
    major_risks=[
        "Rate case lag risk — WEC's authorized returns are reset periodically; "
        "during high-inflation periods, actual costs can exceed authorized "
        "recovery levels until the next rate case is approved",
        "Clean energy transition capital requirements — Wisconsin's clean "
        "energy mandates require substantial wind, solar, and storage investment "
        "that must be financed while maintaining credit metrics",
        "Weather and demand variability — Midwest weather creates "
        "heating and cooling degree-day variability that affects quarterly "
        "earnings relative to assumptions in rate structures",
        "Gas distribution long-term risk — natural gas distribution faces "
        "secular pressure from building electrification mandates in states "
        "beyond Wisconsin's current regulatory jurisdiction",
    ],
    valuation_style=(
        "WEC trades at 18-23x forward P/E and 15-18x EV/EBITDA, at a premium "
        "to utility peers reflecting consistent earnings growth, regulatory "
        "relationship quality, and dividend growth track record.  "
        "Dividend yield of 3-4% with 7%+ EPS growth target.  "
        "P/E relative to 10-year treasury yield is the most reliable anchor."
    ),
    key_metrics=[
        "Rate base growth (% per year from clean energy and infrastructure)",
        "PSCW and ICC authorized ROE vs. earned ROE",
        "EPS growth trajectory vs. 5-7% long-term guidance",
        "Dividend growth rate (26+ consecutive years of increases)",
        "Customer growth rate (WI and IL economic activity indicator)",
    ],
    competitive_advantages=[
        "Midwest utility monopoly franchise — WEC's regulated service "
        "territories have no competitive alternative for electric and "
        "gas distribution, providing captive customer base revenue certainty",
        "Regulatory relationship quality — WEC is consistently recognized "
        "for constructive PSCW and ICC regulatory relationships, facilitating "
        "cost recovery and timely rate case resolutions",
        "Dividend growth track record — 26+ consecutive years of dividend "
        "increases demonstrates earnings quality and management capital discipline",
    ],
    business_model_keywords=[
        "WEC", "WEC Energy", "We Energies", "Wisconsin utility", "PSCW",
        "natural gas distribution", "clean energy", "P/E", "EV/EBITDA",
        "dividend growth", "regulated utility", "Midwest", "rate base",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="ED",
    company_name="Consolidated Edison, Inc.",
    business_model=(
        "Consolidated Edison is a regulated electric, gas, and steam utility "
        "serving New York City and Westchester County through Con Edison "
        "(CECONY) and Orange and Rockland Utilities.  CECONY serves "
        "3.4 million electric, 1.1 million gas, and 1,700 steam customers "
        "in New York City — the most dense and complex utility service "
        "territory in the US.  Clean Energy Businesses (sold 2023) transferred "
        "renewable development activities, refocusing ED on pure regulated utility."
    ),
    primary_revenue_drivers=[
        "CECONY electric distribution (~60%) — NYC and Westchester electric "
        "customers under NYPSC-approved multi-year rate plans; largest "
        "urban electric utility in the US",
        "CECONY gas distribution (~25%) — gas service to 1.1 million NYC "
        "and Westchester customers; vulnerable to electrification policy",
        "CECONY steam (~5%) and O&R (~10%) — Manhattan steam district "
        "heating and Orange & Rockland electric/gas service",
    ],
    recurring_revenue_sources=[
        "ConEd NYPSC-regulated electric distribution revenues from "
        "3.5 million New York City and Westchester customer accounts",
        "Natural gas distribution revenues from New York City residential "
        "and commercial accounts under multi-year rate agreements",
    ],
    rate_sensitivity_note=(
        "Con Edison is rate-sensitive: NYC regulatory environment is "
        "constructive but complex; P/E compresses meaningfully as utility "
        "yields rise relative to risk-free rates.  Con Edison's credit "
        "quality (A-rated) provides financing access across rate cycles."
    ),
    inflation_pass_through=(
        "Good: NYPSC rate cases include fuel adjustment clauses and "
        "capital cost recovery provisions that pass inflation through "
        "to customers with a regulatory lag."
    ),
    recession_behavior=(
        "Con Edison generates stable regulated utility revenues from its "
        "captive New York City customer base and demonstrates resilient "
        "earnings from the NYPSC regulatory structure.  However, "
        "commercial and industrial electric demand has cyclical sensitivity "
        "to NYC economic activity and office occupancy levels."
    ),
    major_risks=[
        "New York City regulatory policy — NYPSC rate decisions and NY "
        "Climate Leadership and Community Protection Act (CLCPA) mandates "
        "require substantial clean energy investment that must be financed "
        "while managing customer rate affordability constraints",
        "Gas distribution transition risk — New York's All-Electric Buildings "
        "Act (Local Law 154) bans new gas hookups in NYC buildings, creating "
        "long-term gas distribution customer attrition and stranded asset risk",
        "Infrastructure aging and reliability — Con Edison's NYC underground "
        "electric and steam infrastructure is among the oldest in the US; "
        "reliability incidents attract regulatory scrutiny and capital requirements",
        "Climate change physical risk — increased extreme weather events "
        "(Hurricane Sandy, heat events) create storm recovery costs and "
        "infrastructure hardening requirements beyond normal rate recovery",
    ],
    valuation_style=(
        "ED trades at 15-19x forward P/E and 13-16x EV/EBITDA, at a slight "
        "discount to premium utilities reflecting NYC regulatory complexity "
        "and gas distribution transition risk.  Dividend yield of 3.5-4.5% "
        "with a 49-year consecutive increase track record.  "
        "P/E relative to long-term treasuries is the primary valuation anchor."
    ),
    key_metrics=[
        "NYPSC rate case outcomes and authorized ROE",
        "Electric and gas capital investment program (CLCPA compliance)",
        "Gas customer attrition from NYC all-electric building mandates",
        "Storm recovery cost and regulatory lag",
        "Dividend growth rate and coverage ratio",
    ],
    competitive_advantages=[
        "New York City monopoly electric and gas franchise — CECONY "
        "is the sole electric and gas distribution provider for the "
        "world's most economically dense urban market with no competitive "
        "alternative",
        "Manhattan steam district heating — unique 105-year-old urban "
        "steam distribution network serving 1,700 Manhattan buildings "
        "with zero competitive substitute",
        "Dividend Aristocrat track record — 49+ consecutive years of "
        "dividend increases reflecting regulatory reliability and "
        "management's earnings quality commitment",
    ],
    business_model_keywords=[
        "ED", "Con Edison", "ConEd", "CECONY", "New York City utility",
        "NYPSC", "steam", "Manhattan", "Dividend Aristocrat", "CLCPA",
        "regulated utility", "P/E", "EV/EBITDA", "all-electric buildings",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="AWK",
    company_name="American Water Works Company, Inc.",
    business_model=(
        "American Water Works is the largest publicly traded US water and "
        "wastewater utility, serving 14+ million people across 24 states.  "
        "The Regulated Businesses segment (~87% of earnings) operates water "
        "and wastewater systems under state public utility commission "
        "authorizations.  The Market-Based Business segment includes "
        "military installation water and wastewater operations and home "
        "warranty services.  AWK is a pure-play water utility with a "
        "fragmented acquisition opportunity in the 50,000+ US water systems."
    ),
    primary_revenue_drivers=[
        "Regulated water utilities (~80%) — customer water and wastewater "
        "usage charges under state PUC authorized rates; revenue relatively "
        "insensitive to economic cycles",
        "Regulated wastewater (~7%) — wastewater treatment services in "
        "adjacent geographies to water distribution footprint",
        "Military installation contracts (~8%) and home warranty (~5%) — "
        "long-term government contracts for base water operations",
    ],
    recurring_revenue_sources=[
        "Regulated water and wastewater rate base revenues from 14 million "
        "customer connections across 24 regulated state service territories",
        "Military installation water and wastewater contract income from "
        "Army and Air Force base operations programs",
    ],
    rate_sensitivity_note=(
        "AWK is rate-sensitive: P/E and dividend yield are compressed by "
        "rising bond yields.  AWK's premium P/E (22-28x) is justified by "
        "above-average rate base growth from acquisitions and infrastructure "
        "investment, but compresses toward the utility peer group average "
        "in high-rate environments."
    ),
    inflation_pass_through=(
        "Good: water utility rate cases include cost recovery for "
        "infrastructure investment and O&M inflation."
    ),
    recession_behavior=(
        "American Water Works generates stable water utility revenues from "
        "its 14 million customer connection base and demonstrates resilient "
        "essential water service demand through economic cycles.  However, "
        "industrial and commercial water demand has cyclical sensitivity "
        "to manufacturing activity and commercial real estate occupancy."
    ),
    major_risks=[
        "Per-capita water use decline — conservation mandates and efficient "
        "appliances reduce residential water consumption per customer, "
        "requiring rate case increases to maintain allowed revenue levels",
        "Infrastructure investment capital requirements — aging US water "
        "infrastructure (lead service line replacement, pipe renewal) "
        "requires multi-decade capital investment financed through rate "
        "increases and equity issuance",
        "State regulatory risk — 24-state diversification reduces single-state "
        "risk, but adverse rate case outcomes in large states (NJ, PA, MO) "
        "create meaningful earnings headwinds",
        "Acquisition integration risk — AWK's fragmented water system "
        "acquisition strategy is central to growth; overpaying or "
        "operational underperformance on acquired systems reduces returns",
    ],
    valuation_style=(
        "AWK trades at 22-27x forward P/E and 18-22x EV/EBITDA, at a "
        "premium to regulated utility peers reflecting water utility "
        "scarcity, acquisition growth, and essential service defensiveness.  "
        "Dividend yield of 2-2.5% with 15%+ EPS growth target from "
        "rate base expansion.  P/E premium to utilities reflects growth premium."
    ),
    key_metrics=[
        "Rate base growth (organic + acquisitions per year)",
        "Allowed ROE vs. earned ROE by state",
        "Acquisition pipeline (municipal water system privatizations)",
        "Adjusted EPS growth trajectory",
        "Lead service line replacement pace (regulatory mandate compliance)",
    ],
    competitive_advantages=[
        "Largest US water utility franchise providing geographic "
        "diversification across 24 states with scale-based regulatory "
        "expertise and management depth unavailable to small utilities",
        "Fragmented acquisition opportunity — 50,000+ US community water "
        "systems are potential acquisition targets; AWK's capital and "
        "regulatory expertise enables roll-up economics",
        "Essential water service defensiveness — water is the most "
        "critical utility service with political and social protection "
        "from rate shock and service interruption",
    ],
    business_model_keywords=[
        "AWK", "American Water Works", "water utility", "wastewater",
        "regulated water", "rate base", "military installation", "PUC",
        "water privatization", "P/E", "EV/EBITDA", "lead service line",
        "dividend yield", "acquisition growth",
    ],
))

# ── Communications & Services ─────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="TMUS",
    company_name="T-Mobile US, Inc.",
    business_model=(
        "T-Mobile US is the second-largest US wireless carrier by revenue, "
        "with 120+ million customers following the Sprint merger in 2020.  "
        "T-Mobile operates a nationwide 5G network (mid-band 2.5GHz and "
        "mmWave) and competes against AT&T and Verizon as the 'Un-carrier' "
        "with simplified pricing, no-contract plans, and a customer experience "
        "focus.  Postpaid phone net adds, ARPU growth, and network quality "
        "are the primary competitive metrics."
    ),
    primary_revenue_drivers=[
        "Postpaid services (~65%) — monthly recurring ARPU from postpaid "
        "phone, tablet, and home internet customers; churn rate is key",
        "Prepaid services (~10%) — Metro by T-Mobile brand serving "
        "value-conscious consumers; stable with lower ARPU",
        "Equipment revenue (~15%) and wholesale/other (~10%) — device "
        "financing and leasing tied to postpaid customer acquisition",
    ],
    recurring_revenue_sources=[
        "Postpaid wireless subscriber monthly ARPU revenue from 120+ million "
        "customer accounts provides highly recurring service fee income",
        "Business and enterprise wireless fee income from commercial accounts "
        "and government contracts provides institutional service revenue",
    ],
    rate_sensitivity_note=(
        "T-Mobile has $70B+ net debt from the Sprint acquisition and "
        "is sensitive to refinancing cost.  P/E and EV/EBITDA are primary "
        "valuation anchors.  Free cash flow yield is the key capital return metric "
        "given TMUS's history of share buybacks funded by FCF."
    ),
    inflation_pass_through=(
        "Moderate: T-Mobile has raised prices on legacy plans, "
        "but wireless pricing is fundamentally competitive; "
        "network investment inflation is a cost headwind."
    ),
    recession_behavior=(
        "T-Mobile generates stable postpaid subscriber revenue from its "
        "nationwide wireless network and demonstrates resilient ARPU from "
        "its Un-carrier pricing positioning.  However, prepaid customer "
        "mix and device financing volumes have cyclical sensitivity to "
        "consumer spending confidence and wireless competitive pricing dynamics."
    ),
    major_risks=[
        "Wireless market saturation — US wireless penetration is near 100%; "
        "growth requires share gains from AT&T and Verizon rather than "
        "new customer additions, intensifying competitive pricing pressure",
        "5G home internet cannibalization of cable — T-Mobile's FWA "
        "home internet growth attacks cable operators, potentially "
        "triggering aggressive cable wireless response via MVNO pricing",
        "Sprint integration legacy costs — Sprint network shutdown complete "
        "but legacy IT systems, real estate, and workforce cost "
        "synergies are still being realized",
        "ARPU growth sustainability — T-Mobile's postpaid ARPU is below "
        "AT&T and Verizon; price increases to close the gap risk "
        "churn to lower-cost alternatives",
    ],
    valuation_style=(
        "TMUS trades at 18-23x forward P/E and 8-10x EV/EBITDA, at a "
        "premium to VZ and T reflecting superior growth and network quality.  "
        "FCF yield of 4-6% and buyback program are the primary capital return "
        "anchors.  EV/EBITDA relative to cable and wireline peers provides "
        "cross-sector valuation context."
    ),
    key_metrics=[
        "Postpaid net customer additions (phone vs. home internet)",
        "Postpaid phone ARPU growth (vs. AT&T and Verizon)",
        "Postpaid phone churn rate",
        "Free cash flow per share and buyback capacity",
        "5G mid-band network coverage vs. AT&T and Verizon",
    ],
    competitive_advantages=[
        "Mid-band 5G spectrum holdings — TMUS's 2.5GHz mid-band spectrum "
        "from Sprint acquisition is the most valuable 5G spectrum asset "
        "in the US, providing nationwide coverage and capacity advantages",
        "Nationwide 5G network coverage quality — third-party metrics "
        "consistently rate T-Mobile's 5G network fastest and most available "
        "in the US, supporting subscriber acquisition and retention",
        "Un-carrier brand and customer experience positioning — simplified "
        "pricing, no-term contracts, and Magenta customer service create "
        "above-average satisfaction and below-average postpaid churn",
    ],
    business_model_keywords=[
        "TMUS", "T-Mobile", "5G", "postpaid", "ARPU", "Un-carrier",
        "Sprint merger", "mid-band spectrum", "FWA home internet", "Metro",
        "AT&T", "Verizon", "P/E", "EV/EBITDA", "FCF yield",
    ],
))

# ── Real Estate ───────────────────────────────────────────────────────────────

_register(CompanyKnowledgeProfile(
    ticker="PSA",
    company_name="Public Storage",
    business_model=(
        "Public Storage is the world's largest self-storage REIT, operating "
        "3,000+ storage facilities with 216M+ sq ft of rentable space across "
        "the US and Europe (Shurgard).  The self-storage model is operationally "
        "simple — month-to-month rental agreements, minimal tenant improvement "
        "capital, and high operating leverage — generating above-average "
        "REIT margins.  PSA's brand, pricing technology (dynamic pricing "
        "algorithms), and digital marketing leadership differentiate it from "
        "local self-storage operators."
    ),
    primary_revenue_drivers=[
        "US self-storage (~85%) — month-to-month rentals from residential "
        "and small business customers; demand tied to life events (moving, "
        "downsizing, divorce, military deployment) more than economic cycle",
        "Shurgard Europe (~12%) — PSA's European self-storage JV with "
        "200+ properties in Western Europe, particularly UK and France",
        "Tenant insurance and ancillary revenue (~3%) — protection programs "
        "and merchandise (locks, boxes) sold at point of rental",
    ],
    recurring_revenue_sources=[
        "Month-to-month self-storage rental income from 3,000+ facilities "
        "provides recurring revenue from the broad US consumer and SMB base",
        "Ancillary tenant protection program revenue from enrolled customers "
        "provides repeating fee income alongside monthly rental payments",
    ],
    rate_sensitivity_note=(
        "Public Storage is rate-sensitive: REIT multiples compress with "
        "rising interest rates; PSA's floating-rate debt exposure adds "
        "direct cost sensitivity.  AFFO yield and P/FFO are the primary anchors."
    ),
    inflation_pass_through=(
        "Excellent: self-storage monthly rents reset on notice (30-60 days); "
        "PSA can raise in-place rents to market pricing rapidly, "
        "providing strong near-term inflation pass-through."
    ),
    recession_behavior=(
        "Public Storage generates stable self-storage rental income from "
        "life-event-driven consumer demand and demonstrates resilient occupancy "
        "across economic cycles.  However, self-storage new supply development "
        "and pricing competition have cyclical sensitivity to construction "
        "activity and consumer household formation trends."
    ),
    major_risks=[
        "New self-storage supply — development of new self-storage facilities "
        "in PSA's key markets (Sun Belt, suburban metros) creates occupancy "
        "and rate pressure that takes 18-24 months to absorb",
        "Oversaturation in core markets — PSA's strongest markets (LA, Miami, "
        "Houston) attracted aggressive new supply in 2019-23; occupancy "
        "recovery from supply peaks takes multiple years",
        "Revenue management technology commoditization — PSA's pricing "
        "algorithm advantage may be replicated by Extra Space, CubeSmart, "
        "and Life Storage, reducing the pricing-tech moat",
        "Interest rate impact on AFFO multiple — rising rates compress "
        "the AFFO multiple PSA commands; at 5%+ 10-year yields, "
        "AFFO yield expansion reduces REIT P/AFFO multiples",
    ],
    valuation_style=(
        "PSA trades at 20-26x forward AFFO and a 3-4% AFFO yield, "
        "at a premium to self-storage peers reflecting brand, scale, "
        "and pricing technology leadership.  AFFO per share growth of "
        "5-8% annually supports the premium multiple.  Cap rate of "
        "4.5-5.5% for self-storage assets underpins NAV-based valuation."
    ),
    key_metrics=[
        "Same-store revenue growth (occupancy x rate per sq ft)",
        "In-place rate vs. street rate (pricing power indicator)",
        "Occupancy trend in top 10 markets",
        "Development pipeline (new supply threat indicator)",
        "AFFO per share growth and payout ratio",
    ],
    competitive_advantages=[
        "Largest self-storage REIT scale — 3,000+ US facilities providing "
        "national brand recognition, digital marketing reach, and "
        "institutional capital access unmatched by regional operators",
        "Digital marketing and pricing technology leadership — PSA's "
        "dynamic pricing algorithms and online rental conversion capability "
        "drive above-average revenue per sq ft vs. local operators",
        "Shurgard European partnership and brand — co-ownership of European "
        "self-storage market leader provides geographic diversification "
        "and early-stage European market consolidation exposure",
    ],
    business_model_keywords=[
        "PSA", "Public Storage", "self-storage", "REIT", "Shurgard",
        "month-to-month", "AFFO", "FFO", "occupancy", "same-store revenue",
        "storage rental", "dynamic pricing", "P/AFFO", "cap rate",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="EQR",
    company_name="Equity Residential",
    business_model=(
        "Equity Residential is a leading apartment REIT owning and operating "
        "80,000+ apartment units in high-barrier coastal markets: Boston, "
        "New York, Washington DC, Seattle, San Francisco, Southern California, "
        "Denver, and Austin.  Sam Zell-founded, EQR targets affluent renters "
        "(household income $150K+) in supply-constrained urban and suburban "
        "markets where new apartment construction is limited by zoning, "
        "permitting, and construction costs."
    ),
    primary_revenue_drivers=[
        "Apartment rental income (~95%) — monthly rent from 80,000+ units "
        "in coastal gateway markets; rent growth tied to employment and "
        "housing affordability dynamics in each market",
        "Non-residential and ancillary income (~5%) — parking, storage, "
        "pet fees, package services, and commercial ground floor leases",
        "Development and repositioning — EQR develops and redevelops "
        "properties in its target markets to add NAV-accretive units",
    ],
    recurring_revenue_sources=[
        "Apartment rental income from 80,000+ units in coastal gateway "
        "markets provides recurring monthly residential lease revenue",
        "Ancillary resident income from parking, storage, pet fees, "
        "and amenity services generates repeating supplemental revenue",
    ],
    rate_sensitivity_note=(
        "EQR is rate-sensitive: REIT multiples compress with rising rates; "
        "EQR's coastal market positioning reduces somewhat vs. Sun Belt "
        "REIT peers.  AFFO yield and P/FFO are the primary valuation anchors."
    ),
    inflation_pass_through=(
        "Good: coastal apartment rents are market-driven without rent control "
        "in most EQR jurisdictions; inflation drives wage growth supporting "
        "above-CPI rent increases in high-demand markets."
    ),
    recession_behavior=(
        "Equity Residential generates stable apartment rental income from "
        "its high-income coastal renter base and demonstrates resilient "
        "occupancy in supply-constrained gateway markets.  However, "
        "coastal office employment and tech sector layoffs have cyclical "
        "sensitivity that can impair apartment demand in SF, Seattle, and NYC."
    ),
    major_risks=[
        "Coastal market rent control expansion — San Francisco, New York, "
        "and Los Angeles have implemented or expanded rent stabilization "
        "ordinances that limit EQR's ability to achieve market-rate rent "
        "increases on occupied units",
        "Tech sector and coastal employment sensitivity — EQR's San "
        "Francisco and Seattle markets are highly dependent on tech "
        "employment; tech layoffs in 2022-23 created negative net absorption",
        "Multifamily supply in Sun Belt markets — EQR's expansion to "
        "Austin and Denver exposed it to markets with heavy new apartment "
        "supply, pressuring occupancy and rent growth",
        "Remote work structural impact — reduced office utilization may "
        "structurally reduce demand for urban apartments in gateway "
        "cities relative to pre-COVID norms",
    ],
    valuation_style=(
        "EQR trades at 18-24x forward AFFO and a 3.5-4.5% AFFO yield, "
        "at a modest premium to apartment peers reflecting coastal market "
        "quality.  AFFO per share growth of 5-8% and NOI margin above 65% "
        "support the multiple.  Cap rate of 4-5% for coastal apartments "
        "provides NAV cross-check."
    ),
    key_metrics=[
        "Same-store revenue growth (rent per unit x occupancy)",
        "Net absorption by market (demand vs. new supply)",
        "Renewal rent growth vs. new lease spreads",
        "AFFO per share growth and payout ratio",
        "Development pipeline completion and lease-up timeline",
    ],
    competitive_advantages=[
        "Coastal gateway market positioning in supply-constrained "
        "urban and suburban markets where zoning and permitting limit "
        "new apartment construction, protecting EQR's pricing power",
        "High-income renter demographic ($150K+ household income) "
        "providing above-average ability to absorb rent increases "
        "and below-average vacancy sensitivity to economic stress",
        "Scale property management and technology — EQR's centralized "
        "property management and leasing technology provides operating "
        "leverage on 80,000 units",
    ],
    business_model_keywords=[
        "EQR", "Equity Residential", "apartment REIT", "multifamily",
        "coastal market", "AFFO", "FFO", "occupancy", "same-store NOI",
        "Boston", "New York", "Seattle", "San Francisco", "P/AFFO",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="VICI",
    company_name="VICI Properties Inc.",
    business_model=(
        "VICI Properties is the largest US experiential REIT, owning "
        "50+ gaming and hospitality properties including Caesars Palace, "
        "MGM Grand, The Venetian, and Mandalay Bay.  VICI operates exclusively "
        "as a landlord through triple-net leases with casino operators (Caesars "
        "and MGM as anchor tenants), with 100% rent coverage and CPI-linked "
        "annual rent escalators.  VICI has been an S&P 500 constituent since "
        "2022 and has never missed a rent payment since formation in 2017."
    ),
    primary_revenue_drivers=[
        "Casino and gaming property rental income (~90%) — triple-net "
        "lease rent from Caesars Entertainment (~45%) and MGM Resorts (~40%); "
        "leases have 15-35 year initial terms with extension options",
        "Golf and experiential properties (~7%) — Chelsea Piers, Cabot "
        "golf resorts, and bowling venues diversifying beyond gaming",
        "Loan and investment income (~3%) — bridge loans to experiential "
        "real estate operators pending acquisition",
    ],
    recurring_revenue_sources=[
        "Long-term casino property triple-net lease income from Caesars "
        "and MGM provides contractual, CPI-indexed rent with 100% coverage",
        "Gaming REIT base rent escalations tied to CPI and fixed "
        "annual rent step-ups generate predictable rent growth",
    ],
    rate_sensitivity_note=(
        "VICI is rate-sensitive: net lease REITs with long-duration leases "
        "are bond proxies; rising rates compress P/AFFO multiples.  "
        "AFFO yield of 5-6.5% is the primary investment anchor."
    ),
    inflation_pass_through=(
        "Good: VICI's master lease agreements include CPI-linked rent "
        "escalators (typically 2% floor with CPI cap) providing "
        "partial inflation pass-through on in-place rents."
    ),
    recession_behavior=(
        "VICI Properties generates stable triple-net lease rental income "
        "from Caesars and MGM master lease agreements and demonstrates "
        "resilient and defensive rent collection through economic cycles from "
        "investment-grade tenants.  However, gaming operator revenues have "
        "cyclical exposure to consumer entertainment spending and travel patterns."
    ),
    major_risks=[
        "Tenant concentration risk — Caesars Entertainment and MGM together "
        "represent ~85% of VICI revenue; a financial distress event at "
        "either tenant would create significant rent coverage pressure",
        "Gaming industry disruption from online gambling — iGaming and "
        "online sports betting growth could structurally reduce physical "
        "casino visitation over time, impairing tenant rent coverage ratios",
        "REIT leverage and interest rate sensitivity — VICI's 5.5-6.5x "
        "Net Debt/EBITDA leverage is elevated vs. net lease peers; "
        "refinancing at higher rates increases interest expense materially",
        "Experiential diversification execution risk — VICI's non-gaming "
        "experiential acquisitions (golf, bowling) are smaller-scale and "
        "require operating expertise beyond pure casino landlord skills",
    ],
    valuation_style=(
        "VICI trades at 14-18x forward AFFO and an AFFO yield of 5-6%, "
        "at a slight discount to O (Realty Income) reflecting gaming "
        "tenant concentration.  CPI rent escalators and 100% rent "
        "collection history justify a premium vs. other casino REITs.  "
        "Cap rate of 5.5-6.5% for Las Vegas Strip assets provides NAV cross-check."
    ),
    key_metrics=[
        "Rent coverage ratio by master lease (Caesars and MGM)",
        "AFFO per share growth (rent escalator contribution)",
        "Experiential non-gaming asset acquisition pipeline",
        "Net Debt/EBITDA and debt maturity profile",
        "Tenant gaming revenue health (Las Vegas Strip and regional)",
    ],
    competitive_advantages=[
        "Irreplaceable Las Vegas Strip casino properties — Caesars Palace, "
        "MGM Grand, and The Venetian are among the most recognized "
        "hotel-casino assets in the world with no substitution possibility",
        "Triple-net lease structure with investment-grade tenants — "
        "100% NNN leases with Caesars and MGM provide operating cost "
        "insulation and long-term rent visibility with CPI escalators",
        "Blue-chip gaming operator tenant base — Caesars and MGM are "
        "investment-grade rated, publicly accountable tenants with "
        "100% rent coverage and contractual escalation commitments",
    ],
    business_model_keywords=[
        "VICI", "VICI Properties", "gaming REIT", "Caesars", "MGM",
        "Las Vegas Strip", "triple-net lease", "AFFO", "FFO",
        "casino property", "CPI escalator", "P/AFFO", "cap rate",
        "experiential REIT", "Caesars Palace",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="WELL",
    company_name="Welltower Inc.",
    business_model=(
        "Welltower is the largest healthcare REIT and largest owner of "
        "senior housing and outpatient medical properties globally.  Three "
        "segments: Senior Housing Operating (SHOP, ~55% of NOI), Senior "
        "Housing Triple-Net (~15%), and Outpatient Medical (15%) and "
        "Health Systems (~15%).  SHOP properties are operated in a "
        "revenue-sharing joint venture structure where Welltower retains "
        "operating upside from aging demographic demand and occupancy recovery."
    ),
    primary_revenue_drivers=[
        "Senior Housing Operating (SHOP, ~55%) — assisted living, "
        "independent living, and memory care communities operated with "
        "management partners; occupancy and rate drive NOI growth",
        "Outpatient Medical (~20%) — medical office buildings and outpatient "
        "surgery centers leased to health systems and physician groups",
        "Senior Housing Triple-Net (~15%) and Health Systems (~10%) — "
        "long-term leased senior housing and hospital properties",
    ],
    recurring_revenue_sources=[
        "Senior housing operating portfolio NOI from assisted living "
        "and independent living communities provides recurring occupancy-based revenue",
        "Outpatient medical building and long-term care lease income "
        "from healthcare operators provides contracted recurring rental revenue",
    ],
    rate_sensitivity_note=(
        "Welltower is rate-sensitive: REIT multiples compress with rising "
        "rates; WELL's SHOP growth story partially offsets rate sensitivity "
        "with above-average AFFO growth.  AFFO yield and P/AFFO are the "
        "primary valuation anchors."
    ),
    inflation_pass_through=(
        "Good in SHOP: senior housing rental rates are market-driven "
        "and can be raised annually; labor inflation is the key cost challenge "
        "given senior housing's labor-intensive care model."
    ),
    recession_behavior=(
        "Welltower generates stable outpatient medical building revenue "
        "from long-term healthcare operator leases and demonstrates resilient "
        "SHOP demand from the non-discretionary nature of senior housing "
        "placement decisions.  However, senior housing occupancy has cyclical "
        "sensitivity to household wealth effects and COVID-related demand "
        "disruptions."
    ),
    major_risks=[
        "Senior housing labor cost inflation — SHOP communities are labor-"
        "intensive; labor shortages and wage inflation in the 2021-23 period "
        "compressed margins materially; a repeat would impair SHOP NOI growth",
        "Senior housing oversupply in certain markets — development of new "
        "assisted living and independent living communities in Sun Belt and "
        "suburban markets can pressure occupancy recovery in WELL's portfolio",
        "Operating leverage in SHOP — the revenue-sharing SHOP structure "
        "means Welltower bears full operating cost risk (labor, food, utilities) "
        "and sees amplified EBITDA swings relative to occupancy changes",
        "Health system tenant credit risk — outpatient medical leases "
        "with regional health systems carry credit exposure to hospital "
        "operating margin pressure",
    ],
    valuation_style=(
        "WELL trades at 30-38x forward AFFO and a 2-3% AFFO yield, "
        "at a premium to REIT peers reflecting the SHOP secular growth "
        "story from aging demographics.  AFFO per share growth of 10-15% "
        "justifies the premium multiple.  Cap rate of 5.5-6.5% for senior "
        "housing properties provides NAV cross-check."
    ),
    key_metrics=[
        "SHOP same-store NOI growth (occupancy x rate)",
        "Senior housing occupancy trend vs. 2019 pre-COVID baseline",
        "SHOP labor cost per occupied unit",
        "Outpatient medical lease renewal spreads",
        "AFFO per share growth and guidance range",
    ],
    competitive_advantages=[
        "Largest senior housing REIT scale with 85,000+ senior housing "
        "and care units providing unmatched portfolio diversification, "
        "operator partnership depth, and capital market access",
        "Secular aging demographic demand — the 80+ year old population "
        "in the US is projected to double by 2040, creating structural "
        "demand growth for assisted living and memory care",
        "Operator partnership model — Welltower's deep relationships with "
        "Sunrise, Discovery, Cogir, and other senior housing operators "
        "provide management expertise and portfolio expansion capability",
    ],
    business_model_keywords=[
        "WELL", "Welltower", "senior housing", "SHOP", "assisted living",
        "independent living", "memory care", "outpatient medical", "AFFO",
        "FFO", "aging demographics", "Sunrise", "P/AFFO", "cap rate",
        "healthcare REIT",
    ],
))


_register(CompanyKnowledgeProfile(
    ticker="AMH",
    company_name="American Homes 4 Rent",
    business_model=(
        "American Homes 4 Rent is the second-largest single-family rental "
        "REIT, owning 60,000+ homes across Sun Belt and Mountain West markets "
        "including Atlanta, Phoenix, Dallas, Charlotte, Tampa, and Nashville.  "
        "AMH operates both an acquisition/renovation strategy (buying existing "
        "homes) and a build-to-rent (BTR) strategy through its AMH Development "
        "program, constructing purpose-built rental communities with amenities "
        "targeting the suburban family renter demographic."
    ),
    primary_revenue_drivers=[
        "Single-family home rental income (~90%) — monthly rent from "
        "60,000+ homes in Sun Belt and Mountain West markets; "
        "demand driven by housing affordability and lifestyle flexibility",
        "Build-to-rent (BTR) development (~10% of growth CapEx) — AMH "
        "constructs purpose-built rental communities at 5-7% development "
        "yield vs. 4-5% acquisition cap rates",
        "Ancillary resident income — smart home technology fees, pet fees, "
        "parking, and storage generate supplemental revenue per occupied home",
    ],
    recurring_revenue_sources=[
        "Single-family home rental income from 60,000+ homes across "
        "Sun Belt and high-growth markets provides monthly residential rent",
        "Ancillary resident income from smart home technology and "
        "pet and parking fees generates repeating supplemental revenue",
    ],
    rate_sensitivity_note=(
        "AMH is rate-sensitive: REIT multiples compress with rising rates; "
        "BTR development yields also compress vs. financing costs.  "
        "AFFO yield and P/FFO are the primary valuation anchors.  "
        "High rates support single-family rental demand (reduces "
        "for-sale home affordability and drives renters to AMH)."
    ),
    inflation_pass_through=(
        "Good: single-family lease rents reset at lease renewal "
        "(typically 12-month leases); AMH can raise rents to market "
        "annually, providing good inflation pass-through in strong markets."
    ),
    recession_behavior=(
        "American Homes 4 Rent generates stable rental income from its "
        "Sun Belt single-family home portfolio and demonstrates resilient "
        "occupancy from the lifestyle flexibility demand driver for "
        "single-family renting.  However, Sun Belt multifamily supply "
        "and for-sale home price declines have cyclical sensitivity to "
        "consumer confidence and housing market conditions."
    ),
    major_risks=[
        "Sun Belt apartment supply competition — AMH's single-family "
        "homes compete with new multifamily construction in Atlanta, "
        "Phoenix, and Dallas; excess apartment supply in 2023-25 created "
        "lease rate compression in AMH's core markets",
        "Home price and acquisition yield compression — rising home prices "
        "reduce cap rates on acquired homes; AMH's BTR strategy partially "
        "offsets this by developing below market acquisition costs",
        "Regulatory risk on institutional homeownership — political "
        "opposition to institutional single-family rental ownership could "
        "result in state or federal legislation limiting investor purchases "
        "of single-family homes",
        "Property tax and insurance cost increases — Sun Belt states "
        "have experienced significant property tax reassessments and "
        "homeowner insurance premium increases, pressuring NOI margins",
    ],
    valuation_style=(
        "AMH trades at 22-28x forward AFFO and a 3-4% AFFO yield, "
        "at a premium to peer Invitation Homes reflecting BTR development "
        "capability.  AFFO per share growth of 7-10% from build-to-rent "
        "delivery and rent growth justifies the premium.  Cap rate of "
        "4.5-5.5% for Sun Belt single-family homes provides NAV support."
    ),
    key_metrics=[
        "Same-property revenue growth (rent x occupancy)",
        "Build-to-rent deliveries and projected development yield",
        "Sun Belt occupancy trend vs. new apartment supply",
        "AFFO per share growth and payout ratio",
        "Acquisition cap rate vs. BTR development yield spread",
    ],
    competitive_advantages=[
        "Sun Belt housing shortage positioning — AMH's 60,000+ homes "
        "in undersupplied Sun Belt markets benefit from household formation "
        "migration from coastal metros to lower-cost Sun Belt cities",
        "Build-to-rent community development capability — AMH's proprietary "
        "BTR construction program adds homes at 5-7% yields vs. 4-5% "
        "acquisition cap rates, creating above-market returns on growth",
        "Single-family rental scale and technology — AMH's centralized "
        "property management, maintenance tracking, and resident app "
        "provide operating leverage and resident satisfaction improvements",
    ],
    business_model_keywords=[
        "AMH", "American Homes 4 Rent", "single-family rental", "REIT",
        "build-to-rent", "Sun Belt", "Atlanta", "Phoenix", "Dallas",
        "BTR", "AFFO", "FFO", "P/AFFO", "cap rate", "occupancy",
    ],
))


# ── S&P Global (SPGI) ────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SPGI",
    company_name="S&P Global Inc.",
    business_model=(
        "S&P Global operates across four segments: S&P Global Ratings (credit ratings "
        "oligopoly with Moody's — issuers must obtain ratings to access public debt "
        "markets), S&P Dow Jones Indices (the S&P 500 franchise — licenses index data "
        "to ETFs, futures exchanges, and asset managers), Market Intelligence (financial "
        "data terminals and analytics competing with Bloomberg/FactSet), and Commodity "
        "Insights (Platts benchmark pricing for energy, metals, agriculture)."
    ),
    primary_revenue_drivers=[
        "Market Intelligence (~35% — subscriptions for financial data and analytics)",
        "Ratings (~30% — transaction fees on new debt issuance + annual surveillance fees)",
        "Commodity Insights (~15% — Platts benchmark pricing subscriptions)",
        "S&P Dow Jones Indices (~15% — asset-linked fees on $5T+ benchmarked AUM)",
        "Mobility (~5% — automotive data and analytics, legacy IHS Markit)",
    ],
    recurring_revenue_sources=[
        "Annual surveillance fees on rated debt (recurring as long as debt is outstanding)",
        "Market Intelligence subscriptions (multi-year enterprise contracts)",
        "Index licensing fees linked to AUM (grows with market appreciation)",
        "Platts benchmark pricing subscriptions (essential for commodity trading)",
    ],
    rate_sensitivity_note=(
        "SPGI is rate-sensitive primarily through its Ratings segment: higher rates "
        "suppress new debt issuance (fewer transactions → lower transaction fees), "
        "but refinancing waves during rate cuts boost issuance volumes.  The index "
        "business benefits from rate cuts (equity market appreciation → higher AUM → "
        "higher asset-linked fees).  Market Intelligence subscriptions are rate-insensitive."
    ),
    inflation_pass_through=(
        "Strong pricing power across all segments.  Ratings fees are set by SPGI with "
        "limited issuer pushback (issuers need the rating).  Index licensing fees grow "
        "automatically with AUM (inflation → higher nominal asset values → higher fees).  "
        "Data subscriptions have annual escalators."
    ),
    recession_behavior=(
        "Mixed: Ratings transaction revenue declines in recessions (fewer new issuances) "
        "but surveillance fees are stable (existing debt still needs ratings).  Index fees "
        "decline with AUM (market drawdowns reduce benchmarked assets).  Market Intelligence "
        "subscriptions are sticky — enterprises don't cancel data terminals in recessions.  "
        "Net: revenue dips 5-10% in severe recessions, margins compress modestly."
    ),
    major_risks=[
        "Regulatory disruption of the ratings oligopoly (SEC/EU proposals to reduce "
        "issuer-pays conflicts of interest or mandate rotation)",
        "Debt issuance volume collapse in sustained high-rate environment",
        "Bloomberg/FactSet competition eroding Market Intelligence market share",
        "Passive investing backlash reducing index licensing demand",
    ],
    valuation_style=(
        "SPGI trades at ~30-34x forward P/E, reflecting the oligopoly franchise in "
        "ratings (regulatory moat), the irreplaceable S&P 500 index brand, and "
        "high-margin recurring subscription revenue across all segments."
    ),
    key_metrics=[
        "Ratings transaction revenue (proxy for debt issuance cycle)",
        "Ratings surveillance revenue (recurring base)",
        "Index AUM-linked fees (proxy for passive investing growth)",
        "Market Intelligence organic revenue growth",
        "Operating margin (~50%+)",
        "Free cash flow conversion",
    ],
    competitive_advantages=[
        "Credit ratings oligopoly with Moody's — regulatory requirement for public debt",
        "S&P 500 index franchise — the benchmark for US equity markets, irreplaceable",
        "Platts commodity benchmark pricing — industry-standard reference prices",
        "Data network effects — more data → better analytics → more subscribers",
    ],
    business_model_keywords=[
        "ratings", "S&P 500", "index", "Platts", "Market Intelligence",
        "issuance", "surveillance", "AUM", "benchmark", "Moody's",
        "IHS Markit", "Commodity Insights", "DJIA", "credit rating",
    ],
    moat_type=["regulatory", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Moody's Corporation (MCO) ────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="MCO",
    company_name="Moody's Corporation",
    business_model=(
        "Moody's operates two segments: Moody's Investors Service (MIS — credit "
        "ratings for debt issuers, duopoly with S&P Global) and Moody's Analytics "
        "(MA — risk assessment software, data, and research subscriptions). MIS "
        "generates ~60% of revenue through transaction fees on new debt issuance "
        "and annual surveillance fees on outstanding rated debt. MA generates ~40% "
        "through recurring subscriptions for risk management tools."
    ),
    primary_revenue_drivers=[
        "MIS Transaction Revenue (~35% — fees on new debt issuance, tied to capital markets cycle)",
        "MIS Recurring Revenue (~25% — annual surveillance fees on outstanding rated debt)",
        "MA Subscription Revenue (~35% — risk analytics, data, research tools)",
        "MA Transaction Revenue (~5% — one-time project-based advisory)",
    ],
    recurring_revenue_sources=[
        "Annual surveillance fees on outstanding rated debt (recurring as long as debt exists)",
        "Moody's Analytics subscriptions (multi-year enterprise contracts, 90%+ retention)",
        "Data licensing fees (KYC, ESG, credit research databases)",
    ],
    rate_sensitivity_note=(
        "Moody's is rate-sensitive primarily through MIS transaction revenue: higher rates "
        "suppress new debt issuance (fewer transactions → lower fees). Refinancing waves "
        "during rate cuts boost issuance volumes. MA subscription revenue is rate-insensitive."
    ),
    inflation_pass_through=(
        "Strong pricing power in both segments. Rating fees are set by Moody's with limited "
        "issuer pushback — issuers need the rating to access debt markets. MA subscriptions "
        "have annual price escalators built into multi-year contracts."
    ),
    recession_behavior=(
        "Mixed: MIS transaction revenue declines sharply in recessions (fewer new issuances) "
        "but surveillance fees are stable (existing debt still needs ratings). MA subscriptions "
        "are sticky — enterprises don't cancel risk management tools during stress. Net: "
        "revenue dips 10-15% in severe recessions, recovers quickly on issuance rebound."
    ),
    major_risks=[
        "Regulatory reform of issuer-pays model (SEC/EU proposals to reduce conflicts)",
        "Sustained high-rate environment suppressing debt issuance volumes",
        "Ratings credibility risk from structured finance mispricing (2008 precedent)",
        "Competition from Fitch and emerging rating agencies in niche markets",
    ],
    valuation_style=(
        "MCO trades at ~30-35x forward P/E reflecting the ratings duopoly franchise, "
        "high-margin recurring surveillance/subscription revenue, and secular growth "
        "in private credit and ESG ratings."
    ),
    key_metrics=[
        "MIS rated issuance volume (proxy for transaction revenue)",
        "MIS surveillance revenue growth (recurring base)",
        "MA Annual Recurring Revenue (ARR) growth",
        "MA retention rate (target 90%+)",
        "Operating margin (~45-50%)",
        "Free cash flow conversion",
    ],
    competitive_advantages=[
        "Credit ratings duopoly with S&P Global — regulatory requirement for public debt",
        "90-year reputation and track record in credit assessment",
        "Moody's Analytics recurring subscription base with 90%+ retention",
        "ESG ratings franchise — fastest-growing segment leveraging core credit expertise",
    ],
    business_model_keywords=[
        "MIS", "Moody's Analytics", "credit rating", "surveillance",
        "issuance", "rated debt", "KYC", "ESG", "risk analytics",
        "Rob Fauber", "issuer-pays", "structured finance",
    ],
    moat_type=["regulatory", "data_advantage", "scale_economy"],
    revenue_model="licensing",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="none",
    binary_risk_level="none",
))


# ── Profile Expansion Phase 2 ───────────────────────────────────────────────

# ── KKR & Co. (KKR) ─────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="KKR",
    company_name="KKR & Co. Inc.",
    business_model="KKR is a global alternative asset manager with $553B+ AUM across private equity, credit, real assets, and infrastructure. Revenue comes from management fees (recurring, AUM-based), performance fees (carried interest on fund returns), and balance sheet investment income.",
    primary_revenue_drivers=["Management fees (~50% — recurring, AUM-linked)", "Carried interest (~25% — performance-based)", "Balance sheet investment income (~25%)"],
    recurring_revenue_sources=["Management fees on committed/invested capital (locked-up 7-10 year fund structures)", "Credit platform subscription-like fee streams"],
    rate_sensitivity_note="Higher rates compress deal activity (fewer LBOs) but benefit credit strategies. Net impact depends on mix.",
    inflation_pass_through="Fee structures are percentage-of-AUM based, so nominal AUM growth from inflation mechanically increases fees.",
    recession_behavior="AUM-based fees are sticky but carried interest collapses in downturns. Fundraising slows. Deal activity freezes. Revenue can decline 30-40%.",
    major_risks=["Sustained market downturn reducing AUM and carried interest", "Regulatory changes affecting private equity fund structures", "Interest rate impact on leveraged buyout deal flow"],
    valuation_style="KKR trades at 20-25x distributable earnings. Alternative asset managers valued on fee-related earnings (recurring) separately from carried interest (volatile).",
    key_metrics=["AUM growth", "Fee-related earnings (FRE)", "Distributable earnings", "Fundraising pace"],
    competitive_advantages=["Global scale across PE, credit, real assets, infrastructure", "40-year track record and institutional relationships", "Permanent capital vehicles reducing fundraising risk"],
    business_model_keywords=["AUM", "private equity", "carried interest", "management fee", "fundraising", "LBO", "credit", "infrastructure"],
    moat_type=["brand", "scale_economy"],
    revenue_model="mixed",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="moderate",
    narrative_dependence="low",
    binary_risk_level="none",
))

# ── Blackstone Inc. (BX) ────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="BX",
    company_name="Blackstone Inc.",
    business_model="Blackstone is the world's largest alternative asset manager with $1T+ AUM across real estate, private equity, credit, and hedge fund solutions. Revenue from management fees (AUM-linked) and performance allocations (carried interest).",
    primary_revenue_drivers=["Management fees (~55% — recurring, AUM-linked)", "Performance allocations (~30% — carried interest)", "Investment income (~15%)"],
    recurring_revenue_sources=["Base management fees on committed capital (locked-up fund structures)", "Perpetual capital vehicles (BREIT, BIP) with no end-of-life"],
    rate_sensitivity_note="Higher rates reduce real estate valuations (largest segment) but benefit credit strategies. Net impact is negative in rate-rising environments.",
    inflation_pass_through="AUM-based fees grow with nominal asset values. Real estate rents have inflation escalators.",
    recession_behavior="Real estate and PE valuations decline. Carried interest collapses. Fundraising slows. FRE more stable but total revenue can decline 25-35%.",
    major_risks=["Real estate downturn reducing largest segment's AUM", "BREIT redemption pressure in rising rate environments", "Regulatory changes to carried interest tax treatment"],
    valuation_style="BX trades at 25-30x FRE reflecting scale, permanent capital growth, and the secular shift from public to private markets.",
    key_metrics=["Total AUM", "Fee-related earnings (FRE)", "Distributable earnings", "Perpetual capital as % of AUM"],
    competitive_advantages=["$1T+ AUM — largest alternative manager globally", "Permanent capital vehicles reduce fundraising cyclicality", "Brand and LP relationships across sovereign wealth funds and pensions"],
    business_model_keywords=["AUM", "BREIT", "private equity", "real estate", "carried interest", "perpetual capital", "LP", "Steve Schwarzman"],
    moat_type=["brand", "scale_economy"],
    revenue_model="mixed",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="moderate",
    narrative_dependence="low",
    binary_risk_level="none",
))

# ── Intuit Inc. (INTU) ──────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="INTU",
    company_name="Intuit Inc.",
    business_model="Intuit provides financial management software: TurboTax (consumer tax), QuickBooks (small business accounting), Credit Karma (personal finance), and Mailchimp (marketing automation). Revenue is subscription-based with high retention.",
    primary_revenue_drivers=["Small Business & Self-Employed (~55% — QuickBooks, Mailchimp)", "Consumer (~25% — TurboTax)", "Credit Karma (~10%)", "ProConnect (~10% — tax professional tools)"],
    recurring_revenue_sources=["QuickBooks Online subscriptions (monthly/annual)", "TurboTax seasonal but structurally recurring (annual tax filing)", "Mailchimp subscriptions"],
    rate_sensitivity_note="Low direct rate sensitivity. Small business health is the macro transmission mechanism.",
    inflation_pass_through="Strong pricing power — annual subscription price increases of 5-10% with minimal churn.",
    recession_behavior="TurboTax is counter-cyclical (people file taxes regardless). QuickBooks is mildly cyclical (small business failures reduce subscribers). Net: revenue resilient, down 0-5% in recessions.",
    major_risks=["IRS free-file expansion reducing TurboTax addressable market", "Competition from free accounting software", "Small business formation slowdown"],
    valuation_style="INTU trades at 35-40x forward P/E reflecting the subscription model, pricing power, and tax preparation near-monopoly.",
    key_metrics=["QuickBooks Online subscribers", "ARPC (average revenue per customer)", "TurboTax units filed", "Online revenue growth"],
    competitive_advantages=["TurboTax brand dominance in consumer tax filing", "QuickBooks ecosystem lock-in for small businesses", "Data advantage from 100M+ consumer financial profiles"],
    business_model_keywords=["TurboTax", "QuickBooks", "Credit Karma", "Mailchimp", "tax filing", "small business", "ARPC", "subscriber"],
    moat_type=["brand", "switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── Shopify Inc. (SHOP) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SHOP",
    company_name="Shopify Inc.",
    business_model="Shopify provides e-commerce infrastructure: online store platform (subscriptions) and merchant services (payments, shipping, capital). Revenue split roughly 30% subscriptions / 70% merchant solutions.",
    primary_revenue_drivers=["Merchant Solutions (~70% — payments processing, Shopify Capital, shipping)", "Subscription Solutions (~30% — monthly platform fees)"],
    recurring_revenue_sources=["Monthly subscription fees", "GMV-linked payment processing fees (recurring with merchant activity)"],
    rate_sensitivity_note="Higher rates compress consumer spending and merchant growth. Shopify Capital (merchant lending) has direct rate exposure.",
    inflation_pass_through="Moderate — subscription price increases possible but merchants are price-sensitive. Payment processing take rates are under competitive pressure.",
    recession_behavior="E-commerce GMV growth slows. Merchant churn increases. Shopify Capital losses rise. Revenue growth decelerates but absolute revenue has never declined.",
    major_risks=["Amazon and BigCommerce competition for SMB merchants", "Payment processing margin compression", "Merchant churn in economic downturns"],
    valuation_style="SHOP trades at 50-70x forward P/E reflecting GMV growth, merchant ecosystem expansion, and platform optionality.",
    key_metrics=["GMV (Gross Merchandise Volume)", "MRR (Monthly Recurring Revenue)", "Merchant count", "Attach rate (merchant solutions/GMV)"],
    competitive_advantages=["Largest independent e-commerce platform by merchant count", "Ecosystem lock-in (payments + shipping + capital + POS)", "Developer ecosystem and app marketplace"],
    business_model_keywords=["GMV", "merchant", "Shopify Payments", "Shopify Capital", "POS", "e-commerce", "MRR", "attach rate"],
    moat_type=["network_effect", "switching_cost"],
    revenue_model="subscription",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="moderate",
    binary_risk_level="none",
))

# ── Snowflake Inc. (SNOW) ───────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="SNOW",
    company_name="Snowflake Inc.",
    business_model="Snowflake provides a cloud-based data platform (Data Cloud) with consumption-based pricing. Revenue is driven by compute and storage consumption on AWS, Azure, and GCP infrastructure.",
    primary_revenue_drivers=["Product revenue (~95% — consumption-based data platform)", "Professional services (~5%)"],
    recurring_revenue_sources=["Consumption-based platform usage (structurally recurring as data workloads grow)", "Committed contracts with minimum spend guarantees"],
    rate_sensitivity_note="High rate sensitivity via valuation multiple compression. Enterprise IT spending can slow in rate-rising environments.",
    inflation_pass_through="Limited — consumption-based pricing is tied to cloud infrastructure costs, not Snowflake's pricing power.",
    recession_behavior="Enterprise data spending is discretionary at the margin. Growth decelerates but existing workloads are sticky. Revenue growth slows from 50%+ to 20-30%.",
    major_risks=["AWS, Azure, GCP native data services competing directly", "Consumption-based model creates revenue volatility", "Databricks competition in data lakehouse"],
    valuation_style="SNOW trades at 15-25x forward revenue reflecting TAM expansion, net revenue retention >130%, and cloud data platform growth.",
    key_metrics=["Product revenue growth", "Net revenue retention rate", "Remaining performance obligations (RPO)", "Customer count (>$1M ARR)"],
    competitive_advantages=["Cross-cloud architecture (works on AWS + Azure + GCP)", "Data sharing/marketplace network effects", "Separation of compute and storage enabling elastic scaling"],
    business_model_keywords=["Data Cloud", "consumption", "RPO", "net revenue retention", "data sharing", "Databricks", "Frank Slootman", "Sridhar Ramaswamy"],
    moat_type=["switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost_level="high",
    customer_concentration="moderate",
    capital_intensity="asset_light",
    earnings_cyclicality="mild",
    narrative_dependence="moderate",
    binary_risk_level="none",
))

# ── Automatic Data Processing (ADP) ─────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="ADP",
    company_name="Automatic Data Processing, Inc.",
    business_model="ADP provides human capital management (HCM) solutions: payroll processing, HR management, tax filing, benefits administration, and workforce management for businesses of all sizes. Revenue is recurring subscription + float income on client funds.",
    primary_revenue_drivers=["Employer Services (~65% — payroll, HR, tax for SMB and mid-market)", "PEO Services (~35% — professional employer organization for comprehensive HR outsourcing)"],
    recurring_revenue_sources=["Monthly payroll processing subscriptions (multi-year contracts)", "Client funds float income (interest earned on payroll funds held before disbursement)", "PEO per-employee-per-month fees"],
    rate_sensitivity_note="ADP benefits from higher rates: earns interest on $30B+ client funds held between collection and disbursement. Each 100bps adds ~$300M to pre-tax income.",
    inflation_pass_through="Strong — annual price increases of 4-6% embedded in contracts. Wage inflation increases the dollar value of payroll processed.",
    recession_behavior="Payroll is non-discretionary — employers must pay employees and file taxes regardless of economic conditions. Pays-per-control (employee count) declines 2-4% in recessions but pricing holds. Revenue declines 0-3% in severe recessions.",
    major_risks=["Competition from Workday, Paylocity, and Paychex in mid-market", "Secular shift to integrated HCM platforms bypassing standalone payroll", "Decline in interest rates reducing client funds float income"],
    valuation_style="ADP trades at 28-32x forward P/E reflecting the recurring revenue model, pricing power, and non-discretionary demand.",
    key_metrics=["Pays per control (same-store employee count)", "Client retention rate (90%+)", "ES new business bookings growth", "Client funds interest yield"],
    competitive_advantages=["Process 1 in 6 US paychecks — scale creates compliance and regulatory expertise moat", "Client fund float ($30B+) generates risk-free interest income", "40+ year client relationships with 90%+ retention", "Regulatory complexity in payroll/tax creates switching friction"],
    business_model_keywords=["payroll", "HCM", "pays per control", "client funds", "PEO", "employer services", "retention rate", "workforce management"],
    moat_type=["switching_cost", "scale_economy", "regulatory"],
    revenue_model="subscription",
    switching_cost_level="very_high",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── Coinbase Global (COIN) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="COIN",
    company_name="Coinbase Global, Inc.",
    business_model="Coinbase operates the largest US cryptocurrency exchange. Revenue from trading fees (retail + institutional), staking rewards, custody fees, and the USDC stablecoin partnership with Circle.",
    primary_revenue_drivers=["Transaction revenue (~60% — retail and institutional trading fees)", "Subscription & services (~35% — staking, custody, USDC interest)", "Other (~5% — blockchain rewards)"],
    recurring_revenue_sources=["USDC interest income (earns yield on reserves)", "Staking rewards (ongoing crypto protocol participation)", "Custody fees for institutional clients"],
    rate_sensitivity_note="Higher rates benefit USDC interest income but may suppress speculative crypto trading activity.",
    inflation_pass_through="Limited — trading fees are percentage-based but trading volume is driven by crypto sentiment, not inflation.",
    recession_behavior="Crypto trading volumes collapse in risk-off environments. Revenue can decline 50-80% peak-to-trough. USDC/staking provides some floor.",
    major_risks=["SEC regulatory action against crypto assets as securities", "Crypto winter reducing trading volumes 70%+", "Competition from decentralized exchanges (DEXs)"],
    valuation_style="COIN is valued on revenue multiples (3-8x) given earnings volatility tied to crypto cycles.",
    key_metrics=["Trading volume", "Monthly transacting users (MTUs)", "USDC market cap", "Revenue per MTU"],
    competitive_advantages=["#1 US regulated crypto exchange by volume", "Regulatory compliance as competitive moat vs offshore exchanges", "USDC partnership provides rate-insensitive revenue"],
    business_model_keywords=["crypto", "USDC", "staking", "trading volume", "MTU", "SEC", "Base", "custody", "blockchain"],
    moat_type=["regulatory", "brand"],
    revenue_model="transaction_toll",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="asset_light",
    earnings_cyclicality="highly_cyclical",
    narrative_dependence="high",
    binary_risk_level="moderate",
))

# ── Lowe's Companies (LOW) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="LOW",
    company_name="Lowe's Companies, Inc.",
    business_model="Lowe's is the #2 US home improvement retailer (behind Home Depot) with 1,700+ stores. Revenue from DIY consumers and professional contractors across building materials, appliances, and home décor.",
    primary_revenue_drivers=["DIY consumer sales (~75%)", "Pro contractor sales (~25% — growing focus)"],
    recurring_revenue_sources=["Loyalty program engagement driving repeat visits", "Pro accounts with recurring project-based purchasing"],
    rate_sensitivity_note="Highly rate-sensitive: mortgage rates directly impact existing home sales → home improvement spending. Each 100bps rate rise reduces existing home sales ~10-15%.",
    inflation_pass_through="Moderate — can pass through material cost inflation but discretionary project deferrals offset volume gains.",
    recession_behavior="Revenue declines 5-15% in housing-led recessions. Maintenance/repair spending is more resilient than remodeling. Gross margins compress as promotions increase.",
    major_risks=["Housing market slowdown from elevated mortgage rates", "Competition from Home Depot in Pro segment", "E-commerce competition for commoditized products"],
    valuation_style="LOW trades at 16-20x forward P/E reflecting the housing cycle, margin expansion story, and buyback-driven EPS growth.",
    key_metrics=["Comparable store sales growth", "Pro sales penetration", "Operating margin expansion", "Transactions per store"],
    competitive_advantages=["#2 US home improvement with 1,700+ stores — duopoly with HD", "Store proximity and in-stock availability create convenience moat", "Growing Pro loyalty program"],
    business_model_keywords=["home improvement", "Pro", "DIY", "comparable store sales", "housing", "remodeling", "Marvin Ellison"],
    moat_type=["scale_economy", "brand"],
    revenue_model="product_sale",
    switching_cost_level="low",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── KLA Corporation (KLAC) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="KLAC",
    company_name="KLA Corporation",
    business_model="KLA is the dominant semiconductor process control and inspection equipment maker. Revenue from new system sales to chip fabricators and recurring service/spare parts revenue from the installed base.",
    primary_revenue_drivers=["Semiconductor Process Control (~80% — inspection, metrology, data analytics)", "PCB/Display/Component Inspection (~15%)", "Services (~20% overlap — recurring installed base)"],
    recurring_revenue_sources=["Service contracts on installed equipment base (multi-year)", "Spare parts and consumables", "Software analytics subscriptions"],
    rate_sensitivity_note="Low direct rate sensitivity. Semiconductor CapEx cycle is the dominant driver, not interest rates.",
    inflation_pass_through="Strong — pricing power from monopoly/duopoly positions in key inspection segments.",
    recession_behavior="Revenue can decline 20-30% in semiconductor CapEx downturns but recovers quickly as node transitions resume. Service revenue provides a floor.",
    major_risks=["Semiconductor CapEx cycle downturn reducing new tool orders", "China export restrictions limiting addressable market", "Customer concentration in TSMC/Samsung/Intel"],
    valuation_style="KLAC trades at 22-28x forward P/E reflecting process control market dominance, high margins (60%+ gross), and recurring service revenue.",
    key_metrics=["Semiconductor Process Control revenue growth", "Service revenue as % of total", "Gross margin", "Backlog"],
    competitive_advantages=["#1 in semiconductor process control with 50%+ market share", "Process control becomes more critical at smaller nodes — secular tailwind", "80%+ gross margins on inspection tools", "Installed base of 50,000+ tools generates recurring service revenue"],
    business_model_keywords=["process control", "inspection", "metrology", "defect", "yield", "node", "wafer", "installed base"],
    moat_type=["scale_economy", "patent", "data_advantage"],
    revenue_model="product_sale",
    switching_cost_level="very_high",
    customer_concentration="concentrated",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── Roblox Corporation (RBLX) ───────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="RBLX",
    company_name="Roblox Corporation",
    business_model="Roblox is a user-generated gaming platform where developers create experiences and users purchase virtual currency (Robux). Revenue from Robux purchases, advertising, and developer marketplace fees.",
    primary_revenue_drivers=["Robux virtual currency purchases (~90%)", "Advertising and sponsorships (~10% — emerging)"],
    recurring_revenue_sources=["Daily active user engagement driving Robux consumption (habitual but not contractual)"],
    rate_sensitivity_note="Low direct rate sensitivity. Growth stock multiple compression is the primary rate transmission.",
    inflation_pass_through="Limited — Robux pricing is fixed. Revenue growth depends on user engagement, not pricing.",
    recession_behavior="Gaming engagement tends to increase in recessions (cheap entertainment). Robux spending may decline modestly as parents cut discretionary allowances.",
    major_risks=["User aging out of core demographic (8-14 year olds)", "COPPA and child safety regulatory risk", "Platform safety scandals impacting brand trust"],
    valuation_style="RBLX is valued on EV/bookings (5-10x) given deferred revenue accounting and pre-profitability status.",
    key_metrics=["Daily Active Users (DAUs)", "Hours engaged", "Bookings growth", "Average bookings per DAU (ABPDAU)"],
    competitive_advantages=["Network effect — user-generated content creates self-reinforcing engagement", "200M+ monthly active users creating massive content library", "Developer ecosystem (4M+ developers) is the moat"],
    business_model_keywords=["Robux", "DAU", "bookings", "developer", "UGC", "metaverse", "engagement", "ABPDAU"],
    moat_type=["network_effect"],
    revenue_model="transaction_toll",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="high",
    binary_risk_level="moderate",
))

# ── CAVA Group (CAVA) ───────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="CAVA",
    company_name="CAVA Group, Inc.",
    business_model="CAVA is a fast-casual Mediterranean restaurant chain with 300+ locations. Revenue from in-store and digital orders of customizable bowls, pitas, and salads.",
    primary_revenue_drivers=["Restaurant-level revenue (~95% — same-store sales + new unit openings)", "CPG/wholesale (~5% — CAVA-branded grocery products)"],
    recurring_revenue_sources=["Habitual dining frequency of loyal customers (not contractual)"],
    rate_sensitivity_note="Moderate — consumer discretionary spending sensitivity. Higher rates compress consumer budgets for dining out.",
    inflation_pass_through="Moderate — can pass through menu price increases of 3-5% but food cost inflation (olive oil, protein) compresses margins.",
    recession_behavior="Fast-casual dining declines 5-15% in recessions as consumers trade down to QSR or home cooking. CAVA's Mediterranean positioning may be more resilient than generic fast-casual.",
    major_risks=["Rapid unit growth execution risk", "Food cost inflation compressing restaurant margins", "Competition from Sweetgreen and expanding Mediterranean concepts"],
    valuation_style="CAVA trades at 100-200x forward P/E reflecting high unit growth (25%+ annual) and long runway for Mediterranean fast-casual penetration.",
    key_metrics=["Same-store sales growth", "New unit openings", "Restaurant-level margin", "AUV (Average Unit Volume)"],
    competitive_advantages=["First-mover in scaled Mediterranean fast-casual", "Strong unit economics (AUV $2.5M+, restaurant margin 24%+)", "Digital ordering platform driving efficiency"],
    business_model_keywords=["Mediterranean", "fast-casual", "AUV", "same-store sales", "unit growth", "restaurant margin", "digital mix"],
    moat_type=["brand"],
    revenue_model="product_sale",
    switching_cost_level="none",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="moderate",
    narrative_dependence="high",
    binary_risk_level="low",
))

# ── MercadoLibre (MELI) ─────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="MELI",
    company_name="MercadoLibre, Inc.",
    business_model="MercadoLibre is the dominant LatAm e-commerce marketplace and fintech platform. Revenue from marketplace commissions, Mercado Pago (payments/fintech), advertising, shipping (Mercado Envios), and credit (Mercado Credito).",
    primary_revenue_drivers=["Commerce (~50% — marketplace commissions, advertising, shipping)", "Fintech (~50% — Mercado Pago payments, Mercado Credito lending, digital account)"],
    recurring_revenue_sources=["Payment processing fees (GMV-linked, structurally recurring)", "Advertising on marketplace (growing rapidly)", "Lending interest income"],
    rate_sensitivity_note="LatAm rates are structural (10%+). MELI benefits from high-rate lending margins on Mercado Credito. US rates have limited direct impact.",
    inflation_pass_through="Strong — marketplace commissions are percentage-based. Inflation in LatAm mechanically increases GMV and revenue.",
    recession_behavior="LatAm e-commerce penetration is low (~15%), so secular growth offsets macro weakness. Fintech credit losses rise in recessions.",
    major_risks=["Credit losses on Mercado Credito lending portfolio", "Competition from Amazon, Shopee in LatAm", "Currency depreciation in Brazil/Argentina/Mexico"],
    valuation_style="MELI trades at 40-60x forward P/E reflecting LatAm e-commerce and fintech penetration runway.",
    key_metrics=["GMV growth (FX-neutral)", "TPV (Total Payment Volume)", "Credit portfolio quality (NPL ratio)", "Active users"],
    competitive_advantages=["Dominant LatAm marketplace (70%+ share in key markets)", "Integrated ecosystem: marketplace + payments + logistics + credit", "Network effect: more sellers → more buyers → more sellers"],
    business_model_keywords=["GMV", "Mercado Pago", "Mercado Credito", "Mercado Envios", "LatAm", "Brazil", "Argentina", "TPV", "fintech"],
    moat_type=["network_effect", "scale_economy", "data_advantage"],
    revenue_model="transaction_toll",
    switching_cost_level="high",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="mild",
    narrative_dependence="low",
    binary_risk_level="low",
))

# ── Veeva Systems (VEEV) ────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="VEEV",
    company_name="Veeva Systems Inc.",
    business_model="Veeva provides cloud software for the life sciences industry: CRM (Veeva CRM), regulatory (Vault RIM), clinical (Vault CDMS), quality (Vault QMS), and commercial data (Veeva Data Cloud). Subscription-based with industry-specific lock-in.",
    primary_revenue_drivers=["Subscription services (~80% — Vault platform, CRM, Data Cloud)", "Professional services (~20% — implementation, training)"],
    recurring_revenue_sources=["Annual/multi-year subscription contracts (85%+ gross retention)", "Data Cloud subscriptions (reference data for pharma commercial teams)"],
    rate_sensitivity_note="Low direct rate sensitivity. Life sciences IT spending is driven by pipeline and regulatory requirements, not interest rates.",
    inflation_pass_through="Strong — annual subscription price increases of 3-5% embedded in contracts.",
    recession_behavior="Life sciences R&D spending is non-cyclical. Veeva's products are regulatory-required (GxP compliance). Revenue is highly resilient in recessions.",
    major_risks=["Salesforce re-entering life sciences CRM after VEEV migration off Salesforce platform", "Customer concentration in top 20 pharma companies", "Vault platform competition from SAP/Oracle in non-CRM modules"],
    valuation_style="VEEV trades at 35-50x forward P/E reflecting non-cyclical life sciences demand, 85%+ subscription retention, and TAM expansion into clinical and regulatory.",
    key_metrics=["Subscription revenue growth", "Remaining performance obligations (RPO)", "Net revenue retention", "Number of Vault product adoptions per customer"],
    competitive_advantages=["Industry-standard CRM for pharma (80%+ market share)", "Vault platform creates multi-product lock-in", "Domain expertise in life sciences regulatory requirements", "Migration off Salesforce to own platform increases independence"],
    business_model_keywords=["Vault", "CRM", "life sciences", "pharma", "clinical", "regulatory", "GxP", "Data Cloud", "RPO"],
    moat_type=["switching_cost", "data_advantage"],
    revenue_model="subscription",
    switching_cost_level="very_high",
    customer_concentration="concentrated",
    capital_intensity="asset_light",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="none",
))

# ── Axon Enterprise (AXON) ──────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AXON",
    company_name="Axon Enterprise, Inc.",
    business_model="Axon provides law enforcement technology: TASER devices (conducted energy weapons), body cameras (Axon Body), fleet cameras, cloud evidence management (Axon Evidence/Records), and VR training. Transitioning from hardware to recurring SaaS + cloud.",
    primary_revenue_drivers=["TASER devices (~40% — hardware sales + cartridge consumables)", "Software & sensors (~35% — Axon Cloud, body cameras, fleet cameras)", "Officer safety plans (~25% — bundled hardware + software subscriptions)"],
    recurring_revenue_sources=["Axon Cloud subscriptions (evidence management, records management)", "Officer Safety Plan (OSP) bundles (5-year subscription including hardware refresh)", "TASER cartridge consumables"],
    rate_sensitivity_note="Low — law enforcement budgets are funded by municipal taxes, not sensitive to interest rates.",
    inflation_pass_through="Strong — government contracts have price escalators. TASER pricing power is monopoly-grade (no competitor).",
    recession_behavior="Law enforcement spending is non-discretionary. Police budgets are funded by local taxes and federal grants. Revenue is highly resilient in recessions.",
    major_risks=["Anti-police sentiment reducing law enforcement budgets", "Regulatory restrictions on TASER or surveillance technology", "International expansion execution risk", "Customer concentration in US law enforcement"],
    valuation_style="AXON trades at 60-80x forward P/E reflecting the transition from hardware to SaaS, TASER monopoly, and TAM expansion into enterprise security.",
    key_metrics=["Annual recurring revenue (ARR)", "Net revenue retention rate", "TASER unit shipments", "Cloud seats"],
    competitive_advantages=["TASER monopoly — no competitor has FDA/safety approval for a competing device", "Axon Evidence is the standard in US law enforcement (250,000+ users)", "OSP bundles create 5-year recurring revenue streams", "Body camera + cloud evidence integration creates switching friction"],
    business_model_keywords=["TASER", "body camera", "Axon Cloud", "Axon Evidence", "OSP", "law enforcement", "ARR", "Rick Smith"],
    moat_type=["natural_monopoly", "switching_cost", "brand"],
    revenue_model="subscription",
    switching_cost_level="very_high",
    customer_concentration="moderate",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="low",
    binary_risk_level="low",
))

# ── Regeneron Pharmaceuticals (REGN) ────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="REGN",
    company_name="Regeneron Pharmaceuticals, Inc.",
    business_model="Regeneron is a biotech focused on antibody-based therapeutics. Revenue driven by Dupixent ($12B+ franchise for eczema/asthma/COPD), Eylea (retinal disease), and a deep antibody technology pipeline.",
    primary_revenue_drivers=["Dupixent (~55% — atopic dermatitis, asthma, COPD, growing indications)", "Eylea/Eylea HD (~25% — retinal disease)", "Oncology (Libtayo) + other (~10%)", "Collaboration revenue (~10% — Sanofi/Bayer partnerships)"],
    recurring_revenue_sources=["Chronic disease treatments requiring ongoing dosing (Dupixent, Eylea)", "Collaboration milestone and royalty payments"],
    rate_sensitivity_note="Low — pharma demand is non-discretionary. Valuation multiple is rate-sensitive at 25x+ P/E.",
    inflation_pass_through="Strong — drug pricing power in US market. Annual list price increases of 3-5%.",
    recession_behavior="Pharma revenue is non-cyclical. Patients continue treatment regardless of economic conditions. Payer coverage may tighten modestly.",
    major_risks=["Dupixent biosimilar entry (patent cliff ~2031)", "Eylea biosimilar competition already emerging", "IRA drug pricing negotiation exposure", "Pipeline failure risk on next-generation programs"],
    valuation_style="REGN trades at 15-20x forward P/E, a discount to pharma peers reflecting Eylea biosimilar overhang and pipeline uncertainty.",
    key_metrics=["Dupixent global sales growth", "Eylea/Eylea HD market share retention", "Pipeline readouts (linvoseltamab, fianlimab)", "R&D productivity"],
    competitive_advantages=["VelociSuite antibody discovery platform — fastest in industry", "Dupixent franchise expanding into new indications (COPD, food allergy)", "Eylea HD lifecycle management extending franchise", "50%+ gross margins with capital-efficient R&D model"],
    business_model_keywords=["Dupixent", "Eylea", "antibody", "VelociSuite", "Sanofi", "atopic dermatitis", "COPD", "biosimilar", "Len Schleifer"],
    moat_type=["patent", "data_advantage"],
    revenue_model="product_sale",
    switching_cost_level="moderate",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="none",
    binary_risk_level="moderate",
))

# ── Vertex Pharmaceuticals (VRTX) ───────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="VRTX",
    company_name="Vertex Pharmaceuticals Incorporated",
    business_model="Vertex has a near-monopoly in cystic fibrosis (CF) treatment with Trikafta/Kaftrio (90%+ market share). Revenue from CF franchise plus emerging pipeline in pain (suzetrigine), gene editing (Casgevy), and kidney disease.",
    primary_revenue_drivers=["Trikafta/Kaftrio (~90% — CF treatment, $9B+ annual revenue)", "Casgevy (~5% — gene therapy for sickle cell/beta-thalassemia)", "Pain (suzetrigine) + kidney disease (~5% — emerging pipeline)"],
    recurring_revenue_sources=["Chronic CF treatment requiring lifetime dosing (patients take Trikafta daily)", "Gene therapy one-time treatments with periodic follow-up"],
    rate_sensitivity_note="Low — CF treatment is non-discretionary. Valuation multiple compression is the primary rate transmission.",
    inflation_pass_through="Strong — drug pricing power. Trikafta price increases of 3-5% annually.",
    recession_behavior="CF treatment is essential — patients cannot stop. Revenue is completely non-cyclical. Pipeline investment continues regardless of economy.",
    major_risks=["CF patient population ceiling (~90K addressable, most already on treatment)", "Pipeline diversification risk (pain, kidney, gene editing all early/mid-stage)", "Trikafta patent cliff (~2037)", "Gene therapy commercial execution (Casgevy pricing/access)"],
    valuation_style="VRTX trades at 25-30x forward P/E reflecting CF monopoly, pipeline optionality in pain/kidney, and non-cyclical revenue.",
    key_metrics=["Trikafta revenue growth (price + new patient starts)", "CF patient penetration rate globally", "Suzetrigine trial readouts", "Casgevy commercial launch metrics"],
    competitive_advantages=["90%+ market share in CF treatment — no competitor has comparable efficacy", "Trikafta addresses 90% of CF mutations (triple combination therapy)", "Gene editing partnership with CRISPR Therapeutics (Casgevy)", "Non-opioid pain program (suzetrigine) could be transformational"],
    business_model_keywords=["Trikafta", "Kaftrio", "CF", "cystic fibrosis", "Casgevy", "suzetrigine", "gene editing", "NaV1.8", "Reshma Kewalramani"],
    moat_type=["patent", "data_advantage"],
    revenue_model="product_sale",
    switching_cost_level="very_high",
    customer_concentration="diversified",
    capital_intensity="moderate",
    earnings_cyclicality="non_cyclical",
    narrative_dependence="low",
    binary_risk_level="moderate",
))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_knowledge_profile(ticker: str) -> Optional[CompanyKnowledgeProfile]:
    """Return the knowledge profile for *ticker* (case-insensitive).

    Parameters
    ----------
    ticker:
        Exchange ticker symbol, e.g. ``'AAPL'`` or ``'brk.b'``.

    Returns
    -------
    CompanyKnowledgeProfile or None
        The profile if found, ``None`` if the ticker is not in the database.
    """
    result = _KNOWLEDGE_DB.get(ticker.upper())
    if result is None:
        logger.debug("company_knowledge: no profile found for ticker %r", ticker)
    return result


def get_profile_for_company(company: CompanyContext) -> Optional[CompanyKnowledgeProfile]:
    """Convenience wrapper that resolves a profile from a ``CompanyContext``.

    Resolution order:
    1. Ticker look-up (preferred — fast and unambiguous).
    2. Case-insensitive company-name match across all profiles.

    Parameters
    ----------
    company:
        A resolved :class:`~app.schemas.CompanyContext` object.

    Returns
    -------
    CompanyKnowledgeProfile or None
    """
    # 1. Try ticker first
    profile = get_knowledge_profile(company.ticker)
    if profile is not None:
        return profile

    # 2. Fall back to company_name substring match
    name_lower = company.company_name.lower()
    for p in _KNOWLEDGE_DB.values():
        if p.company_name.lower() == name_lower:
            logger.debug(
                "company_knowledge: resolved %r via company_name match", company.company_name
            )
            return p

    logger.debug(
        "company_knowledge: no profile found for company %r (ticker=%r)",
        company.company_name,
        company.ticker,
    )
    return None


def list_known_tickers() -> List[str]:
    """Return a sorted list of all tickers in the knowledge database."""
    return sorted(_KNOWLEDGE_DB.keys())
