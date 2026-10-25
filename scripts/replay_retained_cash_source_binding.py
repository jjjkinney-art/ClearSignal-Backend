"""Offline original-byte binding and row-reference probe; no answer admission.

Usage: python SCRIPT NPK_CAPTURE NEW_OUTPUT
"""
def main():
    import sys, socket
    socket.has_ipv6 = False
    def deny(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            raise RuntimeError('external network forbidden in retained binding replay')
    sys.addaudithook(deny)
    sys.path.insert(0, '.')
    from pathlib import Path
    import hashlib, json
    from app.services.cash_reconciliation_source_binding import bind_cash_reconciliation
    capture, output = map(Path, sys.argv[1:3])
    if output.exists():
        raise FileExistsError('replay refuses an existing output')
    body = (capture / 'npk-filing.html').read_bytes()
    receipt = json.loads((capture / 'npk-filing.html.receipt.json').read_text())
    digest = hashlib.sha256(body).hexdigest()
    assert digest == receipt['body_sha256'] == '8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1'
    assert len(body) == receipt['body_bytes'] == 1404517
    original = Path('docs/CASH_RECONCILIATION_PARSER_REPLAY_20261025.json').read_bytes()
    assert hashlib.sha256(original).hexdigest() == 'a54a93981659fc7a27573594f7324a54da291801c82f80f9fa8299f0fe0255bb'
    previous = json.loads(original)
    bound = bind_cash_reconciliation(previous['proof'], source_body=body, content_hash=digest,
        cik='80172', currency='USD', url=receipt['url'], filed_at='2026-03-13',
        evaluated_at='2026-10-25', title='National Presto Industries 2025 annual cash-flow statement',
        document_type='10-K', availability_status='available', freshness_status='fresh')
    assert bound and bound['bridge'] == {**previous['reconstructed_bridge'], 'source_binding_established': True}
    assert len(bound['row_references']) == 16
    assert bound['admitted'] is bound['launch_ready'] is False
    report = {'kind': 'retained_original_cash_source_binding_and_row_references', 'date_auckland': '2026-10-25',
        'base_commit': 'ef7a376ae34c9958eb214392458c1dc2d993687c',
        'previous_replay_sha256': hashlib.sha256(original).hexdigest(),
        'binding_code_sha256': hashlib.sha256(Path('app/services/cash_reconciliation_source_binding.py').read_bytes()).hexdigest(),
        'result': bound, 'external_requests': 0, 'model_calls': 0, 'answer_generation_executed': False,
        'limitations': ['Exact supplied-source consistency and row references, not independent origin authentication or semantic nonoverlap.',
            'Historical retained source; the replay supplies fresh metadata for this consistency probe, not a fresh network availability check.',
            'Not wired to ordinary ingestion, RetrievedEvidence, final answer admission, /ask or saved research.',
            'No current ASML/ACHC reruns, independent usefulness assessment, live calls, spending, capture, old-ledger execution, benchmark/holdout access or activation.']}
    with output.open('x') as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'source_bound': True, 'row_references': 16, 'admitted': False,
                      'external_requests': 0, 'model_calls': 0}))


if __name__ == '__main__':
    main()
