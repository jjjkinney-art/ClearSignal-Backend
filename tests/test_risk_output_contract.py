"""Regression for nested narrative fields seen in production risk output."""
import json
from unittest.mock import Mock

import pytest
from pydantic import BaseModel, ValidationError

from app.investment_agents.risk_agent import _build_prompt
from app.schemas import CompanyContext, RiskProfile
from app.structured_output import get_structured_response, repair_data


def test_nested_risk_narratives_recover_in_one_call_without_promoting_evidence():
    payload = {
        "debt_risk": {"leverage": "Debt levels remain unverified.",
                      "interest_coverage": "Interest coverage remains unverified.",
                      "refinancing_risk": "Refinancing terms remain unverified."},
        "competitive_risk": {"competitive_threats": "Services competition warrants review."},
        "regulatory_risk": {"regulatory_exposure": "App Store regulation warrants review."},
        "concentration_risk": {"customer_supplier_geography": "Supplier concentration warrants review."},
        "key_risks": ["Review the disclosed regulatory risk."],
        "overall": "These are generated risk observations, not verified facts.",
        "confidence": 0.4,
        "evidence_used": [],
        "quantitative_claims": [],
    }
    client = Mock()
    client.call.return_value = json.dumps(payload)
    result = get_structured_response("risk prompt", RiskProfile, client, max_retries=1, backoff_factor=0)
    assert client.call.call_count == 1
    for key in ("debt_risk", "competitive_risk", "regulatory_risk", "concentration_risk"):
        assert isinstance(getattr(result, key), str)
        for original in payload[key].values():
            assert original in getattr(result, key)
    assert result.overall == payload["overall"]
    assert result.confidence == 0.4
    assert result.evidence_used == result.quantitative_claims == []


@pytest.mark.parametrize("value", [
    {}, {"unknown": "text"}, {"leverage": {"nested": "text"}},
    {"leverage": ["text"]}, {"leverage": 42}, {"leverage": " "},
    {"leverage": "x" * 4001},
    {"leverage": "x" * 3000, "interest_coverage": "x" * 3000,
     "refinancing_risk": "x" * 3000},
])
def test_unsupported_narratives_remain_invalid(value):
    repaired = repair_data({"debt_risk": value}, RiskProfile)
    assert repaired["debt_risk"] == value
    with pytest.raises(ValidationError):
        RiskProfile.model_validate(repaired)


def test_plain_risk_strings_are_unchanged_and_other_schemas_are_not_coerced():
    assert repair_data({"debt_risk": "Original narrative."}, RiskProfile)["debt_risk"] == "Original narrative."
    assert repair_data({"overall": {"leverage": "text"}}, RiskProfile)["overall"] == {"leverage": "text"}

    class OtherSchema(BaseModel):
        debt_risk: str = ""

    assert repair_data({"debt_risk": {"leverage": "text"}}, OtherSchema)["debt_risk"] == {"leverage": "text"}


def test_risk_prompt_requires_string_narratives_and_supported_numbers():
    prompt = _build_prompt(CompanyContext(ticker="AAPL", company_name="Apple Inc."), [])
    for key in ("debt_risk", "competitive_risk", "regulatory_risk", "concentration_risk"):
        assert f"{key}: string" in prompt
    assert "never nested objects or arrays" in prompt
    assert "Do not invent figures" in prompt
    assert "$10B+" not in prompt
