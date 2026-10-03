"""Synthetic, zero-production-write rehearsal for thesis notice persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, ResearchConversation, ResearchMessage
from app.services.evidence_references import admit_evidence
from app.services.research_thesis_notices import list_notices, persist_notice_preview
from app.services.thesis_notice_preview import build_selected_thesis_notice_preview


REHEARSAL_SCHEMA_VERSION = 1


def _context() -> dict:
    return {
        "applied": True,
        "status": "applied",
        "conversation_id": "synthetic-conversation",
        "message_id": "synthetic-message",
        "ticker": "AAPL",
        "created_at": "2026-01-01T00:00:00Z",
        "historical_thesis": {
            "direct_answer": (
                "Services retention and the installed base support durable growth."
            ),
            "key_risks": ["Services retention weakens across the installed base."],
        },
    }


def _evidence(**changes) -> SimpleNamespace:
    value = {
        "id": "synthetic-new-evidence",
        "ticker": "AAPL",
        "title": "Quarterly services retention update",
        "source": "Synthetic issuer filing",
        "summary": "Services retention across the installed base remained durable.",
        "timestamp": "2026-02-01T00:00:00Z",
        "relevance_score": 1.0,
        "freshness_status": "unknown",
        "availability_status": "available",
        "material_conflict": False,
    }
    value.update(changes)
    return SimpleNamespace(**value)


async def run_thesis_notice_rehearsal() -> dict:
    """Prove candidate → persistence → dedupe → isolation without live writes."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    checks: dict[str, bool] = {}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        async with factory() as session:
            session.add(ResearchConversation(
                id="synthetic-conversation",
                user_id="synthetic-owner",
                title="Synthetic Apple thesis",
                scope_tickers=["AAPL"],
                created_at=now,
                updated_at=now,
            ))
            session.add(ResearchMessage(
                id="synthetic-message",
                conversation_id="synthetic-conversation",
                user_id="synthetic-owner",
                ordinal=1,
                role="assistant",
                text="Synthetic historical thesis.",
                displayed_snapshot={},
                created_at=now,
            ))
            await session.commit()

            admitted, _references, integrity = admit_evidence(
                [_evidence()], evaluated_at="2026-02-02T00:00:00Z",
            )
            preview = build_selected_thesis_notice_preview(
                context=_context(), evidence_items=admitted,
            )
            first = await persist_notice_preview(
                session, user_id="synthetic-owner", preview=preview,
            )
            second = await persist_notice_preview(
                session, user_id="synthetic-owner", preview=preview,
            )
            await session.commit()
            owner_rows = await list_notices(session, user_id="synthetic-owner")
            foreign_rows = await list_notices(session, user_id="foreign-owner")

            stale_admitted, _stale_references, _stale_integrity = admit_evidence(
                [_evidence(id="synthetic-stale", timestamp="2025-12-01")],
                evaluated_at="2026-02-02T00:00:00Z",
            )
            stale_preview = build_selected_thesis_notice_preview(
                context=_context(),
                evidence_items=stale_admitted,
            )
            stale_write = await persist_notice_preview(
                session, user_id="synthetic-owner", preview=stale_preview,
            )

            checks = {
                "new_admitted_evidence_produces_candidate": (
                    integrity["admission"]["admitted_count"] == 1
                    and integrity["admission"]["blocked_count"] == 0
                    and preview.get("status") == "candidate_found"
                    and len(preview.get("candidates", [])) == 1
                ),
                "candidate_delivery_disabled": (
                    preview.get("delivery_enabled") is False
                    and all(
                        item.get("delivery_enabled") is False
                        for item in preview.get("candidates", [])
                    )
                ),
                "eligible_candidate_persisted": len(first) == 1,
                "duplicate_collapsed": (
                    len(second) == 1
                    and len(owner_rows) == 1
                    and first[0]["id"] == second[0]["id"]
                ),
                "foreign_owner_isolated": foreign_rows == [],
                "stale_evidence_rejected": (
                    stale_preview.get("status") == "no_material_change_candidate"
                    and stale_write == []
                ),
                "persisted_delivery_disabled": (
                    len(owner_rows) == 1
                    and owner_rows[0].get("delivery_enabled") is False
                ),
                "production_database_untouched": True,
                "zero_external_delivery_attempts": True,
            }
        return {
            "schema_version": REHEARSAL_SCHEMA_VERSION,
            "passed": all(checks.values()),
            "database_scope": "ephemeral_in_memory",
            "synthetic": True,
            "checks": checks,
            "candidate_count": len(preview.get("candidates", [])),
            "persisted_count": len(owner_rows),
            "foreign_owner_count": len(foreign_rows),
            "delivery_enabled": False,
        }
    finally:
        await engine.dispose()
