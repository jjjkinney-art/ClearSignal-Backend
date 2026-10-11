"""The PE abbreviation must not override unrelated metric semantics."""
import pytest

from app.integrity.thresholds import MetricDirection, infer_direction
from app.integrity.threshold_parsing import build_decision_thresholds


@pytest.mark.parametrize("metric", [
    "Operating margin", "Operating cash flow growth", "Per-share FCF growth",
    "Revenue growth per share", "European ROIC", "Operating yield",
])
def test_embedded_pe_does_not_override_existing_higher_metric(metric):
    assert infer_direction(metric) == MetricDirection.HIGHER_IS_BETTER
    result, = build_decision_thresholds([
        {"metric": metric, "bull_threshold": ">20%", "bear_threshold": "<10%"}
    ], ticker="TEST")
    assert result["unavailable"] is False
    assert result["direction"] == "higher_is_better"
    assert result["bull_boundary"] == 20
    assert result["bear_boundary"] == 10


@pytest.mark.parametrize("metric", ["PE", "Forward PE", "PE ratio", "Adjusted-PE", "P/E", "Forward P/E"])
def test_explicit_pe_remains_lower_is_better(metric):
    assert infer_direction(metric) == MetricDirection.LOWER_IS_BETTER
    result, = build_decision_thresholds([
        {"metric": metric, "bull_threshold": "<15x", "bear_threshold": ">25x"}
    ], ticker="TEST")
    assert result["unavailable"] is False
    assert result["direction"] == "lower_is_better"


@pytest.mark.parametrize("metric", ["Operating expense", "Revenue per share", "European operations"])
def test_unknown_names_retain_explicit_operator_fallback(metric):
    assert infer_direction(metric) is None
    result, = build_decision_thresholds([
        {"metric": metric, "bull_threshold": "<10", "bear_threshold": ">20"}
    ], ticker="TEST")
    assert result["unavailable"] is False
    assert result["direction"] == "lower_is_better"
