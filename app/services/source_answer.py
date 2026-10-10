"""Deterministic claim-to-source responses for explicit source questions."""

from __future__ import annotations

import re
from typing import Iterable


_SOURCE_REQUEST_RE = re.compile(
    r"\b(which source|what source|sources? supports?|cite|citation|pieces? of .*evidence)\b",
    re.IGNORECASE,
)
_NATURAL_EVIDENCE_REQUEST_RE = re.compile(
    r"\b(?:what|which|show|give|provide|identify)\s+"
    r"(?:(?:is|are|me|the|strongest|best|current|public|available|latest|recent|"
    r"verified|supporting)\s+){0,8}evidence\b",
    re.IGNORECASE,
)
_SERVICES_SCOPE_RE = re.compile(
    r"\b(?:services|app store|icloud|apple music|digital content)\b", re.IGNORECASE,
)
_SERVICES_CLAIM_RE = re.compile(
    r"\b(?:services?|app store|icloud|apple music|digital content)\b", re.IGNORECASE,
)
_LEGACY_SOURCE_RE = re.compile(r"\s*\[Source:\s*https?://[^\]]+\]\s*", re.IGNORECASE)
_RISK_REQUEST_RE = re.compile(
    r"\b(?:operating risks?|risks? to|invalidate(?:s|d)?|invalidating)\b"
    r"|\b(?:what|which|identify|describe|show)\b.{0,80}\brisks?\b", re.I,
)

# Source and operating-risk questions are a bounded evidence view, not permission to
# publish the synthesizer's wider investment case. Keep identity and numeric
# pipeline diagnostics; reset every other schema field before persistence.
# An allowlist makes new generated fields default to withheld as well.
_EVIDENCE_VIEW_RETAINED_FIELDS = frozenset({
    "ticker", "company_name", "generated_at", "evidence_count", "question_intent",
    "thesis_version_id", "previous_thesis_version_id", "runtime_version",
    "confidence_score", "score_source", "conviction_dimensions",
    "fragility_multiplier_applied", "asymmetry_multiplier_applied",
})


def _restrict_evidence_thesis(thesis: object, answer: str, claims: list[dict],
                              selected_items: list[object], *, enough: bool,
                              scope: str = "Services") -> None:
    from ..schemas import InvestmentThesis

    defaults = InvestmentThesis(ticker="", company_name="")
    for name in InvestmentThesis.model_fields:
        if name not in _EVIDENCE_VIEW_RETAINED_FIELDS and hasattr(thesis, name):
            setattr(thesis, name, getattr(defaults, name))

    headline = (
        f"Dated {scope} evidence was retrieved; its implications for the thesis remain unverified."
        if enough else f"{scope} evidence is insufficient; the thesis remains unverified."
    )
    limitation = (
        "Future Services growth, Services gross margin, and thesis-invalidating "
        "operating risks were not verified by this evidence view."
    )
    if scope != "Services":
        limitation = ("Only the cited observations are supported. Future growth, risk likelihood, "
                      "quantified financial impact, and a directional thesis change remain unverified.")
    fields = {
        "direct_answer": answer,
        "one_sentence_thesis": headline,
        "conclusion": answer,
        "core_takeaway": headline,
        "verdict_rationale": headline,
        "directional_stance": "",
        "setup_label": "monitoring required" if enough else "insufficient conviction",
        "expectation_regime": "",
        "analysis_foundation_evidence": [row["claim"] for row in claims] if enough else [],
        "analysis_foundation_constraints": [limitation],
        "analysis_foundation_sources": list(dict.fromkeys(
            str(getattr(item, "source", "")) for item in selected_items
        )) if enough else [],
    }
    # Retain producer-bound quantities from selected admitted items; the
    # Services view permits only its segment amounts/growth.
    verified = [dict(claim) for item in selected_items if enough
                for claim in (getattr(item, "verified_claims", []) or [])
                if isinstance(claim, dict)
                and (scope != "Services" or str(claim.get("metric", "")).startswith("issuer:Services net sales"))
                and claim.get("document_ref")]
    fields["quantitative_claims"] = verified
    fields["claim_provenance_summary"] = {
        provenance: sum(claim.get("provenance") == provenance for claim in verified)
        for provenance in {claim.get("provenance") for claim in verified}
        if provenance
    }
    for name, value in fields.items():
        if name == "direct_answer" or hasattr(thesis, name):
            setattr(thesis, name, value)


def is_source_answer_request(question: str) -> bool:
    """Detect explicit attribution requests and operating-risk evidence views."""
    return bool(
        _SOURCE_REQUEST_RE.search(question or "")
        or _NATURAL_EVIDENCE_REQUEST_RE.search(question or "")
        or _RISK_REQUEST_RE.search(question or "")
    )


def _claim_text(item: object) -> str | None:
    source = str(getattr(item, "source", "") or "")
    summary = str(getattr(item, "summary", "") or "").strip()
    # Filing-discovery metadata proves only that a filing exists. It is not an
    # extracted fact and cannot support a business claim.
    if source == "SEC EDGAR" and (
        " filed a " in summary or "filings contain" in summary
    ):
        return None
    summary = _LEGACY_SOURCE_RE.sub(" ", summary)
    summary = re.sub(r"\s+", " ", summary).strip()
    # Producer-bound disclosures are complete quotations. Never truncate one
    # mid-sentence while rendering the evidence answer.
    if len(summary) < 30:
        return None
    if getattr(item, "risk_disclosures", []):
        return summary if len(summary) <= 1400 else None
    return summary[:500]


def _requested_bound_metric(item: object, ticker: str, question: str) -> bool:
    """A requested numeric fact may answer a separate part, never the risk slot."""
    from .verified_sec_metric_service import _METRICS
    from .live_issuer_kpi_service import requested_issuer_kpi_aliases
    concepts = {f"us-gaap:{concept}" for metric in _METRICS
                if any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", question, re.I) for term in metric[2])
                for concept in metric[0]}
    concepts.update(f"issuer:{metric}" for metric in requested_issuer_kpi_aliases(question))
    return any(isinstance(claim, dict) and claim.get("ticker") == ticker
               and claim.get("metric") in concepts and claim.get("document_ref")
               for claim in getattr(item, "verified_claims", []) or [])


def apply_source_answer_gate(thesis: object, question: str, items: Iterable[object],
                             *, references: list[dict] | None = None) -> dict | None:
    """Bind source-demand answers to retrieved evidence or fail closed."""
    if not is_source_answer_request(question):
        return None

    from .services_risk_evidence import bound_services_risk
    from .issuer_risk_evidence import bound_issuer_risk, requested_risk_profile
    from .services_revenue_evidence import requests_services_revenue
    from .evidence_references import _evidence_url

    material = list(items)
    from .financial_thesis_foundation import is_broad_thesis_request, build_financial_foundation
    requested_thesis = is_broad_thesis_request(question)
    from .live_issuer_kpi_service import requested_issuer_kpi_aliases
    # A company-wide financial foundation cannot substitute for a requested
    # segment, issuer KPI or named operating-risk mechanism.
    from .thesis_disclosures import requests_thesis_disclosures
    foundation_scope = requests_thesis_disclosures(str(getattr(thesis, "ticker", "")), question)
    if foundation_scope:
        foundation = build_financial_foundation(ticker=str(getattr(thesis, "ticker", "")),
                                               items=material, references=references)
        if foundation:
            from .financial_reporting_coverage import reporting_coverage
            coverage, notice, coverage_gaps = reporting_coverage(
                str(getattr(thesis, "ticker", "")), material, foundation["selected_items"], references)
            if coverage:
                foundation["answer"] += "\n\nReporting coverage\n" + notice
                foundation["unanswered_parts"].extend(coverage_gaps)
            _restrict_evidence_thesis(thesis, foundation["answer"], foundation["claims"],
                                     foundation["selected_items"], enough=True,
                                     scope="Financial thesis foundation")
            return {"status": "partial", "reason": "Producer-bound financial foundation; broader investment case remains unverified.",
                    "claims": foundation["claims"], "inferences": foundation["inferences"],
                    "unanswered_parts": foundation["unanswered_parts"],
                    "common_reporting_period": foundation["common_reporting_period"],
                    **({"reporting_coverage": coverage} if coverage else {})}
    from .verified_sec_metric_service import _requested_metrics
    requested_metrics = _requested_metrics(question, include_defaults=False)
    # A multipart metric question must retain all requested metric slots.
    # Broader prose is still not permission to generate an investment case.
    requested_three = bool(re.search(r"\b(?:three|3)\b", question, re.IGNORECASE))
    claim_limit = 3 if requested_three else max(3, len(requested_metrics))
    claims: list[dict] = []
    selected_items: list[object] = []
    ticker = str(getattr(thesis, "ticker", ""))
    from .financial_thesis_foundation import (
        SUPPLEMENTARY_METRICS, _rebuild, PRETAX_LIMITATION,
        requests_profitability_context, requests_pretax_income,
    )
    pretax_concepts = SUPPLEMENTARY_METRICS["pretax income"]
    pretax_candidates = [item for item in material if any(
        claim.get("metric") == f"us-gaap:{pretax_concepts[0]}"
        for claim in getattr(item, "verified_claims", []) if isinstance(claim, dict))]
    eligible_pretax = []
    if pretax_candidates and (requests_profitability_context(question) or requests_pretax_income(question)):
        from .providers.sec_provider import _load_ticker_cik_map
        try:
            cik = _load_ticker_cik_map().get(ticker)
        except Exception:
            cik = None
        if isinstance(cik, str):
            eligible_pretax = [item for item in pretax_candidates if _rebuild(
                item, ticker=ticker, cik=cik, name="pretax income", concepts=pretax_concepts)]
            if len({repr(item.verified_claims) for item in eligible_pretax}) != 1:
                eligible_pretax = []
    services_requested = bool(_SERVICES_SCOPE_RE.search(question or ""))
    risk_profile = requested_risk_profile(ticker, question)
    scoped_risk = risk_profile if not (ticker == "AAPL" and risk_profile and risk_profile.scope == "Services") else None
    risk_requested = bool(_RISK_REQUEST_RE.search(question or "")
                          or re.search(r"\brisks?\b", question or "", re.I))
    unsupported_risk = risk_requested and not risk_profile
    view_scope = scoped_risk.scope if scoped_risk else ("Services" if services_requested else "Requested topic")
    for index, item in enumerate(material, start=1):
        if any(item is candidate for candidate in pretax_candidates) and not any(
                item is candidate for candidate in eligible_pretax):
            continue
        claim = _claim_text(item)
        if not claim:
            continue
        # Consolidated revenue/profit observations do not answer an explicit
        # Services question. Require the extracted claim itself to mention
        # that scope; a filing title alone cannot establish segment support.
        if services_requested and not scoped_risk and not _SERVICES_CLAIM_RE.search(claim):
            continue
        disclosure = (bound_issuer_risk(item, ticker=ticker, question=question) if risk_profile
                      else bound_services_risk(item, ticker=ticker))
        if unsupported_risk:
            disclosure = None
            if not _requested_bound_metric(item, ticker, question):
                continue
        if getattr(item, "risk_disclosures", []) and not disclosure:
            continue
        # The new issuer/topic slices support qualitative risk disclosures.
        # Consolidated metrics and generated summaries cannot establish a
        # segment's growth or fill its risk slot without their own binding.
        if scoped_risk and not disclosure and not _requested_bound_metric(item, ticker, question):
            continue
        # Only producer-bound quotes can answer the requested operating-risk
        # part. Conditional/generated summaries cannot substitute for them.
        if risk_requested and re.search(r"\b(?:risk|may|might|could)\b", claim, re.I) and not disclosure:
            continue
        reference_id = f"E{index}"
        if references is not None:
            matching = next((ref for ref in references
                if ref.get("title") == str(getattr(item, "title", "") or "Untitled evidence").strip()[:300]
                and ref.get("source") == str(getattr(item, "source", "") or "Unknown source").strip()[:120]
                and ref.get("published_at") == (str(getattr(item, "timestamp", "") or "").strip()[:40] or None)
                and ref.get("url") == _evidence_url(item)), None)
            if not matching or not re.fullmatch(r"E[1-9]\d*", str(matching.get("id", ""))):
                continue
            reference_id = matching["id"]
        row = {"claim": claim, "reference_id": reference_id}
        if any(item is candidate for candidate in eligible_pretax) and not requests_pretax_income(question):
            row["claim_kind"] = "supplementary_profitability_comparison"
        if disclosure:
            row.update(claim_kind="issuer_disclosed_risk", document_ref=disclosure["document_ref"])
            if disclosure.get("issuer_relationship"):
                row["issuer_relationship"] = disclosure["issuer_relationship"]
            if disclosure.get("incorporation"):
                row["incorporation"] = disclosure["incorporation"]
                row["table_columns"] = disclosure["table_columns"]
        if len(claims) == claim_limit:
            # Preserve one requested risk slot even when earlier Services
            # context filled the three-claim presentation limit.
            if disclosure:
                claims[-1] = row
                selected_items[-1] = item
                break
            continue
        claims.append(row)
        selected_items.append(item)
        if len(claims) == claim_limit and (not risk_requested or any(
            candidate.get("claim_kind") == "issuer_disclosed_risk" for candidate in claims
        )):
            break

    unanswered_parts = []
    from .financial_reporting_coverage import reporting_coverage
    coverage, coverage_notice, coverage_gaps = reporting_coverage(
        ticker, material, selected_items, references)
    unanswered_parts.extend(coverage_gaps)
    if requested_thesis:
        unanswered_parts.append("investment thesis and its supporting/invalidation mechanisms")
    if len(requested_metrics) > 1:
        supported_concepts = {
            str(claim.get("metric", ""))
            for item in selected_items for claim in getattr(item, "verified_claims", [])
            if isinstance(claim, dict) and claim.get("ticker") == ticker
            and claim.get("document_ref")
        }
        unanswered_parts.extend(
            name for concepts, name, _, _, _ in requested_metrics
            if not any(f"us-gaap:{concept}" in supported_concepts for concept in concepts)
        )
    if risk_requested and not any(c.get("claim_kind") == "issuer_disclosed_risk" for c in claims):
        unanswered_parts.append("operating risk")
    enough = len(claims) >= (3 if requested_three else 1)
    if not enough:
        answer = (
            "ClearSignal retrieved source records, but this run did not extract "
            "enough claim-level evidence to answer the question with reliable "
            "claim-to-source attribution. Review the linked filings directly or "
            "run the analysis again when structured facts are available."
        )
        setattr(thesis, "direct_answer", answer)
        if risk_requested:
            answer = (
                "No source-bound operating-risk disclosure qualified for the requested company "
                "and topic. The retrieved sources and consolidated metrics do not establish "
                "that risk, its likelihood, or its effect on the thesis. Review the linked "
                "primary documents; this part of the question remains unverified."
            )
        if requested_thesis:
            answer = (
                "This run did not establish a source-supported investment thesis, its "
                "supporting mechanisms, or what would invalidate it. No source-bound "
                "operating-risk disclosure qualified for this broad question. Filing "
                "discovery alone cannot establish the investment case; these parts "
                "remain unverified."
            )
        elif unanswered_parts:
            answer += "\n\nUnverified requested parts: " + "; ".join(unanswered_parts) + "."
        _restrict_evidence_thesis(thesis, answer, [], [], enough=False, scope=view_scope)
        return {
            "status": "insufficient_claim_evidence",
            "reason": "No relevant source-bound operating-risk disclosure qualified." if risk_requested
                      else "Not enough relevant claim-level support was retrieved for this question.",
            "claims": [],
            "unanswered_parts": unanswered_parts,
        }

    answer = "\n\n".join(
        f"{number}. {row['claim']} [{row['reference_id']}]"
        for number, row in enumerate(claims, start=1)
    )
    has_disclosed_risk = any(row.get("claim_kind") == "issuer_disclosed_risk" for row in claims)
    if services_requested and any(
        str(claim.get("metric", "")).startswith("issuer:Services net sales")
        for item in selected_items for claim in getattr(item, "verified_claims", [])
        if isinstance(claim, dict)
    ):
        answer += (
            "\n\nThese dated observations do not, by themselves, verify future "
            "Services growth, Services gross margin, or which operating risk "
            "would invalidate the thesis."
        )
    elif risk_requested and requests_services_revenue(question):
        answer += "\n\nNo source-bound Services revenue observation qualified in this answer."
    if has_disclosed_risk:
        answer += (
            "\n\nThe quoted disclosures preserve the issuer's distinction between reported "
            "events and potential risks. This evidence view does not independently verify "
            "occurrence, current conditions, risk likelihood, quantified financial effects, "
            "or a directional thesis change."
        )
        if scoped_risk:
            answer += (f"\n\nThis {scoped_risk.scope} risk disclosure does not, by itself, "
                       "verify revenue growth or its sustainability.")
    elif risk_requested and not (ticker == "AAPL" and services_requested):
        answer += ("\n\nThese observations answer only the requested financial metric. No source-bound "
                   "operating-risk disclosure qualified for the requested company and topic; "
                   "risk likelihood, financial effects, and thesis implications remain unverified.")
    elif risk_requested:
        answer += "\n\nNo source-bound Services operating-risk disclosure qualified in this run."
    if unanswered_parts:
        answer += "\n\nUnverified requested parts: " + "; ".join(unanswered_parts) + "."
    if "operating income" in unanswered_parts:
        if any(item is candidate for item in selected_items for candidate in eligible_pretax):
            answer += "\n\n" + PRETAX_LIMITATION
    if coverage:
        answer += "\n\nReporting coverage\n" + coverage_notice
    if re.search(r"\bprofitability\b", question or "", re.I):
        profitability_concepts = {
            "operating income": {"us-gaap:OperatingIncomeLoss"},
            "net income": {"us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"},
            "pretax income": {f"us-gaap:{concept}" for concept in pretax_concepts},
        }
        selected_concepts = {
            str(claim.get("metric", ""))
            for item in selected_items for claim in getattr(item, "verified_claims", [])
            if isinstance(claim, dict) and claim.get("ticker") == ticker
            and claim.get("document_ref")
        }
        measures = [name for name, concepts in profitability_concepts.items()
                    if concepts & selected_concepts]
        if measures:
            answer += ("\n\nProfitability measures supported in this answer: "
                       + "; ".join(measures) + ". These amounts are not profit margins.")
        else:
            answer += "\n\nNo requested profitability measure was verified. Amounts are not profit margins."
        if "operating income" in unanswered_parts:
            answer += ("\n\nOperating income was not verified in this run. This does not establish "
                       "that the issuer did not report it; retrieval or extraction may be incomplete.")
    setattr(thesis, "direct_answer", answer)
    _restrict_evidence_thesis(thesis, answer, claims, selected_items, enough=True, scope=view_scope)
    return {
        "status": "partial" if unanswered_parts else "attributed",
        "reason": "Each claim is bound to a retrieved evidence reference.",
        "claims": claims,
        "unanswered_parts": unanswered_parts,
        **({"reporting_coverage": coverage} if coverage else {}),
    }
