"""Conservative US-GAAP display semantics; source labels remain on bound claims.

Do not infer an issuer's income-statement line composition from a broad concept.
See docs/SEC_METRIC_LABEL_SEMANTICS.md for authoritative references and limits.
"""


def metric_label(name: str, concept: str) -> str:
    return {
        "NetIncomeLoss": "net income attributable to parent",
        "ProfitLoss": "net income including noncontrolling interests",
        "Revenues": "revenue (as reported)",
        "RevenueFromContractWithCustomerExcludingAssessedTax":
            "revenue from contracts with customers excluding assessed taxes",
        "RevenuesNetOfInterestExpense": "revenue net of interest expense",
    }.get(concept, name)


def income_attribution(concept: str) -> str | None:
    return {
        "NetIncomeLoss": "attributable_to_parent",
        "ProfitLoss": "including_noncontrolling_interests",
    }.get(concept)
