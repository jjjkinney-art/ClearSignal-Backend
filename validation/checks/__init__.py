"""Independent response-validation checks for the Sprint 2A harness.

Each module exposes a `check(thesis, fixture) -> List[Finding]` (plus, for
structure.py, a `field_presence(thesis) -> Dict[str, bool]`). These are
deliberately independent of app/integrity/* — the harness validates the
DEPLOYED backend as a black box and must keep working even if the backend's
own internal validators have a bug or are rolled back.
"""
