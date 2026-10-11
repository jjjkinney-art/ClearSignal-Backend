# Valuation evidence time-basis integrity

The answer-quality roadmap retains valuation and expected returns as open gaps
(THESIS_BUSINESS_RISK_CONTEXT_20261009.md and CITED_COMPETITIVE_CONTEXT_20261011.md).
This increment repairs an existing provider contract; it does not choose a
valuation methodology, discount rate, forecast, expected return or rating.

The ratios adapter previously treated priceEarningsRatioTTM as forward P/E.
Both peRatioTTM and priceEarningsRatioTTM now remain trailing P/E. Only an
explicit forwardPE value receives the forward label, including when equal to
trailing P/E. Equal trailing aliases deduplicate; conflicting trailing aliases
are omitted without dropping independent forward or other ratio evidence.
Finite nonzero numeric inputs preserve existing negative-value behavior;
zero, booleans, strings, nonfinite and malformed values are omitted. This is
input validation, not an assessment that a multiple is cheap or expensive.
The container title no longer incorrectly labels a mixed-basis collection TTM.

Tests also exposed that ratios and key metrics silently failed construction:
RetrievedEvidence requires timestamp. These outputs now explicitly retain an
unknown date (empty string), matching existing provider conventions. They do
not substitute retrieval time, gain a public citation URL, verified facts,
source freshness or primary-source status. Strict financial-foundation
admission still rejects this unbound provider prose.

Independent review found downstream consumers were undoing that unknown-date
contract: dimension freshness treated undated items as fresh, coverage counted
any ratio endpoint as live, and analyst EPS prose could count as recent earnings.
The shared consumers now preserve unknown publication dates. Valuation coverage
uses the existing 14-day fresh-valuation window; recent earnings retains its
existing 90-day window and excludes explicitly typed or identified analyst
estimates. A valid date on another item cannot establish either coverage gap.
Timestamp parsing rejects malformed/future dates for freshness instead of
truncating malformed strings into valid dates, while preserving supported ISO
offsets and the legacy month-only form.

Synthesis keeps undated ratios and estimates available as qualified evidence,
without calling them live, automatically labeling EPS forward, or confusing an
estimate period with publication. These remain prompt instructions, not proof
that a live model will follow them. The unknown-date and earnings/estimate
distinction is enforced deterministically in freshness and coverage.

Downstream repair validation: 528 tests passed across provider freshness
semantics (21 cases), truth density, realism hardening, monitoring intelligence,
valuation period labels, valuation consistency, conviction modeling/dispersion,
structured provenance, question-anchored valuation and source-pipeline latency.
The combined run emitted existing background-thread and Starlette deprecation
warnings; all checks completed. New offline tests exercise
the actual restored ratio adapter through freshness, gap calibration and full
synthesis prompt construction, plus the restored analyst-record shape, malformed
and future dates, dated positive controls, mixed pools and existing boundaries.

Acceptance: 233 tests passed across test_valuation_period_labels (47 cases),
test_fmp_provider, test_question_anchored_valuation, test_valuation_consistency
and test_source_evidence_latency. New tests intercept provider payloads and
fail on socket/DNS access. They check nonempty returned evidence, downstream
agent prompt text, malformed inputs, unknown dates and foundation rejection.
The combined run emitted existing source-pipeline background-thread warnings;
it completed successfully. No live provider/model calls were made.

Live verification and source-bound expected-return acceptance remain open.
No new price data, EPS horizon, dividend assumptions, future exit multiple,
discount rate or expected-return model was invented. Analyst estimates and
price-target outputs also omit required timestamps; that separately observed
contract defect is not changed in this increment.
