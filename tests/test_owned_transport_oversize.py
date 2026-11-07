"""What the owned transport reports when a response passes the size limit, offline."""
import httpx
import pytest

from validation import pilot_live
from validation.pilot_live import OwnedHTTPTransport, TransportFailure


class Gate:
    def validate_request(self, *args): pass
    def record_dispatch(self): pass


class Response:
    status_code = 200

    def __init__(self, headers, chunks, close_fails=False):
        self.headers, self.chunks, self.close_fails = httpx.Headers(headers), chunks, close_fails
        self.closed = self.read = 0

    def iter_raw(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    def close(self):
        self.closed += 1
        if self.close_fails:
            raise RuntimeError('invented close failure')


def send(monkeypatch, response):
    monkeypatch.setattr(pilot_live, 'MAX_RESPONSE_BYTES', 8)
    transport = OwnedHTTPTransport()
    transport.close()
    transport.gate = Gate()
    transport._wire = type('Wire', (), {'handle_request': lambda self, request: response})()
    return transport.exchange('GET', 'https://www.sec.gov/Archives/edgar/data/1/000000000000000001/a.htm')


def test_a_declared_excess_stops_before_any_body_is_read(monkeypatch):
    response = Response({'content-length': '9', 'content-type': 'text/html'}, [b'x' * 9])
    with pytest.raises(TransportFailure) as caught:
        send(monkeypatch, response)
    assert caught.value.code == 'response_size' and response.read == 0 and response.closed == 1
    assert caught.value.size_observation == {'limit_bytes': 8, 'declared_bytes': 9, 'bytes_read': 0}


def test_an_undeclared_excess_stops_at_the_chunk_that_passes_the_limit(monkeypatch):
    response = Response({'content-type': 'text/html'}, [b'x' * 5, b'y' * 5, b'z' * 5])
    with pytest.raises(TransportFailure) as caught:
        send(monkeypatch, response)
    assert caught.value.code == 'response_size' and response.read == 2 and response.closed == 1
    assert caught.value.size_observation == {'limit_bytes': 8, 'declared_bytes': None, 'bytes_read': 10}


def test_a_small_declaration_cannot_admit_a_larger_stream(monkeypatch):
    response = Response({'content-length': '3', 'content-type': 'text/html'}, [b'x' * 5, b'y' * 5])
    with pytest.raises(TransportFailure) as caught:
        send(monkeypatch, response)
    assert caught.value.size_observation == {'limit_bytes': 8, 'declared_bytes': 3, 'bytes_read': 10}


@pytest.mark.parametrize('headers, chunks', [({'content-length': '9'}, []), ({}, [b'x' * 9])], ids=['declared', 'stream'])
def test_a_close_that_fails_reports_no_observation_so_it_cannot_be_recovered(monkeypatch, headers, chunks):
    response = Response({**headers, 'content-type': 'text/html'}, chunks, close_fails=True)
    with pytest.raises(TransportFailure) as caught:
        send(monkeypatch, response)
    assert caught.value.code == 'response_size' and caught.value.size_observation is None


def test_other_failures_carry_no_observation(monkeypatch):
    response = Response({'content-length': 'nonsense', 'content-type': 'text/html'}, [])
    with pytest.raises(TransportFailure) as caught:
        send(monkeypatch, response)
    assert caught.value.code == 'protocol_error' and caught.value.size_observation is None
