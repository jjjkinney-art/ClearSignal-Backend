"""Sprint 5I regressions for first-class comparative/ranking intelligence."""

from unittest.mock import patch

import pytest


class TestMultiCompanyDetection:
    @pytest.mark.parametrize(
        "query,expected",
        [
            ("NVDA vs AMD", ["NVDA", "AMD"]),
            ("Which is better, MSFT or GOOGL?", ["MSFT", "GOOGL"]),
            ("Rank NVDA, AMD, and AVGO", ["NVDA", "AMD", "AVGO"]),
            ("Compare Visa and Mastercard", ["V", "MA"]),
        ],
    )
    def test_detects_every_exact_entity_in_query_order(self, query, expected):
        from app.services.company_detection import detect_companies

        assert [company.ticker for company in detect_companies(query)] == expected

    def test_deduplicates_repeated_company(self):
        from app.services.company_detection import detect_companies

        result = detect_companies("Compare Apple vs Apple vs Microsoft")
        assert [company.ticker for company in result] == ["AAPL", "MSFT"]

    def test_does_not_fuzzy_guess_second_company(self):
        from app.services.company_detection import detect_companies

        result = detect_companies("Compare Nvidio and AMD")
        assert [company.ticker for company in result] == ["AMD"]


class TestComparativeRankingService:
    def _companies(self, query):
        from app.services.company_detection import detect_companies

        return detect_companies(query)

    def test_ranks_structural_quality_not_input_order(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Rank AMD, NVDA, and AVGO"),
            question="Rank AMD, NVDA, and AVGO",
        )
        assert [entry.ticker for entry in result.entries] == ["AVGO", "NVDA", "AMD"]
        assert result.leader == "AVGO"
        assert result.score_spread > 0

    def test_known_quality_pair_orders_defensibly(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Compare MSFT vs TSLA"),
            question="Compare MSFT vs TSLA",
        )
        assert [entry.ticker for entry in result.entries] == ["MSFT", "TSLA"]
        assert result.entries[0].structural_quality_score > result.entries[1].structural_quality_score

    def test_entries_include_decision_evidence(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Compare Visa and Mastercard"),
            question="Compare Visa and Mastercard",
        )
        for entry in result.entries:
            assert entry.key_advantage
            assert entry.estimate_watch
            assert entry.valuation_reference.startswith(
                "Curated reference framework (not live market data):"
            )

    def test_result_disclaims_buy_and_live_return_ranking(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Which is the better stock, MSFT or GOOGL?"),
            question="Which is the better stock, MSFT or GOOGL?",
        )
        caveats = " ".join(result.caveats).lower()
        assert "not current expected return" in caveats
        assert "non-live market data" in caveats

    def test_valuation_question_gets_live_data_limitation(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Which is cheaper, NVDA or AMD?"),
            question="Which is cheaper, NVDA or AMD?",
        )
        assert "live valuation winner cannot be determined" in result.caveats[0].lower()

    def test_equal_scores_preserve_user_order(self):
        from app.services.comparative_ranking_service import build_comparative_ranking

        result = build_comparative_ranking(
            self._companies("Compare MA vs V"),
            question="Compare MA vs V",
        )
        assert [entry.ticker for entry in result.entries] == ["MA", "V"]
        assert result.leader == ""
        assert "tied" in result.summary.lower()

    def test_surface_respects_institutional_pairwise_constraints(self):
        from app.services.company_detection import detect_company
        from app.services.comparative_ranking_service import build_comparative_ranking
        from tests.benchmark.v0_institutional_benchmark import PAIRWISE_CONSTRAINTS

        violations = []
        tested = 0
        for superior, inferior, reason in PAIRWISE_CONSTRAINTS:
            superior_company = detect_company(superior)
            inferior_company = detect_company(inferior)
            if superior_company is None or inferior_company is None:
                continue
            result = build_comparative_ranking([superior_company, inferior_company])
            scores = {entry.ticker: entry.structural_quality_score for entry in result.entries}
            tested += 1
            if scores[superior] < scores[inferior]:
                violations.append(
                    f"{superior} ({scores[superior]:.2f}) < "
                    f"{inferior} ({scores[inferior]:.2f}): {reason}"
                )

        assert tested >= 100
        assert len(violations) / tested <= 0.10, "\n".join(violations[:10])


class TestComparativeRouter:
    def test_comparison_uses_dedicated_route_without_llm_pipeline(self):
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        with patch(
            "app.services.router_service._run_investment_pipeline",
            side_effect=AssertionError("single-company pipeline must not run"),
        ):
            response = route_question(
                QuestionRequest(company_name="", question="Compare NVDA vs AMD")
            )

        assert response.routing["pipeline"] == "comparative_ranking"
        assert response.routing["detected_tickers"] == ["NVDA", "AMD"]
        assert response.agents_used == ["comparative_ranking"]
        assert "comparative_ranking" in response.answer
        assert "general" in response.answer

    def test_frontend_company_and_question_company_are_combined(self):
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        response = route_question(
            QuestionRequest(company_name="NVDA", question="Compare it with AMD")
        )
        assert response.routing["pipeline"] == "comparative_ranking"
        assert response.routing["detected_tickers"] == ["NVDA", "AMD"]

    def test_one_resolved_company_requests_disambiguation(self):
        from app.schemas import QuestionRequest
        from app.services.router_service import route_question

        with patch(
            "app.services.router_service._run_investment_pipeline",
            side_effect=AssertionError("must not silently analyze one company"),
        ):
            response = route_question(
                QuestionRequest(company_name="", question="Compare Nvidio vs AMD")
            )
        assert response.routing["pipeline"] == "comparative_disambiguation"
        assert response.routing["detected_tickers"] == ["AMD"]

    def test_generic_between_question_is_not_hijacked(self):
        from app.schemas import GeneralFinanceAnswer, QuestionRequest
        from app.services.router_service import route_question

        answer = GeneralFinanceAnswer(
            answer="Debt is contractual capital, while equity is residual ownership capital.",
            bullets=["Debt ranks ahead of equity in the capital structure."],
            caveats=[],
        )
        with patch("app.services.router_service.run_general_finance_agent", return_value=answer):
            response = route_question(
                QuestionRequest(
                    company_name="",
                    question="What is the difference between debt and equity?",
                    intent="investing_education",
                )
            )
        assert response.routing["pipeline"] != "comparative_disambiguation"

    def test_single_company_temporal_comparison_is_not_hijacked(self):
        from app.schemas import AgentAnswerResponse, QuestionRequest
        from app.services.router_service import route_question

        stub = AgentAnswerResponse(
            company="Apple Inc.", request_id="test", agents_used=["investment"],
            answer={"investment_thesis": {}},
        )
        with patch("app.services.router_service._run_investment_pipeline", return_value=stub) as run:
            response = route_question(
                QuestionRequest(
                    company_name="AAPL",
                    question="Compare Apple's margins between 2025 and 2026",
                )
            )
        assert response is stub
        run.assert_called_once()

    def test_single_company_non_comparison_route_is_unchanged(self):
        from app.schemas import AgentAnswerResponse, QuestionRequest
        from app.services.router_service import route_question

        stub = AgentAnswerResponse(
            company="NVIDIA Corporation",
            request_id="test",
            agents_used=["investment"],
            answer={"investment_thesis": {}},
        )
        with patch("app.services.router_service._run_investment_pipeline", return_value=stub) as run:
            response = route_question(
                QuestionRequest(company_name="", question="Analyze NVDA's investment thesis")
            )
        assert response is stub
        run.assert_called_once()
