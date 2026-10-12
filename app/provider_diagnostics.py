"""Suppress unsafe low-level diagnostics from the audited provider transports.

These loggers can include credential-bearing URLs, response headers or exception
tracebacks. Application-owned status, latency and usage events remain enabled.
No credentials are read; no logger levels, handlers or network settings change.
"""
import logging

# Exact emitters used by the audited OpenAI chat-completions, httpx/httpcore and
# requests/urllib3. A filter on a parent logger does NOT filter child records.
PROVIDER_TRANSPORT_LOGGERS = (
    'openai', 'openai._base_client', 'openai._response', 'openai._legacy_response',
    'httpx', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2',
    'httpcore.proxy', 'httpcore.socks',
    'urllib3', 'urllib3.connection', 'urllib3.connectionpool', 'urllib3.poolmanager',
    'urllib3.response', 'urllib3.util.retry',
)


class _SuppressProviderTransport(logging.Filter):
    def filter(self, record):
        # Do not format messages or exceptions: either may itself expose a key.
        return False


_FILTER = _SuppressProviderTransport()


def install_provider_transport_guards():
    """Install once per emitter, before provider clients can dispatch requests."""
    for name in PROVIDER_TRANSPORT_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(item, _SuppressProviderTransport) for item in logger.filters):
            logger.addFilter(_FILTER)
