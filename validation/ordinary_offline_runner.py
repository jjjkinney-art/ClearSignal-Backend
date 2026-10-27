"""End-to-end twelve-case fixture coordinator. No live execution path.

Answers are deliberately invented placeholders, not application answers or
research evidence. The synthetic clock tests accounting, not real deadlines.
"""
from .ordinary_artifacts import export_fixture_packet, store_fixture_answer
from .ordinary_case_lifecycle import OfflineCaseLifecycle
from .ordinary_pilot_accounting import OfflineAccounting
from .ordinary_pilot_contract import CASES
from .ordinary_wire_rehearsal import rehearse_facts


def run_fixture_cohort(ledger_path, *, fault_case=None, fault='wire_connect_failure'):
    """Use a fresh ledger and fixed fake transport; no resume or real provider."""
    if fault_case is not None and fault_case not in CASES:
        raise ValueError('unknown fixture fault case')
    if fault not in {'wire_connect_failure', 'wire_redirect', 'wire_read_failure'}:
        raise ValueError('unknown fixture fault')
    tick = [0.0]
    book = OfflineAccounting(ledger_path, clock=lambda: tick[0])
    lifecycle = OfflineCaseLifecycle(book)
    failure = None
    try:
        for case in CASES:
            lifecycle.begin(case)
            rehearse_facts(book, case, scenario=fault if case == fault_case else 'reported-facts')
            store_fixture_answer(book, case,
                {'company': case.split(':')[0], 'answer': {'text': 'Synthetic fixture only'}},
                forbidden_values=('invented-secret',))
            lifecycle.finish(case, status='partial_gap')
            tick[0] += 2.0
    except Exception as exc:
        failure = type(exc).__name__
    lifecycle.finalize()
    packet = export_fixture_packet(book, forbidden_values=('invented-secret',))
    return {'packet': packet, 'failure_class': failure, 'fixture_only': True,
            'application_answers': False, 'execution_authorized': False}
