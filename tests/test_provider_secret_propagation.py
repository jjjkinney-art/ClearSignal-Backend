"""Synthetic transport/exception probes. Network is blocked by the test runner."""
import importlib
import json
import logging
import socket
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import OpenAI

from app.provider_diagnostics import PROVIDER_TRANSPORT_LOGGERS, install_provider_transport_guards

SECRET = 'ZXQV_synthetic_credential_Only'


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError('Network forbidden in synthetic transport tests')
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket.socket, 'sendto', blocked)
    yield
    assert not attempts, 'A synthetic transport test attempted real networking'


def assert_private(capsys, caplog):
    output = capsys.readouterr()
    text = output.out + output.err + caplog.text
    assert SECRET not in text
    assert SECRET[:4] not in text


@pytest.mark.parametrize('status', [200, 401, 429, 500])
def test_real_sdk_mock_transport_debug_logs_and_retries(capsys, caplog, status):
    from app.model_client import ModelClient
    caplog.set_level(logging.DEBUG)
    for name in PROVIDER_TRANSPORT_LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)
    dispatched = []
    def respond(request):
        assert request.headers['authorization'] == 'Bearer ' + SECRET
        dispatched.append(request)
        body = ({'choices': [{'message': {'content': 'ok'}}],
                 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
                if status == 200 else {'error': {'message': SECRET, 'type': 'fixture'}})
        return httpx.Response(status, json=body, headers={'x-request-id': SECRET})
    transport = httpx.Client(transport=httpx.MockTransport(respond))
    sdk = OpenAI(api_key=SECRET, base_url='https://api.openai.com/v1/' + SECRET + '/',
                 http_client=transport, max_retries=1)
    client = ModelClient.__new__(ModelClient)
    client.model, client.temperature, client.max_tokens = 'fixture-model', 0, 10
    client.max_retries, client.backoff_factor, client._client = 1, 0, sdk
    try:
        if status == 200:
            assert client.call('fixture prompt') == 'ok'
        else:
            with pytest.raises(Exception):
                client.call('fixture prompt')
        assert len(dispatched) == (2 if status in [429, 500] else 1)
        assert_private(capsys, caplog)
        assert 'model_call_' in caplog.text  # Application observability remains.
    finally:
        sdk.close()


def test_urllib3_real_request_diagnostic_with_fake_connection(capsys, caplog):
    from urllib3 import HTTPConnectionPool
    from urllib3.response import HTTPResponse
    caplog.set_level(logging.DEBUG, logger='urllib3.connectionpool')
    connection = MagicMock()
    connection.is_closed = False
    connection.getresponse.return_value = HTTPResponse(body=b'{}', status=200)
    pool = HTTPConnectionPool('financialmodelingprep.com')
    response = pool._make_request(connection, 'GET', '/profile?apikey=' + SECRET)
    assert response.status == 200
    assert SECRET in connection.request.call_args.args[1]
    assert_private(capsys, caplog)


def test_httpcore_trace_response_headers_and_exception(capsys, caplog):
    from httpcore import Request
    from httpcore._trace import Trace
    logger = logging.getLogger('httpcore.http11')
    caplog.set_level(logging.DEBUG, logger=logger.name)
    request = Request('GET', 'https://fixture.invalid/')
    with Trace('receive_response_headers', logger, request) as trace:
        trace.return_value = [(b'authorization', SECRET.encode())]
    with pytest.raises(RuntimeError):
        with Trace('receive_response_headers', logger, request):
            raise RuntimeError(SECRET)
    assert_private(capsys, caplog)


def test_transport_guards_idempotent_and_leave_application_logs(caplog):
    install_provider_transport_guards()
    before = {name: len(logging.getLogger(name).filters) for name in PROVIDER_TRANSPORT_LOGGERS}
    install_provider_transport_guards()
    for name in PROVIDER_TRANSPORT_LOGGERS:
        assert len(logging.getLogger(name).filters) == before[name]
        logging.getLogger(name).error('URL/header %s', SECRET, extra={'fixture': SECRET})
    logging.getLogger('app.fixture').warning('application-status-retained')
    assert SECRET not in caplog.text
    assert 'application-status-retained' in caplog.text


def test_structured_retry_omits_propagated_exception(monkeypatch, capsys, caplog):
    from app.structured_output import get_structured_response
    from app.schemas import ValuationView
    client = MagicMock()
    client.call.side_effect = RuntimeError(SECRET)
    result = get_structured_response('fixture', ValuationView, client, max_retries=2, backoff_factor=0)
    assert isinstance(result, ValuationView)
    assert client.call.call_count == 2
    assert_private(capsys, caplog)
    assert 'RuntimeError' in caplog.text


def test_synthesis_retry_omits_propagated_exception(monkeypatch, capsys, caplog):
    from app.services import thesis_synthesizer as synthesis
    client = MagicMock()
    client.call.side_effect = RuntimeError(SECRET)
    monkeypatch.setattr(synthesis, '_synthesis_client_for_request', lambda: client)
    assert synthesis._call_with_json_enforcement('fixture', 'AAPL', 2, 0) is None
    assert client.call.call_count == 2
    assert_private(capsys, caplog)


@pytest.mark.parametrize('agent', ['valuation', 'macro', 'risk', 'market', 'quality'])
def test_agent_failure_handler_omits_propagated_exception(monkeypatch, capsys, caplog, agent):
    from app.schemas import CompanyContext, RetrievedEvidence
    module = importlib.import_module('app.investment_agents.' + agent + '_agent')
    evidence = [RetrievedEvidence(title='fixture', source='FMP', summary='fixture', timestamp='2026-01-01', relevance_score=1)]
    # Ensure the real exception handler is reached, independent of source filters.
    selector = next(name for name in vars(module) if name.startswith('_filter_'))
    monkeypatch.setattr(module, selector, lambda *a, **k: evidence)
    def fail(*args, **kwargs):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(module, 'get_structured_response', fail)
    result = getattr(module, 'run_' + agent + '_agent')(CompanyContext(ticker='AAPL', company_name='Apple'), evidence)
    assert result.confidence == 0
    # The fallback reaches captured output and the next model prompt, even at
    # confidence zero. Check both boundaries, not only the logger.
    serialized = json.dumps(result.model_dump())
    assert SECRET not in serialized
    assert SECRET[:4] not in serialized
    assert result.overall.endswith('Model request failed.')
    from app.schemas import ValuationView, MacroSensitivity, RiskProfile, MarketContext, QualityAssessment
    from app.services.thesis_synthesizer import _build_synthesis_prompt
    outputs = dict(valuation=ValuationView(), macro=MacroSensitivity(), risk=RiskProfile(),
                   market=MarketContext(), quality=QualityAssessment())
    outputs[agent] = result
    prompt = _build_synthesis_prompt(CompanyContext(ticker='AAPL', company_name='Apple'),
                                     evidence=[], **outputs)
    assert 'Model request failed.' in prompt
    assert SECRET not in prompt
    assert SECRET[:4] not in prompt
    assert_private(capsys, caplog)
    assert 'RuntimeError' in caplog.text


def test_question_answerer_failure_handler(monkeypatch, capsys, caplog):
    from app.investment_agents import question_answerer_agent as agent
    from app.schemas import CompanyContext
    monkeypatch.setattr(agent, 'model_client', SimpleNamespace(call=MagicMock(side_effect=RuntimeError(SECRET))))
    assert agent.run_question_answerer('fixture', 'investment_thesis', CompanyContext(ticker='AAPL', company_name='Apple'), None, []) == ''
    assert_private(capsys, caplog)


def test_evidence_future_error_does_not_echo_request_url(capsys, caplog):
    from app.services.router_service import _collect_investment_evidence
    future = Future()
    future.set_exception(RuntimeError('https://financialmodelingprep.com/?apikey=' + SECRET))
    assert _collect_investment_evidence({'fmp': future}) == {'fmp': []}
    assert_private(capsys, caplog)
    assert 'RuntimeError' in caplog.text
