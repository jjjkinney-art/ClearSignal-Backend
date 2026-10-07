"""Opt-in bounded public-source inspection, never evidence or launch approval."""
from __future__ import annotations

from collections import Counter
import hashlib
import re

from app.services.issuer_risk_evidence import (
    _has_topic_scope, requested_risk_profile, risk_quote_rejections,
)
from app.services.sec_risk_sections import (
    _ITEM, RISK_START, find_risk_closing, rejected_risk_heading,
    MAX_ISSUER_RISK_SECTION_CHARS,
)


REJECTION_REASONS = {
    "document exceeds the size limit": "document_size_limit",
    "invalid document content length": "invalid_content_length",
    "unsupported document content type": "unsupported_media_type",
    "expanded limits require HTML content": "sec_periodic_non_html",
    "expanded limits require a SEC periodic HTML filing": "sec_periodic_url_or_metadata",
    "document redirect limit exceeded": "redirect_limit",
    "document contained no extractable text": "empty_visible_text",
}


def rejection_reason(error) -> str:
    # Only exact, application-authored messages become stable codes. Never
    # return arbitrary exception text, request URLs, headers or response bodies.
    return REJECTION_REASONS.get(str(error), "unclassified_rejection")


def boundary_inspection(text: str) -> dict:
    """Full visible text only; sample caps are independent of evidence limits."""
    samples = []
    for index, opening in enumerate(RISK_START.finditer(text)):
        if index == 8:
            break
        closing = find_risk_closing(text, opening.end())
        samples.append({
            "offset": opening.start(),
            "context": text[max(0, opening.start() - 60):opening.end() + 160],
            "rejected": rejected_risk_heading(text, opening.end(), start=opening.start()),
            "recognized_closing_offset": closing.start() if closing else None,
            "recognized_section_chars": closing.start() - opening.end() if closing else None,
        })
    # Include numbered labels even when their title fails the production regex.
    numbered = re.compile(rf"\b{_ITEM}\s+(?:1\s*[ABC]|2)(?=\s|[.:—–-])", re.I)
    headings = []
    for index, match in enumerate(numbered.finditer(text)):
        if index == 24:
            break
        headings.append({"offset": match.start(),
                        "context": text[max(0, match.start() - 40):match.end() + 160]})
    return {"text_coordinates": "full_normalized_visible_document",
            "visible_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "risk_heading_samples": samples, "numbered_heading_samples": headings,
            "sample_limits": {"risk_headings": 8, "numbered_headings": 24}}


def topic_inspection(document, *, ticker: str, question: str) -> dict:
    """Inspect the same retained text and sentence boundaries as extraction."""
    profile = requested_risk_profile(ticker, question)
    samples = []
    if not profile:
        return {"topic_sentence_samples": samples}
    section_limit = 80_000 if ticker == "AAPL" else MAX_ISSUER_RISK_SECTION_CHARS
    for index, opening in enumerate(RISK_START.finditer(document.text)):
        if index == 64 or len(samples) == 8:
            break
        if rejected_risk_heading(document.text, opening.end(), start=opening.start()):
            continue
        closing = find_risk_closing(document.text, opening.end())
        if not closing or closing.start() - opening.end() > section_limit:
            continue
        section = document.text[opening.end():closing.start()]
        for sentence in re.finditer(r"(?:^|(?<=[.!?])\s+)([^.!?]+[.!?])", section):
            quote = sentence.group(1).strip()
            if not _has_topic_scope(quote, profile):
                continue
            offset = (opening.end() + sentence.start(1)
                      + len(sentence.group(1)) - len(sentence.group(1).lstrip()))
            samples.append({"start_offset": offset, "end_offset": offset + len(quote),
                "quote_chars": len(quote), "excerpt": quote[:900],
                "excerpt_truncated": len(quote) > 900,
                "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                "rejection_reasons": list(risk_quote_rejections(quote, profile))})
            if len(samples) == 8:
                break
    return {"text_coordinates": "retained_document_text",
            "topic_sentence_samples": samples, "sample_limit": 8}


def submission_inventory(data: dict, *, forms: list, cutoff: str) -> dict:
    """Expose array alignment and lookback counts, excluding raw SEC payloads."""
    recent = data.get("filings", {}).get("recent", {})
    names = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument")
    arrays = {name: recent.get(name, []) for name in names}
    counts = {name: len(value) if isinstance(value, list) else None for name, value in arrays.items()}
    form_list = arrays["form"] if isinstance(arrays["form"], list) else []
    dates = arrays["filingDate"] if isinstance(arrays["filingDate"], list) else []
    matching = [i for i, form in enumerate(form_list)
                if form in forms and i < len(dates) and isinstance(dates[i], str) and dates[i] >= cutoff]
    archives = data.get("filings", {}).get("files", [])
    archives = archives if isinstance(archives, list) else []
    return {"array_lengths": counts, "lookback_start": cutoff,
            "requested_form_counts": dict(Counter(form_list[i] for i in matching)),
            "matched_rows_beyond_report_date_array": sum(i >= (counts["reportDate"] or 0) for i in matching),
            "within_lookback_archive_count": sum(
                isinstance(item, dict) and isinstance(item.get("filingTo"), str)
                and item["filingTo"] >= cutoff for item in archives)}
