"""Choose company-specific risk disclosures for a broad thesis answer.

Every candidate has already passed the issuer-risk admission rules. This
step removes disclosures that are about the risk-factor section itself or
that list generic hazards any issuer could name, then prefers disclosures
that state something particular to this issuer: a concrete dependency or
concentration first, then named parties (not statutes, which apply to every
issuer, and not acronyms). A disclosure qualifies only with such a signal,
and a macro-hazard disclosure only with a concrete dependency; when none
qualifies, nothing is presented and the answer says so. Selection never asserts materiality or likelihood.
Nothing here names an issuer.
"""
import re

# About the section, not a risk: "the events discussed in these risk factors …".
_PREAMBLE = re.compile(
    r"\b(?:these|the|such|our) risk factors\b|\brisks? (?:discussed|described|set forth|identified) "
    r"(?:below|above|herein|in this)\b|\b(?:discussed|described) (?:below|above)\b", re.I)
_BULLET = re.compile(r"•")
# Generic macro hazards; four or more distinct ones make a catch-all list.
_HAZARDS = {
    'natural disaster': r"\bnatural (?:or human-caused )?disasters?\b|\bhurricanes?\b|\btornado(?:es)?\b|\bearthquakes?\b|\bfloods?\b",
    'weather': r"\b(?:adverse|extreme|severe) weather\b|\bclimate\b",
    'terrorism': r"\bterroris[tm]\b",
    'public health': r"\bpublic health\b|\bpandemics?\b|\bepidemics?\b",
    'conflict': r"\bwars?\b|\b(?:military|armed|regional|international) conflicts?\b|\bconflicts\b",
    'geopolitical': r"\bgeopolitic",
    'unrest': r"\b(?:political|civil|labor|social) unrest\b|\bstrikes\b",
    'catastrophe': r"\bcatastroph",
    'inflation': r"\binflation",
    'currency': r"\bforeign exchange\b|\bcurrenc(?:y|ies)\b",
    'interest rates': r"\binterest rates?\b",
    'supply chain': r"\bsupply chains?\b",
    'cyber': r"\bcyber",
    'trade measures': r"\bsanctions\b|\bexport controls?\b|\btariffs?\b|\btrade (?:policy|policies|restrictions?)\b",
}
_HAZARD_PATTERNS = {name: re.compile(pattern, re.I) for name, pattern in _HAZARDS.items()}
# A concrete dependency or concentration this issuer states about itself.
_DEPENDENCY = re.compile(
    r"\b(?:accounts?|accounted) for (?:a )?(?:significant|substantial|large|majority|material)\b"
    r"|\b(?:represents?|represented) (?:a )?(?:significant|substantial|large|majority)\b"
    r"|\bonly one or (?:a )?limited (?:number of )?sources?\b|\bsingle[- ]source\b|\bsole[- ]source\b"
    r"|\b(?:companies|businesses|issuers) like ours\b"
    r"|\bour (?:largest|principal|key|major) (?:customers?|suppliers?|clients?)\b", re.I)
_GENERIC_CAPITALIZED = {
    'The', 'Our', 'We', 'Any', 'If', 'In', 'For', 'Some', 'Many', 'Such', 'These', 'This', 'Company',
    'Despite', 'Because', 'As', 'An', 'A', 'New', 'Failure', 'Failures', 'Failing', 'Decisions'}
def hazard_count(quote):
    return sum(bool(pattern.search(quote)) for pattern in _HAZARD_PATTERNS.values())


def run_in_heading(quote):
    """A risk-factor heading run into its first sentence: most of the first
    eight words capitalized ("Risks Related to Artificial Intelligence, Our Data …")."""
    words = quote.split()[:8]
    return len(words) == 8 and sum(word[:1].isupper() for word in words) >= 6


def rejection(quote):
    if _PREAMBLE.search(quote):
        return 'risk_factor_preamble'
    if len(_BULLET.findall(quote)) >= 2:
        return 'bullet_summary'
    if run_in_heading(quote):
        return 'run_in_heading'
    if hazard_count(quote) >= 4:
        return 'generic_hazard_list'
    return None


# Laws and regulations apply to every issuer subject to them.
_STATUTE = re.compile(r"(?:[A-Z][A-Za-z\-]+\s+(?:in\s+|of\s+)?){1,7}(?:Act|Acts|Regulations?|Laws?|Rules?|Directive)\b")


def specificity(quote):
    """Concrete dependency statements outrank named parties (beyond the opening
    word); statute names and all-capital acronyms are not parties."""
    text = _STATUTE.sub(' ', quote)
    named = {word for word in re.findall(r"(?<=\s)[A-Z][a-z][A-Za-z\-]*", text)
             if word not in _GENERIC_CAPITALIZED}
    return 3 * len(_DEPENDENCY.findall(quote)) + min(len(named), 2)


def qualifies(quote):
    """Company-specific enough to present: a positive signal, and for text that
    names generic macro hazards, a concrete dependency."""
    if hazard_count(quote) >= 2:
        return bool(_DEPENDENCY.search(quote))
    return specificity(quote) > 0


def select_risks(candidates, *, quote_of, offset_of, limit=2):
    """(selected, rejected reasons). Empty selection means none qualified."""
    kept, reasons = [], []
    for item in candidates:
        reason = rejection(quote_of(item)) or (None if qualifies(quote_of(item)) else 'not_company_specific')
        if reason:
            reasons.append(reason)
        else:
            kept.append(item)
    kept.sort(key=lambda item: (-specificity(quote_of(item)), offset_of(item)))
    return kept[:limit], reasons
