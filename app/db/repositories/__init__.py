"""
Phase 9A repositories — data-access layer.

Repositories encapsulate all SQLAlchemy queries.  Each repository
function accepts an AsyncSession and returns plain Python objects.

All functions guard against ``session is None`` so callers need only
write ``if session is None: return`` when using ``get_session()``.
"""

from .thesis_repo import (
    create_version,
    get_latest_version,
    create_delta,
    get_evolution,
)
from .memory_repo import (
    get_or_create_memory,
    append_entry,
    get_history,
)
from .concern_repo import (
    upsert_tag,
    get_tags_for_ticker,
)
from .evolution_repo import (
    get_evolution_with_versions,
    get_delta_full,
    get_latest_change_card,
    get_material_changes_feed,
    create_delta_with_debounce,
)

__all__ = [
    # Phase 9A
    "create_version",
    "get_latest_version",
    "create_delta",
    "get_evolution",
    "get_or_create_memory",
    "append_entry",
    "get_history",
    "upsert_tag",
    "get_tags_for_ticker",
    # Phase 9B
    "get_evolution_with_versions",
    "get_delta_full",
    "get_latest_change_card",
    "get_material_changes_feed",
    "create_delta_with_debounce",
]
