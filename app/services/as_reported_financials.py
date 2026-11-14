"""Annual comparisons from SEC company facts reported under IFRS or in a currency other than USD/EUR.

Default off (``settings.as_reported_financials_enabled``). It runs only when the existing US-GAAP
USD/EUR path produced no comparison, and it uses company facts only: **the Company Facts response that
path already fetched for this request** (no additional request, no other source). It is not used for
decision-threshold questions.

Rules, each one withholding (with a stated reason) rather than guessing:
* Amounts keep the unit the filing reported. **Nothing is converted**, and a figure in one currency is never
  compared with a figure in another, or across taxonomies.
* One reporting basis per issuer: the (taxonomy, currency) whose latest annual balance sheet is most recent.
  A tie between bases withholds everything (``ambiguous_basis_or_currency``).
* Each comparison is two annual facts of the same concept, unit and taxonomy, one year apart on the same duration,
  each unambiguous after resolving duplicates. Interim (6-K, 10-Q) facts are not compared.
* Concept aliases are tried separately, never joined, exactly as the US-GAAP path does.
* A zero or non-positive amount is not turned into a percentage; the comparison is withheld.

Claims carry additive ``taxonomy``, ``currency`` and ``reporting_basis`` metadata. The foundation rebuilds
every comparison from its two bound facts before showing it.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from ..integrity.provenance import ClaimDocumentReference, Provenance, QuantitativeClaim
from ..integrity.sec_metric_evidence import (_duration, _latest_unambiguous_fact, _scaled, _value)
from ..integrity.sec_metric_labels import metric_label
from ..providers.sec_client import AS_REPORTED_FORMS, SecFactRecord
from ..schemas import RetrievedEvidence

ANCHOR = "Assets"
MAX_STALENESS_DAYS = 550
ANNUAL_PREFIXES = ("10-K", "20-F", "40-F")
BASES = {"us-gaap": "US-GAAP", "ifrs-full": "IFRS"}
CORE = {
    "revenue": {
        "ifrs-full": ("Revenue", "RevenueFromContractsWithCustomers"),
        "us-gaap": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenuesNetOfInterestExpense",
                    "RevenueFromContractWithCustomerIncludingAssessedTax"),
    },
    "operating income": {"ifrs-full": ("ProfitLossFromOperatingActivities",), "us-gaap": ("OperatingIncomeLoss",)},
    "net income": {"ifrs-full": ("ProfitLoss",), "us-gaap": ("NetIncomeLoss", "ProfitLoss")},
    "operating cash flow": {"ifrs-full": ("CashFlowsFromUsedInOperatingActivities",),
                            "us-gaap": ("NetCashProvidedByUsedInOperatingActivities",)},
}
_ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
_REFERENCE = re.compile(r"sec:(\d+):(\d{10}-\d{2}-\d{6}):(us-gaap|ifrs-full):([A-Za-z0-9]+)\Z")
SOURCE = "SEC EDGAR — structured XBRL fact"


# The concept that states an issuer's total revenues, by taxonomy.
TOTAL_REVENUE = {"us-gaap": "Revenues", "ifrs-full": "Revenue"}


def latest_revenue(candidates):
    """The revenue comparison to show: the latest current period; when several revenue concepts cover that
    period and disagree in value, the issuer's total revenues, because a narrower line (such as revenue from
    contracts with customers) does not match total operating income or profit. Equal values keep the configured
    order. Values are never joined across concepts.
    """
    latest = max(candidate.reporting_period_end or "" for candidate in candidates)
    tied = [candidate for candidate in candidates if (candidate.reporting_period_end or "") == latest]
    values = {tuple(claim["raw_value"] for claim in candidate.verified_claims) for candidate in tied}
    if len(tied) > 1 and len(values) > 1:
        totals = [candidate for candidate in tied
                  if candidate.verified_claims[0]["metric"] in {f"{tax}:{concept}" for tax, concept in TOTAL_REVENUE.items()}]
        if len(totals) == 1:
            return totals[0]
    return tied[0]


def requested_specs() -> tuple[tuple[str, str], ...]:
    """(taxonomy, concept) pairs the as-reported path reads, including the balance-sheet anchor."""
    specs = [(tax, concept) for by_tax in CORE.values() for tax, concepts in by_tax.items() for concept in concepts]
    specs += [(tax, ANCHOR) for tax in BASES]
    return tuple(dict.fromkeys(specs))


# --------------------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------------------

def _display(value, unit: str) -> str:
    """The exact unscaled amount in the filing's own unit."""
    exact = format(Decimal(str(value)), ",f")
    if "." in exact:
        exact = exact.rstrip("0").rstrip(".")
    return f"${exact}" if unit == "USD" else f"{exact} {unit}"


def _short(value, unit: str) -> str:
    return _value(value, unit) if unit in {"USD", "EUR"} else _scaled(value, suffix=f" {unit}")


def _short_pair(current, prior, unit: str) -> tuple[str, str]:
    rendered = _short(current, unit), _short(prior, unit)
    if rendered[0] != rendered[1] or current == prior:
        return rendered
    affixes = {"prefix": "$"} if unit == "USD" else {"suffix": f" {unit}"}
    for decimals in range(2, 7):
        rendered = _scaled(current, decimals=decimals, **affixes), _scaled(prior, decimals=decimals, **affixes)
        if rendered[0] != rendered[1]:
            break
    return rendered


# --------------------------------------------------------------------------------------------------
# Claims and evidence from one (current, prior) pair
# --------------------------------------------------------------------------------------------------

def _annual(record: SecFactRecord) -> bool:
    days = _duration(record)
    return days is not None and record.form.startswith(ANNUAL_PREFIXES) and 330 <= days <= 385


def _comparable(current: SecFactRecord, prior: SecFactRecord) -> bool:
    if (current.cik != prior.cik or current.taxonomy != prior.taxonomy or current.concept != prior.concept
            or current.unit != prior.unit or not _annual(current) or not _annual(prior)):
        return False
    gap = (date.fromisoformat(current.end) - date.fromisoformat(prior.end)).days
    return 350 <= gap <= 380 and abs(_duration(current) - _duration(prior)) <= 7


def _proof_taxonomy(proof) -> Optional[str]:
    """The taxonomy the filing's own markup names for the fact (its concept namespace), never a caller's word."""
    from ..providers.sec_inline_facts import _TAXONOMIES
    namespace = proof.get("concept_namespace") if isinstance(proof, dict) else None
    return next((name for name in BASES if isinstance(namespace, str) and _TAXONOMIES[name].fullmatch(namespace)), None)


def _bind_inline(record: SecFactRecord, *, ticker: str, expected_cik: str) -> Optional[dict]:
    """A claim for a fact read from the filing's own inline XBRL, bound to its exact location in that document."""
    from ..integrity.sec_inline_binding import inline_document_reference
    if _proof_taxonomy(record.inline_binding) != record.taxonomy:
        return None
    reference = inline_document_reference(record, expected_cik=expected_cik, taxonomies=tuple(BASES), currencies="*")
    if (reference is None or record.form not in AS_REPORTED_FORMS or isinstance(record.value, bool)
            or record.concept not in {c for by in CORE.values() for cs in by.values() for c in cs}):
        return None
    claim = QuantitativeClaim(
        value_text=_display(record.value, record.unit), provenance=Provenance.REPORTED, raw_value=record.value,
        unit=record.unit, ticker=ticker, metric=f"{record.taxonomy}:{record.concept}", as_of=record.end,
        source=record.form, document_ref=reference)
    output = claim.to_dict()
    output.update({
        "period_start": record.start, "period_end": record.end, "period": f"FY{record.end[:4]}",
        "scope": "consolidated", "currency": record.unit, "label": record.label,
        "taxonomy": record.taxonomy, "reporting_basis": BASES[record.taxonomy],
        # Additive: the exact source location of the fact inside the filing document.
        "inline_binding": dict(record.inline_binding),
    })
    return output


def _bind(record: SecFactRecord, *, ticker: str, expected_cik: str) -> Optional[dict]:
    """A producer-bound claim for one fact, or None unless every identity agrees."""
    if record.inline_binding is not None:
        return _bind_inline(record, ticker=ticker, expected_cik=expected_cik)
    if (record.taxonomy not in BASES or not re.fullmatch(r"[A-Z]{3}", record.unit or "") or not record.concept
            or record.form not in AS_REPORTED_FORMS or not expected_cik.isdigit() or not record.cik.isdigit()
            or int(expected_cik) != int(record.cik) or not _ACCESSION.fullmatch(record.accession or "")
            or isinstance(record.value, bool)):
        return None
    try:
        date.fromisoformat(record.end), date.fromisoformat(record.filed)
        if record.start is not None:
            date.fromisoformat(record.start)
        amount = Decimal(str(record.value))
        if not amount.is_finite():
            return None
    except (TypeError, ValueError, ArithmeticError):
        return None
    url = (f"https://www.sec.gov/Archives/edgar/data/{int(record.cik)}/"
           f"{record.accession.replace('-', '')}/{record.accession}-index.htm")
    if record.filing_url != url:
        return None
    claim = QuantitativeClaim(
        value_text=_display(record.value, record.unit), provenance=Provenance.REPORTED, raw_value=record.value,
        unit=record.unit, ticker=ticker, metric=f"{record.taxonomy}:{record.concept}", as_of=record.end,
        source=record.form,
        document_ref=ClaimDocumentReference(
            reference_id=f"sec:{record.cik}:{record.accession}:{record.taxonomy}:{record.concept}",
            title=f"{record.form} filed {record.filed} · {record.label}", provider="SEC EDGAR", url=url,
            published_at=record.filed))
    output = claim.to_dict()
    output.update({
        "period_start": record.start, "period_end": record.end, "period": f"FY{record.end[:4]}",
        "scope": "consolidated", "currency": record.unit, "label": record.label,
        # Additive metadata for this slice: where the figure was reported and on what basis.
        "taxonomy": record.taxonomy, "reporting_basis": BASES[record.taxonomy],
    })
    return output


def evidence_from_pair(current: SecFactRecord, prior: SecFactRecord, *, ticker: str, expected_cik: str,
                       metric_name: str) -> tuple[Optional[RetrievedEvidence], Optional[str]]:
    """(evidence, None), or (None, why it was withheld)."""
    if not _comparable(current, prior):
        return None, "periods_not_comparable"
    if prior.value == 0:
        return None, "prior_value_zero"
    if current.value <= 0 or prior.value <= 0:
        return None, "non_positive_value"
    name = metric_label(metric_name, current.concept)
    change = ((Decimal(str(current.value)) - Decimal(str(prior.value))) / abs(Decimal(str(prior.value))) * 100)
    current_text, prior_text = _short_pair(current.value, prior.value, current.unit)
    if change == 0:
        # Equal amounts: nothing moved, so no direction and no percentage.
        lead, link = f"{ticker} {name} was unchanged at", "the same as"
    else:
        direction = "increased" if change > 0 else "decreased"
        if f"{abs(change):.1f}" == "0.0":
            # A real movement too small to show at one decimal keeps its direction and is not rounded to nothing.
            lead = f"{ticker} {name} {direction} by less than 0.1% to"
        else:
            lead = f"{ticker} {name} {direction} {abs(change):.1f}% to"
        link = "from"
    summary = (f"{lead} {current_text} for the period {current.start} to {current.end}, {link} "
               f"{prior_text} in the comparable prior-year period {prior.start} to {prior.end}. "
               f"Reported in {current.unit} under {BASES[current.taxonomy]}; no currency conversion was applied.")
    claims = [claim for record in (current, prior)
              if (claim := _bind(record, ticker=ticker, expected_cik=expected_cik)) is not None]
    if len(claims) != 2:
        return None, "claim_binding_failed"
    return RetrievedEvidence(
        title=f"{ticker} {name}: {_short(current.value, current.unit)} ({current.end})",
        source=SOURCE, summary=summary, timestamp=current.filed, url=current.filing_url, relevance_score=0.99,
        source_type="regulatory_filing", source_tier="primary", claim_type="reported_fact",
        document_type=current.form, reporting_period_start=current.start, reporting_period_end=current.end,
        filed_at=current.filed, extraction_method="structured_xbrl", verified_claims=claims), None


def rebuild_as_reported(item, *, ticker: str, cik: str, name: str) -> Optional[RetrievedEvidence]:
    """Recheck both facts and the displayed summary of an as-reported comparison from its bound claims."""
    claims = getattr(item, "verified_claims", None)
    if not isinstance(claims, list) or len(claims) != 2 or name not in CORE:
        return None
    try:
        records = []
        for claim in claims:
            ref = claim["document_ref"]
            if claim.get("inline_binding") is not None:
                proof = claim["inline_binding"]
                if (_proof_taxonomy(proof) != claim.get("taxonomy") or claim["ticker"] != ticker or claim["provenance"] != "reported" or claim["scope"] != "consolidated"
                        or claim.get("taxonomy") not in BASES or claim.get("reporting_basis") != BASES[claim["taxonomy"]]
                        or claim["metric"] != f"{claim['taxonomy']}:{proof['concept']}" or claim["currency"] != claim["unit"]
                        or proof["concept"] not in CORE[name].get(claim["taxonomy"], ())
                        or proof["unit"] != claim["unit"] or proof["start"] != claim["period_start"]
                        or proof["end"] != claim["period_end"]):
                    return None
                records.append(SecFactRecord(
                    cik=str(int(cik)), taxonomy=claim["taxonomy"], concept=proof["concept"], label=proof["concept"],
                    unit=claim["unit"], value=claim["raw_value"], start=claim["period_start"], end=claim["period_end"],
                    filed=ref["published_at"], form=claim["source"], accession=proof["accession"],
                    filing_url=ref["url"], inline_binding=proof))
                continue
            match = _REFERENCE.fullmatch(ref["reference_id"])
            if (not match or int(match[1]) != int(cik) or claim["ticker"] != ticker or claim["provenance"] != "reported"
                    or claim["scope"] != "consolidated" or ref["provider"] != "SEC EDGAR"
                    or claim["metric"] != f"{match[3]}:{match[4]}" or claim.get("taxonomy") != match[3]
                    or claim.get("reporting_basis") != BASES[match[3]] or claim["currency"] != claim["unit"]
                    or match[4] not in CORE[name].get(match[3], ())
                    or date.fromisoformat(ref["published_at"]) > date.today()
                    or date.fromisoformat(claim["period_end"]) > date.today()):
                return None
            records.append(SecFactRecord(
                cik=match[1], taxonomy=match[3], concept=match[4], label=claim["label"], unit=claim["unit"],
                value=claim["raw_value"], start=claim["period_start"], end=claim["period_end"], filed=ref["published_at"],
                form=claim["source"], accession=match[2], filing_url=ref["url"]))
        rebuilt, _ = evidence_from_pair(records[0], records[1], ticker=ticker, expected_cik=cik, metric_name=name)
        if (rebuilt is None or rebuilt.verified_claims != claims or rebuilt.summary != item.summary
                or rebuilt.url != item.url or rebuilt.timestamp != item.timestamp
                or rebuilt.reporting_period_start != item.reporting_period_start
                or rebuilt.reporting_period_end != item.reporting_period_end):
            return None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    return rebuilt


# --------------------------------------------------------------------------------------------------
# Selecting a basis and building the comparisons
# --------------------------------------------------------------------------------------------------

def choose_basis(records: Sequence[SecFactRecord]):
    """(taxonomy, currency, latest_anchor_end) or (None, None, reason)."""
    annual = [r for r in records if r.form.startswith(ANNUAL_PREFIXES)]
    anchors = [r for r in annual if r.concept == ANCHOR and r.start is None]
    rows = anchors or [r for r in annual if _annual(r)]
    if not rows:
        return None, None, "no_annual_facts"
    latest = {}
    for r in rows:
        key = (r.taxonomy, r.unit)
        latest[key] = max(latest.get(key, r.end), r.end)
    top = max(latest.values())
    bases = [key for key, end in latest.items() if end == top]
    if len(bases) != 1:
        return None, None, "ambiguous_basis_or_currency"
    return bases[0][0], bases[0][1], top if anchors else None


def build_comparisons(records: Sequence[SecFactRecord], *, ticker: str, cik: str):
    """(evidence, withheld): withheld is a list of {metric, reason, concepts}. Pure over ``records``."""
    taxonomy, currency, anchor_end = choose_basis(records)
    if taxonomy is None:
        return [], [{"metric": "all", "reason": anchor_end, "concepts": []}]
    evidence, withheld = [], []
    for name, by_tax in CORE.items():
        candidates, reasons = [], []
        for concept in by_tax.get(taxonomy, ()):
            rows = [r for r in records if r.taxonomy == taxonomy and r.concept == concept and r.unit == currency and _annual(r)]
            if not rows:
                continue
            latest_end = max(r.end for r in rows)
            current = _latest_unambiguous_fact([r for r in rows if r.end == latest_end], include_start=True)
            if current is None:
                reasons.append((concept, "ambiguous_current_observation"))
                continue
            current_end = date.fromisoformat(current.end)
            priors = [r for r in rows if r.end < current.end and _comparable(current, r)]
            if not priors:
                reasons.append((concept, "no_comparable_prior_year_period"))
                continue
            prior_end = max(r.end for r in priors)
            prior = _latest_unambiguous_fact([r for r in priors if r.end == prior_end], include_start=True)
            if prior is None:
                reasons.append((concept, "ambiguous_prior_observation"))
                continue
            item, why = evidence_from_pair(current, prior, ticker=ticker, expected_cik=cik, metric_name=name)
            if item is None:
                reasons.append((concept, why))
                continue
            if anchor_end and (date.fromisoformat(anchor_end) - current_end).days > MAX_STALENESS_DAYS:
                reasons.append((concept, "stale_relative_to_latest_balance_sheet"))
                continue
            candidates.append(item)
        if candidates:
            # Aliases are ordered, never joined; the latest current period wins. For revenue, concepts that disagree
            # for that period resolve to the issuer's total revenues; otherwise ties keep the configured order.
            evidence.append(latest_revenue(candidates) if name == "revenue"
                            else max(candidates, key=lambda c: c.reporting_period_end or ""))
        else:
            withheld.append({"metric": name, "reason": reasons[0][1] if reasons else "concept_not_reported",
                             "concepts": [c for c, _ in reasons] or list(by_tax.get(taxonomy, ())),
                             "basis": BASES[taxonomy], "currency": currency})
    # One period for the whole answer: a measure whose latest valid annual period is older than another's is
    # withheld rather than shown beside it as if the periods matched.
    if evidence:
        newest = max(item.reporting_period_end or "" for item in evidence)
        for item in [i for i in evidence if (i.reporting_period_end or "") != newest]:
            evidence.remove(item)
            name = next(n for n, by in CORE.items() if item.verified_claims[0]["metric"].partition(":")[2] in by.get(taxonomy, ()))
            withheld.append({"metric": name, "reason": "older_period_than_other_measures",
                             "concepts": [item.verified_claims[0]["metric"].partition(":")[2]],
                             "basis": BASES[taxonomy], "currency": currency})
    return evidence, withheld


def evidence_from_response(data: Optional[dict], ticker: str, cik: str, *, boundary: Optional[date] = None):
    """Build annual comparisons from the Company Facts response the request already holds. (evidence, withheld).

    Makes no request. With no response (the existing fetch failed or was not made) it returns nothing.
    """
    from ..providers.sec_client import as_reported_records_from_facts
    records = as_reported_records_from_facts(data, cik, specs=requested_specs()) if data else []
    if boundary is not None:
        records = [r for r in records if date.fromisoformat(r.filed) <= boundary and date.fromisoformat(r.end) <= boundary]
    if not records:
        return [], []
    return build_comparisons(records, ticker=ticker, cik=cik)
