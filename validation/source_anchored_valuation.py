"""Compatibility imports for offline review; implementation is application-owned."""
from app.services.source_anchored_valuation import (
    _calendar, _assumption, _annual_eps_context, _source_eps, evaluate_source_anchored_scenario,
)
