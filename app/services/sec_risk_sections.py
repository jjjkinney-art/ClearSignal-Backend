"""Shared conservative boundaries for normalized SEC Risk Factors text."""
import re
from itertools import islice

MAX_ISSUER_RISK_SECTION_CHARS = 320_000

US_RISK_FORMS = frozenset({'10-K', '10-K/A', '10-Q', '10-Q/A'})
FOREIGN_RISK_FORMS = frozenset({'20-F', '20-F/A'})
RISK_FORMS = US_RISK_FORMS | FOREIGN_RISK_FORMS


def risk_section_label(form: str) -> str | None:
    if form in US_RISK_FORMS:
        return 'Item 1A. Risk Factors'
    if form in FOREIGN_RISK_FORMS:
        return 'Item 3.D. Risk Factors'
    return None


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

_FOREIGN_ITEM3 = re.compile(
    rf'\b{_ITEM}\s+3\s*[.:—–-]?\s*{_word("Key")}\s+{_word("Information")}\b', re.I)
_FOREIGN_RISK = re.compile(rf'\b(?:D\s*[.:—–-]\s*)?{_word("Risk")}\s+{_word("Factors")}\b', re.I)
_FOREIGN_DIRECT = re.compile(
    rf'\b{_ITEM}\s+3\s*[.]?\s*D\s*[.:—–-]?\s*{_word("Risk")}\s+{_word("Factors")}\b', re.I)
_FOREIGN_END = re.compile(
    rf'\b{_ITEM}\s+4\s*[.:—–-]?\s*{_word("Information")}\s+on\s+the\s+{_word("Company")}\b', re.I)


def _foreign_headings(text: str):
    # A bare risk heading is accepted only inside an explicit Item 3 section,
    # within a small preamble. Never scan arbitrary report prose for a match.
    candidates = list(islice(_FOREIGN_DIRECT.finditer(text), 64))
    for index, item in enumerate(_FOREIGN_ITEM3.finditer(text)):
        if index == 64:
            break
        if rejected_risk_heading(text, item.end(), start=item.start()):
            continue
        for heading in _FOREIGN_RISK.finditer(text, item.end(), min(len(text), item.end() + 2000)):
            explicit_d = bool(re.match(r'D\s*[.:—–-]', heading.group(), re.I))
            # TSM's reviewed layout omits the D label after its non-applicable
            # Item 3 preamble. Do not accept a bare mention in arbitrary prose.
            reviewed_preamble = bool(re.search(r'\bNot applicable\.\s*$', text[item.end():heading.start()], re.I))
            if ((explicit_d or reviewed_preamble)
                    and not rejected_risk_heading(text, heading.end(), start=heading.start())):
                candidates.append(heading)
                break
    return sorted({m.start(): m for m in candidates}.values(), key=lambda m: m.start())


def risk_openings(text: str, *, form: str = '10-K', layout: dict | None = None):
    if layout:
        return re.compile(layout['opening'], re.I).finditer(text)
    return _foreign_headings(text) if form in FOREIGN_RISK_FORMS else RISK_START.finditer(text)


def rejected_risk_heading(text: str, end: int, *, start: int | None = None) -> bool:
    # TOC page numbers, quoted cross-references and dash-led references are not
    # independently established section boundaries.
    return bool(re.match(r'[\d"”\u2013\u2014-]|\(Continued\)', text[end:].lstrip(), re.I)
                or (start is not None and re.search(
                    r'(?:["“]\s*|\b(?:see|refer\s+to|discussed\s+in|in|under|within)\s*)$',
                    text[max(0, start - 60):start], re.I)))


def find_risk_closing(text: str, start: int, *, end: int | None = None, form: str = '10-K', layout: dict | None = None) -> re.Match | None:
    """An explicit closing heading, excluding quoted references and TOC rows."""
    pattern = re.compile(layout['closing'], re.I) if layout else (_FOREIGN_END if form in FOREIGN_RISK_FORMS else RISK_END)
    for index, heading in enumerate(pattern.finditer(text, start, len(text) if end is None else end)):
        if index == 64:
            return None
        if not rejected_risk_heading(text, heading.end(), start=heading.start()):
            return heading
    return None


def complete_risk_window(text: str, *, max_section_chars: int = MAX_ISSUER_RISK_SECTION_CHARS, form: str = '10-K', layout: dict | None = None) -> tuple[int, int] | None:
    """First bounded section with an explicit closing heading; no synthesis."""
    for index, heading in enumerate(risk_openings(text, form=form, layout=layout)):
        # A hostile document cannot trigger unlimited suffix scans. Failure to
        # find an eligible section within this bound is an explicit gap.
        if index == 64:
            return None
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            continue
        closing = find_risk_closing(text, heading.end(),
                                   end=min(len(text), heading.end() + max_section_chars + 100), form=form, layout=layout)
        if closing and closing.start() - heading.end() <= max_section_chars:
            return heading.start(), closing.end()
    return None


def risk_section_spans(text: str, *, max_section_chars: int, diagnostics: dict | None = None, form: str = '10-K', layout: dict | None = None):
    """Bounded, nonoverlapping bodies; references cannot open a section."""
    stats = diagnostics if diagnostics is not None else {}
    covered_until = 0
    for index, heading in enumerate(risk_openings(text, form=form, layout=layout)):
        if index == 64:
            break
        stats['risk_headings'] = stats.get('risk_headings', 0) + 1
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            stats['rejected_heading_prefixes'] = stats.get('rejected_heading_prefixes', 0) + 1
            continue
        if heading.start() < covered_until:
            continue
        closing = find_risk_closing(text, heading.end(), form=form, layout=layout)
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


BUSINESS_START = re.compile(rf"\b{_ITEM}\s+1\s*[.:—–-]?\s*{_word('Business')}\b", re.I)


def complete_business_window(text: str):
    """A bounded 10-K Item 1 body, excluding TOC and quoted references."""
    for heading in islice(BUSINESS_START.finditer(text), 64):
        if rejected_risk_heading(text, heading.end(), start=heading.start()):
            continue
        for closing in islice(RISK_START.finditer(text, heading.end(), min(len(text), heading.end() + 160_000)), 64):
            if not rejected_risk_heading(text, closing.end(), start=closing.start()):
                return heading.end(), closing.start()
    return None
