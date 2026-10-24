"""Offline source inspection only; no production qualification or answer changes.

Usage: python SCRIPT NPK_CAPTURE PR314_FACTS_ZIP PR292_ZIP NEW_OUTPUT
"""


def main():
    import sys, socket
    socket.has_ipv6 = False
    def deny(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            raise RuntimeError('external network forbidden in retained inspection')
    sys.addaudithook(deny)
    import hashlib, json, re, zipfile
    from datetime import date
    from pathlib import Path
    from xml.etree import ElementTree as ET
    capture, facts_zip, older_zip, output = map(Path, sys.argv[1:5])
    if output.exists():
        raise FileExistsError('inspection refuses an existing output')
    digest = lambda b: hashlib.sha256(b).hexdigest()
    body = (capture / 'npk-filing.html').read_bytes()
    receipt = json.loads((capture / 'npk-filing.html.receipt.json').read_text())
    assert digest(body) == receipt['body_sha256'] == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body) == receipt['body_bytes'] == 1404517
    root = ET.fromstring(body)
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    clean = lambda e: ' '.join(''.join(e.itertext()).split())
    tables = [e for e in root.iter() if local(e) == 'table']
    candidates = [(i + 1, t) for i, t in enumerate(tables) if any(
        f.get('name') == 'us-gaap:NetCashProvidedByUsedInOperatingActivities' for f in t.iter())]
    assert len(candidates) == 1
    number, table = candidates[0]
    resources = {e.get('id'): e for e in root.iter() if local(e) in ('context', 'unit')}
    rows = []
    started = False
    for tr in table.iter():
        if local(tr) != 'tr':
            continue
        cells = [c for c in tr if local(c) in ('td', 'th')]
        texts = [clean(c) for c in cells]
        if texts and texts[0] == 'Net earnings':
            started = True
        if not started:
            continue
        values = []
        for index, cell in enumerate(cells):
            facts = [e for e in cell.iter() if local(e) == 'nonFraction']
            if not facts:
                continue
            assert len(facts) == 1
            fact, = facts
            literal = clean(fact)
            # Display contributions and taxonomy values are separate observations.
            # This reviewed dash is diagnostic zero, not newly supported ingestion.
            assert literal == '-' or re.fullmatch(r'\d{1,3}(?:,\d{3})*|\d+', literal)
            magnitude = 0 if literal == '-' else int(literal.replace(',', ''))
            assert fact.get('scale') == '3'
            assert texts[index] in (literal, '(' + literal)
            negative = texts[index].startswith('(')
            assert texts[index + 1] == (')' if negative else '')
            printed = magnitude * 1000 * (-1 if negative else 1)
            tagged = magnitude * 1000 * (-1 if fact.get('sign') == '-' else 1)
            context = resources[fact.get('contextRef')]
            fields = {local(e): e.text for e in context.iter()
                      if local(e) in ('identifier', 'startDate', 'endDate')}
            assert fields['identifier'] == '0000080172'
            assert not any(local(e) in ('explicitMember', 'typedMember') for e in context.iter())
            unit = resources[fact.get('unitRef')]
            assert [e.text for e in unit.iter() if local(e) == 'measure'] == ['iso4217:USD']
            values.append({'fact_attributes': dict(fact.attrib), 'literal': literal,
                'cell_index': index, 'period_start': fields['startDate'], 'period_end': fields['endDate'],
                'printed_cash_contribution_usd': printed, 'signed_taxonomy_value_usd': tagged,
                'display_sign_differs_from_taxonomy_sign': printed != tagged,
                'context_xml': ET.tostring(context, encoding='unicode')})
        rows.append({'label': texts[0], 'cells': texts, 'observations': values})
        if any(v['fact_attributes']['name'] == 'us-gaap:NetCashProvidedByUsedInOperatingActivities' for v in values):
            break
    components = [r for r in rows[:-1] if r['observations']]
    assert len(components) == 15 and len(rows[-1]['observations']) == 3
    reconciliations = []
    for column, total in enumerate(rows[-1]['observations']):
        entries = [r['observations'][column] for r in components]
        assert all((v['period_start'], v['period_end']) == (total['period_start'], total['period_end']) for v in entries)
        printed_sum = sum(v['printed_cash_contribution_usd'] for v in entries)
        raw_sum = sum(v['signed_taxonomy_value_usd'] for v in entries)
        assert printed_sum == total['printed_cash_contribution_usd']
        reconciliations.append({'period_start': total['period_start'], 'period_end': total['period_end'],
            'printed_component_sum_usd': printed_sum, 'reported_cfo_usd': total['printed_cash_contribution_usd'],
            'residual_usd': printed_sum - total['printed_cash_contribution_usd'],
            'naive_taxonomy_sum_usd': raw_sum,
            'naive_taxonomy_residual_usd': raw_sum - total['signed_taxonomy_value_usd']})
    changes = [{'label': r['label'], 'current_usd': r['observations'][0]['printed_cash_contribution_usd'],
                'prior_usd': r['observations'][1]['printed_cash_contribution_usd'],
                'change_usd': r['observations'][0]['printed_cash_contribution_usd'] - r['observations'][1]['printed_cash_contribution_usd']}
               for r in components]
    delta = reconciliations[0]['reported_cfo_usd'] - reconciliations[1]['reported_cfo_usd']
    assert sum(r['change_usd'] for r in changes) == delta == 44289000
    # Cross-company presence checks cannot reconstruct statement presentation.
    sources = {}
    with zipfile.ZipFile(facts_zip) as archive:
        manifest = json.loads(archive.read('SHA256SUMS.json'))
        assert len(manifest) == 19
        assert all(digest(archive.read(n)) == h for n, h in manifest.items())
        for ticker in ('npk', 'asml'):
            raw = archive.read(f'capture/{ticker}-facts.json')
            rec = json.loads(archive.read(f'capture/{ticker}-facts.json.receipt.json'))
            sources[ticker.upper()] = (raw, rec)
    with zipfile.ZipFile(older_zip) as archive:
        sources['ACHC'] = (archive.read('capture/achc-facts.json'),
                           json.loads(archive.read('capture/achc-facts.json.receipt.json')))
    concepts = sorted({v['fact_attributes']['name'].split(':')[1] for r in components for v in r['observations']
                       if v['fact_attributes']['name'].startswith('us-gaap:')})
    inventories = {}
    expected_hashes = {'NPK': '0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f',
        'ASML': '28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4',
        'ACHC': 'b1d48d703acb9cf3f60aaa852af3b91f4c463c554bf1a3d1bbf0ae55d0e977a3'}
    for ticker, (raw, rec) in sources.items():
        assert digest(raw) == rec['body_sha256'] == expected_hashes[ticker]
        assert len(raw) == rec['body_bytes']
        facts = json.loads(raw)
        gaap = facts.get('facts', {}).get('us-gaap', {})
        cfo = gaap.get('NetCashProvidedByUsedInOperatingActivities', {}).get('units', {})
        annual = [(unit, v) for unit, observations in cfo.items() for v in observations
                  if v.get('form') in ('10-K', '10-K/A', '20-F', '20-F/A')
                  and v.get('filed', '') <= '2026-10-15' and v.get('start')
                  and 330 <= (date.fromisoformat(v['end']) - date.fromisoformat(v['start'])).days <= 380]
        latest = max((v['end'] for _, v in annual), default=None)
        anchors = [(u, v) for u, v in annual if v['end'] == latest]
        inventories[ticker] = {'body_sha256': digest(raw), 'body_bytes': len(raw), 'url': rec['url'],
            'diagnostic_as_of': '2026-10-15', 'latest_annual_cfo_period_end': latest,
            'annual_cfo_candidates': [{'unit': u, **v} for u, v in anchors],
            'selected_concept_presence': {c: c in gaap for c in concepts},
            'complete_cash_table_available_in_review': ticker == 'NPK',
            'cross_company_bridge_qualified': False}
    report = {'kind': 'unblinded_retained_cash_reconciliation_inspection', 'date_auckland': '2026-10-25',
        'base_commit': 'b6a93ba170848e537eaca00b245d77f5248ddc34',
        'source': {'url': receipt['url'], 'body_sha256': digest(body), 'table_number_one_based': number,
                   'table_xml_sha256': digest(ET.tostring(table)), 'independent_origin_verification': False},
        'operating_rows': rows, 'reconciliations': reconciliations, 'component_changes_2025_vs_2024': changes,
        'extension_concept_names_in_reviewed_table': sorted({v['fact_attributes']['name']
            for r in components for v in r['observations'] if not v['fact_attributes']['name'].startswith('us-gaap:')}),
        'reported_cfo_change_usd': delta, 'company_fact_inventories': inventories,
        'facts_archive_entries_verified': len(manifest), 'external_requests': 0, 'model_calls': 0,
        'production_admission_changed': False, 'launch_ready': False,
        'limitations': ['Reviewed retained presentation arithmetic, not a new production source contract or independent factual/usefulness review.',
            'Taxonomy signs and displayed cash contributions differ. Never infer a cash effect by summing raw fact values or by guessing label semantics.',
            'Custom concepts and dash zeros remain diagnostic; no extension to the existing conservative production parser.',
            'Presence of selected concepts and annual CFO candidates does not establish complete cash-flow coverage, uniqueness, comparable periods or a verified cross-company bridge.',
            'Historical annual movements do not establish recurrence, current interim drivers, normalized free cash flow or valuation.',
            'No provider/model call, capture, spending, old-ledger execution, benchmark/holdout access or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'reconciliations': reconciliations, 'component_count': len(components),
                      'cfo_change_usd': delta, 'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
