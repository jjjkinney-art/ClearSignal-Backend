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


def name_key(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
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
    global _cache, _expires_at, _retry_at
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
        try:
            directory = parse_directory(_fetch_directory_json())
            if not directory.symbols:
                raise ValueError("empty issuer directory")
            _cache, _expires_at, _retry_at = directory, now + DIRECTORY_TTL_SECONDS, 0.0
            return directory
        except Exception as exc:
            _retry_at = now + 30
            logger.warning("Official issuer directory unavailable: %s", type(exc).__name__)
            # Expired metadata must not silently authorize a current identity.
            return Directory({}, {})


def _fetch_directory_json():
    from .providers.sec_provider import _fetch_json, _COMPANY_TICKERS_URL
    return _fetch_json(_COMPANY_TICKERS_URL, timeout=5)


def exact_issuer(value: str, directory: Directory) -> Issuer | None:
    match = directory.symbols.get(symbol(value))
    if match:
        return match
    matches = directory.names.get(name_key(value), [])
    # Even same-issuer share classes need an explicit security selection.
    return matches[0] if len(matches) == 1 else None


def discover_company(value: str, *, question_text: bool = False, as_of=None) -> CompanyContext | None:
    """Resolve exact official names/tickers; ambiguous and historical gaps close.

    Free text uses full name token windows, never arbitrary common-word ticker
    tokens. Structured company selections may use lowercase or class symbols.
    """
    if not value.strip() or as_of:
        return None  # A current directory cannot prove historical identity.
    directory = _load_directory()
    if not question_text:
        issuer = exact_issuer(value, directory)
    else:
        from .company_detection import _TICKER_STOP_WORDS, PROTECTED_GENERIC_TICKERS, _CONTEXT_WORDS
        excluded = _TICKER_STOP_WORDS | frozenset(PROTECTED_GENERIC_TICKERS)
        matches = {}
        # Full exact name spans take precedence over ticker-like words inside
        # that name: SEC's "WD 40 CO" must not also select ticker WD.
        words = list(re.finditer(r"[a-z0-9]+", value.lower()))
        name_spans = []
        for start in range(len(words)):
            for width in range(1, min(12, len(words) - start) + 1):
                key = " ".join(word.group() for word in words[start:start + width])
                if width == 1 and (len(key) < 5 or key.upper() in excluded or key in _CONTEXT_WORDS):
                    continue
                found = directory.names.get(key, [])
                if found:
                    name_spans.append((words[start].start(), words[start + width - 1].end()))
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
        issuer = next(iter(matches.values())) if len(matches) == 1 else None
    if issuer is None:
        return None
    return CompanyContext(ticker=issuer.ticker, company_name=issuer.name, aliases=[value])
