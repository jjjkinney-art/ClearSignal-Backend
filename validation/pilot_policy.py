"""Fixed policy for an offline API-usage rehearsal, never spending authority."""
from types import MappingProxyType

from validation.capture_budget import BudgetError, digest
from validation.pilot_preflight import preflight


MODEL = 'gpt-4o-mini'
MODEL_SNAPSHOT = 'gpt-4o-mini-2024-07-18'
CONTEXT_TOKENS = 128_000
AGENT_STAGES = ('valuation', 'macro', 'risk', 'market', 'quality', 'question_answerer')
MODEL_ROUTES = tuple('model/' + stage for stage in (*AGENT_STAGES, 'synthesis'))
SEC_ROUTES = ('sec/directory', 'sec/submissions', 'sec/facts', 'sec/document')
AUDITED_DEPENDENCIES = MappingProxyType({
    'openai': '2.32.0', 'httpx': '0.28.1', 'httpcore': '1.0.9',
    'requests': '2.32.5', 'urllib3': '2.8.0',
})
PILOT_SETTINGS = MappingProxyType({
    'agent_model': MODEL, 'synthesis_model': MODEL, 'temperature': 0.0,
    'max_tokens': 4096, 'synthesis_max_tokens': 1536,
    'agent_max_retries': 1, 'synthesis_max_retries': 1,
    'agent_timeout': 15.0, 'synthesis_timeout': 55.0,
    'enable_data_retrieval': False,
})


def policy_for(code_binding, dependencies):
    """No caller-supplied limits, rates, routes, approval or configuration."""
    setup = preflight()
    if dependencies != dict(AUDITED_DEPENDENCIES):
        raise BudgetError('dependency audit changed; separate review required')
    if (type(code_binding) is not dict or set(code_binding) != {'revision', 'source_sha256'}
            or any(type(v) is not str or not v for v in code_binding.values())):
        raise BudgetError('explicit code binding required')
    per_case = {}
    for case in setup['cases']:
        source = case['case_id'].endswith(':core_thesis')
        limits = {route: 0 for route in (*MODEL_ROUTES, *SEC_ROUTES)}
        limits.update({'model': 0 if source else 8, 'sec': 8 if source else 2,
                       'sec/directory': 2 if source else 1, 'sec/submissions': 3 if source else 1,
                       'sec/facts': 1 if source else 0, 'sec/document': 2 if source else 0})
        if not source:
            limits.update({route: 1 for route in MODEL_ROUTES})
            limits['model/synthesis'] = 2
        per_case[case['case_id']] = limits
    configuration = {
        'python_implementation': 'cpython', 'python_version': '3.11.9',
        'settings': dict(PILOT_SETTINGS), 'variant': 'control',
        'service_tier': 'default', 'n': 1, 'stream': False,
        'sdk_max_retries': 0, 'transport_retries': 0, 'redirects': False,
        'model': MODEL, 'response_model': MODEL_SNAPSHOT,
        'context_window_tokens': CONTEXT_TOKENS,
        'input_reservation_tokens': CONTEXT_TOKENS,
        'input_admission': 'utf8_bpe_upper_bound_with_64_token_per_message_and_reply_margin',
        'token_framing_verified_for_live': False,
    }
    prices = {}
    for route in (*MODEL_ROUTES, *SEC_ROUTES):
        model = route.startswith('model/')
        prices[route] = {
            'currency': 'USD', 'all_incremental_charges_accounted': False,
            'request_usd': '0',
            'input_token_usd': '0.00000015' if model else '0',
            'output_token_usd': '0.00000060' if model else '0',
            'maximum_input_tokens': CONTEXT_TOKENS if model else 0,
            'maximum_output_tokens': (1536 if route == 'model/synthesis' else 4096) if model else 0,
        }
    return {
        'schema_version': 2, 'purpose': 'offline_six_case_rehearsal',
        'pilot_id': 'frozen-v2-six-case-offline-rehearsal',
        'approval_reference': 'NO_SPENDING_AUTHORITY',
        'configuration_version': digest(configuration),
        'pricing_review_reference': 'ILLUSTRATIVE_PUBLIC_STANDARD_TEXT_RATES_ONLY',
        'budget_usd': '0.52', 'maximum_attempts': 54,
        'approved_case_ids': [case['case_id'] for case in setup['cases']],
        'setup_sha256': setup['setup_sha256'],
        'prices': prices,
        'quotas': {'groups': {'model': list(MODEL_ROUTES), 'sec': list(SEC_ROUTES)},
                   'overall': {'model': 24, 'sec': 30}, 'per_case': per_case,
                   'sec_per_second': 10},
        'configuration': configuration, 'code_binding': code_binding,
        'dependencies': dict(dependencies),
        'execution_allowed': False, 'spending_authorized': False,
        'tariffs_verified': False, 'all_incremental_charges_accounted': False,
    }


def validate_model_payload(payload, stage):
    """Admit a fixed plain-text schema, reserving the FULL token context.

    Byte-level BPE can only merge UTF-8 bytes, so their count is a conservative
    content-token upper bound, not a token count or a billing unit. Add generous
    framing margins for the fixed two-message schema. Actual billing reservation
    is always 128,000 input TOKENS, independent of this admission bound. The
    model's framing/alias mapping still needs independent review before live use.
    """
    if stage not in (*AGENT_STAGES, 'synthesis'):
        raise BudgetError('model stage is outside the pilot')
    output = 1536 if stage == 'synthesis' else 4096
    if (type(payload) is not dict
            or set(payload) != {'model', 'messages', 'temperature', 'max_tokens',
                                'service_tier', 'n', 'stream'}
            or payload['model'] != MODEL or payload['service_tier'] != 'default'
            or type(payload['n']) is not int or payload['n'] != 1
            or payload['stream'] is not False
            or type(payload['max_tokens']) is not int or payload['max_tokens'] != output
            or type(payload['temperature']) not in (float, int) or payload['temperature'] != 0
            or type(payload['messages']) is not list or not 1 <= len(payload['messages']) <= 2):
        raise BudgetError('unsupported model request or chargeable units')
    roles = []
    admission_bound = 64  # Reply framing margin; never priced as input usage.
    for message in payload['messages']:
        if (type(message) is not dict or set(message) != {'role', 'content'}
                or type(message['role']) is not str or type(message['content']) is not str):
            raise BudgetError('only plain text messages are supported')
        roles.append(message['role'])
        try:
            admission_bound += 64 + sum(len(value.encode('utf-8')) for value in message.values())
        except UnicodeError:
            raise BudgetError('invalid text encoding') from None
    if roles not in (['user'], ['system', 'user']):
        raise BudgetError('unsupported message roles or ordering')
    if admission_bound + output > CONTEXT_TOKENS:
        raise BudgetError('complete request plus output exceeds context admission bound')
    return CONTEXT_TOKENS, output


def response_usage(data, output_bound):
    """Parse fixture protocol usage; never infer missing units or account cost."""
    if (type(data) is not dict or data.get('model') != MODEL_SNAPSHOT
            or data.get('service_tier') != 'default'):
        raise BudgetError('response model or service tier mismatch')
    usage = data.get('usage')
    choices = data.get('choices')
    if (type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict
            or choices[0].get('index') != 0 or choices[0].get('finish_reason') != 'stop'
            or type(choices[0].get('message')) is not dict
            or set(choices[0]['message']) != {'role', 'content'}
            or choices[0]['message']['role'] != 'assistant'
            or type(choices[0]['message']['content']) is not str):
        raise BudgetError('only a single complete plain text choice is supported')
    allowed = {'prompt_tokens', 'completion_tokens', 'total_tokens',
               'prompt_tokens_details', 'completion_tokens_details'}
    if type(usage) is not dict or not {'prompt_tokens', 'completion_tokens', 'total_tokens'} <= set(usage) <= allowed:
        raise BudgetError('missing or unknown usage units')
    inputs, outputs, total = (usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
    if (any(type(v) is not int or v < 0 for v in (inputs, outputs, total))
            or total != inputs + outputs or inputs > CONTEXT_TOKENS or outputs > output_bound):
        raise BudgetError('ambiguous or excessive usage')
    for key, fields in [('prompt_tokens_details', {'cached_tokens', 'audio_tokens'}),
                        ('completion_tokens_details', {'reasoning_tokens', 'audio_tokens',
                                                       'accepted_prediction_tokens', 'rejected_prediction_tokens'})]:
        details = usage.get(key, {})
        if type(details) is not dict or not set(details) <= fields:
            raise BudgetError('unknown usage details')
        for unit, value in details.items():
            if type(value) is not int or value < 0 or (value > inputs if unit == 'cached_tokens' else value != 0):
                raise BudgetError('unsupported additional charge units')
    return inputs, outputs
