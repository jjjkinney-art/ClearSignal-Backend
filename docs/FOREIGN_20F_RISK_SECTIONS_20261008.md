# Foreign annual risk sections — 8 October 2026

## Last deployed checkpoint

The owner ran the complete 33-company read-only acceptance cohort after PR #203.
All 29 domestic issuer/topic cases reported pass; SPOT, ASML, TSM and NVO
reported gap. This closes the domestic sample's source-binding failures, not
signed-in acceptance, all possible questions or full launch. The complete JSON
and deployed runtime SHA were not independently retrieved in this session.

## Change

Risk discovery includes 20-F and 20-F/A alongside existing US periodic forms.
A first amendment without qualifying disclosures prefers the same issuer's full
20-F in the remaining document slot. Foreign annuals cannot borrow a domestic
Item 1A section. They require an explicit Item 3.D heading or a Risk Factors
subheading in a bounded Item 3 Key Information preamble, and an explicit Item 4
Information on the Company closing. The reviewed TSM preamble omits the D label;
that bare-heading variant requires the preceding non-applicable preamble.
TOC numbers, quoted references, missing closings, distant preambles and
oversized sections withhold. No arbitrary integrated-report risk headings qualify.

Ingestion selects the same form-specific complete section if it occurs beyond
the retained prefix. References use Item 3.D. Risk Factors, preserving exact
normalized-document offsets, body hashes, filing date, URL and citation binding.
Foreign source references can preserve the same complete nonnumeric sentences
up to 900 characters. Other references retain their existing quote limits.
Inspection follows the same form-specific boundaries as extraction.

The 15 MB download bound, 360k retained-text bound, 320k general section ceiling,
two-document attempt budget and live router deadline remain unchanged. Ordinary
KPI/exhibit discovery and Apple Services remain unchanged. Exact-CIK discovery,
primary source admission, account ownership and unsupported-claim gates remain.
40-F, 6-K and integrated or incorporated-report risks are not authorized by this
change.

## Reviewed source replay

Primary documents were downloaded directly for inspection. Extraction/admission
and citation checks used those actual bytes with a frozen cohort identity fixture;
this is not a live production retriever or signed-in acceptance test.

| Issuer | Primary document | Filing date | Local replay |
|---|---|---|---|
| SPOT | https://www.sec.gov/Archives/edgar/data/1639920/000162828026006874/ck0001639920-20251231.htm | 2026-02-10 | Two attributed subscription disclosures |
| TSM | https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm | 2026-04-16 | One attributed export-control disclosure |
| NVO | https://www.sec.gov/Archives/edgar/data/353278/000035327826000012/nvo-20251231.htm | 2026-02-04 | No qualifying drug-development disclosure |
| ASML | https://www.sec.gov/Archives/edgar/data/937966/000162828026011378/asml-20251231.htm | 2026-02-25 | Integrated report; 24,864,733 downloaded bytes exceed the unchanged production limit; no supported Item 3 extraction claimed |

Novo Nordisk points to incorporated Annual Report material for some risks. A
separate source-bound incorporation path is needed; a cross-reference is not a
qualifying risk claim. ASML's integrated report requires reviewed section anchors
and an operating memory/latency decision before changing the bounded retriever.
No full foreign coverage or new complete-cohort pass count is inferred.

## Validation and deployment gate

694 tests passed across 16 isolated modules, including 27 new foreign-section
cases. Authored fixtures test complete source binding, form-specific discovery,
amendment fallback, long quotations, hidden text, late windows, section ceilings,
wrong forms and section tampering. Existing US, Apple and Exxon regressions pass.
Required pinned CI and production acceptance remain separate checks.

After deployment:

```sh
python scripts/company_evidence_acceptance.py \
  --case SPOT --case TSM --case NVO --case ASML \
  --inspect-source --output /tmp/company-evidence-foreign20f.json
```

Verify actual document spans, citation binding and timing. Then run fresh signed-in
SPOT and TSM answers and saved-thread/History/Research Trail checks. Re-run the
complete cohort to establish that the 29 domestic passes remain. Keep ASML/NVO
open until their separate source-grounded paths are implemented and verified.
