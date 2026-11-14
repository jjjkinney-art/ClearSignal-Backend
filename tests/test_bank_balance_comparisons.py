"""Deposits and loans appear in a bank's answer only as checked, aligned point-in-time comparisons."""
import pytest

from app.integrity.sec_metric_evidence import comparable_instant_metric_evidence
from app.providers.sec_client import SecFactRecord
from app.services import financial_thesis_foundation as foundation
from app.services import verified_sec_metric_service as service
from app.services.financial_thesis_foundation import (BALANCE_LIMITATION, SECTOR_BALANCE_METRICS, SECTOR_GAPS,
                                                      build_financial_foundation)
from test_financial_thesis_foundation import evidence, reference

CIK, TICKER = '1471265', 'NWBI'
DEPOSITS, LOANS = list(SECTOR_BALANCE_METRICS['bank'])
CONCEPTS = SECTOR_BALANCE_METRICS['bank']


def balance(name, *, current=110, prior=100, current_end='2025-06-30', prior_end='2024-06-30'):
    concept = CONCEPTS[name][0]
    records = []
    for end, value, filed, accn in ((prior_end, prior, '2024-08-01', '24'), (current_end, current, '2025-08-01', '25')):
        accession = f'{int(CIK):010d}-{accn}-000002'
        records.append(SecFactRecord(
            cik=CIK, taxonomy='us-gaap', concept=concept, label=concept, unit='USD', value=value, start=None,
            end=end, filed=filed, form='10-Q', accession=accession,
            filing_url=f'https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace("-", "")}/{accession}-index.htm'))
    return comparable_instant_metric_evidence(records, ticker=TICKER, expected_cik=CIK, concepts=(concept,),
                                              metric_name=name, unit='USD')


def answer(monkeypatch, balances, *, sector='bank'):
    monkeypatch.setattr(foundation, 'issuer_sector', lambda cik: sector)
    items = [evidence('NetIncomeLoss', 'net income', ticker=TICKER, cik=CIK),
             evidence('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow', ticker=TICKER, cik=CIK,
                      ytd=True)] + [item for item in balances if item is not None]
    refs = [reference(item, f'E{n}') for n, item in enumerate(items, start=1)]
    return build_financial_foundation(TICKER, items, refs, expected_cik=CIK)


def balance_rows(result):
    return [row['claim'] for row in result['claims'] if ' as of ' in row['claim']]


def test_aligned_deposits_and_loans_are_shown_with_a_narrowed_gap(monkeypatch):
    result = answer(monkeypatch, [balance(DEPOSITS), balance(LOANS, current=103)])
    rows = balance_rows(result)
    assert rows[0].startswith('NWBI deposits increased 10.0% to ') and 'as of 2025-06-30' in rows[0]
    assert 'as of the comparable prior-year date 2024-06-30' in rows[0]
    assert rows[1].startswith(f'NWBI {LOANS} increased 3.0% to ')
    assert all(row['reference_id'].startswith('E') for row in result['claims'] if ' as of ' in row['claim'])
    assert 'credit quality' in result['unanswered_parts']
    assert SECTOR_GAPS['bank'][0] not in result['unanswered_parts']
    assert BALANCE_LIMITATION in result['answer']
    # Duration comparisons are untouched and still described by their own periods.
    assert 'for the period 2025-04-01 to 2025-06-30' in result['answer']


def test_a_balance_at_another_date_is_not_shown_and_the_gap_stays_whole(monkeypatch):
    result = answer(monkeypatch, [balance(DEPOSITS, current_end='2025-03-31', prior_end='2024-03-31'),
                                  balance(LOANS, current_end='2025-03-31', prior_end='2024-03-31')])
    assert balance_rows(result) == [] and SECTOR_GAPS['bank'][0] in result['unanswered_parts']
    assert BALANCE_LIMITATION not in result['answer']


def test_one_balance_narrows_the_gap_only_by_itself(monkeypatch):
    only_deposits = answer(monkeypatch, [balance(DEPOSITS)])
    assert len(balance_rows(only_deposits)) == 1
    assert 'loan growth and credit quality' in only_deposits['unanswered_parts']
    only_loans = answer(monkeypatch, [balance(LOANS)])
    assert 'deposits and credit quality' in only_loans['unanswered_parts']


def test_a_balance_never_appears_for_another_business_type_or_without_one(monkeypatch):
    items = [balance(DEPOSITS), balance(LOANS)]
    assert balance_rows(answer(monkeypatch, items, sector=None)) == []
    assert balance_rows(answer(monkeypatch, items, sector='insurer')) == []
    plain = answer(monkeypatch, [])
    assert plain['unanswered_parts'].count(SECTOR_GAPS['bank'][0]) == 1 and BALANCE_LIMITATION not in plain['answer']


def test_a_balance_that_does_not_rebuild_exactly_is_not_shown(monkeypatch):
    item = balance(DEPOSITS)
    for update in ({'summary': item.summary.replace('10.0%', '11.0%')}, {'reporting_period_end': '2025-03-31'},
                   {'source_tier': 'secondary'}, {'freshness_status': 'stale'}):
        assert balance_rows(answer(monkeypatch, [item.model_copy(update=update)])) == [], update
    claims = [dict(c) for c in item.verified_claims]
    claims[0]['raw_value'] += 1
    assert balance_rows(answer(monkeypatch, [item.model_copy(update={'verified_claims': claims})])) == []


# --- the request: balance concepts ride in the existing single Company Facts request ----------------------

def _facts(concept, current, prior, *, start=None):
    def record(value, end, filed, accn):
        accession = f'{int(CIK):010d}-{accn}-000002'
        return SecFactRecord(
            cik=CIK, taxonomy='us-gaap', concept=concept, label=concept, unit='USD', value=value,
            start=(f'{end[:4]}-04-01' if start else None), end=end, filed=filed, form='10-Q', accession=accession,
            filing_url=f'https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace("-", "")}/{accession}-index.htm')
    return [record(prior, '2024-06-30', '2024-08-01', '24'), record(current, '2025-06-30', '2025-08-01', '25')]


def _fetch(monkeypatch, question, records):
    seen = {}
    monkeypatch.setattr(service, '_load_ticker_cik_map', lambda: {TICKER: CIK})

    def fake(cik, *, concept_units, user_agent=''):
        seen['concept_units'] = concept_units
        return records
    monkeypatch.setattr(service, 'get_company_fact_records_for_concept_units', fake)
    return service.fetch_verified_metric_evidence(TICKER, question=question), seen['concept_units']


THESIS = f'What is the investment thesis for {TICKER}, what supports it, and what could invalidate it?'
BANK_FACTS = [*_facts('ProvisionForLoanLeaseAndOtherLosses', 8, 9, start='2024-04-01'),
              *_facts('NoninterestIncome', 31, 30, start='2024-04-01'),
              *_facts('Assets', 1_000, 900),
              *_facts('Deposits', 110, 100), *_facts(CONCEPTS[LOANS][0], 103, 100)]


def test_balance_concepts_are_requested_for_a_thesis_but_not_for_a_narrow_question(monkeypatch):
    _, units = _fetch(monkeypatch, THESIS, BANK_FACTS)
    assert ('Deposits', 'USD') in units and (CONCEPTS[LOANS][0], 'USD') in units
    _, narrow = _fetch(monkeypatch, f"Which source supports {TICKER}'s net interest income growth?", BANK_FACTS)
    assert ('Deposits', 'USD') not in narrow


def test_balance_items_are_kept_only_for_an_issuer_that_reports_the_banks_signature(monkeypatch):
    kept, _ = _fetch(monkeypatch, THESIS, BANK_FACTS)
    assert {'us-gaap:Deposits', f'us-gaap:{CONCEPTS[LOANS][0]}'} <= {i.verified_claims[0]['metric'] for i in kept}
    # The same balances without the signature pair are dropped: other issuers' answers are unchanged.
    others = [r for r in BANK_FACTS if r.concept not in {'ProvisionForLoanLeaseAndOtherLosses', 'NoninterestIncome'}]
    dropped, _ = _fetch(monkeypatch, THESIS, others)
    assert not {i.verified_claims[0]['metric'] for i in dropped} & {'us-gaap:Deposits', f'us-gaap:{CONCEPTS[LOANS][0]}'}
