# Disabled source-monitoring pilot variant

This variant is an offline review surface based on PR284. It does not grant live
execution or spending authority. The existing frozen pilot remains unchanged;
none of its six consumed run records may be resumed, reset or reused.

`validation.pilot_source_monitoring` runs the actual six-case application pipeline
through the owned HTTP transport using invented responses and fake network I/O.
It enables `decision_monitoring_inputs_enabled` and requires source-only answers
for ASML, ACHC and NPK, for both `core_thesis` and `decision_threshold`.

| Per-case allocation | Directory | Submissions | Facts | Documents | Models |
| --- | ---: | ---: | ---: | ---: | ---: |
| Core thesis | 2 | 3 | 1 | 2 | 0 |
| Decision threshold | 1 | 1 | 1 | 0 | 0 |

The overall maximum is 33 SEC GETs and zero model attempts. Case and route slots
cannot transfer. Existing stage deadlines, the 480-second run deadline, token
bounds, transport restrictions and schema-2 ledger safeguards are inherited
without changes. FMP, NewsAPI and FRED stay excluded from physical dispatch.

The router schedules ten logical evidence tasks per core case and eight per
threshold case. Excluded-provider tasks return local empty evidence. The boundary
checks actual callable identities through the two fixed observability wrappers;
physical requests separately pass identity, reservation and atomic claim checks.
The artifact records the logical inventory, settled requests and sanitized answers.

Example offline command (use a new, nonexistent output path each time):

```sh
/workspace/clearsignal-venv/bin/python -I -B -c 'import sys; sys.path.insert(0,"/workspace/clearsignal-monitoring"); from validation.pilot_source_monitoring import main; raise SystemExit(main())' --output-dir /workspace/NEW-UNUSED-OFFLINE-OUTPUT --scenario monitoring_financial_inputs
```

`happy` supplies missing financial facts; `monitoring_financial_inputs` supplies
invented annual revenue and operating income. Completion alone is not a quality
pass. Inspect the persisted references and reproduce both margins and their
percentage-point change. The historical margin benchmark must remain explicitly
distinct from a buy/sell boundary; missing valuation, returns and KPI inputs must
remain unanswered gaps. These invented fixtures establish no real ASML evidence.

A future live variant needs separate exact-diff review, passing required checks,
validated execution configuration, a fresh commit-bound manifest, unused output
directory and new ledger, and separate user approval. This entrypoint has no live
approval option. The inherited US$0.52 ledger allowance is not an invoice ceiling
or permission to spend.
