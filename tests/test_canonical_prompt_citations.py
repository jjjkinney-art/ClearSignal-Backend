"""Prompt ranking/removal must not renumber source inspection citations."""

from app.schemas import RetrievedEvidence
from app.services.evidence_references import admit_evidence, with_canonical_citations
from app.services.thesis_synthesizer import _evidence_block


def evidence(title, date, **kwargs):
    return RetrievedEvidence(
        title=title, source="SEC EDGAR", timestamp=date,
        summary=f"{title}: Services demand update.",
        url=f"https://www.sec.gov/{title}", **kwargs,
    )


def test_removed_reference_and_prompt_sort_preserve_canonical_ids():
    blocked = evidence("Blocked", "2026-10-01", availability_status="unavailable")
    older = evidence("Older", "2026-07-01", relevance_score=0.3)
    newer = evidence("Q3 Earnings", "2026-10-02", relevance_score=1.0)
    admitted, refs, _ = admit_evidence([blocked, older, newer])
    prompt_items = with_canonical_citations(admitted, refs)
    block = _evidence_block(prompt_items)
    assert "[E1]" not in block
    assert block.index("[E3]") < block.index("[E2]")
    assert "[E3] [EARNINGS] Q3 Earnings" in block
    assert "[E2]" in block
    assert older.citation_id is None and newer.citation_id is None
    assert prompt_items[0] is not older
    assert "citation_id" not in prompt_items[0].model_dump()


def test_unmatched_prompt_source_cannot_borrow_a_canonical_id():
    item = evidence("Q3 Earnings", "2026-10-02")
    prompt_items = with_canonical_citations([item], [])
    assert "[UNATTRIBUTED]" in _evidence_block(prompt_items)
    assert "[E1]" not in _evidence_block(prompt_items)
