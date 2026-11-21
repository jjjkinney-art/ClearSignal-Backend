"""Does the filing's own row label contradict the meaning of the tag its figure carries?

The check reads only a label already retained from a filing the request has read. It never supplies a replacement
figure and never infers a sign from another measure: a disputed measure is withheld, nothing more.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_EXPENSE_WORD = re.compile(r"\b(?:expenses?|costs?)\b", re.I)
_RESULT_WORD = re.compile(r"\b(?:income|loss(?:es)?|profit|earnings|gain|result|surplus|deficit)\b", re.I)
_LOSS_WORD = re.compile(r"\bloss(?:es)?\b", re.I)
_INCOME_WORD = re.compile(r"\b(?:income|profit|earnings|gain)\b", re.I)
# Tax wording names the tax, not the result: "Loss before taxes on income" is a loss row, "Income before income taxes" is not.
_TAX_PHRASE = re.compile(r"\b(?:before\s+)?(?:income\s+)?tax(?:es)?(?:\s+on\s+(?:income|profit|earnings))?\b", re.I)
# Concepts whose natural sign is income-positive (a loss is a negative value).
_INCOME_CONCEPTS = {"OperatingIncomeLoss", "NetIncomeLoss", "ProfitLoss",
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"}
MEANING = {"OperatingIncomeLoss": "operating income or loss",
           "NetIncomeLoss": "net income or loss", "ProfitLoss": "net income or loss",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "income or loss before income taxes"}


def normalize_amount(value) -> str | None:
    try:
        return format(abs(Decimal(str(value))).normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return None


def label_contradicts(concept: str, label: str | None, value) -> str | None:
    """A reason code when the row label contradicts the concept's meaning, else None.

    expense_row               the concept is an income/loss result and the row is an expense line with no result word
                              ("OPERATING EXPENSES" tagged OperatingIncomeLoss).
    loss_row_positive_value   the row is labelled only as a loss, but the tagged value is positive income.
    A row labelled as income with a negative value is NOT disputed: negative income is ordinary presentation.
    """
    if concept not in _INCOME_CONCEPTS or not isinstance(label, str) or not label.strip():
        return None
    if _EXPENSE_WORD.search(label) and not _RESULT_WORD.search(label):
        return "expense_row"
    try:
        positive = Decimal(str(value)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return None
    if positive and _LOSS_WORD.search(label) and not _INCOME_WORD.search(_TAX_PHRASE.sub(" ", label)):
        return "loss_row_positive_value"
    return None
