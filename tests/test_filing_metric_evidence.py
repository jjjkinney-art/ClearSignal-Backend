from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.providers.sec_inline_facts import parse_inline_observations
from app.services import filing_metric_evidence as service
from app.services.financial_thesis_foundation import _rebuild, CORE_METRICS, build_financial_foundation
from app.services.providers.sec_provider import _make_evidence

CIK = '0000320193'
URL = 'https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/company.htm'
CONCEPTS = tuple(c for aliases in CORE_METRICS.values() for c in aliases)


def _xml(concept='Revenues', *, current='1,100', prior='1,000'):
    def context(key, year):
        return f'''<xbrli:context id="{key}"><xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
        </xbrli:entity><xbrli:period><xbrli:startDate>{year}-04-01</xbrli:startDate>
        <xbrli:endDate>{year}-06-30</xbrli:endDate></xbrli:period></xbrli:context>'''
    def fact(key, value):
        return f'''<ix:nonFraction id="f-{key}" name="us-gaap:{concept}" contextRef="{key}"
        unitRef="usd" decimals="-3" format="ixt:num-dot-decimal" scale="3">{value}</ix:nonFraction>'''
    return f'''<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12">
      <head/><body><ix:header><ix:resources>{context('current', 2026)}{context('prior', 2025)}
      <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
      </ix:resources></ix:header>{fact('current', current)}{fact('prior', prior)}</body></html>'''


def _document(xml=None):
    return SimpleNamespace(requested_url=URL, final_url=URL, publisher='SEC EDGAR',
        published_at='2026-07-28', document_type='10-Q', extraction_method='html',
        source_type='regulatory_filing', source_tier='primary', content_hash='a' * 64,
        inline_xbrl_facts=parse_inline_observations(xml or _xml(), cik=CIK, concepts=CONCEPTS))


def _filing():
    return _make_evidence('Company', '10-Q', '2026-07-28', '2026-06-30', URL)


def _items(xml=None):
    return service.evidence_from_filing(_document(xml), _filing(), ticker='AAPL', cik=CIK)


def test_filing_comparison_binds_both_contexts_and_survives_reconstruction():
    item, = _items()
    current, prior = item.verified_claims
    assert (current['raw_value'], prior['raw_value']) == (1100000, 1000000)
    assert 'increased 10.0%' in item.summary
    assert item.reporting_period_start == '2026-04-01'
    assert current['document_ref']['url'] == URL
    assert prior['document_ref']['url'] == URL
    assert current['document_ref']['content_hash'] == 'a' * 64
    assert current['document_ref']['section'] == 'Inline XBRL context current'
    assert current['inline_binding']['fact_id'] == 'f-current'
    assert _rebuild(item, ticker='AAPL', cik=CIK, name='revenue', concepts=CORE_METRICS['revenue'])


@pytest.mark.parametrize('before,after', [
    ('http://fasb.org/us-gaap/2026', 'https://untrusted.example/us-gaap/2026'),
    ('>0000320193<', '>0001675149<'),
    ('http://www.sec.gov/CIK', 'https://untrusted.example/CIK'),
    ('iso4217:USD', 'iso4217:EUR'),
    ('num-dot-decimal', 'num-comma-decimal'),
    ('transformation/2020-02-12', 'transformation/2099-01-01'),
    ('scale="3"', 'scale="99"'),
    ('scale="3"', 'scale="invalid"'),
    ('contextRef="current"', 'contextRef="missing"'),
    ('unitRef="usd"', 'unitRef="missing"'),
    ('id="f-prior"', 'id="f-current"'),
    ('<xbrli:identifier scheme=', '<xbrli:segment/><xbrli:identifier scheme='),
    ('<xbrli:startDate>2026-04-01', '<xbrli:startDate>2027-04-01'),
    ('1,100', '11,00'),
    ('1,100', 'NaN'),
    ('1,100', '(1,100)'),
    ('1,100', '1.2501'),  # A scaled fractional dollar is outside this statement parser.
    ('1,100', '1.000000000000000000000000000000001'),
    ('decimals="-3"', 'decimals="invalid"'),
    ('<ix:nonFraction id=', '<ix:nonFraction tupleRef="t" id='),
    ('name="us-gaap:Revenues"', 'name="other:Revenues"'),
])
def test_unsupported_or_wrong_identity_observations_do_not_make_a_comparison(before, after):
    assert _items(_xml().replace(before, after)) == []


def test_dimensions_nil_duplicate_contexts_and_entity_expansion_fail_closed():
    assert _items(_xml().replace('</xbrli:entity>', '<xbrli:segment/></xbrli:entity>')) == []
    assert _items(_xml().replace('id="prior"', 'id="current"')) == []
    assert _items('<!DOCTYPE html [<!ENTITY n "1100">]>' + _xml()) == []
    assert parse_inline_observations('<html>', cik=CIK, concepts=CONCEPTS) == ()
    assert _items(_xml().replace('<ix:nonFraction id=',
        '<ix:nonFraction xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true" id=')) == []


def test_sign_and_ytd_cashflow_are_preserved_without_quarter_conversion():
    xml = _xml('NetCashProvidedByUsedInOperatingActivities').replace('-04-01', '-01-01')
    xml = xml.replace('id="f-current"', 'id="f-current" sign="-"')
    item, = _items(xml)
    assert item.verified_claims[0]['raw_value'] == -1100000
    assert item.reporting_period_start == '2026-01-01'
    assert 'decreased 210.0%' in item.summary
    assert item.verified_claims[0]['period'].startswith('year-to-date')


def test_conflicting_duplicate_observations_and_incomparable_prior_period_fail_closed():
    xml = _xml()
    additional = '<ix:nonFraction id="conflict" name="us-gaap:Revenues" contextRef="current" unitRef="usd" decimals="-3" scale="3">1200</ix:nonFraction>'
    assert _items(xml.replace('</body>', additional + '</body>')) == []
    assert _items(xml.replace('2025-04-01', '2025-01-01')) == []
    assert _items(xml.replace('2025-06-30', '2024-06-30')) == []
    assert _items(xml.replace('>1,000<', '>0<')) == []


def test_bound_latest_filing_metrics_clear_only_the_supported_coverage_gap(monkeypatch):
    from app.services.financial_reporting_coverage import reporting_coverage
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': CIK})
    revenue, = _items()
    cash, = _items(_xml('NetCashProvidedByUsedInOperatingActivities'))
    foundation = build_financial_foundation('AAPL', [revenue, cash, _filing()], None, expected_cik=CIK)
    assert foundation and 'operating income' in foundation['unanswered_parts']
    assert 'net income' in foundation['unanswered_parts']
    assert reporting_coverage('AAPL', [revenue, cash, _filing()], foundation['selected_items']) == (None, '', [])
    assert len(foundation['claims']) == 2
    assert 'valuation and expected returns' in foundation['unanswered_parts']


@pytest.mark.parametrize('key,value', [('raw_value', 999999), ('period_start', '2026-01-01'),
                                     ('scope', 'segment'), ('label', 'Fake')])
def test_tampered_claim_cannot_enter_financial_foundation(key, value):
    item, = _items()
    item.verified_claims[0][key] = value
    assert _rebuild(item, ticker='AAPL', cik=CIK, name='revenue', concepts=CORE_METRICS['revenue']) is None


@pytest.mark.parametrize('key,value', [('literal', '2,000'), ('scale', 6),
    ('entity_identifier', '1675149'), ('concept', 'ProfitLoss'), ('document_url', URL + '?x=1'),
    ('content_hash', 'bad'), ('context_id', 'bad context'), ('start', '2026-01-01')])
def test_tampered_source_observation_fails_rebinding(key, value):
    item, = _items()
    item.verified_claims[0]['inline_binding'][key] = value
    assert _rebuild(item, ticker='AAPL', cik=CIK, name='revenue', concepts=CORE_METRICS['revenue']) is None


def test_same_period_conflicts_are_visible_and_older_same_concept_is_replaced(monkeypatch):
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': CIK})
    current, = _items()
    older = deepcopy(current)
    # Build a genuinely older bound filing comparison, not edited prose.
    doc = _document(_xml().replace('2026-', '2024-').replace('2025-', '2023-'))
    filing = _filing().model_copy(update={'reporting_period_end': '2024-06-30'})
    older, = service.evidence_from_filing(doc, filing, ticker='AAPL', cik=CIK)
    assert service.merge_latest_filing_metrics([older], [current], ticker='AAPL') == [current]
    assert service.merge_latest_filing_metrics([current], [older], ticker='AAPL') == [current]
    assert service.merge_latest_filing_metrics([current], [deepcopy(current)], ticker='AAPL') == [current]
    conflict, = _items(_xml(current='1,200'))
    merged = service.merge_latest_filing_metrics([current], [conflict], ticker='AAPL')
    assert len(merged) == 2
    assert build_financial_foundation('AAPL', merged, None, expected_cik=CIK) is None


def test_latest_filing_only_no_historical_or_segment_fetch(monkeypatch):
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': CIK})
    calls = []
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **k: [_filing()])
    monkeypatch.setattr(service, 'fetch_public_document', lambda *a, **k: (calls.append((a, k)) or _document()))
    assert len(service.fetch_latest_filing_metrics('AAPL', question='Cite revenue and operating cash flow trends')) == 1
    assert len(calls) == 1 and calls[0][1]['inline_fact_cik'] == CIK
    assert service.fetch_latest_filing_metrics('AAPL', question='Cite revenue', as_of='2025-01-01') == []
    assert service.fetch_latest_filing_metrics('AAPL', question='Cite Services revenue') == []
    assert len(calls) == 1


def test_retrieval_failure_preserves_existing_facts(monkeypatch):
    monkeypatch.setattr(service.sec_provider, '_load_ticker_cik_map', lambda: {'AAPL': CIK})
    monkeypatch.setattr(service.sec_provider, 'fetch_recent_filings', lambda *a, **k: [_filing()])
    def denied(*a, **k):
        raise ValueError('403')
    monkeypatch.setattr(service, 'fetch_public_document', denied)
    assert service.fetch_latest_filing_metrics('AAPL', question='Cite revenue') == []
    current = _items()
    assert service.merge_latest_filing_metrics(current, [], ticker='AAPL') == current
