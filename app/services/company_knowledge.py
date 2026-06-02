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
        "Semi-custom SoC royalties (PlayStation 5, Xbox Series X long-cycle contracts)",
        "Hyperscaler EPYC CPU deployment (multi-year server refresh cycles)",
        "MI300X AI accelerator pipeline from cloud providers and HPC customers",
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
        "AMD has moderate cyclicality. Data Center (EPYC + Instinct) is relatively "
        "resilient as hyperscaler AI capex is a multi-year secular build-out. Client "
        "(Ryzen) and Gaming (Radeon, semi-custom) are consumer-cyclical and can decline "
        "30-50% in severe downturns. Embedded (Xilinx) is the most cyclical segment."
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
        "Chiplet architecture (AMD CDNA/RDNA on TSMC): AMD pioneered chiplet design for "
        "cost-effective scaling of HPC chips, now the industry standard approach",
    ],
    business_model_keywords=[
        "EPYC", "MI300", "Instinct", "Ryzen", "ROCm", "CDNA", "RDNA",
        "Zen 5", "Xilinx", "Versal", "HBM", "inference", "data center GPU",
        "server CPU", "semi-custom", "Lisa Su", "fabless",
    ],
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
        "Apple multi-year chip supply agreements (A-series iPhone, M-series Mac, annual)",
        "NVIDIA AI GPU wafer allocations (H100/H200/Blackwell, 12-18 month lead times)",
        "CoWoS advanced packaging pre-paid capacity reservations from hyperscalers",
        "Long-term NRE (non-recurring engineering) contracts for custom process development",
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
        "structural offset — hyperscaler AI capex is relatively recession-resistant. "
        "In 2022-2023 inventory correction, TSMC revenue declined ~15% then recovered "
        "strongly. Advanced node revenue is more resilient than mature node revenue."
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
        "Monthly subscription fees (high stickiness — ~2-3% monthly churn for paid tiers)",
        "Annual/pre-paid plan subscribers (growing mix, lower churn)",
        "Ad-supported tier subscription fees + CPM-based advertising revenue",
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
        "Global licensing infrastructure: operating in 190+ countries with localized "
        "payment processing, content compliance, and subtitling at a scale no competitor "
        "matches (Disney+ is in ~80 countries, Max in ~65)",
        "Password-sharing enforcement model: Netflix's technical infrastructure and "
        "household verification systems are more advanced than competitors, enabling "
        "the paid-sharing upsell that added 30M+ subscribers",
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
        "ARPA — average revenue per account) — very high switching costs due to device "
        "payoff lock-in and 24-month payment plans",
        "MyPlan and MyHome customizable plan ARPA expansion (add-ons for Disney+, Apple One, "
        "Walmart+ — driving ARPU growth via upsell)",
        "Fios internet subscription (monthly broadband service fee — 96%+ retention rate "
        "in Fios footprint)",
        "Business connectivity long-term contracts (enterprise WAN, private 5G, SD-WAN)",
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
        "Wireless service is largely non-discretionary — consumers maintain phone plans "
        "even in recessions (may downgrade tier but rarely cancel).  Fios broadband is "
        "nearly recession-proof (essential connectivity).  Device upgrade volumes slow "
        "in recessions (consumers extend device life), reducing equipment revenue but "
        "improving service margin mix.  Business wireline may see enterprise spending "
        "deferrals.  VZ's ~$11B annual dividend is well-covered by FCF."
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
        "Fios fiber moat in footprint: FTTH (fiber-to-the-home) in NY/NJ/PA markets "
        "delivers gigabit broadband with near-zero churn in established footprint",
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
        "AT&T Fiber broadband subscription (near-100% retention in fiber footprint; "
        "internet-only strategy following DIRECTV stake reduction)",
        "FirstNet network service contracts (multi-year federal/state first-responder "
        "wireless contracts — deferred revenue and long-term visibility)",
        "Business Wireline managed services contracts (multi-year government/enterprise)",
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
        "Wireless service is non-discretionary for most consumers.  AT&T Fiber broadband "
        "is essential infrastructure.  Consumers may downgrade to lower-priced prepaid "
        "in severe recessions.  Business wireline sees enterprise spending deferrals. "
        "AT&T's primary recession concern is FCF coverage of the dividend — if FCF "
        "falls below $14B, the ~$8B/yr dividend sustainability comes into question."
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
        "Postpaid wireless pricing momentum: price increases in 2023 demonstrated "
        "consumer acceptance of value-tiered pricing, expanding ARPU without equivalent "
        "churn — showing demand inelasticity for wireless service",
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
        "Digital platform subscriptions (Delfi/Lumi SaaS licenses — growing recurring "
        "revenue from cloud-based reservoir characterization tools)",
        "Production Systems aftermarket parts and services (subsea maintenance "
        "contracts for installed base)",
        "Artificial lift and production optimization services (continuous well surveillance "
        "and intervention for producing wells)",
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
        "Delfi/Lumi digital platform: cloud-native reservoir characterization platform "
        "with AI-powered geology and geomechanics capabilities that integrates disparate "
        "NOC data sources — creates switching costs once data is ingested",
        "International NOC relationships: 60+ years of operating in challenging basins "
        "(Saudi Arabia, Russia, Iraq, Kazakhstan) builds institutional trust that no "
        "new entrant can replicate quickly",
        "Integrated project management: SLB can take full-cycle well delivery risk "
        "(design-to-production) for NOC customers who lack internal technical capacity "
        "— differentiated from equipment-only competitors",
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
        "Multi-year enterprise SaaS subscriptions (~93% of total revenue) — "
        "average annual contract value $150K+; Fortune 500 customers auto-renew",
        "Agentforce usage-based revenue: AI agent 'conversations' priced per "
        "1,000 interactions (~$2/conversation) — new consumption-based layer atop subscriptions",
        "Professional services and implementation fees (~7%) — typically tied "
        "to new product expansion rather than churn",
        "AppExchange ISV ecosystem revenue share — thousands of third-party "
        "applications creating platform lock-in and incremental revenue",
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
        "Customer 360 platform breadth: Sales + Service + Marketing + Data Cloud "
        "integrated on a single platform forces competitors to replicate an entire "
        "suite rather than displace a single point solution — the largest moat",
        "Trailhead community and AppExchange ecosystem: 10M+ certified Salesforce "
        "developers and administrators create a massive talent pool and switching cost — "
        "enterprises cannot easily retrain their Salesforce-skilled workforce",
        "Data Cloud advantage: Salesforce has more enterprise customer interaction "
        "data than any single competitor (1 trillion+ records processed daily) — "
        "powers more accurate AI models for Einstein and Agentforce",
        "Marc Benioff brand and enterprise trust: 25+ years as the cloud CRM "
        "standard makes Salesforce the default enterprise consideration — "
        "no-compete during procurement is rare; Salesforce wins most deals that go "
        "to bake-off",
    ],
    business_model_keywords=[
        "Agentforce", "Customer 360", "Sales Cloud", "Service Cloud", "Data Cloud",
        "MuleSoft", "Tableau", "Slack", "Marc Benioff", "Einstein AI",
        "CRM", "remaining performance obligations", "RPO", "cRPO",
        "net revenue retention", "autonomous agents", "agentic AI",
        "Trailhead", "AppExchange", "non-GAAP operating margin",
        "Marketing Cloud", "Commerce Cloud",
    ],
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
        "Nike Membership (300M+ members): SNKRS app and Nike app members "
        "generate higher LTV, repeat purchase frequency, and first-party data",
        "Jordan Brand licensing to NBA, NFL, MLB: exclusive leagues/team "
        "uniform contracts renewed multi-year with escalating fees",
        "Converse brand (sub-brand with separate positioning targeting "
        "street culture) — relatively stable $2B+ revenue stream",
        "Nike+/NRC (Nike Run Club) and NTC fitness platforms — ecosystem "
        "driving member retention and purchase conversion",
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
        "Moderately defensive: Nike's top-franchise silhouettes (Air Force 1, "
        "Jordan 1, Dunk) have cultural cachet that sustains demand in mild "
        "recessions — limited-edition drops maintain pricing power.  In deeper "
        "recessions, consumers trade down to lower-priced athletic brands (New "
        "Balance, adidas, Hoka's lower-end lines).  Jordan Brand's premium "
        "positioning makes it slightly more resilient than core Nike.  "
        "China represents ~16% of revenue — geopolitical and COVID-related "
        "disruptions have periodically reduced China Direct revenue."
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
        "Athlete endorsement depth: LeBron James, Serena Williams (posthumous "
        "brand), Cristiano Ronaldo, Kylian Mbappé, Travis Scott — Nike spends "
        "$3.5B/year on athletes, creating a moat competitors cannot economically bridge",
        "SNKRS and consumer data: 300M+ member profiles with purchase history, "
        "size preferences, and wishlist data enable hyper-targeted launch allocation "
        "and demand forecasting impossible for DTC-light brands",
        "Scale manufacturing relationships: Vietnam and Indonesia factory "
        "partnerships spanning 30+ years — Nike receives priority capacity "
        "and quality standards that new entrants cannot access",
    ],
    business_model_keywords=[
        "Jordan Brand", "Nike Direct", "DTC", "SNKRS", "Air Max", "Air Force 1",
        "Elliott Hill", "John Donahoe", "Dunk", "React", "ZoomX",
        "Dri-FIT", "Nike Membership", "wholesale", "Converse",
        "gross margin", "inventory", "China Direct", "performance running",
        "Vomero", "Pegasus", "Win Now", "organic growth",
    ],
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
        "Long-term US DoD contracts: F-15 production, KC-46 tanker, and other "
        "multi-year defense programs provide stable government revenue stream",
        "Training services: Boeing's training centers for pilot simulation and "
        "maintenance technicians for airlines worldwide",
        "737 MAX and 787 reorder stream: United, American, Southwest, Ryanair, "
        "and international carriers have multi-year delivery schedules on order",
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
        "Commercial airline backlog stickiness: 5,600-aircraft backlog represents "
        "years of advance deposits and contractual delivery obligations — even "
        "severely distressed Boeing retains this forward revenue foundation",
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
        "FPL rate base revenue: Florida Public Service Commission regulates FPL's "
        "rates based on cost-of-service + allowed ROE — near-guaranteed revenue "
        "regardless of economic cycle as long as customers pay bills",
        "NEER long-term PPAs: 15-20 year fixed-price or CPI-linked power "
        "purchase agreements with rated utilities (Duke, ConEd, Xcel) — "
        "contractual cash flows for the life of each wind/solar project",
        "NEP distributions: NEP pays quarterly distributions to NEE from its "
        "operating wind and solar assets; distributions have grown 12-15% annually",
        "Renewable development pipeline: NEER has a record 30+ GW backlog "
        "of signed but not yet constructed projects — years of visible future earnings",
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
        "Highly defensive: utility earnings are economically insensitive.  "
        "FPL residential and commercial customers pay electric bills in "
        "recessions — Florida's customer growth (retirees, in-migration) "
        "provides structural volume support.  NEER's contracted renewable "
        "generation revenue is fixed by PPAs regardless of spot power prices "
        "or economic conditions.  NEE is widely held as a defensive income "
        "stock; dividend has grown every year for 30+ consecutive years."
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
