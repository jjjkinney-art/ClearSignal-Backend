"""Net income: when NetIncomeLoss (attributable to the parent) is older than ProfitLoss (including noncontrolling interests), show the alias with the latest period,
labelled as including noncontrolling interests, behind latest_alias_net_income_enabled (default off).

Development finding (822 seen issuers, offline): 30 of 115 omitted domestic cells were net income where NetIncomeLoss stopped being tagged (Caterpillar 2011, Truist 2009,
Ventas 2011, Eversource 2023) while ProfitLoss runs to 2026. Facts below are constructed and labelled as such; values are small round numbers."""
import pytest

from app.config import settings
from app.providers import sec_client
from app.services import financial_thesis_foundation as foundation
from app.services import verified_sec_metric_service as service

A = '0000000009-26-000001'; B = '0000000009-25-000001'; OLD = '0000000009-12-000001'; OLD2 = '0000000009-11-000001'


class Reply:
    def __init__(self, body): self._body = body
    def raise_for_status(self): pass
    def json(self): return self._body


def ob(start, end, val, accn, filed, form='10-K'): return {'start': start, 'end': end, 'val': val, 'accn': accn, 'fy': int(end[:4]), 'fp': 'FY', 'form': form, 'filed': filed}


def pair(cur, prior, accn=A, paccn=B, year=2025):
    return [ob(f'{year}-01-01', f'{year}-12-31', cur, accn, f'{year + 1}-02-15'), ob(f'{year - 1}-01-01', f'{year - 1}-12-31', prior, paccn, f'{year}-02-15')]


def facts(**concepts):
    body = {'cik': 9, 'entityName': 'Alias Co', 'facts': {'us-gaap': {}}}
    for name, rows in concepts.items():
        body['facts']['us-gaap'][name] = {'label': name, 'units': {'USD': rows}}
    body['facts']['us-gaap']['Assets'] = {'label': 'Assets', 'units': {'USD': [{'end': '2025-12-31', 'val': 1, 'accn': A, 'fy': 2025, 'fp': 'FY', 'form': '10-K', 'filed': '2026-02-15'}]}}
    return body


@pytest.fixture
def served(monkeypatch):
    def install(body):
        calls = []
        monkeypatch.setattr(service, '_load_ticker_cik_map', lambda: {'ALS': '0000000009'})
        monkeypatch.setattr(service, 'facts_not_applicable', lambda cik: None)
        monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: (calls.append(a), Reply(body))[1])
        return calls
    return install


Q = 'What is the investment thesis for ALS, what supports it, and what could invalidate it?'


def net_income(items):
    return [i for i in items if i.verified_claims and i.verified_claims[0]['metric'].split(':')[1] in ('NetIncomeLoss', 'ProfitLoss')]


def stale_parent_current_total():
    return facts(NetIncomeLoss=pair(50, 40, OLD, OLD2, year=2011), ProfitLoss=pair(60, 45), Revenues=pair(1000, 900), OperatingIncomeLoss=pair(120, 100))


def test_flag_off_nothing_changes_and_the_stale_preferred_concept_still_drops_net_income(served, monkeypatch):
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', False, raising=False)
    served(stale_parent_current_total()); assert net_income(service.fetch_verified_metric_evidence('ALS', question=Q)) == []


def test_flag_on_the_alias_with_the_latest_period_is_shown_and_labelled_as_including_noncontrolling_interests(served, monkeypatch):
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False)
    calls = served(stale_parent_current_total()); items = net_income(service.fetch_verified_metric_evidence('ALS', question=Q))
    assert len(items) == 1 and len(calls) == 1
    item = items[0]; current, prior = item.verified_claims
    assert current['metric'] == prior['metric'] == 'us-gaap:ProfitLoss' and (current['raw_value'], prior['raw_value']) == (60, 45)
    assert current['income_attribution'] == 'including_noncontrolling_interests' and 'including noncontrolling interests' in item.title
    assert 'attributable to parent' not in item.title and item.reporting_period_end == '2025-12-31'


def test_an_issuer_current_in_its_preferred_concept_is_unchanged_with_the_flag_on(served, monkeypatch):
    body = facts(NetIncomeLoss=pair(50, 40), ProfitLoss=pair(60, 45), Revenues=pair(1000, 900))
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', False, raising=False); served(body); off = net_income(service.fetch_verified_metric_evidence('ALS', question=Q))
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False); served(body); on = net_income(service.fetch_verified_metric_evidence('ALS', question=Q))
    assert [i.verified_claims for i in on] == [i.verified_claims for i in off] and on[0].verified_claims[0]['metric'] == 'us-gaap:NetIncomeLoss'   # equal periods keep the configured order


def test_values_are_never_joined_across_concepts(served, monkeypatch):
    # the preferred concept has only the current year, the alias only the prior: no complete pair in either, so nothing is built
    body = facts(NetIncomeLoss=[pair(50, 40)[0]], ProfitLoss=[pair(60, 45)[1]], Revenues=pair(1000, 900))
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False); served(body)
    assert net_income(service.fetch_verified_metric_evidence('ALS', question=Q)) == []


def test_a_stale_alias_is_still_dropped_by_the_staleness_window(served, monkeypatch):
    body = facts(NetIncomeLoss=pair(50, 40, OLD, OLD2, year=2011), ProfitLoss=pair(60, 45, OLD, OLD2, year=2012), Revenues=pair(1000, 900))
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False); served(body)
    assert net_income(service.fetch_verified_metric_evidence('ALS', question=Q)) == []


def test_only_net_income_is_affected_and_revenue_and_operating_income_are_identical_with_the_flag_on_and_off(served, monkeypatch):
    body = stale_parent_current_total()
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', False, raising=False); served(body); off = service.fetch_verified_metric_evidence('ALS', question=Q)
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False); served(body); on = service.fetch_verified_metric_evidence('ALS', question=Q)
    other = lambda items: [(i.title, i.summary, i.verified_claims) for i in items if i not in net_income(items)]
    assert other(on) == other(off) and len(on) == len(off) + 1


def test_the_financial_foundation_accepts_it_and_says_including_noncontrolling_interests(served, monkeypatch):
    monkeypatch.setattr(settings, 'latest_alias_net_income_enabled', True, raising=False); served(stale_parent_current_total())
    items = service.fetch_verified_metric_evidence('ALS', question=Q)
    for i in items: i.freshness_status = 'current'
    refs = [{'id': f'E{n}', 'title': i.title.strip()[:300], 'source': i.source.strip()[:120], 'url': i.url, 'published_at': i.timestamp, 'freshness_status': 'current'} for n, i in enumerate(items, 1)]
    built = foundation.build_financial_foundation('ALS', items, refs, expected_cik='0000000009')
    assert built is not None
    text = ' '.join(row['claim'] for row in built['claims']) + ' ' + ' '.join(inf.get('metric', '') + ' ' + inf.get('text', '') for inf in built.get('inferences', []))
    assert 'net income including noncontrolling interests' in text and 'attributable to parent' not in text


def test_the_setting_is_off_by_default():
    from app.config import Settings
    assert Settings().latest_alias_net_income_enabled is False
