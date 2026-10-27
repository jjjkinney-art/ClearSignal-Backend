"""Transport envelope for the proposed twelve-case pilot; no execution authority.

This class does not construct a gate or grant network access. The future
executor must independently bind it to an approved twelve-case ledger and
isolated process. The historic reviewed-document exception is never accepted.
"""
from validation.capture_budget import BudgetError
from validation.ordinary_pilot_contract import quota_contract
from validation.pilot_live import OwnedHTTPTransport


class OrdinaryHTTPTransport(OwnedHTTPTransport):
    """Apply the cohort's fixed 16 MiB envelope to every response."""

    def authorize_reviewed_document(self, cik, url, form, filed_at):
        return None

    def response_limit(self, method, url, reviewed):
        if reviewed is not None:
            raise BudgetError('ordinary pilot forbids larger reviewed envelopes')
        return quota_contract()['body_max_bytes']
