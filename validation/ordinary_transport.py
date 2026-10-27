"""Transport envelope for the proposed twelve-case pilot; no execution authority.

This class does not construct a gate or grant network access. The future
executor must independently bind it to an approved twelve-case ledger and
isolated process. The historic reviewed-document exception is never accepted.
"""
from validation.capture_budget import BudgetError
from validation.ordinary_pilot_contract import quota_contract
from validation.pilot_live import OwnedHTTPTransport
from urllib.parse import urlsplit


class OrdinaryHTTPTransport(OwnedHTTPTransport):
    """SEC GET only, with the cohort's fixed 16 MiB response envelope."""

    def exchange(self, method, url, *, body=b'', timeout=10.0, reviewed=None):
        if type(url) is not str or type(method) is not str or type(body) is not bytes:
            raise BudgetError('ordinary SEC request refused')
        try:
            parts = urlsplit(url)
            valid = (method == 'GET' and body == b'' and parts.scheme == 'https'
                     and parts.netloc in {'www.sec.gov', 'data.sec.gov'}
                     and parts.username is None and parts.password is None
                     and not parts.query and not parts.fragment and bool(parts.path))
        except ValueError:
            valid = False
        if not valid:
            raise BudgetError('ordinary SEC request refused')
        return super().exchange(method, url, body=body, timeout=timeout, reviewed=reviewed)

    def authorize_reviewed_document(self, cik, url, form, filed_at):
        return None

    def response_limit(self, method, url, reviewed):
        if reviewed is not None:
            raise BudgetError('ordinary pilot forbids larger reviewed envelopes')
        return quota_contract()['body_max_bytes']
