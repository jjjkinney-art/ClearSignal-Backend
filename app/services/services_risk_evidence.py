"""Compatibility entry points for the reviewed Apple Services risk topic."""
from .issuer_risk_evidence import (
    bound_issuer_risk, extract_issuer_risk_evidence, requested_risk_profile, risk_summary,
)


def requests_services_operating_risk(question: str) -> bool:
    return requested_risk_profile("AAPL", question) is not None


def extract_services_risk_evidence(document, *, ticker: str):
    if str(ticker).strip().upper() != "AAPL":
        return []
    return extract_issuer_risk_evidence(document, ticker=ticker, question="Services operating risks")


def bound_services_risk(item, *, ticker: str):
    if ticker != "AAPL":
        return None
    return bound_issuer_risk(item, ticker=ticker, question="Services operating risks")
