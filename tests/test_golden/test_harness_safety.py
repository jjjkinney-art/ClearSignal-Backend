"""
Slice 5B green tests — harness safety + controlled-experiment invariants.

Proves the harness is a pure offline experiment: OFF injects nothing, the three
conditions differ ONLY inside the block region, and nothing here touches the
production injection flags or the live /ask route.
"""

from __future__ import annotations

import inspect

from tests.golden import harness
from tests.golden.golden_set import GOLDEN_CASES, NOW
from tests.golden.harness import (
    OFF, TRUE, POISON, CONDITIONS, assemble_prompt, run_condition, run_case,
    run_harness, _BLOCK_OPEN, _BLOCK_CLOSE,
)


def _strip_block_region(prompt: str) -> str:
    """Remove the sentinel-delimited block region so the rest can be compared."""
    start = prompt.find(_BLOCK_OPEN)
    if start == -1:
        return prompt
    end = prompt.find(_BLOCK_CLOSE)
    assert end != -1
    tail = prompt[end + len(_BLOCK_CLOSE):].lstrip("\n")
    return prompt[:start] + tail


def test_off_injects_zero_bytes():
    for c in GOLDEN_CASES:
        rec = run_condition(c, OFF, now=NOW, client=None)
        assert rec["block_present"] is False
        assert rec["block_tokens"] == 0
        assert _BLOCK_OPEN not in rec["prompt"]


def test_conditions_differ_only_in_block_region():
    # Outside the injected block, OFF/TRUE/POISON prompts are byte-identical.
    for c in GOLDEN_CASES:
        off = run_condition(c, OFF, now=NOW, client=None)["prompt"]
        tru = run_condition(c, TRUE, now=NOW, client=None)["prompt"]
        poi = run_condition(c, POISON, now=NOW, client=None)["prompt"]
        base_off = _strip_block_region(off)
        base_true = _strip_block_region(tru)
        base_poison = _strip_block_region(poi)
        assert base_off == base_true == base_poison, c.case_id


def test_true_and_poison_inject_a_block():
    c = GOLDEN_CASES[0]
    tru = run_condition(c, TRUE, now=NOW, client=None)
    poi = run_condition(c, POISON, now=NOW, client=None)
    assert tru["block_present"] and tru["block_tokens"] > 0
    assert poi["block_present"] and poi["block_tokens"] > 0
    assert _BLOCK_OPEN in tru["prompt"]


def test_prompt_delta_is_bounded_by_block_plus_overhead():
    # The only token delta vs OFF is the block + the two sentinels.
    for c in GOLDEN_CASES:
        off = run_condition(c, OFF, now=NOW, client=None)
        tru = run_condition(c, TRUE, now=NOW, client=None)
        delta = tru["prompt_tokens"] - off["prompt_tokens"]
        # block tokens + a small fixed sentinel overhead; never unbounded.
        assert 0 < delta <= tru["block_tokens"] + 40, (c.case_id, delta)


def test_no_client_marks_behavioural_skipped_not_error():
    rec = run_condition(GOLDEN_CASES[0], TRUE, now=NOW, client=None)
    assert rec["llm_ran"] is False
    assert rec["error"] is None
    assert "no_model_client" in (rec["llm_skipped_reason"] or "")


def test_run_case_emits_all_three_conditions():
    recs = run_case(GOLDEN_CASES[0], now=NOW, client=None)
    assert [r["condition"] for r in recs] == CONDITIONS


def test_run_harness_full_grid():
    recs = run_harness(GOLDEN_CASES, now=NOW, client=None)
    assert len(recs) == len(GOLDEN_CASES) * 3


def test_harness_never_references_production_injection_flags():
    # The whole experiment is local: it must not read/set the production flags
    # or hit the live ask route.
    src = inspect.getsource(harness)
    for forbidden in (
        "dossier_injection_enabled",
        "dossier_injection_shadow",
        "dossier_injection_canary_pct",
        "/ask",
    ):
        assert forbidden not in src, f"harness must not reference {forbidden!r}"


def test_with_mock_client_records_output():
    class _Mock:
        def call(self, prompt, system_prompt="", request_id=None):
            return '{"stance":"bearish","direct_answer":"x","conclusion":"y",' \
                   '"prior_challenged":true,"prior_challenge_note":"n","change_vector":"v"}'

    rec = run_condition(GOLDEN_CASES[0], TRUE, now=NOW, client=_Mock())
    assert rec["llm_ran"] is True
    assert rec["raw_output"].startswith("{")
    assert rec["latency_s"] is not None
