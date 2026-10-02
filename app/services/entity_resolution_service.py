"""
entity_resolution_service.py — High-confidence company/entity resolver.

Purpose
-------
Resolve a natural-language query to a canonical ticker+company before
retrieval and analysis begin.  Sits upstream of every other service so
all downstream components receive a single agreed-upon entity identity.

Why this layer exists (root-cause note)
---------------------------------------
In the raw company_detection pipeline, Step 1 scans for ANY uppercase token
that matches a known ticker.  In the query:

    "Can Meta continue compounding despite AI infrastructure spending pressure?"

…the token "AI" was matched first (confidence 1.0 → C3.ai) before "Meta"
(confidence 0.95 → META) was ever checked.  This service adds:
  1. Full-query context-aware resolution (prefer company names over
     incidental uppercase tokens).
  2. Protected generic-word ticker disambiguation (AI/APP/NET/SNOW/DASH/…).
  3. Explicit-intent detection ("ticker AI", "C3.ai", "c3 ai") that restores
     C3.ai resolution when the user clearly means C3.ai.
  4. needs_clarification flag + prompt for genuinely ambiguous cases.

Resolution priority (highest → lowest)
---------------------------------------
1. Explicit company alias in query (alias_exact, confidence 0.95) — wins over
   any incidental uppercase ticker token.
2. Explicit disambiguating phrase: "ticker AI", "C3.ai", "C3 AI" → honour the
   protected ticker despite its generic-word status.
3. Explicit uppercase ticker that is NOT a protected generic word
   (exact_ticker, confidence 1.00).
4. Fuzzy token match (>= MINIMUM_ROUTE_CONFIDENCE = 0.85).
5. not_found → check for protected generic-word tokens → needs_clarification.

Public API
----------
    from app.services.entity_resolution_service import (
        resolve_query, EntityResolutionResult
    )

    result = resolve_query(
        query="Can Meta continue compounding despite AI infrastructure spending?",
        company_hint="",  # optional pre-extracted company_name from frontend
    )
    # result.canonical_ticker  → "META"
    # result.company_name      → "Meta Platforms Inc."
    # result.needs_clarification → False

No network calls.  Pure Python.  Returns in < 2 ms.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple

from .company_detection import (
    _alias_lookup,
    _extract_explicit_ticker,
    _fuzzy_token_match,
    resolve_entity,
    MINIMUM_ROUTE_CONFIDENCE,
    PROTECTED_GENERIC_TICKERS,
    _COMPANY_DB,
)

logger = logging.getLogger(__name__)

_ALIAS_RELATIONSHIPS = {
    ("META", "fb"): "former_ticker",
    ("META", "facebook"): "former_name_or_brand",
    ("META", "instagram"): "subsidiary",
    ("META", "whatsapp"): "subsidiary",
    ("GOOGL", "google"): "subsidiary",
    ("GOOGL", "google cloud"): "business_unit",
    ("GOOGL", "google search"): "business_unit",
    ("AMZN", "aws"): "business_unit",
    ("SHEL", "royal dutch shell"): "former_name",
    ("SHEL", "royal dutch"): "former_name",
}
_ACQUISITION_RELATIONSHIPS = {
    # Legal close dates, not announcement dates. Historical tickers are kept
    # so pre-close research is never silently attributed to the buyer.
    ("GOOGL", "youtube"): ("2006-11-13", ""),
    ("MSFT", "linkedin"): ("2016-12-08", "LNKD"),
    ("AMZN", "whole foods"): ("2017-08-28", "WFM"),
    ("MSFT", "github"): ("2018-10-26", ""),
    ("MSFT", "activision blizzard"): ("2023-10-13", "ATVI"),
}
_SEPARATION_RELATIONSHIPS = {
    # First day as a legally separate public company, plus the former parent.
    ("PYPL", "paypal"): ("2015-07-17", "EBAY", "spin_off"),
    ("KD", "kyndryl"): ("2021-11-03", "IBM", "spin_off"),
    ("GEHC", "ge healthcare"): ("2023-01-04", "GE", "spin_off"),
    ("GEHC", "ge healthcare technologies"): ("2023-01-04", "GE", "spin_off"),
    ("GEV", "ge vernova"): ("2024-04-02", "GE", "spin_off"),
}
_SAME_ISSUER_ALIAS_WINDOWS = {
    # Last trading day under the former symbol. The issuer/CIK did not change.
    ("META", "fb"): ("", "2022-06-08"),
}
_SHARE_CLASS_TICKERS = {"BRK.A", "BRK.B", "BF.B", "GOOG", "GOOGL"}

# ---------------------------------------------------------------------------
# Explicit-intent patterns — override protected ticker stop-word suppression
# ---------------------------------------------------------------------------
# When the user explicitly names a protected-ticker company using one of these
# patterns, we restore the resolution rather than requiring clarification.
# Examples: "ticker AI", "C3.ai", "c3 ai", "ticker APP", "AppLovin", etc.
#
# NOTE: Most of these are already handled by the alias map ("c3 ai" → AI,
# "applovin" → APP, "cloudflare" → NET, "snowflake" → SNOW, etc.).
# This set covers the remaining edge-case explicit signals.

_EXPLICIT_TICKER_PHRASES: dict[str, str] = {
    # Patterns that, if found (case-insensitive), force a specific ticker.
    # Key: lowercase regex pattern; Value: forced ticker.
    r"\bticker\s+ai\b":            "AI",
    r"\bticker\s+app\b":           "APP",
    r"\bticker\s+net\b":           "NET",
    r"\bticker\s+snow\b":          "SNOW",
    r"\bticker\s+dash\b":          "DASH",
    r"\bticker\s+path\b":          "PATH",
    r"\bticker\s+open\b":          "OPEN",
    r"\bticker\s+shop\b":          "SHOP",
    r"\bticker\s+arm\b":           "ARM",
    r"\bticker\s+now\b":           "NOW",
    # C3.ai explicit forms
    r"\bc3[\.\s]?ai\b":            "AI",
    # Standalone uppercase-in-context patterns like "$AI" or "(AI)"
    r"\$ai\b":                     "AI",
    r"\$app\b":                    "APP",
    r"\$net\b":                    "NET",
    r"\$snow\b":                   "SNOW",
    r"\$dash\b":                   "DASH",
}

# Pre-compile for speed
_EXPLICIT_TICKER_COMPILED: list[Tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), ticker)
    for pat, ticker in _EXPLICIT_TICKER_PHRASES.items()
]

# Regex to detect a protected-generic-ticker token appearing standalone
# and uppercase in the query — used for clarification detection.
_STANDALONE_UPPER_TOKEN_RE = re.compile(r"\b([A-Z]{2,5})\b")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class EntityResolutionResult:
    """Complete result from resolve_query().

    Attributes
    ----------
    canonical_ticker : str
        The resolved ticker symbol (e.g. "META").  Empty string when
        resolution failed or needs_clarification is True.
    company_name : str
        The canonical company name (e.g. "Meta Platforms Inc.").
    confidence_score : float
        Resolution confidence: 1.0 = exact ticker, 0.95 = alias exact,
        0.72–0.95 = fuzzy, 0.0 = not resolved.
    matched_alias : str
        The alias / token / ticker that triggered the match.
    resolution_method : str
        "alias_exact" | "exact_ticker" | "fuzzy_token" | "explicit_phrase" |
        "not_found" | "needs_clarification"
    ambiguity_reason : str
        Human-readable description of why the query was ambiguous.
        Non-empty only when needs_clarification is True.
    needs_clarification : bool
        True when the query contains a protected generic-word ticker token
        but no unambiguous company name was found.
    clarification_prompt : str
        The question to show the user when needs_clarification is True.
    resolution_warning : str
        Non-empty when the resolution succeeded but with reduced confidence
        or notable ambiguity — shown as a subtle UI chip.
    sector : str
        Sector for the resolved company (empty if unknown).
    industry : str
        Industry for the resolved company (empty if unknown).
    """
    canonical_ticker:     str   = ""
    company_name:         str   = ""
    confidence_score:     float = 0.0
    matched_alias:        str   = ""
    resolution_method:    str   = "not_found"
    ambiguity_reason:     str   = ""
    needs_clarification:  bool  = False
    clarification_prompt: str   = ""
    resolution_warning:   str   = ""
    sector:               str   = ""
    industry:             str   = ""
    candidates:           List[Tuple[str, str, float]] = field(default_factory=list)
    identity_relation:    str = "canonical_issuer"
    requested_entity:     str = ""
    relationship_status:  str = "current"
    relationship_effective_from: str = ""
    relationship_effective_to: str = ""
    historical_ticker:    str = ""
    predecessor_ticker:   str = ""
    relationship_event:   str = ""
    identity_as_of:       str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_explicit_phrase(text: str) -> Optional[str]:
    """Return a forced ticker if the query contains an explicit-intent pattern.

    E.g. "Is the ticker AI investable?" → "AI"
         "What about C3.ai valuation?"  → "AI"
         "Is $NET overvalued?"          → "NET"
    """
    for pattern, ticker in _EXPLICIT_TICKER_COMPILED:
        if pattern.search(text):
            return ticker
    return None


def _detect_protected_tokens(text: str) -> List[str]:
    """Return any protected-generic-ticker tokens found as standalone uppercase
    in the raw query text.  Used for clarification detection."""
    found = []
    for match in _STANDALONE_UPPER_TOKEN_RE.finditer(text):
        token = match.group(1)
        if token in PROTECTED_GENERIC_TICKERS:
            found.append(token)
    return found


def _build_result_from_resolution(resolution, warning: str = "") -> EntityResolutionResult:
    """Convert a company_detection.EntityResolution into an EntityResolutionResult."""
    ctx = resolution.context
    if ctx is None:
        return EntityResolutionResult(
            resolution_method="not_found",
            candidates=resolution.candidates,
        )
    info = _COMPANY_DB.get(ctx.ticker, {})
    return EntityResolutionResult(
        canonical_ticker=ctx.ticker,
        company_name=ctx.company_name,
        confidence_score=resolution.confidence,
        matched_alias=resolution.matched_text,
        resolution_method=resolution.method,
        resolution_warning=warning,
        sector=info.get("sector", ""),
        industry=info.get("industry", ""),
        candidates=resolution.candidates,
    )


def _make_result_for_ticker(ticker: str, method: str, alias: str,
                             confidence: float = 1.0,
                             warning: str = "") -> EntityResolutionResult:
    """Build a result directly from a known ticker (used for explicit phrases)."""
    info = _COMPANY_DB.get(ticker, {})
    return EntityResolutionResult(
        canonical_ticker=ticker,
        company_name=info.get("company_name", ticker),
        confidence_score=confidence,
        matched_alias=alias,
        resolution_method=method,
        resolution_warning=warning,
        sector=info.get("sector", ""),
        industry=info.get("industry", ""),
        identity_relation=(
            "share_class" if ticker in _SHARE_CLASS_TICKERS
            else "canonical_issuer"
        ),
        requested_entity=alias,
    )


def _coerce_as_of(as_of: Optional[date | datetime | str]) -> Optional[date]:
    if as_of is None or as_of == "":
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    try:
        return date.fromisoformat(str(as_of).strip()[:10])
    except (TypeError, ValueError):
        return None


def _identity_metadata(
    ticker: str,
    alias: str,
    as_of: Optional[date | datetime | str] = None,
) -> dict:
    normalized = (alias or "").strip().lower()
    relation = _ALIAS_RELATIONSHIPS.get((ticker, normalized))
    acquisition = _ACQUISITION_RELATIONSHIPS.get((ticker, normalized))
    separation = _SEPARATION_RELATIONSHIPS.get((ticker, normalized))
    alias_window = _SAME_ISSUER_ALIAS_WINDOWS.get((ticker, normalized))
    effective_from = ""
    effective_to = ""
    historical_ticker = ""
    predecessor_ticker = ""
    relationship_event = ""
    status = "current"
    identity_date = _coerce_as_of(as_of)
    if acquisition is not None:
        effective_from, historical_ticker = acquisition
        relation = "acquired_subsidiary"
        if identity_date is not None and identity_date < date.fromisoformat(effective_from):
            status = "not_yet_owned"
        relationship_event = "acquisition"
    elif separation is not None:
        effective_from, predecessor_ticker, relationship_event = separation
        relation = "separated_company"
        if identity_date is not None and identity_date < date.fromisoformat(effective_from):
            status = "pre_separation"
    elif alias_window is not None:
        effective_from, effective_to = alias_window
        relationship_event = "ticker_change"
        if identity_date is not None and identity_date <= date.fromisoformat(effective_to):
            status = "historical_alias_active"
        else:
            status = "former_alias"
    if relation is None and ticker in _SHARE_CLASS_TICKERS:
        relation = "share_class"
    return {
        "identity_relation": relation or "canonical_issuer",
        "requested_entity": alias,
        "relationship_status": status,
        "relationship_effective_from": effective_from,
        "relationship_effective_to": effective_to,
        "historical_ticker": historical_ticker,
        "predecessor_ticker": predecessor_ticker,
        "relationship_event": relationship_event,
        "identity_as_of": identity_date.isoformat() if identity_date else "",
    }


def _guard_temporal_identity(result: EntityResolutionResult) -> EntityResolutionResult:
    """Fail closed when an acquisition alias predates the buyer's ownership."""
    if result.relationship_status not in {"not_yet_owned", "pre_separation"}:
        return result
    if result.relationship_status == "pre_separation":
        return EntityResolutionResult(
            matched_alias=result.matched_alias,
            resolution_method="temporal_identity_mismatch",
            ambiguity_reason=(
                f"{result.requested_entity} was not yet a separate public issuer "
                f"on {result.identity_as_of}; separation from "
                f"{result.predecessor_ticker} became effective "
                f"{result.relationship_effective_from}."
            ),
            needs_clarification=True,
            clarification_prompt=(
                f"Research predecessor {result.predecessor_ticker} as of "
                f"{result.identity_as_of}, or analyze the current standalone company?"
            ),
            identity_relation=result.identity_relation,
            requested_entity=result.requested_entity,
            relationship_status=result.relationship_status,
            relationship_effective_from=result.relationship_effective_from,
            predecessor_ticker=result.predecessor_ticker,
            relationship_event=result.relationship_event,
            identity_as_of=result.identity_as_of,
        )
    historical = (
        f" Its historical ticker was {result.historical_ticker}."
        if result.historical_ticker else ""
    )
    return EntityResolutionResult(
        matched_alias=result.matched_alias,
        resolution_method="temporal_identity_mismatch",
        ambiguity_reason=(
            f"{result.requested_entity} was not owned by {result.company_name} "
            f"on {result.identity_as_of}; ownership began "
            f"{result.relationship_effective_from}.{historical}"
        ),
        needs_clarification=True,
        clarification_prompt=(
            f"Research {result.requested_entity} as a historical standalone entity "
            f"as of {result.identity_as_of}, or analyze its current parent?"
        ),
        identity_relation=result.identity_relation,
        requested_entity=result.requested_entity,
        relationship_status=result.relationship_status,
        relationship_effective_from=result.relationship_effective_from,
        relationship_effective_to=result.relationship_effective_to,
        historical_ticker=result.historical_ticker,
        predecessor_ticker=result.predecessor_ticker,
        relationship_event=result.relationship_event,
        identity_as_of=result.identity_as_of,
    )


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

def resolve_query(
    query: str,
    company_hint: str = "",
    as_of: Optional[date | datetime | str] = None,
) -> EntityResolutionResult:
    """Resolve a natural-language query to a canonical (ticker, company_name).

    Parameters
    ----------
    query : str
        The full user query, e.g.
        "Can Meta continue compounding despite AI infrastructure spending pressure?"
    company_hint : str, optional
        Pre-extracted company name from the frontend (the AnalysisRequest
        company_name field).  Used as a secondary resolution target when
        the full query does not yield a confident result.

    Returns
    -------
    EntityResolutionResult
        Never raises.  Check needs_clarification and canonical_ticker in caller.

    Resolution algorithm
    --------------------
    1. Explicit disambiguating phrase ("ticker AI", "C3.ai", "$SNOW", …)
       → honour the protected ticker, return immediately.
    2. Alias lookup on the full query (Step 2 of company_detection pipeline).
       This finds "meta" in "Can Meta continue despite AI infrastructure?".
       → return alias_exact (confidence 0.95).
    3. Non-protected exact uppercase ticker from full query.
       → return exact_ticker (confidence 1.00).
    4. Fuzzy token match on full query (>= MINIMUM_ROUTE_CONFIDENCE).
       → return fuzzy_token.
    5. If query failed but company_hint is different, repeat 1-4 on hint.
    6. Not found — check for protected generic-word tokens in original query.
       → if found: needs_clarification=True with clarification_prompt.
       → else: not_found with candidates.
    """
    if not query and not company_hint:
        return EntityResolutionResult(resolution_method="not_found")

    primary_text = query.strip() or company_hint.strip()
    hint_text    = company_hint.strip() if company_hint.strip() != primary_text else ""

    # ── Step 1: explicit-intent phrase override ───────────────────────────────
    forced_ticker = _check_explicit_phrase(primary_text)
    if forced_ticker:
        logger.info(
            "[entity_resolution] explicit phrase override → %s (query=%r)",
            forced_ticker, primary_text[:80],
        )
        return _make_result_for_ticker(
            forced_ticker, "explicit_phrase", forced_ticker,
            confidence=0.98,
        )

    # ── Step 2: alias lookup first (finds "meta", "google", "nvidia", etc.) ──
    # Run alias lookup BEFORE exact-ticker so that a company name in the query
    # always beats an incidental uppercase token (the Meta/AI fix).
    alias_ctx = _alias_lookup(primary_text)
    if alias_ctx is not None:
        info = _COMPANY_DB.get(alias_ctx.ticker, {})
        alias = alias_ctx.aliases[0] if alias_ctx.aliases else ""
        logger.info(
            "[entity_resolution] alias_exact → %s via '%s' (query=%r)",
            alias_ctx.ticker, alias, primary_text[:80],
        )
        return _guard_temporal_identity(EntityResolutionResult(
            canonical_ticker=alias_ctx.ticker,
            company_name=alias_ctx.company_name,
            confidence_score=0.95,
            matched_alias=alias,
            resolution_method="alias_exact",
            sector=info.get("sector", ""),
            industry=info.get("industry", ""),
            **_identity_metadata(alias_ctx.ticker, alias, as_of),
        ))

    # ── Step 3: non-protected exact uppercase ticker ──────────────────────────
    # Protected generic-word tickers (AI, APP, NET, SNOW, …) are already in
    # _TICKER_STOP_WORDS so _extract_explicit_ticker won't return them.
    ticker_ctx = _extract_explicit_ticker(primary_text)
    if ticker_ctx is not None:
        info = _COMPANY_DB.get(ticker_ctx.ticker, {})
        logger.info(
            "[entity_resolution] exact_ticker → %s (query=%r)",
            ticker_ctx.ticker, primary_text[:80],
        )
        return EntityResolutionResult(
            canonical_ticker=ticker_ctx.ticker,
            company_name=ticker_ctx.company_name,
            confidence_score=1.0,
            matched_alias=ticker_ctx.ticker,
            resolution_method="exact_ticker",
            sector=info.get("sector", ""),
            industry=info.get("industry", ""),
            **_identity_metadata(ticker_ctx.ticker, ticker_ctx.ticker, as_of),
        )

    # ── Step 4: fuzzy token match on full query ───────────────────────────────
    fuzzy_result = _fuzzy_token_match(primary_text, cutoff=0.72)
    if fuzzy_result is not None:
        ctx, score, matched_alias = fuzzy_result
        confidence = round(0.50 + score * 0.47, 3)
        if confidence >= MINIMUM_ROUTE_CONFIDENCE:
            info = _COMPANY_DB.get(ctx.ticker, {})
            logger.info(
                "[entity_resolution] fuzzy_token → %s via '%s' (conf=%.2f) (query=%r)",
                ctx.ticker, matched_alias, confidence, primary_text[:80],
            )
            return _guard_temporal_identity(EntityResolutionResult(
                canonical_ticker=ctx.ticker,
                company_name=ctx.company_name,
                confidence_score=confidence,
                matched_alias=matched_alias,
                resolution_method="fuzzy_token",
                resolution_warning=(
                    f"Resolved via fuzzy match on '{matched_alias}' — "
                    f"confirm this is the right company."
                ) if confidence < 0.90 else "",
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
                **_identity_metadata(ctx.ticker, matched_alias, as_of),
            ))

    # ── Step 5: retry steps 2-4 on company_hint if different from query ───────
    if hint_text and hint_text.lower() != primary_text.lower():
        logger.debug("[entity_resolution] retrying on company_hint=%r", hint_text[:60])
        # Explicit phrase
        forced_ticker = _check_explicit_phrase(hint_text)
        if forced_ticker:
            return _make_result_for_ticker(forced_ticker, "explicit_phrase", forced_ticker, 0.98)
        # Alias
        alias_ctx = _alias_lookup(hint_text)
        if alias_ctx is not None:
            info = _COMPANY_DB.get(alias_ctx.ticker, {})
            alias = alias_ctx.aliases[0] if alias_ctx.aliases else ""
            return _guard_temporal_identity(EntityResolutionResult(
                canonical_ticker=alias_ctx.ticker,
                company_name=alias_ctx.company_name,
                confidence_score=0.95,
                matched_alias=alias,
                resolution_method="alias_exact",
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
                **_identity_metadata(alias_ctx.ticker, alias, as_of),
            ))
        # Exact ticker
        ticker_ctx = _extract_explicit_ticker(hint_text)
        if ticker_ctx is not None:
            info = _COMPANY_DB.get(ticker_ctx.ticker, {})
            return EntityResolutionResult(
                canonical_ticker=ticker_ctx.ticker,
                company_name=ticker_ctx.company_name,
                confidence_score=1.0,
                matched_alias=ticker_ctx.ticker,
                resolution_method="exact_ticker",
                sector=info.get("sector", ""),
                industry=info.get("industry", ""),
                **_identity_metadata(ticker_ctx.ticker, ticker_ctx.ticker, as_of),
            )
        # Fuzzy
        fuzzy_result = _fuzzy_token_match(hint_text, cutoff=0.72)
        if fuzzy_result is not None:
            ctx, score, matched_alias = fuzzy_result
            confidence = round(0.50 + score * 0.47, 3)
            if confidence >= MINIMUM_ROUTE_CONFIDENCE:
                info = _COMPANY_DB.get(ctx.ticker, {})
                return _guard_temporal_identity(EntityResolutionResult(
                    canonical_ticker=ctx.ticker,
                    company_name=ctx.company_name,
                    confidence_score=confidence,
                    matched_alias=matched_alias,
                    resolution_method="fuzzy_token",
                    sector=info.get("sector", ""),
                    industry=info.get("industry", ""),
                    **_identity_metadata(ctx.ticker, matched_alias, as_of),
                ))

    # ── Step 6: protected generic ticker → needs_clarification ───────────────
    protected_found = _detect_protected_tokens(primary_text)
    # Also check hint text
    if not protected_found and hint_text:
        protected_found = _detect_protected_tokens(hint_text)

    if protected_found:
        # Use the first detected protected token as the primary ambiguity subject
        token = protected_found[0]
        company_name, clarification_prompt = PROTECTED_GENERIC_TICKERS[token]
        ambiguity_reason = (
            f"'{token}' is both a valid ticker ({company_name}) and a common "
            f"English word. The query does not unambiguously identify the "
            f"company — please clarify."
        )
        logger.info(
            "[entity_resolution] needs_clarification: protected token %s detected (query=%r)",
            token, primary_text[:80],
        )
        return EntityResolutionResult(
            needs_clarification=True,
            ambiguity_reason=ambiguity_reason,
            clarification_prompt=clarification_prompt,
            resolution_method="needs_clarification",
            candidates=[(token, company_name, 0.5)],
        )

    # ── Not found ─────────────────────────────────────────────────────────────
    # Use the full resolve_entity candidates for "Did you mean?" UX
    from .company_detection import _gather_candidates
    candidates = _gather_candidates(primary_text) or _gather_candidates(hint_text or "")
    logger.info(
        "[entity_resolution] not_found (query=%r, hint=%r, candidates=%s)",
        primary_text[:60], hint_text[:40], [(t, round(s, 2)) for t, _, s in candidates[:3]],
    )
    return EntityResolutionResult(
        resolution_method="not_found",
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper used by the analysis pipeline
# ---------------------------------------------------------------------------

def resolve_for_analysis(
    user_question: str = "",
    company_hint: str = "",
) -> EntityResolutionResult:
    """Resolve entity for the analysis pipeline.

    When company_hint (the AnalysisRequest.company_name field) is explicitly
    provided and resolves successfully, it is treated as authoritative.  The
    user_question is only used as primary resolution text when company_hint is
    absent or fails to match any known entity.

    This prevents questions that mention competitor names (e.g. "Costco trades
    at a premium vs Walmart") from resolving to the wrong company.

    Parameters
    ----------
    user_question : str
        The full natural-language user question from AnalysisRequest.
    company_hint : str
        The company_name field from AnalysisRequest.  Treated as authoritative
        when non-empty and resolvable.
    """
    # When an explicit company_hint is provided, resolve it first and return
    # immediately on success.  Do NOT use user_question as primary — questions
    # routinely mention competitors and sector peers whose names would otherwise
    # override the caller's intended company.
    if company_hint.strip():
        result = resolve_query(company_hint.strip(), "")
        if result.canonical_ticker:
            return result
    # company_hint absent or unresolvable — fall back to question text as primary.
    if user_question:
        return resolve_query(user_question, company_hint)
    return EntityResolutionResult(resolution_method="not_found")
