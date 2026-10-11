# Preserve signed decision-threshold inputs

The active structured-threshold parser searched for unsigned digits. It silently
converted `<-10x` into a positive 10x boundary and truncated `<1e3x` to 1x.
The parser now preserves ASCII/Unicode minus, explicit plus, leading decimals
and signs around dollar symbols. Multiple numeric tokens, malformed comma
separators/double signs, unsupported scientific notation and nonfinite overflow
produce the existing explicit unavailable result. No threshold or valuation
policy is selected; existing direction and overlap checks still apply.

Acceptance: 370 tests passed in separate processes: signed valuation thresholds
21, structured provenance 51, validation harness 42, valuation consistency 48,
canonicalization units 77, claim hardening 88 and latency optimization 43.
Coverage exercises the actual decision builder and thesis structured-content
wiring, negative EPS/margins, positive controls and malformed input rejection.
No model/provider calls or live acceptance were used. This is deterministic
input-fidelity validation, not verification of the model's chosen investment
thresholds, valuation assumptions or expected-return arithmetic.

Independent review identified further partial matches: unsupported sign-before-
non-dollar-currency expressions, accounting parentheses and trailing malformed
decimals. They now fail closed instead of discarding signs or punctuation.
Regression examples include `<-€10`, `<−€10`, `<($10)`, `<10..x` and unbalanced
parentheses. The seven affected files passed again (378 tests); two additional
unbalanced-parenthesis cases then passed with the complete 31-case new file.
