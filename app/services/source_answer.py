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

# Scoped source questions are a bounded evidence view, not permission to
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
        limitation = (f"The {scope} disclosure does not verify revenue growth, risk likelihood, "
                      "quantified financial impact, or a directional thesis change.")
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
    # Retain only producer-bound Services amounts/growth from the selected
    # admitted items, never numbers extracted from the generated thesis.
    verified = [dict(claim) for item in selected_items if enough
                for claim in (getattr(item, "verified_claims", []) or [])
                if isinstance(claim, dict)
                and str(claim.get("metric", "")).startswith("issuer:Services net sales")
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
    """Return whether the user explicitly requested evidence attribution."""
    return bool(
        _SOURCE_REQUEST_RE.search(question or "")
        or _NATURAL_EVIDENCE_REQUEST_RE.search(question or "")
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
    return summary[:500] if len(summary) >= 30 else None


def apply_source_answer_gate(thesis: object, question: str, items: Iterable[object],
                             *, references: list[dict] | None = None) -> dict | None:
    """Bind source-demand answers to retrieved evidence or fail closed."""
    if not is_source_answer_request(question):
        return None

    from .services_risk_evidence import bound_services_risk, requests_services_operating_risk
    from .issuer_risk_evidence import bound_issuer_risk, requested_risk_profile
    from .services_revenue_evidence import requests_services_revenue
    from .evidence_references import _evidence_url

    material = list(items)
    claims: list[dict] = []
    selected_items: list[object] = []
    services_requested = bool(_SERVICES_SCOPE_RE.search(question or ""))
    ticker = str(getattr(thesis, "ticker", ""))
    risk_profile = requested_risk_profile(ticker, question)
    scoped_risk = risk_profile if ticker != "AAPL" else None
    risk_requested = bool(risk_profile) or (services_requested and requests_services_operating_risk(question))
    for index, item in enumerate(material, start=1):
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
        if getattr(item, "risk_disclosures", []) and not disclosure:
            continue
        # The new issuer/topic slices support qualitative risk disclosures.
        # Consolidated metrics and generated summaries cannot establish a
        # segment's growth or fill its risk slot without their own binding.
        if scoped_risk and not disclosure:
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
        if disclosure:
            row.update(claim_kind="issuer_disclosed_risk", document_ref=disclosure["document_ref"])
        if len(claims) == 3:
            # Preserve one requested risk slot even when earlier Services
            # context filled the three-claim presentation limit.
            if disclosure:
                claims[-1] = row
                selected_items[-1] = item
                break
            continue
        claims.append(row)
        selected_items.append(item)
        if len(claims) == 3 and (not risk_requested or any(
            candidate.get("claim_kind") == "issuer_disclosed_risk" for candidate in claims
        )):
            break

    requested_three = bool(re.search(r"\b(?:three|3)\b", question, re.IGNORECASE))
    enough = len(claims) >= (3 if requested_three else 1)
    if not enough:
        answer = (
            "ClearSignal retrieved source records, but this run did not extract "
            "enough claim-level evidence to answer the question with reliable "
            "claim-to-source attribution. Review the linked filings directly or "
            "run the analysis again when structured facts are available."
        )
        setattr(thesis, "direct_answer", answer)
        if services_requested or scoped_risk:
            _restrict_evidence_thesis(thesis, answer, [], [], enough=False,
                                    scope=scoped_risk.scope if scoped_risk else "Services")
        return {
            "status": "insufficient_claim_evidence",
            "reason": "Not enough relevant claim-level support was retrieved for this question.",
            "claims": [],
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
    elif risk_requested:
        answer += "\n\nNo source-bound Services operating-risk disclosure qualified in this run."
    setattr(thesis, "direct_answer", answer)
    if services_requested or scoped_risk:
        _restrict_evidence_thesis(thesis, answer, claims, selected_items, enough=True,
                                scope=scoped_risk.scope if scoped_risk else "Services")
    return {
        "status": "attributed",
        "reason": "Each claim is bound to a retrieved evidence reference.",
        "claims": claims,
    }
