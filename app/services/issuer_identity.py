"""Exact current SEC issuer discovery; no fuzzy guesses or historical inference."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from threading import Lock
import time

from ..schemas import CompanyContext

logger = logging.getLogger(__name__)
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,11}(?:[.-][A-Z0-9]{1,4})?$")
_SUFFIX = re.compile(r"\s+(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc)\.?$", re.I)
_cache = None
_expires_at = 0.0
_retry_at = 0.0
_lock = Lock()
# (fetched_at, generation) of the shared response the last fetch returned.
# Written and read only while holding _lock.
_fetched = None
DIRECTORY_TTL_SECONDS = 3600


class CompanyIdentityError(ValueError):
    """Company analysis cannot proceed without a verified identity."""


@dataclass(frozen=True)
class Issuer:
    ticker: str
    cik: str
    name: str


@dataclass
class Directory:
    symbols: dict[str, Issuer]
    names: dict[str, list[Issuer]]


def symbol(value: str) -> str:
    return value.strip().lstrip("$").upper().replace("-", ".")


# SEC titles end with a state or country tag ("LITTELFUSE INC /DE", "PORTLAND GENERAL ELECTRIC CO /OR/", "PATRIOT ACQUISITION CORP./CI"):
# it is a registry annotation, not part of the name a person types, so it is not part of the key.
_REGISTRY_TAG = re.compile(r"\s*/[A-Za-z]{2,4}/?\s*$")


def name_key(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", _REGISTRY_TAG.sub("", value).lower()).strip()
    while _SUFFIX.search(value):
        value = _SUFFIX.sub("", value).strip()
    return value


def parse_directory(data: object) -> Directory:
    """Validate official rows and withhold conflicting symbols/name matches."""
    symbols, names, conflicts = {}, {}, set()
    if not isinstance(data, dict):
        return Directory({}, {})
    for row in data.values():
        if not isinstance(row, dict):
            continue
        ticker, title, cik = row.get("ticker"), row.get("title"), row.get("cik_str")
        if (not isinstance(ticker, str) or not _SYMBOL.fullmatch(ticker.upper())
                or not isinstance(title, str) or not 2 <= len(title.strip()) <= 300
                or isinstance(cik, bool) or not re.fullmatch(r"[0-9]{1,10}", str(cik))
                or int(cik) <= 0):
            continue
        item = Issuer(symbol(ticker), str(int(cik)).zfill(10), title.strip())
        existing = symbols.get(item.ticker)
        if existing and existing != item:
            conflicts.add(item.ticker)
        symbols[item.ticker] = item
    for ticker in conflicts:
        symbols.pop(ticker, None)
    for item in symbols.values():
        names.setdefault(name_key(item.name), []).append(item)
    return Directory(symbols, names)


def _load_directory() -> Directory:
    global _cache, _expires_at, _retry_at, _fetched
    now = time.monotonic()
    if _cache is not None and now < _expires_at:
        return _cache
    if now < _retry_at:
        return Directory({}, {})
    with _lock:
        now = time.monotonic()
        if _cache is not None and now < _expires_at:
            return _cache
        if now < _retry_at:
            return Directory({}, {})
        _fetched = None
        try:
            directory = parse_directory(_fetch_directory_json())
            fetched_at, generation = _fetched or (now, None)
            if not directory.symbols:
                if generation is not None:
                    # Let the next eligible attempt fetch again, not reuse it.
                    from .providers.sec_provider import discard_shared_company_tickers
                    discard_shared_company_tickers(generation)
                raise ValueError("empty issuer directory")
            # Freshness runs from when SEC served the response, not from reuse.
            _cache, _expires_at, _retry_at = directory, fetched_at + DIRECTORY_TTL_SECONDS, 0.0
            return directory
        except Exception as exc:
            _retry_at = now + 30
            logger.warning("Official issuer directory unavailable: %s", type(exc).__name__)
            # Expired metadata must not silently authorize a current identity.
            return Directory({}, {})


def _fetch_directory_json():
    """The full SEC directory, shared with the ticker/CIK map when eligible."""
    global _fetched
    from .providers.sec_provider import shared_company_tickers
    data, fetched_at, generation = shared_company_tickers(max_age=DIRECTORY_TTL_SECONDS, timeout=5)
    _fetched = (fetched_at, generation)
    return data


def exact_issuer(value: str, directory: Directory) -> Issuer | None:
    match = directory.symbols.get(symbol(value))
    if match:
        return match
    matches = directory.names.get(name_key(value), [])
    # Even same-issuer share classes need an explicit security selection.
    return matches[0] if len(matches) == 1 else None


def title_tag(title: str) -> str:
    """The registry tag at the end of an SEC title ("FIRST BANCORP /ME/" -> "ME", "RESOLUTION MINERALS LTD/ADR" -> "ADR"), upper case, or ""."""
    match = re.search(r"/\s*([A-Za-z]{2,4})/?\s*$", title or "")
    return match.group(1).upper() if match else ""


def _name_windows(value: str, directory: Directory) -> list[tuple[tuple[int, int], list[Issuer]]]:
    """Exact official-name word windows in free text, as (character span, issuers)."""
    from .company_detection import _TICKER_STOP_WORDS, PROTECTED_GENERIC_TICKERS, _CONTEXT_WORDS
    excluded = _TICKER_STOP_WORDS | frozenset(PROTECTED_GENERIC_TICKERS)
    words = list(re.finditer(r"[a-z0-9]+", value.lower()))
    windows = []
    for start in range(len(words)):
        for width in range(1, min(12, len(words) - start) + 1):
            key = " ".join(word.group() for word in words[start:start + width])
            if width == 1 and (len(key) < 5 or key.upper() in excluded or key in _CONTEXT_WORDS):
                continue
            found = directory.names.get(key, [])
            if not found and width > 1:
                # Windows are already normalised words, so name_key differs
                # only by removing a trailing legal form. That explicit form
                # ("NN Inc") makes a short registrant name exact; the bare
                # word ("nn") never qualifies.
                legal = name_key(key)
                if legal != key and not (" " not in legal and (
                        legal.upper() in excluded or legal in _CONTEXT_WORDS)):
                    found = directory.names.get(legal, [])
            if found:
                end = words[start + width - 1].end()
                tag = re.match(r"[\s.,]*/([A-Za-z]{2,4})/?(?![A-Za-z0-9])", value[end:])
                if tag:      # the registry tag written after the name ("... CORP /DE/") belongs to the name, not to a second company
                    end += tag.end()
                    if len({item.cik for item in found}) > 1:
                        # ... and it tells same-named issuers apart ("First Bancorp /ME/" is not "First Bancorp /PR/"): keep those titled with it.
                        written = tag.group(1).upper()
                        same = [item for item in found if (title_tag(item.name) or "") == written]
                        found = same or found
                windows.append(((words[start].start(), end), found))
    return windows


# A five-letter symbol ending in F is, by US symbology convention, an
# over-the-counter line for a foreign issuer's ordinary or preferred shares
# (SMFNF beside SMFG; ENBFF beside ENB). Within one CIK it is not a share class
# that needs an explicit selection: when exactly one other unsuffixed symbol
# remains (an exchange listing or a Y-ending ADR line), that symbol names the
# issuer. Several remaining symbols, or only F lines, still abstain.
_FOREIGN_ORDINARY_LINE = re.compile(r"[A-Z]{4}F")
_DERIVATIVE_SUFFIXES = frozenset({"W", "WS", "WT", "WW", "U", "R", "RT", "RW"})
# A warrant, unit or rights line is the primary line plus one of these suffixes, with an optional class letter (BRKRW, BRKRU, ABCAW, ABCWSA).
_SECURITY_LINE_SUFFIX = re.compile(r"(?:W|WS|WT|WW|U|UN|R|RT|RW|Z)[A-Z]?")
# A question that names a kind of security is not company-level: nothing is resolved on the company's behalf.
SECURITY_INTENT = re.compile(
    r"\b(?:warrants?|preferred|preference\s+(?:shares?|stock)|depositary|adrs?|bonds?|debentures?|notes\s+due|"
    r"(?:senior|subordinated|convertible|unsecured|exchangeable|baby)\s+(?:notes?|bonds?)|class\s+[a-z0-9]|series\s+[a-z0-9]{1,2}|units?|rights)\b", re.I)


def representative_security(items: list, directory) -> "Issuer | None":
    """The line that stands for an issuer in company-level work, or None when the lines belong to more than one CIK.

    Class and series lines (symbol with '.' or '-') and foreign OTC lines give way to listed common lines; warrant, unit and rights
    lines give way to the line they extend; of what remains, the first in directory order.
    """
    if not items or len({item.cik for item in items}) != 1:
        return None
    order = {ticker: n for n, ticker in enumerate(directory.symbols)}
    lines = sorted({item.ticker: item for item in items}.values(), key=lambda item: (order.get(item.ticker, 10 ** 9), item.ticker))
    plain = [item for item in lines if not re.search(r"[.-]", item.ticker)]
    lines = plain or lines
    listed = [item for item in lines if not _FOREIGN_ORDINARY_LINE.fullmatch(item.ticker)]
    lines = listed or lines
    names = {item.ticker for item in lines}
    primary = [item for item in lines if not any(item.ticker != other and item.ticker.startswith(other) and _SECURITY_LINE_SUFFIX.fullmatch(item.ticker[len(other):]) for other in names)]
    lines = primary or lines
    return lines[0]      # directory order lists an issuer's larger line first (GOOGL before GOOG, ZG before Z)


def official_name_spans(value: str) -> list[tuple[tuple[int, int], list[Issuer]]]:
    """Where exact current official names occur in free text, and whose they are."""
    from .company_detection import mask_exchange_prefix
    return _name_windows(mask_exchange_prefix(value), _load_directory()) if value.strip() else []


def symbol_name_collisions(value: str) -> list[Issuer]:
    """Issuers named by a symbol that is also another issuer's entire official name, or [] ("SUN": Sunoco LP and SUN)."""
    if not value.strip():
        return []
    from .company_detection import _TICKER_STOP_WORDS, PROTECTED_GENERIC_TICKERS, mask_exchange_prefix
    excluded = _TICKER_STOP_WORDS | frozenset(PROTECTED_GENERIC_TICKERS)
    directory = _load_directory()
    for token_match in re.finditer(r"(?<!\w)\$?[A-Z][A-Z0-9]{0,11}(?:[.-][A-Z0-9]{1,4})?(?!\w)", mask_exchange_prefix(value)):
        token = token_match.group()
        if token.lstrip("$") in excluded and not token.startswith("$"):
            continue
        item = directory.symbols.get(symbol(token))
        others = [other for other in directory.names.get(token.lstrip("$").lower(), []) if item and other.cik != item.cik]
        if item and others:
            return [item, *others]
    return []


# Words that describe the question, not a company: a window made only of these never names an issuer by its first word(s).
_QUESTION_WORDS = frozenset((
    "investment thesis supports support invalidate distinguish reported facts inference cite material claims risks risk main good right "
    "buy sell hold should could would what which where when why tell about financial financials performance performing performed doing "
    "compared compare versus last year quarter sales profit profits growth outlook valuation overvalued undervalued opinion think "
    "stock stocks share shares company companies business invest investing investor investors return returns price prices earnings "
    "revenue margin margins dividend dividends interest rates inflation recession market markets sector industry economy economic "
    "analysis analyze explain describe summary current latest recent future worth value fund funds trust capital group holdings "
    "global national american united general first bank energy financial services technology technologies international").split())


def name_prefix_candidates(value: str, limit: int = 5) -> list[Issuer]:
    """Issuers whose official name BEGINS with the distinctive word(s) the question uses ("Toyota" -> TOYOTA MOTOR CORP).

    Used only to make a clarification useful (offer these issuers); it never selects an issuer by itself. Windows made of question or
    generic words are ignored; the window with the fewest matching issuers (at most six) wins, then the longest, then the earliest.
    One issuer is offered once, under its shortest unsuffixed symbol.
    """
    import bisect
    if not value or not value.strip():
        return []
    from .company_detection import _TICKER_STOP_WORDS, PROTECTED_GENERIC_TICKERS, _CONTEXT_WORDS, mask_exchange_prefix
    directory = _load_directory()
    keys = sorted(directory.names)
    excluded = _TICKER_STOP_WORDS | frozenset(PROTECTED_GENERIC_TICKERS)
    masked = mask_exchange_prefix(value)
    spans = [m for m in re.finditer(r"[A-Za-z0-9]+", masked)]
    words = [m.group().lower() for m in spans]
    best = None
    for width in (3, 2, 1):
        for start in range(len(words) - width + 1):
            window = words[start:start + width]
            if all(w in _QUESTION_WORDS or w in _CONTEXT_WORDS or w.upper() in excluded for w in window):
                continue
            if width == 1:
                original = spans[start].group()
                # One word names an issuer only as a proper noun: capitalised, not just the first word of a longer sentence
                # ("Lithium prices ..."), and not a generic or question word.
                if (len(window[0]) < 4 or window[0] in _QUESTION_WORDS or window[0] in _CONTEXT_WORDS or window[0].upper() in excluded
                        or not original[0].isupper() or (start == 0 and len(words) > 3)):
                    continue
            key = " ".join(window)
            found = {}
            for k in keys[bisect.bisect_left(keys, key + " "):bisect.bisect_left(keys, key + "!")]:
                for item in directory.names[k]:
                    found.setdefault(item.cik, []).append(item)
            for item in directory.names.get(key, []):
                found.setdefault(item.cik, []).append(item)
            if not found or len(found) > 6:
                continue
            rank = (len(found), -width, start)
            if best is None or rank < best[0]:
                best = (rank, found)
    if best is None:
        return []
    out = []
    for items in best[1].values():
        plain = sorted((i for i in items if not re.search(r"[.-]", i.ticker)), key=lambda i: (len(i.ticker), i.ticker)) or sorted(items, key=lambda i: i.ticker)
        out.append(plain[0])
    return sorted(out, key=lambda i: (len(i.name), i.name))[:limit]


_NAME_EDGE_STOP = frozenset("a an the of and for in on to is are was what which who how why when where about with from by at as or vs versus its it".split())
_NAME_TAIL = frozenset("trust fund funds inc incorporated corp corporation co company companies ltd limited plc llc lp group holdings holding".split())


_LEGAL_WORDS = frozenset("inc incorporated corp corporation co company ltd limited plc llc lp".split())
_LOOSE_CACHE: dict = {}


def _loose(text: str) -> str:
    """A name key with its legal-form words removed, padded with spaces, for comparing a typed phrase with a name that carries 'Corp' or 'Inc' in its middle."""
    return " " + " ".join(w for w in text.split() if w not in _LEGAL_WORDS) + " "


def _loose_names(directory) -> list:
    cached = _LOOSE_CACHE.get("names")
    if cached is None or cached[0] is not directory.names:
        cached = (directory.names, [(key, _loose(key)) for key in directory.names])
        _LOOSE_CACHE["names"] = cached
    return cached[1]


def other_issuers_naming_phrase(value: str, hits: list[tuple[int, int]], own_ciks: set[str]) -> tuple[list[Issuer], str, bool]:
    """Issuers other than the matched one whose official name contains the phrase around a matched word.

    A brand alias or ticker-like word that sits inside a longer proper name ("Eaton" in "Eaton Vance Duration Income Fund", "OR" or
    "General Electric" in "Portland General Electric") may belong to that longer name. `hits` are the character spans of the matched
    word in `value`; `own_ciks` are the CIKs of the issuer the word resolved to. Returns (issuers, phrase, sole): the issuers whose name
    contains the longest phrase made of the matched word plus its neighbours (neither edge a function word) that the matched issuer's
    own name does not contain, the phrase, and True when exactly one issuer qualifies and its name continues the phrase only with
    legal-form or generic words ("... Realty Income" -> "... Realty Income Trust"). Empty when nothing qualifies.
    """
    if not value.strip() or not hits:
        return [], "", False
    from .company_detection import mask_exchange_prefix
    masked = mask_exchange_prefix(value)
    directory = _load_directory()
    words = [(m.group().lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9]+", masked)]
    own_keys = [" " + key + " " for key, items in directory.names.items() if any(i.cik in own_ciks for i in items)]
    best = None
    loose_own = [_loose(own) for own in own_keys]
    for hit_start, hit_end in hits:
        covered = [n for n, (_, start, end) in enumerate(words) if start < hit_end and end > hit_start]
        if not covered:
            return [], "", False
        first, last = covered[0], covered[-1]
        hit_best = None
        for loose in (False, True):      # a legal-form word inside the other name ("Trust for Allstate Corp Securities") is passed over only when the exact phrase found nothing
            if hit_best is not None:
                break
            loose_names = _loose_names(directory) if loose else None
            for left in range(0, 4):
                for right in range(0, 5):
                    lo, hi = first - left, last + right
                    if (left + right == 0) or lo < 0 or hi >= len(words) or hi - lo + 1 > 8:
                        continue
                    if words[lo][0] in _NAME_EDGE_STOP or words[hi][0] in _NAME_EDGE_STOP:
                        continue
                    phrase = " ".join(w[0] for w in words[lo:hi + 1]); padded = " " + phrase + " "
                    core = " " + name_key(phrase) + " "      # the phrase without a trailing legal form: "... Acquisition Corp" is the same name as "... Acquisition"
                    if any(padded in own or core in own for own in own_keys):
                        continue
                    found = {}
                    if loose:
                        lphrase = _loose(phrase)
                        if len(lphrase.split()) < 2 or any(lphrase in own for own in loose_own):
                            continue
                        for key, lkey in loose_names:
                            if lphrase in lkey:
                                for item in directory.names[key]:
                                    if item.cik not in own_ciks:
                                        found.setdefault(item.cik, []).append((key, item))
                    else:
                        for key, items in directory.names.items():
                            if padded in " " + key + " ":
                                for item in items:
                                    if item.cik not in own_ciks:
                                        found.setdefault(item.cik, []).append((key, item))
                    if found and (hit_best is None or (hi - lo, -len(found)) > (hit_best[0], -len(hit_best[1]))):
                        hit_best = (hi - lo, found, phrase)
        if hit_best is None:
            return [], "", False      # this occurrence stands on its own ("... for T, given competition from T-Mobile US"): the word is really there
        if best is None or (hit_best[0], -len(hit_best[1])) > (best[0], -len(best[1])):
            best = hit_best
    if best is None:
        return [], "", False
    _, found, phrase = best
    issuers = []
    for rows in found.values():
        plain = sorted((i for _, i in rows if not re.search(r"[.-]", i.ticker)), key=lambda i: (len(i.ticker), i.ticker)) or sorted((i for _, i in rows), key=lambda i: i.ticker)
        issuers.append(plain[0])
    issuers.sort(key=lambda i: (len(i.name), i.name))
    sole = False
    if len(found) == 1:
        keys = [key for key, _ in next(iter(found.values()))]
        sole = any(key.startswith(phrase + " ") and set(key[len(phrase):].split()) <= _NAME_TAIL or key == phrase for key in keys)
    return issuers[:6], phrase, sole


def discover_company(value: str, *, question_text: bool = False, as_of=None) -> CompanyContext | None:
    """Resolve exact official names/tickers; ambiguous and historical gaps close.

    Free text uses full name token windows, never arbitrary common-word ticker
    tokens. Structured company selections may use lowercase or class symbols.
    """
    if not value.strip() or as_of:
        return None  # A current directory cannot prove historical identity.
    if question_text:
        from .company_detection import mask_exchange_prefix
        value = mask_exchange_prefix(value)
    directory = _load_directory()
    if not question_text:
        issuer = exact_issuer(value, directory)
    else:
        from .company_detection import _TICKER_STOP_WORDS, PROTECTED_GENERIC_TICKERS
        excluded = _TICKER_STOP_WORDS | frozenset(PROTECTED_GENERIC_TICKERS)
        matches = {}
        token_lines = []      # symbols the user typed: an explicit security
        # Full exact name spans take precedence over ticker-like words inside
        # that name: SEC's "WD 40 CO" must not also select ticker WD.
        name_matches = _name_windows(value, directory)
        name_spans = [span for span, _ in name_matches]
        # The longest exact name wins: a shorter official name lying wholly
        # inside a longer one ("southern" in "southern copper corp") is part of
        # that name, not a second company.
        for span, found in name_matches:
            if not any(other != span and other[0] <= span[0] and span[1] <= other[1]
                       for other, _ in name_matches):
                for item in found:
                    matches[item.ticker] = item
        for token_match in re.finditer(r"(?<!\w)\$?[A-Z][A-Z0-9]{0,11}(?:[.-][A-Z0-9]{1,4})?(?!\w)", value):
            if any(start <= token_match.start() and token_match.end() <= end
                   for start, end in name_spans):
                continue
            token = token_match.group()
            if token.lstrip("$") in excluded and not token.startswith("$"):
                continue
            item = directory.symbols.get(symbol(token))
            if item:
                matches[item.ticker] = item
                token_lines.append(item.ticker)
                # A symbol that is also another issuer's entire official name ("SUN" is Sunoco LP's symbol and an issuer's
                # name; "HP" is Helmerich & Payne's symbol and HP Inc.'s name) names two issuers: it must not pick one.
                for other in directory.names.get(token.lstrip("$").lower(), []):
                    if other.cik != item.cik:
                        matches[other.ticker] = other
        issuer = next(iter(matches.values())) if len(matches) == 1 else None
        if issuer is None and len({item.cik for item in matches.values()}) == 1:
            # One issuer's securities (common plus preferred or notes): the
            # single symbol without a class or series suffix names the issuer.
            # Distinct base symbols (two share classes) still abstain.
            base = [item for item in matches.values() if not re.search(r"[.-]", item.ticker)]
            if len(base) > 1:
                # An issuer's US listing or ADR beside its foreign-security OTC lines.
                # Distinct share classes (GOOGL/GOOG) still abstain.
                listed = [item for item in base if not _FOREIGN_ORDINARY_LINE.fullmatch(item.ticker)]
                base = listed if len(listed) == 1 else base
            if len(base) > 1:
                # An offering's other lines: warrants, units and rights carry the common symbol plus a derivative
                # suffix (GRAB / GRABW, CORZ / CORZW / CORZR / CORZZ). One symbol that all the others extend this
                # way names the issuer; unrelated share classes (GOOGL/GOOG, RUSHA/RUSHB) still abstain.
                derivatives = {item.ticker for item in base for other in base
                               if other.ticker != item.ticker and item.ticker.startswith(other.ticker)
                               and item.ticker[len(other.ticker):] in _DERIVATIVE_SUFFIXES}
                primary = [item for item in base if item.ticker not in derivatives]
                base = primary if len(primary) == 1 else base
            issuer = base[0] if len(base) == 1 else None
        if issuer is None and not token_lines:
            # Every plausible security is one issuer's: a company-level question is about the issuer. A question that names a kind of
            # security (warrants, preferred, notes, a share class) is not, and keeps asking.
            outside = list(value)
            for start, end in name_spans:      # spans may overlap ("Meridian Utility" inside "Meridian Utility Co"): blank by position
                outside[start:end] = " " * (end - start)
            outside = "".join(outside)
            if not SECURITY_INTENT.search(outside):
                issuer = representative_security(list(matches.values()), directory)
    if issuer is None:
        return None
    return CompanyContext(ticker=issuer.ticker, company_name=issuer.name, aliases=[value])
