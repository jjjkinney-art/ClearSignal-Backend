"""Product / model / filing / index identifier spans (Sprint 2B).

Sprint 2A's production benchmark showed the claim extractor turning the number
inside a *name* into a quantitative claim — "Microsoft 365" became the claim
``365``, "Boeing 737" became ``737``.  Those are identifiers, not measurements.

The fix is deliberately NOT a universal number blacklist: ``365`` and ``737``
are perfectly good quantities in "365 days" or "737 aircraft delivered".  What
makes them non-quantitative is the *token span they sit in* — a recognized
brand/model/filing/index/rule phrase.  So this module reports character spans
of numbers that are part of such a phrase, and the extractor skips a numeric
match only when its span is contained in one.

Adding coverage is a one-line addition to ``_IDENTIFIER_PATTERNS`` — no
company-specific behavior leaks into the extractor or the agents.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Each pattern matches a full identifier PHRASE and marks the numeric portion
# that must not become a claim with the named group ``num``.  Anything outside
# that group (including any other number in the sentence) stays extractable.
_IDENTIFIER_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        # ── Software product lines ──────────────────────────────────────────
        ("Microsoft 365", r"\bmicrosoft\s+(?P<num>365)\b"),
        ("Office 365", r"\boffice\s+(?P<num>365)\b"),
        ("Windows 365", r"\bwindows\s+(?P<num>365)\b"),
        ("Dynamics 365", r"\bdynamics\s+(?P<num>365)\b"),
        # ── Aircraft families ───────────────────────────────────────────────
        # "Boeing 737" / "Boeing 787" — brand-qualified aircraft family.
        ("Boeing aircraft family", r"\bboeing\s+(?P<num>7\d7)\b"),
        # "737 MAX" / "787 Dreamliner" — suffix-qualified, brand may be absent.
        ("Boeing aircraft family",
         r"\b(?P<num>7\d7)[\s-]*(?:max|ng|dreamliner|classic)\b"),
        ("Airbus aircraft family", r"\bairbus\s+a(?P<num>3\d0)\b"),
        # ── Vehicle models ──────────────────────────────────────────────────
        # Only "Model 3" carries a digit; S/X/Y are non-numeric and never match
        # the numeric extractor anyway, but they are listed for documentation.
        ("Tesla Model 3", r"\bmodel\s+(?P<num>3)\b"),
        # ── Indices ─────────────────────────────────────────────────────────
        ("S&P index", r"\bs&p\s*(?P<num>500|400|600)\b"),
        ("Fortune list", r"\bfortune\s+(?P<num>500|1000)\b"),
        ("Nasdaq index", r"\bnasdaq[\s-]*(?P<num>100)\b"),
        ("Russell index", r"\brussell\s+(?P<num>1000|2000|3000)\b"),
        ("FTSE index", r"\bftse\s+(?P<num>100|250|350)\b"),
        # ── SEC filings ─────────────────────────────────────────────────────
        ("SEC form", r"\bform\s+(?P<num>10)-[kq]\b"),
        ("SEC form", r"\bform\s+(?P<num>8)-k\b"),
        ("SEC form", r"\bform\s+(?P<num>20)-f\b"),
        # Bare filing references ("the 10-K", "a 10-Q") without the word Form.
        ("SEC form", r"\b(?P<num>10)-[kq]\b"),
        ("SEC form", r"\b(?P<num>8)-k\b"),
        # ── SEC rules ───────────────────────────────────────────────────────
        ("SEC rule", r"\brule\s+(?P<num>10)b5-1\b"),
        ("SEC rule", r"\brule\s+(?P<num>144)a?\b"),
        # ── Accounting / reporting standards ────────────────────────────────
        ("Accounting standard", r"\b(?:asc|ifrs|ias|fasb)\s+(?P<num>\d+)\b"),
        ("Tax code section", r"\bsection\s+(?P<num>\d+)\b"),
    )
)


def identifier_spans(text: str) -> List[Tuple[int, int, str]]:
    """Return ``(start, end, label)`` char spans of numbers that belong to a
    recognized identifier phrase and therefore must not become claims.

    Only the numeric portion of the phrase is returned, so an otherwise
    legitimate figure elsewhere in the same sentence is untouched:
    "S&P 500 returned 12%" yields one span covering ``500`` — ``12%`` remains
    fully extractable.
    """
    if not text:
        return []
    spans: List[Tuple[int, int, str]] = []
    for label, pattern in _IDENTIFIER_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span("num")
            if start >= 0 and end > start:
                spans.append((start, end, label))
    return spans


def identifier_label_at(spans: List[Tuple[int, int, str]], start: int, end: int) -> Optional[str]:
    """Return the identifier label if the numeric match ``[start, end)`` overlaps
    an identifier span, else ``None``.

    Overlap (rather than strict containment) is used so trailing punctuation or
    a unit swept into the numeric match — "Microsoft 365," extracting as
    ``365,`` — still resolves to the identifier.
    """
    for s, e, label in spans:
        if start < e and end > s:
            return label
    return None
