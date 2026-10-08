"""Reviewed SEC incorporation relationships; never general exhibit discovery."""
from copy import deepcopy
from hashlib import sha256
import re

NVO = {
    "registry_id": "nvo-2025-risk-table-v1",
    "cik": "353278",
    "scope": "Drug development",
    "filed_at": "2026-02-04",
    "parent_url": "https://www.sec.gov/Archives/edgar/data/353278/000035327826000012/nvo-20251231.htm",
    "parent_form": "20-F",
    "parent_canonical_hash": "bc3b95895aa5c5ce37bbeb9b511ab60f9bfa5b9c072bbb24e58c0b093f92edd9",
    "parent_quote": "For information on risk factors, reference is made to ‘Risk management’ on pages 41-42 of our Annual Report 2025, excluding the section ‘Mitigating actions’ on page 42 .",
    "parent_section": "Item 3.D. Risk Factors",
    "exhibit_url": "https://www.sec.gov/Archives/edgar/data/353278/000035327826000012/nvo-20251231_d2.htm",
    "exhibit_form": "EX-15.1",
    "exhibit_canonical_hash": "757f48ffad59564c82b801e3ca55aec74245b456659c34f5ad013d9d0ce547ee",
    "section": "Annual Report 2025 - Risk management - Key risks and mitigations",
    "page": 42,
    "table_number": 90,
    "headers": ("Risk area", "Description", "Impact", "Mitigating actions"),
    "risk_area": "Research and clinical pipeline risks",
    "row_hash": "68ee5d0b7b2a126bbb24b088527c9956ab9670d172674d6ff789945f4296f061",
    "max_bytes": 15_000_000,
}
REVIEWED_INCORPORATIONS = (NVO,)


def registered_incorporation(url, form, filed_at, *, canonical_hash=None, cik=None):
    for entry in REVIEWED_INCORPORATIONS:
        if filed_at != entry["filed_at"] or (cik is not None and str(cik) != entry["cik"]):
            continue
        for role in ("parent", "exhibit"):
            if (url == entry[role + "_url"] and form == entry[role + "_form"]
                    and (canonical_hash is None or canonical_hash == entry[role + "_canonical_hash"])):
                return deepcopy(entry), role
    return None


def valid_hash(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def risk_row_hash(cells):
    return sha256("\0".join(cells).encode()).hexdigest()
