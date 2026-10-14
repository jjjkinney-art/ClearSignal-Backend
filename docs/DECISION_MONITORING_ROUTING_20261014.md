# Verified input routing for financial monitoring

Production decision-threshold questions now enter the deterministic source
view. Retrieval requests the existing consolidated revenue, operating income,
net income and operating cash-flow comparisons, using their existing producer
and admission checks. No numerical valuation breakpoint or arbitrary KPI is
inferred. The monitoring producer added in PR283 may admit a matched-period
operating-margin benchmark; insufficient inputs still produce an honest gap.
Model agents and synthesis are skipped on this production route.

`decision_monitoring_inputs_enabled` defaults to true in application settings.
The isolated frozen pilot explicitly pins it false in its policy and both
launcher and worker fixed environments. It never inherits the caller's value.
This keeps the prior threshold-route request allowance and model routing;
the final source gate still withholds unsupported generated boundaries.

The pilot policy/source hashes change because this pin is now part of the
reviewed configuration. All six historical approvals remain consumed. A new
pilot testing the new input route requires a separate reviewed policy with an
explicit facts allowance, new manifest/configuration and fresh approval. Do
not enable the setting inside the old frozen pilot or silently enlarge quotas.
No quota, deadline, retry, transport or credential rule is relaxed here.

Offline tests cover classification, narrowed metric selection, frozen-policy
disablement and an actual synthetic router response with admitted inputs and
zero model calls. Initial rehearsals exposed configuration drift because the
worker clears the launcher environment; pinning the setting in both fixed
environments addresses that drift without weakening the guard. Required full
checks and final results are reported in the PR. No live requests were made.
