"""Collection deadlines and late-result isolation; no sleeps or network calls."""
from concurrent.futures import Future

import pytest

from app.services import router_service as service


@pytest.mark.parametrize('elapsed', [10, 12])
def test_source_view_retains_document_result_but_not_late_unrelated_provider(monkeypatch, elapsed):
    futures = {key: Future() for key in ('sec_metrics', 'thesis_disclosures', 'filing_metrics', 'news_co')}
    evidence = [object()]
    waits = []
    clock = iter([0, elapsed])
    monkeypatch.setattr(service.time, 'monotonic', lambda: next(clock))

    def wait(items, *, timeout, return_when):
        waits.append((items, timeout))
        if len(waits) == 1:
            futures['sec_metrics'].set_result(['metrics'])
        else:
            futures['thesis_disclosures'].set_result(evidence)
            futures['filing_metrics'].set_result(['filing'])
            futures['news_co'].set_result(['late unrelated evidence'])

    monkeypatch.setattr(service, '_cf_wait', wait)
    result = service._collect_investment_evidence(futures, source_evidence_view=True)
    assert result['sec_metrics'] == ['metrics']
    assert result['thesis_disclosures'] is evidence
    assert result['filing_metrics'] == ['filing']
    assert result['news_co'] == []
    assert waits[0][1] == 10 and waits[1][1] == 20 - elapsed
    assert set(waits[1][0]) == {futures['thesis_disclosures'], futures['filing_metrics']}


def test_model_generated_path_keeps_ten_second_cap_and_no_document_grace(monkeypatch, caplog):
    future = Future()
    waits = []
    monkeypatch.setattr(service, '_cf_wait', lambda items, **kw: waits.append(kw['timeout']))
    result = service._collect_investment_evidence({'thesis_disclosures': future})
    assert result == {'thesis_disclosures': []}
    assert waits == [10] and '>10s wall time' in caplog.text


def test_unfinished_document_and_failed_provider_remain_gaps_after_grace(monkeypatch, caplog):
    hung, failed = Future(), Future()
    failed.set_exception(RuntimeError('synthetic provider failure'))
    clock = iter([0, 10])
    monkeypatch.setattr(service.time, 'monotonic', lambda: next(clock))
    waits = []
    monkeypatch.setattr(service, '_cf_wait', lambda items, **kw: waits.append(kw['timeout']))
    result = service._collect_investment_evidence(
        {'thesis_disclosures': hung, 'sec_metrics': failed}, source_evidence_view=True)
    assert result == {'thesis_disclosures': [], 'sec_metrics': []}
    assert waits == [10, 10] and '>20s wall time' in caplog.text


def test_completed_document_does_not_add_grace_wait(monkeypatch):
    future = Future()
    future.set_result(['document'])
    waits = []
    monkeypatch.setattr(service, '_cf_wait', lambda items, **kw: waits.append(kw['timeout']))
    result = service._collect_investment_evidence({'thesis_disclosures': future}, source_evidence_view=True)
    assert result == {'thesis_disclosures': ['document']} and waits == [10]


def test_source_view_without_document_tasks_keeps_original_provider_limit(monkeypatch):
    waits = []
    monkeypatch.setattr(service, '_cf_wait', lambda items, **kw: waits.append(kw['timeout']))
    assert service._collect_investment_evidence({'news_co': Future()}, source_evidence_view=True) == {'news_co': []}
    assert waits == [10]
