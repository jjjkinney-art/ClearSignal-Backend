"""
Phase 9G · Phase 0 — Company Dossier injection formatter (Slice 5A — shadow).

Pure, deterministic assembly of the "prior dossier" briefing block that Slice 5B
will inject into the synthesis prompt.  In Slice 5A this runs in SHADOW mode:
the block is built and measured but NEVER attached to the prompt (wiring lives in
api.py behind ``dossier_injection_shadow``).

Design contract (spec §1):
  * No DB, no clock except the injected ``now`` → unit-testable on hand-built
    dossier objects (ORM rows or SimpleNamespace doubles — attribute access only).
  * Returns ``None`` when there is nothing worth injecting (null-object: the
    caller then changes the prompt by exactly zero bytes — invariant 1).
  * The assembled block (including the red-team trailer) is ≤ 350 tokens, p100,
    enforced mechanically by tokenize→drop, never by hoping the formatter is small.

The block is anti-anchoring by construction (spec §5/§6):
  * the debate is injected as a *question with both poles*, not a verdict;
  * the prior is framed as "a prior to update, not facts to repeat";
  * a fixed CHALLENGE-THE-PRIOR trailer (C4) forces the model to argue the
    prior wrong on this cycle's evidence before concluding.

Slice 5A implements ALL six facet formatters.  moat_profile and
variant_perception are dormant (empty in production until the LLM-extraction
slice backfills them); their formatters light up automatically when populated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ===========================================================================
# Token counting — tiktoken when available, deterministic fallback otherwise
# ===========================================================================

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder(model: str = "gpt-4o-mini"):
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:  # pragma: no cover — depends on optional dep being installed
        import tiktoken  # type: ignore
        try:
            _ENCODER = tiktoken.encoding_for_model(model)
        except Exception:
            _ENCODER = tiktoken.get_encoding("o200k_base")
    except Exception:
        _ENCODER = None
    return _ENCODER


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Token count for *text*.

    Uses tiktoken (o200k_base for the gpt-4o family) when importable; otherwise
    falls back to a deterministic ~4-chars-per-token heuristic so the budget
    machinery behaves identically in environments without tiktoken (e.g. the
    local test box).  The whole pipeline uses THIS function, so cap enforcement
    is self-consistent regardless of which path is active.
    """
    if not text:
        return 0
    enc = _get_encoder(model)
    if enc is not None:  # pragma: no cover — exercised only where tiktoken exists
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, (len(text) + 3) // 4)


# ===========================================================================
# Config (spec §3, §4)
# ===========================================================================

@dataclass(frozen=True)
class InjectionConfig:
    # Hard cap — block incl. red-team trailer never exceeds this (spec §4).
    token_cap: int = 350

    # Fixed overhead budgets (never dropped).
    budget_overhead: int = 18      # header + freshness line
    budget_redteam:  int = 30      # CHALLENGE-THE-PRIOR trailer

    # Per-facet budgets (spec §4 table).
    budget_debate:      int = 70   # pri 1 — never dropped
    budget_prior_state: int = 35   # pri 2 — never dropped (when included)
    budget_catalysts:   int = 80   # pri 3
    budget_failure:     int = 40   # pri 4
    budget_moat:        int = 80   # pri 5 (dormant in v1)
    budget_variant:     int = 50   # pri 6 (dormant in v1)

    # Staleness decay (spec §3).
    tau_default: float = 86.0      # days; weight≈0.50 at 60d (stale boundary)
    theta:       float = 0.35      # inclusion gate on effective_confidence

    # Discrete staleness bands (freshness annotation only).
    fresh_max_days: int = 14
    aging_max_days: int = 60

    # Facet item caps before within-facet trimming.
    max_catalysts: int = 3
    max_variants:  int = 2

    # Whether to include the demoted prior_state line (re-review Decision 1 —
    # staging A/B toggles this; default demote/include).
    include_prior_state: bool = True

    # Field render caps (chars) — applied before tokenisation (spec §5).
    cap_pole_chars:      int = 120
    cap_catalyst_chars:  int = 90
    cap_concern_chars:   int = 60
    cap_question_chars:  int = 160
    cap_stage_chars:     int = 120


# Sector → tau override (spec §3).  Unknown sector → tau_default.
SECTOR_TAU: Dict[str, float] = {
    "semiconductors": 60.0, "ai_infra": 60.0, "biotech": 60.0,
    "utilities": 120.0, "staples": 120.0, "telecom": 120.0,
}

DEFAULT_CONFIG = InjectionConfig()

# Reverse-priority drop order when the block is over cap (spec §4).
# debate + prior_state are never in this list.
_DROP_ORDER = ["failure", "variant", "catalysts", "moat"]


# ===========================================================================
# Result object
# ===========================================================================

@dataclass
class InjectionResult:
    block_str: str
    token_count: int
    staleness_state: str
    intent: str
    included_facets: List[str] = field(default_factory=list)
    dropped_facets: List[Tuple[str, str]] = field(default_factory=list)
    decay_weights: Dict[str, float] = field(default_factory=dict)


# ===========================================================================
# Decay / staleness helpers (spec §3)
# ===========================================================================

def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_days(dt: Optional[datetime], now: datetime) -> Optional[int]:
    dt = _as_utc(dt)
    if dt is None:
        return None
    delta = _as_utc(now) - dt
    return max(0, delta.days)


def decay_weight(age_days: Optional[int], tau: float) -> float:
    """exp(-age/tau).  Missing age → 1.0 (treat as fresh — no penalty)."""
    if age_days is None:
        return 1.0
    if tau <= 0:
        return 1.0
    return math.exp(-float(age_days) / tau)


def effective_confidence(stored: float, age_days: Optional[int], tau: float) -> float:
    return float(stored or 0.0) * decay_weight(age_days, tau)


def staleness_band(age_days: Optional[int], cfg: InjectionConfig) -> str:
    if age_days is None:
        return "fresh"
    if age_days < cfg.fresh_max_days:
        return "fresh"
    if age_days < cfg.aging_max_days:
        return "aging"
    return "stale"


def _tau_for_sector(sector: Optional[str], cfg: InjectionConfig) -> float:
    if not sector:
        return cfg.tau_default
    return SECTOR_TAU.get(str(sector).strip().lower(), cfg.tau_default)


# ===========================================================================
# Small render utilities
# ===========================================================================

def _truncate(text: Any, max_chars: int) -> str:
    s = str(text or "").strip()
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0].rstrip()
    return (cut or s[:max_chars]).rstrip() + "…"


def _g(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


# ===========================================================================
# Facet formatters — each returns (text, used_tokens) or ("", 0) if absent
# ===========================================================================

def _format_debate(debate: Any, eff_conf: float, cfg: InjectionConfig) -> str:
    if debate is None:
        return ""
    question = _truncate(_g(debate, "question"), cfg.cap_question_chars)
    bull = _truncate(_g(debate, "bull_pole"), cfg.cap_pole_chars)
    bear = _truncate(_g(debate, "bear_pole"), cfg.cap_pole_chars)
    if not question and not bull and not bear:
        return ""
    lean = str(_g(debate, "current_lean", "balanced") or "balanced")
    decay_note = " (confidence decayed by age — weight lightly)" if eff_conf < cfg.theta else ""
    lines = [f"DEBATE — {question or '(unspecified)'}"]
    if bull:
        lines.append(f"  Bull pole: {bull}")
    if bear:
        lines.append(f"  Bear pole: {bear}")
    lines.append(f"  Prior lean: {lean}{decay_note}. Re-adjudicate on this cycle's evidence.")
    return "\n".join(lines)


def _format_prior_state(head: Any, cfg: InjectionConfig) -> str:
    stance = str(_g(head, "stance", "") or "").strip()
    if not stance:
        return ""
    conviction = _g(head, "conviction", 0.0) or 0.0
    concern = _truncate(_g(head, "primary_concern"), cfg.cap_concern_chars)
    as_of = _as_utc(_g(head, "prior_as_of")) or _as_utc(_g(head, "last_full_update_at"))
    as_of_str = as_of.date().isoformat() if as_of else "unknown date"
    concern_part = f" · chief concern {concern}" if concern else ""
    return (
        f"PRIOR — stance {stance} · conviction {float(conviction):.2f}{concern_part} "
        f"· as of {as_of_str}. (Treat as a starting point to confirm or revise.)"
    )


def _format_catalysts(catalysts: List[Any], now: datetime, tau: float,
                      cfg: InjectionConfig, max_items: int) -> str:
    rows = [c for c in (catalysts or []) if str(_g(c, "status", "")) == "open"]
    # Decay-gate each row, then rank by conviction_weight desc.
    eligible: List[Tuple[float, Any]] = []
    for c in rows:
        age = _age_days(_g(c, "created_at"), now)
        eff = effective_confidence(_g(c, "conviction_weight", 0.0), age, tau)
        if eff >= cfg.theta:
            eligible.append((float(_g(c, "conviction_weight", 0.0) or 0.0), c))
    if not eligible:
        return ""
    eligible.sort(key=lambda t: t[0], reverse=True)
    chosen = [c for _, c in eligible[:max_items]]
    bullets = []
    for c in chosen:
        stmt = _truncate(_g(c, "statement"), cfg.cap_catalyst_chars)
        direction = str(_g(c, "direction", "") or "").replace("_", " ")
        window = str(_g(c, "expected_window", "") or "").strip() or "no window"
        if stmt:
            bullets.append(f"  • {stmt} → {direction}, window {window}")
    if not bullets:
        return ""
    return "WATCH — open catalysts to check against this cycle's evidence:\n" + "\n".join(bullets)


def _format_failure(failure_modes: List[Any], durability: Any, now: datetime,
                    tau: float, cfg: InjectionConfig,
                    analog_labels: Optional[Dict[str, str]]) -> str:
    # Highest-conviction active match that survives the decay gate.
    best = None
    best_eff = -1.0
    for fm in (failure_modes or []):
        if not _g(fm, "analog_id"):
            continue
        age = _age_days(_g(fm, "matched_at"), now)
        eff = effective_confidence(_g(fm, "relevance_at_match", 0.0), age, tau)
        if eff >= cfg.theta and eff > best_eff:
            best, best_eff = fm, eff
    if best is None:
        return ""
    analog_id = str(_g(best, "analog_id", "") or "")
    label = (analog_labels or {}).get(analog_id) or "historical failure analog"
    stage = _g(best, "sequence_stage", 1)
    # Cycle hint folded into the headline so it survives within-facet trimming;
    # the stage-signal detail is the single droppable continuation line.
    headline = f"RISK — active failure-mode pattern: {label} @ stage {stage}"
    if durability is not None:
        cycle = str(_g(durability, "cycle_position", "") or "")
        horizon = str(_g(durability, "horizon_hint", "") or "")
        bits = [b for b in (cycle, horizon) if b and b != "unknown"]
        if bits:
            headline += f" · cycle: {' · '.join(bits)}"
    headline += "."
    evidence = _truncate(_g(best, "stage_evidence"), cfg.cap_stage_chars)
    if evidence:
        return f"{headline}\n  Stage signal: {evidence}"
    return headline


def _format_moat(dimensions: List[Any], now: datetime, tau: float,
                 cfg: InjectionConfig) -> str:
    # Only axes with strength != absent; weakening axes first.
    rows = []
    for d in (dimensions or []):
        strength = str(_g(d, "strength", "") or "")
        if strength == "absent" or not strength:
            continue
        age = _age_days(_g(d, "last_changed_at"), now)
        eff = effective_confidence(_g(d, "confidence", 0.0), age, tau)
        if eff < cfg.theta:
            continue
        rows.append(d)
    if not rows:
        return ""
    rows.sort(key=lambda d: 0 if str(_g(d, "trend", "")) == "weakening" else 1)
    bullets = []
    for d in rows:
        axis = str(_g(d, "axis", "") or "").replace("_", " ")
        strength = str(_g(d, "strength", "") or "")
        trend = str(_g(d, "trend", "") or "")
        arrow = {"strengthening": "↑", "weakening": "↓", "stable": "→"}.get(trend, "→")
        bullets.append(f"  • {axis}: {strength}{arrow} — confirm or refute")
    return "MOAT — competitive-advantage axes (prior view, to test):\n" + "\n".join(bullets)


def _format_variant(variant: Any, now: datetime, tau: float, cfg: InjectionConfig,
                    max_items: int) -> str:
    if variant is None:
        return ""
    age = _age_days(_g(variant, "updated_at"), now)
    eff = effective_confidence(_g(variant, "confidence", 0.0), age, tau)
    if eff < cfg.theta:
        return ""
    divs = _g(variant, "divergences", []) or []
    if not isinstance(divs, list):
        return ""
    ranked = sorted(
        [d for d in divs if isinstance(d, dict)],
        key=lambda d: float(d.get("conviction", 0.0) or 0.0),
        reverse=True,
    )[:max_items]
    if not ranked:
        return ""
    bullets = []
    for d in ranked:
        dim = str(d.get("dimension", "") or "").strip()
        direction = str(d.get("direction", "") or "").replace("_", " ")
        if dim:
            bullets.append(f"  • {dim} ({direction})")
    if not bullets:
        return ""
    return "VARIANT — where we diverge from consensus (a prior, not a mandate):\n" + "\n".join(bullets)


# Fixed trailer — C4 (spec §6).  Never dropped.
_REDTEAM_TRAILER = (
    "CHALLENGE THE PRIOR — Before you conclude: state the single strongest argument "
    "that THIS CYCLE'S EVIDENCE makes the prior lean WRONG. If the evidence supports "
    "that challenge, revise the stance and say so plainly. If the prior survives, say "
    "it survived and why. Do not maintain the prior by default, and do not flip it "
    "without evidence."
)


# ===========================================================================
# Budget trimming
# ===========================================================================

def _trim_list_facet(text: str, budget: int) -> str:
    """Drop trailing indented lines until the facet fits its per-facet budget.

    The first line is the facet header and is always kept.  Trailing indented
    continuation lines (bullets ``  • …`` or detail lines ``  Stage signal: …``)
    are dropped tail-first.  Returns the header alone if that fits, else "".
    """
    if count_tokens(text) <= budget:
        return text
    lines = text.split("\n")
    if not lines:
        return ""
    header, tail = lines[0], lines[1:]
    while tail:
        tail.pop()  # drop tail continuation line
        candidate = "\n".join([header] + tail)
        if count_tokens(candidate) <= budget:
            return candidate
    return header if count_tokens(header) <= budget else ""


# ===========================================================================
# Public entry point
# ===========================================================================

def build_injection_block(
    dossier: Optional[Dict[str, Any]],
    question_intent: str = "general",
    now: Optional[datetime] = None,
    config: Optional[InjectionConfig] = None,
    *,
    sector: Optional[str] = None,
    analog_labels: Optional[Dict[str, str]] = None,
) -> Optional[InjectionResult]:
    """Assemble the prior-dossier briefing block, or None when nothing to inject.

    Pure: no DB, no global clock.  ``now`` defaults to ``datetime.now(utc)`` only
    as a convenience; tests pass an explicit ``now`` for determinism.
    """
    cfg = config or DEFAULT_CONFIG
    now = _as_utc(now) or datetime.now(timezone.utc)

    if not dossier:
        return None
    head = dossier.get("head")
    if head is None:
        return None

    tau = _tau_for_sector(sector, cfg)

    # Freshness from the head's last material update.
    head_age = _age_days(_g(head, "last_full_update_at") or _g(head, "updated_at"), now)
    staleness = staleness_band(head_age, cfg)
    age_str = "unknown" if head_age is None else f"{head_age}d"

    decay_weights: Dict[str, float] = {}
    dropped: List[Tuple[str, str]] = []

    # ── Render each facet (priority order) ──────────────────────────────────
    debate = dossier.get("debate")
    debate_eff = 1.0
    if debate is not None:
        d_age = _age_days(_g(debate, "updated_at"), now)
        debate_eff = effective_confidence(_g(debate, "confidence", 0.0), d_age, tau)
        decay_weights["debate"] = round(debate_eff, 4)
    debate_txt = _format_debate(debate, debate_eff, cfg)

    prior_txt = ""
    if cfg.include_prior_state:
        # prior_state decay-gated on head conviction + age.
        prior_eff = effective_confidence(_g(head, "conviction", 0.0), head_age, tau)
        decay_weights["prior_state"] = round(prior_eff, 4)
        if prior_eff >= cfg.theta:
            prior_txt = _format_prior_state(head, cfg)
        elif str(_g(head, "stance", "") or "").strip():
            dropped.append(("prior_state", "decayed"))

    catalysts_txt = _format_catalysts(
        dossier.get("catalysts", []), now, tau, cfg, cfg.max_catalysts)
    failure_txt = _format_failure(
        dossier.get("failure_modes", []), dossier.get("durability"),
        now, tau, cfg, analog_labels)
    moat_txt = _format_moat(dossier.get("dimensions", []), now, tau, cfg)
    variant_txt = _format_variant(
        dossier.get("variant"), now, tau, cfg, cfg.max_variants)

    # Per-facet within-budget trimming for list facets.
    if catalysts_txt:
        catalysts_txt = _trim_list_facet(catalysts_txt, cfg.budget_catalysts)
    if moat_txt:
        moat_txt = _trim_list_facet(moat_txt, cfg.budget_moat)
    if variant_txt:
        variant_txt = _trim_list_facet(variant_txt, cfg.budget_variant)
    if failure_txt and count_tokens(failure_txt) > cfg.budget_failure:
        failure_txt = _trim_list_facet(failure_txt, cfg.budget_failure)

    facet_text: Dict[str, str] = {
        "debate":      debate_txt,
        "prior_state": prior_txt,
        "catalysts":   catalysts_txt,
        "failure":     failure_txt,
        "moat":        moat_txt,
        "variant":     variant_txt,
    }

    # If neither anchor facet survived, there is nothing worth injecting.
    if not facet_text["debate"] and not facet_text["prior_state"]:
        return None

    # ── Assemble, then drop whole facets until ≤ cap (spec §4) ──────────────
    header = (
        f"=== WHAT YOU ALREADY KNOW ABOUT {str(_g(head, 'ticker', '')).upper()} "
        f"(a prior to update — not facts to repeat) ==="
    )
    freshness = (
        f"Freshness: dossier last materially updated {age_str} ago ({staleness}). "
        f"Where this cycle's evidence conflicts with the prior below, the evidence "
        f"governs — and you must record the conflict in change_vector."
    )
    closing = "=== END PRIOR DOSSIER — adjudicate below on fresh evidence ==="

    def _assemble(active: Dict[str, str]) -> str:
        order = ["debate", "prior_state", "catalysts", "failure", "moat", "variant"]
        body = [active[k] for k in order if active.get(k)]
        parts = [header, freshness] + body + ["", _REDTEAM_TRAILER, closing]
        return "\n".join(parts)

    block = _assemble(facet_text)
    total = count_tokens(block)

    for facet in _DROP_ORDER:
        if total <= cfg.token_cap:
            break
        if facet_text.get(facet):
            dropped.append((facet, "over_cap"))
            facet_text[facet] = ""
            block = _assemble(facet_text)
            total = count_tokens(block)

    included = [k for k in
                ["debate", "prior_state", "catalysts", "failure", "moat", "variant"]
                if facet_text.get(k)]

    # Defensive: never emit over-cap (debate-only pathological case).  Fail safe.
    if total > cfg.token_cap:
        logger.error(
            "[dossier_injection] block over cap after all drops (%d > %d) for %s — suppressing",
            total, cfg.token_cap, _g(head, "ticker", "?"),
        )
        return None

    return InjectionResult(
        block_str=block,
        token_count=total,
        staleness_state=staleness,
        intent=question_intent or "general",
        included_facets=included,
        dropped_facets=dropped,
        decay_weights=decay_weights,
    )
