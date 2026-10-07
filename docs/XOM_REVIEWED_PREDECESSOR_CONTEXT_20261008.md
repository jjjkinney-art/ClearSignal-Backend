# Exxon successor context — 8 October 2026

## Evidence and scope

The frozen acceptance case identifies XOM's current public parent as
ExxonMobil Holdings Corporation, CIK 2115436. Ordinary exact-CIK discovery has
no full annual report for that issuer; the current quarterly report did not
yield a qualifying commodity-price risk. Exxon Mobil Corporation, CIK 34088,
filed the predecessor group's 2025 annual report. Silently assigning that
filing to the new issuer would lose provenance.

Reviewed primary sources:

| Record | Date | What was reviewed |
|---|---|---|
| [Successor 8-K12B](https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm) | Report dated 2026-07-01 | Explanatory Note identifies the predecessor, successor public parent and effective reorganization date. The relationship is specific to the common-stock registrant; the old corporation remains the primary obligor on the described notes. |
| [Successor quarterly Note 1](https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/R9.htm) and [filing index](https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/0000034088-26-000093-index.htm) | Filed 2026-08-03 | The consolidated business and reporting basis continued through the parent reorganization; the financial statements refer readers to the 2025 annual report. This note supports continuity, not a risk claim or current market condition. |
| [Predecessor annual index](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/0000034088-26-000045-index.htm) | Filed 2026-02-18; period ended 2025-12-31 | Identifies the exact 10-K primary document, accession 0000034088-26-000045 and predecessor CIK 34088. |

These reviewed facts support a narrow historical-context link. They do not
establish that every predecessor disclosure describes current conditions.
The current SEC directory must still identify both the expected current CIK
and company name. There is no automatic inheritance based on a ticker,
similar name, acquisition, subsidiary or arbitrary provider relationship.

## Behavior and boundaries

After the current quarterly report lacks a qualifying risk, discovery first
tries the current issuer's own full annual. Only if none is returned can the
reviewed registry supply the specific predecessor annual:
`https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/xom-20251231.htm`.
The existing remaining document slot is used. The acceptance path still allows
two document attempts; the live router's evidence deadline is unchanged.
Normal `sec_provider.fetch_recent_filings` remains exact-CIK and cannot return
a predecessor report as a current issuer's filing.

Extraction requires an explicit registry authorization. Binding revalidates
the exact URL, form, filing date, current identity and canonical relationship.
All existing primary-source, complete-section, topic, sentence, exact-quote,
hash, offset and citation requirements remain in force. This exception covers
qualitative risk context only, not structured metrics or current financial
aggregation.

The answer names the predecessor and current issuer, retains the actual annual
filing date and states that it is historical context rather than a new
successor disclosure. References and source-answer claims retain the effective
date, relationship proof links and source/subject identities, including both
CIKs. Private completed
turn snapshots preserve those fields when reopened. The acceptance report also
exports the validated provenance alongside its exact-span and citation checks.

Both supporting relationship documents must have been public at the analysis
boundary: use is blocked before 2026-08-03. That availability date and the
2026-07-01 effective date never replace the annual's 2026-02-18 freshness date.
The link cannot make the old risk disclosure newer than a saved thesis.

No shared ticker research route, legacy-memory boundary, backfill, provider
deadline, account ownership rule or notification delivery setting changes.

## Validation and remaining gates

Local validation: 41 new succession tests and 623 existing tests passed, with
the existing launch-security Starlette/AnyIO deprecation warning. The 23 modules
ran in separate interpreters. Tests cover the actual storage/reopen path,
foreign-owner isolation, forged relationships, changed current identities,
wrong URLs/forms/dates, quote/hash/offset tampering, historical comparison,
temporal admission, unchanged ordinary SEC discovery, fallback order and
bounded failed attempts. Positive disclosure sentences are authored fixtures,
not representations of extracted live Exxon claims.

PR #202's fresh signed-in JPM retest returned two cited credit-loss disclosures,
preserved two messages after reopening and appeared correctly in account-owned
History and Research Trail. That is one observed live success, not a production
latency or universal-coverage guarantee.

This Exxon implementation still requires required CI, deployment, actual SEC
source acceptance and a fresh signed-in answer. After deployment, run:

```sh
python scripts/company_evidence_acceptance.py \
  --case XOM --case JPM --case NFLX \
  --inspect-source \
  --output /tmp/company-evidence-successor-retest.json
```

For XOM, inspect the predecessor provenance, February filing date, exact source
spans and answer citations. Then submit the frozen commodity-price risk
question while signed in, reopen the saved investigation and verify History
and Research Trail. The live answer must visibly preserve historical attribution
and must not assert a verified present-day effect or directional thesis change.

Finally rerun the complete 33-company cohort. Its last complete result remains
20 source-binding passes and 13 gaps; targeted repairs do not revise that count
or clear the broader launch gate.
