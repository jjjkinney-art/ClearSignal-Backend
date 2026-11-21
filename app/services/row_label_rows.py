"""Row-label evidence rows from a document the request has already read (any path: periodic filing or annual report)."""
from __future__ import annotations


def accession_from_url(url: str) -> str | None:
    try:
        compact = url.split("/")[-2]
        return f"{compact[:10]}-{compact[10:12]}-{compact[12:]}" if len(compact) == 18 and compact.isdigit() else None
    except (AttributeError, IndexError):
        return None


def label_rows_from_document(document, *, cik: str, accession: str | None, form: str, taxonomies=("us-gaap",), currencies=("USD",)) -> list[dict]:
    """One row per income-concept inline fact that has a retained row label, bound to issuer, taxonomy, unit, period, accession and document.
    Empty unless the row-label check is on (the label scan only runs then)."""
    from ..integrity.row_label_check import LABELLED_CONCEPTS, normalize_amount
    from ..providers.sec_inline_facts import validated_observation
    labels = dict(getattr(document, "inline_row_labels", ()) or ())
    contexts = dict(getattr(document, "inline_row_context", ()) or ())
    if not labels or not accession:
        return []
    rows = []
    for observation in getattr(document, "inline_xbrl_facts", ()) or ():
        label = labels.get(observation.get("fact_id"))
        if observation.get("concept") not in LABELLED_CONCEPTS or not label:
            continue
        amount = validated_observation(observation, cik=cik, concepts=(observation["concept"],), taxonomies=taxonomies, currencies=currencies)
        if amount is None:
            continue
        context = contexts.get(observation["fact_id"]) or {}
        rows.append({"cik": str(int(cik)), "taxonomy": "ifrs-full" if "ifrs" in str(observation.get("concept_namespace")) else "us-gaap",
                     "unit": observation["unit"], "concept": observation["concept"], "start": observation["start"], "end": observation["end"],
                     "abs_value": normalize_amount(amount), "signed_value": str(amount), "label": label, "cells": list(context.get("cells") or ()),
                     "restatement": bool(context.get("restatement")), "accession": accession, "form": form,
                     "document_url": getattr(document, "final_url", None), "content_hash": getattr(document, "content_hash", None),
                     "fact_id": observation["fact_id"]})
    return rows
