"""Offline: identity and route the frozen backend chooses for each pre-registered question.

Uses SEC's company_tickers.json as retained in the run-5 ledger (no network), the
classifier output from the pinned frontend, and stubs for the research pipeline and
general agents. Reads no filing, facts or submissions data.

Usage (through guard/run.sh, from the frozen tree):
  route_check6.py <company_tickers.json> <cases.json> <intents.jsonl>
"""
import json
import sys

sys.path.insert(0, '.')
directory_path, cases_path, intents_path = sys.argv[1:4]
directory = json.load(open(directory_path))
from app.schemas import AgentAnswerResponse, QuestionRequest
from app.services import issuer_identity, router_service as router

parsed = issuer_identity.parse_directory(directory)
issuer_identity._load_directory = lambda: parsed
ticker_cik = {r['ticker']: f"{r['cik_str']:010d}" for r in directory.values()}
router._sec_provider._load_ticker_cik_map = lambda: ticker_cik
seen = []


def pipeline(**kwargs):
    seen.append(('research', kwargs['company'].ticker))
    return AgentAnswerResponse(company=kwargs['company'].ticker, request_id='x', agent='stub', agents_used=[], answer={})


router._run_investment_pipeline = pipeline


class GeneralStub(Exception):
    pass


def general(*args, **kwargs):
    seen.append(('general_model_agent', None))
    raise GeneralStub()


for name in dir(router):
    if (name.startswith('_call_') and 'agent' in name.lower()) or name in ('run_finance_agent', 'run_general_agent'):
        setattr(router, name, general)

intents = {row[0]: row[1] for row in map(json.loads, open(intents_path))}
out = []
for case in json.load(open(cases_path)):
    seen.clear()
    found = issuer_identity.discover_company(case['question'], question_text=True)
    discovered = found.ticker if found else None
    try:
        response = router.route_question(QuestionRequest(question=case['question'], company_name='',
                                                         intent=intents[case['case_id']]))
        if not seen:
            dumped = response.model_dump(mode='json')
            routing = dumped.get('routing') or {}
            text = json.dumps(dumped.get('answer') or {})
            seen.append(('returned', f"company={dumped.get('company')!r} pipeline={routing.get('pipeline')} "
                                     f"suggests={'Did you mean' in text} ", ))
    except GeneralStub:
        pass
    except Exception as exc:  # recorded, not hidden
        seen.append(('error', type(exc).__name__))
    route = seen[0] if seen else ('no route recorded', None)
    cik = ticker_cik.get(route[1]) if route[0] == 'research' else None
    verdict = ('correct issuer' if cik == case['expected_cik'] else 'WRONG ISSUER') if route[0] == 'research' else 'no company'
    row = dict(case_id=case['case_id'], intent=intents[case['case_id']], discovered=str(discovered),
               route=route[0], issuer=route[1], verdict=verdict)
    out.append(row)
    print(json.dumps(row))
