"""Whether SEC's own filing list proves a registrant has no XBRL financial data.

A depositary-receipt registration entity (SEC type "other", SIC 8880) files registration
forms only. SEC builds its company-facts record from XBRL financial data, so such an entity
has none, and asking for it is inapplicable rather than a failure to be tolerated.

This is a conclusion about a response SEC already returned, never an inference from a
name, a ticker, an "/ADR" suffix or an HTTP error. Every condition must hold, and a field
that is missing, malformed, ragged or of the wrong type makes the answer "not proven":

  1. the response is a JSON object whose CIK is exactly the expected CIK;
  2. ``filings.recent`` has parallel arrays ``form``, ``isXBRL``, ``isInlineXBRL`` and
     ``isXBRLNumeric`` of one length, at least 1 (an empty list proves nothing);
  3. ``filings.files`` is an empty list (the listing is complete: no older pages);
  4. every ``isXBRL`` and ``isInlineXBRL`` is exactly the integer 0, and every
     ``isXBRLNumeric`` is null or 0 (SEC leaves it null on most entries);
  5. every form is one of the five the retained evidence shows (widened only on new evidence);
  6. ``entityType`` is "other" and ``sic`` is "8880" (corroboration; never sufficient alone).

validation/ordinary_registration_only.py holds a second, independent copy of this predicate
for the pilot's ledger and export; a test keeps the two equal.
"""
import re

REGISTRATION_FORMS = frozenset({"F-6", "F-6 POS", "F-6EF", "424B3", "EFFECT"})
REASON = "no_xbrl_filings"
_PARALLEL = ("form", "isXBRL", "isInlineXBRL", "isXBRLNumeric")


def _exact_int(value, allowed):
    return type(value) is int and value in allowed


def registration_only_evidence(submissions, expected_cik):
    """The evidence summary if every condition holds, else None."""
    if type(expected_cik) is not str or not re.fullmatch(r"[0-9]{1,10}", expected_cik):
        return None
    if type(submissions) is not dict:
        return None
    reported = submissions.get("cik")
    if type(reported) is not str or not re.fullmatch(r"[0-9]{1,10}", reported) or int(reported) != int(expected_cik):
        return None
    filings = submissions.get("filings")
    recent = filings.get("recent") if type(filings) is dict else None
    if type(recent) is not dict or filings.get("files") != []:
        return None
    arrays = [recent.get(key) for key in _PARALLEL]
    if any(type(array) is not list for array in arrays):
        return None
    count = len(arrays[0])
    if count < 1 or any(len(array) != count for array in arrays):
        return None
    forms, is_xbrl, is_inline, numeric = arrays
    if (any(type(form) is not str or form not in REGISTRATION_FORMS for form in forms)
            or any(not _exact_int(value, (0,)) for value in is_xbrl)
            or any(not _exact_int(value, (0,)) for value in is_inline)
            or any(value is not None and not _exact_int(value, (0,)) for value in numeric)):
        return None
    if submissions.get("entityType") != "other" or submissions.get("sic") != "8880":
        return None
    return {"cik": reported, "filings_listed": count, "forms": sorted(set(forms)), "xbrl_flags": 0,
            "complete_listing": True, "entity_type": "other", "sic": "8880"}


def explanation(evidence):
    """The plain-language reason financial analysis is unavailable."""
    forms = ", ".join(evidence["forms"])
    return (f"No financial analysis is available for this registrant. SEC's complete filing list for it "
            f"({evidence['filings_listed']} filings) contains only depositary-receipt registration forms "
            f"({forms}) and no XBRL financial filings, so no company-facts request was made and no "
            f"financial comparison, monitoring baseline or threshold exists. This describes the registrant; "
            f"it is not a retrieval failure.")
