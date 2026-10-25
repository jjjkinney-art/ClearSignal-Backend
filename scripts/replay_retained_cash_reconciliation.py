"""Offline parser/reconstruction probe, not an answer or evidence-admission run.

Usage: python SCRIPT NPK_CAPTURE NEW_OUTPUT
"""


def main():
    import sys, socket
    socket.has_ipv6 = False
    def deny(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            raise RuntimeError('external network forbidden in reconciliation replay')
    sys.addaudithook(deny)
    sys.path.insert(0, '.')
    from pathlib import Path
    import hashlib, json
    from app.providers.sec_cash_reconciliation import parse_cash_reconciliations, reconstruct_cash_reconciliation
    capture, output = map(Path, sys.argv[1:3])
    if output.exists():
        raise FileExistsError('replay refuses an existing output')
    body = (capture / 'npk-filing.html').read_bytes()
    receipt = json.loads((capture / 'npk-filing.html.receipt.json').read_text())
    digest = hashlib.sha256(body).hexdigest()
    assert digest == receipt['body_sha256'] == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body) == receipt['body_bytes'] == 1404517
    review_bytes = Path('docs/CASH_RECONCILIATION_SOURCE_MAP_20261025.json').read_bytes()
    assert hashlib.sha256(review_bytes).hexdigest() == 'f570c8faff02bec1feb0a2a476c4186615ed837f2a3b9bc92ef3f44d44360ff9'
    reviewed = json.loads(review_bytes)
    proofs = parse_cash_reconciliations(body.decode('utf-8'), cik='80172')
    assert len(proofs) == 1
    proof, = proofs
    assert proof['source_sha256'] == digest
    assert proof['table_number'] == reviewed['source']['table_number_one_based']
    bridge = reconstruct_cash_reconciliation(proof, cik='80172')
    assert bridge is not None
    numeric_rows = [row for row in reviewed['operating_rows'] if row['observations']]
    assert len(bridge['rows']) == len(numeric_rows) == 16
    for before, after in zip(numeric_rows, bridge['rows']):
        assert before['label'] == after['label']
        for displayed, value in zip(before['observations'], after['values']):
            assert displayed['printed_cash_contribution_usd'] == value['display_contribution']
            assert displayed['signed_taxonomy_value_usd'] == value['signed_taxonomy_value']
            assert displayed['fact_attributes']['id'] == value['fact_id']
            assert displayed['period_start'] == value['period_start']
            assert displayed['period_end'] == value['period_end']
    assert len(bridge['totals']) == 3
    for old, new in zip(reviewed['reconciliations'], bridge['totals']):
        assert old['reported_cfo_usd'] == new['operating_cash_flow']
        assert old['residual_usd'] == new['residual'] == 0
    assert bridge['operating_cash_flow_change'] == reviewed['reported_cfo_change_usd'] == 44289000
    assert [r['change'] for r in bridge['current_vs_prior_component_changes']] == [r['change_usd'] for r in reviewed['component_changes_2025_vs_2024']]
    assert bridge['admitted'] is bridge['source_binding_established'] is bridge['launch_ready'] is False
    report = {'kind': 'retained_complete_cash_reconciliation_parser_probe', 'date_auckland': '2026-10-25',
        'base_commit': 'c1c735a5d25c3f3213d833f5221cf623c79b8c6c',
        'source_body_sha256': digest, 'source_url': receipt['url'], 'source_body_bytes': len(body),
        'source_map_sha256': hashlib.sha256(Path('docs/CASH_RECONCILIATION_SOURCE_MAP_20261025.json').read_bytes()).hexdigest(),
        'parser_sha256': hashlib.sha256(Path('app/providers/sec_cash_reconciliation.py').read_bytes()).hexdigest(),
        'proof': proof, 'reconstructed_bridge': bridge, 'all_reviewed_numeric_rows_equal': True,
        'external_requests': 0, 'model_calls': 0, 'answer_generation_executed': False,
        'production_admission_changed': False, 'launch_ready': False,
        'limitations': ['Separate parser/reconstructor, not wired to ordinary ingestion, producer evidence, final source binding, citations or /ask.',
            'Capsule consistency and exact arithmetic do not authenticate original source or prove component semantic nonoverlap. A valid rehashed substitute capsule can still reconcile; final source binding remains required.',
            'Initial source grammar is bounded to calendar annual, two/three columns, supported number/dash formats, complete operating/investing boundaries and USD/EUR/GBP with no conversion.',
            'Issuer-extension rows are source-labelled contributions only, not independently qualified standalone financial concepts or proof of recurrence.',
            'One exposed retained filing, not current ASML/ACHC reruns, complete-answer usefulness or independent development/holdout acceptance.',
            'No live provider/model requests, capture, spending, old-ledger execution, benchmark/holdout access, settings or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'numeric_rows_equal': len(numeric_rows), 'annual_totals': bridge['totals'],
        'cfo_change': bridge['operating_cash_flow_change'], 'capsule_characters': len(proof['xml']),
        'external_requests': 0, 'model_calls': 0, 'admitted': False}))


if __name__ == '__main__':
    main()
