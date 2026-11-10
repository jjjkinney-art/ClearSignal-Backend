"""Annual comparisons and management explanations from a 20-F the request has already fetched (default off).

Nothing here makes a request. ``thesis_disclosures`` already fetches a 20-F for business and risk text; with
the flags on it asks that same fetch to keep two more things: the filing's own inline XBRL facts and a second
text window for the results discussion (Item 5). This module turns them into evidence:

* comparisons: annual facts of the filing itself (IFRS or US-GAAP, any ISO currency, kept as reported), each
  checked for concept, period, currency, scale, sign and reporting basis, and bound to its exact fact and
  context in the document;
* management's stated explanations, through the existing explanation engine and binder.

Both flags must be on: ``annual_filing_facts_enabled`` and ``as_reported_financials_enabled``.
"""
from __future__ import annotations

import re
import threading
from contextvars import ContextVar
from datetime import date
from decimal import Decimal
from typing import Optional

from ..providers.sec_client import SecFactRecord
from ..providers.sec_inline_facts import _TAXONOMIES, validated_observation
from . import as_reported_financials as ar

INLINE_CONCEPTS = tuple(dict.fromkeys(c for by in ar.CORE.values() for cs in by.values() for c in cs))
TAXONOMIES = ("ifrs-full", "us-gaap")
FORMS = {"20-F", "20-F/A"}


def enabled() -> bool:
    from ..config import settings
    return (getattr(settings, "annual_filing_facts_enabled", False) is True
            and getattr(settings, "as_reported_financials_enabled", False) is True)


def fetch_options() -> dict:
    """Extra arguments for the fetch the request already makes: no additional request."""
    return {"inline_fact_cik": None, "inline_fact_concepts": INLINE_CONCEPTS, "inline_fact_taxonomies": TAXONOMIES,
            "inline_fact_currencies": "*", "keep_results_window": True}


def _taxonomy(namespace: str) -> Optional[str]:
    return next((name for name in TAXONOMIES if _TAXONOMIES[name].fullmatch(namespace)), None)


def records_from_document(document, cik: str) -> list[SecFactRecord]:
    """The filing's own annual facts as records, each carrying its exact source location."""
    from .thesis_disclosures import _business_issuer_url
    if (document.document_type not in FORMS or document.publisher != "SEC EDGAR"
            or document.source_type != "regulatory_filing" or document.source_tier != "primary"
            or document.extraction_method != "html" or not _business_issuer_url(document.final_url, cik)):
        return []
    try:
        filed = date.fromisoformat(document.published_at)
        if filed > date.today():
            return []
        compact = document.final_url.split("/")[-2]
        accession = f"{compact[:10]}-{compact[10:12]}-{compact[12:]}"
    except (TypeError, ValueError, AttributeError):
        return []
    records = []
    for observation in document.inline_xbrl_facts:
        amount = validated_observation(observation, cik=cik, concepts=INLINE_CONCEPTS, taxonomies=TAXONOMIES,
                                       currencies="*")
        taxonomy = _taxonomy(observation["concept_namespace"])
        if amount is None or taxonomy is None or observation["end"] > document.published_at:
            continue
        proof = {**observation, "content_hash": document.content_hash, "document_url": document.final_url,
                 "filed": document.published_at, "form": document.document_type, "accession": accession}
        records.append(SecFactRecord(
            cik=str(int(cik)), taxonomy=taxonomy, concept=observation["concept"], label=observation["concept"],
            unit=observation["unit"], value=amount, start=observation["start"], end=observation["end"],
            filed=document.published_at, form=document.document_type, accession=accession,
            filing_url=document.final_url, inline_binding=proof))
    return records


def filing_comparisons(document, ticker: str, cik: str):
    """(evidence, withheld) from the filing's own facts."""
    records = records_from_document(document, cik)
    return ar.build_comparisons(records, ticker=ticker, cik=cik) if records else ([], [])


def extra_items(document, ticker: str, cik: str):
    """Evidence from the 20-F already fetched: its comparisons and management's stated explanations."""
    from .current_period_explanation import extract_annual_foreign_explanation
    comparisons, withheld = filing_comparisons(document, ticker, cik)
    explanations = extract_annual_foreign_explanation(document, comparisons, ticker=ticker, cik=cik) if comparisons else []
    return comparisons, explanations, withheld


# --------------------------------------------------------------------------------------------------
# Request scratch: the Company Facts response the existing request already holds, for the cross-check
# --------------------------------------------------------------------------------------------------

class Scratch:
    """One request's view of the Company Facts response (set by the existing fetch, read after collection)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.company_facts: Optional[dict] = None

    def set(self, data):
        with self._lock:
            if isinstance(data, dict) and self.company_facts is None:
                self.company_facts = data


_scratch: ContextVar[Optional[Scratch]] = ContextVar("annual_filing_scratch", default=None)


def bind_scratch(fn, scratch: Optional[Scratch]):
    """Run ``fn`` with ``scratch`` active; worker threads do not inherit contextvars."""
    if scratch is None:
        return fn

    def _bound(*args, **kwargs):
        token = _scratch.set(scratch)
        try:
            return fn(*args, **kwargs)
        finally:
            _scratch.reset(token)

    return _bound


def note_company_facts(data) -> None:
    scratch = _scratch.get()
    if scratch is not None:
        try:
            scratch.set(data)
        except Exception:  # pragma: no cover - defensive
            pass


# --------------------------------------------------------------------------------------------------
# Reconciliation with Company Facts
# --------------------------------------------------------------------------------------------------

def metric_name(item) -> Optional[str]:
    """The core measure an as-reported or US-GAAP comparison item is about, or None."""
    claims = getattr(item, "verified_claims", None) or []
    if len(claims) != 2 or not isinstance(claims[0], dict):
        return None
    taxonomy, _, concept = str(claims[0].get("metric", "")).partition(":")
    return next((name for name, by in ar.CORE.items() if concept in by.get(taxonomy, ())), None)


def is_filing_item(item) -> bool:
    claims = getattr(item, "verified_claims", None) or []
    return bool(claims) and isinstance(claims[0], dict) and claims[0].get("inline_binding") is not None \
        and claims[0].get("taxonomy") in ar.BASES


def reconcile(ev_results: dict, scratch: Optional[Scratch]) -> list[dict]:
    """Cross-check the 20-F's own comparisons against Company Facts and the existing comparisons.

    In place on ``ev_results``. A filing figure that disagrees with Company Facts for the same concept, unit,
    period and reporting basis is a conflict: the disputed measure is withheld (every comparison for it, and the
    filing's explanations) and the conflict is returned for the answer to state. Otherwise a newer filing period
    replaces an older comparison; an equal period keeps the existing one.
    """
    filing_items = [i for i in ev_results.get("thesis_disclosures", []) if is_filing_item(i)]
    if not filing_items:
        return []
    data = scratch.company_facts if scratch is not None else None
    latest = {}
    if data:
        from ..providers.sec_client import as_reported_records_from_facts
        cik = str(data.get("cik", ""))
        if cik.isdigit():
            for record in as_reported_records_from_facts(data, cik, specs=ar.requested_specs()):
                key = (record.taxonomy, record.concept, record.unit, record.start, record.end)
                if key not in latest or record.filed > latest[key].filed:
                    latest[key] = record
    withheld, drop_filing_context = [], False
    company = list(ev_results.get("sec_metrics", []))
    kept_filing = list(ev_results.get("thesis_disclosures", []))
    for item in filing_items:
        name = metric_name(item)
        conflicts = []
        for claim in item.verified_claims:
            taxonomy, _, concept = claim["metric"].partition(":")
            record = latest.get((taxonomy, concept, claim["unit"], claim["period_start"], claim["period_end"]))
            if record is not None and Decimal(str(record.value)) != Decimal(str(claim["raw_value"])):
                conflicts.append({"concept": concept, "period_end": claim["period_end"], "unit": claim["unit"],
                                  "reporting_basis": claim["reporting_basis"], "filing_value": claim["raw_value"],
                                  "company_facts_value": record.value,
                                  "company_facts_accession": record.accession})
        peers = [c for c in company if metric_name(c) == name]
        if conflicts:
            company = [c for c in company if metric_name(c) != name]
            kept_filing = [i for i in kept_filing if i is not item]
            withheld.append({"metric": name, "reason": "filing_company_facts_conflict", "conflicts": conflicts})
            drop_filing_context = True
            continue
        if peers:
            peer_end = max(p.reporting_period_end or "" for p in peers)
            if (item.reporting_period_end or "") > peer_end:
                company = [c for c in company if metric_name(c) != name]
            else:
                kept_filing = [i for i in kept_filing if i is not item]
    if drop_filing_context:
        kept_filing = [i for i in kept_filing if not getattr(i, "period_explanations", None)]
    ev_results["sec_metrics"] = company
    ev_results["thesis_disclosures"] = kept_filing
    return withheld
