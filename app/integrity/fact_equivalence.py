"""When two reported facts are the same financial fact, for the cross-filing sign check.

Two observations are the same fact only when ALL of: same issuer, the same financial meaning (an explicit group below, never a lookalike
name), the same scope (consolidated, undimensioned: every retained fact is), the same attribution, the same currency/unit, and the same
period (identical start and end). Total net income (including non-controlling interests) and parent-attributable net income are different
facts and are never conflated, even when their amounts happen to match. No group says which sign is right.
"""
from __future__ import annotations

from decimal import Decimal

PRETAX_US = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"

# Each group is one financial meaning across taxonomies. A concept outside every group is equivalent only to itself.
EQUIVALENCE_GROUPS: tuple[frozenset, ...] = (
    frozenset({("us-gaap", "OperatingIncomeLoss"), ("ifrs-full", "ProfitLossFromOperatingActivities")}),          # operating result
    frozenset({("us-gaap", "ProfitLoss"), ("ifrs-full", "ProfitLoss")}),                                           # TOTAL profit or loss, incl. NCI
    frozenset({("us-gaap", "NetIncomeLoss"), ("ifrs-full", "ProfitLossAttributableToOwnersOfParent")}),            # PARENT-attributable
    frozenset({("us-gaap", PRETAX_US), ("ifrs-full", "ProfitLossBeforeTax")}),                                      # before income tax
    frozenset({("us-gaap", "Revenues"), ("ifrs-full", "Revenue")}),                                                # total revenue
    frozenset({("us-gaap", "NetCashProvidedByUsedInOperatingActivities"), ("ifrs-full", "CashFlowsFromUsedInOperatingActivities")}),
)


def meaning_key(taxonomy: str, concept: str) -> tuple:
    """The key two equivalent concepts share (a group's sorted members), or the concept itself."""
    for group in EQUIVALENCE_GROUPS:
        if (taxonomy, concept) in group:
            return ("group", tuple(sorted(group)))
    return ("concept", taxonomy, concept)


def equivalent(a: tuple, b: tuple) -> bool:
    """``a`` and ``b`` are (taxonomy, concept)."""
    return meaning_key(*a) == meaning_key(*b)


def fact_key(cik, taxonomy, concept, unit, start, end) -> tuple:
    """The identity two observations must share to be the same fact (value, sign and filing excluded)."""
    return (str(int(cik)), meaning_key(taxonomy, concept), unit, start, end)


def opposite_sign_rows(index: dict, binding: dict) -> list[dict]:
    """Indexed observations of the same fact with the same magnitude and the opposite sign, from a different accession.
    ``index`` maps fact_key -> list of {value, accession, form, filed, taxonomy, concept}."""
    try:
        value = Decimal(str(binding["amount"]))
    except Exception:
        return []
    if value == 0:
        return []
    rows = index.get(fact_key(binding["cik"], binding["taxonomy"], binding["concept"], binding["unit"], binding["start"], binding["end"]), ())
    return [r for r in rows if r["accession"] != binding["accession"] and Decimal(str(r["value"])) == -value]
