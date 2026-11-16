"""Scope of an answer when the question names a kind of security (warrants, preferred stock, notes or bonds, depositary shares, a share class).

The research pipeline works at issuer level: its evidence is the company's filings and reported facts, not the terms, price or ranking of one security.
Before this module, a question such as "the Acme warrants" was answered as the Acme thesis under Acme's name and common ticker, and nothing said so.

Rules (preregistered in dev_round4/SCORING_RULES_ROUND4):
* a security term outside the company's own name triggers the scope step (a small lexicon; "bond yields", "class action", "business units" do not);
* the issuer's lines come from the SEC ticker directory only;
* two or more lines of the asked kind and none of them resolved: ask which one;
* otherwise answer at issuer level and say so in the first sentence of the visible answer: the kind asked about, that the answer is about the issuer, and
  that security-specific evidence (terms, price, ranking, conversion or redemption rights) is not available.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAME = r"<NAME>"      # stands where the company's own name was removed from the question
_KINDS: dict[str, re.Pattern] = {
    # "warrants" is a noun here, never the verb ("the evidence warrants a closer look", "does this warrant a buy rating")
    "warrants": re.compile(
        rf"(?:\b(?:the|its|their|outstanding|public|private|common|stock|share|spac|and|of|for|about|on|any|all)\s+|['\u2019]s\s+|{_NAME}\s+)warrants?\b|"
        r"\bwarrants?\s+(?:holders?|exercise|price|issued|outstanding|redemption|liabilit\w*|dilution|coverage|expir\w*|overhang|terms)\b", re.I),
    "preferred": re.compile(r"\bpreferred\s+(?:stock|shares?|equity)\b|\bpreference\s+(?:shares?|stock)\b|\bseries\s+[a-z0-9]{1,2}\s+preferred\b", re.I),
    "depositary": re.compile(r"\bdepositary\s+(?:shares|receipts)\b|\badrs?\b|\bamerican\s+depositary\b", re.I),
    "debt": re.compile(
        r"\b(?:senior|subordinated|convertible|unsecured|exchangeable|baby|corporate)\s+(?:notes?|bonds?)\b|\bnotes?\s+due\b|\bdebentures?\b|"
        rf"\b(?:the|its|their|{_NAME})\s+bonds\b|\bbonds\s+(?:issued|due|maturing)\b|\(the\s+bonds\)|['\u2019]s\s+bonds\b", re.I),
    "share_class": re.compile(r"\bclass\s+[a-z0-9]\s+(?:shares?|stock|common|ordinary|equity)\b", re.I),
}
_PHRASE = {"warrants": "warrants", "preferred": "preferred stock", "depositary": "depositary shares", "debt": "notes or bonds", "share_class": "share class"}
_WARRANT = re.compile(r"(?:W|WS|WT|WW)[A-Z]?")
_DERIVATIVE = re.compile(r"(?:W|WS|WT|WW|U|UN|R|RT|RW)[A-Z]?")
_PREFERRED = re.compile(r"\.P[A-Z]?$")
_FOREIGN = re.compile(r"[A-Z]{4}F|[A-Z]{3,4}Y")
LABEL_START = "Scope:"


@dataclass
class ScopeDecision:
    kinds: list[str]
    action: str                                  # "ask" or "label"
    issuer_name: str = ""
    ticker: str = ""                              # the line the pipeline will run on
    lines: list[tuple[str, str]] = field(default_factory=list)       # (ticker, issuer name) of the asked kind, directory order
    selected: str = ""                            # the one line of the asked kind, when exactly one
    note: str = ""


def _strip_names(question: str, titles: list[str], spans: list[tuple[int, int]], tickers: list[str] | None = None) -> str:
    """The question without the company's own name, each occurrence marked <NAME>: its exact name spans and every directory title (with or without a trailing
    registry tag), all found on the original text and merged, so "... Warrant Holdings" or "... Ltd / ADR" is never read as a security term."""
    found = list(spans)
    for title in {t.strip() for t in titles if t and t.strip()}:
        bare = re.sub(r"\s*/\s*[A-Za-z]{2,4}/?\s*$", "", title).strip()
        for form in {title, bare}:
            if form:
                found += [m.span() for m in re.finditer(re.escape(form) + (r"(?:\s*/\s*[A-Za-z]{2,4}/?)?" if form == bare else ""), question, re.I)]
    for ticker in tickers or []:
        found += [m.span() for m in re.finditer(rf"(?<![\w$.-])\$?{re.escape(ticker.replace('.', '-'))}(?![\w])|(?<![\w$.-])\$?{re.escape(ticker)}(?![\w])", question)]
    merged: list[list[int]] = []
    for start, end in sorted(found):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    text = question
    for start, end in reversed(merged):
        text = text[:start] + " <NAME> " + text[end:]
    return re.sub(r"\s{2,}", " ", text)


def requested_kinds(question: str, titles: list[str] | None = None, spans: list[tuple[int, int]] | None = None, tickers: list[str] | None = None) -> list[str]:
    from .company_detection import mask_registry_tags
    # A registry tag after an official name ("Vibra Energia S.A./ADR", "Inficon Holding AG/ADR") is part of the name, not a request for depositary shares.
    outside = _strip_names(mask_registry_tags(question), titles or [], spans or [], tickers)
    return [kind for kind, pattern in _KINDS.items() if pattern.search(outside)]


def issuer_lines(directory, ticker: str) -> list:
    """The issuer's lines in directory order, or [] when the ticker is not in the SEC directory."""
    from .issuer_identity import symbol
    item = directory.symbols.get(symbol(ticker))
    if item is None:
        return []
    return [line for line in directory.symbols.values() if line.cik == item.cik]


def lines_of_kind(kind: str, lines: list) -> list:
    tickers = [line.ticker for line in lines]
    if kind == "warrants":
        return [line for line in lines if any(line.ticker != o and line.ticker.startswith(o) and _WARRANT.fullmatch(line.ticker[len(o):]) for o in tickers)]
    if kind == "preferred":
        return [line for line in lines if _PREFERRED.search(line.ticker)]
    if kind == "depositary":
        return [line for line in lines if _FOREIGN.fullmatch(line.ticker.replace(".", ""))]
    if kind == "share_class":
        return [line for line in lines if not _PREFERRED.search(line.ticker) and not _FOREIGN.fullmatch(line.ticker.replace(".", ""))
                and not any(line.ticker != o and line.ticker.startswith(o) and _DERIVATIVE.fullmatch(line.ticker[len(o):]) for o in tickers)]
    return []        # the directory has no debt lines


def decide(question: str, company_ticker: str, company_name: str) -> ScopeDecision | None:
    """None when the question names no kind of security; otherwise what to do."""
    from .issuer_identity import _load_directory, official_name_spans, symbol
    try:
        directory = _load_directory()
        lines = issuer_lines(directory, company_ticker)
        titles = [company_name] + sorted({line.name for line in lines})
        spans = [span for span, _ in official_name_spans(question)]
        kinds = requested_kinds(question, titles, spans, [line.ticker for line in lines] or [company_ticker])
    except Exception:
        return None
    if not kinds:
        return None
    issuer = company_name or (lines[0].name if lines else company_ticker)
    if len(kinds) > 1:
        return ScopeDecision(kinds, "label", issuer, company_ticker, note="several kinds of security named")
    kind = kinds[0]
    matched = lines_of_kind(kind, lines) if lines else []
    own = symbol(company_ticker)
    typed = [line for line in matched if re.search(rf"(?<![\w$.-])\$?{re.escape(line.ticker.replace('.', '-'))}(?![\w])|(?<![\w$.-])\$?{re.escape(line.ticker)}(?![\w])", question)]
    chosen = typed[0] if typed else next((line for line in matched if symbol(line.ticker) == own and kind != "share_class"), None)
    if chosen is not None:      # the user named this line by its ticker, or the company was selected as this line: not a guess
        return ScopeDecision(kinds, "label", issuer, company_ticker, [(line.ticker, line.name) for line in matched], selected=chosen.ticker)
    if len(matched) >= 2:
        return ScopeDecision(kinds, "ask", issuer, company_ticker, [(line.ticker, line.name) for line in matched])
    if kind == "share_class":
        return ScopeDecision(kinds, "label", issuer, company_ticker, [(line.ticker, line.name) for line in matched],
                             note="the SEC ticker directory lists at most one share class for this issuer")
    if len(matched) == 1:
        return ScopeDecision(kinds, "label", issuer, company_ticker, [(matched[0].ticker, matched[0].name)], selected=matched[0].ticker)
    return ScopeDecision(kinds, "label", issuer, company_ticker)


def _kind_text(kinds: list[str]) -> str:
    names = [_PHRASE[k] for k in kinds]
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def label_text(decision: ScopeDecision) -> str:
    kind = _kind_text(decision.kinds); who = f"{decision.issuer_name} ({decision.ticker})"
    unavailable = "security-specific evidence (terms, price, ranking, conversion or redemption rights) is not available in this analysis"
    if decision.note.startswith("the SEC ticker directory lists at most one"):
        return (f"{LABEL_START} you asked about {decision.issuer_name}'s {kind}. The SEC ticker directory lists only one share class for this issuer, so no separate class could be identified, and "
                f"{unavailable}. The answer below is about {who} at issuer level and makes no claim specific to the {kind}.")
    if decision.selected:
        return (f"{LABEL_START} you asked about {decision.issuer_name}'s {kind} ({decision.selected}). This answer is about {who} at issuer level; {unavailable}, "
                f"so nothing below is a claim about the {kind} itself.")
    if decision.lines or len(decision.kinds) > 1:
        return (f"{LABEL_START} you asked about {decision.issuer_name}'s {kind}. This answer is about {who} at issuer level; {unavailable}, "
                f"so nothing below is a claim about the {kind} itself.")
    return (f"{LABEL_START} you asked about {decision.issuer_name}'s {kind}. The SEC ticker directory lists no line for the {kind} of this issuer, and {unavailable}. "
            f"The answer below is about {who} at issuer level and makes no claim specific to the {kind}.")


def clarification_text(decision: ScopeDecision) -> str:
    kind = _kind_text(decision.kinds); options = "; ".join(f"{name} ({ticker})" for ticker, name in decision.lines[:6])
    return (f"{decision.issuer_name} has {len(decision.lines)} listed lines that could be the {kind} you mean: {options}. Which one do you mean? "
            f"Ask again with its ticker, or ask about {decision.issuer_name} as a company. Security-specific evidence (terms, price, ranking, conversion or redemption rights) "
            f"is not available in this analysis, so an answer would be at issuer level.")


def apply_label(response, decision: ScopeDecision) -> None:
    """Add the scope label to the visible answer (first sentence of `direct_answer`), to the constraint and unanswered lists and to `routing`."""
    label = label_text(decision); kind = _kind_text(decision.kinds)
    answer = response.answer if isinstance(response.answer, dict) else None
    if answer is None:
        return
    thesis = answer.get("investment_thesis")
    if isinstance(thesis, dict):
        current = thesis.get("direct_answer") or ""
        thesis["direct_answer"] = f"{label}\n\n{current}" if current else label
        constraints = thesis.get("analysis_foundation_constraints")
        thesis["analysis_foundation_constraints"] = [label, *(constraints if isinstance(constraints, list) else [])]
    source = answer.get("source_answer")
    if isinstance(source, dict):
        parts = source.get("unanswered_parts")
        source["unanswered_parts"] = [*(parts if isinstance(parts, list) else []), f"Security-specific evidence for the {kind}: not available (answer is at issuer level)."]
    elif not isinstance(thesis, dict):
        answer["security_scope_note"] = label
    response.routing = {**(response.routing or {}), "security_scope": {
        "requested": decision.kinds, "action": "answered_at_issuer_level", "matched_lines": [t for t, _ in decision.lines], "selected_line": decision.selected or None,
        "issuer_ticker": decision.ticker, "security_specific_evidence": "unavailable"}}
