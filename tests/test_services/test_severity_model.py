"""
Phase 10C · Slice 1 — canonical severity model tests.

Targets 100% coverage of the translator and adapters, proving:
  * every legacy value maps to the correct canonical level
  * no legacy token is left unmapped
  * unknown values fail safely (lenient) or raise (strict)
  * the watchlist delegation is behavior-preserving (no behavior change)
"""

import pytest

from app.services import severity_model as sm
from app.services.severity_model import (
    CRITICAL, HIGH, MEDIUM, LOW, INFO,
    CANONICAL_SEVERITIES,
    KNOWN_TOKENS,
    LEGACY_VOCABULARIES,
    UnknownSeverityError,
    to_canonical_severity,
    severity_rank,
    is_canonical,
    from_alert_prioritizer,
    from_watchlist_alert,
    from_delivery_ledger,
    from_briefing_ranking,
)


# ---------------------------------------------------------------------------
# Canonical ladder shape
# ---------------------------------------------------------------------------

class TestCanonicalLadder:
    def test_exactly_five_levels(self):
        assert CANONICAL_SEVERITIES == (CRITICAL, HIGH, MEDIUM, LOW, INFO)
        assert len(CANONICAL_SEVERITIES) == 5

    def test_values_are_lowercase_strings(self):
        assert CRITICAL == "critical"
        assert HIGH == "high"
        assert MEDIUM == "medium"
        assert LOW == "low"
        assert INFO == "info"

    def test_rank_is_strictly_monotonic(self):
        ranks = [severity_rank(s) for s in CANONICAL_SEVERITIES]
        # CANONICAL_SEVERITIES is ordered most → least severe
        assert ranks == sorted(ranks, reverse=True)
        assert ranks == [4, 3, 2, 1, 0]

    def test_is_canonical(self):
        for s in CANONICAL_SEVERITIES:
            assert is_canonical(s)
        assert not is_canonical("warning")
        assert not is_canonical("alert")
        assert not is_canonical("ignore")
        assert not is_canonical("")

    def test_severity_rank_unknown_is_floor_not_raise(self):
        assert severity_rank("warning") == 0      # non-canonical → floor
        assert severity_rank("") == 0
        assert severity_rank("garbage") == 0


# ---------------------------------------------------------------------------
# Translator — full coverage of every known token
# ---------------------------------------------------------------------------

class TestTranslatorFullCoverage:
    # Every token the translator is required to know, with its canonical target.
    EXPECTED = {
        # canonical identity
        "critical": CRITICAL,
        "high":     HIGH,
        "medium":   MEDIUM,
        "low":      LOW,
        "info":     INFO,
        # alert_prioritizer
        "ignore":   INFO,
        # delivery_ledger
        "warning":  MEDIUM,
        "alert":    HIGH,
        # alias
        "none":     INFO,
    }

    @pytest.mark.parametrize("raw,expected", sorted(EXPECTED.items()))
    def test_each_known_token_maps_correctly(self, raw, expected):
        assert to_canonical_severity(raw) == expected

    def test_known_tokens_set_matches_expected(self):
        # No token is known that we didn't enumerate, and vice versa.
        assert KNOWN_TOKENS == set(self.EXPECTED.keys())

    def test_every_known_token_yields_a_canonical_value(self):
        for token in KNOWN_TOKENS:
            assert to_canonical_severity(token) in CANONICAL_SEVERITIES

    def test_case_and_whitespace_insensitive(self):
        assert to_canonical_severity("  CRITICAL ") == CRITICAL
        assert to_canonical_severity("Warning") == MEDIUM
        assert to_canonical_severity("IGNORE") == INFO


# ---------------------------------------------------------------------------
# Fail-safe behavior
# ---------------------------------------------------------------------------

class TestFailSafe:
    def test_unknown_lenient_defaults_to_info(self):
        assert to_canonical_severity("nonsense") == INFO
        assert to_canonical_severity("") == INFO
        assert to_canonical_severity(None) == INFO  # type: ignore[arg-type]

    def test_unknown_respects_custom_default(self):
        assert to_canonical_severity("nonsense", default=LOW) == LOW

    def test_unknown_strict_raises(self):
        with pytest.raises(UnknownSeverityError):
            to_canonical_severity("nonsense", strict=True)
        with pytest.raises(UnknownSeverityError):
            to_canonical_severity("", strict=True)

    def test_strict_does_not_raise_on_known(self):
        assert to_canonical_severity("warning", strict=True) == MEDIUM

    def test_non_canonical_default_rejected(self):
        with pytest.raises(ValueError):
            to_canonical_severity("x", default="warning")

    def test_unknown_never_escalates(self):
        # Fail-low invariant: an unknown value must never become CRITICAL/HIGH.
        for bad in ["", "xyz", "danger", "urgent", "p0", "sev1"]:
            assert severity_rank(to_canonical_severity(bad)) <= severity_rank(INFO)


# ---------------------------------------------------------------------------
# Source adapters
# ---------------------------------------------------------------------------

class TestAlertPrioritizerAdapter:
    @pytest.mark.parametrize("raw,expected", [
        ("critical", CRITICAL),
        ("high",     HIGH),
        ("medium",   MEDIUM),
        ("ignore",   INFO),
    ])
    def test_maps_full_vocabulary(self, raw, expected):
        assert from_alert_prioritizer(raw) == expected

    def test_covers_entire_registered_vocabulary(self):
        for token in LEGACY_VOCABULARIES["alert_prioritizer"]:
            assert from_alert_prioritizer(token) in CANONICAL_SEVERITIES

    def test_unknown_fails_low(self):
        assert from_alert_prioritizer("bogus") == INFO


class TestWatchlistAlertAdapter:
    @pytest.mark.parametrize("raw,expected", [
        ("critical", CRITICAL),
        ("high",     HIGH),
        ("medium",   MEDIUM),
        ("low",      LOW),
        ("info",     INFO),
    ])
    def test_identity_for_canonical(self, raw, expected):
        assert from_watchlist_alert(raw) == expected

    def test_unknown_falls_back_to_low(self):
        # Preserves the pre-10C watchlist fallback (unknown → low).
        assert from_watchlist_alert("bogus") == LOW
        assert from_watchlist_alert("") == LOW


class TestDeliveryLedgerAdapter:
    @pytest.mark.parametrize("raw,expected", [
        ("info",     INFO),
        ("warning",  MEDIUM),
        ("alert",    HIGH),
        ("critical", CRITICAL),
    ])
    def test_maps_full_vocabulary(self, raw, expected):
        assert from_delivery_ledger(raw) == expected

    def test_covers_entire_registered_vocabulary(self):
        for token in LEGACY_VOCABULARIES["delivery_ledger"]:
            assert from_delivery_ledger(token) in CANONICAL_SEVERITIES

    def test_unknown_fails_low(self):
        assert from_delivery_ledger("bogus") == INFO


class TestBriefingRankingAdapter:
    @pytest.mark.parametrize("raw,expected", [
        ("critical", CRITICAL),
        ("high",     HIGH),
        ("medium",   MEDIUM),
        ("low",      LOW),
        ("",         INFO),
    ])
    def test_maps_full_vocabulary(self, raw, expected):
        assert from_briefing_ranking(raw) == expected

    def test_covers_entire_registered_vocabulary(self):
        for token in LEGACY_VOCABULARIES["briefing_ranking"]:
            assert from_briefing_ranking(token) in CANONICAL_SEVERITIES


# ---------------------------------------------------------------------------
# Behavior preservation — watchlist_alert_payload delegation
# ---------------------------------------------------------------------------

class TestWatchlistDelegationNoBehaviorChange:
    """Asserts the pre-10C watchlist normalize_severity map is reproduced exactly."""

    # The exact (raw → result) table from the pre-10C _SEVERITY_MAP, including
    # its unknown→low fallback.
    PRE_10C = {
        "critical": "critical",
        "high":     "high",
        "medium":   "medium",
        "low":      "low",
        "info":     "info",
        "ignore":   "info",
        "warning":  "medium",
        "alert":    "high",
        "none":     "info",
        "":         "low",       # pre-10C explicit "" → low
        "garbage":  "low",       # pre-10C fallback → low
    }

    @pytest.mark.parametrize("raw,expected", sorted(PRE_10C.items()))
    def test_normalize_severity_unchanged(self, raw, expected):
        from app.services.watchlist_alert_payload import normalize_severity
        assert normalize_severity(raw) == expected

    def test_sev_constants_unchanged(self):
        from app.services import watchlist_alert_payload as wap
        assert wap.SEV_CRITICAL == "critical"
        assert wap.SEV_HIGH == "high"
        assert wap.SEV_MEDIUM == "medium"
        assert wap.SEV_LOW == "low"
        assert wap.SEV_INFO == "info"
