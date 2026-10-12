# Frozen SEC + OpenAI pilot preparation

`python -m validation.pilot_preflight` produces a non-executable preparation
artifact for exactly ASML, ACHC and NPK, each with `core_thesis` and
`decision_threshold`. It reads only the three frozen v2 setup files. It does not
import the application, inspect environment variables or credentials, create a
ledger, run captures, start a server or contact any provider. There is no
`--execute` option. Even an enabled capture environment flag cannot enable it.

The approved reduced scope excludes FMP financial/market/valuation/estimate
evidence, NewsAPI company/macro news and FRED evidence. The artifact records those
gaps; it neither checks provider configuration nor claims replacement coverage.
`execution_allowed`, `spending_authorized`, `hard_usd_cap_established` and
`launch_ready` remain false. Quality remains `not_adjudicated`.

## Identity and question boundary

The module pins the reviewed registry, manifest and reservation-metadata bytes
from main `e3054c3473f2e072089fc657a937f35b7a4aa504`. A different v2 file, v1 under a
v2 filename, changed question, changed admission/holdout or recomputed metadata
cannot silently rebind this preparation. Updating these pins requires a separate
setup review; hashes themselves do not authenticate external sources.

`resolve_pilot_identity(ticker, cik)` requires exact strings and checks both the
registry identity and its reviewed admission. It returns immutable identity data
and `company_context()` fields compatible with the pipeline's `CompanyContext`.
NPK resolves to **National Presto Industries, Inc., SEC CIK 0000080172** without
depending on the production detection catalog or substituting another ticker.
CIK stays in the bound identity because `CompanyContext` has no CIK field.
Sector is the registry's benchmark classification, not a verified GICS claim.
This is frozen reviewed identity, not a live SEC-directory verification.

The legacy capture runner and its v1 default remain unchanged. A future reviewed
pilot runner must explicitly use this resolver and v2 binding; this change does
not make the legacy execution path pilot-ready. No manifest, registry, question,
holdout or production company-detection code is modified.

`preflight()` selects the six questions from the frozen manifest. Optional
`--input` accepts an object with `schema_version: 1`, `registry_version: 2`, and
exactly six cases containing only `issuer_id`, zero-padded `cik`, `question_id`
and the verbatim `question`. Unknown identities, other question families,
duplicates, subsets, added state and any question alteration are rejected.

## Logical routes and remaining integration

The artifact's inventory is **expected logical tasks**, not observed physical
dispatches or a provider allowlist. Core-thesis cases select recent filings,
company facts, thesis disclosures and filing metrics, then skip model stages.
Decision-threshold cases select recent filings and may use five specialists,
Q-first and up to two synthesis invocations. These maxima exclude SDK retries,
redirects, sequential fallback and abandoned workers; no attempt cap is claimed.

Synthetic tests compare the six exact questions to application routing predicates
and reject changed inventories through `validate_route_inventory`. The router
still queues a FRED task, but these questions match no topics; tests verify zero
FRED fetches even with an invented key. No issuer-KPI or issuer-release task is
selected. This check is not runtime suppression: a future physical boundary must
refuse unexpected routes independently of missing optional credentials.

Real transports, durable worker fencing, credential-safe request binding,
explicit model/service-tier identity, verified usage bounds/tariffs and dollar
approval remain outside this preparation. The future SEC bridge must apply the
configured contact instead of the current discovery client's hardcoded value.
Any eventual accounting guarantee must state its API-usage reservation scope;
this artifact establishes no absolute invoice or whole-pilot USD ceiling.
