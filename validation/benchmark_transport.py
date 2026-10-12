"""Cooperative fixture-only SDK transport. Not a Python sandbox or live adapter."""
from dataclasses import dataclass
import hashlib
import json
from threading import Lock

import httpx

from validation.capture_budget import AttemptLedger, BudgetError, digest


@dataclass(frozen=True)
class FixtureResponse:
    status: int
    body: bytes
    input_units: int | None
    output_units: int | None
    location: str | None = None


class BenchmarkTransport(httpx.BaseTransport):
    """Own an exact MockTransport with a private, fixed handler, never a callback.

    Input units are complete JSON body BYTES, not actual model tokens. Prices
    must be synthetic and explicitly supplied under fixture-bytes/<model>.
    No external transport, handler, credential loader or production flag exists.
    Trusted callers/storage are required; arbitrary Python can bypass anything.
    """
    def __init_subclass__(cls, **kwargs):
        raise TypeError('fixture transport subclasses are unsupported')

    def __init__(self, ledger, case_run, *, model, responses):
        if type(ledger) is not AttemptLedger or type(model) is not str or not model:
            raise BudgetError('exact ledger and explicit fixture model required')
        if type(responses) is not tuple or not responses:
            raise BudgetError('immutable fixture response tuple required')
        for item in responses:
            if (type(item) is not FixtureResponse or type(item.body) is not bytes
                    or type(item.status) is not int or not 100 <= item.status <= 599
                    or (item.location is not None and type(item.location) is not str)):
                raise BudgetError('plain immutable response fixtures required')
        self._ledger, self._case_run, self._model = ledger, case_run, model
        self._responses = responses
        self._lock = Lock()
        self._index = 0
        # Callers cannot provide a MockTransport subclass or arbitrary handler.
        self._mock = httpx.MockTransport(self._respond)

    def _respond(self, request):
        fixture = self._responses[self._index]
        return httpx.Response(fixture.status, content=fixture.body,
                              headers={'location': fixture.location} if fixture.location else {})

    def handle_request(self, request):
        with self._lock:
            if type(request) is not httpx.Request or type(request.stream) is not httpx.ByteStream:
                raise BudgetError('exact HTTPX request with in-memory byte stream required')
            if (request.method != 'POST' or str(request.url) != 'https://fixture.invalid/v1/chat/completions'):
                raise BudgetError('unknown fixture operation or redirect route')
            body = request.read()
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                raise BudgetError('invalid fixture JSON') from None
            if (type(payload) is not dict or set(payload) != {'model', 'messages', 'max_tokens'}
                    or payload['model'] != self._model or type(payload['messages']) is not list):
                raise BudgetError('unknown model, billing units or request fields')
            for message in payload['messages']:
                if (type(message) is not dict or set(message) != {'role', 'content'}
                        or message['role'] not in ('system', 'user', 'assistant')
                        or type(message['content']) is not str):
                    raise BudgetError('only plain text fixture messages supported')
            if self._index >= len(self._responses):
                raise BudgetError('fixture responses exhausted')
            # Clone before binding; dispatch never reads mutable caller state again.
            frozen = httpx.Request(request.method, str(request.url),
                                   headers=list(request.headers.multi_items()), content=body)
            fingerprint = digest({'method': frozen.method, 'url': str(frozen.url),
                                  'headers': list(frozen.headers.multi_items()),
                                  'body_sha256': hashlib.sha256(body).hexdigest()})
            binding = dict(case_run=self._case_run, route='fixture-bytes/' + self._model,
                           input_bound=len(body), output_bound=payload['max_tokens'],
                           request_sha256=fingerprint)
            attempt = self._ledger.reserve(**binding)
            self._ledger.claim_dispatch(attempt, **binding)
            fixture = self._responses[self._index]
            try:
                response = self._mock.handle_request(frozen)
            finally:
                # No replay after a claimed dispatch, including an ambiguous failure.
                self._index += 1
            self._ledger.settle(attempt, input_tokens=fixture.input_units,
                                output_tokens=fixture.output_units)
            return response
