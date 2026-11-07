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
    # Production since 2026-11-06 (PR #90 squash-merged). Run 5 was bound to 84466b2
    # and its frozen branch keeps that pin; this one applies to future packages only.
    'commit': '138d6461a7d6822fd9b27c784a410f55b243a40e',
    'classifier': 'frontend_cinematic/lib/queryIntent.ts',
    'classifier_sha256': '6ef10de383a75628b72bda552b624489992c84730e43ee884f56a4bc6dc1df38',
    'resolver': 'frontend_cinematic/lib/symbolResolver.ts',
    'resolver_sha256': '6fa4e195816df8c09a6439c86fb4c41d3a9d60990745cb877f492a5d7dd38542',
    # sha256 of json.dumps([question, ...]) in case order: the exact texts classified.
    # Cohort 4 (run 9) was classified 2026-11-08 and cohort 3 (run 6) 2026-11-06 by
    # these unmodified files.
    # Runs 1-5 were re-classified 2026-11-06 by the unmodified files exported
    # from this commit (Node 24.15.0). Any new cohort must be classified the same way.
    'questions_sha256': {'run5': '2f2e0db6f80c457a54bd01859ff3af094df02159fcbd4d338cf851158c351860',
                         'run3': '835a5fe7d038e21f7085f078f63cf10b92a4d58c310cce00fc6a80c5087f061d',
                         'runs-1-2': 'e9948dbc5a8038b2d32805ec39135e7e329c984bff38144679317774ce5eec28',
                         'run6': 'c0617b758458f25c7517393d00809a8d667ad2023b1689e16b813c19be74a4a1',
                         'run9': '33f47ba6198b87310926f33e0d9cee6326a352fc74301645ee52a8f688b37643'}[COHORT],
}
# The frontend's QueryIntent union.
FRONTEND_INTENTS = frozenset({'company_analysis', 'market_question', 'investing_education',
                              'portfolio_question'})
# What the pinned classifier returns: company analysis for every question. At 84466b2
# it sent BNY:core_thesis as investing_education, which halted run 5 there.
CASE_INTENTS = {case: 'company_analysis' for case in CASES}


def frontend_intent(case_id):
    intent = CASE_INTENTS[case_id]
    if intent not in FRONTEND_INTENTS:
        raise ValueError('not a frontend intent')
    return intent
