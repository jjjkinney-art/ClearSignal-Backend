"""Reviewed, document-specific predecessor context; never ticker inheritance.

The SEC directory remains authoritative for the current issuer. This registry
permits one historical annual report after a documented parent reorganization.
It does not authorize other predecessor filings, subsidiaries, metrics or debt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..schemas import RetrievedEvidence


@dataclass(frozen=True)
class ReviewedSuccession:
    ticker: str
    subject_cik: str
    subject_name: str
    source_cik: str
    source_name: str
    effective_at: str
    continuity_filed_at: str
    succession_url: str
    continuity_url: str
    annual_url: str
    annual_filed_at: str
    annual_period_end: str

    def provenance(self) -> dict:
        return {
            "registry_id": "xom-redomiciliation-2026-v1",
            "relationship": "reviewed_predecessor_context",
            "subject_issuer": {"ticker": self.ticker, "cik": self.subject_cik,
                               "name": self.subject_name},
            "source_issuer": {"cik": self.source_cik, "name": self.source_name},
            "effective_at": self.effective_at,
            "available_at": self.continuity_filed_at,
            "sources": [
                {"url": self.succession_url, "report_date": self.effective_at,
                 "document_type": "8-K12B", "section": "Explanatory Note"},
                {"url": self.continuity_url, "filed_at": self.continuity_filed_at,
                 "document_type": "10-Q", "section": "Note 1. Basis of Financial Statement Preparation"},
            ],
            "use": "historical_risk_context_only",
        }


_XOM = ReviewedSuccession(
    ticker="XOM", subject_cik="2115436", subject_name="ExxonMobil Holdings Corporation",
    source_cik="34088", source_name="Exxon Mobil Corporation",
    effective_at="2026-07-01", continuity_filed_at="2026-08-03",
    succession_url="https://www.sec.gov/Archives/edgar/data/2115436/000119312526291990/d71068d8k12b.htm",
    continuity_url="https://www.sec.gov/Archives/edgar/data/2115436/000003408826000093/R9.htm",
    annual_url="https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/xom-20251231.htm",
    annual_filed_at="2026-02-18", annual_period_end="2025-12-31",
)


def reviewed_succession(ticker: str, *, as_of: date | None = None) -> ReviewedSuccession | None:
    """Require exact current SEC identity and already-public relationship proof."""
    if ticker != _XOM.ticker or (as_of or date.today()) < date.fromisoformat(_XOM.continuity_filed_at):
        return None
    from . import issuer_identity
    try:
        issuer = issuer_identity._load_directory().symbols.get(ticker)
    except Exception:
        return None
    if (issuer is None or issuer.cik != _XOM.subject_cik.zfill(10)
            or issuer_identity.name_key(issuer.name) != issuer_identity.name_key(_XOM.subject_name)):
        return None
    return _XOM


def authorized_predecessor(ticker: str, *, current_cik: str, url: str,
                           form: str, filed_at: str, provenance: object) -> dict | None:
    """Revalidate against the registry, not a provider's asserted relationship."""
    relationship = reviewed_succession(ticker)
    if (relationship is None or current_cik != relationship.subject_cik
            or url != relationship.annual_url or form != "10-K"
            or filed_at != relationship.annual_filed_at
            or provenance != relationship.provenance()):
        return None
    return relationship.provenance()


def item_predecessor_provenance(item: object) -> dict | None:
    """Expose only a canonical relationship tied to this source and its date."""
    values = getattr(item, "risk_disclosures", [])
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    value = values[0]
    provenance = value.get("issuer_relationship")
    ref = value.get("document_ref")
    if not isinstance(provenance, dict) or not isinstance(ref, dict):
        return None
    subject = provenance.get("subject_issuer")
    if (not isinstance(subject, dict) or ref.get("url") != getattr(item, "url", None)
            or ref.get("published_at") != getattr(item, "timestamp", None)
            or getattr(item, "filed_at", None) != getattr(item, "timestamp", None)):
        return None
    return authorized_predecessor(value.get("ticker"), current_cik=subject.get("cik"),
        url=ref.get("url"), form=getattr(item, "document_type", None),
        filed_at=ref.get("published_at"), provenance=provenance)


def reviewed_predecessor_annual(ticker: str) -> tuple[RetrievedEvidence, dict] | None:
    """One explicit fallback candidate; the normal SEC search stays exact-CIK."""
    relationship = reviewed_succession(ticker)
    if relationship is None:
        return None
    return RetrievedEvidence(
        title=f"{relationship.source_name} — predecessor 10-K",
        source="SEC EDGAR", summary="Reviewed predecessor annual filing metadata.",
        timestamp=relationship.annual_filed_at, url=relationship.annual_url,
        document_type="10-K", filed_at=relationship.annual_filed_at,
        reporting_period_end=relationship.annual_period_end,
        source_type="regulatory_filing", source_tier="primary", claim_type="filing_metadata",
    ), relationship.provenance()
