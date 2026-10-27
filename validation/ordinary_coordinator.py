"""Offline case coordination only; no network boundary or live authority.

The caller must provide isolated fixture execution and drain workers. This is
not a launcher and does not make an arbitrary callback safe for live use.
"""
from .ordinary_artifacts import store_fixture_answer
from .ordinary_case_lifecycle import OfflineCaseLifecycle
from .ordinary_pilot_accounting import AccountingError
from .ordinary_pilot_contract import CASES


def run_offline_cases(book, invoke, drain, *, forbidden_values):
    """Stop at first failure; retain answers only after workers drain and no halt."""
    lifecycle = OfflineCaseLifecycle(book)
    failure = None
    try:
        for case in CASES:
            lifecycle.begin(case)
            response = invoke(case)
            if drain():
                raise AccountingError('unfinished fixture workers')
            if book.summary()['halt']:
                raise AccountingError('fixture ledger halted')
            store_fixture_answer(book, case, response, forbidden_values=forbidden_values)
            lifecycle.finish(case, status='partial_gap')
    except Exception as exc:
        failure = type(exc).__name__
        book.seal_local()
        try:
            drain()
        except Exception:
            pass  # Retain the first failure; never publish an answer.
    finally:
        result = lifecycle.finalize()
    return {'failure_class': failure, 'lifecycle': result, 'execution_authorized': False}
