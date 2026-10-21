"""Retained PR314 bytes -> signed /ask explicit scenario -> owned save/retry.

Offline only: injected directory, test JWTs/SQLite and saved provider responses.
"""

def main():
    import sys, socket
    socket.has_ipv6 = False
    blocked = []
    def guard(event, args):
        if event.startswith('socket.') and not (event == 'socket.__new__' and args[1] == socket.AF_UNIX):
            blocked.append(event)
            raise RuntimeError('external network forbidden in owned scenario replay')
    sys.addaudithook(guard)
    sys.path[:0] = ['.', 'tests']
    import asyncio, json, hashlib, zipfile, tempfile
    from pathlib import Path
    from datetime import date
    from copy import deepcopy
    from contextlib import redirect_stdout, redirect_stderr
    from io import StringIO
    from fractions import Fraction
    import httpx, pytest
    from app.providers import sec_client
    from app.services import conditional_valuation_service as svc
    from app.services.issuer_identity import parse_directory
    from test_owned_scenario_turns import owned_scenarios, reopen
    from test_conditional_valuation_account_boundary import boundary, approve, token, bearer, SUBJECT_B, EMAIL_B
    real_records = sec_client.get_company_fact_records_for_concept_units
    hashes = {'ASML': '28be6fd0f5608350ec396ae5d5097e45da95f4f29ad3fbd19aac328a15cce3d4',
              'NPK': '0f512e8670882f4d201d24252e31ab457f512be1aa6ac9b7243d3b8ec820e19f'}
    ciks = {'ASML': 937966, 'NPK': 80172}
    with zipfile.ZipFile(sys.argv[1]) as archive:
        sums = json.loads(archive.read('SHA256SUMS.json'))
        assert all(hashlib.sha256(archive.read(n)).hexdigest() == h for n, h in sums.items())
        bodies = {t: archive.read('capture/' + t.lower() + '-facts.json') for t in hashes}
        for t, body in bodies.items():
            receipt = json.loads(archive.read('capture/' + t.lower() + '-facts.json.receipt.json'))
            assert hashlib.sha256(body).hexdigest() == hashes[t] == receipt['body_sha256']
            assert len(body) == receipt['body_bytes']
    gets = []
    def saved_get(url, **kwargs):
        ticker = next((t for t, c in ciks.items() if url == f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json'), None)
        assert ticker is not None, 'unexpected URL'
        gets.append(url)
        return httpx.Response(200, content=bodies[ticker], request=httpx.Request('GET', url))
    def operand(value, unit):
        return {'value': value, 'unit': unit, 'provenance': {'kind': 'user_assumption',
            'reference': 'Invented offline demonstration, not observed price or earnings forecast'}}
    def inputs(ticker, basis, currency, mode):
        a = {'mode': mode, 'scenario_as_of': '2026-10-20', 'distributions': 'excluded',
            'price_per_underlying_common_share': True, 'price': operand('100', currency + '/share'),
            'exit_pe': operand('20', 'x'), 'horizon': operand(2, 'years'),
            'eps_basis': {'issuer': ticker, 'currency': currency, 'accounting': 'gaap',
                'adjustment_definition': 'none', 'share_basis': basis, 'period_basis': 'fiscal_year',
                'earnings_scope': 'total_operations', 'split_basis': 'User assumes identical unconverted underlying common-share basis'}}
        if mode == 'evaluate_growth_scenario': a['eps_growth_rate'] = operand('0', 'annual_fraction')
        elif mode == 'solve_required_earnings_growth': a['annual_price_return_rate'] = operand('0', 'annual_fraction')
        else:
            a['target_eps'] = operand('4', currency + '/shares')
            a['target_fiscal_period'] = {'start': '2027-01-01', 'end': '2027-12-31'}
        return {'ticker': ticker, 'assumptions': a}
    async def run(mp, tmp):
        account_gen = boundary.__wrapped__(mp, tmp)
        account = await anext(account_gen)
        owned_gen = owned_scenarios.__wrapped__(account, mp)
        client, maker, _, models, _ = await anext(owned_gen)
        results = []
        try:
            mp.setattr(svc, 'get_company_fact_records_for_concept_units', real_records)
            mp.setattr(svc, '_current_date', lambda: date(2026, 10, 20))
            mp.setattr(svc, '_load_directory', lambda: parse_directory({str(i):
                {'ticker': t, 'title': 'Injected frozen directory ' + t, 'cik_str': c}
                for i, (t, c) in enumerate(ciks.items())}))
            mp.setattr(sec_client.requests, 'get', saved_get)
            await approve(maker, EMAIL_B)
            ha, hb = bearer(token()), bearer(token(SUBJECT_B, EMAIL_B))
            combinations = [(t, b, c, m, value) for t, b, c, value in
                [('ASML', 'basic', 'EUR', '24.73'), ('ASML', 'diluted', 'EUR', '24.71'), ('NPK', 'basic', 'USD', '4.63')]
                for m in ('evaluate_growth_scenario', 'solve_required_earnings_growth')]
            combinations += [('NPK', 'diluted', 'USD', 'evaluate_growth_scenario', None),
                ('ASML', 'basic', 'USD', 'evaluate_growth_scenario', None),
                ('ASML', 'basic', 'EUR', 'evaluate_earnings_recovery_scenario', None)]
            for index, (t, basis, currency, mode, value) in enumerate(combinations):
                created = await client.post('/research/conversations', json={'title': 'Retained explicit scenario', 'tickers': [t]}, headers=ha)
                assert created.status_code == 201
                cid = created.json()['id']
                q = {'company_name': t, 'question': 'Explain this explicit hypothetical scenario.',
                    'research_conversation_id': cid, 'research_request_ref': f'scenario-retained-{index}',
                    'conditional_valuation': inputs(t, basis, currency, mode)}
                before = deepcopy(q)
                response = await client.post('/ask', json=q, headers=ha)
                assert response.status_code == 200, response.text
                data = response.json(); answer = data['answer']; result = answer['conditional_valuation']['result']
                assert data['routing']['response_mode'] == 'conditional_scenario' and not models
                assert 'investment_thesis' not in answer
                assert answer['conditional_valuation']['request'] == before['conditional_valuation']
                assert result['available'] == (value is not None)
                if value is not None:
                    eps = result['scenario']['source_eps']
                    assert eps['value'] == value and eps['currency'] == currency and eps['share_basis'] == basis
                    assert answer['evidence_references'] == result['evidence_references']
                    assert eps['reference_id'] in {r['id'] for r in answer['evidence_references']}
                    assert result['explanation']['direct_answer'] in answer['direct_answer']
                    factor = Fraction(result['scenario']['values']['terminal_price_factor'])
                    if mode == 'evaluate_growth_scenario':
                        assert abs(factor - Fraction(value) / 5) < Fraction(1, 10**25)
                    else: assert abs(factor - 1) < Fraction(1, 10**25)
                else:
                    assert not answer['evidence_references'] and 'remains unverified' in answer['direct_answer']
                saved = await reopen(client, cid, ha)
                assert saved['messages'][1]['displayed_snapshot']['response'] == data
                assert saved['messages'][1]['text'] == answer['direct_answer']
                assert saved['messages'][1]['displayed_snapshot']['thesis_memory_artifact']['status'] == 'unavailable'
                count = len(gets)
                q['conditional_valuation']['assumptions']['price']['value'] = '999'
                retry = await client.post('/ask', json=q, headers=ha)
                assert retry.json() == data and retry.headers['x-research-turn-replayed'] == 'true'
                assert len(gets) == count and len((await reopen(client, cid, ha))['messages']) == 2
                assert (await client.get('/research/conversations/' + cid, headers=hb)).status_code == 404
                assert (await client.post('/ask', json=before, headers=hb)).status_code == 404
                assert len(gets) == count
                results.append({'ticker': t, 'basis': basis, 'currency': currency, 'mode': mode,
                    'available': result['available'], 'exact_snapshot_preserved': True,
                    'changed_input_retry_exact_no_fetch': True, 'foreign_read_and_dispatch_denied': True,
                    'thesis_memory_artifact': 'unavailable', 'response': data})
            assert len(gets) == 9 and not models and not blocked
        finally:
            await owned_gen.aclose(); await account_gen.aclose()
        return results
    with tempfile.TemporaryDirectory(prefix='owned-scenario-offline-') as tmp, pytest.MonkeyPatch.context() as mp:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            cases = asyncio.run(run(mp, Path(tmp)))
    report = {'base_commit': '35d3cb299283367359aab0d97fb648ea1ae69fe6',
        'kind': 'retained_body_signed_ask_owned_scenario_save_reopen_retry',
        'archive_hashes_verified': len(sums), 'body_hashes': hashes,
        'external_requests': 0, 'model_calls': 0, 'saved_source_substitutions': len(gets),
        'successful_scenarios': 6, 'explicit_gaps': 3, 'cases': cases,
        'limitations': ['Local invented HS256 JWTs, beta accounts and disposable SQLite, not production auth/database/browser acceptance.',
            'Current identity and UTC boundary are injected; retained bodies use the actual provider parser, producer and scenario evaluators.',
            'Price, future earnings, growth, multiple, horizon and share/split assertions are explicit invented inputs, not observed facts or forecasts.',
            'Production flags remain off. No UI assumption-entry form, live execution, spending or broad-company quality acceptance is established.',
            'Historical run records are untouched and complete inventories were not independently revalidated here.']}
    with Path(sys.argv[2]).open('x') as output: json.dump(report, output, indent=2, allow_nan=False)
    print(json.dumps({'scenarios': 6, 'gaps': 3, 'exact_saved_reopen_and_retry': len(cases),
        'foreign_read_and_dispatch_denials': 2 * len(cases), 'external_requests': 0, 'model_calls': 0}))

if __name__ == '__main__':
    main()
