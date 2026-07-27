"""Shared tolerant-lookup helpers for the validation checks.

The deployed backend's exact field names have drifted across sprints (e.g.
`bull_thesis` vs a legacy `bull_case`), so every check looks up several
candidate keys rather than assuming one canonical name — the validator must
not crash or misreport just because of a naming variant.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def get(d: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def get_list(d: Dict[str, Any], *keys: str) -> List[Any]:
    for k in keys:
        if isinstance(d, dict) and isinstance(d.get(k), list) and d[k]:
            return d[k]
    return []


def get_text(*vals: Any) -> str:
    """Flatten strings/lists into one lowercase-searchable text blob."""
    out = []
    for v in vals:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(str(x) for x in v if isinstance(x, (str, int, float)))
        elif isinstance(v, dict):
            out.extend(str(x) for x in v.values() if isinstance(x, (str, int, float)))
    return " \n ".join(out)


def as_number(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None
