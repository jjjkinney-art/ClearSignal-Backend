# Retain verified comparisons when operating income is missing

The PR286 source-only pilot completed all six cases. Its ACHC decision-threshold
answer retained six verified current/prior financial facts and their citations,
but returned no useful monitoring evidence. The monitoring producer required an
operating-margin calculation, although three financial comparisons had already
passed the financial foundation's reconstruction and citation checks.

When operating income is unverified, retain those independently rebuilt
comparisons and their existing conditional monitoring tests. The response stays
partial and explicitly lists operating income and operating margin as gaps. Its
margin benchmark list stays empty, and investment boundaries, valuation,
expected returns, operating KPI breakpoints and quantified earnings impacts
remain unverified. Pretax income cannot supply operating income or margin.

Do not use this fallback when operating income is verified but the margin inputs
have mismatched periods. Identity, currency, raw-fact reconstruction, conflict
handling, summary and reference checks remain owned by the existing financial
foundation producer. Its minimum of two valid core comparisons is unchanged.
Existing margin calculations and removal of model-generated investment zones
remain unchanged. No pilot policy, quotas, deadlines or approval path changed.

Offline replay reconstructed the saved ACHC decision-threshold facts with the
existing SEC evidence producer, asserted equality with all persisted claim
fields, and reused the saved response references. The changed monitoring
producer retained three comparisons, with no margin or decision boundary.
No external fetch or live rerun was made. The saved pilot also has missing
business/risk evidence for ACHC and missing business evidence for NPK; it does
not contain raw filing bytes or extraction diagnostics sufficient to identify
the cause. Those gaps remain unresolved.
