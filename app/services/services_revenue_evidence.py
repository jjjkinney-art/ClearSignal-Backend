"""Services revenue from explicit quarterly SEC table columns, never prose guesses."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from ..integrity.provenance import ClaimDocumentReference, Provenance, QuantitativeClaim
from ..schemas import RetrievedEvidence
from .public_document_ingestion import DocumentTable, PublicDocument


def requests_services_revenue(question: str) -> bool:
    return bool(
        re.search(r"\bservices\b", question or "", re.IGNORECASE)
        and re.search(r"\b(?:revenues?|net sales|growth|thesis|outlook)\b",
                      question or "", re.IGNORECASE)
    )


def _compact(row: tuple[str, ...]) -> list[str]:
    return [re.sub(r"\s+", " ", cell).strip() for cell in row if cell.strip()]


def _date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except ValueError:
        return None


def _layout(table: DocumentTable) -> tuple[list[str], list[date], bool] | None:
    """Support quarter/prior quarter, optionally followed by six/nine months.

    Do not infer a period from a preceding table or from numeric position alone.
    """
    durations: list[str] = []
    for row in table.rows:
        cells = _compact(row)
        if cells and cells[0].lower() == "three months ended":
            durations = [cell.lower() for cell in cells]
            continue
        if not durations:
            continue
        dates = [_date(cell) for cell in cells if cell.lower() != "change"]
        if (not dates or any(value is None for value in dates)
                or len(dates) not in {2, 4}):
            if cells:
                return None
            continue
        if durations not in (["three months ended"],
                             ["three months ended", "six months ended"],
                             ["three months ended", "nine months ended"]):
            return None
        if len(dates) != 2 * len(durations):
            return None
        change = len(cells) != len(dates)
        expected = []
        for _ in range(len(dates) // 2):
            expected.extend(["date", "date"])
            if change:
                expected.append("change")
        actual = ["date" if _date(cell) else cell.lower() for cell in cells]
        if actual != expected:
            return None
        return cells, dates, change
    return None


def _row_values(cells: list[str]) -> list[tuple[Decimal, bool]] | None:
    values: list[tuple[Decimal, bool]] = []
    for cell in cells:
        if cell == "$":
            continue
        if cell == "%":
            if not values or values[-1][1]:
                return None
            values[-1] = (values[-1][0], True)
            continue
        number_pattern = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
        match = re.fullmatch(rf"(-?{number_pattern}|\(\s*{number_pattern}\s*\))(%?)", cell)
        if not match:
            return None
        number = match.group(1).replace(",", "").replace(" ", "")
        if number.startswith("("):
            number = "-" + number[1:-1]
        values.append((Decimal(number), bool(match.group(2))))
    return values


def _claim(document: PublicDocument, table: DocumentTable, *, ticker: str,
           metric: str, amount: Decimal, unit: str, period: date,
           quote: str) -> dict:
    value_text = f"${amount:,.0f}" if unit == "USD" else f"{amount}%"
    reference = ClaimDocumentReference(
        reference_id=f"document:{document.content_hash}:table:{table.table_number}:{metric}:{period}",
        title=document.title or document.document_type or "SEC filing",
        provider=document.publisher or "SEC EDGAR", url=document.final_url,
        published_at=document.published_at, section=f"HTML table {table.table_number}",
        content_hash=document.content_hash, quote=quote,
    )
    claim = QuantitativeClaim(
        value_text=value_text, provenance=Provenance.REPORTED,
        as_of=period.isoformat(), confidence="high", raw_value=float(amount),
        unit=unit, source=document.document_type, ticker=ticker,
        metric=metric, document_ref=reference,
    ).to_dict()
    claim.update(reporting_period_end=period.isoformat(), period_end=period.isoformat(),
                 duration_months=3, scope="Services")
    return claim


def extract_services_revenue_evidence(
    document: PublicDocument, *, ticker: str,
) -> list[RetrievedEvidence]:
    """Return dated amounts and explicitly reported growth, or no evidence.

    Initial issuer coverage is Apple (SEC CIK 320193), whose statements use USD.
    Only the recognized quarterly net-sales layout is supported. Annual-only,
    mixed units, missing dates, cost-of-sales and conflicting rows fail closed.
    """
    ticker = ticker.upper().strip()
    parsed_url = urlsplit(document.final_url)
    if (ticker != "AAPL"
            or not document.text_ready or document.extraction_method != "html"
            or document.source_tier != "primary"
            or document.source_type != "regulatory_filing"
            or document.document_type not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}
            or parsed_url.scheme != "https" or parsed_url.username or parsed_url.password
            or parsed_url.hostname != "www.sec.gov"
            or not re.match(r"^/Archives/edgar/data/320193/\d+/", parsed_url.path)
            or not re.fullmatch(r"[0-9a-f]{64}", document.content_hash)):
        return []
    try:
        published = date.fromisoformat(document.published_at or "")
    except ValueError:
        return []
    candidates: list[RetrievedEvidence] = []
    for table in document.tables:
        layout = _layout(table)
        # Context supplies units; a dollar cell in the table establishes USD.
        units = re.findall(r"\(([^)]*\b(?:millions|thousands|billions)[^)]*)\)",
                           table.context, re.IGNORECASE)
        if (not layout or not units or "millions" not in units[-1].lower()
                or re.search(r"\b(?:thousands|billions)\b", units[-1], re.IGNORECASE)
                or not any("$" in row for row in table.rows)):
            continue
        headers, periods, change = layout
        current, prior = periods[:2]
        if (current > published or current.year != prior.year + 1
                or current.month != prior.month or abs(current.day - prior.day) > 7):
            continue
        context = table.context.lower()
        if re.search(r"\b(?:forecast|guidance|pro forma)\b", context):
            continue
        group = "net sales" if re.search(r"\b(?:net sales|revenue)\b", context) else ""
        for row in table.rows:
            cells = _compact(row)
            if not cells:
                continue
            if len(cells) == 1 and cells[0].endswith(":"):
                group = cells[0][:-1].lower()
                continue
            if cells[0].lower() != "services" or group not in {"net sales", "revenue"}:
                continue
            values = _row_values(cells[1:])
            if not values or len(values) != len(headers):
                continue
            expected_percent = [cell.lower() == "change" for cell in headers]
            if [percent for _, percent in values] != expected_percent:
                continue
            current_amount, prior_amount = values[0][0], values[1][0]
            if current_amount < 0 or prior_amount <= 0:
                continue
            # All currencies are reported in millions, including the prior.
            quote = " ".join(cells)
            if len(quote) > 300:
                continue
            claims = [_claim(
                document, table, ticker=ticker, metric="issuer:Services net sales",
                amount=amount * Decimal(1_000_000), unit="USD", period=period,
                quote=quote,
            ) for amount, period in ((current_amount, current), (prior_amount, prior))]
            candidates.append(RetrievedEvidence(
                title=f"{ticker} Services net sales · quarter ended {current}",
                source="SEC EDGAR", summary=(
                    f"{ticker} reported Services net sales of ${current_amount:,} million "
                    f"for the three months ended {current}, compared with "
                    f"${prior_amount:,} million for the three months ended {prior}. "
                    "These are reported historical amounts, not a forecast."
                ), timestamp=document.published_at, url=document.final_url,
                relevance_score=0.98, source_type="regulatory_filing", source_tier="primary",
                claim_type="reported_fact", document_type=document.document_type,
                reporting_period_end=current.isoformat(), filed_at=document.published_at,
                section=f"HTML table {table.table_number}", extraction_method="html",
                verified_claims=claims,
            ))
            if change:
                growth = values[2][0]
                actual = (current_amount / prior_amount - 1) * 100
                # Reject a mismatched change column; do not silently relabel a
                # currency amount or year-to-date percentage as quarter growth.
                tolerance = Decimal("0.6") if growth == growth.to_integral() else Decimal("0.06")
                if abs(growth - actual) > tolerance:
                    continue
                candidates.append(RetrievedEvidence(
                    title=f"{ticker} Services net sales growth · quarter ended {current}",
                    source="SEC EDGAR", summary=(
                        f"{ticker} reported a {growth}% year-over-year change in Services "
                        f"net sales for the three months ended {current}, compared with "
                        f"the three months ended {prior}. This is the filing's reported "
                        "change, not a forecast or proof that growth will persist."
                    ), timestamp=document.published_at, url=document.final_url,
                    relevance_score=0.98, source_type="regulatory_filing", source_tier="primary",
                    claim_type="reported_fact", document_type=document.document_type,
                    reporting_period_end=current.isoformat(), filed_at=document.published_at,
                    section=f"HTML table {table.table_number}", extraction_method="html",
                    verified_claims=[_claim(
                        document, table, ticker=ticker, metric="issuer:Services net sales growth",
                        amount=growth, unit="%", period=current, quote=quote,
                    )],
                ))
    # Repeated disclosures must agree. Reject the entire metric when any table
    # disagrees about the same quarter; otherwise preserve the first anchor.
    grouped: dict[tuple[str, str], list[RetrievedEvidence]] = {}
    for item in candidates:
        key = (item.verified_claims[0]["metric"], item.reporting_period_end or "")
        grouped.setdefault(key, []).append(item)
    evidence = []
    for items in grouped.values():
        identities = {tuple((claim["reporting_period_end"], claim["raw_value"], claim["unit"])
                            for claim in item.verified_claims) for item in items}
        if len(identities) != 1:
            return []
        evidence.append(items[0])
    if not evidence:
        return []
    newest = max(item.reporting_period_end for item in evidence)
    return [item for item in evidence if item.reporting_period_end == newest]
