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
                    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                    # ifrs-full: operating profit, profit before tax, profit attributable to the parent's owners
                    "ProfitLossFromOperatingActivities", "ProfitLossBeforeTax", "ProfitLossAttributableToOwnersOfParent"}
LABELLED_CONCEPTS = frozenset(_INCOME_CONCEPTS)
MEANING = {"OperatingIncomeLoss": "operating income or loss",
           "NetIncomeLoss": "net income or loss", "ProfitLoss": "net income or loss",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "income or loss before income taxes",
           "ProfitLossFromOperatingActivities": "operating profit or loss", "ProfitLossBeforeTax": "profit or loss before tax",
           "ProfitLossAttributableToOwnersOfParent": "profit or loss attributable to the owners of the parent"}


def normalize_amount(value) -> str | None:
    try:
        return format(abs(Decimal(str(value))).normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return None


def judge_label(concept: str, label: str | None, value, *, cells=(), restatement: bool = False) -> tuple[str, str | None]:
    """(verdict, code) for one retained row.

    contradicted  expense_row: an expense-only label on an income/loss result; loss_row_positive_value: a loss-only label on a positive
                  income value in an ordinary statement.
    ambiguous     the row cannot say what the figure is, so it is left unresolved (never withheld, never counted as clear):
                  ambiguous_mixed_label: the label (or another lettered cell of the same row) names both an expense and a result;
                  ambiguous_restatement_column: a loss-only label on a positive value inside a restatement table, where the same row label
                  covers columns of opposite sign ("as previously reported", "adjustment", "as restated").
    consistent    anything else, including a row labelled as income with a negative value (ordinary presentation).
    """
    if concept not in _INCOME_CONCEPTS or not isinstance(label, str) or not label.strip():
        return "consistent", None
    others = [c for c in cells if isinstance(c, str) and c.strip() and c.strip() != label.strip()]
    if _EXPENSE_WORD.search(label) and _RESULT_WORD.search(label):
        return "ambiguous", "ambiguous_mixed_label"
    if _EXPENSE_WORD.search(label):
        if any(_RESULT_WORD.search(c) and not _EXPENSE_WORD.search(c) for c in others):
            return "ambiguous", "ambiguous_mixed_label"
        return "contradicted", "expense_row"
    try:
        positive = Decimal(str(value)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return "consistent", None
    if positive and _LOSS_WORD.search(label) and not _INCOME_WORD.search(_TAX_PHRASE.sub(" ", label)):
        return ("ambiguous", "ambiguous_restatement_column") if restatement else ("contradicted", "loss_row_positive_value")
    return "consistent", None


def label_contradicts(concept: str, label: str | None, value, *, cells=(), restatement: bool = False) -> str | None:
    """The contradiction code, or None when the row is consistent OR unresolved (see judge_label)."""
    verdict, code = judge_label(concept, label, value, cells=cells, restatement=restatement)
    return code if verdict == "contradicted" else None


# --------------------------------------------------------------------------------------------------
# Binding: a label judges a figure only when it belongs to the same issuer, taxonomy, concept, unit, period,
# accession and retained document. Evidence from another filing is a separate, named kind of evidence.
# --------------------------------------------------------------------------------------------------

_ACCESSION = re.compile(r"sec:(\d+):(\d{10}-\d{2}-\d{6}):([A-Za-z0-9-]+):([A-Za-z0-9]+)\Z")


def binding_from_claim(claim: dict, cik: str) -> dict | None:
    """What a verified claim is: issuer, taxonomy, concept, unit, period, amount, cited accession and (inline) document hash.
    None when the claim does not carry enough to be bound (it is then never judged against a label)."""
    try:
        metric = str(claim["metric"])
        taxonomy, _, concept = metric.partition(":")
        ref = claim.get("document_ref") or {}
        inline = claim.get("inline_binding")
        if isinstance(inline, dict):
            accession, content_hash = inline.get("accession"), inline.get("content_hash")
        else:
            match = _ACCESSION.fullmatch(str(ref.get("reference_id", "")))
            accession, content_hash = (match.group(2) if match else None), None
            if match and int(match.group(1)) != int(cik):
                return None
        if not (taxonomy and concept and accession and claim.get("unit") and claim.get("period_end")):
            return None
        return {"cik": str(int(cik)), "taxonomy": taxonomy, "concept": concept, "unit": claim["unit"], "start": claim.get("period_start"),
                "end": claim["period_end"], "amount": claim.get("raw_value"), "abs_value": normalize_amount(claim.get("raw_value")),
                "accession": accession, "content_hash": content_hash}
    except (KeyError, TypeError, ValueError):
        return None


def _same_fact(binding: dict, row: dict) -> bool:
    return (str(row.get("cik")) == binding["cik"] and row.get("taxonomy") == binding["taxonomy"] and row.get("concept") == binding["concept"]
            and row.get("unit") == binding["unit"] and row.get("start") == binding["start"] and row.get("end") == binding["end"]
            and row.get("abs_value") == binding["abs_value"])


def assess(binding: dict, rows) -> dict:
    """Judge one bound figure against the label rows retained in the request.

    status
      contradicted           the cited filing's own retained row (same accession, same document) contradicts the figure.
      cross_filing_conflict  no retained row of the cited filing, and a different retained filing labels the same fact in a way that
                             contradicts it. That row is not the cited row; the conflict is stated as such and the figure is not used.
      clear                  the cited filing's own retained row is consistent: the check was completed.
      other_filing_only      only other filings' rows were retained and none contradicts: the cited row was NOT checked.
      no_evidence            nothing retained for this fact: the cited row was NOT checked.
      ambiguous              the cited filing's own row cannot say what the figure is (a mixed expense/result label, or a restatement column): the
                             meaning is unresolved, so the figure is neither withheld nor counted as checked.
    ``other_filings`` lists what other filings said (never used as the cited row)."""
    same = [row for row in rows if _same_fact(binding, row)]
    cited = [row for row in same if row.get("accession") == binding["accession"]
             and (not binding.get("content_hash") or not row.get("content_hash") or row["content_hash"] == binding["content_hash"])]
    others = [row for row in same if row not in cited]

    def judged(row):
        verdict, code = judge_label(binding["concept"], row.get("label"), binding["amount"], cells=row.get("cells") or (),
                                    restatement=bool(row.get("restatement")))
        return {"row": row, "verdict": verdict, "code": code if verdict == "contradicted" else None, "unresolved": code if verdict == "ambiguous" else None}
    cited_j, other_j = [judged(r) for r in cited], [judged(r) for r in others]
    result = {"binding": binding, "other_filings": [{"accession": j["row"].get("accession"), "form": j["row"].get("form"),
                                                       "label": j["row"].get("label"), "contradicts": j["code"], "unresolved": j["unresolved"]} for j in other_j]}
    if any(j["code"] for j in cited_j):
        first = next(j for j in cited_j if j["code"])
        return {**result, "status": "contradicted", "code": first["code"], "row": first["row"]}
    if any(j["unresolved"] for j in cited_j):
        first = next(j for j in cited_j if j["unresolved"])
        return {**result, "status": "ambiguous", "code": first["unresolved"], "row": first["row"]}
    if cited_j:
        return {**result, "status": "clear", "row": cited_j[0]["row"]}
    if any(j["code"] for j in other_j):
        first = next(j for j in other_j if j["code"])
        return {**result, "status": "cross_filing_conflict", "code": first["code"], "row": first["row"]}
    return {**result, "status": "other_filing_only" if other_j else "no_evidence"}


# Statuses that withhold the figure; the rest let it stand, and only "clear" means the cited row was actually checked.
WITHHOLD = frozenset({"contradicted", "cross_filing_conflict"})
COMPLETED = frozenset({"clear", "contradicted"})
UNRESOLVED = frozenset({"ambiguous"})                    # evidence exists but cannot decide; distinct from contradicted and from unavailable
UNAVAILABLE = frozenset({"other_filing_only", "no_evidence", "unbound_claim"})
