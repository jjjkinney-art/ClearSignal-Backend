"""Synthesis-model A/B variants (Sprint 3B.2).

Prompt reduction is closed: compact_a and compact_a2 both failed the live
quality gate, and compact_schema_a could only reach 0.27%. Synthesis remains
the slowest stage (~10.3s median, slowest on 34/36 queries), so the remaining
lever is the model itself.

This module isolates MODEL CHOICE and nothing else. A variant changes the
model name passed to the OpenAI client and leaves every other input identical:
the prompt is byte-identical, temperature, max_tokens, timeout, retry count
and backoff all come from the same settings the production client uses, and
retrieval, agents, integrity, canonicalization and polishing are untouched.

Two facts shaped the design:

**The candidate model is operator-configured, not hardcoded.** The only models
named anywhere in this configuration are `gpt-4o` (which synthesis does not
use) and `gpt-4o-mini` — and synthesis already runs `gpt-4o-mini`, the small
model in that family. Hardcoding a "faster" model here would be an assumption
about what a given deployment's account can actually reach. `fast_a` therefore
reads `settings.synthesis_model_fast_a`, and is inert until an operator sets
it.

**An unconfigured or unauthorized variant serves control.** There is no error
path that can leave a request without a synthesis model: every failure to
resolve a variant resolves to the production client.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MODEL_VARIANT_CONTROL = "control"
MODEL_VARIANT_FAST_A = "fast_a"
KNOWN_MODEL_VARIANTS = (MODEL_VARIANT_CONTROL, MODEL_VARIANT_FAST_A)

# Cache of variant -> ModelClient. Building a client opens no connection, but
# one instance per variant keeps behavior identical across requests and avoids
# re-reading settings on every synthesis call.
_CLIENT_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def configured_model_for_variant(variant: str) -> str:
    """The model name a variant would use, or "" when it is not configured.

    ``control`` always reports the production synthesis model, so a caller can
    log what actually served a request without reaching into settings.
    """
    try:
        from ..config import settings
        if variant == MODEL_VARIANT_FAST_A:
            return str(getattr(settings, "synthesis_model_fast_a", "") or "")
        return str(getattr(settings, "synthesis_model", "") or "")
    except Exception:  # pragma: no cover - settings must never break synthesis
        return ""


def resolve_model_variant(requested: Optional[str], *, authorized: bool) -> str:
    """Resolve the synthesis-model variant for a request.

    Fails closed to ``control`` on every ambiguity: an unauthorized caller, an
    unknown variant name, or a variant whose model has not been configured on
    this deployment. Selecting an alternate model requires the same
    authorization as Sprint 3A.1 profiling detail, so no ordinary user can
    reach it.
    """
    if not authorized:
        return MODEL_VARIANT_CONTROL
    name = str(requested or "").strip().lower()
    if name not in KNOWN_MODEL_VARIANTS:
        return MODEL_VARIANT_CONTROL
    if name != MODEL_VARIANT_CONTROL and not configured_model_for_variant(name):
        # Requested a variant this deployment has no model for.
        logger.warning(
            "[synthesis] model variant %r requested but no model configured; "
            "serving control", name,
        )
        return MODEL_VARIANT_CONTROL
    return name


def client_for_variant(variant: str) -> Any:
    """Return the ModelClient for a variant.

    ``control`` returns the exact production ``synthesis_client`` object — not
    a copy — so the control path is provably the current code path. Any other
    variant returns a client built from the SAME settings with only the model
    name substituted, so the experiment isolates model capability rather than
    also changing temperature, token budget, timeout or retry behavior.
    """
    from ..model_client import synthesis_client

    if variant == MODEL_VARIANT_CONTROL or variant not in KNOWN_MODEL_VARIANTS:
        return synthesis_client

    model = configured_model_for_variant(variant)
    if not model:
        return synthesis_client

    cached = _CLIENT_CACHE.get(variant)
    if cached is not None and getattr(cached, "model", None) == model:
        return cached

    try:
        from ..config import settings
        from ..model_client import ModelClient
        client = ModelClient(
            api_key=settings.openai_api_key,
            model=model,
            # Every remaining parameter is taken from the same settings the
            # production synthesis client uses.
            temperature=settings.temperature,
            max_tokens=settings.synthesis_max_tokens,
            timeout=settings.synthesis_timeout,
            max_retries=settings.synthesis_max_retries,
            backoff_factor=settings.model_backoff_factor,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "[synthesis] could not build client for variant %r (%r); "
            "serving control", variant, exc,
        )
        return synthesis_client

    with _CACHE_LOCK:
        _CLIENT_CACHE[variant] = client
    return client


def describe_variant(variant: str) -> Dict[str, Optional[str]]:
    """Metadata for the observability block. Never includes prompt text."""
    client = client_for_variant(variant)
    return {
        "synthesis_model_variant": variant,
        "synthesis_model": getattr(client, "model", None),
        "synthesis_provider": "openai",
    }
