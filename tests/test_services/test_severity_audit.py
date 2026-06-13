"""
Phase 10C · Slice 1 — severity vocabulary audit.

This is the "no unregistered vocabulary" guard.  It encodes the complete
inventory of severity vocabularies that exist in the codebase, asserts each is
fully covered by the canonical translator, and scans the actual source files
so that introducing a NEW (unregistered) severity vocabulary fails the build.

Inventory (the four pre-10C vocabularies, all registered in severity_model):
  1. alert_prioritizer.py      critical | high | medium | ignore
  2. loop_delivery_service.py  info | warning | alert | critical   (_SEVERITY_RANK)
  3. watchlist_alert_payload.py  critical | high | medium | low | info
  4. morning_brief_service.py  critical | high | medium | low | "" (_SEVERITY_RANK)
"""

import re
from pathlib import Path

import pytest

from app.services import severity_model as sm
from app.services.severity_model import (
    LEGACY_VOCABULARIES,
    KNOWN_TOKENS,
    DEFENSIVE_ALIASES,
    CANONICAL_SEVERITIES,
    to_canonical_severity,
)

_APP_SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"


# ---------------------------------------------------------------------------
# Registry completeness — translator covers every registered token
# ---------------------------------------------------------------------------

class TestRegistryCompleteness:
    def test_four_vocabularies_registered(self):
        assert set(LEGACY_VOCABULARIES) == {
            "alert_prioritizer",
            "delivery_ledger",
            "watchlist_alert",
            "briefing_ranking",
        }

    def test_every_registered_token_is_translatable(self):
        # Strict translation must succeed for every registered token except the
        # empty string (which is intentionally handled by the default param).
        for vocab, tokens in LEGACY_VOCABULARIES.items():
            for token in tokens:
                if token == "":
                    # empty is absence, not a vocabulary value
                    assert to_canonical_severity(token) in CANONICAL_SEVERITIES
                    continue
                result = to_canonical_severity(token, strict=True)
                assert result in CANONICAL_SEVERITIES, (vocab, token)

    def test_translator_domain_equals_registered_union(self):
        # The translator must know EXACTLY the union of registered vocabulary
        # tokens plus the documented defensive aliases (minus the empty string).
        # A token known to the translator but neither registered nor a declared
        # alias — or registered but unknown — fails here.  This is the core
        # "no unregistered vocabulary" invariant.
        registered = set()
        for tokens in LEGACY_VOCABULARIES.values():
            registered |= set(tokens)
        registered.discard("")
        assert KNOWN_TOKENS == registered | set(DEFENSIVE_ALIASES)

    def test_no_cross_vocabulary_collisions(self):
        # Each shared token must mean the same canonical level across every
        # vocabulary that uses it (proves a single unified map is valid).
        token_to_canonical = {}
        for tokens in LEGACY_VOCABULARIES.values():
            for token in tokens:
                if token == "":
                    continue
                canon = to_canonical_severity(token)
                if token in token_to_canonical:
                    assert token_to_canonical[token] == canon, token
                token_to_canonical[token] = canon


# ---------------------------------------------------------------------------
# Source-file scan — no new vocabulary literal sneaks in
# ---------------------------------------------------------------------------

class TestSourceFileScan:
    """Scan the known severity-bearing source files and assert every severity
    string literal they contain belongs to a registered vocabulary.

    If a future change introduces a brand-new severity token (a fifth
    vocabulary) in one of these files, this test fails until the token is
    registered in severity_model.LEGACY_VOCABULARIES and mapped.
    """

    # Files known to define/use a severity vocabulary, and the exact set of
    # severity tokens each is permitted to contain.  Permitted == union of the
    # registered vocabularies (any registered token may legitimately appear).
    SEVERITY_FILES = [
        "alert_prioritizer.py",
        "loop_delivery_service.py",
        "watchlist_alert_payload.py",
        "morning_brief_service.py",
        "severity_model.py",
    ]

    # Tokens that look like severities but are NOT — substrings we must not
    # mistake for a severity vocabulary (drift directions, change categories,
    # impact levels in unrelated maps, etc.).  The scan only checks tokens that
    # appear as values in an explicit severity context, so we keep this list
    # tight and assert against the registered union directly.
    @property
    def _registered_union(self):
        union = set()
        for tokens in LEGACY_VOCABULARIES.values():
            union |= set(tokens)
        union |= set(CANONICAL_SEVERITIES)
        # the translator's defensive aliases are registered too
        union |= set(KNOWN_TOKENS)
        union.add("")  # empty is allowed as an absence sentinel
        return union

    def _severity_rank_literals(self, text: str):
        """Extract quoted keys from any ``_SEVERITY_RANK``/``_SEVERITY_MAP``
        or ``_TRANSLATION_MAP`` dict literal in the source text."""
        found = set()
        # Match a dict assigned to a *_SEVERITY_* / *_TRANSLATION_* name, then
        # pull the quoted keys out of that block.
        for m in re.finditer(
            r"_(?:SEVERITY_RANK|SEVERITY_MAP|TRANSLATION_MAP)\s*:?[^=]*=\s*\{(.*?)\}",
            text,
            re.DOTALL,
        ):
            block = m.group(1)
            for key in re.finditer(r"""["']([a-zA-Z]*)["']\s*:""", block):
                found.add(key.group(1).lower())
        return found

    @pytest.mark.parametrize("filename", SEVERITY_FILES)
    def test_severity_dict_literals_are_registered(self, filename):
        path = _APP_SERVICES / filename
        assert path.exists(), f"expected severity file missing: {filename}"
        text = path.read_text()
        literals = self._severity_rank_literals(text)
        unregistered = literals - self._registered_union
        assert not unregistered, (
            f"{filename} introduces unregistered severity tokens {sorted(unregistered)}; "
            f"register them in severity_model.LEGACY_VOCABULARIES and map them."
        )

    def test_alert_prioritizer_priority_literals_registered(self):
        # alert_prioritizer assigns priority via `priority = "..."`, not a dict.
        text = (_APP_SERVICES / "alert_prioritizer.py").read_text()
        assigned = {
            m.group(1).lower()
            for m in re.finditer(r"""priority\s*=\s*["']([a-zA-Z]+)["']""", text)
        }
        unregistered = assigned - self._registered_union
        assert not unregistered, (
            f"alert_prioritizer introduces unregistered priority tokens "
            f"{sorted(unregistered)}; register + map them in severity_model."
        )


# ---------------------------------------------------------------------------
# Single-translator invariant
# ---------------------------------------------------------------------------

class TestSingleTranslator:
    def test_only_one_translation_map_module(self):
        # severity_model is the only module permitted to own a *_TRANSLATION_MAP.
        offenders = []
        for path in _APP_SERVICES.glob("*.py"):
            if path.name == "severity_model.py":
                continue
            if "_TRANSLATION_MAP" in path.read_text():
                offenders.append(path.name)
        assert not offenders, (
            f"severity translation must live only in severity_model.py; "
            f"found _TRANSLATION_MAP in {offenders}"
        )

    def test_watchlist_payload_delegates(self):
        # watchlist_alert_payload must no longer carry its own severity map.
        text = (_APP_SERVICES / "watchlist_alert_payload.py").read_text()
        assert "_SEVERITY_MAP" not in text, (
            "watchlist_alert_payload still defines its own _SEVERITY_MAP; "
            "it must delegate to severity_model."
        )
        assert "severity_model" in text
