"""Source-bound reviewed table risks with independently verified incorporation."""
from copy import deepcopy
from datetime import date

from ..integrity.provenance import ClaimDocumentReference
from ..schemas import RetrievedEvidence
from .reviewed_incorporations import registered_incorporation, valid_hash, risk_row_hash


def _document_eligible(document):
    return (document.text_ready and document.extraction_method == "html"
            and document.publisher == "SEC EDGAR" and document.source_tier == "primary"
            and document.source_type == "regulatory_filing" and valid_hash(document.content_hash)
            and valid_hash(document.canonical_content_hash))


def reviewed_incorporation_candidate(document, *, ticker, question):
    """An observed same-accession link and exact Item 3.D quote authorize one exhibit."""
    from .issuer_risk_evidence import requested_risk_profile
    profile = requested_risk_profile(ticker, question)
    if not profile or not _document_eligible(document):
        return None
    registration = registered_incorporation(document.final_url, document.document_type,
        document.published_at, canonical_hash=document.canonical_content_hash, cik=profile.cik)
    if not registration or registration[1] != "parent":
        return None
    entry = registration[0]
    if (profile.scope != entry["scope"] or date.fromisoformat(entry["filed_at"]) > date.today()
            or not any(link.url == entry["exhibit_url"] for link in document.links)
            or document.text.count(entry["parent_quote"]) != 1):
        return None
    start = document.text.index(entry["parent_quote"])
    ref = ClaimDocumentReference(reference_id=f"document:{document.content_hash}:incorporation:{start}",
        title=document.title or "NVO 20-F", provider="SEC EDGAR", url=document.final_url,
        published_at=document.published_at, section=entry["parent_section"],
        content_hash=document.content_hash, quote=entry["parent_quote"]).to_dict()
    proof = {"registry_id": entry["registry_id"], "parent_document_ref": ref,
        "parent_canonical_hash": document.canonical_content_hash,
        "parent_start_offset": start, "parent_end_offset": start + len(entry["parent_quote"]),
        "exhibit_url": entry["exhibit_url"]}
    candidate = RetrievedEvidence(title="NVO incorporated Annual Report 2025 risk table",
        source="SEC EDGAR", summary="Reviewed incorporated annual-report exhibit",
        timestamp=entry["filed_at"], url=entry["exhibit_url"], document_type=entry["exhibit_form"],
        source_type="regulatory_filing", source_tier="primary")
    return candidate, proof


def _valid_incorporation(proof, entry):
    if (not isinstance(proof, dict) or set(proof) != {"registry_id", "parent_document_ref",
            "parent_canonical_hash", "parent_start_offset", "parent_end_offset", "exhibit_url"}
            or proof["registry_id"] != entry["registry_id"]
            or proof["parent_canonical_hash"] != entry["parent_canonical_hash"]
            or proof["exhibit_url"] != entry["exhibit_url"]):
        return False
    try:
        ref = ClaimDocumentReference(**proof["parent_document_ref"]).to_dict()
    except (TypeError, ValueError, AttributeError):
        return False
    start, end = proof["parent_start_offset"], proof["parent_end_offset"]
    return (type(start) is int and type(end) is int and start >= 0
        and end - start == len(entry["parent_quote"]) and ref.get("quote") == entry["parent_quote"]
        and ref.get("url") == entry["parent_url"] and ref.get("published_at") == entry["filed_at"]
        and ref.get("section") == entry["parent_section"] and ref.get("provider") == "SEC EDGAR"
        and ref.get("page") is None
        and valid_hash(ref.get("content_hash"))
        and ref.get("reference_id") == f"document:{ref['content_hash']}:incorporation:{start}")


def table_risk_summary(value):
    filed = value["document_ref"]["published_at"]
    return (f"{value['ticker']} disclosed in Annual Report 2025 (EX-15.1), incorporated by its "
        f"20-F filed {filed}. The quoted table row contains the risk area, description and "
        f"impact; mitigating actions are excluded: “{value['quote']}” "
        "This is an issuer disclosure, not an independent assessment of whether the "
        "described effects occurred or will occur, or of their financial impact.")


def extract_incorporated_risk(document, *, ticker, question, incorporation, diagnostics=None):
    from .issuer_risk_evidence import requested_risk_profile, risk_quote_rejections
    stats = diagnostics if diagnostics is not None else {}
    stats.update(status="document_ineligible", risk_headings=0, complete_sections=0,
        rejected_heading_prefixes=0, missing_closing_sections=0, oversized_sections=0,
        sentences=0, topic_sentences=0, qualifying_sentences=0, extracted_disclosures=0,
        topic_rejection_counts={}, scan_stopped_at_limit=False, reviewed_tables=0)
    profile = requested_risk_profile(ticker, question)
    if not profile or not _document_eligible(document):
        return []
    registration = registered_incorporation(document.final_url, document.document_type,
        document.published_at, canonical_hash=document.canonical_content_hash, cik=profile.cik)
    if not registration or registration[1] != "exhibit":
        return []
    entry = registration[0]
    if (profile.scope != entry["scope"] or not _valid_incorporation(incorporation, entry)
            or date.fromisoformat(entry["filed_at"]) > date.today()):
        return []
    stats["status"] = "no_qualifying_risk_table"
    tables = [t for t in document.tables if t.table_number == entry["table_number"]]
    if len(tables) != 1:
        return []
    rows = [tuple(c for c in row if c) for row in tables[0].rows]
    headers = tuple(entry["headers"])
    if rows.count(headers) != 1:
        return []
    header_index = rows.index(headers)
    candidates = [r for r in rows[header_index + 1:] if len(r) == 4 and r[0] == entry["risk_area"]]
    if len(candidates) != 1:
        return []
    row = candidates[0]
    if risk_row_hash(row[:3]) != entry["row_hash"]:
        return []
    # Only the first three contiguous cells are incorporated risk material.
    # No text from the explicitly excluded mitigation column enters a claim.
    quote = " ".join(row[:3])
    stats.update(reviewed_tables=1, complete_sections=1, sentences=1, topic_sentences=1)
    reasons = risk_quote_rejections(quote, profile)
    stats["topic_rejection_counts"] = {r: 1 for r in reasons}
    if reasons or document.text.count(quote) != 1:
        return []
    start = document.text.index(quote)
    offset = start
    columns = {"table_number": entry["table_number"], "headers": list(headers),
        "mitigating_actions_excluded": True}
    for key, text in zip(("risk_area", "description", "impact"), row[:3]):
        columns[key] = {"text": text, "start_offset": offset, "end_offset": offset + len(text)}
        offset += len(text) + 1
    ref = ClaimDocumentReference(reference_id=f"document:{document.content_hash}:risk:{start}",
        title=document.title or "NVO Annual Report 2025", provider="SEC EDGAR", url=document.final_url,
        published_at=document.published_at, section=entry["section"], page=entry["page"],
        content_hash=document.content_hash, quote=quote).to_dict()
    value = {"claim_kind": "issuer_disclosed_risk", "ticker": ticker, "scope": profile.scope,
        "quote": quote, "start_offset": start, "end_offset": start + len(quote), "document_ref": ref,
        "incorporation": deepcopy(incorporation), "table_columns": columns,
        "exhibit_binding": {"registry_id": entry["registry_id"], "raw_content_hash": document.content_hash,
            "canonical_content_hash": document.canonical_content_hash}}
    item = RetrievedEvidence(title=f"{ticker} {profile.scope} incorporated risk table · {document.published_at}",
        source="SEC EDGAR", summary=table_risk_summary(value), timestamp=document.published_at,
        url=document.final_url, relevance_score=0.97, source_type="regulatory_filing", source_tier="primary",
        claim_type="reported_fact", document_type=document.document_type, filed_at=document.published_at,
        section=entry["section"], page=entry["page"], extraction_method="html", risk_disclosures=[value])
    stats.update(status="risk_extracted", qualifying_sentences=1, extracted_disclosures=1)
    return [item]


def bound_incorporated_risk(item, *, ticker, question):
    from .issuer_risk_evidence import requested_risk_profile, risk_quote_rejections
    profile = requested_risk_profile(ticker, question)
    values = getattr(item, "risk_disclosures", None)
    if not profile or not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    binding = value.get("exhibit_binding")
    if not isinstance(binding, dict) or not valid_hash(binding.get("raw_content_hash")):
        return None
    canonical = binding.get("canonical_content_hash")
    if not valid_hash(canonical):
        return None
    registration = registered_incorporation(getattr(item, "url", None), getattr(item, "document_type", None),
        getattr(item, "timestamp", None), canonical_hash=canonical, cik=profile.cik)
    if not registration or registration[1] != "exhibit":
        return None
    entry = registration[0]
    if (binding != {"registry_id": entry["registry_id"], "raw_content_hash": binding["raw_content_hash"],
            "canonical_content_hash": entry["exhibit_canonical_hash"]}
            or profile.scope != entry["scope"] or not _valid_incorporation(value.get("incorporation"), entry)
            or value.get("claim_kind") != "issuer_disclosed_risk" or value.get("ticker") != ticker
            or value.get("scope") != profile.scope or "issuer_relationship" in value
            or "reviewed_layout" in value
            or getattr(item, "source", None) != "SEC EDGAR" or getattr(item, "source_tier", None) != "primary"
            or getattr(item, "source_type", None) != "regulatory_filing"
            or getattr(item, "claim_type", None) != "reported_fact"
            or getattr(item, "section", None) != entry["section"] or getattr(item, "page", None) != entry["page"]
            or getattr(item, "extraction_method", None) != "html"
            or getattr(item, "freshness_status", None) in {"unavailable", "conflicting", "superseded"}
            or date.fromisoformat(entry["filed_at"]) > date.today()):
        return None
    try:
        ref = ClaimDocumentReference(**value["document_ref"]).to_dict()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    quote = value.get("quote")
    start, end = value.get("start_offset"), value.get("end_offset")
    if (not isinstance(quote, str) or risk_quote_rejections(quote, profile)
            or type(start) is not int or type(end) is not int or start < 0 or end - start != len(quote)
            or ref.get("quote") != quote or ref.get("content_hash") != binding["raw_content_hash"]
            or ref.get("provider") != "SEC EDGAR" or ref.get("url") != entry["exhibit_url"]
            or ref.get("published_at") != entry["filed_at"] or ref.get("section") != entry["section"]
            or ref.get("page") != entry["page"]
            or ref.get("reference_id") != f"document:{ref['content_hash']}:risk:{start}"):
        return None
    columns = value.get("table_columns")
    if (not isinstance(columns, dict) or set(columns) != {"table_number", "headers", "mitigating_actions_excluded", "risk_area", "description", "impact"}
            or type(columns["table_number"]) is not int or columns["table_number"] != entry["table_number"]
            or columns["headers"] != list(entry["headers"])
            or columns["mitigating_actions_excluded"] is not True):
        return None
    offset = start
    texts = []
    for key in ("risk_area", "description", "impact"):
        cell = columns[key]
        if (not isinstance(cell, dict) or set(cell) != {"text", "start_offset", "end_offset"}
                or not isinstance(cell["text"], str) or not cell["text"]
                or type(cell["start_offset"]) is not int or type(cell["end_offset"]) is not int
                or cell["start_offset"] != offset or cell["end_offset"] != offset + len(cell["text"])):
            return None
        texts.append(cell["text"])
        offset = cell["end_offset"] + 1
    if (texts[0] != entry["risk_area"] or risk_row_hash(texts) != entry["row_hash"]
            or " ".join(texts) != quote or offset - 1 != end
            or getattr(item, "summary", None) != table_risk_summary(value)):
        return None
    return value
