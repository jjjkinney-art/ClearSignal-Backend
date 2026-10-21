"""Opt-in /ask scenario turns; exact owned snapshots, no thesis/model pipeline."""
import json
import uuid

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.dependencies.auth import SYSTEM_DEFAULT_USER_ID
from app.progress import progressive_requested, encode_frame, final_frame, PROGRESS_MEDIA_TYPE
from app.services import conditional_valuation_service as scenarios
from app.services.conditional_valuation_math import load_scenario, _object, ValuationContractError
from app.services import research_conversations as conversations


def _response(payload, http_request, *, replayed=False):
    headers = {'Cache-Control': 'no-store'}
    if replayed:
        headers['X-Research-Turn-Replayed'] = 'true'
    if progressive_requested(http_request.headers.get('accept')):
        return Response(encode_frame(final_frame(payload)), media_type=PROGRESS_MEDIA_TYPE, headers=headers)
    return JSONResponse(payload, headers=headers)


def _fresh_input(raw_payload, request):
    payload = scenarios.parse_scenario_request(json.dumps(raw_payload, allow_nan=False).encode())
    ticker, assumptions = payload['ticker'], payload['assumptions']
    if (request.company_name != ticker or request.active_ticker not in (None, ticker)
            or request.as_of not in (None, assumptions['scenario_as_of'])
            or request.intent not in (None, 'company_analysis')
            or request.context is not None or request.research_memory_conversation_id is not None):
        raise ValuationContractError('explicit single-company scenario scope required')
    # Missing assumptions never fall back to inferred prices, rates or a model.
    keys = {'mode', 'scenario_as_of', 'price', 'price_per_underlying_common_share',
            'eps_basis', 'exit_pe', 'horizon', 'distributions'}
    if assumptions['mode'] == 'evaluate_earnings_recovery_scenario':
        keys |= {'target_eps', 'target_fiscal_period'}
    else:
        keys.add('eps_growth_rate' if assumptions['mode'] == 'evaluate_growth_scenario' else 'annual_price_return_rate')
    _object(assumptions, keys, 'explicit assumptions')
    return payload


def _completed_answer(request, payload, evaluation, request_id):
    # The pure evaluator's standalone no-persistence statement is superseded by
    # this wrapper's mandatory conversation transaction, not its source checks.
    evaluation = dict(evaluation)
    evaluation['limitations'] = [line for line in evaluation.get('limitations', [])
        if line != 'No portfolio, conversation, thesis snapshot or alert was written.']
    evaluation['limitations'].append(
        'Saved only as an explicit scenario turn in the selected owner conversation; no portfolio, investment-thesis snapshot or alert is written.')
    explanation = evaluation.get('explanation')
    if evaluation['available'] and isinstance(explanation, dict):
        text = '\n\n'.join([
            'Conditional valuation scenario (partial)',
            '\n'.join(row['text'] for row in explanation['reported_facts']),
            'Explicit hypothetical assumptions\n' + '\n'.join(explanation['explicit_assumptions']),
            explanation['direct_answer'],
            'Unverified requested parts: ' + '; '.join(explanation['unanswered_parts']) + '.',
        ])
    else:
        text = ('Conditional valuation scenario remains unverified. The requested annual EPS evidence '
                'or explicit scenario inputs did not qualify. No forecast, expected return or '
                'buy/sell threshold is established. The supplied assumptions are preserved for review.')
    return {
        'company': payload['ticker'], 'request_id': request_id, 'agents_used': [],
        'routing': {'pipeline': 'owned_conditional_scenario', 'response_mode': 'conditional_scenario',
                    'detected_ticker': payload['ticker'], 'model_calls': 0},
        'answer': {'direct_answer': text, 'general': {'answer': text},
                   'evidence_references': evaluation.get('evidence_references', []),
                   'conditional_valuation': {'request': payload, 'result': evaluation}},
    }


async def handle_owned_scenario_turn(request, http_request, *, user_id):
    """Called only after /ask's real auth/admission/entitlement/quota preflight.

    A request reference denotes the original completed turn. Replays never
    refresh evidence or reinterpret changed inputs, including after UTC rollover.
    Concurrent first requests are not provider-at-most-once; the persisted winner
    is canonical. Unavailable persistence fails closed, with no unsaved answer.
    """
    if (settings.owned_research_scenarios_enabled is not True
            or settings.conditional_valuation_scenarios_enabled is not True):
        raise HTTPException(404, 'Not found')
    if (settings.auth_enabled is not True or user_id == SYSTEM_DEFAULT_USER_ID
            or getattr(http_request.state, 'is_authenticated', False) is not True):
        raise HTTPException(401, 'Authenticated account required.')
    if settings.enable_data_retrieval is not True:
        raise HTTPException(503, 'Evidence retrieval is disabled.')
    if not request.research_conversation_id or not request.research_request_ref:
        raise HTTPException(400, 'An owned conversation and explicit request reference are required.')
    if http_request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'JSON body required.')
    lengths = http_request.headers.getlist('content-length')
    if len(lengths) > 1 or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 8)):
        raise HTTPException(400, 'Invalid request length.')
    if lengths and int(lengths[0]) > scenarios.MAX_REQUEST_BYTES:
        raise HTTPException(413, 'Request body too large.')
    raw = await http_request.body()
    if len(raw) > scenarios.MAX_REQUEST_BYTES:
        raise HTTPException(413, 'Request body too large.')
    try:
        # Parse the original bytes: Pydantic's decoded dictionary cannot detect
        # duplicate keys. Numeric floats/nonfinite constants are not repaired.
        raw_payload = load_scenario(raw.decode('utf-8'))['conditional_valuation']
        if not isinstance(raw_payload, dict):
            raise ValuationContractError('explicit scenario object required')
    except (ValuationContractError, UnicodeDecodeError, KeyError, TypeError):
        raise HTTPException(400, 'Invalid explicit scenario request.') from None

    from app.db.connection import get_session_factory
    try:
        factory = get_session_factory()
        if factory is None:
            raise HTTPException(503, 'Owned research storage is unavailable.')
        async with factory() as session:
            conversation = await conversations.get_conversation(session, user_id=user_id,
                conversation_id=request.research_conversation_id, include_messages=False)
            if conversation is None:
                raise HTTPException(404, 'Research conversation not found.')
            saved = await conversations.get_completed_response(session, user_id=user_id,
                conversation_id=request.research_conversation_id, request_ref=request.research_request_ref)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Owned research storage is unavailable.') from None
    if saved is not None:
        return _response(saved, http_request, replayed=True)
    try:
        payload = _fresh_input(raw_payload, request)
        # A dedicated, explicitly scoped thread avoids silently rebinding a
        # historical or comparative conversation to a different company.
        if conversation['scope']['tickers'] != [payload['ticker']]:
            raise ValuationContractError('single-company conversation scope required')
    except (ValuationContractError, TypeError, ValueError):
        raise HTTPException(400, 'Invalid explicit scenario inputs or company scope.') from None

    try:
        evaluation = await run_in_threadpool(scenarios.evaluate_requested_scenario, payload)
        response = _completed_answer(request, payload, evaluation,
            getattr(http_request.state, 'request_id', None) or str(uuid.uuid4()))
    except Exception:
        raise HTTPException(503, 'Conditional scenario evaluation is unavailable.') from None
    try:
        async with factory() as session:
            staged = await conversations.append_completed_turn(session, user_id=user_id,
                conversation_id=request.research_conversation_id, question=request.question,
                response=response, request_ref=request.research_request_ref)
            if not staged:
                raise HTTPException(404, 'Research conversation not found.')
            canonical = await conversations.get_completed_response(session, user_id=user_id,
                conversation_id=request.research_conversation_id, request_ref=request.research_request_ref)
            if canonical is None:
                raise RuntimeError('completed snapshot missing')
            await session.commit()
        return _response(canonical, http_request, replayed=canonical != response)
    except HTTPException:
        raise
    except Exception:
        # A concurrent writer or ambiguous commit may have completed. One read
        # recovers that original turn; no source dispatch is repeated here.
        try:
            async with factory() as session:
                canonical = await conversations.get_completed_response(session, user_id=user_id,
                    conversation_id=request.research_conversation_id, request_ref=request.research_request_ref)
            if canonical is not None:
                return _response(canonical, http_request, replayed=True)
        except Exception:
            pass
        raise HTTPException(503, 'The scenario turn could not be saved. No completed answer is available.') from None
