# ClearSignal account-data retention policy — beta proposal

**Policy ID:** `account-retention-v1-beta`  
**Status:** provisional; pending independent legal review and explicit owner approval  
**Operational authority:** none

This document is an internal engineering proposal. It is not legal advice, does
not claim compliance with every jurisdiction, and does not authorize a
production preview or deletion. The manual identity-verification and separate
approval requirements in `ACCOUNT_DELETION_RUNBOOK.md` remain controlling.

## Principles

ClearSignal will collect and retain only what has a documented product,
security, billing, or legal purpose. Account-linked information must not be kept
indefinitely “just in case.” At the end of a retention period it must be deleted
or irreversibly anonymized unless a documented legal hold applies.

This direction follows:

- New Zealand Privacy Act 2020, Information Privacy Principle 9: personal
  information must not be kept longer than required for a lawful purpose:
  https://www.privacy.org.nz/privacy-principles/9/
- New Zealand Privacy Act 2020, Information Privacy Principle 1: collect only
  information necessary for a lawful purpose:
  https://www.privacy.org.nz/privacy-principles/1/
- UK ICO storage-limitation guidance: document standard periods, justify them,
  review them, and erase or anonymize information no longer needed:
  https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/
- UK ICO erasure guidance: respond without undue delay and, where applicable,
  within one month:
  https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/

## Proposed beta schedule

| Record category | Proposed handling after verified deletion | Period | Purpose / boundary |
|---|---|---:|---|
| Account-owned research, profiles, preferences, watchlists, portfolios, notices and generated private content | Delete | 0 days after approved transaction | No continuing product purpose after account deletion |
| Canonical user row | Delete | 0 days after approved transaction | Remove the application identity after children are handled |
| Supabase authentication identity | Delete last | 0 days after successful application deletion | Preserve recovery ability until the application transaction succeeds |
| Access grant | Revoke first, then delete after successful account deletion | 0 days | Prevent new writes during processing; retain no account-linked grant afterward |
| Security audit trail | Remove or irreversibly anonymize account linkage during the deletion transaction; retain only the non-identifying security record | 365 days | Limited incident investigation and control verification; never retain content, email, token, ticker, portfolio value, or reversible account identifier |
| Opaque deletion completion record | Retain `DEL-###`, date and aggregate outcome only | 365 days | Demonstrate that the request was handled without retaining the requester’s identity |
| Render/Vercel infrastructure logs and Gmail support correspondence | Governed by provider/mailbox controls, not the application deletion transaction | Provider/mailbox policy | Must be accurately disclosed; ClearSignal must not promise per-account deletion it cannot technically perform |
| Shared ticker-wide research and operational benchmark records | Excluded from account deletion | Not account-linked | Must contain no private account identifier and remain behind existing route guards |

## Request timing

The beta target is to acknowledge promptly and complete a verified deletion
request within **30 calendar days**, unless identity cannot be verified, a
documented legal obligation requires limited retention, or a technically
necessary extension is communicated to the requester. This target must not be
published until legal review confirms the wording and applicable jurisdictions.

## Holds and exceptions

A hold is exceptional and must be narrowly documented with purpose, scope,
start date, reviewer and review date. It may not be created merely because data
could be useful someday. When the purpose expires, the held data returns to the
normal deletion schedule.

No current ClearSignal workflow implements legal holds.

## Review and approval

- Review interval: every 180 days and before entering a new jurisdiction.
- Required before public launch: independent privacy/legal review.
- Required before production tooling: explicit owner approval recorded outside
  source code, followed by a separate engineering change that implements and
  rehearses anonymization semantics.
- Any changed period or disposition requires a new policy version and tests.

Until those steps are complete, the policy remains provisional and the
fail-closed gate must continue to report:

- `approved_for_public_launch: false`
- `authorizes_production_preview: false`
- `authorizes_production_deletion: false`
