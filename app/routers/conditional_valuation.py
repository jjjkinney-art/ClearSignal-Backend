"""Disabled-by-default explicit scenario endpoint, separate from scenario reads."""
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.dependencies.auth import require_user_id
from app.services.conditional_valuation_service import (
    MAX_REQUEST_BYTES, parse_scenario_request, evaluate_requested_scenario,
)
from app.services.conditional_valuation_math import ValuationContractError

router = APIRouter(prefix='/research/valuation-scenarios', tags=['conditional valuation'])


@router.post('')
async def conditional_valuation(request: Request, response: Response = None):
    if settings.conditional_valuation_scenarios_enabled is not True:
        raise HTTPException(status_code=404, detail='Not found')
    require_user_id(request)  # Existing enforcement/bypass policy; before body or providers.
    if settings.enable_data_retrieval is not True:
        raise HTTPException(status_code=503, detail='Evidence retrieval is disabled.')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise HTTPException(status_code=415, detail='JSON body required.')
    lengths = request.headers.getlist('content-length')
    if len(lengths) > 1 or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 8)):
        raise HTTPException(status_code=400, detail='Invalid request length.')
    if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail='Request body too large.')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail='Request body too large.')
        raw.extend(chunk)
    try:
        payload = parse_scenario_request(bytes(raw))
    except ValuationContractError:
        raise HTTPException(status_code=400, detail='Invalid conditional scenario request.') from None
    if response is not None:
        response.headers['Cache-Control'] = 'no-store'
    return await run_in_threadpool(evaluate_requested_scenario, payload)
