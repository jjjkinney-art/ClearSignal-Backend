# SEC filing download diagnostics

The October 5 production Apple source-question run discovered five periodic
filings and sixteen consolidated fact references. Its two issuer-KPI document
downloads failed, leaving zero Services observations. The document task finished
in 741 ms and total retrieval in 1.53 seconds: this run did not exceed the
ten-second evidence collection deadline. Parsing Services tables could not
begin because no document was retrieved.

The previous error `public document request failed` did not distinguish an
HTTP rejection from a timeout, TLS failure or connection failure. It does not
establish an HTTP status, missing request identity or provider bot block.

## Diagnostic change

`PublicDocumentError` retains the existing safe message and adds:

- `failure_kind`: `http_error`, `timeout`, `tls_error`, `connection_error`,
  `request_error`, `dns_error`, or `document_rejected`.
- `http_status`: the bounded numeric status for HTTP errors, otherwise null.
- `error_class`: a fixed transport category, never raw exception text.

Issuer-KPI skip logs include those fields and `user_agent_configured` as a
boolean. They omit contact strings, document URLs/paths, request headers,
response bodies and raw exception messages. Primary filings and exhibits use
the same diagnostics. URL validation, size limits, redirect checks, timeouts,
document budgets and evidence admission are unchanged. No automatic retries,
alternate transport or authentication changes are introduced.

## Next production check

After deployment, run one new signed-in AAPL Services evidence question. If it
still returns insufficient evidence, inspect the `issuer KPI document skipped`
lines for the same `/ask` request and timestamp.

| Observation | Next investigation |
| --- | --- |
| `http_status=403` | Confirm the provider's access requirements and the deployment's configured request identity; a status alone does not prove the cause. |
| `http_status=404` | Inspect filing-discovery metadata and the returned primary document link. |
| `http_status=429` | Inspect provider rate limits and concurrent request volume. |
| `http_status=5xx` | Check the provider's availability before changing extraction rules. |
| `timeout`, `tls_error`, `connection_error`, `dns_error` | Investigate the deployment's transport or resolution failure. |
| Downloads succeed but Services evidence stays empty | Inspect actual table layouts and extraction/admission outcomes. |

The same production log separately shows RiskProfile schema validation failing:
the model returned objects for fields defined as strings. That is an independent
structured-output issue, not an explanation for the failed filing downloads.
Its repair must preserve the distinction between generated risk hypotheses and
verified evidence. PR #186 addresses the unsupported Services thesis-output leak;
this diagnostic change does not claim to repair either download availability or
the RiskProfile output contract.
