"""
Post-synthesis thesis polisher.

Applies deterministic quality refinements to an InvestmentThesis after the
LLM synthesis call.  All operations are purely textual — no LLM calls, no
external API calls, no blocking I/O.

Refinements applied (in order):
  1. Concision enforcement
     Truncates verbose prose fields to their sentence-count targets and strips
     well-known filler openers (e.g. "It is worth noting that…").

  2. Cross-section redundancy suppression
     Walks sections in priority order (highest-value first), builds a pool of
     committed sentences, and removes sentences from lower-priority sections
     when their Jaccard similarity to a committed sentence exceeds the
     _DEDUP_THRESHOLD.  At least one sentence is always preserved per section
     to avoid creating empty fields.

Usage
-----
    from app.services.thesis_polisher import polish_thesis

    thesis = polish_thesis(thesis)   # in-place quality refinement
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from ..schemas import InvestmentThesis

# ── Financial mechanism taxonomy (Refinement 1 upgrade) ──────────────────────
# Maps mechanism tag → frozenset of keyword tokens that signal its presence.
# Mechanisms represent causal drivers; sentences sharing mechanisms express
# the same analytical idea even when worded differently.
_MECHANISM_TAXONOMY: Dict[str, frozenset] = {
    "valuation_multiple": frozenset({
        "pe", "p/e", "multiple", "forward", "trailing", "premium",
        "discount", "ev", "ebitda", "28x", "30x", "25x", "valuation",
    }),
    "dcf_rate_sensitivity": frozenset({
        "dcf", "discount", "rate", "wacc", "duration", "cash", "flow",
        "compress", "expand", "basis", "bps", "terminal",
    }),
    "margin_dynamics": frozenset({
        "margin", "gross", "operating", "net", "profitability",
        "expansion", "compression", "cost", "opex", "leverage",
    }),
    "revenue_quality": frozenset({
        "recurring", "subscription", "arr", "saas", "services",
        "contract", "retention", "churn", "sticky", "durable",
    }),
    "capital_return": frozenset({
        "buyback", "repurchase", "dividend", "yield", "share",
        "count", "dilution", "shrink", "shareholder", "capital",
    }),
    "rate_macro": frozenset({
        "rate", "fed", "federal", "reserve", "yield", "treasury",
        "interest", "monetary", "hike", "cut", "pause",
    }),
    "geopolitical_risk": frozenset({
        "china", "tariff", "supply", "chain", "export", "restriction",
        "ban", "geopolitic", "trade", "war", "sanction",
    }),
    "regulatory_risk": frozenset({
        "regulation", "antitrust", "compliance", "enforcement",
        "investigation", "doj", "ftc", "probe", "lawsuit",
    }),
    "growth_earnings": frozenset({
        "growth", "revenue", "earnings", "eps", "beat", "guidance",
        "revision", "estimate", "accelerat", "decelerat",
    }),
    "debt_leverage": frozenset({
        "debt", "leverage", "credit", "refinanc", "covenant",
        "rating", "liquidity", "solvency", "balance", "sheet",
    }),
    "hardware_cyclical": frozenset({
        "hardware", "device", "upgrade", "consumer", "demand",
        "cycle", "shipment", "unit", "asp", "volume",
    }),
    "competitive_moat": frozenset({
        "ecosystem", "switching", "lock", "network", "effect",
        "brand", "patent", "moat", "barrier", "differentiat",
    }),
}

# Concept-level dedup: lower Jaccard required when mechanism overlap fires.
# Catches paraphrases that pure Jaccard would miss (e.g., "Services offsets
# rate pressure" ≈ "Recurring cash flows buffer multiple compression").
_CONCEPT_JACCARD_FLOOR: float = 0.28


def extract_core_mechanisms(text: str) -> Set[str]:
    """Return set of mechanism tags found in *text*.

    Tokenises *text* and checks each token against ``_MECHANISM_TAXONOMY``.
    Returns a set of tag names (e.g. {'valuation_multiple', 'rate_macro'})
    that are present — empty set if the text has no recognisable mechanism.
    """
    tokens = _tokenize(text)
    found: Set[str] = set()
    for tag, keywords in _MECHANISM_TAXONOMY.items():
        if tokens & keywords:
            found.add(tag)
    return found

# ── Sentence limits (refinement 1) ────────────────────────────────────────────
# Maps InvestmentThesis field name → maximum number of sentences to keep.
# Targets are tighter than before: supporting sections (bull/bear, valuation,
# macro) must add only incremental information not already in direct_answer or
# the ranked signals, so shorter prose forces higher signal density.
_SENTENCE_LIMITS: Dict[str, int] = {
    # ── Top-level (stay compressed — terminal-density hero layer) ──────────────
    "direct_answer":    2,   # mechanism + company-specific offset — stays tight
    "conclusion":       2,   # inflection condition + positioning — stays tight
    # ── Analytical depth layer (hierarchically richer than top-level) ──────────
    # These sections MUST explain WHY the thesis works / breaks, not just assert it.
    # Prompt asks for 3-4 sentences; polisher allows up to 4 so the LLM's third
    # and fourth analytical sentence (operating leverage, second-order effects,
    # downside pathway) survive to the frontend.
    "bull_thesis":      4,   # driver + mechanism + leverage/capital effect + confirmation trigger
    "bear_thesis":      4,   # risk transmission + second-order effect + downside pathway + catalyst
    "valuation_view":   2,   # multiple structure/implicit pricing + sensitivity/segment contribution
    "macro_sensitivity": 2,  # primary channel + magnitude / directional bias
}

# ── Filler opener patterns (refinement 1) ─────────────────────────────────────
# Applied to each sentence after splitting. The opener is stripped and the
# remainder is title-cased at the start to restore capitalisation.
_FILLER_OPENERS: Tuple[str, ...] = (
    r"It is worth noting that\s+",
    r"It's worth noting that\s+",
    r"As is well known,\s+",
    r"It's important to mention that\s+",
    r"It is important to mention that\s+",
    r"As previously mentioned,\s+",
    r"As mentioned (?:earlier|above|before),\s+",
    r"In conclusion,\s+",
    r"In summary,\s+",
    r"To summarize,\s+",
    r"Overall, it is (?:clear|worth noting) that\s+",
    r"It should be noted that\s+",
    r"Notably,\s+",
    r"Furthermore,\s+",
    r"Additionally,\s+",
    r"Moreover,\s+",
    # Refinement 4 — conclusion summary phrases that restate rather than add
    r"Overall,\s+",
    r"On balance,\s+",
    r"Taken together,\s+",
    r"All in all,\s+",
    r"In light of (?:the above|this),\s+",
    r"To sum (?:up|it up),\s+",
)

# Pre-compiled filler regexes (case-insensitive, anchored to start of sentence)
_FILLER_RES = [re.compile(r"^(?:" + p + r")", re.IGNORECASE) for p in _FILLER_OPENERS]

# ── Section priority for cross-section dedup (refinement 2) ──────────────────
# Sections listed first are highest-priority (their sentences are committed
# first and protected from suppression; later sections get suppressed when
# their sentences duplicate committed ones).
_SECTION_PRIORITY: Tuple[str, ...] = (
    "direct_answer",
    "conclusion",
    "bull_thesis",
    "bear_thesis",
    "valuation_view",
    "macro_sensitivity",
)

# Jaccard threshold for cross-section sentence dedup.
# 0.55 catches near-verbatim repetition while preserving same-topic rewrites.
_DEDUP_THRESHOLD: float = 0.55

# Stopwords for tokenisation (same approach as signal_ranker for consistency)
_STOPWORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "will", "would", "may", "might", "could", "should",
    "its", "it", "this", "that", "as", "not", "no", "also", "both", "while",
    "which", "their", "they", "we", "our", "if", "when", "than",
})


# ── Tokenisation helpers ──────────────────────────────────────────────────────

def _tokenize(text: str) -> Set[str]:
    """Return content word tokens (stopwords removed, lower-cased, len > 2)."""
    words = re.findall(r"\b\w+\b", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a: str, b: str) -> float:
    """Jaccard similarity between word-token sets of two strings."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── Sentence splitting ────────────────────────────────────────────────────────

# Sentence boundary: sentence-ending punctuation followed by whitespace.
# Handles "U.S." and decimal numbers crudely — good enough for output text.
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> List[str]:
    """Split prose text into individual sentences, stripping whitespace."""
    if not text or not text.strip():
        return []
    parts = _SENT_BOUNDARY.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _join_sentences(sentences: List[str]) -> str:
    """Re-join a sentence list into a single paragraph string."""
    if not sentences:
        return ""
    # Ensure each sentence ends with terminal punctuation
    fixed = []
    for s in sentences:
        s = s.strip()
        if s and s[-1] not in ".!?":
            s += "."
        fixed.append(s)
    return " ".join(fixed)


# ── Filler stripping ─────────────────────────────────────────────────────────

def _strip_filler_opener(sentence: str) -> str:
    """Remove known filler openers from the start of a sentence.

    After stripping, capitalises the first remaining character to preserve
    proper sentence capitalisation.
    """
    for pattern in _FILLER_RES:
        m = pattern.match(sentence)
        if m:
            remainder = sentence[m.end():].strip()
            if remainder:
                # Re-capitalise the start of the stripped sentence
                return remainder[0].upper() + remainder[1:]
    return sentence


def strip_filler_openers(text: str) -> str:
    """Apply filler-opener stripping to every sentence in *text*."""
    sentences = _split_sentences(text)
    return _join_sentences([_strip_filler_opener(s) for s in sentences])


# ── Concision enforcement ─────────────────────────────────────────────────────

def _truncate_to_sentences(text: str, max_sentences: int) -> str:
    """Truncate *text* to at most *max_sentences* sentences.

    Filler openers are stripped from each sentence before truncation.
    The last kept sentence always ends with terminal punctuation.
    """
    sentences = _split_sentences(text)
    cleaned = [_strip_filler_opener(s) for s in sentences]
    truncated = cleaned[:max_sentences]
    return _join_sentences(truncated)


def enforce_concision(thesis: InvestmentThesis) -> InvestmentThesis:
    """Apply sentence-count limits to verbose prose fields.

    Returns a new InvestmentThesis with all prose fields trimmed to their
    sentence targets.  Non-prose fields (key_drivers, key_risks, etc.) are
    unchanged.

    Sentence targets (hierarchical — top-level stays compressed, analytical depth
    sections allow more sentences so operating leverage / second-order effects survive)
    ---------------------------------------------------------------------------------
    direct_answer    : 2 sentences  — mechanism + offset (ultra-compressed hero layer)
    conclusion       : 2 sentences  — inflection condition + positioning
    bull_thesis      : 4 sentences  — driver + mechanism + leverage/capital + confirmation
    bear_thesis      : 4 sentences  — transmission + second-order + downside path + catalyst
    valuation_view   : 2 sentences  — multiple structure + sensitivity/segment logic
    macro_sensitivity: 2 sentences  — primary channel + magnitude quantification
    """
    updates: Dict[str, str] = {}
    for field_name, max_sents in _SENTENCE_LIMITS.items():
        original: str = getattr(thesis, field_name, "") or ""
        if not original.strip():
            continue
        trimmed = _truncate_to_sentences(original, max_sents)
        if trimmed != original:
            updates[field_name] = trimmed

    if not updates:
        return thesis

    # Return an updated copy (model_copy for pydantic v2 / copy for v1)
    if hasattr(thesis, "model_copy"):
        return thesis.model_copy(update=updates)
    return thesis.copy(update=updates)  # type: ignore[attr-defined]


# ── Cross-section redundancy suppression ──────────────────────────────────────

def _suppress_redundant_sentences(
    sections: Dict[str, str],
    priority: Tuple[str, ...],
    threshold: float = _DEDUP_THRESHOLD,
    pre_committed: Optional[List[str]] = None,
    concept_floor: float = _CONCEPT_JACCARD_FLOOR,
) -> Dict[str, str]:
    """Remove redundant sentences from lower-priority sections.

    Walks sections in *priority* order, committing each kept sentence to a
    shared pool.  Subsequent sections' sentences are checked against the
    committed pool; those with Jaccard ≥ threshold are dropped.

    At least one sentence per section is always preserved (the one with the
    lowest similarity to the pool, or the first sentence if all exceed the
    threshold).

    Parameters
    ----------
    sections      : Mapping from field name to prose text.
    priority      : Ordered tuple of field names, highest-priority first.
    threshold     : Jaccard threshold above which a sentence is redundant.
    pre_committed : Optional list of sentences already "committed" before this
                    pass starts.  Used to inject signal text so that supporting
                    prose sections do not repeat signal concepts.
    concept_floor : Minimum Jaccard similarity required (in addition to full
                    mechanism containment) for concept-level suppression.
                    Raise this for analytical sections so that mechanistically-
                    related elaborations (which share mechanism tags with the
                    top-level but add new operating-leverage or pathway detail)
                    are kept rather than suppressed.

    Returns
    -------
    Dict with the same keys, values replaced by de-duplicated prose.
    """
    committed: List[str] = list(pre_committed) if pre_committed else []
    # Track mechanism tags of all committed sentences for concept-level dedup
    committed_mechanisms: Set[str] = set()
    for s in committed:
        committed_mechanisms.update(extract_core_mechanisms(s))

    result: Dict[str, str] = {}

    for field_name in priority:
        text = sections.get(field_name, "") or ""
        sentences = _split_sentences(text)
        if not sentences:
            result[field_name] = text
            continue

        kept: List[str] = []
        suppressed: List[Tuple[float, str]] = []  # (max_sim, sentence)

        for sent in sentences:
            if not committed:
                kept.append(sent)
                committed.append(sent)
                committed_mechanisms.update(extract_core_mechanisms(sent))
                continue

            max_sim = max(_jaccard(sent, c) for c in committed)

            # Concept-level check: suppress if mechanisms are fully contained
            # in committed pool AND sentence has a baseline lexical overlap.
            # This catches paraphrases that pure Jaccard under-weights.
            # For supporting analytical sections a higher concept_floor is passed
            # so that mechanistically-related elaborations (operating leverage,
            # downside pathways, sensitivity logic) survive even when they share
            # mechanism tags with the already-committed direct_answer/conclusion.
            sent_mechs = extract_core_mechanisms(sent)
            is_concept_redundant = (
                bool(sent_mechs)
                and sent_mechs.issubset(committed_mechanisms)
                and max_sim >= concept_floor
            )

            if max_sim >= threshold or is_concept_redundant:
                suppressed.append((max_sim, sent))
            else:
                kept.append(sent)
                committed.append(sent)
                committed_mechanisms.update(sent_mechs)

        # Safety: never leave a section fully empty
        if not kept and suppressed:
            least_redundant = min(suppressed, key=lambda x: x[0])[1]
            kept.append(least_redundant)
            committed.append(least_redundant)
            committed_mechanisms.update(extract_core_mechanisms(least_redundant))

        result[field_name] = _join_sentences(kept)

    # Carry over any sections not in the priority list unchanged
    for k, v in sections.items():
        if k not in result:
            result[k] = v

    return result


def suppress_redundancy(thesis: InvestmentThesis) -> InvestmentThesis:
    """Remove cross-section repeated concepts from an InvestmentThesis.

    Two-pass signal-aware redundancy suppression:

    Pass 1 — primary sections (direct_answer, conclusion):
      Processed against each other in priority order.  No pre-committed
      context, so direct_answer is fully protected.

    Pass 2 — supporting sections (bull_thesis, bear_thesis, valuation_view,
      macro_sensitivity): Processed against a pre-committed pool that
      combines Pass-1 sentences PLUS the text of the top ranked signals.
      This ensures supporting prose adds only incremental information not
      already captured in direct_answer, conclusion, or the ranked signals.

    At least one sentence per section is always preserved.
    """
    _PRIMARY   = ("direct_answer", "conclusion")
    _SUPPORTING = ("bull_thesis", "bear_thesis", "valuation_view", "macro_sensitivity")

    # ── Pass 1: primary sections ──────────────────────────────────────────────
    primary_sections: Dict[str, str] = {
        f: (getattr(thesis, f, "") or "") for f in _PRIMARY
    }
    primary_result = _suppress_redundant_sentences(primary_sections, _PRIMARY)

    # Collect committed sentences from pass 1 for use in pass 2
    pass1_committed: List[str] = []
    for f in _PRIMARY:
        pass1_committed.extend(_split_sentences(primary_result.get(f, "") or ""))

    # ── Signal context for pass 2 ─────────────────────────────────────────────
    # Inject top signal text so supporting sections don't repeat signal concepts
    signal_committed: List[str] = []
    for sig in (getattr(thesis, "top_signals", None) or [])[:3]:
        if getattr(sig, "signal", None):
            signal_committed.append(sig.signal)
    for sig in (getattr(thesis, "top_risks", None) or [])[:3]:
        if getattr(sig, "signal", None):
            signal_committed.append(sig.signal)

    # ── Pass 2: supporting sections ───────────────────────────────────────────
    # Use a higher concept_floor (0.45 vs the global 0.28) so that analytical
    # elaboration sentences in bull/bear/valuation/macro survive dedup even when
    # they share mechanism tags with the top-level direct_answer or conclusion.
    # The whole purpose of these sections IS to explain WHY/HOW via the same
    # mechanisms — we only want to suppress near-verbatim repetition, not depth.
    supporting_sections: Dict[str, str] = {
        f: (getattr(thesis, f, "") or "") for f in _SUPPORTING
    }
    supporting_result = _suppress_redundant_sentences(
        supporting_sections,
        _SUPPORTING,
        pre_committed=pass1_committed + signal_committed,
        concept_floor=0.45,  # raise from global 0.28 → keep analytical elaborations
    )

    # ── Build updates ─────────────────────────────────────────────────────────
    updates: Dict[str, str] = {}
    for f in _PRIMARY:
        original = primary_sections[f]
        polished = primary_result.get(f, original)
        if polished != original:
            updates[f] = polished
    for f in _SUPPORTING:
        original = supporting_sections[f]
        polished = supporting_result.get(f, original)
        if polished != original:
            updates[f] = polished

    if not updates:
        return thesis

    if hasattr(thesis, "model_copy"):
        return thesis.model_copy(update=updates)
    return thesis.copy(update=updates)  # type: ignore[attr-defined]


# ── Institutional language rewriter (Refinement 2) ───────────────────────────
# Applied per-sentence after concision enforcement.  Each rule is (pattern, replacement).
# Rules are ordered: most specific first.  Only safe, high-confidence rewrites included —
# no rule changes meaning, only removes robotic syntax or AI compression artifacts.
_INSTITUTIONAL_REWRITES: List[Tuple[re.Pattern, str]] = [
    # Robotic sentence starters → analyst phrasing
    (re.compile(r'^This\s+indicates?\s+that\s+', re.IGNORECASE),  "The evidence suggests "),
    (re.compile(r'^This\s+indicates?\s+',         re.IGNORECASE),  "The evidence suggests "),
    (re.compile(r'^This\s+shows?\s+that\s+',      re.IGNORECASE),  "The data reflects "),
    (re.compile(r'^This\s+demonstrates?\s+that\s+', re.IGNORECASE), "This reflects "),
    (re.compile(r'^This\s+demonstrates?\s+',      re.IGNORECASE),  "This reflects "),
    (re.compile(r'^This\s+suggests?\s+that\s+',   re.IGNORECASE),  "This points to "),

    # Corporate stall verbs
    (re.compile(r'\bThe\s+company\s+remains\b',   re.IGNORECASE),  "The stock maintains"),
    (re.compile(r'\bThe\s+company\s+continues\b', re.IGNORECASE),  "The company"),
    (re.compile(r'\bpoised\s+to\b',               re.IGNORECASE),  "positioned to"),

    # Refinement 2 — "continues to X" → conjugated verb (removes helper-verb padding)
    # Ordered longest-match first to avoid partial matches.
    (re.compile(r'\bcontinues\s+to\s+outperform\b', re.IGNORECASE), "outperforms"),
    (re.compile(r'\bcontinues\s+to\s+strengthen\b',  re.IGNORECASE), "strengthens"),
    (re.compile(r'\bcontinues\s+to\s+dominate\b',    re.IGNORECASE), "dominates"),
    (re.compile(r'\bcontinues\s+to\s+generate\b',    re.IGNORECASE), "generates"),
    (re.compile(r'\bcontinues\s+to\s+compress\b',    re.IGNORECASE), "compresses"),
    (re.compile(r'\bcontinues\s+to\s+pressure\b',    re.IGNORECASE), "pressures"),
    (re.compile(r'\bcontinues\s+to\s+increase\b',    re.IGNORECASE), "increases"),
    (re.compile(r'\bcontinues\s+to\s+provide\b',     re.IGNORECASE), "provides"),
    (re.compile(r'\bcontinues\s+to\s+deliver\b',     re.IGNORECASE), "delivers"),
    (re.compile(r'\bcontinues\s+to\s+support\b',     re.IGNORECASE), "supports"),
    (re.compile(r'\bcontinues\s+to\s+benefit\b',     re.IGNORECASE), "benefits"),
    (re.compile(r'\bcontinues\s+to\s+expand\b',      re.IGNORECASE), "expands"),
    (re.compile(r'\bcontinues\s+to\s+weigh\b',       re.IGNORECASE), "weighs"),
    (re.compile(r'\bcontinues\s+to\s+trade\b',       re.IGNORECASE), "trades"),
    (re.compile(r'\bcontinues\s+to\s+drive\b',       re.IGNORECASE), "drives"),
    (re.compile(r'\bcontinues\s+to\s+face\b',        re.IGNORECASE), "faces"),
    (re.compile(r'\bcontinues\s+to\s+grow\b',        re.IGNORECASE), "grows"),

    # Refinement 6 — final synthetic construction filter
    # Each pattern targets a specific "AI finance" turn of phrase and replaces
    # it with a tighter institutional equivalent.
    (re.compile(r'\bremains\s+compelling\b',           re.IGNORECASE),
     "offers asymmetric risk/reward"),
    (re.compile(
        r'\bsupports?\s+(?:a\s+)?higher\s+(?:blended\s+)?(?:P/E\s+)?multiple\b',
        re.IGNORECASE,
    ), "sustains valuation multiple"),
    (re.compile(r'\bsupports?\s+(?:a\s+)?higher\s+valuation\b', re.IGNORECASE),
     "supports valuation"),
    (re.compile(r'\bcontributes?\s+to\s+(?:overall\s+)?growth\b', re.IGNORECASE),
     "drives growth"),
    (re.compile(r'\boffsets?\s+(?:the\s+)?pressure\b',  re.IGNORECASE), "absorbs pressure"),
    (re.compile(r'\bindicates?\s+strength\b',            re.IGNORECASE), "signals strength"),
    (re.compile(r'\bstrategically\s+positioned\b',       re.IGNORECASE), "positioned"),

    # Refinement 3 — Elite institutional phrase substitutions
    # Each replaces educational/generic finance language with PM-memo density.
    # Ordered to avoid cascading conflicts: more-specific patterns first.
    (re.compile(r'\bhigh-margin\s+segment\b',            re.IGNORECASE),
     "recurring high-margin revenue"),
    (re.compile(r'\bhigh\s+gross\s+margin\b',            re.IGNORECASE),
     "structurally high margin"),
    (re.compile(r'\bstrong\s+margins?\b',                re.IGNORECASE), "margin durability"),
    (re.compile(r'\bprovides?\s+(?:a\s+)?buffer\b',      re.IGNORECASE), "cushions downside"),
    (re.compile(r'\bsupports?\s+(?:its\s+)?resilience\b', re.IGNORECASE), "cushions downside"),
    (re.compile(r'\bpremium\s+valuation\b',              re.IGNORECASE), "elevated valuation multiple"),
    (re.compile(r'\bpremium\s+multiple\b',               re.IGNORECASE), "elevated valuation multiple"),
    (re.compile(r'\bpricing\s+power\b',                  re.IGNORECASE), "demand resilience"),
    (re.compile(r'\bimpacting\s+revenue\b',              re.IGNORECASE), "pressuring earnings"),
    # "supports valuation" → "stabilizes valuation" (upgrade from prior phase's replacement)
    (re.compile(r'\bsupports?\s+valuation\b',            re.IGNORECASE), "stabilizes valuation"),
    # Banned institutional clichés — replace with specific mechanism language
    (re.compile(r'\binvestors?\s+should\s+monitor\b',    re.IGNORECASE), "watch for"),
    (re.compile(r'\bsupports?\s+structural\s+P/?E\s+expansion\b', re.IGNORECASE),
     "expands the earnings multiple"),
    (re.compile(r'\bresilient\s+against\b',              re.IGNORECASE), "absorbs pressure from"),

    # Refinement 4 — Conclusion cadence: "However" at sentence start → "Yet"
    # "However," is a generic transition that slows prose; "Yet" is tighter.
    (re.compile(r'^However,\s+', re.IGNORECASE), "Yet "),

    # Trailing temporal filler (remove)
    (re.compile(r',?\s+(?:going|moving)\s+forward[.,]?$', re.IGNORECASE), "."),
    (re.compile(r',?\s+in\s+the\s+(?:long|near|medium)\s+(?:run|term)[.,]?$', re.IGNORECASE), "."),
    (re.compile(r',?\s+over\s+time[.,]?$',        re.IGNORECASE),  "."),
]


def institutional_phrase_rewriter(text: str) -> str:
    """Apply institutional language rewrites to a prose string.

    Processes sentence by sentence, applying each rewrite rule to every
    sentence.  Strips trailing whitespace and normalises terminal punctuation
    after each rewrite pass.

    Rules are conservative — each targets a specific, reliably improvable
    pattern.  No rule changes the information content of a sentence.
    """
    if not text or not text.strip():
        return text

    sentences = _split_sentences(text)
    rewritten: List[str] = []

    for sent in sentences:
        for pattern, replacement in _INSTITUTIONAL_REWRITES:
            sent = pattern.sub(replacement, sent).strip()
        # Normalise terminal punctuation after rewrites
        if sent and sent[-1] not in ".!?":
            sent += "."
        rewritten.append(sent)

    return " ".join(rewritten)


# ── Hero-thesis compression (Refinement 1) ────────────────────────────────────
# Applied to one_sentence_thesis to strip verbose structural patterns and
# truncate to terminal-grade word count.  Pairs with the institutional rewrites
# above — by the time compress_hero_thesis() is called, "continues to expand"
# has already been contracted to "expands" by institutional_phrase_rewriter().
_HERO_COMPRESSION_RES: List[Tuple[re.Pattern, str]] = [
    # "[high conviction, 75%]" / "[moderate conviction, 62%]" confidence bracket
    (re.compile(r'\s*\[(?:high|moderate|low)\s+conviction[^\]]*\]', re.IGNORECASE), ''),
    # ", with its [phrase]," — parenthetical elaboration mid-sentence
    (re.compile(r',\s+with\s+its\s+[^,]+,', re.IGNORECASE), ','),
    # ", which [clause]," — relative clause elaboration
    (re.compile(r',\s+which\s+[^,]+,', re.IGNORECASE), ','),
    # trailing ", offsetting X [and supporting Y]" — use \.? to consume trailing period
    (re.compile(r',\s+offsetting\s+[^.]*\.?\s*$', re.IGNORECASE), ''),
    # trailing ", [and] supporting [a higher] X"
    (re.compile(r',\s+(?:and\s+)?supporting\s+(?:a\s+)?(?:higher\s+)?[^.]*\.?\s*$',
                re.IGNORECASE), ''),
    # trailing ", contributing X"
    (re.compile(r',\s+contributing\s+[^.]*\.?\s*$', re.IGNORECASE), ''),
    # double-comma artefacts: ",," → ","
    (re.compile(r',\s*,'), ','),
    # comma-period artefacts: ",." → "."
    (re.compile(r',\s*\.'), '.'),
]


def compress_hero_thesis(text: str, max_words: int = 18) -> str:
    """Compress a verbose hero-thesis string to terminal-grade density.

    Targets ``one_sentence_thesis`` specifically.  Strips confidence-score
    brackets (``[high conviction, 75%]``), parenthetical elaborations
    (``"with its…"``), and trailing gerund chains
    (``"…offsetting X and supporting Y"``).  Truncates at *max_words* when
    the sentence remains too long after structural stripping.

    Rules
    -----
    - First sentence only (hero thesis is one sentence by design).
    - Strip ``[high/moderate/low conviction, X%]`` qualifier.
    - Remove ``", with its [phrase],"`` parentheticals.
    - Remove trailing ``"offsetting X [and supporting Y]"`` chains.
    - Truncate at *max_words* at the last clause boundary (comma / conjunction).

    Parameters
    ----------
    text     : Raw hero-thesis string (may include confidence bracket).
    max_words: Target maximum word count (default 18 — Bloomberg/PM-note density).

    Returns
    -------
    Compressed single-sentence string ending with terminal punctuation.
    """
    if not text or not text.strip():
        return text

    # Take first sentence only
    sentences = _split_sentences(text)
    if not sentences:
        return text
    sent = sentences[0]

    # Apply hero compression patterns sequentially
    for pattern, replacement in _HERO_COMPRESSION_RES:
        sent = pattern.sub(replacement, sent).strip()

    # Collapse double spaces introduced by stripping
    sent = re.sub(r'\s+', ' ', sent).strip()

    # Truncate to max_words at the last natural clause boundary
    words = sent.split()
    if len(words) > max_words:
        candidate = ' '.join(words[:max_words])
        # Prefer to cut at last comma within the candidate for clean grammar
        last_comma = candidate.rfind(',')
        if last_comma > len(candidate) // 2:
            candidate = candidate[:last_comma]
        # Drop trailing conjunction if we cut mid-coordination
        candidate = re.sub(
            r'\s+(?:and|but|or|while|despite|though|although)\s*$',
            '', candidate, flags=re.IGNORECASE,
        ).strip()
        sent = candidate

    # Ensure terminal punctuation
    if sent and sent[-1] not in '.!?':
        sent += '.'

    return sent


# ── Confidence naturalization (Refinement 3) ──────────────────────────────────
# Strips mechanical confidence-score citations from confidence_reasoning text.
# Converts agent-name + percentage references to analyst-style qualitative prose.

# Patterns that betray mechanical LLM confidence citation
_CONFIDENCE_STRIP_RES: List[re.Pattern] = [
    # "X% confidence" / "confidence of X%"
    re.compile(r'\b\d+(?:\.\d+)?%\s+confidence\b',          re.IGNORECASE),
    re.compile(r'\bconfidence\s+(?:score\s+)?of\s+\d+(?:\.\d+)?%?\b', re.IGNORECASE),
    re.compile(r'\bat\s+\d+(?:\.\d+)?(?:%|)\s*confidence\b', re.IGNORECASE),
    # "register X%" / "at X confidence"
    re.compile(r'\bregister\s+\d+(?:\.\d+)?%\b',             re.IGNORECASE),
]

# Agent-name patterns — replace with generic reference
_AGENT_NAME_RE = re.compile(
    r'\b(?:the\s+)?(valuation|macro|risk|market|quality)\s+agent\b',
    re.IGNORECASE,
)
_AGENT_PLURAL_RE = re.compile(
    r'\bagents?\s+(register|show|indicate|signal)\b',
    re.IGNORECASE,
)


def naturalize_confidence(text: str) -> str:
    """Convert mechanical confidence citations to analyst-style prose.

    Strips patterns like "macro agents register 30% confidence" and agent-name
    references, leaving the surrounding analytical framing intact.  The result
    reads like a PM commentary note rather than an automated scoring report.
    """
    if not text:
        return text

    for pattern in _CONFIDENCE_STRIP_RES:
        text = pattern.sub("", text)

    text = _AGENT_NAME_RE.sub(r"\1 analysis", text)
    text = _AGENT_PLURAL_RE.sub(r"evidence \1s", text)

    # Clean up orphaned punctuation and double spaces
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s+([,;.])', r'\1', text)
    text = re.sub(r'^[,;\s]+', '', text)
    return text.strip()


# ── Confidence prose de-numericalization (Refinement 3 — frontend pass) ──────
# Frontend-facing confidence_reasoning MUST never expose raw percentages.
# naturalize_confidence_prose() is a second, stronger pass that strips ALL
# remaining percentage values after naturalize_confidence() has already
# removed the most mechanical citation patterns.

# Pre-rewrites: convert percentage-qualified phrases to qualitative equivalents
# BEFORE the bare-number strip, so we produce meaningful replacements.
_CONF_PROSE_REWRITES_PRE: List[Tuple[re.Pattern, str]] = [
    # "is X% bullish/bearish" → "leans bullish/bearish"
    (re.compile(r'\bis\s+\d+(?:\.\d+)?%\s+(bullish|bearish)\b', re.IGNORECASE),
     r'leans \1'),
    # "averaging X% across" → "broadly aligned across"
    (re.compile(r'\baveraging\s+\d+(?:\.\d+)?%\s+across\b', re.IGNORECASE),
     'broadly aligned across'),
    # "(each ≥70% confidence)" → strip the entire parens block
    (re.compile(r'\s*\(each\s+[≥≤><=]+\s*\d+%[^)]*\)', re.IGNORECASE), ''),
    # "average X% across N specialists" → "broadly consistent across N specialists"
    (re.compile(
        r'\baverage\s+\d+(?:\.\d+)?%\s+across\s+(\d+\s+specialists?)\b',
        re.IGNORECASE,
    ), r'broadly consistent across \1'),
]

# Strip any remaining percentage values (bare numbers after the pre-rewrites).
# Note: % is NOT a \w character so \b does not work after %; use (?!\w) or
# (?=\s|[,;.)]|$) as the trailing boundary instead.
_CONF_PROSE_STRIP_RES: List[re.Pattern] = [
    # Parenthesized: "(52%)" or "(52% confidence)" → remove
    re.compile(r'\s*\(\d+(?:\.\d+)?%[^)]*\)', re.IGNORECASE),
    # "at 52%" (trailing boundary: non-word or end)
    re.compile(r'\s+at\s+\d+(?:\.\d+)?%(?!\w)', re.IGNORECASE),
    # Comparison operator + number + %: "≥70%", ">80%"
    re.compile(r'[≥≤><]=?\s*\d+(?:\.\d+)?%(?!\w)'),
    # Bare "N%" anywhere remaining — word-start required, no \b after %
    re.compile(r'(?<!\w)\d+(?:\.\d+)?%(?!\w)', re.IGNORECASE),
    # "range < 15pp" — artefact from de-numericalization of range expressions
    re.compile(r',?\s+range\s+<\s+\d+pp(?!\w)', re.IGNORECASE),
]


def naturalize_confidence_prose(text: str) -> str:
    """Strip ALL percentage values from frontend-facing confidence reasoning.

    Converts quantitative agent-confidence citations
    (``"lower conviction (52%) vs valuation agents (81%)"``) to purely
    qualitative analyst prose.  The output contains no raw percentages —
    relative conviction and signal direction are expressed in words, not
    numbers.

    This is a stronger filter than ``naturalize_confidence()``, which only
    strips the most mechanical citation patterns.  Call this function on
    ``confidence_reasoning`` as a second pass so the frontend never sees
    raw percentage figures.

    Parameters
    ----------
    text : Raw confidence_reasoning string (may contain percentages).

    Returns
    -------
    Confidence reasoning with all percentage values removed and qualitative
    rewrites applied to the most common percentage-qualified phrases.
    """
    if not text:
        return text

    # Phase 1: targeted qualitative rewrites (must run before bare % strip)
    for pattern, replacement in _CONF_PROSE_REWRITES_PRE:
        text = pattern.sub(replacement, text)

    # Phase 2: strip any remaining percentage values
    for pattern in _CONF_PROSE_STRIP_RES:
        text = pattern.sub('', text)

    # Phase 3: cleanup after stripping
    text = re.sub(r'\s{2,}', ' ', text)           # collapse multiple spaces
    text = re.sub(r'\s+([,;.])', r'\1', text)      # fix orphaned punctuation
    text = re.sub(r'([.!?])\s+([,;])', r'\1', text)  # fix double terminal
    text = re.sub(r'^[,;\s]+', '', text)           # remove leading junk
    return text.strip()


# ── Confidence humanization (Refinement 1) ───────────────────────────────────
# Strips system-visible signal counts and mechanics from confidence_reasoning.
# Called as the THIRD and final pass on confidence text, after
# naturalize_confidence() and naturalize_confidence_prose() have already
# removed mechanical % citations and agent-name references.
#
# Target: investment-committee language — no counts, no system artifacts.

_BULL_BEAR_DIRECTION_RE = re.compile(
    r"(?P<n1>\d+)\s+(?P<d1>bullish|bearish)\s+vs\s+(?P<n2>\d+)\s+(?P<d2>bullish|bearish)",
    re.IGNORECASE,
)


def _replace_bull_bear_counts(m: "re.Match[str]") -> str:  # type: ignore[type-arg]
    """Convert 'N bullish vs M bearish' to qualitative direction language.

    Used as a re.sub() callable — receives the Match object and returns a
    replacement string that expresses the signal split in PM-note prose.
    """
    try:
        n1, d1 = int(m.group("n1")), m.group("d1").lower()
        n2      =  int(m.group("n2"))
        bull    = n1 if d1 == "bullish" else n2
        bear    = n1 if d1 == "bearish" else n2
        total   = bull + bear
        if total == 0:
            return "directionally mixed"
        bull_share = bull / total
        if bull_share >= 0.70:
            return "predominantly constructive"
        elif bull_share <= 0.30:
            return "predominantly cautious"
        else:
            return "directionally mixed"
    except (ValueError, AttributeError):
        return "directionally mixed"


# Patterns for stripping count-bearing phrases.
# Order matters: parenthesized direction blocks stripped FIRST so the bare
# direction regex doesn't replace inside parens and then get re-stripped.
_HUMANIZE_SIGNAL_STRIP_RES: List[re.Pattern] = [
    # Parenthesized direction counts "(4 bullish vs 1 bearish)" → remove entirely.
    # The surrounding sentence already expresses the direction qualitatively.
    re.compile(r"\s*\(\d+\s+(?:bullish|bearish)\s+vs\s+\d+\s+(?:bullish|bearish)\)",
               re.IGNORECASE),
    # Parenthesized evidence count: "(11 items)" / "(2 item)"
    re.compile(r"\s*\(\d+\s+items?\)", re.IGNORECASE),
    # "across N ranked signals"
    re.compile(r"\s+across\s+\d+\s+ranked\s+signals?", re.IGNORECASE),
    # "across N specialists"
    re.compile(r"\s+across\s+\d+\s+specialists?", re.IGNORECASE),
]


def humanize_confidence_reasoning(text: str) -> str:
    """Final humanization pass: strip signal counts and system mechanics.

    Two-step approach:

    Step 1 — Strip parenthesized direction count blocks
      ``"(4 bullish vs 1 bearish)"`` → removed entirely.  The surrounding
      sentence (e.g., "Signal direction leans bullish" or "two-sided uncertainty")
      already expresses the direction qualitatively.

    Step 2 — Replace any remaining bare direction counts
      ``"4 bullish vs 1 bearish"`` (not in parens) → ``"predominantly constructive"``.

    Step 3 — Strip all remaining count-bearing phrases
      ``"(11 items)"`` → removed; ``"across 5 ranked signals"`` → removed.

    Examples
    --------
    Before: ``"Signal direction leans bullish (4 bullish vs 1 bearish) across 5 signals."``
    After:  ``"Signal direction leans bullish."``

    Before: ``"Evidence base is solid (11 items)."``
    After:  ``"Evidence base is solid."``

    Before: ``"Agent consensus is broadly aligned across 5 specialists."``
    After:  ``"Agent consensus is broadly aligned."``

    Called AFTER ``naturalize_confidence()`` and ``naturalize_confidence_prose()``
    have already stripped percentages and mechanical agent-name citations.
    """
    if not text:
        return text

    # Step 1 — strip parenthesized direction count blocks FIRST
    for pattern in _HUMANIZE_SIGNAL_STRIP_RES:
        text = pattern.sub("", text)

    # Step 2 — replace any remaining BARE "N bullish vs M bearish" (not in parens)
    text = _BULL_BEAR_DIRECTION_RE.sub(_replace_bull_bear_counts, text)

    # Step 3 — cleanup artefacts left by stripping
    text = re.sub(r"\s{2,}", " ", text)           # collapse double spaces
    text = re.sub(r"\s+([,;.])", r"\1", text)     # fix orphaned punctuation
    text = re.sub(r"([,;])\s*\.", ".", text)      # ", ." → "."
    text = re.sub(r"—\s*\.", ".", text)           # "— ." → "."
    text = re.sub(r"\(\s*\)", "", text)           # empty parens "()"
    text = re.sub(r"^[,;\s]+", "", text)          # leading junk
    return text.strip()


def _apply_institutional_language(thesis: InvestmentThesis) -> InvestmentThesis:
    """Apply institutional phrase rewrites and confidence naturalization.

    Processes all prose fields through ``institutional_phrase_rewriter()``
    and passes ``confidence_reasoning`` through ``naturalize_confidence()``.
    Returns an updated copy; never mutates the input.
    """
    _PROSE_FIELDS = (
        "direct_answer", "bull_thesis", "bear_thesis",
        "conclusion", "valuation_view", "macro_sensitivity",
        "one_sentence_thesis",  # hero thesis gets institutional rewrites too
    )
    updates: Dict[str, str] = {}

    for field_name in _PROSE_FIELDS:
        original: str = getattr(thesis, field_name, "") or ""
        if not original.strip():
            continue
        rewritten = institutional_phrase_rewriter(original)
        if rewritten != original:
            updates[field_name] = rewritten

    conf_text: str = thesis.confidence_reasoning or ""
    if conf_text:
        # Stage 1: strip mechanical citation patterns (agent names, "X% confidence")
        naturalized = naturalize_confidence(conf_text)
        # Stage 2: strip ALL remaining percentage values for frontend delivery
        naturalized = naturalize_confidence_prose(naturalized)
        # Stage 3: strip signal counts ("8 bullish vs 4 bearish", "11 items",
        #          "across 5 ranked signals") — replaces counts with qualitative prose
        naturalized = humanize_confidence_reasoning(naturalized)
        if naturalized != conf_text:
            updates["confidence_reasoning"] = naturalized

    if not updates:
        return thesis

    if hasattr(thesis, "model_copy"):
        return thesis.model_copy(update=updates)
    return thesis.copy(update=updates)  # type: ignore[attr-defined]


# ── Structural variety enforcement (Refinement 5) ────────────────────────────
# Detects when two or more prose sections open with the same rhetorical template
# and rotates sentence order in the second occurrence so each section leads with
# a distinct framing.  Conservative — only fires on the specific
# "X [support/provide/…] Y" template to avoid unexpected re-ordering.

_SUPPORT_DESPITE_RE = re.compile(
    r"^\S+(?:'s)?\s+"
    r"(?:\S+\s+){0,3}"         # allow 0–3 middle words (e.g. "buyback program")
    r"(?:supports?|provides?|enables?|delivers?|anchors?|sustains?|limits?|constrains?)\b",
    re.IGNORECASE,
)


def _enforce_structural_variety(thesis: InvestmentThesis) -> InvestmentThesis:
    """Rotate sentence order in sections that duplicate the opening template.

    Checks ``bull_thesis``, ``bear_thesis``, and ``conclusion`` in that order.
    When two or more of those sections start with the same support/provide/
    enable template (``"X supports Y despite Z"``), the second occurrence is
    rotated so the second sentence leads instead.

    Conservative rules
    ------------------
    - Only fires on the specific "X [support-class verb] Y" template.
    - Never removes sentences — only changes order within a section.
    - Requires ≥ 2 sentences in the rotated section (otherwise no-op).
    - Returns the thesis unchanged when no template collision is detected.
    """
    _CHECKED_FIELDS = ("bull_thesis", "bear_thesis", "conclusion")
    template_seen = False
    updates: Dict[str, str] = {}

    for field_name in _CHECKED_FIELDS:
        text = getattr(thesis, field_name, "") or ""
        sentences = _split_sentences(text)
        if not sentences:
            continue

        starts_with_template = bool(_SUPPORT_DESPITE_RE.match(sentences[0]))

        if starts_with_template and template_seen and len(sentences) >= 2:
            # Rotate: second sentence leads, first sentence follows
            rotated = _join_sentences([sentences[1]] + [sentences[0]] + sentences[2:])
            updates[field_name] = rotated
        elif starts_with_template:
            template_seen = True

    if not updates:
        return thesis

    if hasattr(thesis, "model_copy"):
        return thesis.model_copy(update=updates)
    return thesis.copy(update=updates)  # type: ignore[attr-defined]


# ── Temporal defaults (Refinement 4) ─────────────────────────────────────────

def apply_temporal_defaults(thesis: InvestmentThesis) -> InvestmentThesis:
    """Ensure temporal intelligence fields have safe defaults.

    When no prior thesis exists (the common case for first-time analysis),
    all three temporal fields are already at their schema defaults:
      - what_changed  = []
      - thesis_trend  = "unclear"
      - change_drivers = []

    This function is an explicit extension point: in a future timeline-memory
    integration, it will accept an optional prior_thesis and compute diffs.
    For now it is a no-op that enforces the "unclear" default.
    """
    updates: Dict[str, object] = {}

    if thesis.thesis_trend not in ("strengthening", "weakening", "stable", "unclear"):
        updates["thesis_trend"] = "unclear"

    if updates:
        if hasattr(thesis, "model_copy"):
            return thesis.model_copy(update=updates)
        return thesis.copy(update=updates)  # type: ignore[attr-defined]

    return thesis


# ── Main entry point ──────────────────────────────────────────────────────────

def polish_thesis(thesis: InvestmentThesis) -> InvestmentThesis:
    """Apply all polish refinements to a synthesised InvestmentThesis.

    Order of operations
    -------------------
    1. enforce_concision              — trim prose to sentence-count targets, strip fillers
    2. suppress_redundancy            — remove repeated ideas (sentence + concept level)
    3. _apply_institutional_language  — rewrite robotic patterns; naturalize confidence
                                        (also strips ALL percentages from confidence_reasoning
                                        via naturalize_confidence_prose for frontend delivery)
    4. _enforce_structural_variety    — rotate repeated opening templates across sections
    5. apply_temporal_defaults        — enforce valid thesis_trend value
    6. compress_hero_thesis           — trim one_sentence_thesis to ≤22 words,
                                        strip verbose parentheticals + gerund chains

    Returns a new InvestmentThesis (immutable update pattern); the input is
    never mutated.
    """
    thesis = enforce_concision(thesis)
    thesis = suppress_redundancy(thesis)
    thesis = _apply_institutional_language(thesis)
    thesis = _enforce_structural_variety(thesis)
    thesis = apply_temporal_defaults(thesis)
    # Hero thesis compression — applied last so all prior rewrites are captured
    hero = getattr(thesis, "one_sentence_thesis", "") or ""
    if hero:
        compressed = compress_hero_thesis(hero)
        if compressed != hero:
            if hasattr(thesis, "model_copy"):
                thesis = thesis.model_copy(update={"one_sentence_thesis": compressed})
            else:
                thesis = thesis.copy(update={"one_sentence_thesis": compressed})  # type: ignore[attr-defined]
    return thesis
