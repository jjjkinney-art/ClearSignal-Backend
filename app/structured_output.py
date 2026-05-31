"""
Utilities for parsing, validating, and repairing model outputs.

This module centralizes the handling of model responses.  It implements
a robust pipeline to extract a structured JSON candidate from a raw
string, validate it against a Pydantic schema, attempt repairs on
common malformations, and perform controlled retries.  If all
attempts fail, a safe fallback instance of the schema is returned.

Usage example:

    from .model_client import model_client
    from .schemas import EquityAnalysis
    result = get_structured_response(prompt, EquityAnalysis, model_client)

"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Type, Any, Dict

# Use get_origin from typing to inspect generic types in a version‑agnostic way.
try:
    from typing import get_origin  # Python 3.8+
except ImportError:  # pragma: no cover - fallback
    def get_origin(tp):  # type: ignore
        return getattr(tp, '__origin__', None)

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def extract_json_candidate(text: str) -> str:
    """Attempt to extract the first balanced JSON object from a text string.

    Language model outputs may include prose, markdown or other
    embellishments before and after the JSON.  This function scans
    the string to locate the first balanced set of curly braces and
    returns that substring.  If balanced braces cannot be found, it
    falls back to a regex search for the first JSON‑like object.  If
    all else fails, the original stripped text is returned.  This
    approach is more robust than simply taking the substring between
    the first ``{`` and the last ``}``.
    """
    from typing import Optional  # local import to avoid polluting module namespace
    first_brace: Optional[int] = None
    brace_count = 0
    for idx, ch in enumerate(text):
        if ch == '{':
            if brace_count == 0:
                first_brace = idx
            brace_count += 1
        elif ch == '}':
            if brace_count > 0:
                brace_count -= 1
                if brace_count == 0 and first_brace is not None:
                    return text[first_brace: idx + 1]
    # Attempt regex fallback for a simple object (no nested braces)
    m = re.search(r"\{[^\{\}]*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text.strip()


def repair_data(parsed: Dict[str, Any], schema: Type[BaseModel]) -> Dict[str, Any]:
    """Attempt to repair common issues in the parsed JSON data.

    This function converts string fields to lists when the schema
    expects a list.  It splits strings on newlines or bullet
    characters.  It fills missing keys with default values from the
    schema.  Additional repair strategies can be added here.

    Stringified-array fix (2026)
    ----------------------------
    LLMs occasionally return a JSON array field as a JSON-encoded string
    instead of a proper JSON array, for example::

        "key_risks": "[\"risk 1\", \"risk 2\"]"   ← wrong: string
        "key_risks": ["risk 1", "risk 2"]          ← correct: array

    The original logic found no newline/bullet delimiters in such
    strings and placed the whole JSON string as a single element in the
    repaired list.  For ``List[str]`` fields Pydantic accepted this, so
    the raw JSON string was silently passed through to the frontend and
    rendered verbatim.  The fix tries ``json.loads`` first whenever the
    string starts with ``[`` and ends with ``]``; if it returns a list
    that list is used directly.  For ``List[Signal]`` fields the same
    fix lets the JSON-decoded dicts be coerced to ``Signal`` objects by
    Pydantic, recovering signals that would otherwise have been lost.
    """
    repaired: Dict[str, Any] = {}
    # Pydantic v2 exposes ``model_fields`` as the public interface to
    # model fields.  Accessing ``__fields__`` in pydantic v2 emits a
    # deprecation warning.  To keep the backend warning‑free we rely
    # exclusively on ``model_fields`` when present.  For older
    # pydantic versions that lack ``model_fields``, we simply treat
    # ``model_fields`` as an empty mapping.  In that case, list
    # detection and default filling below fall back to default
    # instances returned by the schema, which still produces safe
    # objects albeit without string‑to‑list conversion.
    model_fields = getattr(schema, "model_fields", {})  # type: ignore[attr-defined]
    for key, field in model_fields.items():
        if key in parsed:
            value = parsed[key]
            # Convert scalar strings to lists when the schema expects a list.  In
            # pydantic v2 the field annotation is accessible via field.annotation.
            # Use typing.get_origin to detect list types.  In v1 the model
            # exposes outer_type_, which we also check for backwards compatibility.
            is_list_field = False
            try:
                origin = get_origin(field.annotation)
                if origin is list:
                    is_list_field = True
            except Exception:
                pass
            # Fallback for pydantic v1: check outer_type_ when present
            if not is_list_field:
                if hasattr(field, 'outer_type_'):
                    outer = getattr(field, 'outer_type_', None)
                    origin = getattr(outer, '__origin__', None)
                    if outer is list or origin is list:  # type: ignore
                        is_list_field = True
            if is_list_field:
                if isinstance(value, list):
                    repaired[key] = value
                elif isinstance(value, str):
                    stripped = value.strip()
                    # ── Stringified-array fix ──────────────────────────────────
                    # LLMs sometimes return a JSON array field as a JSON-encoded
                    # string, e.g. "key_risks": "[\"r1\",\"r2\"]" instead of
                    # "key_risks": ["r1","r2"].  Without this fix, repair_data
                    # found no newline/bullet delimiters and wrapped the whole
                    # JSON string in a one-element list.  For List[str] fields
                    # Pydantic accepted that single-element list, so raw JSON
                    # strings silently reached the frontend and rendered as-is.
                    # Fix: if the string looks like a JSON array, try json.loads
                    # first.  Use the parsed list directly if it succeeds.
                    if stripped.startswith('[') and stripped.endswith(']'):
                        try:
                            parsed_list = json.loads(stripped)
                            if isinstance(parsed_list, list):
                                repaired[key] = parsed_list
                                continue  # do not fall through to split logic
                        except (json.JSONDecodeError, ValueError):
                            pass  # fall through to split-on-delimiter logic
                    # Fallback: split on newlines, bullets or hyphens
                    items = [item.strip().lstrip('-').strip() for item in re.split(r'[\n\r]+|\u2022|\-|;|\*', value) if item.strip()]
                    repaired[key] = items
                else:
                    repaired[key] = []
            else:
                repaired[key] = value
        else:
            # Use default value from field when key is missing.  Prefer
            # default_factory for list fields to ensure new list instances.
            if getattr(field, 'default_factory', None) is not None:
                repaired[key] = field.default_factory()  # type: ignore[call-arg]
            else:
                repaired[key] = field.default
    return repaired


def get_structured_response(
    prompt: str,
    schema: Type[BaseModel],
    model_client: "ModelClient",
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    **call_params: Any,
) -> BaseModel:
    """Fetch and parse a structured response from the model.

    This function encapsulates the end‑to‑end process for obtaining a
    structured object from a language model.  It performs controlled
    retries with exponential backoff if parsing or validation fails.
    If all attempts fail, it returns a fallback instance of the
    schema populated with default values.

    Parameters
    ----------
    prompt : str
        The prompt to send to the language model.
    schema : Type[BaseModel]
        The Pydantic model class defining the expected structure.
    model_client : ModelClient
        The model client used to make API calls.
    max_retries : int, optional
        Maximum number of attempts (default is 3).
    backoff_factor : float, optional
        Multiplier for the exponential backoff delay between retries.
    **call_params : Any
        Additional keyword arguments passed to the model client call.

    Returns
    -------
    BaseModel
        An instance of ``schema`` populated with data from the model
        or default values if parsing fails.
    """
    for attempt in range(1, max_retries + 1):
        try:
            raw_text = model_client.call(prompt, **call_params)
        except Exception as exc:
            logger.warning(
                json.dumps({
                    "event": "model_call_failed",
                    "error": str(exc),
                    "attempt": attempt,
                })
            )
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        # ── TRACE: raw LLM output ────────────────────────────────────────────
        print(
            f"[get_structured_response] schema={schema.__name__} attempt={attempt} "
            f"raw_text_len={len(raw_text) if raw_text else 0}\n"
            f"[get_structured_response] RAW TEXT: {raw_text!r:.800}"
        )

        candidate = extract_json_candidate(raw_text)

        print(f"[get_structured_response] CANDIDATE JSON: {candidate!r:.600}")

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            logger.warning(
                json.dumps({
                    "event": "json_decode_error",
                    "candidate": candidate,
                    "attempt": attempt,
                })
            )
            m = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None
            else:
                data = None

        print(f"[get_structured_response] PARSED DATA: {data}")

        if data is None:
            time.sleep(backoff_factor * (2 ** (attempt - 1)))
            continue

        # Attempt validation.  Use model_validate when available (pydantic v2)
        try:
            if hasattr(schema, 'model_validate'):  # pydantic v2
                result = schema.model_validate(data)  # type: ignore[attr-defined]
            else:
                result = schema.parse_obj(data)  # type: ignore[call-arg]
            print(f"[get_structured_response] VALIDATED RESULT: {result}")
            return result
        except ValidationError as ve:
            logger.warning(
                json.dumps({
                    "event": "schema_validation_failed",
                    "errors": ve.errors(),
                    "attempt": attempt,
                })
            )
            repaired = repair_data(data, schema)
            print(f"[get_structured_response] REPAIRED DATA: {repaired}")
            try:
                if hasattr(schema, 'model_validate'):  # pydantic v2
                    result = schema.model_validate(repaired)  # type: ignore[attr-defined]
                else:
                    result = schema.parse_obj(repaired)  # type: ignore[call-arg]
                print(f"[get_structured_response] REPAIRED RESULT: {result}")
                return result
            except ValidationError:
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue

    # All attempts failed — return default empty instance
    logger.error(
        json.dumps({
            "event": "structured_response_fallback",
            "schema": schema.__name__,
        })
    )
    print(f"[get_structured_response] FALLBACK: returning empty {schema.__name__}()")
    return schema()  # type: ignore