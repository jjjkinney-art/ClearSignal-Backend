# Guarded source-monitoring pilot

This entry point extends the offline source-monitoring variant with a separately
approved execution path. It does not authorize execution by being installed,
merged, or deployed.

`python -m validation.pilot_source_monitoring_approved` uses the existing launcher
arguments. `--prepare` writes a pending manifest without reading runtime
credentials or creating the run directory. Execution requires a separate approval
matching the exact source binding, validated execution configuration, and fresh
absolute output directory. The manifest purpose is
`approved_source_monitoring_pilot`; approvals for the original pilot cannot be
used for this variant, or vice versa.

The six ASML/ACHC/NPK cases remain fixed. All are source-only, with zero model
attempts and 33 nontransferable SEC slots. Model claims fail before dispatch, and
the approved exchange gate also rejects the OpenAI host for this variant. The
existing runtime credential-presence contract is retained; zero model quota does
not remove that launcher check. FMP, NewsAPI and FRED remain excluded.

The original pilot's policy and default launcher remain unchanged. Reviewed
document envelopes, complete-body and canonical-hash validation, stage and
whole-run deadlines, durable claims, at-most-once native dispatch, halt behavior,
late-worker tracking, concurrency fencing, proxy/CA checks, ambient-auth isolation
and credential canaries are shared without relaxing their checks.

Artifacts retain complete source answers and evidence, including explicit gaps.
Historical margin observations are monitoring benchmarks, not buy/sell cutoffs.
The illustrative model allocation is zero; the US$0.52 ledger allowance remains
distinct from an invoice ceiling, and actual charges are not established by the
ledger.

Offline tests cover cross-variant approval rejection, fixed quotas, mutated
authority, refusal without approval, preparation without runtime access, SEC
settlement, model refusal before network entry, and a six-case isolated worker
with invented responses and sockets blocked. Hosted checks and exact-diff review
must precede preparation of a new live approval package. No historical approval
or output directory is reusable.
