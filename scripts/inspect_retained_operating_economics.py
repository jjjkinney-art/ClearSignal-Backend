"""Offline source inspection, not a production admission or valuation route.

Usage: python SCRIPT CAPTURE_DIR FACTS_ZIP NEW_OUTPUT
"""
def main():
    import sys, socket
    socket.has_ipv6 = False
    def deny(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            raise RuntimeError('external network forbidden in retained source inspection')
    sys.addaudithook(deny)
    sys.path.insert(0, '.')
    import hashlib, json, zipfile
    from pathlib import Path
    from datetime import date
    from app.services.public_document_ingestion import _HTMLTextExtractor
    from app.providers.sec_client import parse_company_fact_records
    from app.services.annual_eps_research import select_annual_eps
    from app.integrity.sec_metric_evidence import comparable_metric_evidence

    capture, facts_zip, output = map(Path, sys.argv[1:4])
    if output.exists():
        raise FileExistsError('inspection refuses an existing output')
    digest = lambda value: hashlib.sha256(value).hexdigest()
    body = (capture / 'npk-filing.html').read_bytes()
    receipt = json.loads((capture / 'npk-filing.html.receipt.json').read_text())
    assert digest(body) == receipt['body_sha256'] == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body) == receipt['body_bytes'] == 1404517
    parser = _HTMLTextExtractor()
    parser.feed(body.decode('utf-8'))
    text = parser.normalized_visible_text(preserve_sec_risk=True)
    assert len(text) == 173081
    assert digest(text.encode()) == 'e8dd751e931eee031f8b0a5174deb32e554f43837d8d107f760b50496fff3ca3'
    with zipfile.ZipFile(facts_zip) as archive:
        manifest = json.loads(archive.read('SHA256SUMS.json'))
        assert len(manifest) == 19
        for name, value in manifest.items():
            assert digest(archive.read(name)) == value
        raw = archive.read('capture/npk-facts.json')
        facts_receipt = json.loads(archive.read('capture/npk-facts.json.receipt.json'))
    assert digest(raw) == facts_receipt['body_sha256'] == '0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'
    assert len(raw) == facts_receipt['body_bytes']
    facts = json.loads(raw)
    spans = []
    def span(role, start, end, window, limitation):
        a, b = text.index(start, *window), text.index(end, *window)
        assert window[0] <= a < b <= window[1]
        quote = text[a:b].strip(' \ufeff')
        b = a + len(quote)
        assert text[a:b] == quote
        spans.append({'role': role, 'start_offset': a, 'end_offset': b,
            'quote': quote, 'quote_sha256': digest(quote.encode()),
            'section_window': list(window), 'limitation': limitation,
            'new_production_admission': False})
    business = (text.index('ITEM 1. BUSINESS'), text.index('ITEM 1A.'))
    liquidity_start = text.index('LIQUIDITY AND CAPITAL RESOURCES 2025 COMPARED TO 2024')
    liquidity = (liquidity_start, text.index('2024 COMPARED TO 2023', liquidity_start))
    note = (text.index('( 11 ) REVENUES:'), text.index('( 12 ) ADVERTISING:'))
    span('working_capital_practices', "The major portion of the Company's sales", '6. Order Backlog', business,
         'Issuer business practices; does not quantify period cash-flow causality or complete issuer economics.')
    span('annual_operating_cash_explanation', 'Cash used in operating activities was $9,137,000',
         'Net cash used in investing activities', liquidity,
         'Management attribution for 2025 versus 2024, including prior-year context; not an explanation of 2026 interim improvement. Cash used is an outflow, not positive cash generation.')
    span('annual_investing_context', 'Net cash used in investing activities',
         'Net cash provided by financing activities', liquidity,
         'Investing flows include security maturities/sales and capital expenditure; not operating cash flow or a complete free-cash-flow valuation.')
    span('line_of_credit_financing_context', 'Net cash provided by financing activities',
         'As a result of the foregoing factors', liquidity,
         'Financing proceeds are not operating cash flow, a period-end debt balance, or evidence of debt completeness. Preserve dividends and treasury-stock context.')
    span('performance_obligations_and_allowances', 'The Company’s revenues are derived',
         "The Company's contracts in the Defense segment", note,
         'Issuer accounting policy and contract practices; preserve variable consideration and allowances. Not all contracts have identical economics.')
    span('defense_contract_economics', "The Company's contracts in the Defense segment",
         'For the Housewares/Small Appliance and Safety segments', note,
         'Named-segment fixed-price economics; retain the limited escalation exception. Does not prove relative advantage, backlog profitability or cost pass-through.')
    span('segment_revenue_recognition', 'For the Housewares/Small Appliance and Safety segments',
         'The timing of revenue recognition', note,
         'Keep shipment/receipt distinctions and Defense title/acceptance plus termination-clause exception together. This describes recognition, not cash receipt or future revenue.')
    span('customer_advances_and_contract_liabilities', 'The timing of revenue recognition',
         'The Company monitors its estimates of variable consideration', note,
         'Advances can precede recognized revenue. Balances, releases and financing-component judgment differ; these are not new orders or the same period cash collected.')

    records = []
    concepts = ('Assets', 'EarningsPerShareBasic', 'EarningsPerShareDiluted',
                'NetCashProvidedByUsedInOperatingActivities', 'PaymentsToAcquirePropertyPlantAndEquipment')
    for concept in concepts:
        unit = 'USD/shares' if concept.startswith('EarningsPerShare') else 'USD'
        records.extend(parse_company_fact_records(facts, concept=concept, unit=unit))
    eps = {}
    for basis in ('basic', 'diluted'):
        item = select_annual_eps(records, ticker='NPK', cik='80172', basis=basis,
                                 currency='USD', boundary=date(2026, 10, 15))
        eps[basis] = {'qualified': item is not None,
                      'verified_claims': item.verified_claims if item else []}
    annual = [r for r in records if r.form in ('10-K', '10-K/A') and r.filed <= '2026-10-15']
    comparisons = {}
    for concept, label in [('NetCashProvidedByUsedInOperatingActivities', 'operating cash flow'),
                           ('PaymentsToAcquirePropertyPlantAndEquipment', 'capital expenditure')]:
        item = comparable_metric_evidence(annual, ticker='NPK', expected_cik='80172',
                    concepts=(concept,), metric_name=label, unit='USD')
        comparisons[label] = {'qualified': item is not None,
            'verified_claims': item.verified_claims if item else []}
    debt_concepts = ('LongTermDebtCurrent', 'LongTermDebtNoncurrent', 'LongTermDebt',
                     'LongTermDebtAndCapitalLeaseObligations', 'ShortTermBorrowings')
    debt_inventory = {c: c in facts.get('facts', {}).get('us-gaap', {}) for c in debt_concepts}
    report = {'date_auckland': '2026-10-24', 'base_commit': '718cb6db44340e07797fb2987c871eb9eddf75f2',
        'kind': 'unblinded_retained_operating_economics_source_inspection',
        'source': {'url': receipt['url'], 'body_sha256': digest(body), 'body_bytes': len(body),
                   'normalized_text_sha256': digest(text.encode()), 'normalized_text_characters': len(text),
                   'offset_basis': 'Unicode characters in full normalized visible text; end exclusive.',
                   'independent_origin_verification': False},
        'facts_sha256': digest(raw), 'facts_archive_entries_verified': len(manifest),
        'diagnostic_as_of': '2026-10-15',
        'contract_source_hashes': {p: digest(Path(p).read_bytes()) for p in (
            'app/services/public_document_ingestion.py', 'app/services/annual_eps_research.py',
            'app/integrity/sec_metric_evidence.py')},
        'candidate_passages': spans, 'existing_annual_eps_contract': eps,
        'annual_financial_comparisons': comparisons, 'selected_standard_debt_concept_presence': debt_inventory,
        'missing_debt_tags_establish_zero_debt': False,
        'valuation_readiness': {'market_price_verified': False, 'security_basis_verified': False,
            'normalized_future_earnings_verified': False, 'investment_boundary_established': False,
            'scenario_assumptions_chosen': False},
        'external_requests': 0, 'model_calls': 0, 'launch_ready': False,
        'limitations': ['Source inspection, not production extraction or independent usefulness acceptance.',
            'Retained annual evidence does not explain later interim outcomes without a matched source bridge.',
            'Conditional valuation arithmetic already exists separately behind disabled-by-default controls; this inspection does not activate or connect it to broad /ask.',
            'No new capture, spending, old-ledger execution, benchmark change, holdout access or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'passages': len(spans), 'annual_eps_qualified': {k:v['qualified'] for k,v in eps.items()},
                      'debt_tag_presence': debt_inventory, 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
