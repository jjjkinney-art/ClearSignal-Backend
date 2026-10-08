# ASML integrated annual risk context — 8 October 2026

## Deployed checkpoint

The owner-reported post-PR #204 Render subset passes SPOT and TSM; ASML and
NVO remain gaps. The earlier complete post-PR #203 cohort passed all 29 domestic
cases. These separate runs do not establish a new complete-cohort pass count,
signed-in acceptance, saved-thread acceptance or full launch clearance.

## Reviewed ASML document

ASML's 2025 20-F is an integrated annual report. Its Item 3.D crosswalk maps
Risk Factors to the Risk and security section, page 66. The reviewed body is:

- URL: https://www.sec.gov/Archives/edgar/data/937966/000162828026011378/asml-20251231.htm
- Filed: 2026-02-25; CIK: 937966; form: 20-F.
- Bytes: 24,864,733.
- SHA-256: `c7f397cd04b206b5b93a2ee338626885b1dab3b310243b02f78ffa7fd849f1f3`.

Only that exact URL/form/date registration receives a 30 MB download ceiling.
Its raw-body hash and visible Item 3.D mapping must match before extraction.
Redirect destinations are checked independently. Every other periodic filing
retains the 15 MB ceiling; unreviewed integrated reports cannot borrow this path.
A changed body at the same URL fails closed and requires review.

The registered opening requires Risk and security, Risk factors and the section's
introductory wording. The closing requires Risk and security, Information security
and its introductory wording. Repeated Risk factors (continued) headers do not
close the section. The 360k retained-text and 320k section ceilings remain.
References retain the actual integrated section label, exact normalized text
spans, source URL, filing date and body hash. The adverse-mechanism vocabulary
now recognizes the explicit phrase legal liabilities, while still requiring a
supported topic and possibility language.

## Validation

744 tests pass across 17 isolated modules, including 18 reviewed-layout cases.
They cover exact registration, wrong hash/date/form/issuer, altered bodies,
visible crosswalk requirements, bounded declared and streamed downloads,
unsupported headings, incomplete/oversized sections, repeated headings,
source offsets, citation admission and forged source references.

A replay of the directly downloaded actual ASML filing produces one complete
export-control disclosure, binds its exact text offsets and returns an attributed
answer with a citation. This replay supplies downloaded bytes and frozen issuer
identity fixtures; it is not a live Render retriever or signed-in test. Required
pinned CI and deployed acceptance remain separate gates.

## Remaining launch gate and next work

After deployment run the four foreign cases, then the complete 33-case cohort:

```sh
python scripts/company_evidence_acceptance.py \
  --case SPOT --case TSM --case ASML --case NVO \
  --inspect-source --output /tmp/company-evidence-post205.json
```

NVO's 20-F incorporates Annual Report 2025 Risk management pages 41–42, excluding
Mitigating actions. The SEC index links EX-15.1 `nvo-20251231_d2.htm` within the
same accession. Its risk table separates descriptions, impacts and mitigations.
The next slice must verify incorporation and preserve those column relationships;
flattening them into a synthetic risk sentence is insufficient. NVO remains open.

Fresh signed-in answers and saved-thread/History/Research Trail evidence checks
also remain outstanding. Continue the broader roadmap after those launch gates
are verified, rather than inferring clearance from local replay.
