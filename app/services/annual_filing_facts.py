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

def later_reports_enabled() -> bool:
    """The later-reports notice follows the as-reported flag: it qualifies the annual answers that flag adds."""
    from ..config import settings
    return getattr(settings, "as_reported_financials_enabled", False) is True


class Scratch:
    """One request's view of responses it already fetched (set by the existing fetches, read after collection)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.company_facts: Optional[dict] = None
        self.listings: dict[str, list[dict]] = {}
        self.withheld: list[dict] = []

    def set(self, data):
        with self._lock:
            if isinstance(data, dict) and self.company_facts is None:
                self.company_facts = data

    def set_withheld(self, rows):
        with self._lock:
            if isinstance(rows, list) and not self.withheld:
                self.withheld = [dict(r) for r in rows if isinstance(r, dict)]

    def set_listing(self, cik: str, rows: list[dict]):
        with self._lock:
            self.listings.setdefault(cik, rows)


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


LISTED_FORMS = {"6-K", "6-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def note_withheld(rows) -> None:
    """Keep the as-reported builder's own withheld reasons for the answer (request-scoped; no request)."""
    scratch = _scratch.get()
    if scratch is not None:
        try:
            scratch.set_withheld(rows)
        except Exception:  # pragma: no cover - defensive
            pass


def note_filing_list(cik, recent) -> None:
    """Keep the filing-list rows the request already fetched (metadata only; nothing is read or requested)."""
    scratch = _scratch.get()
    if scratch is None:
        return
    try:
        columns = [recent.get(k) or [] for k in ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument")]
        rows = [{"form": f, "filed": d, "report": r, "accession": a, "document": p}
                for f, d, r, a, p in zip(*columns) if f in LISTED_FORMS]
        scratch.set_listing(str(int(cik)), rows)
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
                proof = claim["inline_binding"]
                conflicts.append({"concept": concept, "period_start": claim["period_start"],
                                  "period_end": claim["period_end"], "unit": claim["unit"],
                                  "reporting_basis": claim["reporting_basis"], "filing_value": claim["raw_value"],
                                  "filing_form": proof["form"], "filing_filed": proof["filed"],
                                  "filing_accession": proof["accession"], "filing_fact_id": proof["fact_id"],
                                  "company_facts_value": record.value, "company_facts_form": record.form,
                                  "company_facts_filed": record.filed, "company_facts_accession": record.accession})
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


# --------------------------------------------------------------------------------------------------
# The warning the answer carries when a comparison is withheld because the sources disagree
# --------------------------------------------------------------------------------------------------

NOTICE_HEADER = "Sources disagree"


def _amount(value, unit: str) -> str:
    exact = format(Decimal(str(value)), ",f")
    if "." in exact:
        exact = exact.rstrip("0").rstrip(".")
    return f"{exact} {unit}"


def conflict_notice(conflicts: list[dict]) -> str:
    """Plain wording for each disputed figure: where each value comes from, and that neither is accepted.

    The values appear only here. They are never put in a claim, a comparison or a calculation.
    """
    lines = []
    for row in conflicts:
        for c in row["conflicts"]:
            lines.append(
                f"- {row['metric']} for the period {c['period_start']} to {c['period_end']} "
                f"({c['reporting_basis']}, {c['unit']}): the {c['filing_form']} filed {c['filing_filed']} "
                f"(accession {c['filing_accession']}, inline fact {c['filing_fact_id']}) reports "
                f"{_amount(c['filing_value'], c['unit'])}; SEC Company Facts ({c['company_facts_form']} filed "
                f"{c['company_facts_filed']}, accession {c['company_facts_accession']}) reports "
                f"{_amount(c['company_facts_value'], c['unit'])}.")
    measures = ", ".join(dict.fromkeys(row["metric"] for row in conflicts))
    return (f"{NOTICE_HEADER}: the 20-F's own figures and SEC Company Facts give different values for the same period "
            f"and reporting basis.\n" + "\n".join(lines) + f"\nNeither value is accepted or used. No comparison for "
            f"{measures} is shown, and nothing is calculated from either figure. The retained data does not say "
            "which is correct, or whether one is a restatement.")


def apply_conflict_notice(thesis, source_answer, conflicts):
    """State the disagreement in the answer itself (independent of the outcome-record flag); idempotent."""
    if not conflicts or source_answer is None:
        return source_answer
    notice = conflict_notice(conflicts)
    for field in ("direct_answer", "conclusion"):
        text = getattr(thesis, field, None)
        if isinstance(text, str) and NOTICE_HEADER + ":" not in text:
            setattr(thesis, field, f"{notice}\n\n{text}" if text else notice)
    measures = list(dict.fromkeys(row["metric"] for row in conflicts))
    held = [f"{name} (withheld: the filing and SEC Company Facts disagree)" for name in measures]
    parts = [p for p in source_answer.get("unanswered_parts") or [] if p not in held]
    return {**source_answer, "status": "partial" if source_answer.get("status") == "attributed" else source_answer.get("status"),
            "unanswered_parts": [*parts, *held]}


# --------------------------------------------------------------------------------------------------
# The warning the answer carries when the issuer has filed reports for later periods that were not read
# --------------------------------------------------------------------------------------------------

LATER_HEADER = "Later filings not read"
FOREIGN_ANNUAL = {"20-F", "20-F/A", "40-F", "40-F/A"}
INTERIM_FORMS = {"6-K", "6-K/A"}
_EDGAR_CIK = re.compile(r"/edgar/data/(\d+)/")


def _month_end(value: date) -> bool:
    return date.fromordinal(value.toordinal() + 1).day == 1


def later_reports(evidence, scratch: Optional[Scratch]) -> list[dict]:
    """Later filings SEC lists for an issuer whose answer rests on an annual foreign filing (metadata only).

    Uses only the filing list the request already fetched. Two kinds of row are reported, never merged:

    * dated: the report date is a month end a whole number of quarters after the latest annual period in the
      answer and before its own filing date (a report date on or after the filing date does not state a completed
      period);
    * undated: any other 6-K filed after the last dated one (or, if none, after the annual filing the answer
      cites). SEC's list does not say which period, if any, these cover.

    A report date is filer-entered metadata; nothing here says a filing contains results.
    """
    if scratch is None or not scratch.listings:
        return []
    ends: dict[str, str] = {}
    annual_filed: dict[str, str] = {}
    for item in evidence or []:
        if (getattr(item, "source_type", None) != "regulatory_filing" or getattr(item, "document_type", None) not in FOREIGN_ANNUAL
                or not getattr(item, "verified_claims", None) or not getattr(item, "reporting_period_end", None)
                or getattr(item, "freshness_status", None) == "stale"):
            continue
        match = _EDGAR_CIK.search(getattr(item, "url", None) or "")
        if match:
            cik = str(int(match.group(1)))
            ends[cik] = max(ends.get(cik, ""), item.reporting_period_end)
            filed_at = str(getattr(item, "filed_at", None) or getattr(item, "timestamp", None) or "")[:10]
            annual_filed[cik] = max(annual_filed.get(cik, ""), filed_at)
    found = []
    for cik, end in ends.items():
        try:
            annual_end = date.fromisoformat(end)
        except ValueError:
            continue
        dated, parsed = [], []
        for row in scratch.listings.get(cik, []):
            try:
                report, filed = date.fromisoformat(row["report"]), date.fromisoformat(row["filed"])
            except (TypeError, ValueError):
                continue
            parsed.append(row)
            months = (report.year - annual_end.year) * 12 + report.month - annual_end.month
            if report > annual_end and report < filed and _month_end(report) and months % 3 == 0:
                dated.append(row)
        periods = sorted({r["report"] for r in dated})
        latest = [r for r in dated if r["report"] == periods[-1]] if periods else []
        cutoff = max([r["filed"] for r in latest] or [annual_filed.get(cik) or end])
        undated = sorted((r for r in parsed if r["form"] in INTERIM_FORMS and r not in dated and r["filed"] > cutoff),
                         key=lambda r: r["filed"], reverse=True)
        if periods or undated:
            found.append({"cik": cik, "annual_period_end": end, "periods": periods, "latest": latest,
                          "undated_after": cutoff, "undated": undated})
    return found


def _and(values: list[str]) -> str:
    return values[0] if len(values) == 1 else ", ".join(values[:-1]) + " and " + values[-1]


def _filing(r: dict) -> str:
    return f"Form {r['form']} filed {r['filed']} (accession {r['accession']}, document {r['document']})"


def later_reports_notice(found: list[dict]) -> str:
    lines = []
    for row in found:
        line = f"The financial figures in this answer cover the fiscal year ended {row['annual_period_end']}."
        if row["periods"]:
            n = len(row["latest"])
            line += (f" SEC's filing list for this issuer shows filings with later report dates: {_and(row['periods'])}."
                     f" The filing{'s' if n > 1 else ''} dated {row['periods'][-1]}: {'; '.join(_filing(r) for r in row['latest'])}.")
        if row["undated"]:
            n = len(row["undated"])
            lead = "It also lists" if row["periods"] else "SEC's filing list for this issuer shows"
            line += (f" {lead} "
                     f"{n} Form 6-K filing{'s' if n > 1 else ''} made after {row['undated_after']} that "
                     f"{'do' if n > 1 else 'does'} not give a later report date, so the period covered, if any, is not "
                     f"stated (most recent: {_filing(row['undated'][0])}).")
        lines.append(line)
    end = _and(sorted({row["annual_period_end"] for row in found}))
    return (f"{LATER_HEADER}: " + " ".join(lines) + f" None of these filings was read, so nothing after {end} is "
            "reflected and these figures may be out of date. This answer does not know what those filings contain.")


def unanswered_part(row: dict) -> str:
    return f"anything after {row['annual_period_end']} (later SEC filings listed but not read)"


def apply_later_reports_notice(thesis, source_answer, found):
    """State that later filings exist and were not read; idempotent. Their contents are never claimed."""
    if not found or source_answer is None:
        return source_answer
    notice = later_reports_notice(found)
    for field in ("direct_answer", "conclusion"):
        text = getattr(thesis, field, None)
        if isinstance(text, str) and LATER_HEADER + ":" not in text:
            setattr(thesis, field, f"{notice}\n\n{text}" if text else notice)
    held = [unanswered_part(row) for row in found]
    parts = [p for p in source_answer.get("unanswered_parts") or [] if p not in held]
    return {**source_answer, "status": "partial" if source_answer.get("status") == "attributed" else source_answer.get("status"),
            "unanswered_parts": [*parts, *held]}
