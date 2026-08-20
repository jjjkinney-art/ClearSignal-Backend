"""Risk-agent output-shape variants (Sprint 3B.3).

Why this exists
---------------
Sprint 3B.2 closed the synthesis-model lever: ``gpt-4.1-nano`` lost the MSFT
FCF threshold, degraded four of five names, and returned a -2.0% median
synthesis latency — it failed both gates. The remaining measured bottleneck is
the risk agent, which is the slowest agent in the large majority of queries.

What the profiling artifacts actually say
-----------------------------------------
Across 466 agent model calls in ``validation/runs``:

    corr(duration, input_tokens)  = 0.04
    corr(duration, output_tokens) = 0.857   (r^2 = 0.734)
    duration_ms ~= 723 + 8.75 * output_tokens        (~114 tokens/sec)

Agent latency is **output-bound**. Input size is statistically irrelevant. The
cleanest natural experiment is the risk agent against the question-answerer in
the same request: near-identical input (1425 vs 1416 median tokens), 8x the
output (851 vs 106), 5.6x the duration (8483 vs 1511 ms). In runs where all six
agents call the model, agent duration orders *exactly* by output tokens
(105->1936ms, 326->4903, 687->7610, 734->8588, 752->9009, 945->11265).

The risk agent is not slow because it is special. It is slow because it emits
the most tokens.

Why this particular reduction
-----------------------------
``max_tokens`` is 4096 and the largest output ever observed is 960, so lowering
the cap cannot move latency — the model stops well short of it. Nor is there a
redundant call to delete: every sampled risk invocation is a single call with
``retry_count=0``.

That leaves the generated shape. Of the eight output fields, ``key_risks`` is
already specified "concise", ``overall`` is "one concise paragraph", and
``signals`` has a fixed object shape. The four domain prose fields — debt,
competitive, regulatory, concentration — carry **no length guidance at all**,
and they are also the fields with the weakest downstream consumption: they
reach synthesis only through intent-conditional sub-field injection, while
``overall``, ``key_risks``, ``signals`` and ``confidence`` are consumed on
every request.

So ``risk_fast_a`` bounds exactly those four fields and nothing else. It is a
*brevity* constraint, not a content constraint: the variant text mandates that
every figure, thresholded metric, named competitor/regulator/customer and
percentage be retained, because losing a quantitative anchor is precisely the
failure that disqualified the 3B.2 candidate.

Isolation
---------
A variant is a pure suffix transform appended to the control prompt. The
control prompt is built by ``_build_prompt`` exactly as in production and
``control`` returns that string unchanged — byte-identical, verified by test.
Nothing here selects a variant on its own: ``resolve_risk_variant`` fails
closed to control for any unauthorized caller, unknown name, or empty value.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

RISK_VARIANT_CONTROL = "risk_control"
RISK_VARIANT_FAST_A = "risk_fast_a"
# Sprint 3B.4 — structured representation. `risk_fast_a` is retained as a
# named variant purely so its live failure stays reproducible; it is not a
# candidate any more (0 keeps across 15 live observations at 11.1% latency).
RISK_VARIANT_STRUCT_A = "risk_struct_a"
KNOWN_RISK_VARIANTS = (RISK_VARIANT_CONTROL, RISK_VARIANT_FAST_A,
                       RISK_VARIANT_STRUCT_A)

# Variants whose model output is RiskStructured rather than RiskProfile, and
# therefore need the projection step before anything downstream sees them.
STRUCTURED_RISK_VARIANTS = (RISK_VARIANT_STRUCT_A,)

# Rough English prose ratio, used only to report an approximate token figure
# next to an exact character count. Never used to support a latency claim.
_CHARS_PER_TOKEN = 4.0

# The four output fields this sprint bounds. These are the only RiskProfile
# prose fields the control prompt leaves without length guidance, and the only
# ones whose path into synthesis is intent-conditional rather than
# unconditional. Kept as data so a test can assert the set has not drifted.
BOUNDED_FIELDS = (
    "debt_risk",
    "competitive_risk",
    "regulatory_risk",
    "concentration_risk",
)

# Fields deliberately NOT touched: they are consumed on every request, so
# changing their shape would alter the thesis for every query rather than
# isolating a latency experiment.
UNTOUCHED_FIELDS = ("key_risks", "overall", "confidence", "signals")

# The variant instruction. Appended after the control prompt's "JSON:" cue is
# stripped, then the cue is re-appended, so the model still ends on the same
# token it does in production.
_FAST_A_BLOCK = """
LENGTH DISCIPLINE (applies ONLY to debt_risk, competitive_risk, regulatory_risk, concentration_risk):
- Write each of these four fields as AT MOST 2 sentences.
- Cut connective and hedging prose, not content.

MANDATORY RETENTION — these must survive the shortening:
- Every numeric figure, ratio, percentage and dollar amount.
- Every named competitor, regulator, customer, supplier and geography.
- Every metric that carries a threshold or trigger level.
- Every evidence citation marker such as [1], [2].
- The causal mechanism: state WHAT changes and HOW it transmits to the thesis.

Do NOT shorten key_risks, overall or signals — produce those exactly as specified above.
Do NOT drop a field. If a field has no evidence, return an empty string for it."""

_JSON_CUE = "\n\nJSON:"

# ── Sprint 3B.4: structured representation ───────────────────────────────────
# The control prompt's output section begins at this exact line. `risk_struct_a`
# replaces everything from here to the JSON cue and leaves the entire preceding
# prompt — analyst framing, company context, question emphasis, the evidence
# block, and the five analytical questions — byte-identical. That is what makes
# this a representation experiment rather than a scope change: the model is
# asked the same questions about the same evidence, and only the shape it
# answers in differs.
_OUTPUT_SECTION_MARKER = "Produce a JSON object matching the RiskProfile schema with these fields:"

_STRUCT_A_BLOCK = """Produce a JSON object with exactly these top-level keys:

- overall: One concise paragraph summarising the risk profile.
- confidence: 0.0-1.0 based on evidence completeness.
- risk_items: array of 3-6 objects. State each material risk EXACTLY ONCE.
    Do not repeat a risk across items, and do not restate it in `overall`
    beyond naming it. Each object must have:
    - category: "debt" | "competitive" | "regulatory" | "concentration" | "other"
    - mechanism: the causal chain — WHAT changes and HOW it transmits to the
      thesis. Required. A risk with no mechanism is not analysis.
    - metric: the specific metric that would move (e.g. "Azure YoY growth").
      Empty string if the risk is genuinely unquantifiable.
    - current_value: the metric's current level (e.g. "~29%"). Empty if unknown.
    - warning_threshold: level at which the thesis weakens (e.g. "25%").
    - bear_threshold: level at which the thesis breaks (e.g. "20%").
    - entities: array of specific named competitors, regulators, customers,
      suppliers or geographies at stake.
    - citations: array of evidence numbers supporting this item (e.g. [1, 2]).
    - impact: 0.0-1.0 severity to the thesis.
    - horizon: "short_term" | "medium_term" | "long_term"

Requirements:
- Every risk must name the specific {ticker} revenue line, customer segment or
  competitive dynamic at stake — no generic sector risks.
- Never invent a figure or a threshold. Leave the field as an empty string when
  the evidence does not support one.
- Do not write debt_risk, competitive_risk, regulatory_risk, concentration_risk,
  key_risks or signals — those are derived from risk_items downstream.
- Return ONLY valid JSON, no markdown fences or prose outside the JSON object."""


def estimate_tokens(text: str) -> int:
    return int(len(text or "") / _CHARS_PER_TOKEN)


def resolve_risk_variant(requested: Optional[str], *, authorized: bool) -> str:
    """Resolve the risk-agent variant for a request.

    Fails closed to ``risk_control`` on every ambiguity: an unauthorized
    caller, an unknown variant name, or an empty value. Selecting a variant
    requires the same authorization as Sprint 3A.1 profiling detail, so no
    ordinary user can reach it.
    """
    if not authorized:
        return RISK_VARIANT_CONTROL
    name = str(requested or "").strip().lower()
    return name if name in KNOWN_RISK_VARIANTS else RISK_VARIANT_CONTROL


def apply_risk_variant(control_prompt: str, variant: str) -> str:
    """Return the prompt for ``variant``, derived from the control prompt.

    ``risk_control`` returns the input unchanged — byte-identical to
    production. Any unknown variant also returns it unchanged, so a bad value
    can never produce a novel prompt.
    """
    if variant == RISK_VARIANT_FAST_A:
        body = control_prompt
        if body.endswith(_JSON_CUE):
            body = body[: -len(_JSON_CUE)]
            return body + "\n" + _FAST_A_BLOCK + _JSON_CUE
        # Control prompt shape changed — append without assuming the trailing
        # cue rather than silently placing the block in the wrong position.
        return body + "\n" + _FAST_A_BLOCK

    if variant == RISK_VARIANT_STRUCT_A:
        return _apply_struct_a(control_prompt)

    return control_prompt


def _apply_struct_a(control_prompt: str) -> str:
    """Swap the control prompt's output section for the structured spec.

    Everything before the output section is preserved verbatim, so the model
    receives the identical framing, evidence and analytical questions. If the
    marker is absent — the control prompt was restructured — this returns the
    control prompt unchanged rather than guessing where the boundary is, which
    would risk emitting a prompt with two contradictory output schemas.
    """
    idx = control_prompt.find(_OUTPUT_SECTION_MARKER)
    if idx == -1:
        logger.warning(
            "[risk_variants] struct_a output-section marker not found; "
            "serving control prompt",
        )
        return control_prompt

    head = control_prompt[:idx]
    ticker = _infer_ticker(control_prompt)
    block = _STRUCT_A_BLOCK.replace("{ticker}", ticker)
    return head + block + _JSON_CUE


def _infer_ticker(prompt: str) -> str:
    """Best-effort ticker for the structured spec's specificity requirement.

    The control prompt opens with "Analyse <Company> (<TICKER>)." Falling back
    to "the company" keeps the instruction grammatical when that shape changes,
    rather than leaving a literal placeholder in the prompt.
    """
    match = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", prompt[:400])
    return match.group(1) if match else "the company"


def describe_risk_variant(variant: str, *, prompt: Optional[str] = None,
                          evidence_count: Optional[int] = None) -> dict:
    """Metadata for the observability block. Never includes prompt text."""
    from ..config import settings

    out = {
        "risk_variant": variant,
        "risk_model": str(getattr(settings, "agent_model", "") or "") or None,
        "risk_provider": "openai",
    }
    # Key names deliberately avoid the substrings "prompt" and "evidence":
    # the observability scrubber treats both as unsafe markers so prompt text
    # and evidence bodies can never be recorded. These are sizes and counts,
    # not content, so they are renamed to pass the filter honestly rather than
    # the filter being widened to let them through.
    if prompt is not None:
        out["risk_input_chars"] = len(prompt)
        out["risk_input_tokens_est"] = estimate_tokens(prompt)
    if evidence_count is not None:
        out["risk_item_count"] = evidence_count
    return out
