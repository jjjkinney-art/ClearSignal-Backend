# Persist bounded thesis retrieval diagnostics

The completed PR286 pilot retained answers, citations and transport claims but
discarded diagnostic log text after canary checks. ACHC lacked business and risk
evidence; NPK lacked business evidence. Neither missing citations nor settled
document claims distinguish ingestion rejection, missing section boundaries or
sentence-admission rejection. The retained records cannot prove their cause.

The thesis-disclosure fetch now emits a structured diagnostic separate from its
formatted messages. It records the retrieval stage, fixed outcome code, admitted
business/competition/risk counts, and existing business-extraction status and
rejection counts. Document failures may include an allowlisted failure kind and
HTTP status. It does not record filing text, URLs, exception messages, identity
directory contents, raw responses or credentials.

The isolated pilot worker collects only this named logger's structured field,
revalidates it against fixed enums and bounded integer counts, and adds at most
six records to the artifact. Records are associated with the current frozen case.
The worker already drains all tracked tasks before advancing to another case;
unfinished workers halt the run instead of advancing. Ordinary formatted logs
remain discarded and subject to the existing credential-canary checks.

Retrieval selection, source admission, document envelopes and validation,
timeouts, quotas, claims, halts, fencing and answer status do not change. This
does not fix or establish the cause of either company's missing context. A future
separately authorized run can expose the relevant safe outcome without adding
provider requests. No live execution is authorized by this change, and all seven
historical approvals remain consumed.

Offline tests distinguish a successful business extraction, missing section,
rejected sentences and document HTTP refusal; reject unknown fields, malformed
enums, invalid counts and invented secret strings; enforce the record bound;
and verify persistence through the actual isolated approved worker with
synthetic transport. No live SEC or model calls are required.
