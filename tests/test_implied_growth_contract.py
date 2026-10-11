"""Prompt-contract tests, not a numerical answer-quality or live acceptance gate."""
from unittest.mock import patch

from app.schemas import (CompanyContext, RetrievedEvidence, ValuationView,
                         MacroSensitivity, RiskProfile, MarketContext, QualityAssessment)
from app.investment_agents.question_answerer_agent import _INTENT_PROMPTS, run_question_answerer
from app.investment_agents.valuation_agent import _build_prompt
from app.services.thesis_synthesizer import _build_synthesis_prompt
from app.services.implied_growth_contract import IMPLIED_GROWTH_RULES


def test_all_three_implied_growth_prompts_share_input_and_metric_contract():
    company = CompanyContext(ticker='TEST', company_name='Test Company')
    prompts = [
        _INTENT_PROMPTS['implied_growth_rate'],
        _build_prompt(company, [], question_intent='implied_growth_rate',
                      question='What growth is implied?'),
        _build_synthesis_prompt(company, ValuationView(overall='', confidence=0),
            MacroSensitivity(overall='', confidence=0), RiskProfile(overall='', confidence=0),
            MarketContext(overall='', confidence=0), QualityAssessment(overall='', confidence=0),
            evidence=[], original_user_question='What growth is implied?',
            question_intent='implied_growth_rate'),
    ]
    for prompt in prompts:
        assert IMPLIED_GROWTH_RULES in prompt
        assert 'Earnings CAGR is not revenue CAGR' in prompt
        assert 'margin\nand share-count bridge' in prompt
        assert 'matching metric and\nperiods' in prompt
        assert 'Numerical historical analogs require supplied evidence, never training' in prompt
        assert 'Do not infer expected stock returns from implied operating growth' in prompt
        assert '3–5 years, 10% discount and terminal P/E 20–25x' in prompt
        assert 'calculation is unavailable and name the missing inputs' in prompt
        assert 'use training knowledge' not in prompt
        assert 'Then compute the implied compound revenue' not in prompt


def test_explicit_user_scenario_is_preserved_without_new_parser_or_blanket_guard():
    question = 'Assume entry P/E 30x, terminal P/E 20x and five years; explain implied EPS growth.'
    company = CompanyContext(ticker='TEST', company_name='Test Company')
    with patch('app.investment_agents.question_answerer_agent.model_client.call',
               return_value='A conditional scenario explanation.') as call:
        result = run_question_answerer(question, 'implied_growth_rate', company, None, [])
    assert result == 'A conditional scenario explanation.'
    assert question in call.call_args.kwargs['prompt']
    assert 'Explicit user assumptions remain labeled user assumptions' in call.call_args.kwargs['prompt']


def test_available_provider_evidence_and_ordinary_valuation_keep_generation_path():
    company = CompanyContext(ticker='TEST', company_name='Test Company')
    item = RetrievedEvidence(title='TEST valuation', source='test', timestamp='',
                             summary='Trailing P/E: 30x')
    for intent in ['implied_growth_rate', 'valuation_stance', 'investment_thesis']:
        with patch('app.investment_agents.question_answerer_agent.model_client.call',
                   return_value='Supported explanation.') as call:
            assert run_question_answerer('Explain valuation.', intent, company, None,
                                         [item]) == 'Supported explanation.'
        assert 'Trailing P/E: 30x' in call.call_args.kwargs['prompt']
        if intent != 'implied_growth_rate':
            assert IMPLIED_GROWTH_RULES not in call.call_args.kwargs['prompt']
