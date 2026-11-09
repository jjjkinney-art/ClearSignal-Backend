"""An evidence outcome record for each part of a research answer (default off).

For every evidence need an answer plans to meet, one record says whether the evidence was
available, unavailable, unsupported, failed or not attempted, and says so without claiming more
than was checked. It adds no source, claim or request: it is derived from signals the request
already produced, plus request-scoped notes that watch (and never change) what the SEC clients
already do.

States
  available      bound evidence was delivered for the need.
  unavailable    the authoritative source was read and shows the evidence is not there. Said only
                 about that source. A failed request, a 404 or an empty reply is never this.
  unsupported    the evidence exists or is listed and this version cannot use it.
  failed         an attempt did not complete (the class is recorded).
  not_attempted  never tried, with the reason.

The whole module is inert unless ``settings.evidence_outcomes_enabled`` is true: no note is taken,
no field is added and no text changes.
"""
from __future__ import annotations

import re
import threading
from contextvars import ContextVar
from typing import Iterable, Optional

NEEDS = ("reported_financials", "change_drivers", "business_description", "risk_disclosures",
         "liquidity_going_concern", "decision_inputs")
_LABELS = {
    "reported_financials": "Reported financials",
    "change_drivers": "Management's stated drivers of change",
    "business_description": "Business description",
    "risk_disclosures": "Company-specific risk disclosures",
    "liquidity_going_concern": "Liquidity and going-concern disclosure",
    "decision_inputs": "Decision inputs",
}
STATES = ("available", "unavailable", "unsupported", "failed", "not_attempted")
REASONS = {
    "available": ("bound",),
    "unavailable": ("registration_only_filing_list", "concept_absent_from_returned_facts"),
    "unsupported": ("ifrs_taxonomy", "non_usd_reporting", "annual_form_not_read", "interim_form_not_read",
                    "no_same_period_pair", "conflicting_evidence", "selection_rules_not_met"),
    "failed": ("facts_retrieval_failed", "filing_list_failed", "filing_too_large", "filing_not_read",
               "time_limit"),
    "not_attempted": ("identity_unresolved", "no_filing_listed", "not_requested", "no_provider",
                      "not_recorded"),
}

# claim_kind -> the need a delivered claim meets
_CLAIM_NEED = {
    "reported_financial_comparison": "reported_financials",
    "sector_financial_comparison": "reported_financials",
    "supplementary_profitability_comparison": "reported_financials",
    "issuer_current_period_explanation": "change_drivers",
    "issuer_business_description": "business_description",
    "issuer_competition_description": "business_description",
    "issuer_disclosed_risk": "risk_disclosures",
    "issuer_going_concern_disclosure": "liquidity_going_concern",
}
# The evidence task that serves each filing-based need, and the forms that task can read.
_NEED_TASK = {"business_description": "thesis_disclosures", "risk_disclosures": "thesis_disclosures",
              "change_drivers": "filing_metrics", "liquidity_going_concern": "filing_metrics"}
_TASK_FORMS = {"thesis_disclosures": {"10-K", "20-F", "10-Q"}, "filing_metrics": {"10-K", "10-Q"}}
_ANNUAL_TYPE = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
_INTERIM_TYPE = {"10-Q", "10-Q/A", "6-K", "6-K/A"}
_FILING_NEEDS = tuple(_NEED_TASK)
_NOT_EVIDENCE = "investment thesis"


# --------------------------------------------------------------------------------------------------
# Notes: what the SEC clients already did, watched and never changed
# --------------------------------------------------------------------------------------------------

class OutcomeNotes:
    """One request's observations. Thread-safe; nothing outlives the request."""

    def __init__(self):
        self._lock = threading.Lock()
        self.facts_requests: list[dict] = []
        self.listed_forms: set[str] = set()
        self.list_failures: list[dict] = []
        self.filing_selected: dict[str, str] = {}
        self.filing_read_failures: dict[str, bool] = {}  # task -> over the size limit
        self.completed: set[str] = set()  # tasks that returned
        self.abandoned: set[str] = set()  # tasks the request stopped waiting for

    def add_facts(self, row: dict):
        with self._lock:
            self.facts_requests.append(row)

    def add_listed(self, forms: Iterable[str]):
        with self._lock:
            self.listed_forms.update(str(form) for form in forms if isinstance(form, str))

    def add_list_failure(self, row: dict):
        with self._lock:
            self.list_failures.append(row)

    def mark_completed(self, task: str):
        with self._lock:
            self.completed.add(task)

    def mark_abandoned(self, tasks: Iterable[str]):
        with self._lock:
            self.abandoned.update(tasks)

    def add_selected(self, task: str, form: str):
        with self._lock:
            self.filing_selected[task] = form

    def add_read_failure(self, task: str, too_large: bool):
        with self._lock:
            self.filing_read_failures[task] = bool(too_large) or self.filing_read_failures.get(task, False)


_notes: ContextVar[Optional[OutcomeNotes]] = ContextVar("evidence_outcome_notes", default=None)


def bind_outcome_notes(fn, notes: Optional[OutcomeNotes]):
    """Run ``fn`` with ``notes`` active; worker threads do not inherit contextvars."""
    if notes is None:
        return fn

    def _bound(*args, **kwargs):
        token = _notes.set(notes)
        try:
            return fn(*args, **kwargs)
        finally:
            _notes.reset(token)

    return _bound


def _safe(action):
    """A note never raises into the code it watches."""
    notes = _notes.get()
    if notes is None:
        return
    try:
        action(notes)
    except Exception:  # pragma: no cover - defensive
        pass


def _failure(exc: BaseException) -> dict:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    return {"error_class": type(exc).__name__, "http_status": status if isinstance(status, int) else None}


def note_facts_failure(cik: str, exc: BaseException):
    _safe(lambda notes: notes.add_facts({"cik": cik, "ok": False, **_failure(exc)}))


def note_facts_rejected(cik: str, reason: str):
    """A response arrived but was not about the requested CIK."""
    _safe(lambda notes: notes.add_facts({"cik": cik, "ok": False, "error_class": reason, "http_status": None}))


def note_facts_received(cik: str, data: dict, concept_units, records) -> None:
    def action(notes):
        facts = data.get("facts") if isinstance(data, dict) else None
        facts = facts if isinstance(facts, dict) else {}
        counts, currencies = {}, {}
        for taxonomy in ("us-gaap", "ifrs-full"):
            concepts = facts.get(taxonomy)
            if not isinstance(concepts, dict):
                continue
            counts[taxonomy] = len(concepts)
            found = set()
            for entry in concepts.values():
                units = entry.get("units") if isinstance(entry, dict) else None
                if isinstance(units, dict):
                    found.update(unit for unit in units if re.fullmatch(r"[A-Z]{3}", str(unit)))
            currencies[taxonomy] = sorted(found)
        gaap = facts.get("us-gaap") if isinstance(facts.get("us-gaap"), dict) else {}
        requested = list(dict.fromkeys(concept for concept, _ in concept_units))
        units = {}
        for concept in requested:
            entry = gaap.get(concept) if isinstance(gaap.get(concept), dict) else {}
            found = entry.get("units") if isinstance(entry.get("units"), dict) else {}
            units[concept] = sorted(u for u in found if re.fullmatch(r"[A-Z]{3}", str(u)))
        notes.add_facts({
            "requested_currencies": units,
            "cik": cik, "ok": True, "taxonomies": counts, "currencies": currencies,
            "requested": requested, "present": [c for c in requested if c in gaap],
            "with_records": sorted({getattr(r, "concept", "") for r in records} & set(requested)),
        })
    _safe(action)


def note_filings_listed(forms) -> None:
    _safe(lambda notes: notes.add_listed(forms))


def note_filing_list_failure(exc: BaseException):
    _safe(lambda notes: notes.add_list_failure(_failure(exc)))


def note_filing_selected(task: str, form: str):
    _safe(lambda notes: notes.add_selected(task, form))


def note_filing_read_failure(task: str, too_large: bool):
    _safe(lambda notes: notes.add_read_failure(task, too_large))


# --------------------------------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------------------------------

def _record(need, state, reason, *, tried, source_family, user_text, detail=None, reference_ids=(),
            as_of=None, freshness=None, missing_parts=None):
    assert reason in REASONS[state], (state, reason)
    row = {"need": need, "state": state, "reason": reason, "source_family": source_family, "tried": tried,
           "detail": detail or {}, "reference_ids": list(reference_ids), "as_of": as_of,
           "freshness": freshness, "missing_parts": list(missing_parts or []), "user_text": user_text}
    return row


def _kind(source_answer: dict) -> str:
    if source_answer.get("missing_threshold_inputs") is not None or source_answer.get("monitoring_benchmarks") is not None:
        return "threshold"
    if "business_context_coverage" in source_answer:
        return "thesis"
    # A broad question the gate could not answer still asked for the whole thesis.
    if any(str(part).startswith(_NOT_EVIDENCE) for part in source_answer.get("unanswered_parts") or []):
        return "thesis"
    return "metric"


def _reference(references, reference_id):
    return next((ref for ref in references or [] if ref.get("id") == reference_id), None)


def _claims_for(source_answer, need):
    return [row for row in source_answer.get("claims") or []
            if isinstance(row, dict) and _CLAIM_NEED.get(row.get("claim_kind", "reported_financial_comparison")) == need]


def _freshness(refs):
    states = {ref.get("freshness_status") for ref in refs if ref}
    if not refs or not all(refs):
        return "unknown"
    if "stale" in states:
        return "stale"
    return "current" if states == {"current"} else "unknown"


def _as_of(source_answer, refs):
    period = source_answer.get("common_reporting_period")
    if isinstance(period, dict):
        for key in ("end", "period_end", "as_of"):
            if isinstance(period.get(key), str):
                return period[key]
    ends = sorted(str(ref.get("reporting_period_end")) for ref in refs if ref and ref.get("reporting_period_end"))
    return ends[-1] if ends else None


def _text_fact_failure(failure):
    status = failure.get("http_status")
    how = f"HTTP {status}" if status else failure.get("error_class", "an error")
    return (f"SEC company facts could not be retrieved for this answer ({how}). That is a failed request, "
            "not evidence that no data exists; trying again may give a fuller answer.")


def _financial_state(source_answer, notes, references):
    facts = notes.facts_requests if notes else []
    ok = [row for row in facts if row.get("ok")]
    analysis = source_answer.get("financial_analysis") or {}
    not_applicable = source_answer.get("evidence_not_applicable") or []
    gaps = source_answer.get("evidence_gaps") or []
    if not_applicable:
        return _record("reported_financials", "unavailable", "registration_only_filing_list", tried=True,
                       source_family="sec_filing_list",
                       detail={"company_facts_queried": False},
                       user_text="SEC's filing list for this registrant shows only registration forms and no XBRL "
                                 "filing. This rests on the filing list alone; SEC's company-facts service was not "
                                 "queried, so nothing here states what it holds.")
    if facts and not ok:
        failure = facts[-1]
        return _record("reported_financials", "failed", "facts_retrieval_failed", tried=True,
                       source_family="sec_company_facts",
                       detail={"error_class": failure.get("error_class"), "http_status": failure.get("http_status")},
                       user_text=_text_fact_failure(failure))
    for gap in gaps:
        if gap.get("task") == "sec_metrics":
            return _record("reported_financials", "failed",
                           "time_limit" if gap.get("reason") == "time_limit" else "facts_retrieval_failed",
                           tried=True, source_family="sec_company_facts", detail={"gap_reason": gap.get("reason")},
                           user_text="SEC company facts could not be read within this request, so reported "
                                     "financials are missing. Trying again may give a fuller answer.")
    if notes and "sec_metrics" in notes.abandoned and not ok:
        return _record("reported_financials", "failed", "time_limit", tried=True, source_family="sec_company_facts",
                       user_text="SEC company facts could not be read within this request, so reported "
                                 "financials are missing. Trying again may give a fuller answer.")
    taxonomies = ok[-1].get("taxonomies", {}) if ok else {}
    currencies = ok[-1].get("currencies", {}) if ok else {}
    ifrs = (analysis.get("reason") == "ifrs_taxonomy_not_supported"
            or taxonomies.get("ifrs-full", 0) > taxonomies.get("us-gaap", 0))
    if ifrs:
        return _record("reported_financials", "unsupported", "ifrs_taxonomy", tried=True,
                       source_family="sec_company_facts",
                       detail={"taxonomies": taxonomies or analysis.get("observed_taxonomies"),
                               "currencies": currencies.get("ifrs-full", [])},
                       user_text="The SEC structured data for this issuer is tagged mainly under the IFRS taxonomy, "
                                 "which this version does not read. The data exists; no comparison was built from it.")
    shown = ok[-1].get("requested_currencies", {}) if ok else {}
    gaap_currencies = sorted({c for concept in ok[-1].get("present", []) for c in shown.get(concept, [])}) if ok else []
    if ok and gaap_currencies and "USD" not in gaap_currencies:
        return _record("reported_financials", "unsupported", "non_usd_reporting", tried=True,
                       source_family="sec_company_facts", detail={"currencies": gaap_currencies},
                       user_text=f"The SEC structured data for this issuer is reported in {', '.join(gaap_currencies)}, "
                                 "not US dollars, which this version does not compare. The data exists; no comparison "
                                 "was built from it.")
    if ok and not any(row.get("present") for row in ok):
        return _record("reported_financials", "unavailable", "concept_absent_from_returned_facts", tried=True,
                       source_family="sec_company_facts", detail={"requested": ok[-1].get("requested", [])},
                       user_text="None of the requested measures appears in the company-facts data returned by SEC "
                                 "for this issuer. This describes that response only; it does not establish that the "
                                 "issuer never reported the measure.")
    if ok:
        return _record("reported_financials", "unsupported", "no_same_period_pair", tried=True,
                       source_family="sec_company_facts", detail={"present": ok[-1].get("present", [])},
                       user_text="Company-facts data was retrieved, but no comparison of a current and a prior-period "
                                 "figure on the same basis could be built from it.")
    if analysis.get("reason") == "comparisons_unavailable":
        return _record("reported_financials", "unsupported", "no_same_period_pair", tried=True,
                       source_family="sec_company_facts", detail={},
                       user_text="A verified comparison of current and prior-period figures could not be built from "
                                 "the SEC data retrieved.")
    return _record("reported_financials", "not_attempted", "not_recorded", tried=False,
                   source_family="sec_company_facts", detail={},
                   user_text="This run recorded no attempt to read SEC company facts, so reported financials are unknown.")


def _filing_state(need, source_answer, notes):
    task = _NEED_TASK[need]
    family = "sec_filing"
    not_applicable = source_answer.get("evidence_not_applicable") or []
    if not_applicable:
        return _record(need, "unavailable", "registration_only_filing_list", tried=True, source_family="sec_filing_list",
                       user_text="SEC's filing list for this registrant shows only registration forms; no annual or "
                                 "periodic report is listed. This rests on the filing list alone.")
    gaps = [g for g in source_answer.get("evidence_gaps") or [] if g.get("task") in {task, "sec_submissions"}]
    for gap in gaps:
        if gap.get("task") == "sec_submissions":
            return _record(need, "failed", "filing_list_failed", tried=False, source_family="sec_filing_list",
                           user_text="SEC's filing list could not be retrieved, so no filing was read for this part. "
                                     "Trying again may give a fuller answer.")
        reason = {"too_large": "filing_too_large", "time_limit": "time_limit"}.get(gap.get("reason"), "filing_not_read")
        text = {"filing_too_large": "The filing is larger than the size limit, so it was not read; retrying will not help.",
                "time_limit": "The filing could not be read within the time limit for this answer.",
                "filing_not_read": "The filing could not be read for this answer."}[reason]
        return _record(need, "failed", reason, tried=True, source_family=family,
                       detail={"form": (notes.filing_selected.get(task) if notes else None)},
                       user_text=text + " What it would have added is missing.")
    if notes:
        if task in notes.filing_read_failures:
            reason = "filing_too_large" if notes.filing_read_failures[task] else "filing_not_read"
            return _record(need, "failed", reason, tried=True, source_family=family,
                           user_text="The filing could not be read for this answer; what it would have added is missing.")
        if notes.list_failures and not notes.listed_forms:
            failure = notes.list_failures[-1]
            return _record(need, "failed", "filing_list_failed", tried=False, source_family="sec_filing_list",
                           detail=dict(failure),
                           user_text="SEC's filing list could not be retrieved, so no filing was read for this part. "
                                     "That is a failed request, not evidence that no filing exists.")
        if task in notes.filing_selected and task in notes.abandoned:
            return _record(need, "failed", "time_limit", tried=True, source_family=family,
                           detail={"form": notes.filing_selected[task]},
                           user_text="The filing could not be read within the time limit for this answer. "
                                     "What it would have added is missing.")
        if task in notes.filing_selected and task not in notes.completed:
            return _record(need, "failed", "filing_not_read", tried=True, source_family=family,
                           detail={"form": notes.filing_selected[task]},
                           user_text="The filing was chosen but its reading did not finish for this answer. "
                                     "What it would have added is missing.")
        if task in notes.filing_selected:
            return _record(need, "unsupported", "selection_rules_not_met", tried=True, source_family=family,
                           detail={"form": notes.filing_selected[task]},
                           user_text=f"A Form {notes.filing_selected[task]} was read and no passage met this version's "
                                     "selection rules. This does not establish that the filing has no such disclosure.")
        listed = notes.listed_forms
        if listed and not (listed & _TASK_FORMS[task]):
            if listed & _ANNUAL_TYPE:
                return _record(need, "unsupported", "annual_form_not_read", tried=False, source_family=family,
                               detail={"listed_forms": sorted(listed)},
                               user_text="The issuer's recent filings include an annual report on a form this version "
                                         "does not read. No filing was read for this part.")
            if listed & _INTERIM_TYPE:
                return _record(need, "unsupported", "interim_form_not_read", tried=False, source_family=family,
                               detail={"listed_forms": sorted(listed)},
                               user_text="The issuer's recent filings include periodic reports on a form this version "
                                         "does not read. No filing was read for this part.")
            return _record(need, "not_attempted", "no_filing_listed", tried=False, source_family="sec_filing_list",
                           detail={"listed_forms": sorted(listed)},
                           user_text="No annual or periodic report this version reads is in the recent filing list "
                                     "(older filing pages were not read). No filing was read for this part.")
    return _record(need, "not_attempted", "not_recorded", tried=False, source_family=family,
                   user_text="This run recorded no filing read for this part, so what the filings say about it is unknown.")


def _decision_inputs(source_answer, financial):
    if source_answer.get("monitoring_benchmarks") is not None:
        return _record("decision_inputs", "not_attempted", "no_provider", tried=False, source_family="none",
                       user_text="Valuation boundaries, expected returns and earnings impact need price, estimate or "
                                 "scenario inputs that this version does not retrieve. Only historical baselines were built.")
    return _record("decision_inputs", financial["state"] if financial["state"] != "available" else "unsupported",
                   financial["reason"] if financial["state"] != "available" else "no_same_period_pair",
                   tried=financial["tried"], source_family=financial["source_family"], detail=dict(financial["detail"]),
                   user_text="No monitoring baseline or decision threshold could be built. "
                             + ("" if financial["state"] == "available" else financial["user_text"]))


def _missing_parts(source_answer, notes):
    """Revenue is the usual gap when operating income or profit was delivered without it."""
    if not notes:
        return []
    ok = [row for row in notes.facts_requests if row.get("ok")]
    if not ok:
        return []
    last = ok[-1]
    revenue_concepts = [c for c in last.get("requested", []) if re.search(r"revenue|sales", c, re.I)]
    if not revenue_concepts:
        return []
    if any(re.search(r"revenue|net sales", str(row.get("claim", "")), re.I) for row in source_answer.get("claims") or []):
        return []
    if not any(c in last.get("present", []) for c in revenue_concepts):
        return [{"part": "revenue", "state": "unavailable", "reason": "concept_absent_from_returned_facts"}]
    if not any(c in last.get("with_records", []) for c in revenue_concepts):
        return [{"part": "revenue", "state": "unsupported", "reason": "no_same_period_pair"}]
    return []


def build_evidence_outcomes(source_answer: dict, *, notes: Optional[OutcomeNotes] = None, references=(),
                            integrity: Optional[dict] = None, identity_resolved: bool = True) -> list[dict]:
    """One record per applicable evidence need. Pure: reads only its arguments."""
    kind = _kind(source_answer)
    needs = (("reported_financials", "change_drivers", "decision_inputs") if kind == "threshold"
             else ("reported_financials",) if kind == "metric"
             else tuple(n for n in NEEDS if n != "decision_inputs"))
    if source_answer.get("status") == "unresolved_company_identity":
        identity_resolved = False
    if not identity_resolved:
        needs = tuple(n for n in NEEDS if n != "decision_inputs")
        return [_record(need, "not_attempted", "identity_unresolved", tried=False, source_family="none",
                        user_text="The company could not be identified, so no evidence was requested.")
                for need in needs]
    blocked = [ref for ref in references or []
               if ref.get("freshness_status") == "conflicting"
               and ref.get("id") in ((integrity or {}).get("admission", {}).get("blocked_reference_ids") or [])]
    records = []
    financial = None
    for need in needs:
        if need == "decision_inputs":
            financial = financial or _financial_state(source_answer, notes, references)
            records.append(_decision_inputs(source_answer, financial))
            continue
        claims = _claims_for(source_answer, need)
        if claims:
            ids = list(dict.fromkeys(row["reference_id"] for row in claims if row.get("reference_id")))
            refs = [_reference(references, i) for i in ids]
            records.append(_record(need, "available", "bound", tried=True, source_family="sec_filing" if need != "reported_financials" else "sec_company_facts",
                                   reference_ids=ids, as_of=_as_of(source_answer, refs), freshness=_freshness(refs),
                                   missing_parts=_missing_parts(source_answer, notes) if need == "reported_financials" else [],
                                   user_text="Bound to the cited evidence."))
            if need == "reported_financials":
                financial = records[-1]
            continue
        if need == "reported_financials":
            if blocked:
                row = _record(need, "unsupported", "conflicting_evidence", tried=True, source_family="sec_company_facts",
                              detail={"blocked_reference_ids": [ref["id"] for ref in blocked]},
                              user_text="Retrieved evidence for this part conflicts with other retrieved evidence, so no "
                                        "figure is stated as fact. Evidence admission blocked the conflicting items.")
            else:
                row = _financial_state(source_answer, notes, references)
            financial = row
            records.append(row)
            continue
        records.append(_filing_state(need, source_answer, notes))
    return records


# --------------------------------------------------------------------------------------------------
# Rendering and application
# --------------------------------------------------------------------------------------------------

HEADER = "What remains unknown"
def _rewrites(failed: bool):
    """The sentences that say a disclosure 'qualified' or not, restated for a filing that was not read."""
    how = "could not be read" if failed else "was not read"
    return (
    ("No source-bound operating-risk disclosure qualified for this broad question. ", ""),
    ("No source-bound operating-risk disclosure qualified for the requested company and topic. The retrieved sources "
     "and consolidated metrics do not establish that risk, its likelihood, or its effect on the thesis. Review the "
     "linked primary documents; this part of the question remains unverified.",
     f"The filing {how} for this part, so no operating-risk disclosure was examined; this part of the question "
     "remains unverified."),
    ("No source-bound operating-risk disclosure qualified for the requested company and topic; risk likelihood, "
     "financial effects, and thesis implications remain unverified.",
     f"The filing {how} for the operating-risk part, so no disclosure was examined; risk likelihood, financial "
     "effects, and thesis implications remain unverified."),
    )


_PART_TEXT = {
    "concept_absent_from_returned_facts": "the requested measures do not appear in the company-facts data returned "
                                           "for this issuer (this describes that response only)",
    "no_same_period_pair": "the measure was present but no current and prior-period pair on the same basis could be built",
}


def render_unknown_block(records: list[dict]) -> str:
    lines = [f"- {_LABELS[row['need']]}: {row['user_text']}" for row in records if row["state"] != "available"]
    for row in records:
        for part in row["state"] == "available" and row["missing_parts"] or []:
            lines.append(f"- {_LABELS[row['need']]}, also missing: {part['part']}: "
                         f"{_PART_TEXT.get(part['reason'], part['reason'])}.")
    return HEADER + "\n" + "\n".join(lines) if lines else ""


def _correct_unread_risk_text(thesis, source_answer, records):
    """When no filing was read for the risk part, the answer must not say a disclosure was found wanting."""
    risk = next((row for row in records if row["need"] == "risk_disclosures"), None)
    # Only a filing that was read to the end and yielded nothing may keep "qualified" wording.
    if not risk or risk["state"] == "available" or risk["reason"] == "selection_rules_not_met":
        return source_answer
    for field in ("direct_answer", "conclusion"):
        text = getattr(thesis, field, None)
        if isinstance(text, str):
            for old, new in _rewrites(risk["state"] == "failed"):
                text = text.replace(old, new)
            setattr(thesis, field, text)
    reason = source_answer.get("reason")
    if reason == "No relevant source-bound operating-risk disclosure qualified.":
        source_answer = {**source_answer, "reason": "No filing was read to the end for the operating-risk part of the question."}
    return source_answer


def apply_evidence_outcomes(thesis: object, source_answer: Optional[dict], *, notes: Optional[OutcomeNotes] = None,
                            references=(), integrity: Optional[dict] = None) -> Optional[dict]:
    """Add the outcome record and its "What remains unknown" block. Inert when the flag is off."""
    from ..config import settings
    if getattr(settings, "evidence_outcomes_enabled", False) is not True or source_answer is None:
        return source_answer
    records = build_evidence_outcomes(source_answer, notes=notes, references=references, integrity=integrity)
    source_answer = _correct_unread_risk_text(thesis, source_answer, records)
    block = render_unknown_block(records)
    if block:
        for field in ("direct_answer", "conclusion"):
            text = getattr(thesis, field, None)
            if isinstance(text, str) and HEADER + "\n" not in text:
                setattr(thesis, field, f"{text}\n\n{block}" if text else block)
    return {**source_answer, "evidence_outcomes": records}


_PART_NEED = (
    (r"valuation|expected return|threshold|boundar|earnings impact|breakpoint", "decision_inputs"),
    (r"financial performance|reported comparison|operating income|net income|revenue|profit|margin|cash flow|"
     r"deposit|loan|monitoring baseline|comparison", "reported_financials"),
    (r"going.concern|liquidity", "liquidity_going_concern"),
    (r"driver|cause", "change_drivers"),
    (r"risk|invalidat", "risk_disclosures"),
    (r"business|competitive|competition|segment", "business_description"),
)


def part_need(part: str) -> Optional[str]:
    """The need an ``unanswered_parts`` entry belongs to. Interpretation is not an evidence need."""
    text = part.lower()
    if text.startswith(_NOT_EVIDENCE):
        return None
    if text.startswith("evidence from"):
        return "filing"
    for pattern, need in _PART_NEED:
        if re.search(pattern, text):
            return need
    return None


def explain_part(part: str, records: list[dict]) -> Optional[str]:
    """The missing-evidence text for an unanswered part, or None when it has no evidence need."""
    need = part_need(part)
    if need is None:
        return None
    if need == "filing":
        row = next((r for r in records if r["need"] in _FILING_NEEDS and r["state"] != "available"), None)
    else:
        row = next((r for r in records if r["need"] == need and r["state"] != "available"), None)
    return row["user_text"] if row else None


def identity_gap_source_answer(source_answer: dict) -> dict:
    """The unresolved-identity answer, with every need recorded as never attempted (flag on only)."""
    from ..config import settings
    if getattr(settings, "evidence_outcomes_enabled", False) is not True:
        return source_answer
    return {**source_answer, "evidence_outcomes": build_evidence_outcomes(source_answer, identity_resolved=False)}
