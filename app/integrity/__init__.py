"""Content-integrity layer (Sprint 1B).

Shared typed contracts + validators that make the *rendered* analysis internally
consistent and evidence-aware BEFORE it reaches the frontend.  This package adds
no product features and does not touch the conviction mathematics — it reconciles
and validates fields the pipeline already produces, and fails CLOSED (qualified
fallback, never invented precision) when fields contradict each other.

Entry point: ``validate_thesis_integrity(thesis_dict)`` in ``consistency.py``.
"""
