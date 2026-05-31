"""
tests/test_repair_data_stringified_arrays.py

Regression suite for the stringified-array bug in repair_data().

Root cause
----------
LLMs occasionally return a JSON array field as a JSON-encoded string
rather than a proper JSON array, e.g.

    "key_risks": "[\"risk 1\", \"risk 2\"]"   ← LLM serialises the array as a string
    "key_risks": ["risk 1", "risk 2"]          ← correct JSON array

The original repair_data() split on newlines/bullets and found no
delimiters, so it wrapped the whole JSON string in a single-element
list.  For List[str] fields Pydantic validated this successfully,
causing raw JSON strings to be sent to the frontend and rendered as-is.

For List[Signal] fields the same issue silently discarded all signals
because Pydantic could not coerce a raw JSON string to a Signal object.

Fix
---
repair_data() now detects strings that begin with '[' and end with ']',
attempts json.loads first, and uses the parsed list directly when it
succeeds.  The original split-on-delimiter logic is the fallback.

Run
---
    python3 -m pytest tests/test_repair_data_stringified_arrays.py -v
"""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from app.schemas import (
    InvestmentThesis,
    ValuationView,
    MacroSensitivity,
    RiskProfile,
    MarketContext,
    QualityAssessment,
    Signal,
)
from app.structured_output import repair_data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_thesis(**overrides) -> dict:
    """Return a minimal dict that lets InvestmentThesis validate."""
    base = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "confidence_score": 0.65,
    }
    base.update(overrides)
    return base


def _minimal_valuation(**overrides) -> dict:
    base = {
        "pe_assessment": "test",
        "overall": "test overview",
        "confidence": 0.6,
    }
    base.update(overrides)
    return base


# ── repair_data: List[str] with stringified JSON array ───────────────────────

class TestRepairDataStringifiedListStr:
    """Stringified JSON arrays on List[str] fields must be parsed back to real lists."""

    @pytest.mark.parametrize("field,value,expected", [
        (
            "key_risks",
            '["Rate compression on 28x multiple", "China revenue risk", "Hardware slowdown", "Regulatory exposure"]',
            ["Rate compression on 28x multiple", "China revenue risk", "Hardware slowdown", "Regulatory exposure"],
        ),
        (
            "key_drivers",
            '["Services margin expansion", "Buyback EPS amplification", "iPhone base", "EM growth"]',
            ["Services margin expansion", "Buyback EPS amplification", "iPhone base", "EM growth"],
        ),
        (
            "what_changes_the_thesis",
            '["Fed signals rate cuts", "China reopens", "Services misses", "Buyback paused"]',
            ["Fed signals rate cuts", "China reopens", "Services misses", "Buyback paused"],
        ),
    ])
    def test_stringified_array_is_parsed(self, field, value, expected):
        """repair_data must convert a stringified JSON array to a real list."""
        data = {field: value}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired[field] == expected, (
            f"repair_data({field!r}) returned {repaired[field]!r}, "
            f"expected {expected!r}. "
            "The raw JSON string must NOT appear as a single list element."
        )

    def test_key_risks_not_single_json_string_element(self):
        """After repair_data, key_risks must NOT be a single-element list whose
        only element is a raw JSON string starting with '['."""
        data = {"key_risks": '["r1", "r2", "r3"]'}
        repaired = repair_data(data, InvestmentThesis)
        result = repaired["key_risks"]
        assert len(result) == 3, f"Expected 3 risks, got {len(result)}: {result}"
        for item in result:
            assert not item.strip().startswith('['), (
                f"Risk item {item!r} is a raw JSON string — the fix did not fire."
            )

    def test_key_drivers_not_single_json_string_element(self):
        data = {"key_drivers": '["d1", "d2", "d3", "d4"]'}
        repaired = repair_data(data, InvestmentThesis)
        result = repaired["key_drivers"]
        assert len(result) == 4, f"Expected 4 drivers, got {len(result)}: {result}"
        for item in result:
            assert not item.strip().startswith('['), (
                f"Driver item {item!r} is a raw JSON string — the fix did not fire."
            )


# ── Full round-trip: repair + InvestmentThesis validation ────────────────────

class TestRoundTripInvestmentThesis:
    """After repair_data, InvestmentThesis.model_validate must produce real lists."""

    def test_key_risks_round_trip(self):
        raw = _minimal_thesis(
            key_risks='["risk A", "risk B", "risk C", "risk D"]'
        )
        repaired = repair_data(raw, InvestmentThesis)
        thesis = InvestmentThesis.model_validate(repaired)
        assert thesis.key_risks == ["risk A", "risk B", "risk C", "risk D"]

    def test_key_drivers_round_trip(self):
        raw = _minimal_thesis(
            key_drivers='["driver 1", "driver 2", "driver 3", "driver 4"]'
        )
        repaired = repair_data(raw, InvestmentThesis)
        thesis = InvestmentThesis.model_validate(repaired)
        assert thesis.key_drivers == ["driver 1", "driver 2", "driver 3", "driver 4"]

    def test_what_changes_the_thesis_round_trip(self):
        raw = _minimal_thesis(
            what_changes_the_thesis='["trigger 1", "trigger 2", "trigger 3", "trigger 4"]'
        )
        repaired = repair_data(raw, InvestmentThesis)
        thesis = InvestmentThesis.model_validate(repaired)
        assert thesis.what_changes_the_thesis == [
            "trigger 1", "trigger 2", "trigger 3", "trigger 4"
        ]

    def test_multiple_stringified_fields_in_one_response(self):
        """All affected fields in a single LLM response are repaired correctly."""
        raw = _minimal_thesis(
            key_risks='["risk 1", "risk 2"]',
            key_drivers='["driver 1", "driver 2"]',
            what_changes_the_thesis='["trigger 1", "trigger 2"]',
        )
        repaired = repair_data(raw, InvestmentThesis)
        thesis = InvestmentThesis.model_validate(repaired)
        assert thesis.key_risks == ["risk 1", "risk 2"]
        assert thesis.key_drivers == ["driver 1", "driver 2"]
        assert thesis.what_changes_the_thesis == ["trigger 1", "trigger 2"]


# ── repair_data: List[Signal] with stringified JSON array ─────────────────────

class TestRepairDataStringifiedSignalList:
    """Stringified JSON arrays on List[Signal] fields must parse to Signal dicts."""

    def test_signals_stringified_array_parsed_to_dicts(self):
        """repair_data must parse a stringified signal array back to a list of dicts."""
        signal_data = [
            {
                "signal": "Services margin at 72% offsets hardware P/E pressure",
                "direction": "bullish",
                "signal_type": "structural",
                "impact_score": 0.85,
                "time_horizon": "medium_term",
            }
        ]
        data = {"signals": json.dumps(signal_data)}
        repaired = repair_data(data, ValuationView)
        result = repaired["signals"]
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == 1, f"Expected 1 signal, got {len(result)}"
        assert isinstance(result[0], dict), (
            f"Signal element must be a dict after repair, got {type(result[0])}: {result[0]!r}"
        )
        assert result[0]["signal"] == "Services margin at 72% offsets hardware P/E pressure"

    def test_signals_stringified_validates_to_signal_objects(self):
        """After repair, ValuationView.model_validate must produce real Signal objects."""
        signal_data = [
            {
                "signal": "Services ARR durability thesis",
                "direction": "bullish",
                "signal_type": "structural",
                "impact_score": 0.80,
                "time_horizon": "medium_term",
                "importance_reason": "Recurring cash flow offsets hardware cyclicality",
                "evidence_origin": "earnings call",
                "source_category": "earnings",
            }
        ]
        raw = _minimal_valuation(signals=json.dumps(signal_data))
        repaired = repair_data(raw, ValuationView)
        v = ValuationView.model_validate(repaired)
        assert len(v.signals) == 1
        assert isinstance(v.signals[0], Signal)
        assert v.signals[0].signal == "Services ARR durability thesis"
        assert v.signals[0].direction == "bullish"

    def test_signals_stringified_on_risk_profile(self):
        """Same fix applies to RiskProfile.signals."""
        signal_data = [
            {
                "signal": "Refinancing risk at elevated rates",
                "direction": "bearish",
                "signal_type": "risk",
                "impact_score": 0.70,
                "time_horizon": "short_term",
            }
        ]
        raw = {"signals": json.dumps(signal_data), "overall": "risk overview", "confidence": 0.5}
        repaired = repair_data(raw, RiskProfile)
        r = RiskProfile.model_validate(repaired)
        assert len(r.signals) == 1
        assert r.signals[0].direction == "bearish"


# ── Existing behaviour preserved: non-array strings still split ───────────────

class TestNonArrayStringsStillSplit:
    """Strings that do NOT look like JSON arrays must still split on delimiters."""

    def test_newline_delimited_list_still_splits(self):
        data = {"key_risks": "rate compression\nChina risk\nhardware slowdown"}
        repaired = repair_data(data, InvestmentThesis)
        assert len(repaired["key_risks"]) == 3
        assert "rate compression" in repaired["key_risks"]

    def test_bullet_delimited_list_still_splits(self):
        data = {"key_drivers": "services margin • buyback EPS • iPhone base • EM growth"}
        repaired = repair_data(data, InvestmentThesis)
        # Original split logic fires for strings not starting with '['
        assert len(repaired["key_drivers"]) >= 1

    def test_plain_string_becomes_single_element_list(self):
        """A plain string with no array syntax becomes a single-element list."""
        data = {"key_risks": "single risk with no array brackets"}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired["key_risks"] == ["single risk with no array brackets"]

    def test_already_proper_list_passes_through(self):
        """A proper list is passed through unchanged."""
        data = {"key_risks": ["risk 1", "risk 2", "risk 3"]}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired["key_risks"] == ["risk 1", "risk 2", "risk 3"]

    def test_malformed_bracket_string_falls_back_to_split(self):
        """A string starting with '[' that is invalid JSON falls back to split logic."""
        data = {"key_risks": "[not valid json, missing closing bracket"}
        repaired = repair_data(data, InvestmentThesis)
        # Should not crash; should fall through to split-on-delimiter logic
        assert isinstance(repaired["key_risks"], list)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases for the stringified-array fix."""

    def test_empty_json_array_string(self):
        data = {"key_risks": "[]"}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired["key_risks"] == []

    def test_nested_json_array_of_arrays(self):
        """JSON array of arrays produces a list of lists (Pydantic may reject,
        but repair_data itself should not crash or silently corrupt.)"""
        data = {"key_risks": '[["a", "b"], ["c"]]'}
        repaired = repair_data(data, InvestmentThesis)
        # The repaired value should be a list with 2 sub-lists
        result = repaired["key_risks"]
        assert isinstance(result, list)
        assert len(result) == 2

    def test_whitespace_around_json_array(self):
        """Leading/trailing whitespace around a JSON array is handled."""
        data = {"key_risks": '  ["risk 1", "risk 2"]  '}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired["key_risks"] == ["risk 1", "risk 2"]

    def test_integer_values_in_list_schema(self):
        """Non-string, non-list values produce an empty list (existing behaviour)."""
        data = {"key_risks": 42}
        repaired = repair_data(data, InvestmentThesis)
        assert repaired["key_risks"] == []


# ── Frontend payload: no raw JSON strings in serialized thesis ────────────────

class TestFrontendPayloadClean:
    """After fix, model_dump() on a thesis with stringified fields must produce
    clean lists — no element should be a raw JSON string."""

    def test_thesis_dump_has_no_raw_json_string_elements(self):
        raw = _minimal_thesis(
            key_risks='["rate risk", "china risk", "hardware risk", "regulatory risk"]',
            key_drivers='["services", "buyback", "installed base", "india"]',
            what_changes_the_thesis='["fed cuts", "china", "services miss", "buyback pause"]',
        )
        repaired = repair_data(raw, InvestmentThesis)
        thesis = InvestmentThesis.model_validate(repaired)
        payload = thesis.model_dump()

        for field in ("key_risks", "key_drivers", "what_changes_the_thesis"):
            items = payload[field]
            for item in items:
                assert not str(item).strip().startswith('['), (
                    f"Field {field!r} contains raw JSON string element: {item!r}\n"
                    "This would render verbatim in the frontend."
                )
