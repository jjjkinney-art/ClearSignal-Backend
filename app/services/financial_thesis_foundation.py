"""A conditional financial case from producer-bound SEC comparisons only.

This is a partial investment-thesis foundation, never a valuation recommendation,
forecast, independently verified business moat or directional thesis change.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import re

from ..integrity.sec_metric_evidence import comparable_metric_evidence
from ..providers.sec_client import SecFactRecord

CORE_METRICS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenuesNetOfInterestExpense"),
    "operating income": ("OperatingIncomeLoss",),
    "net income": ("NetIncomeLoss", "ProfitLoss"),
    "operating cash flow": ("NetCashProvidedByUsedInOperatingActivities",),
}
SUPPLEMENTARY_METRICS = {
    "pretax income": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",),
}


def financial_metric_label(name: str, concept: str) -> str:
    """Retain the bank revenue definition instead of relabeling it as gross sales."""
    if name == "revenue" and concept == "RevenuesNetOfInterestExpense":
        return "revenue net of interest expense"
    return name


def requests_profitability_context(question: str | None) -> bool:
    return is_broad_thesis_request(question or "") or bool(re.search(r"\bprofitability\b", question or "", re.I))


def requests_pretax_income(question: str | None) -> bool:
    return bool(re.search(r"\b(?:pre[- ]?tax income|income before (?:income )?taxes)\b", question or "", re.I))


PRETAX_LIMITATION = ("The cited pretax-income comparison is supplementary profitability context. "
    "Pretax income includes effects outside operating profit; it does not establish operating income "
    "or an operating margin. Operating income remains unverified.")


def is_broad_thesis_request(question: str) -> bool:
    return bool(re.search(r"\bwhat\s+is\s+(?:the\s+)?investment thesis\b", question or "", re.I))


def _rebuild(item, *, ticker: str, cik: str, name: str, concepts: tuple):
    """Recheck both facts and the displayed summary with the existing producer."""
    if (getattr(item, "source", None) != "SEC EDGAR — structured XBRL fact"
            or getattr(item, "source_type", None) != "regulatory_filing"
            or getattr(item, "source_tier", None) != "primary"
            or getattr(item, "claim_type", None) != "reported_fact"
            or getattr(item, "extraction_method", None) != "structured_xbrl"
            or getattr(item, "freshness_status", None) in {"conflicting", "superseded", "unavailable", "stale"}):
        return None
    claims = getattr(item, "verified_claims", [])
    if not isinstance(claims, list) or len(claims) != 2:
        return None
    records = []
    try:
        for claim in claims:
            ref = claim["document_ref"]
            inline = claim.get("inline_binding")
            if inline is not None:
                # Filing facts retain the source observation, hash and exact
                # context. The binder checks them again during reconstruction.
                concept = inline.get("concept") if isinstance(inline, dict) else None
                if (concept not in concepts or claim["ticker"] != ticker
                        or claim["provenance"] != "reported" or claim["metric"] != f"us-gaap:{concept}"
                        or claim["unit"] != "USD" or claim["scope"] != "consolidated"):
                    return None
                records.append(SecFactRecord(cik=cik, taxonomy="us-gaap", concept=concept,
                    label=claim["label"], unit=claim["unit"], value=claim["raw_value"],
                    start=claim["period_start"], end=claim["period_end"], filed=ref["published_at"],
                    form=claim["source"], accession=inline.get("accession"), filing_url=ref["url"],
                    inline_binding=inline))
                continue
            match = re.fullmatch(r"sec:(\d+):(\d{10}-\d{2}-\d{6}):us-gaap:([A-Za-z0-9]+)", ref["reference_id"])
            if (not match or int(match[1]) != int(cik) or match[3] not in concepts
                    or claim["ticker"] != ticker or claim["provenance"] != "reported"
                    or claim["metric"] != f"us-gaap:{match[3]}"
                    or claim["unit"] != "USD" or claim["scope"] != "consolidated"
                    or ref["provider"] != "SEC EDGAR"
                    or date.fromisoformat(ref["published_at"]) > date.today()
                    or date.fromisoformat(claim["period_end"]) > date.today()
                    or isinstance(claim["raw_value"], bool)
                    or not Decimal(str(claim["raw_value"])).is_finite()):
                return None
            records.append(SecFactRecord(
                cik=match[1], taxonomy="us-gaap", concept=match[3], label=claim["label"],
                unit=claim["unit"], value=claim["raw_value"], start=claim["period_start"],
                end=claim["period_end"], filed=ref["published_at"], form=claim["source"],
                accession=match[2], filing_url=ref["url"],
            ))
        rebuilt = comparable_metric_evidence(records, ticker=ticker, expected_cik=cik,
                                             concepts=concepts,
                                             metric_name=financial_metric_label(name, records[0].concept))
        if (rebuilt is None or rebuilt.verified_claims != claims
                or rebuilt.summary != item.summary or rebuilt.url != item.url
                or rebuilt.timestamp != item.timestamp
                or rebuilt.reporting_period_start != item.reporting_period_start
                or rebuilt.reporting_period_end != item.reporting_period_end):
            return None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    return rebuilt


def build_financial_foundation(ticker: str, items: list, references: list[dict] | None,
                               *, expected_cik: str | None = None) -> dict | None:
    """Return a financial foundation only after identity, fact and citation checks."""
    candidates = [item for item in items if getattr(item, "verified_claims", [])]
    if not candidates:
        return None
    if expected_cik is None:
        from .providers.sec_provider import _load_ticker_cik_map
        try:
            expected_cik = _load_ticker_cik_map().get(ticker)
        except Exception:
            return None
    if not expected_cik or not expected_cik.isdigit():
        return None
    selected, rows, interpretations = [], [], []
    missing = []
    for name, concepts in CORE_METRICS.items():
        qualified = []
        for index, item in enumerate(items, start=1):
            rebuilt = _rebuild(item, ticker=ticker, cik=expected_cik, name=name, concepts=concepts)
            if rebuilt is None:
                continue
            reference_id = f"E{index}"
            if references is not None:
                ref = next((ref for ref in references
                    if ref.get("title") == item.title.strip()[:300]
                    and ref.get("source") == item.source.strip()[:120]
                    and ref.get("url") == item.url and ref.get("published_at") == item.timestamp), None)
                if not ref or not re.fullmatch(r"E[1-9]\d*", str(ref.get("id", ""))):
                    continue
                reference_id = ref["id"]
            qualified.append((item, rebuilt, reference_id))
        # Do not resolve conflicting concepts/periods by selecting the first row.
        if not qualified or len({repr(row[1].verified_claims) for row in qualified}) != 1:
            missing.append(name)
            continue
        item, rebuilt, reference_id = qualified[0]
        display_name = financial_metric_label(name, rebuilt.verified_claims[0]["metric"].split(":")[-1])
        current, prior = rebuilt.verified_claims
        value, baseline = Decimal(str(current["raw_value"])), Decimal(str(prior["raw_value"]))
        movement = "higher" if value > baseline else "lower" if value < baseline else "unchanged"
        signal = "supporting" if value > 0 and value > baseline else "counter_evidence"
        text = f"Reported {display_name} is {movement} than the comparable prior-year amount."
        if value <= 0:
            text += f" The current reported {display_name} is non-positive."
        interpretations.append({"kind": "financial_inference", "metric": display_name,
            "signal": signal, "text": text, "reference_ids": [reference_id],
            "conditional_test": f"A future comparable {display_name} below the cited current amount would weaken this financial assumption; this is a monitoring condition, not a forecast."})
        rows.append({"claim": rebuilt.summary, "reference_id": reference_id,
                     "claim_kind": "reported_financial_comparison"})
        selected.append(item)
    # One isolated observation does not form a multi-dimensional financial case.
    if len(rows) < 2:
        return None
    supplemental = []
    if "operating income" in missing:
        name, concepts = next(iter(SUPPLEMENTARY_METRICS.items()))
        for index, item in enumerate(items, 1):
            rebuilt = _rebuild(item, ticker=ticker, cik=expected_cik, name=name, concepts=concepts)
            if rebuilt is None:
                continue
            ref = f"E{index}"
            if references is not None:
                ref = next((r.get("id") for r in references
                    if r.get("title") == item.title.strip()[:300]
                    and r.get("source") == item.source.strip()[:120]
                    and r.get("url") == item.url and r.get("published_at") == item.timestamp), None)
                if not re.fullmatch(r"E[1-9]\d*", str(ref or "")):
                    continue
            supplemental.append((item, rebuilt, ref))
        if supplemental and len({repr(row[1].verified_claims) for row in supplemental}) == 1:
            item, rebuilt, ref = supplemental[0]
            rows.append({"claim": rebuilt.summary, "reference_id": ref,
                         "claim_kind": "supplementary_profitability_comparison"})
            selected.append(item)
        else:
            supplemental = []
    periods = {(item.reporting_period_start, item.reporting_period_end) for item in selected}
    limitation = ("These metrics cover different reporting durations or end dates. Evaluate each "
                  "against its own comparable prior-year period; they do not establish a common-period "
                  "margin, cash-conversion ratio or causal relationship." if len(periods) > 1 else
                  "The observations share a reporting period. No margin or cash-conversion ratio has been calculated here.")
    supporting = [f"{row['metric']} [{row['reference_ids'][0]}]" for row in interpretations if row["signal"] == "supporting"]
    counter = [f"{row['metric']} [{row['reference_ids'][0]}]" for row in interpretations if row["signal"] == "counter_evidence"]
    hypothesis = ("Conditional financial case: sustaining the favorable reported trends in " +
                  ", ".join(supporting) + " would support the financial foundation of the investment case."
                  if supporting else "The retrieved comparisons do not establish improving financial performance.")
    if counter:
        hypothesis += " Counter-evidence or an unresolved improvement pattern remains in " + ", ".join(counter) + "."
    answer = "Financial thesis foundation (partial)\n\n" + hypothesis
    answer += "\n\nReported evidence\n" + "\n\n".join(
        f"{index}. {row['claim']} [{row['reference_id']}]" for index, row in enumerate(rows, start=1))
    if supplemental:
        answer += "\n\n" + PRETAX_LIMITATION
    answer += "\n\nInterpretation and conditional tests\n" + "\n\n".join(
        f"{row['text']} [{row['reference_ids'][0]}] {row['conditional_test']}" for row in interpretations)
    from .thesis_disclosures import bound_business_description, bound_thesis_risk
    disclosures = []
    counts = {"issuer_business_description": 0, "issuer_disclosed_risk": 0}
    seen = set()
    for index, item in enumerate(items, start=1):
        value = (bound_business_description(item, ticker=ticker, cik=expected_cik)
                 or bound_thesis_risk(item, ticker=ticker))
        if not value or value["quote"] in seen or counts[value["claim_kind"]] >= 2:
            continue
        reference_id = f"E{index}"
        if references is not None:
            ref = next((ref for ref in references
                if ref.get("title") == item.title.strip()[:300]
                and ref.get("source") == item.source.strip()[:120]
                and ref.get("url") == item.url and ref.get("published_at") == item.timestamp), None)
            if not ref or not re.fullmatch(r"E[1-9]\d*", str(ref.get("id", ""))):
                continue
            reference_id = ref["id"]
        row = {"claim": item.summary, "reference_id": reference_id,
               "claim_kind": value["claim_kind"]}
        disclosures.append(row)
        rows.append(row)
        selected.append(item)
        seen.add(value["quote"])
        counts[value["claim_kind"]] += 1
    if disclosures:
        answer += "\n\nOfficial business and sampled risk context\n" + "\n\n".join(
            f"{row['claim']} [{row['reference_id']}]" for row in disclosures)
        answer += ("\nThese short excerpts are partial context, not a complete business model or a ranking "
                   "of the most material risks. Disclosed possibilities do not establish occurrence, "
                   "probability or a quantified effect on the financial case.")
    unanswered = missing + ["competitive position" if counts["issuer_business_description"] else
                            "business model and competitive position", "valuation and expected returns",
                            "issuer-disclosed operating-risk mechanisms"]
    if counts["issuer_disclosed_risk"]:
        unanswered.remove("issuer-disclosed operating-risk mechanisms")
        unanswered.append("risk materiality, likelihood and effect on the investment case")
    answer += "\n\n" + limitation
    answer += ("\n\nThis financial foundation does not establish a complete investment thesis or a buy/sell "
               "recommendation. Unverified requested parts: " + "; ".join(unanswered) + ".")
    return {"answer": answer, "claims": rows, "selected_items": selected,
            "inferences": interpretations, "unanswered_parts": unanswered,
            "common_reporting_period": len(periods) == 1}
