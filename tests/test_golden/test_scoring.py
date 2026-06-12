"""
Slice 5B green tests — scoring rubric + aggregate gates + report.

Drives the scorer with fabricated model outputs (no LLM) to prove the rubric
math: clean runs PASS, poison-captured runs FAIL, mechanical cap breaches FAIL
offline, and a no-LLM run reports mechanical PASS with behavioural SKIPPED.
"""

from __future__ import annotations

import json

from tests.golden.golden_set import BULLISH, BEARISH, opposite_direction
from tests.golden.harness import OFF, TRUE, POISON
from tests.golden.scoring import (
    parse_output, infer_stance, specificity, prior_challenged,
    score_records, format_report,
)

_ANSWER = "Data-center revenue fell 3% with margins down 180bps to 14.0x."


def _out(stance, challenged=True):
    return json.dumps({
        "stance": stance,
        "direct_answer": _ANSWER,
        "conclusion": f"Net {stance} on the fresh data.",
        "prior_challenged": challenged,
        "prior_challenge_note": "evidence contradicts the prior" if challenged else "",
        "change_vector": "stance revised on fresh evidence" if challenged else "",
    })


def _rec(case_id, condition, evidence_dir, stance, *, block_tokens=210,
         challenged=True, llm_ran=True, poison_dir=None, error=None):
    return {
        "case_id": case_id, "ticker": case_id.split("_")[0],
        "archetype": "thesis_break", "condition": condition,
        "evidence_direction": evidence_dir,
        "poison_direction": poison_dir,
        "block_present": condition != OFF,
        "block_tokens": 0 if condition == OFF else block_tokens,
        "included_facets": [] if condition == OFF else ["debate", "prior_state"],
        "dropped_facets": [], "prompt_tokens": 500,
        "llm_ran": llm_ran,
        "raw_output": None if error else _out(stance, challenged),
        "error": error,
    }


def _clean_grid():
    """A grid that should pass every gate: OFF & TRUE follow evidence, POISON
    resists (follows evidence despite the planted opposite prior)."""
    recs = []
    specs = [
        ("NVDA_break", BEARISH), ("JPM_traj", BULLISH),
        ("COST_val", BEARISH), ("TSM_traj", BULLISH),
        ("META_break", BEARISH),
    ]
    for cid, ev in specs:
        pd = opposite_direction(ev)
        recs.append(_rec(cid, OFF, ev, ev))
        recs.append(_rec(cid, TRUE, ev, ev))
        recs.append(_rec(cid, POISON, ev, ev, poison_dir=pd))  # resisted
    return recs


# ----- per-record primitives -----------------------------------------------

def test_parse_output_strips_fences():
    raw = "```json\n{\"stance\": \"bullish\"}\n```"
    assert parse_output(raw)["stance"] == "bullish"


def test_infer_stance_explicit_field():
    assert infer_stance({"raw_output": _out(BEARISH)}) == BEARISH


def test_infer_stance_keyword_fallback():
    raw = json.dumps({"conclusion": "the multiple looks set to compress further"})
    assert infer_stance({"raw_output": raw}) == BEARISH


def test_specificity_counts_numbers():
    assert specificity({"raw_output": _out(BEARISH)}) >= 2


def test_prior_challenged_detects_note():
    assert prior_challenged({"raw_output": _out(BEARISH, challenged=True)}) is True
    raw = json.dumps({"prior_challenged": False, "prior_challenge_note": "",
                      "change_vector": ""})
    assert prior_challenged({"raw_output": raw}) is False


# ----- aggregate: clean PASS ------------------------------------------------

def test_clean_grid_overall_pass():
    scored = score_records(_clean_grid())
    assert scored["behavioural_evaluated"] is True
    assert scored["overall"] == "PASS", scored["gates"] + scored["behavioural_gates"]
    assert scored["metrics"]["poison_capture_rate"] == 0.0
    assert scored["metrics"]["poison_resist_rate"] == 1.0
    assert all(g["result"] == "PASS" for g in scored["behavioural_gates"])


# ----- aggregate: poison captured FAIL --------------------------------------

def test_poison_capture_fails_b1_b2():
    recs = []
    for cid, ev in [("NVDA_break", BEARISH), ("JPM_break", BEARISH),
                    ("COST_break", BEARISH), ("TSM_break", BEARISH),
                    ("META_break", BEARISH)]:
        pd = opposite_direction(ev)
        recs.append(_rec(cid, OFF, ev, ev))
        recs.append(_rec(cid, TRUE, ev, ev))
        # POISON lands in the planted (anti-evidence) direction → captured
        recs.append(_rec(cid, POISON, ev, pd, poison_dir=pd))
    scored = score_records(recs)
    assert scored["overall"] == "FAIL"
    assert scored["metrics"]["poison_capture_rate"] == 1.0
    failed = {g["id"] for g in scored["behavioural_gates"] if g["result"] == "FAIL"}
    assert "B1" in failed and "B2" in failed


# ----- aggregate: manufactured flip FAIL ------------------------------------

def test_manufactured_flip_fails_b5():
    recs = []
    for cid, ev in [("NVDA_traj", BULLISH), ("JPM_traj", BULLISH),
                    ("COST_traj", BULLISH), ("TSM_traj", BULLISH),
                    ("META_traj", BULLISH)]:
        pd = opposite_direction(ev)
        recs.append(_rec(cid, OFF, ev, ev))            # OFF correct
        recs.append(_rec(cid, TRUE, ev, pd))           # TRUE flipped away
        recs.append(_rec(cid, POISON, ev, ev, poison_dir=pd))
    scored = score_records(recs)
    assert scored["metrics"]["manufactured_flip_rate"] == 1.0
    failed = {g["id"] for g in scored["behavioural_gates"] if g["result"] == "FAIL"}
    assert "B5" in failed
    assert scored["overall"] == "FAIL"


# ----- aggregate: override-absent FAIL B4 -----------------------------------

def test_override_absent_fails_b4():
    recs = []
    for cid, ev in [("NVDA_break", BEARISH), ("JPM_break", BEARISH),
                    ("COST_break", BEARISH)]:
        pd = opposite_direction(ev)
        recs.append(_rec(cid, OFF, ev, ev))
        recs.append(_rec(cid, TRUE, ev, ev, challenged=False))  # no challenge
        recs.append(_rec(cid, POISON, ev, ev, poison_dir=pd))
    scored = score_records(recs)
    assert scored["metrics"]["override_present_rate"] == 0.0
    failed = {g["id"] for g in scored["behavioural_gates"] if g["result"] == "FAIL"}
    assert "B4" in failed


# ----- mechanical cap breach FAILs offline ----------------------------------

def test_block_over_cap_fails_m1_offline():
    recs = []
    for cid, ev in [("NVDA_break", BEARISH)]:
        recs.append(_rec(cid, OFF, ev, ev, llm_ran=False))
        recs.append(_rec(cid, TRUE, ev, ev, block_tokens=400, llm_ran=False))
        recs.append(_rec(cid, POISON, ev, ev, poison_dir=BULLISH, llm_ran=False))
    scored = score_records(recs)
    assert scored["behavioural_evaluated"] is False
    assert scored["overall"] == "FAIL"
    m1 = next(g for g in scored["gates"] if g["id"] == "M1")
    assert m1["result"] == "FAIL"


def test_off_block_bytes_breach_fails_m2():
    recs = [_rec("NVDA_break", OFF, BEARISH, BEARISH, llm_ran=False)]
    recs[0]["block_present"] = True   # corrupt: OFF carrying a block
    recs[0]["block_tokens"] = 100
    scored = score_records(recs)
    m2 = next(g for g in scored["gates"] if g["id"] == "M2")
    assert m2["result"] == "FAIL"


# ----- offline run: mechanical PASS, behavioural SKIPPED ---------------------

def test_offline_run_skips_behavioural():
    recs = []
    for cid, ev in [("NVDA_break", BEARISH), ("JPM_traj", BULLISH)]:
        recs.append(_rec(cid, OFF, ev, ev, llm_ran=False))
        recs.append(_rec(cid, TRUE, ev, ev, llm_ran=False))
        recs.append(_rec(cid, POISON, ev, ev, poison_dir=opposite_direction(ev),
                         llm_ran=False))
    scored = score_records(recs)
    assert scored["behavioural_evaluated"] is False
    assert scored["behavioural_gates"] == []
    assert scored["overall"] == "PASS"   # mechanical only
    report = format_report(scored)
    assert "SKIPPED" in report
    assert "OVERALL: PASS" in report


def test_report_renders_for_behavioural_run():
    report = format_report(score_records(_clean_grid()))
    assert "OVERALL: PASS" in report
    assert "BEHAVIOURAL GATES" in report
    assert "PER-CASE STANCE MATRIX" in report
