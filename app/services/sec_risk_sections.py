"""Shared conservative boundaries for normalized SEC Risk Factors text."""
import re

MAX_ISSUER_RISK_SECTION_CHARS = 320_000


def _word(value: str) -> str:
    # Visible SEC HTML can split a word across styled spans ("Ri sk", "Ite m").
    # Match that whitespace without rewriting the normalized source or offsets.
    return r"\s*".join(value)


_ITEM = _word("Item")
RISK_START = re.compile(
    rf"\b{_ITEM}\s+1\s*A\s*[.:—–-]?\s*{_word('Risk')}\s+{_word('Factors')}\b", re.I)
RISK_END = re.compile(
    rf"\b{_ITEM}\s+(?:1\s*B|1\s*C|2)(?:\s*[.:—–-]\s*|\s+)(?:"
    rf"{_word('Unresolved')}(?:\s+{_word('Staff')}\s+{_word('Comments')})?|"
    rf"{_word('Cybersecurity')}|{_word('Properties')}|"
    rf"{_word('Legal')}(?:\s+{_word('Proceedings')})?|"
    rf"{_word('Unregistered')}(?:\s+{_word('Sales')}(?:\s+of\s+Equity\s+Securities)?)?)\b", re.I)


def rejected_risk_heading(text: str, end: int, *, start: int | None = None) -> bool:
    # TOC page numbers, quoted cross-references and dash-led references are not
    # independently established section boundaries.
    return bool(re.match(r'[\d"”\u2013\u2014-]|\(Continued\)', text[end:].lstrip(), re.I)
                or (start is not None and re.search(
                    r'(?:["“]\s*|\b(?:see|refer\s+to|discussed\s+in|in|under|within)\s*)$',
                    text[max(0, start - 60):start], re.I)))


def find_risk_closing(text: str, start: int, *, end: int | None = None) -> re.Match | None:
    """An explicit closing heading, excluding quoted references and TOC rows."""
    for index, heading in enumerate(RISK_END.finditer(text, start, len(text) if end is None else end)):
        if index == 64:
            return None
        if not rejected_risk_heading(text, heading.end(), start=heading.start()):
            return heading
    return None


def complete_risk_window(text: str, *, max_section_chars: int = MAX_ISSUER_RISK_SECTION_CHARS) -> tuple[int, int] | None:
    """First bounded section with an explicit closing heading; no synthesis."""
    for index, heading in enumerate(RISK_START.finditer(text)):
        # A hostile document cannot trigger unlimited suffix scans. Failure to
        # find an eligible section within this bound is an explicit gap.
        if index == 64:
            return None
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            continue
        closing = find_risk_closing(text, heading.end(),
                                   end=min(len(text), heading.end() + max_section_chars + 100))
        if closing and closing.start() - heading.end() <= max_section_chars:
            return heading.start(), closing.end()
    return None


def risk_section_spans(text: str, *, max_section_chars: int, diagnostics: dict | None = None):
    """Bounded, nonoverlapping bodies; references cannot open a section."""
    stats = diagnostics if diagnostics is not None else {}
    covered_until = 0
    for index, heading in enumerate(RISK_START.finditer(text)):
        if index == 64:
            break
        stats['risk_headings'] = stats.get('risk_headings', 0) + 1
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            stats['rejected_heading_prefixes'] = stats.get('rejected_heading_prefixes', 0) + 1
            continue
        if heading.start() < covered_until:
            continue
        closing = find_risk_closing(text, heading.end())
        if closing is None:
            stats['missing_closing_sections'] = stats.get('missing_closing_sections', 0) + 1
            continue
        if closing.start() - heading.end() > max_section_chars:
            stats['oversized_sections'] = stats.get('oversized_sections', 0) + 1
            continue
        covered_until = closing.end()
        stats['complete_sections'] = stats.get('complete_sections', 0) + 1
        yield heading.end(), closing.start()


_ABBREVIATION = re.compile(r'(?:\be\.g\.|\bi\.e\.|\bU\.S\.|\bU\.K\.|\bInc\.|\bLtd\.|\bvs\.|\bMr\.|\bDr\.)$', re.I)


def risk_sentence_spans(text: str):
    """Exact complete spans; common abbreviations are not sentence endings."""
    start = 0
    for punctuation in re.finditer(r'[.!?](?=\s|$)', text):
        end = punctuation.end()
        if _ABBREVIATION.search(text[max(start, end - 12):end]):
            continue
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            yield start, end
        start = end
