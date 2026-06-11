"""
Phase 9A–9G repositories — data-access layer.

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
# Phase 9G · Phase 0 — Company Dossier
from .dossier_repo import (
    get_head,
    get_or_create_head,
    upsert_head,
    get_full_dossier,
    get_debate,
    write_debate,
    update_debate_lean,
    get_dimensions,
    upsert_dimension,
    set_pending_flip,
    list_catalysts,
    append_catalyst,
    transition_catalyst,
    get_variant,
    write_variant,
    get_durability,
    write_durability,
    list_failure_modes,
    upsert_failure_mode,
)
from .dossier_revision_repo import (
    append_revision,
    get_timeline,
    append_evidence_ref,
    get_evidence_refs,
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
    # Phase 9G · Phase 0 — Dossier head + facets
    "get_head",
    "get_or_create_head",
    "upsert_head",
    "get_full_dossier",
    "get_debate",
    "write_debate",
    "update_debate_lean",
    "get_dimensions",
    "upsert_dimension",
    "set_pending_flip",
    "list_catalysts",
    "append_catalyst",
    "transition_catalyst",
    "get_variant",
    "write_variant",
    "get_durability",
    "write_durability",
    "list_failure_modes",
    "upsert_failure_mode",
    # Phase 9G · Phase 0 — Dossier audit trail
    "append_revision",
    "get_timeline",
    "append_evidence_ref",
    "get_evidence_refs",
]
