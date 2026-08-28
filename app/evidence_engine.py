"""
Phase 9F — Historical Evidence Engine.

Retrieves the most relevant historical analogs for the current analysis
by scoring against a SetupFingerprint derived from concern_tags, mechanisms,
and contextual signals in the thesis.

Design constraints:
  - NEVER injects analogs into the synthesis prompt (no LLM token impact).
  - Post-dispatch only: attaches historical_evidence to the final response.
  - Hard floor: returns [] when best score < RELEVANCE_FLOOR ("no analog" is valid).
  - Diversity: at most one analog per mechanism; returns top-3 distinct mechanisms.
  - Match on setup and mechanism — never on outcome alone.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RELEVANCE_FLOOR = 0.45   # Phase 7: ↑ 0.40→0.45 (better library → filter more aggressively)
TOP_K = 3                # maximum analogs returned (one per mechanism)
DISANALOGY_PENALTY = 0.03  # Phase 7: ↓ 0.05→0.03 (less punitive with better matching)

# ---------------------------------------------------------------------------
# Concern-tag → primary mechanism mapping
# ---------------------------------------------------------------------------

# Tags that map to a primary mechanism trigger that mechanism at 1.0 weight.
# Tags listed under "secondary" produce 0.7 weight via the mechanism scoring.
# "amplifier" tags have no mechanism but boost concern_tag_jaccard naturally.

_TAG_TO_PRIMARY_MECHANISM: Dict[str, str] = {
    "capex_cycle":          "infrastructure_overbuild",
    "supply_chain_risk":    "inventory_channel_correction",
    "macro_slowdown_risk":  "demand_air_pocket",
    "interest_rate_risk":   "rate_shock",
    "cre_credit_risk":      "credit_event",
    "valuation_risk":       "multiple_compression",
    "competitive_risk":     "competitive_displacement",
    "regulatory_risk":      "regulatory_break",
    "geopolitical_risk":    "regulatory_break",
    "att_privacy_risk":     "regulatory_break",
    "ai_adoption_risk":     "hypergrowth_deceleration",
    "currency_risk":        "commodity_shock",
    # amplifier / outcome tags — no primary mechanism
    # "concentration_risk":  no mechanism
    # "margin_pressure":     no mechanism
}

_TAG_TO_SECONDARY_MECHANISM: Dict[str, str] = {
    "capex_cycle":          "demand_air_pocket",
    "supply_chain_risk":    "demand_air_pocket",
    "macro_slowdown_risk":  "inventory_channel_correction",
    "interest_rate_risk":   "credit_event",
    "cre_credit_risk":      "rate_shock",
    "ai_adoption_risk":     "competitive_displacement",
    "competitive_risk":     "hypergrowth_deceleration",
}

# Mechanism siblings (partial credit: 0.5 on mechanism match)
_MECHANISM_SIBLINGS: Dict[str, str] = {
    "infrastructure_overbuild":     "inventory_channel_correction",
    "inventory_channel_correction": "infrastructure_overbuild",
    "demand_air_pocket":            "inventory_channel_correction",
    "multiple_compression":         "hypergrowth_deceleration",
    "hypergrowth_deceleration":     "multiple_compression",
    "rate_shock":                   "credit_event",
    "credit_event":                 "rate_shock",
    # Phase 7: new mechanism siblings
    "network_fee_compression":      "regulatory_break",
    "franchise_credibility_crisis": "regulatory_break",
    "export_control_restriction":   "regulatory_break",
    "patent_cliff":                 "competitive_displacement",
    "membership_elasticity_test":   "demand_air_pocket",
    "credit_cycle_loss":            "credit_event",
    "government_budget_cut":        "demand_air_pocket",
    "platform_transition":          "competitive_displacement",
}

# Structural mechanism priors by business model.  A sparse thesis often names
# the company but omits the mechanism explicitly; in that case an exact
# business-model match should still be able to surface the small set of failure
# modes inherent to that model.  The prior is deliberately partial (0.5), so a
# stated concern/mechanism always outranks it and an unrelated analog still
# cannot clear the relevance floor on business model alone.
_BUSINESS_MODEL_NATIVE_MECHANISMS: Dict[str, set[str]] = {
    "asset_manager": {"multiple_compression", "rate_shock"},
    "cloud_platform": {"multiple_compression"},
    "consumer_staples": {"competitive_displacement"},
    "consumer_hardware": {"demand_air_pocket"},
    "defense_contractor": {"government_budget_cut"},
    "diversified_bank": {"credit_event"},
    "e_commerce": {"multiple_compression"},
    "financial_intermediary": {"credit_event", "rate_shock"},
    "fintech_platform": {"hypergrowth_deceleration"},
    "government_enterprise": {"multiple_compression"},
    "integrated_oil": {"commodity_shock"},
    "industrial_equipment": {"demand_air_pocket"},
    "internet_platform": {"regulatory_break"},
    "life_science_tools": {"demand_air_pocket"},
    "media_platform": {"multiple_compression"},
    "membership_retail": {"multiple_compression"},
    "payment_network": {"network_fee_compression"},
    "pharma_pipeline": {"patent_cliff"},
    "regulated_utility": {"rate_shock"},
    "restaurant_chain": {"franchise_credibility_crisis"},
    "ratings_data_oligopoly": {"regulatory_break"},
    "saas": {"multiple_compression"},
    "semiconductor_equipment": {"demand_air_pocket"},
    "semiconductor_fabless": {"inventory_channel_correction"},
    "semiconductor_manufacturer": {"inventory_channel_correction"},
    "telecom_carrier": {"competitive_displacement"},
    "tower_reit": {"rate_shock"},
    "travel_marketplace": {"regulatory_break"},
}

# ---------------------------------------------------------------------------
# SetupFingerprint
# ---------------------------------------------------------------------------

@dataclass
class SetupFingerprint:
    """Derived at request time from the thesis and question context."""

    concern_tags: List[str] = field(default_factory=list)    # canonical tag names
    inferred_mechanisms: List[str] = field(default_factory=list)  # derived from tags
    ticker: Optional[str] = None
    sector: Optional[str] = None
    business_model: Optional[str] = None
    valuation_regime: Optional[str] = None   # peak_multiple | compressed | neutral | ""
    growth_phase: Optional[str] = None       # hypergrowth | deceleration | mature | ""
    macro_regime: Optional[str] = None       # hiking | easing | inversion | neutral | ""
    question_text: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_fingerprint(
    question: str,
    thesis_dict: dict,
    ticker: Optional[str] = None,
    profile: Optional[Any] = None,
) -> SetupFingerprint:
    """Build a SetupFingerprint from an InvestmentThesis dict and the question.

    Phase 7: When a CompanyKnowledgeProfile is provided and has structured
    durability fields populated (revenue_model non-empty), the business_model
    is taken from the profile instead of being inferred from thesis text.
    This makes the fingerprint deterministic for profiled companies.
    """
    concern_tags = _extract_concern_tags(thesis_dict)
    mechanisms = _infer_mechanisms(concern_tags, question, thesis_dict)
    sector, biz_model = _infer_sector_biz(thesis_dict, ticker)
    val_regime = _infer_valuation_regime(question, thesis_dict)
    growth_phase = _infer_growth_phase(question, thesis_dict)
    macro_regime = _infer_macro_regime(question, thesis_dict)

    # Phase 7: override business_model from profile when structured fields exist.
    # Maps revenue_model (how company earns) → analog business_model (what company is).
    _REVENUE_TO_BIZ_MODEL: Dict[str, str] = {
        "transaction_toll":  "payment_network",
        "subscription":      "saas",
        "membership":        "membership_retail",
        "licensing":         "cloud_platform",
        "project_contract":  "government_enterprise",
        "product_sale":      "consumer_hardware",
        "advertising":       "internet_platform",
        "mixed":             "financial_intermediary",
    }
    if profile is not None:
        _profile_biz = getattr(profile, "revenue_model", "")
        if _profile_biz:
            biz_model = _REVENUE_TO_BIZ_MODEL.get(_profile_biz, _profile_biz)
        # Ticker-specific overrides for companies whose revenue_model doesn't
        # map cleanly to their analog business_model category.
        _ticker_biz_overrides: Dict[str, str] = {
            "MSFT": "cloud_platform",
            "ORCL": "cloud_platform",
            "AMZN": "e_commerce",
            "AXP":  "payment_network",
            "KO":   "membership_retail",
            "MCD":  "restaurant_chain",
            "INTU": "internet_platform",
            "UNH":  "pharma_pipeline",
            "BLK":  "asset_manager",
            "SPGI": "ratings_data_oligopoly",
            "MCO":  "ratings_data_oligopoly",
            "MSCI": "ratings_data_oligopoly",
            "ASML": "semiconductor_equipment",
            "AMAT": "semiconductor_equipment",
            "LRCX": "semiconductor_equipment",
            "KLAC": "semiconductor_equipment",
            "JPM":  "diversified_bank",
            "BAC":  "diversified_bank",
            "C":    "diversified_bank",
            "WFC":  "diversified_bank",
            "GS":   "diversified_bank",
            "LLY":  "pharma_pipeline",
            "NVO":  "pharma_pipeline",
            "PFE":  "pharma_pipeline",
            "MRK":  "pharma_pipeline",
            "ABBV": "pharma_pipeline",
            "NVDA": "semiconductor_fabless",
            "AMD":  "semiconductor_fabless",
            "AVGO": "semiconductor_fabless",
            "TSM":  "semiconductor_manufacturer",
            "CAT":  "industrial_equipment",
            "MU":   "semiconductor_manufacturer",
            "INTC": "semiconductor_manufacturer",
            "XOM":  "integrated_oil",
            "RBLX": "internet_platform",
            "NFLX": "internet_platform",
            "PANW": "saas",
            "TMO":  "life_science_tools",
            "NEE":  "regulated_utility",
            "AMT":  "tower_reit",
            "CAVA": "restaurant_chain",
            "DIS":  "media_platform",
            "LMT":  "defense_contractor",
            "RTX":  "defense_contractor",
            "T":    "telecom_carrier",
            "PG":   "consumer_staples",
            "UBER": "travel_marketplace",
            "ABNB": "travel_marketplace",
            "TSLA": "consumer_hardware",
            "PLTR": "government_enterprise",
        }
        if ticker and ticker.upper() in _ticker_biz_overrides:
            biz_model = _ticker_biz_overrides[ticker.upper()]

        # Narrative-only sector inference is intentionally lightweight and can
        # miss terse benchmark/production theses.  Keep deterministic sector
        # metadata for profiled companies whose analog category is curated
        # above and whose sector is unambiguous.
        _ticker_sector_overrides: Dict[str, str] = {
            "MCO":  "financials",
            "MCD":  "consumer_discretionary",
            "BLK":  "financials",
            "CAT":  "industrials",
            "ADP":  "technology",
            "XOM":  "energy",
            "GS":   "financials",
            "ABBV": "healthcare",
            "PFE":  "healthcare",
            "TMO":  "healthcare",
            "NEE":  "utilities",
            "AMT":  "real_estate",
            "TSLA": "consumer_discretionary",
            "CAVA": "consumer_discretionary",
            "DIS":  "consumer_discretionary",
            "LMT":  "industrials",
            "RTX":  "industrials",
            "T":    "communication_services",
            "PG":   "consumer_staples",
            "UBER": "consumer_discretionary",
            "ABNB": "consumer_discretionary",
        }
        if ticker and ticker.upper() in _ticker_sector_overrides:
            sector = _ticker_sector_overrides[ticker.upper()]

    return SetupFingerprint(
        concern_tags=concern_tags,
        inferred_mechanisms=mechanisms,
        ticker=ticker,
        sector=sector,
        business_model=biz_model,
        valuation_regime=val_regime,
        growth_phase=growth_phase,
        macro_regime=macro_regime,
        question_text=question,
    )


def retrieve_historical_analogs(
    analogs,
    fingerprint: SetupFingerprint,
    floor: float = RELEVANCE_FLOOR,
    top_k: int = TOP_K,
) -> List[dict]:
    """Score all analogs against the fingerprint, apply floor, enforce diversity.

    Args:
        analogs: List[HistoricalAnalog] ORM objects (from get_all_analogs).
        fingerprint: SetupFingerprint derived from the current query.
        floor: minimum score threshold.
        top_k: max results (one per mechanism).

    Returns:
        List of dicts (serialisable payload for the response), [] if no strong match.
    """
    if not analogs or not fingerprint:
        return []

    scored: List[Tuple[float, object]] = []
    for analog in analogs:
        score = _score_analog(analog, fingerprint)
        if score >= floor:
            scored.append((score, analog))

    if not scored:
        return []

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Diversity: at most one analog per mechanism, take top_k
    seen_mechanisms: set = set()
    results = []
    for score, analog in scored:
        mech = analog.mechanism
        if mech in seen_mechanisms:
            continue
        seen_mechanisms.add(mech)
        results.append(_analog_to_dict(score, analog))
        if len(results) >= top_k:
            break

    return results


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# ── Business model partial-credit table ──────────────────────────────────────
# Related business models get partial credit (0.3–0.7) instead of binary 0/1.
_RELATED_BUSINESS_MODELS: Dict[tuple, float] = {
    ("diversified_bank", "financial_intermediary"):   0.7,
    ("cloud_platform", "saas"):                       0.6,
    ("payment_network", "fintech_platform"):           0.5,
    ("semiconductor_equipment", "semiconductor_manufacturer"): 0.4,
    ("semiconductor_equipment", "semiconductor_fabless"): 0.3,
    ("membership_retail", "e_commerce"):               0.3,
    ("government_enterprise", "saas"):                 0.3,
    ("ratings_data_oligopoly", "financial_intermediary"): 0.3,
}


def _business_model_score(query_biz: Optional[str], analog_biz: Optional[str]) -> float:
    """Score business model similarity with partial credit for related models."""
    if not query_biz or not analog_biz:
        return 0.3  # unknown → neutral (don't penalize or reward)
    if query_biz == analog_biz:
        return 1.0  # exact match
    pair = tuple(sorted([query_biz, analog_biz]))
    return _RELATED_BUSINESS_MODELS.get(pair, 0.0)


def _score_analog(analog, fp: SetupFingerprint) -> float:
    """Compute composite relevance score (0–1) for one analog.

    Phase 7 reweight: business_model is now the dominant signal (0.30),
    concern-tag Jaccard reduced from 0.40 to 0.15 to prevent generic-tag
    matches across unrelated business models.

    Weights:
      0.30 × business_model_score  (exact, partial-credit, or zero)
      0.25 × mechanism_match       (exact or sibling)
      0.15 × concern_tag_jaccard   (set overlap)
      0.10 × sector_match          (binary)
      0.10 × setup_match           (valuation + growth phase)
      0.05 × macro_regime_match    (binary)
      + 0.02 quality boost (strong only)
      − 0.03 disanalogy penalty
    """
    # 1. Business model similarity (weight 0.30)
    biz_score = _business_model_score(fp.business_model, getattr(analog, "business_model", ""))

    # 2. Mechanism match (weight 0.25)
    mech_score = 0.0
    for inferred_mech in (fp.inferred_mechanisms or []):
        ms = _mechanism_score(inferred_mech, analog.mechanism)
        if ms > mech_score:
            mech_score = ms
    for tag in fp.concern_tags:
        primary = _TAG_TO_PRIMARY_MECHANISM.get(tag)
        if primary:
            ms = _mechanism_score(primary, analog.mechanism)
            if ms > mech_score:
                mech_score = ms

    # Exact business-model matches carry a conservative structural prior for
    # mechanisms native to that model.  This recovers useful analogs when the
    # generated thesis is sparse without weakening the global relevance floor.
    analog_biz = getattr(analog, "business_model", "")
    native_mechanisms = _BUSINESS_MODEL_NATIVE_MECHANISMS.get(fp.business_model or "", set())
    if fp.business_model == analog_biz and analog.mechanism in native_mechanisms:
        mech_score = max(mech_score, 0.5)

    # 3. Concern-tag Jaccard (weight 0.15)
    analog_tags = set(analog.concern_tags or [])
    fp_tags = set(fp.concern_tags or [])
    if analog_tags or fp_tags:
        intersection = len(analog_tags & fp_tags)
        union = len(analog_tags | fp_tags)
        tag_score = intersection / union if union else 0.0
    else:
        tag_score = 0.0

    # 4. Sector match (weight 0.10)
    sector_score = 0.0
    if fp.sector and getattr(analog, "sector", "") and fp.sector == analog.sector:
        sector_score = 1.0

    # 5. Setup match: valuation_regime + growth_phase (weight 0.10)
    setup_score = 0.0
    if fp.valuation_regime and getattr(analog, "valuation_regime", None):
        if fp.valuation_regime == analog.valuation_regime:
            setup_score += 0.5
    if fp.growth_phase and getattr(analog, "growth_phase", None):
        if fp.growth_phase == analog.growth_phase:
            setup_score += 0.5

    # 6. Macro regime agreement (weight 0.05)
    macro_score = 0.0
    if fp.macro_regime and getattr(analog, "macro_regime", None):
        if fp.macro_regime == analog.macro_regime:
            macro_score = 1.0

    # Weighted composite
    raw = (
        0.30 * biz_score
        + 0.25 * mech_score
        + 0.15 * tag_score
        + 0.10 * sector_score
        + 0.10 * setup_score
        + 0.05 * macro_score
    )

    # Quality boost
    if getattr(analog, "quality_rating", "") == "strong":
        raw += 0.02

    # Disanalogy penalty (reduced from 0.05 to 0.03)
    raw -= 0.03

    return max(0.0, min(1.0, raw))


def _mechanism_score(query_mech: str, analog_mech: str) -> float:
    """1.0 primary match, 0.5 sibling, 0.0 none."""
    if not query_mech or not analog_mech:
        return 0.0
    if query_mech == analog_mech:
        return 1.0
    sibling = _MECHANISM_SIBLINGS.get(query_mech)
    if sibling and sibling == analog_mech:
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Fingerprint construction helpers
# ---------------------------------------------------------------------------

def _extract_concern_tags(thesis: dict) -> List[str]:
    """Extract concern tags from the thesis using multiple extraction strategies.

    Strategy 1: Structured concern_tags field (Phase 9C DB concern records — dicts
                or strings).  InvestmentThesis does NOT have this field, so this
                is a forward-compat path only.
    Strategy 2: key_risks strings — keyword-scanned for canonical tag patterns.
    Strategy 3: Narrative text (bear_thesis, macro_sensitivity, conclusion) —
                keyword-scanned.  The primary extraction path for InvestmentThesis.
    """
    tags: List[str] = []

    # Strategy 1: explicit concern_tags field (present on legacy/DB models)
    raw_tags = thesis.get("concern_tags") or []
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, str) and t in _CANONICAL_TAGS:
                tags.append(t)
            elif isinstance(t, dict):
                name = t.get("tag") or t.get("name") or t.get("tag_name") or ""
                if name and name in _CANONICAL_TAGS:
                    tags.append(name)

    # Strategy 2: keyword-scan key_risks list (InvestmentThesis has List[str])
    key_risks = thesis.get("key_risks") or []
    if isinstance(key_risks, list):
        for risk_text in key_risks:
            if isinstance(risk_text, str):
                _scan_text_for_tags(risk_text, tags)

    # Strategy 3: scan narrative fields
    for field in ("bear_thesis", "macro_sensitivity", "conclusion", "what_changes_the_thesis"):
        val = thesis.get(field) or ""
        if isinstance(val, str):
            _scan_text_for_tags(val, tags)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    _scan_text_for_tags(item, tags)

    # Strategy 4: macro_sensitivity dict keys (legacy models)
    macro = thesis.get("macro_sensitivity") or {}
    if isinstance(macro, dict):
        for k in macro:
            canonical = _normalize_to_canonical_tag(k)
            if canonical and canonical not in tags:
                tags.append(canonical)

    return list(dict.fromkeys(tags))  # deduplicate, preserve order


# Keyword patterns for each canonical tag — scanned against narrative text
_TAG_KEYWORDS: Dict[str, List[str]] = {
    "capex_cycle":          ["capex", "capital expenditure", "infrastructure spend", "data center build", "hyperscaler spend"],
    "supply_chain_risk":    ["supply chain", "inventory", "channel inventory", "supply constraint", "chip shortage"],
    "macro_slowdown_risk":  ["recession", "economic slowdown", "gdp", "demand slowdown", "consumer spending"],
    "interest_rate_risk":   ["interest rate", "rate hike", "fed", "federal reserve", "rate rise", "duration", "bond yield"],
    "cre_credit_risk":      ["commercial real estate", "cre", "loan default", "credit loss", "mortgage"],
    "valuation_risk":       ["valuation", "multiple", "overvalued", "p/e", "price-to-earnings", "expensive"],
    "competitive_risk":     ["competition", "competitor", "market share", "displacement", "amazon", "google", "microsoft", "amd"],
    "regulatory_risk":      ["regulation", "antitrust", "regulatory", "ftc", "doj", "gdpr", "privacy law"],
    "geopolitical_risk":    ["geopolit", "taiwan", "china", "tariff", "trade war", "sanctions", "export control"],
    "att_privacy_risk":     ["apple", "att", "privacy", "tracking", "idfa", "app tracking"],
    "ai_adoption_risk":     ["ai adoption", "ai transition", "model commodit", "open source model", "llm competition"],
    "currency_risk":        ["currency", "foreign exchange", "fx risk", "dollar strength", "yen", "euro"],
    "concentration_risk":   ["concentration", "customer concentration", "single customer", "hyperscaler depend"],
    "margin_pressure":      ["margin compress", "margin pressure", "gross margin", "pricing pressure", "cost inflation"],
}


def _scan_text_for_tags(text: str, tags: List[str]) -> None:
    """Scan text for canonical tag keywords; append matched tags to the list."""
    t = text.lower()
    for tag, keywords in _TAG_KEYWORDS.items():
        if tag not in tags and any(_keyword_matches(t, kw) for kw in keywords):
            tags.append(tag)


# These entries are intentional stems rather than complete words.  All other
# keywords require both left and right token boundaries, preventing short
# tokens such as ``cre`` and ``att`` from matching inside unrelated words.
_TAG_KEYWORD_PREFIXES = {
    "geopolit",
    "model commodit",
    "hyperscaler depend",
    "margin compress",
}


def _keyword_matches(text: str, keyword: str) -> bool:
    """Return whether a tag keyword occurs on safe alphanumeric boundaries."""
    escaped = re.escape(keyword)
    left_boundary = r"(?<![a-z0-9])"
    right_boundary = "" if keyword in _TAG_KEYWORD_PREFIXES else r"(?![a-z0-9])"
    return re.search(left_boundary + escaped + right_boundary, text) is not None


_CANONICAL_TAGS = set(_TAG_TO_PRIMARY_MECHANISM.keys()) | {"concentration_risk", "margin_pressure"}

_ALIAS_MAP: Dict[str, str] = {
    "rates":              "interest_rate_risk",
    "interest_rates":     "interest_rate_risk",
    "rate":               "interest_rate_risk",
    "capex":              "capex_cycle",
    "competition":        "competitive_risk",
    "regulation":         "regulatory_risk",
    "geopolitics":        "geopolitical_risk",
    "supply_chain":       "supply_chain_risk",
    "macro":              "macro_slowdown_risk",
    "currency":           "currency_risk",
    "credit":             "cre_credit_risk",
    "ai_adoption":        "ai_adoption_risk",
    "att":                "att_privacy_risk",
    "valuation":          "valuation_risk",
    "concentration":      "concentration_risk",
    "margin":             "margin_pressure",
}


def _normalize_to_canonical_tag(key: str) -> Optional[str]:
    k = key.lower().replace("-", "_").replace(" ", "_")
    if k in _CANONICAL_TAGS:
        return k
    return _ALIAS_MAP.get(k)


def _infer_mechanisms(tags: List[str], question: str, thesis: dict) -> List[str]:
    """Derive candidate mechanisms from concern tags and question text."""
    mechs = []
    for tag in tags:
        pm = _TAG_TO_PRIMARY_MECHANISM.get(tag)
        if pm and pm not in mechs:
            mechs.append(pm)
        sm = _TAG_TO_SECONDARY_MECHANISM.get(tag)
        if sm and sm not in mechs:
            mechs.append(sm)

    # Question-text heuristics
    q = question.lower()
    _kw_to_mech = [
        (["break", "bull case", "risk", "downside", "what could go wrong"], None),  # general
        (["inventory", "channel", "oversupply", "supply glut"],              "inventory_channel_correction"),
        (["overbuild", "overbuilt", "capex cycle", "buildout"],              "infrastructure_overbuild"),
        (["air pocket", "demand drop", "demand collapse", "pull-forward"],   "demand_air_pocket"),
        (["multiple", "de-rate", "re-rate", "valuation compress"],           "multiple_compression"),
        (["deceleration", "growth miss", "first miss", "growth stall"],      "hypergrowth_deceleration"),
        (["displace", "competition", "market share loss", "competitor"],      "competitive_displacement"),
        (["rates", "interest rate", "rate hike", "rate shock", "duration"],  "rate_shock"),
        (["credit", "default", "bank run", "balance sheet"],                 "credit_event"),
        (["regulation", "antitrust", "banned", "restricted"],                "regulatory_break"),
        (["commodity", "oil", "energy price", "raw material"],               "commodity_shock"),
    ]
    for keywords, mech in _kw_to_mech:
        if mech and any(kw in q for kw in keywords) and mech not in mechs:
            mechs.append(mech)

    return mechs


_SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "technology":            ["tech", "software", "hardware", "cloud", "ai", "semiconductor", "chip"],
    "financials":            ["bank", "financial", "credit", "insurance", "fintech", "reit", "mortgage"],
    "healthcare":            ["pharma", "biotech", "healthcare", "medical", "drug", "therapy"],
    "consumer_discretionary": ["retail", "consumer", "e-commerce", "fashion", "auto"],
    "energy":                ["oil", "gas", "energy", "crude", "refin"],
    "industrials":           ["industrial", "manufacturing", "aerospace", "defense", "transport"],
}

_BIZ_MODEL_KEYWORDS: Dict[str, List[str]] = {
    "saas":                    ["saas", "software as a service", "recurring revenue", "arr", "mrr"],
    "semiconductor_fabless":   ["fabless", "gpu", "chip design", "arm"],
    "semiconductor_manufacturer": ["foundry", "wafer", "tsmc", "memory", "dram", "nand"],
    "infrastructure_supplier": ["networking", "switch", "router", "interconnect"],
    "internet_platform":       ["platform", "social", "search", "marketplace", "ad"],
    "fintech_platform":        ["payment", "fintech", "checkout", "wallet"],
    "financial_intermediary":  ["bank", "lender", "broker", "dealer", "reit"],
    "consumer_hardware":       ["hardware", "device", "consumer electronics"],
    "integrated_oil":          ["integrated", "upstream", "downstream", "refining"],
}


def _infer_sector_biz(thesis: dict, ticker: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Try to infer sector and business model from thesis text."""
    text = " ".join([
        str(thesis.get("bull_thesis", "")),
        str(thesis.get("bear_thesis", "")),
        str(thesis.get("conclusion", "")),
        str(thesis.get("company_name", "")),
        str(ticker or ""),
    ]).lower()

    sector = None
    for s, keywords in _SECTOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            sector = s
            break

    biz_model = None
    for b, keywords in _BIZ_MODEL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            biz_model = b
            break

    return sector, biz_model


def _infer_valuation_regime(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("conclusion", ""))).lower()
    if any(kw in text for kw in ["overvalued", "peak multiple", "expensive", "bubble", "frothy", "60x", "50x", "40x"]):
        return "peak_multiple"
    if any(kw in text for kw in ["undervalued", "cheap", "compressed", "low multiple", "discounted"]):
        return "compressed"
    # Heuristic from confidence
    confidence = float(thesis.get("confidence_score") or 0)
    if confidence > 0.75:
        return "peak_multiple"
    return None


def _infer_growth_phase(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("bull_thesis", "")) + " " + str(thesis.get("conclusion", ""))).lower()
    if any(kw in text for kw in ["hypergrowth", "hyper-growth", "triple digit", "200%", "150%", "100% growth"]):
        return "hypergrowth"
    if any(kw in text for kw in ["decelerat", "slowdown", "growth missing", "growth miss", "mature"]):
        return "deceleration"
    if any(kw in text for kw in ["mature", "steady state", "single digit growth"]):
        return "mature"
    return None


def _infer_macro_regime(question: str, thesis: dict) -> Optional[str]:
    text = (question + " " + str(thesis.get("macro_sensitivity", ""))).lower()
    if any(kw in text for kw in ["rate hike", "hiking", "tightening", "fed raise", "rising rates"]):
        return "hiking"
    if any(kw in text for kw in ["rate cut", "easing", "dovish", "fed cut", "falling rates"]):
        return "easing"
    if any(kw in text for kw in ["inversion", "inverted", "yield curve inverted"]):
        return "inversion"
    return None


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _analog_to_dict(score: float, analog) -> dict:
    """Convert HistoricalAnalog ORM object to the response payload dict."""
    return {
        "label":                analog.label,
        "episode":              analog.episode,
        "entity_ticker":        analog.entity_ticker,
        "sector":               analog.sector,
        "mechanism":            analog.mechanism,
        "quality_rating":       analog.quality_rating,
        "drawdown_pct":         analog.drawdown_pct,
        "time_to_trough_days":  analog.time_to_trough_days,
        "time_to_recover_days": analog.time_to_recover_days,
        "outcome_summary":      analog.outcome_summary,
        "why_relevant":         analog.why_relevant,
        "disanalogy":           analog.disanalogy,
        "base_rate_note":       analog.base_rate_note,
        "data_confidence":      analog.data_confidence,
        "relevance_score":      round(score, 4),
    }
