"""The intent the production frontend sends with each ordinary pilot question.

The frontend calls /ask with company_name="" and the intent from
classifyQueryIntent; explicit general intents are authoritative in the backend
and route away from research. These values were produced by running that
classifier, unmodified, from the pinned commit below on the cohort questions.
A pilot is representative only while the deployed frontend serves that code.
This module is under validation/, so source_binding() binds it to the policy.
"""
from validation.ordinary_pilot_contract import CASES, COHORT

FRONTEND = {
    'repository': 'jjjkinney-art/Ai-Intelligence-interface',
    'commit': 'd66be31ecf7a8581323ff539a5fe43d299e15c01',  # main, PR #87 squash-merged
    'classifier': 'frontend_cinematic/lib/queryIntent.ts',
    'classifier_sha256': 'f0b6a07b707beb6c94784e7b18cb5b7aee79b80e74b255e1e9c9367b73d0dde8',
    'resolver': 'frontend_cinematic/lib/symbolResolver.ts',
    'resolver_sha256': '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542',
    # sha256 of json.dumps([question, ...]) in case order: the exact texts classified.
    # The run-3 cohort was classified 2026-11-03 by the unmodified files at this
    # commit (Node 24.15.0), after its production deployment; it was classified
    # 2026-10-31 at 5ee51c3 for run 3. Runs 1 and 2 (tests/ordinary_pilot_cases.json)
    # were classified for PR #350.
    'questions_sha256': {'run3': '835a5fe7d038e21f7085f078f63cf10b92a4d58c310cce00fc6a80c5087f061d',
                         'runs-1-2': 'e9948dbc5a8038b2d32805ec39135e7e329c984bff38144679317774ce5eec28'}[COHORT],
}
# The frontend's QueryIntent union.
FRONTEND_INTENTS = frozenset({'company_analysis', 'market_question', 'investing_education',
                              'portfolio_question'})
# What the pinned classifier returns: company analysis for every cohort question.
# (At 5ee51c3 it sent BWMX:core_thesis as investing_education; run 3 counted that.)
CASE_INTENTS = {case: 'company_analysis' for case in CASES}


def frontend_intent(case_id):
    intent = CASE_INTENTS[case_id]
    if intent not in FRONTEND_INTENTS:
        raise ValueError('not a frontend intent')
    return intent
