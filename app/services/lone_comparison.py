"""A partial answer built on one verified annual comparison, with the specific reason each other measure was not compared.

Default off (``lone_comparison_enabled``). Until now the financial foundation needed two comparisons; a loss-making
issuer whose operating income, net income and operating cash flow are negative kept only its revenue pair, which was
dropped, and the answer said a comparison "could not be used in this answer" without saying why. This module only
words the reasons the comparison builder already recorded; it adds no figure, and states nothing about the issuer
beyond what the withheld reason is.
"""
from __future__ import annotations

# reason recorded by the as-reported builder (or the foundation) -> plain wording, with no number and no claim about the issuer
REASON_WORDS = {
    "non_positive_value": ("at least one of its two annual amounts is zero or negative, and this version does not express a "
                           "percentage change on a zero or negative base"),
    "prior_value_zero": "its prior-year amount is zero, so no percentage change can be calculated",
    "periods_not_comparable": "its current and prior periods do not cover the same length of time",
    "no_comparable_prior_year_period": "no comparable prior-year period was reported for it",
    "ambiguous_current_observation": "more than one differing current-period amount was reported, so none was chosen",
    "ambiguous_prior_observation": "more than one differing prior-period amount was reported, so none was chosen",
    "claim_binding_failed": "its figures could not be tied to the SEC filing they come from",
    "stale_relative_to_latest_balance_sheet": "its latest annual period is older than the issuer's latest reported annual balance sheet",
    "older_period_than_other_measures": "its latest annual period is older than the period of the measure shown",
    "concept_not_reported": "the issuer's SEC data did not report this measure under the concepts this version reads",
    "no_annual_facts": "no annual-form facts were found in the issuer's SEC data",
    "ambiguous_basis_or_currency": "the SEC data mixed accounting bases or currencies for the latest annual period",
}
GENERIC = "no verified comparison for the latest annual period was available"


def enabled() -> bool:
    from ..config import settings
    return getattr(settings, "lone_comparison_enabled", False) is True


def reason_for(metric: str, withheld) -> str:
    for row in withheld or []:
        if isinstance(row, dict) and row.get("metric") == metric:
            return REASON_WORDS.get(str(row.get("reason")), GENERIC)
    return GENERIC


def section(shown: str, missing: list[str], withheld) -> str:
    """The text added after the reported comparison when only one measure could be compared."""
    lines = [f"- {name}: not compared; {reason_for(name, withheld)}." for name in missing]
    body = "\n".join(lines) if lines else "- no other measure was available"
    return ("\n\nWhat was not compared, and why\n" + body +
            f"\nOnly one measure ({shown}) could be compared, so this is not a multi-dimensional financial case. It says "
            "nothing about profitability or cash generation.")
