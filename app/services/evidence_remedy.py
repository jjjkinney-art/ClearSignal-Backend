"""Remedy router and source eligibility gate (pure, recommendations only, unwired).

Nothing here retrieves, retries, spends or edits an answer, and nothing is imported by the router,
the pilot or the Task 1 outcome record. It makes the first fallback decisions executable and testable:

* ``remedy_for``       what would fix an unmet evidence need, taken from a Task 1 outcome record.
                       It returns a recommendation. It never retries or fetches.
* ``source_eligibility``  whether a source *descriptor* (metadata only) may go forward to claim
                       verification. **It never marks a claim verified.** Verification is a separate step
                       against retained bytes (quote, table or XBRL binding), which this module cannot do.

Every approval a rule depends on lives in ``SourcePolicy`` and defaults to *unapproved*, so with the
default policy no alternate-source claim is eligible. Policy values used by the tests are invented
fixtures, not decisions.

Launch gates: claims that come from a fallback source count toward the same launch gates as every
other claim (material-number accuracy, claim-to-source binding, zero fabricated sources). Report them
with a separate breakdown by source tier (``tier_breakdown``). See docs/EVIDENCE_REMEDY_20261110.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# --------------------------------------------------------------------------------------------------
# Remedy router
# --------------------------------------------------------------------------------------------------

NONE = "none"
BETTER_READING = "better_reading_of_retained_sec_evidence"
NEW_SEC_RETRIEVAL = "new_sec_retrieval_needed"
RETRY = "retry_same_source"
ALTERNATE = "alternate_source"
DISCLOSE = "disclose_only"
WITHHOLD = "withhold"
REMEDIES = (NONE, BETTER_READING, NEW_SEC_RETRIEVAL, RETRY, ALTERNATE, DISCLOSE, WITHHOLD)

# Failure classes, kept apart: each has its own recommendation.
RATE_LIMITED, SERVER_ERROR, NOT_FOUND, FORBIDDEN, TRANSPORT = "rate_limited", "server_error", "not_found", "forbidden", "transport"
INTEGRITY, TOO_LARGE, TIME_LIMIT, NOT_READ, LIST_FAILED, OTHER_CLIENT = (
    "integrity", "too_large", "time_limit", "not_read", "list_failed", "other_client_error")
_TRANSPORT_CLASSES = {"ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout", "ConnectionResetError",
                      "URLError", "SSLError", "ChunkedEncodingError", "ProxyError", "RemoteDisconnected"}


def classify_failure(record: dict) -> str:
    """The failure class of a ``failed`` outcome record (or of the failed attempt behind it)."""
    detail = record.get("detail") or {}
    status, error = detail.get("http_status"), str(detail.get("error_class") or "")
    reason = record.get("reason")
    if reason == "time_limit":
        return TIME_LIMIT
    if reason == "filing_too_large":
        return TOO_LARGE
    if error in {"cik_mismatch"}:
        return INTEGRITY
    if isinstance(status, int):
        if status == 429:
            return RATE_LIMITED
        if status == 404:
            return NOT_FOUND
        if status == 403:
            return FORBIDDEN
        if status >= 500:
            return SERVER_ERROR
        if status >= 400:
            return OTHER_CLIENT
    if error in _TRANSPORT_CLASSES or error.endswith("Timeout") or error.endswith("Error") and not status:
        return TRANSPORT
    if reason == "filing_list_failed":
        return LIST_FAILED
    return NOT_READ


@dataclass(frozen=True)
class SourcePolicy:
    """Every approval a fallback rule depends on. The default approves nothing."""

    approved_identity_mappings: frozenset = frozenset()  # {(listed_key, underlying_issuer_key)}
    approved_regulators: frozenset = frozenset()  # e.g. {"cvm_br"}: primary-tier home regulators
    licensed_providers: frozenset = frozenset()  # market-data vendors with approved terms
    event_corroboration_approved: bool = False  # decision 3 (two independent origins)
    third_party_labelled_approved: bool = False  # decision 4 ("reported by X, not verified")
    issuer_ir_numeric_eligible: bool = False  # decision 1 (recommended False)
    min_independent_origins: int = 2
    # Decision on source ranking and conflict resolution is still open. While False, ``arbitrate`` applies no
    # ranking at all: any disagreement among eligible candidates withholds every one of them.
    tier_ranking_approved: bool = False


DEFAULT_POLICY = SourcePolicy()


def _out(remedy, reason, *, rationale, permitted=True, blocked_by=(), retry=None, live_approval=False,
         if_not_permitted=None, source_families=()):
    assert remedy in REMEDIES
    return {"remedy": remedy, "reason": reason, "rationale": rationale, "permitted": permitted,
            "blocked_by": list(blocked_by), "requires_live_approval": live_approval, "retry": retry,
            "if_not_permitted": if_not_permitted, "source_families": list(source_families),
            "executes_anything": False}


def _retry(failure_class, *, retryable, note):
    # No attempt count is suggested: how many retries, and at what cost, is an unapproved budget decision.
    return {"failure_class": failure_class, "retryable": retryable, "budget_required": retryable, "note": note}


def _failure_remedy(record):
    cls = classify_failure(record)
    table = {
        RATE_LIMITED: (RETRY, True, "The source asked us to slow down; a later attempt within a budget may succeed."),
        SERVER_ERROR: (RETRY, True, "A server-side error; a later attempt within a budget may succeed."),
        TRANSPORT: (RETRY, True, "A connection or timeout error; a later attempt within a budget may succeed."),
        TIME_LIMIT: (RETRY, True, "The request ran out of time; a later attempt may succeed, and it needs a time budget."),
        LIST_FAILED: (RETRY, True, "The filing list could not be retrieved; a later attempt may succeed."),
        NOT_READ: (RETRY, True, "The filing could not be read; a later attempt may succeed."),
        NOT_FOUND: (DISCLOSE, False, "A 404 does not prove absence, and repeating the same request is not recommended. "
                                     "Disclose it as an unproven gap; if the filing list already held shows XBRL filings, "
                                     "treat the 404 as an anomaly for the owner to review."),
        FORBIDDEN: (DISCLOSE, False, "A 403 may mean access is blocked; do not retry blindly. Disclose it and refer it "
                                     "to the owner as an access-policy question."),
        INTEGRITY: (DISCLOSE, False, "The response was for a different entity; it must not be used or retried silently."),
        TOO_LARGE: (DISCLOSE, False, "The document is over the size limit, so retrying the same document cannot help."),
        OTHER_CLIENT: (DISCLOSE, False, "A client error that a retry will not change."),
    }
    remedy, retryable, note = table[cls]
    return _out(remedy, f"failed_{cls}", rationale=note, retry=_retry(cls, retryable=retryable, note=note),
                blocked_by=["access_policy_review"] if cls == FORBIDDEN else [])


def remedy_for(record: dict, *, policy: SourcePolicy = DEFAULT_POLICY, context: Optional[dict] = None) -> dict:
    """Recommend what would fix an unmet need. ``record`` is one Task 1 ``evidence_outcomes`` entry.

    ``context`` may carry ``retained_documents`` (forms whose text this request already holds),
    ``listed_key`` (the registrant the filing list belongs to) and ``underlying_issuer_key``.
    """
    context = context or {}
    state, reason = record["state"], record["reason"]
    if state == "available":
        return _out(NONE, "available", rationale="The need is met; nothing to fix.")
    if state == "failed":
        return _failure_remedy(record)
    if reason == "conflicting_evidence":
        return _out(WITHHOLD, reason, rationale="Admitted evidence conflicts, so no figure is stated until it is resolved.")
    if reason in {"ifrs_taxonomy", "non_usd_reporting", "no_same_period_pair"}:
        return _out(BETTER_READING, reason, rationale=(
            "The structured data is already retained and cannot be used by this version: read it as filed, in its own "
            "taxonomy and currency (no conversion), instead of fetching anything."))
    if reason == "selection_rules_not_met":
        return _out(BETTER_READING, reason, rationale=(
            "A filing was read and retained but no passage met the selection rules. Improving the reading of retained "
            "text may help; it is unproven that the filing holds such a disclosure."))
    if reason in {"annual_form_not_read", "interim_form_not_read"}:
        listed = (record.get("detail") or {}).get("listed_forms") or []
        retained = set(context.get("retained_documents") or ())
        if retained and retained & {f for f in listed if f in {"10-K", "20-F", "40-F", "10-Q", "6-K"}}:
            return _out(BETTER_READING, reason, rationale=(
                "The listed document was already retrieved for another need in this request; read it for this one "
                "without a new retrieval."))
        return _out(NEW_SEC_RETRIEVAL, reason, live_approval=True, rationale=(
            "The filing is listed on SEC but its text is not held. Reading it needs a new SEC retrieval, which needs "
            "separate live approval. It does not need an alternate source."))
    if reason == "no_filing_listed":
        return _out(NEW_SEC_RETRIEVAL, reason, live_approval=True, rationale=(
            "No readable report is in the recent filing list; older filing pages were not read. Reading them needs a "
            "new SEC retrieval and live approval."))
    if reason == "concept_absent_from_returned_facts":
        return _out(DISCLOSE, reason, rationale=(
            "The measure is absent from the SEC response returned. Disclose that about that response only; there is "
            "nothing further to fetch from SEC."))
    if reason == "registration_only_filing_list":
        key, under = context.get("listed_key"), context.get("underlying_issuer_key")
        blocked = []
        if not (key and under and (key, under) in policy.approved_identity_mappings):
            blocked.append("identity_mapping_unapproved")
        if not policy.approved_regulators:
            blocked.append("home_regulator_unapproved")
        return _out(ALTERNATE, reason, permitted=not blocked, blocked_by=blocked, if_not_permitted=DISCLOSE,
                    source_families=["home_regulator_filing"], rationale=(
            "SEC lists only registration forms for this registrant; operating filings are made elsewhere. A home-regulator "
            "source would be needed, but only for an approved identity mapping and an approved regulator."))
    if reason == "no_provider":
        blocked = [] if policy.licensed_providers else ["no_licensed_market_data_provider"]
        return _out(ALTERNATE, reason, permitted=not blocked, blocked_by=blocked, if_not_permitted=WITHHOLD,
                    source_families=["licensed_market_data"], rationale=(
            "Price and valuation inputs have no SEC substitute. Only a licensed, dated market-data source can supply them."))
    if reason == "identity_unresolved":
        return _out(DISCLOSE, reason, rationale="The company is not identified; ask for clarification before any source is chosen.")
    if reason == "not_recorded":
        return _out(DISCLOSE, reason, rationale=(
            "The run recorded no attempt, so nothing can be recommended. Diagnose why before choosing a remedy."))
    if reason == "not_requested":
        return _out(NONE, reason, rationale="The question did not ask for this need.")
    return _out(DISCLOSE, reason, rationale="No remedy is defined for this outcome; disclose the gap.")


# --------------------------------------------------------------------------------------------------
# Source eligibility gate (metadata only)
# --------------------------------------------------------------------------------------------------

CLAIM_TYPES = ("reported_figure", "business_risk", "event", "third_party_figure", "price_valuation", "opinion")
ELIGIBLE, ELIGIBLE_LABELLED, WITHHELD = "eligible_for_verification", "eligible_labelled", "withhold"
_EXCLUDED = {"aggregator", "forum", "promotional", "ai_summary"}
_TIER_RANK = {"primary": 0, "authoritative_secondary": 1, "reputable_secondary": 2, "unverified": 3}
_STALE = {"stale", "superseded", "conflicting", "unavailable"}


@dataclass(frozen=True)
class SourceDescriptor:
    """Metadata about a candidate source. Free text (title, excerpt) is deliberately absent from the
    decision: a source cannot argue its way in."""

    kind: str  # sec_filing, regulator_filing, issuer_release, issuer_ir, exchange, news, wire, market_data,
    #            aggregator, forum, promotional, ai_summary, unknown
    tier: str = "unverified"
    publisher: str = ""
    published_at: Optional[str] = None
    content_hash: Optional[str] = None
    independence_group: Optional[str] = None
    licence: str = "unknown"  # licensed | unlicensed | unknown
    regulator: Optional[str] = None  # which regulator, for regulator_filing
    issuer_key: Optional[str] = None  # whose filing it is
    freshness: str = "current"
    claim_key: Optional[str] = None
    asserted_value: Optional[str] = None
    title: str = field(default="", compare=False)  # ignored by every rule


def _decide(decision, reason, *, label=None, usable_in_calculation=False, warning=None, requires=()):
    # ``claim_verified`` is always False: eligibility only lets a source go on to verification.
    return {"decision": decision, "reason": reason, "label": label, "warning": warning,
            "usable_in_calculation": usable_in_calculation, "requires": list(requires), "claim_verified": False}


def _identity_ok(candidate, context, policy):
    listed, wanted = context.get("subject_key"), candidate.issuer_key
    if not wanted or not listed or wanted == listed:
        return True
    return (listed, wanted) in policy.approved_identity_mappings


def source_eligibility(claim_type: str, candidate: SourceDescriptor, *, policy: SourcePolicy = DEFAULT_POLICY,
                       context: Optional[dict] = None, others: Iterable[SourceDescriptor] = ()) -> dict:
    """May ``candidate`` go on to claim verification? Metadata only; never marks a claim verified."""
    context = context or {}
    if claim_type not in CLAIM_TYPES:
        return _decide(WITHHELD, "unknown_claim_type")
    if claim_type == "opinion":
        return _decide(WITHHELD, "opinion_is_not_evidence")
    if candidate.kind in _EXCLUDED:
        return _decide(WITHHELD, f"excluded_source_{candidate.kind}")
    if not candidate.published_at:
        return _decide(WITHHELD, "no_publication_time")
    if not candidate.content_hash:
        return _decide(WITHHELD, "no_content_hash")
    if candidate.freshness in _STALE:
        return _decide(WITHHELD, f"evidence_{candidate.freshness}")
    sec = candidate.kind == "sec_filing" and candidate.tier == "primary"
    regulator = candidate.kind == "regulator_filing" and candidate.tier == "primary"
    if regulator:
        if candidate.regulator not in policy.approved_regulators:
            return _decide(WITHHELD, "source_policy_unapproved", requires=["approved_regulator"])
    if (sec or regulator or candidate.kind in {"issuer_release", "issuer_ir", "exchange"}) \
            and not _identity_ok(candidate, context, policy):
        return _decide(WITHHELD, "identity_unapproved", requires=["approved_identity_mapping"])

    if claim_type == "reported_figure":
        if sec or regulator:
            return _decide(ELIGIBLE, "filing_primary", label="as filed")
        if candidate.kind in {"issuer_ir", "issuer_release"} and policy.issuer_ir_numeric_eligible:
            return _decide(ELIGIBLE_LABELLED, "issuer_published_not_a_filing",
                           label="issuer-published, not checked against a filing")
        return _decide(WITHHELD, "not_a_filing_for_a_reported_figure")
    if claim_type == "business_risk":
        if sec or regulator:
            return _decide(ELIGIBLE, "filing_primary", label="issuer filing")
        if candidate.kind in {"issuer_ir", "issuer_release"}:
            return _decide(ELIGIBLE_LABELLED, "issuer_statement", label="issuer statement")
        return _decide(WITHHELD, "third_party_characterisation_is_opinion")
    if claim_type == "event":
        if sec or regulator or candidate.kind in {"issuer_release", "exchange"}:
            return _decide(ELIGIBLE, "primary_event_source", label="primary source")
        if candidate.kind in {"news", "wire"}:
            if not policy.event_corroboration_approved:
                return _decide(WITHHELD, "source_policy_unapproved", requires=["event_corroboration_rule"])
            groups = {c.independence_group or f"unique:{i}" for i, c in enumerate([candidate, *others])
                      if c.kind in {"news", "wire"} and c.tier in {"reputable_secondary", "authoritative_secondary"}
                      and c.published_at and c.content_hash}
            if candidate.tier not in {"reputable_secondary", "authoritative_secondary"}:
                return _decide(WITHHELD, "source_tier_too_low")
            if len(groups) >= policy.min_independent_origins:
                return _decide(ELIGIBLE_LABELLED, "independent_corroboration", label="corroborated reporting")
            return _decide(ELIGIBLE_LABELLED, "single_origin", label="single source",
                           warning="Reported by one origin only; not corroborated.")
        return _decide(WITHHELD, "not_an_event_source")
    if claim_type == "third_party_figure":
        if not policy.third_party_labelled_approved:
            return _decide(WITHHELD, "source_policy_unapproved", requires=["third_party_figure_rule"])
        if candidate.licence != "licensed":
            return _decide(WITHHELD, "licence_unknown_or_missing")
        if candidate.tier not in {"authoritative_secondary", "reputable_secondary"}:
            return _decide(WITHHELD, "source_tier_too_low")
        return _decide(ELIGIBLE_LABELLED, "licensed_third_party", label="reported by the source, not verified")
    # price_valuation
    if candidate.kind != "market_data" or candidate.licence != "licensed" \
            or candidate.publisher not in policy.licensed_providers:
        return _decide(WITHHELD, "no_licensed_provider", requires=["licensed_market_data_provider"])
    return _decide(ELIGIBLE, "licensed_market_data", label="licensed, dated market data")


def arbitrate(candidates: Iterable[SourceDescriptor], claim_type: str, *, policy: SourcePolicy = DEFAULT_POLICY,
              context: Optional[dict] = None) -> list:
    """Which candidates for one claim may go forward when they disagree. Returns one row per candidate.

    Every row carries ``claim_verified: False``: arbitration only decides who may go on to verification.
    No source ranking is applied unless ``policy.tier_ranking_approved`` is true. Until then any disagreement
    among eligible candidates withholds all of them (fail closed). With ranking approved, same-tier
    disagreement still withholds every disagreeing candidate, and a lower tier that disagrees with the
    highest eligible tier is set aside and the disagreement recorded.
    """
    candidates = list(candidates)
    rows = []
    for index, cand in enumerate(candidates):
        verdict = source_eligibility(claim_type, cand, policy=policy, context=context,
                                     others=[c for j, c in enumerate(candidates) if j != index])
        rows.append({"index": index, "candidate": cand, **verdict, "disagreement": None})
    live = [r for r in rows if r["decision"] != WITHHELD and r["candidate"].asserted_value is not None]
    values = {r["candidate"].asserted_value for r in live}
    if len(values) > 1:
        if not policy.tier_ranking_approved:
            for r in live:
                r.update(decision=WITHHELD, reason="disagreement_ranking_policy_unapproved", disagreement="unresolved")
            return rows
        best = min(_TIER_RANK.get(r["candidate"].tier, 3) for r in live)
        top = [r for r in live if _TIER_RANK.get(r["candidate"].tier, 3) == best]
        if len({r["candidate"].asserted_value for r in top}) > 1:
            for r in live:
                r.update(decision=WITHHELD, reason="same_tier_disagreement", disagreement="same_tier")
        else:
            for r in live:
                if r not in top:
                    r.update(decision=WITHHELD, reason="disagrees_with_higher_tier", disagreement="shown_not_used")
                else:
                    r["disagreement"] = "lower_tier_disagrees"
    return rows


def tier_breakdown(records: Iterable[dict]) -> dict:
    """Counts of eligibility decisions by source tier. Fallback claims count toward the same launch gates
    as every other claim; this breakdown is reported separately. It counts decisions, not accuracy."""
    out: dict = {}
    for record in records:
        tier = record.get("tier", "unverified")
        bucket = out.setdefault(tier, {ELIGIBLE: 0, ELIGIBLE_LABELLED: 0, WITHHELD: 0})
        bucket[record["decision"]] += 1
    return out
