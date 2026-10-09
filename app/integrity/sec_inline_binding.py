"""Recheck a filing-level observation independently of its comparison prose."""
from datetime import date
from decimal import Decimal
import re
from urllib.parse import urlsplit

from .provenance import ClaimDocumentReference
from ..providers.sec_inline_facts import validated_observation


def inline_document_reference(record, *, expected_cik):
    proof = record.inline_binding
    try:
        parsed = urlsplit(record.filing_url)
        path = f'/Archives/edgar/data/{int(expected_cik)}/{record.accession.replace("-", "")}/'
        if (not isinstance(proof, dict) or parsed.scheme != 'https'
                or parsed.netloc != 'www.sec.gov' or parsed.query or parsed.fragment
                or not parsed.path.startswith(path)
                or not re.fullmatch(r'[A-Za-z0-9_.-]+\.html?', parsed.path[len(path):])
                or proof['document_url'] != record.filing_url
                or proof['filed'] != record.filed or proof['form'] != record.form
                or proof['accession'] != record.accession
                or not re.fullmatch(r'[0-9a-f]{64}', proof['content_hash'])
                or record.taxonomy != 'us-gaap' or record.unit != 'USD'
                or record.label != record.concept
                or proof['start'] != record.start or proof['end'] != record.end
                or not date.fromisoformat(record.end) <= date.fromisoformat(record.filed) <= date.today()):
            return None
        amount = validated_observation(proof, cik=expected_cik, concepts=(record.concept,))
        if amount is None or isinstance(record.value, bool) or Decimal(str(record.value)) != amount:
            return None
        return ClaimDocumentReference(
            reference_id=f'sec-inline:{record.cik}:{record.accession}:{record.concept}:{proof["content_hash"]}:{proof["fact_id"]}',
            title=f'{record.form} filed {record.filed} · {record.label}',
            provider='SEC EDGAR', url=record.filing_url, published_at=record.filed,
            content_hash=proof['content_hash'], quote=proof['literal'],
            section=f'Inline XBRL context {proof["context_id"]}')
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
