"""Public routing boundaries for reviewed and unresolved issuer evidence queries."""
import pytest

from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import router_service
from app.services.company_detection import detect_company
from app.services.issuer_risk_evidence import RISK_PROFILES
from app.services.research_conversations import assistant_text_from_response


@pytest.mark.parametrize('name', ['DOCU', 'docu', 'DocuSign', 'DocuSign Inc.', 'Docu Sign'])
def test_docusign_identity_routes_to_evidence_pipeline(monkeypatch, name):
    question = 'What current public evidence identifies an operating risk to DocuSign’s subscription renewals, and what remains unverified?'
    captured = []
    def pipeline(**kwargs):
        captured.append(kwargs)
        return AgentAnswerResponse(company='DOCU', request_id='test', agents_used=[], answer={})
    monkeypatch.setattr(router_service, '_run_investment_pipeline', pipeline)
    response = router_service.route_question(QuestionRequest(company_name=name, question=question, intent='company_analysis'))
    assert response.company == 'DOCU'
    assert len(captured) == 1 and captured[0]['question'] == question
    assert captured[0]['company'].ticker == 'DOCU'
    assert captured[0]['company'].company_name == 'DocuSign Inc.'


def test_reviewed_risk_profiles_have_upstream_company_identity():
    for ticker in RISK_PROFILES:
        assert detect_company(ticker).ticker == ticker


def test_docusign_in_question_resolves_without_explicit_ticker(monkeypatch):
    monkeypatch.setattr(router_service, '_run_investment_pipeline', lambda **k:
                        AgentAnswerResponse(company=k['company'].ticker, request_id='test', agents_used=[], answer={}))
    response = router_service.route_question(QuestionRequest(
        company_name='', question='What public evidence identifies an operating risk to DocuSign subscription renewals?'))
    assert response.company == 'DOCU'


@pytest.mark.parametrize('intent', [None, 'company_analysis'])
def test_unresolved_source_request_never_calls_legacy_agents_or_substitutes_issuer(monkeypatch, intent):
    def forbidden(*a, **k):
        pytest.fail('unresolved issuer must not run a provider or legacy analysis')
    for name in ['_run_investment_pipeline', 'enrich_grounding_context', 'build_evidence',
                 'run_equity_agent', 'run_synthesizer_agent']:
        monkeypatch.setattr(router_service, name, forbidden)
    response = router_service.route_question(QuestionRequest(
        company_name='ZZZZZ', intent=intent,
        question='What public evidence identifies subscription risks compared with Microsoft?'))
    assert response.company == 'ZZZZZ'
    assert response.routing['pipeline'] == 'company_identity_clarification'
    assert response.answer['source_answer']['claims'] == []
    assert response.answer['evidence_references'] == []
    text = assistant_text_from_response(response.model_dump(mode='json'))
    assert text == response.answer['answer']
    assert 'coverage may be incomplete' in text.lower()
    assert '{' not in text


def test_source_request_for_known_company_works_without_intent_keyword(monkeypatch):
    monkeypatch.setattr(router_service, '_run_investment_pipeline', lambda **k:
                        AgentAnswerResponse(company=k['company'].ticker, request_id='test', agents_used=[], answer={}))
    response = router_service.route_question(QuestionRequest(
        company_name='DOCU', question='What source describes DocuSign?'))
    assert response.company == 'DOCU'
