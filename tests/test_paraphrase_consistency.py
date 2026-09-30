from __future__ import annotations

import json

import pytest

from scripts import benchmark_paraphrase_consistency
from validation.intelligence_benchmark import BenchmarkContractError
from validation.paraphrase_consistency import (
    ParaphraseGroup,
    score_paraphrase_groups,
    score_payload,
)


def _claim(**overrides):
    value = {
        "claim_id": "revenue", "value": "100", "unit": "million",
        "currency": "USD", "period": "FY2025", "scope": "consolidated",
        "source_id": "10-k-2025",
    }
    value.update(overrides)
    return value


def _variant(variant_id, question, **overrides):
    value = {
        "variant_id": variant_id, "question": question, "behavior": "answer",
        "direction": "positive", "confidence": 0.70,
        "claims": [_claim()], "material_risk_ids": ["margin"],
        "material_catalyst_ids": ["new-product"],
    }
    value.update(overrides)
    return value


def _group(*variants):
    return ParaphraseGroup.from_dict({
        "group_id": "apple-growth", "case_id": "case-1", "issuer_id": "AAPL",
        "as_of": "2026-01-01T00:00:00Z", "source_snapshot_id": "snapshot-1",
        "variants": variants or (
            _variant("a", "What drives Apple's growth?"),
            _variant("b", "What are Apple's main growth drivers?"),
        ),
    })


def test_consistent_pair_scores_one():
    result = score_paraphrase_groups([_group()])
    assert result.paraphrase_consistency == 1.0
    assert result.material_inconsistency_count == 0
    assert result.fully_evaluated is True


def test_all_pairs_are_scored_not_only_a_baseline():
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?"),
        _variant("b", "Question two?"),
        _variant("c", "Question three?"),
    )])
    assert result.pair_count == 3
    assert result.consistent_pair_count == 3


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"behavior": "abstain", "confidence": None}, "answer_behavior_changed"),
        ({"direction": "negative"}, "thesis_direction_changed"),
        ({"confidence": 0.40}, "confidence_drift"),
        ({"confidence": None, "behavior": "abstain"}, "answer_behavior_changed"),
        ({"claims": []}, "material_claim_omitted"),
        ({"claims": [_claim(value="101")]}, "material_claim_conflict"),
        ({"claims": [_claim(source_id="press-release")]}, "material_claim_conflict"),
        ({"material_risk_ids": ["competition"]}, "material_risk_coverage_drift"),
        ({"material_catalyst_ids": ["services"]}, "material_catalyst_coverage_drift"),
    ],
)
def test_material_drift_is_explicit(overrides, code):
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?"),
        _variant("b", "Question two?", **overrides),
    )])
    assert result.paraphrase_consistency == 0.0
    assert code in result.groups[0].pairs[0].finding_codes


def test_confidence_at_tolerance_is_allowed():
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?", confidence=0.70),
        _variant("b", "Question two?", confidence=0.55),
    )])
    assert result.paraphrase_consistency == 1.0


def test_equivalent_decimal_formatting_is_not_material_drift():
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?", claims=[_claim(value="100")]),
        _variant("b", "Question two?", claims=[_claim(value="100.0")]),
    )])
    assert result.paraphrase_consistency == 1.0


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_confidence_fails_closed(confidence):
    with pytest.raises(BenchmarkContractError, match="confidence"):
        _group(_variant("a", "One?"), _variant("b", "Two?", confidence=confidence))


def test_topic_overlap_threshold_is_explicit():
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?", material_risk_ids=["a", "b"]),
        _variant("b", "Question two?", material_risk_ids=["a", "c"]),
    )], minimum_topic_overlap=0.33)
    assert result.paraphrase_consistency == 1.0


def test_empty_topic_sets_are_consistent():
    result = score_paraphrase_groups([_group(
        _variant("a", "Question one?", material_risk_ids=[], material_catalyst_ids=[]),
        _variant("b", "Question two?", material_risk_ids=[], material_catalyst_ids=[]),
    )])
    assert result.paraphrase_consistency == 1.0


def test_duplicate_questions_and_variant_ids_fail_closed():
    with pytest.raises(BenchmarkContractError, match="variant ids"):
        _group(_variant("a", "One?"), _variant("a", "Two?"))
    with pytest.raises(BenchmarkContractError, match="questions"):
        _group(_variant("a", "Same?"), _variant("b", "same?"))


def test_answer_requires_confidence():
    with pytest.raises(BenchmarkContractError, match="require confidence"):
        _group(_variant("a", "One?"), _variant("b", "Two?", confidence=None))


def test_duplicate_claim_and_topic_ids_fail_closed():
    with pytest.raises(BenchmarkContractError, match="claim ids"):
        _group(_variant("a", "One?"), _variant("b", "Two?", claims=[_claim(), _claim()]))
    with pytest.raises(BenchmarkContractError, match="must be unique"):
        _group(_variant("a", "One?"), _variant("b", "Two?", material_risk_ids=["x", "x"]))


def test_invalid_thresholds_fail_closed():
    with pytest.raises(BenchmarkContractError, match="max_confidence_gap"):
        score_paraphrase_groups([_group()], max_confidence_gap=1.1)
    with pytest.raises(BenchmarkContractError, match="minimum_topic_overlap"):
        score_paraphrase_groups([_group()], minimum_topic_overlap=-0.1)


def test_duplicate_group_ids_fail_closed():
    with pytest.raises(BenchmarkContractError, match="group ids"):
        score_paraphrase_groups([_group(), _group()])


def _payload(confidence=0.70):
    return {
        "groups": [{
            "group_id": "apple-growth", "case_id": "case-1", "issuer_id": "AAPL",
            "as_of": "2026-01-01T00:00:00Z", "source_snapshot_id": "snapshot-1",
            "variants": [
                _variant("a", "What drives Apple's growth?"),
                _variant("b", "What are Apple's main growth drivers?", confidence=confidence),
            ],
        }]
    }


def test_payload_and_cli_pass_consistent_bundle(tmp_path, capsys):
    payload = _payload()
    assert score_payload(payload).paraphrase_consistency == 1.0
    path = tmp_path / "paraphrases.json"
    path.write_text(json.dumps(payload))
    assert benchmark_paraphrase_consistency.main([str(path), "--require-consistent"]) == 0
    assert '"paraphrase_consistency": 1.0' in capsys.readouterr().out


def test_cli_rejects_material_inconsistency(tmp_path):
    path = tmp_path / "paraphrases.json"
    path.write_text(json.dumps(_payload(confidence=0.2)))
    assert benchmark_paraphrase_consistency.main([str(path), "--require-consistent"]) == 2


def test_empty_payload_is_visibly_not_evaluated():
    result = score_payload({"groups": []})
    assert result.paraphrase_consistency is None
    assert result.fully_evaluated is False
