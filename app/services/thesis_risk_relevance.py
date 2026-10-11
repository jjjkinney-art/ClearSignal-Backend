"""Shared broad-thesis sample eligibility; no risk ranking or materiality claim."""
import re

_GENERIC_RISK_INTRODUCTION = re.compile(
    r"^(?:(?:Any|All|Some|One|Each)\s+(?:of\s+)?(?:the\s+|these\s+|our\s+)?"
    r"(?:risk factors|risks)\s+(?:discussed|described|listed|set forth)\s+"
    r"(?:above|below|herein)\b|"
    r"(?:Additional|Other) risks and uncertainties not "
    r"(?:presently|currently) known to us\b|"
    r"Our operations and financial results are subject to "
    r"(?:various|certain) risks and uncertainties,? including those described below\b)", re.I)
_UNRESOLVED_RISK_SUBJECT = re.compile(
    r"^(?:(?:Furthermore|Moreover|However|In addition|As a result|Consequently),?\s+)?"
    r"(?:our (?:actions|efforts|measures)|(?:these|such) (?:actions|efforts|measures|risks|factors))"
    r"\s+(?:may|could|might|can)\b", re.I)



def eligible_thesis_risk_quote(quote: object) -> bool:
    """Require the existing self-contained mechanism before the sample cap."""
    return (isinstance(quote, str) and not _GENERIC_RISK_INTRODUCTION.match(quote)
            and not _UNRESOLVED_RISK_SUBJECT.match(quote))
