"""Invented, internal fixtures only. No external fixture files or callbacks."""
import json

from validation.pilot_policy import MODEL_SNAPSHOT


SYNTHETIC_KEY = 'invented-integrated-pilot-key-canary'
SYNTHETIC_CONTACT = 'Offline pilot fixture contact@example.invalid'
SECRET_CANARIES = (SYNTHETIC_KEY, SYNTHETIC_CONTACT, 'invented-response-secret-canary')
SCENARIOS = frozenset({
    'happy', 'model_429', 'model_500', 'missing_usage', 'excess_usage',
    'model_mismatch', 'tier_mismatch', 'unknown_usage', 'secret_reflection',
    'sec_redirect', 'sec_identity_mismatch', 'unknown_sec_route',
    'unknown_model_route', 'oversize_input', 'sdk_copy_retry', 'sdk_retry_drift',
    'configuration_drift', 'dotenv_drift', 'evidence_timeout', 'agent_timeout',
    'synthesis_timeout', 'partial_pool_failure', 'crash_after_claim',
    'concurrency', 'duplicate_stage', 'application_retry_drift', 'request_secret',
    'socket_attempt', 'unknown_dns', 'sdk_copy_valid',
    'custom_request_header', 'concurrent_usage_failure',
    'sec_post', 'sec_body', 'sec_response_identity_mismatch',
    'agent_submit_failure', 'synthesis_submit_failure', 'synthesis_running_submit_failure',
    'evidence_constructor_failure', 'agents_constructor_failure', 'synthesis_constructor_failure',
})


def document_url(identity):
    cik = identity['cik']
    return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{cik}26000001/report.htm'


def sec_fixture(route, identity, identities):
    if route == 'sec/directory':
        data = {str(i): {'ticker': item['ticker'], 'cik_str': int(item['cik']),
                         'title': item['company_name']} for i, item in enumerate(identities)}
    elif route == 'sec/submissions':
        form = '20-F' if identity['ticker'] == 'ASML' else '10-K'
        data = {'cik': identity['cik'], 'name': identity['company_name'],
                'filings': {'recent': {
                    'form': [form], 'filingDate': ['2026-03-01'],
                    'reportDate': ['2025-12-31'], 'items': [''],
                    'accessionNumber': [identity['cik'] + '-26-000001'],
                    'primaryDocument': ['report.htm'],
                }}}
    elif route == 'sec/facts':
        # Empty facts intentionally do not pretend to replace missing financial
        # coverage. The real facts HTTP and parsing paths still execute.
        data = {'cik': int(identity['cik']), 'entityName': identity['company_name'], 'facts': {}}
    else:
        title = identity['company_name']
        return ('text/html', f'''<html><head><title>Synthetic fixture</title></head><body>
<h1>{title} — synthetic offline annual filing fixture</h1>
<h2>Item 1. Business</h2><p>{title} manufactures products and provides services to customers.
This invented document exists only to exercise local parser and transport paths.</p>
<h2>Item 1A. Risk Factors</h2><p>Customer demand and operating costs may change.
This is synthetic test material and supplies no real issuer evidence.</p>
<h2>Item 2. Properties</h2><p>End of the synthetic business and risk sections.</p>
</body></html>'''.encode())
    return 'application/json', json.dumps(data).encode()


def model_fixture(stage, identity):
    if stage == 'question_answerer':
        content = 'Synthetic offline answer used only to exercise the existing investment pipeline.'
    elif stage == 'synthesis':
        content = json.dumps({'ticker': identity['ticker'], 'company_name': identity['company_name'],
                              'bull_thesis': 'Synthetic offline fixture.',
                              'bear_thesis': 'Synthetic offline fixture.',
                              'conclusion': 'Synthetic rehearsal; quality not adjudicated.',
                              'direct_answer': 'Synthetic offline fixture.', 'confidence_score': 0.0})
    else:
        content = json.dumps({'summary': 'Synthetic offline fixture.',
                              'overall': 'Synthetic offline fixture.', 'confidence': 0.0})
    return {'id': 'offline-fixture', 'object': 'chat.completion', 'created': 0,
            'model': MODEL_SNAPSHOT, 'service_tier': 'default',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 32, 'total_tokens': 132}}
