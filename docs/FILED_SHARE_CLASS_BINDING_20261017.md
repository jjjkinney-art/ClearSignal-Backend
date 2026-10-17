# Filed share-class binding — 17 October 2026 Auckland

Base: `38b611c9983f3a272f2520fe0432fb456cee8730` (merged/deployed PR304).

## Result and limits

This increment extracts the requested security's exact common-stock title,
trading symbol and exchange label from one saved primary filing's Inline XBRL
cover row. The integration rebuilds PR304's quote/profile/EPS inputs and requires
the cover to belong to that EPS observation's same accession, form, filing date
and reporting-period end. It does not accept an already-passing caller report.

This establishes a source-bound declaration **as filed**. It does not establish
today's listing or identifier mapping, the price's unit, EPS allocation to the
declared class, distribution rights or split compatibility. No ratio, conversion,
return, evidence admission, recommendation or new live authority is produced.
All positive reports remain partial, unadmitted and not launch ready. Production
application modules do not import the new extractors.

The existing source-EPS helper now retains its reconstructed `document_type`
alongside period and filing date. This additive field allows explicit form
agreement without parsing a display title. Its existing source reconstruction,
reference, positive-EPS and annual-period requirements remain unchanged.

## Parser and binding

`validation.filing_share_class.extract_filed_share_class` consumes saved bytes,
their receipt, expected symbol/ten-digit CIK, form, filing date and period end.
Supported forms are domestic 10-K/10-Q and amendments. Missing, foreign,
unsupported class grammars or malformed inputs remain gaps; no issuer exceptions
or new taxonomy/HTML repair guesses are added.

- Require a canonical exact-CIK SEC primary HTML path, an eighteen-digit
  accession directory, matching raw SHA-256/length, integer HTTP 200, text/html
  and identity encoding. Extra historical receipt fields are not copied. The
  supplied receipt and metadata are consistency inputs, not authentication or
  submissions authorization. No URL is fetched and no existing hash gate is
  bypassed.
- Use the existing 15,000,000-byte SEC-periodic envelope as a fixed offline input
  bound, without a caller override or a new reviewed-annual exception. UTF-8 and
  ASCII XML bytes only; prohibit NUL, DTD/entity declarations and unsupported
  encoding declarations. Malformed XML is not repaired into an accepted filing.
- Parse with namespace scopes, checking all IDs through EOF for uniqueness.
  Selected fact/context identifiers must fit the narrower 200-character grammar;
  unrelated generated IDs may reach 4096 characters. This accommodates long
  dimensional IDs observed in the saved NPK body without allowing a long or
  ambiguous selected reference. Duplicate IDs still reject the whole parse.
- Enforce 100,000 nodes, depth 128, 256 namespaces in scope, 20,000 contexts,
  64 nodes per context, 1000 relevant facts and 500 characters per selected fact.
  Retain context and relevant text subtrees only; clear/remove unrelated display
  elements as parsing progresses. Body, text decoding and parser buffers still
  add memory overhead; this is not a process-RSS bound.
- Resolve DEI names through their actual SEC taxonomy namespace, not an assumed
  prefix. Required document issuer/form and selected fact contexts must agree
  with the expected CIK and period end. Context period structure and start/end
  chronology are checked. Dimension semantics are not interpreted as EPS-class
  equivalence.
- Select exactly one requested `dei:TradingSymbol`. Its `Security12bTitle` and
  `SecurityExchangeName` must be in the same XHTML table row and exact context.
  Reject field mixing across rows/contexts, duplicate-symbol candidates,
  ix:hidden security facts, excluded/nil/escaped/continued facts and transformed
  identity/title/symbol values. This is not a browser visibility audit.
- The title grammar covers explicit English common stock/shares, optional class
  letter and supported par-value wording. Preferred, warrants, units, depositary,
  ordinary and mixed-security titles do not become common-stock assertions.
  Exchange text and its optional transformation label are retained literally,
  never silently converted into MIC/provider-exchange equivalence.

`validation.share_basis_binding.assess_filed_share_basis` reruns the raw quote,
profile and EPS binding before extraction. It then requires identical accession
directory, form, filed date and EPS period end. A quarterly document cannot
masquerade as the annual EPS filing merely by sharing caller-supplied metadata.
Source index and primary-document filenames may differ within that same accession.

Successful reports expose the exact fact IDs, namespace, context, row ordinal,
literal text and raw body binding. Failure reports expose only fixed reason,
stage where applicable, and exception-class diagnostics. No arbitrary receipt
extras or exception messages are emitted.

## Saved-source replay

[Replay result](NPK_FILED_CLASS_REPLAY_20261017.json) uses the already retained
NPK annual body, not a new request or documentation sample:

- 1,404,517 bytes, SHA-256
  `8d9ea0ecbc1619994be67fe36900878ae6c825ba99047373ad749f9caedab8a1`.
- Exact filing URL and supplied metadata appear in the result. The title is
  `$1.00 par value common stock`, symbol NPK, exchange New York Stock Exchange.
- Fact IDs `ixv-11175`, `ixv-11176`, `ixv-11177` share context
  `d_2025-01-01_2025-12-31`. Filing date 2026-03-13; period end 2025-12-31.
- Original body and receipt bytes were compared before/after replay and remain
  unchanged. This is not a new all-history hash inventory or ledger adjudication.
- The actual saved-body replay covers extraction only. Full quote/profile/EPS
  integration is tested with invented fixtures, not represented as a live NPK
  valuation or a completed answer.

The initial replay rejected long **unrelated** generated IDs. Inspection found
no duplicate IDs. The final parser retains full-document uniqueness checks while
using separate bounded rules for unrelated IDs and selected references. Tests
cover both long-unrelated-ID acceptance and duplicate/long-selected-ID rejection.
The final saved-source replay succeeded; the initial gap is not hidden or counted
as successful source extraction.

To replay offline, use the socket-denying wrapper from
[PR302](DATED_PRICE_CAPTURE_CONTRACT_20261016.md), load the existing body/receipt,
assert the fixed body hash above, then call:

```python
extract_filed_share_class(body, receipt, expected_cik='0000080172',
    expected_symbol='NPK', form='10-K', filed_at='2026-03-13',
    reporting_period_end='2025-12-31')
```

The original capture is required for independent replay; the result JSON is not
a substitute for source bytes or proof of origin. No source body is duplicated
in this PR.

## Corporate actions and next gate

`corporate_action_status` stays `not_established_no_complete_event_evidence`.
Absence of the word split in a filing, a failed search, an empty event list,
provider non-ADR flags or a caller's passing report cannot prove no corporate
actions between the EPS basis and quote date. There is no event-list bypass.
Price unit and class-specific EPS/distribution rights still require source proof.
Current mapping, source authenticity, quote session/observation admission and
independent factual/usefulness acceptance remain open. No launch percentage is
inferred from these checks or from declaration extraction.

## Validation

67 new cases cover row/context/issuer/form/namespace binding, title ambiguity,
raw receipts, date and reference corruption, duplicate IDs including late IDs,
long unrelated IDs, XML resource bounds and encoding/entity defenses, streaming
text preservation, multi-source same-filing integration and unchanged split/unit
gaps. Final related suite: **878 passed**, no warnings. Separate synthetic
source-monitoring/freshness suite: **36 passed**, no warnings. Total **914**
regressions; narrower earlier suites are subsets, not additional coverage.
Import smoke passed with 135 routes under pinned CPython 3.11.9. Hosted CI and
independent review remain pending.

Use the socket-denying PR302 wrapper with the exact PR304 related-file list,
prepending `tests/test_filing_share_class.py` and appending
`tests/test_public_document_ingestion.py` and `tests/test_sec_inline_memory.py`.
Run `tests/test_monitoring_freshness_pilot.py` and
`tests/test_source_monitoring_pilot.py` separately with that same wrapper.
The transient pinned interpreter target was initially absent; `uv python install
3.11.9` restored it. The failed version probe ran no tests. The dependency
environment was reused; the runtime download was separate from socket-denied
validation and was not a provider request.

No provider API/SEC/model request, live probe, approval creation, production
activation, application admission change, transport/deadline/quota/fencing change,
historical-record edit or holdout output occurred. All eleven live approvals
remain consumed; frozen provider exclusions remain unchanged. The earlier PR301
combined-suite thread warning is not claimed diagnosed or repaired.
