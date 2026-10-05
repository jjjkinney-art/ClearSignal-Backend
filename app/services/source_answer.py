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
    r"\b(?:services|app store|icloud|apple music)\b", re.IGNORECASE,
)
_SERVICES_CLAIM_RE = re.compile(
    r"\b(?:services?|app store|icloud|apple music)\b", re.IGNORECASE,
)
_LEGACY_SOURCE_RE = re.compile(r"\s*\[Source:\s*https?://[^\]]+\]\s*", re.IGNORECASE)

# Services source questions are a bounded evidence view, not permission to
# publish the synthesizer's wider investment case. Keep identity and numeric
# pipeline diagnostics; reset every other schema field before persistence.
# An allowlist makes new generated fields default to withheld as well.
_SERVICES_RETAINED_FIELDS = frozenset({
    "ticker", "company_name", "generated_at", "evidence_count", "question_intent",
    "thesis_version_id", "previous_thesis_version_id", "runtime_version",
    "confidence_score", "score_source", "conviction_dimensions",
    "fragility_multiplier_applied", "asymmetry_multiplier_applied",
})


def _restrict_services_thesis(thesis: object, answer: str, claims: list[dict],
                              selected_items: list[object], *, enough: bool) -> None:
    from ..schemas import InvestmentThesis

    defaults = InvestmentThesis(ticker="", company_name="")
    for name in InvestmentThesis.model_fields:
        if name not in _SERVICES_RETAINED_FIELDS and hasattr(thesis, name):
            setattr(thesis, name, getattr(defaults, name))

    headline = (
        "Dated Services evidence was retrieved; its implications for the thesis remain unverified."
        if enough else "Services evidence is insufficient; the thesis remains unverified."
    )
    limitation = (
        "Future Services growth, Services gross margin, and thesis-invalidating "
        "operating risks were not verified by this evidence view."
    )
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


def apply_source_answer_gate(thesis: object, question: str, items: Iterable[object]) -> dict | None:
    """Bind source-demand answers to retrieved evidence or fail closed."""
    if not is_source_answer_request(question):
        return None

    material = list(items)
    claims: list[dict] = []
    selected_items: list[object] = []
    services_requested = bool(_SERVICES_SCOPE_RE.search(question or ""))
    for index, item in enumerate(material, start=1):
        claim = _claim_text(item)
        if not claim:
            continue
        # Consolidated revenue/profit observations do not answer an explicit
        # Services question. Require the extracted claim itself to mention
        # that scope; a filing title alone cannot establish segment support.
        if services_requested and not _SERVICES_CLAIM_RE.search(claim):
            continue
        claims.append({
            "claim": claim,
            "reference_id": f"E{index}",
        })
        selected_items.append(item)
        if len(claims) == 3:
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
        if services_requested:
            _restrict_services_thesis(thesis, answer, [], [], enough=False)
        return {
            "status": "insufficient_claim_evidence",
            "reason": "Not enough relevant claim-level support was retrieved for this question.",
            "claims": [],
        }

    answer = " ".join(
        f"{number}. {row['claim']} [{row['reference_id']}]"
        for number, row in enumerate(claims, start=1)
    )
    if services_requested and any(
        str(claim.get("metric", "")).startswith("issuer:Services net sales")
        for item in material for claim in getattr(item, "verified_claims", [])
        if isinstance(claim, dict)
    ):
        answer += (
            " These dated observations do not, by themselves, verify future "
            "Services growth, Services gross margin, or which operating risk "
            "would invalidate the thesis."
        )
    setattr(thesis, "direct_answer", answer)
    if services_requested:
        _restrict_services_thesis(thesis, answer, claims, selected_items, enough=True)
    return {
        "status": "attributed",
        "reason": "Each claim is bound to a retrieved evidence reference.",
        "claims": claims,
    }
