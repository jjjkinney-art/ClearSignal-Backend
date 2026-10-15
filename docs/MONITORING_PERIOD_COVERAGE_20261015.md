# Disclose newer listed filing periods in monitoring answers

The saved PR289 pilot has ACHC Q2 facts in its core answer, but Q1 facts in its
monitoring answer. The routes have different source paths: a core thesis may
fetch a filing-body fallback; the fixed monitoring route has no document slot.
The Company Facts selector chooses the latest qualifying comparable period in
its received records, but the raw Company Facts response was not retained.
The saved results do not prove why it lacked a qualifying Q2 pair. Do not infer
API lag or silently promote filing metadata into Q2 financial evidence.

When the financial foundation has rebuilt cited comparisons and a retrieved,
same-issuer primary SEC periodic filing listing identifies a newer period, add
a cited reporting-period coverage notice. Retain the original facts, dates,
calculations and partial answer status. Identify which comparisons end before
the newer listed period, and mark newer-period comparisons unverified. The
listing supplies metadata only; it does not establish the filing's amounts,
comparable observations or financial direction. Absence of a notice does not
establish that an answer contains the latest available facts.

Metadata must match the issuer of already reconstructed financial facts, use
the existing strict SEC archive URL check, have an eligible periodic form,
primary regulatory-filing publisher-feed metadata, available/non-conflicting
status, canonical ISO dates no later than today, and a unique bound response
reference with matching metadata fields. No model-generated values authorize
the notice. It is an explicit coverage gap, not a new financial claim.

Offline replay reconstructed the PR289 ACHC monitoring facts and checked equality
against the persisted claim fields, retaining all three Q1 comparisons. The
notice cites E4's listed Q2 period ending 2026-06-30, and identifies E1/E2/E3 as
older comparisons. Operating income and margin remain gaps; no margin or
investment boundary is invented. No live provider request was made.

This change does not add a filing request, alter metric selection, expand pilot
quotas or deadlines, change evidence admission, or resolve NPK's missing business
description. NPK's individual rejected sentences are absent from the saved pilot;
its aggregate rejection counts do not justify changing admission predicates.
All nine historical approvals remain consumed.
