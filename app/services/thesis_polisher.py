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

# ── Sentence limits (refinement 1) ────────────────────────────────────────────
# Maps InvestmentThesis field name → maximum number of sentences to keep.
_SENTENCE_LIMITS: Dict[str, int] = {
    "direct_answer":    2,
    "conclusion":       3,
    "bull_thesis":      3,
    "bear_thesis":      3,
    "valuation_view":   2,
    "macro_sensitivity": 2,
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
    sections : Mapping from field name to prose text.
    priority : Ordered tuple of field names, highest-priority first.
    threshold: Jaccard threshold above which a sentence is considered redundant.

    Returns
    -------
    Dict with the same keys, values replaced by de-duplicated prose.
    """
    committed: List[str] = []      # Sentences kept so far, across all sections
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
                continue

            max_sim = max(_jaccard(sent, c) for c in committed)
            if max_sim >= threshold:
                suppressed.append((max_sim, sent))
            else:
                kept.append(sent)
                committed.append(sent)

        # Safety: never leave a section fully empty
        if not kept and suppressed:
            # Keep the least-redundant suppressed sentence
            least_redundant = min(suppressed, key=lambda x: x[0])[1]
            kept.append(least_redundant)
            committed.append(least_redundant)

        result[field_name] = _join_sentences(kept)

    # Carry over any sections not in the priority list unchanged
    for k, v in sections.items():
        if k not in result:
            result[k] = v

    return result


def suppress_redundancy(thesis: InvestmentThesis) -> InvestmentThesis:
    """Remove cross-section repeated concepts from an InvestmentThesis.

    Walks sections in priority order (direct_answer → conclusion → bull_thesis
    → bear_thesis → valuation_view → macro_sensitivity).  Sentences that
    express an idea already stated in a higher-priority section are dropped
    from the lower-priority section.

    At least one sentence per section is always preserved.
    """
    # Build the sections dict for prose fields
    prose_fields = list(_SECTION_PRIORITY)
    sections: Dict[str, str] = {
        f: (getattr(thesis, f, "") or "")
        for f in prose_fields
    }

    cleaned = _suppress_redundant_sentences(sections, _SECTION_PRIORITY)

    updates: Dict[str, str] = {}
    for field_name in prose_fields:
        original = sections[field_name]
        polished = cleaned.get(field_name, original)
        if polished != original:
            updates[field_name] = polished

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
    1. enforce_concision      — trim prose to sentence-count targets, strip fillers
    2. suppress_redundancy    — remove repeated ideas from lower-priority sections
    3. apply_temporal_defaults — enforce valid thesis_trend value

    Returns a new InvestmentThesis (immutable update pattern); the input is
    never mutated.
    """
    thesis = enforce_concision(thesis)
    thesis = suppress_redundancy(thesis)
    thesis = apply_temporal_defaults(thesis)
    return thesis
