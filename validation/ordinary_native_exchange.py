"""Worker-facing SEC exchange adapter; no launcher or credential lookup.

Only directory/facts/submissions routes are ready here. Document admission still
requires a reviewed same-issuer filings resolver before worker integration.
"""
from validation.capture_budget import BudgetError, digest
from validation.ordinary_native_ledger import OrdinaryNativeLedger, OrdinaryNativeGate
from validation.ordinary_transport import OrdinaryHTTPTransport


def exchange_sec(owner, wire, *, case_run, stage, route, url, forbidden_values):
    """Reserve, dispatch, retain and settle one immutable SEC GET, or halt.

    The future isolated worker supplies its parent deadline scope and verified
    runtime configuration. Nothing in this helper authenticates operator input.
    """
    ledger = owner.ledger
    if (type(ledger) is not OrdinaryNativeLedger or type(owner.gate) is not OrdinaryNativeGate
            or type(wire) is not OrdinaryHTTPTransport or wire.gate is not owner.gate):
        raise BudgetError('ordinary owned exchange components required')
    with ledger.transaction() as db:
        case = db.execute("SELECT case_id FROM cases WHERE id=? AND status='active'", (case_run,)).fetchone()
    if not case:
        raise BudgetError('active ordinary case required')
    ticker = case[0].split(':')[0]
    record = next(c for c in ledger.policy['case_records'] if c['issuer_id'] == ticker)
    cik = record['expected_cik']
    allowed = {'sec/directory': 'https://www.sec.gov/files/company_tickers.json',
               'sec/facts': f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',
               'sec/submissions': f'https://data.sec.gov/submissions/CIK{cik}.json'}
    if route not in allowed or type(url) is not str or url != allowed[route]:
        ledger.halt('invalid_request')
        raise BudgetError('ordinary source route not admitted')
    owner.active()
    fingerprint = digest({'method': 'GET', 'url': url, 'stage': stage, 'route': route})
    attempt = ledger.reserve(case_run, route, stage=stage, input_bound=0, output_bound=0,
                             request_sha256=fingerprint)
    try:
        # No pacing/retry loop: a refused claim halts this run conservatively.
        ledger.claim_dispatch(attempt, case_run=case_run, route=route, request_sha256=fingerprint,
                              input_bound=0, output_bound=0)
        grant = owner.gate.issue(attempt, fingerprint, route, case_run, stage)
        with owner.gate.exchange(url, grant, fingerprint):
            media, body = wire.exchange('GET', url)
        owner.active()
        ledger.complete_response(attempt, url=url, media_type=media, body=body,
                                 forbidden_values=forbidden_values)
        return media, body
    except BaseException:
        # Stop other work before cleanup. Never expose raw provider exceptions
        # or let a cleanup failure replace the original safe refusal.
        owner.gate.seal()
        try:
            ledger.halt('invalid_response')
        except Exception:
            pass
        raise BudgetError('ordinary owned SEC exchange failed') from None
