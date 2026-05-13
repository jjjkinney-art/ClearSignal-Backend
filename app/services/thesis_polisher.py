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
    "direct_answer":    2,
    "conclusion":       2,   # tightened from 3 — one causal sentence + so-what
    "bull_thesis":      2,   # tightened from 3 — strongest driver + valuation anchor
    "bear_thesis":      2,   # tightened from 3 — primary risk + transmission mechanism
    "valuation_view":   1,   # tightened from 2 — one specific multiple/metric sentence
    "macro_sensitivity": 1,  # tightened from 2 — one specific transmission sentence
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

    Sentence targets
    ----------------
    direct_answer    : 2 sentences
    conclusion       : 3 sentences
    bull_thesis      : 3 sentences
    bear_thesis      : 3 sentences
    valuation_view   : 2 sentences
    macro_sensitivity: 2 sentences
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
            sent_mechs = extract_core_mechanisms(sent)
            is_concept_redundant = (
                bool(sent_mechs)
                and sent_mechs.issubset(committed_mechanisms)
                and max_sim >= _CONCEPT_JACCARD_FLOOR
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
    supporting_sections: Dict[str, str] = {
        f: (getattr(thesis, f, "") or "") for f in _SUPPORTING
    }
    supporting_result = _suppress_redundant_sentences(
        supporting_sections,
        _SUPPORTING,
        pre_committed=pass1_committed + signal_committed,
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


def _apply_institutional_language(thesis: InvestmentThesis) -> InvestmentThesis:
    """Apply institutional phrase rewrites and confidence naturalization.

    Processes all prose fields through ``institutional_phrase_rewriter()``
    and passes ``confidence_reasoning`` through ``naturalize_confidence()``.
    Returns an updated copy; never mutates the input.
    """
    _PROSE_FIELDS = (
        "direct_answer", "bull_thesis", "bear_thesis",
        "conclusion", "valuation_view", "macro_sensitivity",
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
        naturalized = naturalize_confidence(conf_text)
        if naturalized != conf_text:
            updates["confidence_reasoning"] = naturalized

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
    1. enforce_concision           — trim prose to sentence-count targets, strip fillers
    2. suppress_redundancy         — remove repeated ideas (sentence + concept level)
    3. _apply_institutional_language — rewrite robotic patterns; naturalize confidence
    4. apply_temporal_defaults     — enforce valid thesis_trend value

    Returns a new InvestmentThesis (immutable update pattern); the input is
    never mutated.
    """
    thesis = enforce_concision(thesis)
    thesis = suppress_redundancy(thesis)
    thesis = _apply_institutional_language(thesis)
    thesis = apply_temporal_defaults(thesis)
    return thesis
