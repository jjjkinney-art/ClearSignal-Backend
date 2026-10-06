"""Shared conservative boundaries for normalized SEC Risk Factors text."""
import re

RISK_START = re.compile(r"\bItem\s+1A\s*[.:—–-]?\s*Ris\s*k\s+Factors\b", re.I)
RISK_END = re.compile(
    r"\bItem\s+(?:1B|1C|2)\s*[.:—–-]?\s+(?:"
    r"Unresolve\s*d(?:\s+Staff\s+Comments)?|Cy\s*bersecurity|Properties|"
    r"Legal(?:\s+Proceedings)?|Unregistered(?:\s+Sales(?:\s+of\s+Equity\s+Securities)?)?)\b", re.I)


def rejected_risk_heading(text: str, end: int, *, start: int | None = None) -> bool:
    # TOC page numbers, quoted cross-references and dash-led references are not
    # independently established section boundaries.
    return bool(re.match(r'[\d"”\u2013\u2014-]', text[end:].lstrip())
                or (start is not None and re.search(
                    r'\b(?:see|refer\s+to)\s*["“]?\s*$', text[max(0, start - 60):start], re.I)))


def complete_risk_window(text: str, *, max_section_chars: int = 160_000) -> tuple[int, int] | None:
    """First bounded section with an explicit closing heading; no synthesis."""
    for index, heading in enumerate(RISK_START.finditer(text)):
        # A hostile document cannot trigger unlimited suffix scans. Failure to
        # find an eligible section within this bound is an explicit gap.
        if index == 64:
            return None
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            continue
        closing = RISK_END.search(text, heading.end(),
                                 min(len(text), heading.end() + max_section_chars + 100))
        if closing and closing.start() - heading.end() <= max_section_chars:
            return heading.start(), closing.end()
    return None
