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
    'commit': '5ee51c375a75d43ba51fe71114e54a07efe43815',  # main, PR #86 squash-merged
    'classifier': 'frontend_cinematic/lib/queryIntent.ts',
    'classifier_sha256': 'd8f9810fa10cc539f4fc8ef6cdf140a137c312aabb57f88b677f3466ed5e41b6',
    'resolver': 'frontend_cinematic/lib/symbolResolver.ts',
    'resolver_sha256': '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542',
    # sha256 of json.dumps([question, ...]) in case order: the exact texts classified
    # (run-3 cohort, classified 2026-10-31 by the unmodified files at this commit).
    'questions_sha256': '835a5fe7d038e21f7085f078f63cf10b92a4d58c310cce00fc6a80c5087f061d',
}
# Runs 1 and 2 classified tests/ordinary_pilot_cases.json (all company_analysis).
RUN_1_2_QUESTIONS_SHA256 = 'e9948dbc5a8038b2d32805ec39135e7e329c984bff38144679317774ce5eec28'
# The frontend's QueryIntent union.
FRONTEND_INTENTS = frozenset({'company_analysis', 'market_question', 'investing_education',
                              'portfolio_question'})
# What the pinned classifier returns. It does not recognise the BWMX thesis
# question as naming a company; production would send a general intent, so the
# pilot sends the same and counts the outcome.
CASE_INTENTS = {case: 'investing_education' if case == 'BWMX:core_thesis' else 'company_analysis'
                for case in CASES}


def frontend_intent(case_id):
    intent = CASE_INTENTS[case_id]
    if intent not in FRONTEND_INTENTS:
        raise ValueError('not a frontend intent')
    return intent
