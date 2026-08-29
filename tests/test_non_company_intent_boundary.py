"""Regression coverage for intent-authoritative company routing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.schemas import GeneralFinanceAnswer, QuestionRequest
from app.services.router_service import route_question


def _general_answer() -> GeneralFinanceAnswer:
    return GeneralFinanceAnswer(
        answer=(
            "Semiconductor margins reflect product mix, manufacturing yields, "
            "capacity utilization, pricing power, and input costs across the industry."
        ),
        bullets=["Product mix", "Manufacturing yields", "Capacity utilization"],
        caveats=["This is an industry-level explanation."],
    )


@pytest.mark.parametrize(
    ("intent", "question"),
    [
        ("market_question", "What factors are driving semiconductor margins?"),
        ("investing_education", "What drivers matter most for cloud margins?"),
        ("portfolio_question", "How exposed is my portfolio to margin pressure?"),
    ],
)
def test_general_intents_cannot_fuzzy_route_to_investment_pipeline(intent, question):
    request = QuestionRequest(
        question=question,
        company_name="",
        intent=intent,
    )
    fake = _general_answer()

    with (
        patch(
            "app.services.router_service._run_investment_pipeline",
            side_effect=AssertionError("general intent reached investment pipeline"),
        ),
        patch(
            "app.services.router_service.run_general_finance_agent",
            return_value=fake,
        ),
        patch(
            "app.services.router_service.run_general_fallback_agent",
            return_value=fake,
        ),
    ):
        response = route_question(request)

    assert "general" in response.answer
    assert "investment_thesis" not in response.answer
    assert response.company in ("", None)
