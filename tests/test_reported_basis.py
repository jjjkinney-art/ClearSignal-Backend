"""A filer's own presentation, not a US-dollar convenience translation or a long-stale USD figure (as-reported path, default off).

Development finding (822 seen issuers, offline): foreign filers that report in CNY, HKD, TWD, KRW or JPY also tag a US-dollar
convenience translation for the latest year of each filing. (1) The latest balance sheets tie, so every comparison was withheld as
`ambiguous_basis_or_currency`. (2) The USD/EUR path then built comparisons from the translation, whose prior year is a different
filing at a different rate, or from a USD translation that stopped years ago (a 2012 figure for an issuer reporting through 2026).
The statements' own currency carries the prior-year columns in each filing; a translation carries one period per filing."""
from datetime import date

import pytest

from app.services import as_reported_financials as ar
from app.providers.sec_client import SecFactRecord


def rec(**kw):
    base = dict(cik='1', taxonomy='us-gaap', concept='Revenues', label='Revenues', unit='CNY', value=100, start='2024-01-01', end='2024-12-31',
                filed='2025-03-01', form='20-F', accession='0000000001-25-000001', filing_url=None)
    base.update(kw)
    base['filing_url'] = (f"https://www.sec.gov/Archives/edgar/data/{int(base['cik'])}/{base['accession'].replace('-', '')}/{base['accession']}-index.htm")
    return SecFactRecord(**base)


A25, A26 = '0000000001-25-000001', '0000000001-26-000001'


def own_currency(unit='CNY'):
    """Each filing carries the current and the prior-year column in the filer's own currency."""
    out = []
    for concept, cur, prior, prior2 in (('Revenues', 120, 100, 90), ('NetIncomeLoss', 12, 10, 9)):
        out += [rec(concept=concept, unit=unit, value=cur, start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession=A26),
                rec(concept=concept, unit=unit, value=prior, start='2024-01-01', end='2024-12-31', filed='2026-03-01', accession=A26),
                rec(concept=concept, unit=unit, value=prior, start='2024-01-01', end='2024-12-31', filed='2025-03-01', accession=A25),
                rec(concept=concept, unit=unit, value=prior2, start='2023-01-01', end='2023-12-31', filed='2025-03-01', accession=A25)]
    out.append(rec(concept='Assets', unit=unit, value=900, start=None, end='2025-12-31', filed='2026-03-01', accession=A26))
    return out


def translation(unit='USD', rate=7.0):
    """One period per filing: the latest year, at that year's rate."""
    out = []
    for concept, cur, prior in (('Revenues', 120, 100), ('NetIncomeLoss', 12, 10)):
        out += [rec(concept=concept, unit=unit, value=round(cur / rate, 2), start='2025-01-01', end='2025-12-31', filed='2026-03-01', accession=A26),
                rec(concept=concept, unit=unit, value=round(prior / (rate - 0.3), 2), start='2024-01-01', end='2024-12-31', filed='2025-03-01', accession=A25)]
    out.append(rec(concept='Assets', unit=unit, value=130, start=None, end='2025-12-31', filed='2026-03-01', accession=A26))
    return out


def test_the_filers_own_currency_is_chosen_over_a_single_period_translation():
    taxonomy, currency, _ = ar.choose_basis(own_currency() + translation())
    assert (taxonomy, currency) == ('us-gaap', 'CNY')
    evidence, withheld = ar.build_comparisons(own_currency() + translation(), ticker='T', cik='1')
    assert {e.verified_claims[0]['unit'] for e in evidence} == {'CNY'} and len(evidence) == 2 and withheld == [
        {'metric': 'operating income', 'reason': 'concept_not_reported', 'concepts': ['OperatingIncomeLoss'], 'basis': 'US-GAAP', 'currency': 'CNY'},
        {'metric': 'operating cash flow', 'reason': 'concept_not_reported', 'concepts': ['NetCashProvidedByUsedInOperatingActivities'], 'basis': 'US-GAAP', 'currency': 'CNY'}]
    assert all('USD' not in e.summary for e in evidence)


def test_the_resolution_is_symmetric_in_record_order_and_never_uses_the_translation_values():
    records = own_currency() + translation()
    forward = ar.build_comparisons(records, ticker='T', cik='1')[0]
    backward = ar.build_comparisons(list(reversed(records)), ticker='T', cik='1')[0]
    assert [e.summary for e in forward] == [e.summary for e in backward]
    assert forward[0].verified_claims[0]['raw_value'] == 120 and forward[0].verified_claims[1]['raw_value'] == 100


def test_two_bases_that_both_carry_prior_year_columns_stay_ambiguous():
    records = own_currency('CNY') + own_currency('USD')
    assert ar.choose_basis(records)[2] == 'ambiguous_basis_or_currency'
    assert ar.build_comparisons(records, ticker='T', cik='1')[0] == []


def test_two_single_period_bases_stay_ambiguous():
    records = translation('USD') + translation('HKD', rate=1.0)
    assert ar.choose_basis(records)[2] == 'ambiguous_basis_or_currency'


def test_a_translation_with_some_prior_columns_is_still_not_primary_below_the_threshold():
    share = ar._column_share([r for r in own_currency() + translation() if r.form.startswith('20-F')], ('us-gaap', 'USD'))
    assert share == 0.0
    assert ar._column_share([r for r in own_currency() if r.form.startswith('20-F')], ('us-gaap', 'CNY')) == 1.0


def usd_main(end='2025-12-31', value=17, unit='USD'):
    cur = rec(concept='Revenues', unit=unit, value=value, start=f'{end[:4]}-01-01', end=end, filed=f'{int(end[:4]) + 1}-03-01', accession=A26)
    prior = rec(concept='Revenues', unit=unit, value=value - 2, start=f'{int(end[:4]) - 1}-01-01', end=f'{int(end[:4]) - 1}-12-31', filed=f'{end[:4]}-03-01', accession=A25)
    item, why = ar.evidence_from_pair(cur, prior, ticker='T', expected_cik='1', metric_name='revenue')
    assert why is None
    return [item]


def response(records):
    """A Company Facts response holding exactly these records (the replacement reads it through the shared parser)."""
    facts = {}
    for r in records:
        node = facts.setdefault(r.taxonomy, {}).setdefault(r.concept, {'label': r.label, 'units': {}})
        node['units'].setdefault(r.unit, []).append({'start': r.start, 'end': r.end, 'val': r.value, 'accn': r.accession, 'fy': int(r.end[:4]), 'fp': 'FY',
                                                     'form': r.form, 'filed': r.filed})
    return {'cik': 1, 'entityName': 'T', 'facts': facts}


def test_a_usd_translation_is_replaced_by_the_filers_own_currency():
    data = response(own_currency() + translation())
    out = ar.reported_basis_replacement(usd_main(), data, 'T', '1')
    assert out is not None and {c['unit'] for e in out[0] for c in e.verified_claims} == {'CNY'}


def test_a_long_stale_usd_figure_is_replaced_by_a_newer_own_currency_period_even_in_the_same_currency_family():
    data = response(own_currency('JPY'))
    out = ar.reported_basis_replacement(usd_main(end='2012-12-31'), data, 'T', '1')
    assert out is not None and out[0][0].reporting_period_end == '2025-12-31'


def test_the_existing_comparison_is_kept_when_the_currency_and_the_period_agree():
    data = response(own_currency('USD'))
    assert ar.reported_basis_replacement(usd_main(end='2025-12-31'), data, 'T', '1') is None


def test_a_newer_interim_main_path_comparison_is_kept():
    data = response(own_currency('USD'))
    from types import SimpleNamespace
    main = [SimpleNamespace(reporting_period_end='2026-06-30', verified_claims=[{'unit': 'USD'}, {'unit': 'USD'}])]
    assert ar.reported_basis_replacement(main, data, 'T', '1') is None


def test_an_ambiguous_basis_keeps_the_existing_comparison_and_nothing_is_replaced_without_data():
    data = response(own_currency('CNY') + own_currency('USD'))
    assert ar.reported_basis_replacement(usd_main(), data, 'T', '1') is None
    assert ar.reported_basis_replacement(usd_main(), None, 'T', '1') is None
    assert ar.reported_basis_replacement([], response(own_currency()), 'T', '1') is None


def test_the_replacement_respects_the_as_of_boundary():
    data = response(own_currency() + translation())
    assert ar.reported_basis_replacement(usd_main(), data, 'T', '1', boundary=date(2025, 6, 30)) is None or all(
        c['period_end'] <= '2024-12-31' for e in ar.reported_basis_replacement(usd_main(), data, 'T', '1', boundary=date(2025, 6, 30))[0] for c in e.verified_claims)


# --- through the service: one request, the flag decides -------------------------------------------------

from app.config import settings
from app.providers import sec_client
from app.services import verified_sec_metric_service as service


class Reply:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def usd_translation_filer():
    """A CNY filer (own columns in each 20-F) whose USD translation is one period per filing."""
    return response(own_currency() + translation())


@pytest.fixture
def served(monkeypatch):
    calls = []

    def install(body):
        monkeypatch.setattr(service, '_load_ticker_cik_map', lambda: {'TST': '0000000001'})
        monkeypatch.setattr(service, 'facts_not_applicable', lambda cik: None)
        monkeypatch.setattr(sec_client.requests, 'get', lambda *a, **k: (calls.append(a), Reply(body))[1])
        return calls
    return install


QUESTION = 'What is the investment thesis for TST, what supports it, and what could invalidate it?'


def test_flag_off_the_translation_is_still_served_exactly_as_before(served, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', False, raising=False)
    calls = served(usd_translation_filer())
    items = service.fetch_verified_metric_evidence('TST', question=QUESTION)
    assert items and {c['unit'] for i in items for c in i.verified_claims} == {'USD'} and len(calls) == 1


def test_flag_on_the_filers_own_currency_replaces_the_translation_with_the_same_single_request(served, monkeypatch):
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    calls = served(usd_translation_filer())
    items = service.fetch_verified_metric_evidence('TST', question=QUESTION)
    assert items and {c['unit'] for i in items for c in i.verified_claims} == {'CNY'} and len(calls) == 1
    assert all('no currency conversion was applied' in i.summary for i in items)


def test_flag_on_an_issuer_the_existing_path_serves_in_its_own_currency_is_unchanged(served, monkeypatch):
    body = response(own_currency('USD'))
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', False, raising=False)
    served(body)
    off = service.fetch_verified_metric_evidence('TST', question=QUESTION)
    monkeypatch.setattr(settings, 'as_reported_financials_enabled', True, raising=False)
    served(body)
    on = service.fetch_verified_metric_evidence('TST', question=QUESTION)
    assert off and [i.summary for i in on] == [i.summary for i in off] and [i.verified_claims for i in on] == [i.verified_claims for i in off]
