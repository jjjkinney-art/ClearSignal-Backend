"""Grade captured ClearSignal outputs against frozen factual references.

This adapter consumes the serialized response returned by the real investment
pipeline.  It never calls providers, writes memory, or invokes user-facing
delivery.  Only structured, accession-bound ``verified_sec_facts`` are admitted;
generated prose is not silently converted into a fact.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

from .factual_citation_grading import FactualCitationScorecard, grade_payload
from .intelligence_benchmark import BenchmarkContractError


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GeneratedOutputCaseResult:
    issuer_id: str
    question_id: str
    expected_claim_count: int
    admitted_claim_count: int
    rejected_claim_count: int
    material_numerical_accuracy: float | None
    claim_source_binding: float | None
    pending_material_adjudications: int
    fabricated_material_sources: int
    stop_ship_count: int
    passed: bool


@dataclass(frozen=True)
class GeneratedOutputReport:
    schema_version: int
    run_id: str
    case_count: int
    cases: Tuple[GeneratedOutputCaseResult, ...]
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _answer(response: Mapping[str, Any]) -> Mapping[str, Any]:
    answer = response.get("answer")
    if not isinstance(answer, Mapping):
        raise BenchmarkContractError("captured response requires an answer object")
    return answer


def _source_for_fact(
    fact: Mapping[str, Any], sources: Sequence[Mapping[str, Any]],
) -> str | None:
    reference = fact.get("document_ref")
    if not isinstance(reference, Mapping):
        return None
    url = str(reference.get("url", ""))
    reference_id = str(reference.get("reference_id", ""))
    matches = []
    for source in sources:
        revision = str(source.get("revision_id", ""))
        normalized = revision.replace("-", "")
        if revision and (revision in url or revision in reference_id
                         or normalized in url or normalized in reference_id):
            matches.append(str(source.get("source_id", "")))
    return matches[0] if len(matches) == 1 and matches[0] else None


def _normalize_fact(
    fact: Mapping[str, Any], *, issuer_id: str,
    expected: Mapping[str, Any], sources: Sequence[Mapping[str, Any]],
) -> dict | None:
    metric = str(fact.get("metric", ""))
    if metric.startswith("us-gaap:"):
        metric = metric.split(":", 1)[1]
    if (
        str(fact.get("provenance", "")) != "reported"
        or str(fact.get("ticker", "")).upper() != issuer_id
        or metric != str(expected.get("metric", ""))
        or not isinstance(fact.get("document_ref"), Mapping)
        or fact.get("raw_value") is None
    ):
        return None
    source_id = _source_for_fact(fact, sources)
    return {
        "claim_id": str(expected["claim_id"]),
        "text": str(fact.get("rendered") or fact.get("value_text") or ""),
        "value": str(fact["raw_value"]),
        "unit": str(fact.get("unit", "")),
        "currency": fact.get("currency"),
        "period": str(fact.get("period", "")),
        "scope": str(fact.get("scope", "")),
        "cited_source_id": source_id,
    }


def _grade_case(case: Mapping[str, Any]) -> GeneratedOutputCaseResult:
    issuer_id = str(case.get("issuer_id", "")).upper().strip()
    question_id = str(case.get("question_id", "")).strip()
    if not issuer_id or not question_id:
        raise BenchmarkContractError("generated-output case requires issuer_id and question_id")
    expected_claims = case.get("expected_claims")
    sources = case.get("sources")
    adjudications = case.get("adjudications")
    response = case.get("response")
    if not isinstance(expected_claims, list) or not expected_claims:
        raise BenchmarkContractError("generated-output case requires expected_claims")
    if not isinstance(sources, list) or not isinstance(adjudications, list):
        raise BenchmarkContractError("generated-output case requires sources and adjudications")
    if not isinstance(response, Mapping):
        raise BenchmarkContractError("generated-output case requires a captured response")
    response_company = str(response.get("company", "")).upper().strip()
    if response_company != issuer_id:
        raise BenchmarkContractError("captured response company does not match issuer_id")

    facts = _answer(response).get("verified_sec_facts")
    if not isinstance(facts, list):
        raise BenchmarkContractError("answer.verified_sec_facts must be a list")
    observed = []
    rejected = 0
    used_indexes: set[int] = set()
    for expected in expected_claims:
        if not isinstance(expected, Mapping):
            raise BenchmarkContractError("expected claims must be objects")
        candidates = []
        for index, fact in enumerate(facts):
            if index in used_indexes or not isinstance(fact, Mapping):
                continue
            normalized = _normalize_fact(
                fact, issuer_id=issuer_id, expected=expected, sources=sources,
            )
            if normalized is not None:
                candidates.append((index, normalized))
        if len(candidates) > 1:
            raise BenchmarkContractError(
                f"captured output has ambiguous facts for {expected.get('claim_id')}"
            )
        if candidates:
            index, normalized = candidates[0]
            used_indexes.add(index)
            observed.append(normalized)
    rejected = len(facts) - len(used_indexes)

    expected_ids = {str(item.get("claim_id", "")) for item in expected_claims}
    relevant_adjudications = [
        item for item in adjudications
        if isinstance(item, Mapping) and str(item.get("claim_id", "")) in expected_ids
    ]
    scorecard: FactualCitationScorecard = grade_payload({
        "expected_claims": expected_claims,
        "observed_claims": observed,
        "adjudications": relevant_adjudications,
    })
    passed = (
        rejected == 0
        and len(observed) == len(expected_claims)
        and scorecard.fully_adjudicated
        and scorecard.stop_ship_count == 0
        and scorecard.material_numerical_accuracy == 1.0
        and scorecard.claim_source_binding == 1.0
    )
    return GeneratedOutputCaseResult(
        issuer_id=issuer_id,
        question_id=question_id,
        expected_claim_count=len(expected_claims),
        admitted_claim_count=len(observed),
        rejected_claim_count=rejected,
        material_numerical_accuracy=scorecard.material_numerical_accuracy,
        claim_source_binding=scorecard.claim_source_binding,
        pending_material_adjudications=scorecard.pending_material_adjudications,
        fabricated_material_sources=scorecard.fabricated_material_sources,
        stop_ship_count=scorecard.stop_ship_count,
        passed=passed,
    )


def grade_generated_outputs(payload: Mapping[str, Any]) -> GeneratedOutputReport:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise BenchmarkContractError("generated-output schema_version must be 1")
    run_id = str(payload.get("run_id", "")).strip()
    cases = payload.get("cases")
    if not run_id or not isinstance(cases, list) or not cases:
        raise BenchmarkContractError("generated-output run_id and non-empty cases are required")
    keys = [
        (str(item.get("issuer_id", "")).upper(), str(item.get("question_id", "")))
        for item in cases if isinstance(item, Mapping)
    ]
    if len(keys) != len(cases) or len(set(keys)) != len(keys):
        raise BenchmarkContractError("generated-output issuer/question pairs must be unique")
    results = tuple(_grade_case(case) for case in cases)
    return GeneratedOutputReport(
        schema_version=SCHEMA_VERSION, run_id=run_id, case_count=len(results),
        cases=results, passed=all(item.passed for item in results),
    )
