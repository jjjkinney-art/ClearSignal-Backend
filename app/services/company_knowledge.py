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
        "device installed base."
    ),
    primary_revenue_drivers=[
        "iPhone (~52% of revenue)",
        "Services (~25% of revenue, ~72% gross margin)",
        "Mac (~8%)",
        "iPad (~7%)",
        "Wearables / Home / Accessories (~8%)",
    ],
    recurring_revenue_sources=[
        "App Store commissions (15–30% take rate)",
        "iCloud storage subscriptions",
        "Apple One bundle (Music, TV+, Arcade, Fitness+)",
        "AppleCare extended warranty",
        "Apple Pay / Tap-to-Pay interchange participation",
        "Google TAC (search default on Safari, ~$18–20B/yr)",
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
        "manufactures all A/M-series chips in Taiwan",
        "EU and US regulatory scrutiny of App Store monopoly (DMA enforcement could "
        "force sideloading and reduce take rates)",
        "Google TAC payment at risk if DOJ antitrust action forces Search default "
        "competition (represents ~$18-20B/yr in high-margin Services revenue)",
        "iPhone upgrade cycle elongation as consumers hold devices longer",
        "Generative AI disruption of Siri and potential loss of AI-native platform relevance",
    ],
    valuation_style=(
        "Market prices AAPL on a blended P/E (~28-30x) with significant weight on "
        "Services segment via a sum-of-parts: hardware traded at ~15x, Services at "
        "~35-40x (software multiple), weighted by mix.  As Services becomes a larger "
        "share, the blended multiple expands structurally.  Buyback yield (~3-4%/yr) "
        "provides meaningful EPS accretion that partially offsets multiple compression "
        "in rising-rate environments."
    ),
    key_metrics=[
        "iPhone unit volumes and ASP",
        "Services revenue growth rate and gross margin",
        "Active installed base (2B+ devices)",
        "Gross margin (overall target ~44-46%)",
        "Free cash flow ($85-95B/yr range)",
        "Share buybacks (>$85B/yr authorized)",
        "China revenue % of total",
        "App Store GMV and take rate",
    ],
    competitive_advantages=[
        "Tightly integrated hardware-software-services ecosystem that raises switching costs",
        "A/M-series chip vertical integration delivering best-in-class perf-per-watt",
        "Brand loyalty with ~90%+ iPhone retention in upgrade cycles",
        "App Store platform network effect (developer supply × user demand)",
        "Privacy positioning as differentiator vs Android",
    ],
    business_model_keywords=[
        "iPhone", "Services", "App Store", "iCloud", "installed base", "buyback",
        "China", "Mac", "AppleCare", "ecosystem", "TSMC", "Tim Cook", "M-series",
        "TAC", "sideloading",
    ],
))


# ── Nvidia (NVDA) ─────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="NVDA",
    company_name="NVIDIA Corporation",
    business_model=(
        "NVIDIA designs GPUs and system-on-chip processors, licensing its CUDA parallel "
        "computing platform to hyperscalers and enterprises for AI training and inference, "
        "while also serving the gaming, automotive, and professional visualization markets."
    ),
    primary_revenue_drivers=[
        "Data Center (~87% of revenue — H100/H200/B100 GPU clusters, DGX systems, "
        "InfiniBand networking via Mellanox)",
        "Gaming (~9% — GeForce RTX consumer GPUs)",
        "Professional Visualization (~2%)",
        "Automotive (<2% — DRIVE platform)",
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
        "NIM", "DLSS", "Grace", "export restrictions", "Jensen Huang", "InfiniBand",
        "Blackwell", "HBM",
    ],
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
        "Satya Nadella",
    ],
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
        "Vehicles are large discretionary purchases; prior recessions saw US auto sales "
        "fall 30-40%.  Tesla's direct-sales model and agressive price-cutting create "
        "volume resilience at the cost of margin.  The Megapack/Energy backlog (multi-year "
        "committed utility orders) provides some revenue stability.  FSD and Robotaxi "
        "long-term optionality is unaffected by near-term recession."
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
        "platform (30-50x P/E on FSD/Robotaxi optionality), and energy storage business "
        "(15-20x EV/EBITDA on Megapack).  The market-implied Robotaxi/FSD terminal value "
        "is enormous — removing that option value from the stock implies the auto business "
        "alone would be worth ~$100-120/share.  The premium above that level is pure "
        "technology optionality."
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
))


# ── Amazon (AMZN) ─────────────────────────────────────────────────────────────
_register(CompanyKnowledgeProfile(
    ticker="AMZN",
    company_name="Amazon.com, Inc.",
    business_model=(
        "Amazon operates three distinct profit pools: AWS cloud computing (the primary "
        "earnings engine), North America and International e-commerce marketplaces "
        "(retail + third-party seller services + advertising), and a growing advertising "
        "business monetising the purchase-intent signal of 200M+ Prime members."
    ),
    primary_revenue_drivers=[
        "Online Stores (~22% of revenue — first-party retail)",
        "Third-Party Seller Services (~24% — marketplace fulfillment and commissions)",
        "AWS (~17% of revenue but ~65-70% of operating income)",
        "Advertising Services (~8% and growing rapidly — sponsored products/brands)",
        "Subscription Services (~7% — Prime membership, music, video)",
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
        "AWS is sticky: enterprise cloud workloads are mission-critical and hard to "
        "turn off, though optimisation deals are common in stress periods.  Retail "
        "e-commerce benefits from trade-down from specialty retail and brick-and-mortar "
        "in recessions (Amazon gains market share as a value channel).  Advertising "
        "is more cyclical — branded advertising cuts faster than performance marketing."
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
        "revenue (cloud comps), Advertising at ~20-25x revenue (high-growth ad platform), "
        "Retail at 0.5-1x revenue (thin-margin distribution).  The implied 'retail for "
        "free' thesis often frames the investment case: pay for AWS+Advertising, get the "
        "retail flywheel at no incremental cost."
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
        "Bedrock", "same-day delivery",
    ],
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
        "a step-change in US commercial customer count — still unproven at scale",
        "Valuation: 60-100x revenue prices in a decade of hyper-growth; any deceleration "
        "in AIP adoption reprices the stock sharply",
        "Binary on US Government contract renewals: losing a major classified program "
        "would remove a large, predictable revenue block",
        "Competition from hyperscalers (Microsoft Copilot, Amazon Bedrock, Google Vertex) "
        "offering similar AI workflow capabilities at lower cost",
        "Key-person risk: Peter Thiel and Alex Karp are central to the government "
        "relationship network; leadership departure risk is existential",
    ],
    valuation_style=(
        "PLTR is valued on a revenue multiple (EV/Revenue 30-60x) with optionality embedded "
        "for AIP commercial adoption driving software-like margins at scale.  The commercial "
        "segment growth rate and bootcamp conversion rate are the key valuation drivers.  "
        "On any normalized earnings basis, the stock carries extreme optionality premium — "
        "most of the value is in a blue-sky scenario where AIP becomes a category-defining "
        "enterprise platform."
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
