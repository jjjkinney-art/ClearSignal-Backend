"""
Phase 9G · Slice 5B — 3-way evaluation harness.

For each golden case the harness assembles ONE controlled synthesis prompt and
runs it under three conditions that differ by EXACTLY the injected prior block:

  * **OFF**    — no block injected (byte-identical to pre-injection synthesis);
  * **TRUE**   — the real Slice-5A formatter block built from the ticker's dossier;
  * **POISON** — the same formatter applied to an adversarial prior that
                 contradicts this cycle's evidence.

Holding the question + fresh evidence constant and varying only the prior is the
correct controlled design for an anchoring study: any change in the conclusion is
attributable to the injected prior, not to evidence drift.

Safety invariants (asserted by the test suite):
  * the harness NEVER reads or sets the production injection-enable / shadow
    settings and never calls the production ask route — it builds prompts
    in-process and (optionally) calls the model client directly;
  * OFF injects zero bytes;
  * OFF / TRUE / POISON prompts are identical outside the injected block region.

The LLM call is optional: with no ``OPENAI_API_KEY`` the harness still builds and
sizes every prompt (mechanical gates run) and marks the behavioural fields
skipped, so the green test suite is fully offline.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.dossier_injection_service import (
    InjectionConfig,
    build_injection_block,
    count_tokens,
)

from .golden_set import (
    NOW,
    GOLDEN_CASES,
    DOSSIER_FIXTURES,
    GoldenCase,
    opposite_direction,
)
from .poison import build_poison_dossier

OFF = "OFF"
TRUE = "TRUE"
POISON = "POISON"
CONDITIONS = [OFF, TRUE, POISON]

SYNTHESIS_SYSTEM_PROMPT = (
    "You are a senior investment analyst. You reason from THIS CYCLE'S EVIDENCE "
    "first. Any prior dossier provided is a starting point to confirm or revise, "
    "never a fact to repeat. When fresh evidence conflicts with a prior, the "
    "evidence governs and you must say so."
)

# ── Block-region sentinels (so the test suite can prove OFF/TRUE/POISON differ
#    ONLY inside this region) ──────────────────────────────────────────────────
_BLOCK_OPEN = "<<<PRIOR_DOSSIER>>>"
_BLOCK_CLOSE = "<<<END_PRIOR_DOSSIER>>>"

_OUTPUT_CONTRACT = """Return ONLY a single JSON object, no markdown, in this exact shape:
{
  "stance": "bullish" | "bearish" | "neutral",
  "direct_answer": "2-4 sentences answering the exact question from the evidence",
  "conclusion": "1-3 sentences stating where you land and why",
  "prior_challenged": true | false,
  "prior_challenge_note": "if a prior was supplied: state the strongest reason this cycle's evidence makes it wrong, or why it survived; else empty",
  "change_vector": "what changed vs any supplied prior this cycle; else empty"
}"""


def assemble_prompt(case: GoldenCase, block_str: str) -> str:
    """Controlled synthesis prompt. Identical across conditions except the
    sentinel-delimited block region (empty for OFF)."""
    block_region = ""
    if block_str:
        block_region = f"{_BLOCK_OPEN}\n{block_str}\n{_BLOCK_CLOSE}\n\n"
    return (
        "CRITICAL OUTPUT RULES — READ FIRST:\n"
        "- Return ONLY one valid JSON object. No prose, no markdown fences.\n\n"
        f"{block_region}"
        f"COMPANY: {case.ticker}\n\n"
        f"USER QUESTION:\n{case.question}\n\n"
        "THIS CYCLE'S EVIDENCE (authoritative — reason from this first):\n"
        f"{case.evidence}\n\n"
        f"{_OUTPUT_CONTRACT}\n"
    )


def _block_for(
    case: GoldenCase,
    condition: str,
    now: datetime,
    config: InjectionConfig,
):
    """Return the InjectionResult (or None) for a case under a condition."""
    if condition == OFF:
        return None
    dossier = DOSSIER_FIXTURES.get(case.ticker)
    if condition == TRUE:
        return build_injection_block(
            dossier, question_intent="company_analysis", now=now,
            config=config, sector=case.sector or None)
    if condition == POISON:
        poison_dir = opposite_direction(case.evidence_direction)
        poisoned = build_poison_dossier(dossier, poison_dir, now=now)
        return build_injection_block(
            poisoned, question_intent="company_analysis", now=now,
            config=config, sector=case.sector or None)
    raise ValueError(f"unknown condition {condition!r}")


# ===========================================================================
# Model client (optional — skips cleanly without a key)
# ===========================================================================

def get_model_client():
    """Return a configured ModelClient, or None if unavailable (no key / no SDK).

    Imported lazily so the offline green tests never depend on the OpenAI SDK or
    on a key being present.
    """
    try:
        from app.config import settings
        from app.model_client import ModelClient, _OPENAI_AVAILABLE
    except Exception:
        return None
    if not _OPENAI_AVAILABLE:
        return None
    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key:
        return None
    try:
        # Structurally mirror the production SYNTHESIS client (model_client.py):
        # synthesis_model + settings.temperature (prod decodes at 0.0), with
        # max_tokens headroom so the compact JSON contract is never truncated.
        return ModelClient(
            api_key=api_key,
            model=getattr(settings, "synthesis_model", None) or "gpt-4o-mini",
            temperature=getattr(settings, "temperature", 0.0),
            max_tokens=max(getattr(settings, "synthesis_max_tokens", 900), 900),
        )
    except Exception:
        return None


# ===========================================================================
# Runners
# ===========================================================================

def run_condition(
    case: GoldenCase,
    condition: str,
    *,
    now: datetime = NOW,
    config: Optional[InjectionConfig] = None,
    client: Any = "auto",
) -> Dict[str, Any]:
    """Build (and optionally execute) one case×condition. Returns a record."""
    cfg = config or InjectionConfig()
    result = _block_for(case, condition, now, cfg)
    block_str = result.block_str if result is not None else ""
    prompt = assemble_prompt(case, block_str)

    record: Dict[str, Any] = {
        "case_id": case.case_id,
        "ticker": case.ticker,
        "archetype": case.archetype,
        "condition": condition,
        "evidence_direction": case.evidence_direction,
        "poison_direction": (opposite_direction(case.evidence_direction)
                             if condition == POISON else None),
        "block_present": bool(block_str),
        "block_tokens": (result.token_count if result is not None else 0),
        "included_facets": (list(result.included_facets) if result else []),
        "dropped_facets": ([list(d) for d in result.dropped_facets]
                           if result else []),
        "prompt_tokens": count_tokens(prompt),
        "prompt": prompt,
        "llm_ran": False,
        "llm_skipped_reason": None,
        "latency_s": None,
        "raw_output": None,
        "error": None,
    }

    if client == "auto":
        client = get_model_client()
    if client is None:
        record["llm_skipped_reason"] = "no_model_client (no OPENAI_API_KEY)"
        return record

    try:
        t0 = time.time()
        raw = client.call(prompt, system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                          request_id=f"5b_{case.case_id}_{condition}")
        record["latency_s"] = round(time.time() - t0, 2)
        record["raw_output"] = raw
        record["llm_ran"] = True
    except Exception as exc:  # degrade, don't crash the sweep
        record["error"] = repr(exc)
        record["llm_skipped_reason"] = "model_call_failed"
    return record


def run_case(case: GoldenCase, *, now: datetime = NOW,
             config: Optional[InjectionConfig] = None,
             client: Any = "auto") -> List[Dict[str, Any]]:
    if client == "auto":
        client = get_model_client()
    return [run_condition(case, c, now=now, config=config, client=client)
            for c in CONDITIONS]


def run_harness(cases: Optional[List[GoldenCase]] = None, *,
                now: datetime = NOW,
                config: Optional[InjectionConfig] = None,
                client: Any = "auto") -> List[Dict[str, Any]]:
    """Run every case under all three conditions. Returns flat record list."""
    cases = cases if cases is not None else GOLDEN_CASES
    if client == "auto":
        client = get_model_client()
    records: List[Dict[str, Any]] = []
    for case in cases:
        records.extend(run_case(case, now=now, config=config, client=client))
    return records
