"""Cooperative cancellation of filing tasks and the parent's host readings, offline."""
import json
import os
import threading
import time

import pytest

from app.services.providers import sec_provider
from validation import ordinary_host_readings as host


@pytest.fixture
def observed():
    rows = []
    sec_provider.set_filing_stage_observer(lambda task, stage, cpu: rows.append((task, stage, type(cpu))))
    yield rows
    sec_provider.set_filing_stage_observer(None)


def in_scope(scope, fn, *args, **kwargs):
    return sec_provider.bind_submissions_scope(fn, scope)(*args, **kwargs)


def test_without_a_scope_a_checkpoint_does_nothing(observed):
    sec_provider.filing_checkpoint('thesis_disclosures', 'document_read')
    assert observed == []


def test_a_checkpoint_records_and_continues_until_cancelled(observed):
    scope = sec_provider.SubmissionsRequestScope()
    in_scope(scope, sec_provider.filing_checkpoint, 'thesis_disclosures', 'document_read')
    scope.cancel_tasks(['thesis_disclosures'])
    in_scope(scope, sec_provider.filing_checkpoint, 'filing_metrics', 'document_read')  # another task carries on
    with pytest.raises(sec_provider.FilingTaskCancelled):
        in_scope(scope, sec_provider.filing_checkpoint, 'thesis_disclosures', 'html_parsed')
    assert observed == [('thesis_disclosures', 'document_read', int), ('filing_metrics', 'document_read', int),
                        ('thesis_disclosures', 'cancelled:html_parsed', int)]


def test_an_unobserved_checkpoint_still_cancels_and_records_why(observed):
    scope = sec_provider.SubmissionsRequestScope()
    in_scope(scope, sec_provider.filing_checkpoint, 'thesis_disclosures', 'risk_extraction', observe=False)
    assert observed == []
    scope.cancel_tasks(['thesis_disclosures'])
    with pytest.raises(sec_provider.FilingTaskCancelled):
        in_scope(scope, sec_provider.filing_checkpoint, 'thesis_disclosures', 'risk_extraction', observe=False)
    assert observed == [('thesis_disclosures', 'cancelled:risk_extraction', int)]


def test_a_broad_exception_handler_cannot_absorb_cancellation():
    scope = sec_provider.SubmissionsRequestScope()
    scope.cancel_tasks(['filing_metrics'])

    def task():
        try:
            sec_provider.filing_checkpoint('filing_metrics', 'comparisons_built')
        except Exception:
            return 'absorbed'
    with pytest.raises(sec_provider.FilingTaskCancelled):
        in_scope(scope, task)


def test_a_failing_observer_never_changes_the_outcome():
    def broken(*args):
        raise RuntimeError('invented')
    sec_provider.set_filing_stage_observer(broken)
    try:
        in_scope(sec_provider.SubmissionsRequestScope(), sec_provider.filing_checkpoint, 'filing_metrics', 'document_read')
    finally:
        sec_provider.set_filing_stage_observer(None)


def test_the_document_parser_stops_at_its_stages(monkeypatch):
    from app.services import public_document_ingestion as ingestion
    html = b'<html><body><p>Invented text for a parser stage test.</p></body></html>'

    class Response:
        status_code = 200
        headers = {'Content-Type': 'text/html', 'Content-Length': str(len(html))}
        encoding = 'utf-8'
        def raise_for_status(self): pass
        def iter_content(self, chunk_size=0): yield html
        def close(self): pass
    monkeypatch.setattr(ingestion.requests, 'get', lambda *a, **k: Response())
    monkeypatch.setattr(ingestion.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    seen = []
    url = 'https://www.example.com/a.htm'
    document = ingestion.fetch_public_document(url, checkpoint=seen.append)
    assert document.text_ready and seen[:2] == ['document_read', 'document_decoded'] and 'html_parsed' in seen

    def stop(stage):
        if stage == 'html_parsed':
            raise sec_provider.FilingTaskCancelled('x')
    with pytest.raises(sec_provider.FilingTaskCancelled):
        ingestion.fetch_public_document(url, checkpoint=stop)


def test_the_host_recorder_covers_launch_to_exit_and_writes_owner_only(tmp_path):
    with host.HostReadings(tmp_path, interval=0.05) as readings:
        time.sleep(0.25)
    data = json.loads((tmp_path / 'host_readings.json').read_text())
    assert len(data['readings']) >= 2 and data['readings'][0]['offset_s'] < 1
    assert os.stat(tmp_path / 'host_readings.json').st_mode & 0o077 == 0
    assert readings.summary()['readings'] == len(data['readings'])
    assert not any(t.name == 'host-readings' and t.is_alive() for t in threading.enumerate())


def test_a_failed_host_reading_is_recorded_and_harmless(tmp_path, monkeypatch):
    def broken(parent):
        raise RuntimeError('invented')
    monkeypatch.setattr(host, 'read_host', broken)
    with host.HostReadings(tmp_path, interval=0.01) as readings:
        time.sleep(0.05)
    assert readings.rows and all(row['unreadable'] for row in readings.rows)
    assert readings.summary()['min_cpu_speed_limit'] is None


def test_missing_host_tools_give_missing_values(monkeypatch):
    monkeypatch.setattr(host, '_run', lambda *command: '')
    row = host.read_host(os.getpid())
    assert row['cpu_speed_limit'] is None and row['on_ac_power'] is None and row['worker_cpu_percent'] is None
