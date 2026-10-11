"""Profitability scope from independently rebuilt, selected comparisons.

An unavailable measure is not evidence that an issuer omitted it. Pretax income
remains supplementary and cannot alone satisfy a general profitability request.
"""
from .financial_thesis_foundation import CORE_METRICS, SUPPLEMENTARY_METRICS, _rebuild
from .providers.sec_provider import _load_ticker_cik_map


def profitability_coverage(ticker, selected_items, claims):
    try:
        cik = _load_ticker_cik_map().get(ticker)
    except Exception:
        cik = None
    metrics = {name: CORE_METRICS[name] for name in ("operating income", "net income")}
    metrics.update(SUPPLEMENTARY_METRICS)
    coverage = []
    for name, concepts in metrics.items():
        qualified = []
        if isinstance(cik, str) and cik.isdigit():
            for item, claim in zip(selected_items, claims):
                rebuilt = _rebuild(item, ticker=ticker, cik=cik, name=name, concepts=concepts)
                if rebuilt is not None:
                    qualified.append((rebuilt, claim["reference_id"]))
        signatures = {repr(item.verified_claims) for item, _ in qualified}
        status = ("verified_comparison" if len(signatures) == 1 else
                  "conflicting_comparisons" if signatures else "not_verified")
        coverage.append({"metric": name, "status": status,
                         "reference_ids": list(dict.fromkeys(ref for _, ref in qualified))})
    return coverage
