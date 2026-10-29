"""The intent the production frontend sends with each ordinary pilot question.

The frontend calls /ask with company_name="" and the intent from
classifyQueryIntent; explicit general intents are authoritative in the backend
and route away from research. These values were produced by running that
classifier, unmodified, from the pinned commit below on the cohort questions.
A pilot is representative only while the deployed frontend serves that code.
This module is under validation/, so source_binding() binds it to the policy.
"""
from validation.ordinary_pilot_contract import CASES

FRONTEND = {
    'repository': 'jjjkinney-art/Ai-Intelligence-interface',
    'commit': 'b56cd0bbf9fd9df9d586086e63b682c811d1a4ac',
    'classifier': 'frontend_cinematic/lib/queryIntent.ts',
    'classifier_sha256': 'd8f9810fa10cc539f4fc8ef6cdf140a137c312aabb57f88b677f3466ed5e41b6',
    'resolver': 'frontend_cinematic/lib/symbolResolver.ts',
    'resolver_sha256': '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542',
    # sha256 of json.dumps([question, ...]) in case order: the exact texts classified.
    'questions_sha256': 'e9948dbc5a8038b2d32805ec39135e7e329c984bff38144679317774ce5eec28',
}
# The frontend's QueryIntent union.
FRONTEND_INTENTS = frozenset({'company_analysis', 'market_question', 'investing_education',
                              'portfolio_question'})
CASE_INTENTS = {case: 'company_analysis' for case in CASES}


def frontend_intent(case_id):
    intent = CASE_INTENTS[case_id]
    if intent not in FRONTEND_INTENTS:
        raise ValueError('not a frontend intent')
    return intent
