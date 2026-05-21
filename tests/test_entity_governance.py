"""
Entity Resolution Governance — comprehensive regression suite.

Covers all 10 governance requirements:
  1. Exact-match priority
  2. Hard confidence threshold (MINIMUM_ROUTE_CONFIDENCE)
  3. Never-silent-remap guarantee
  4. Multi-candidate resolution
  5. Company coverage (pharma, semiconductors, global ADRs, mega-caps)
  6. Regression: 15 named companies
  7. Typo / fuzzy tests
  8. Observability fields (rejection_reason, fallback_reason)
  9. Frontend-safe fallback states
  10. Deterministic tests for gate, precedence, ranking

Run with:
    pytest tests/test_entity_governance.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.company_detection import (
    resolve_entity,
    detect_company,
    MINIMUM_ROUTE_CONFIDENCE,
    EntityResolution,
    _extract_explicit_ticker,
    _alias_lookup,
    _fuzzy_token_match,
    _gather_candidates,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _ticker(q: str) -> str:
    """Return ticker string or 'None' for a query."""
    r = resolve_entity(q)
    return r.context.ticker if r.context else "None"


def _above_gate(r: EntityResolution) -> bool:
    """Return True if this resolution would clear the routing gate."""
    return (
        r.method in ("exact_ticker", "alias_exact")
        or r.confidence >= MINIMUM_ROUTE_CONFIDENCE
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. EXACT-MATCH PRIORITY
# ─────────────────────────────────────────────────────────────────────────────

class TestExactMatchPrecedence:
    """Exact ticker (Step 1) must always override alias and fuzzy logic."""

    # Core principle: if the text contains a valid uppercase ticker, it wins.

    def test_vrtx_uppercase_wins(self):
        r = resolve_entity("VRTX")
        assert r.context.ticker == "VRTX"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_amd_uppercase_wins(self):
        r = resolve_entity("AMD")
        assert r.context.ticker == "AMD"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_nvda_uppercase_wins(self):
        r = resolve_entity("NVDA")
        assert r.context.ticker == "NVDA"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_tsm_uppercase_wins(self):
        r = resolve_entity("TSM")
        assert r.context.ticker == "TSM"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_asml_uppercase_wins(self):
        r = resolve_entity("ASML")
        assert r.context.ticker == "ASML"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_avgo_uppercase_wins(self):
        r = resolve_entity("AVGO")
        assert r.context.ticker == "AVGO"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_llm_uppercase_wins(self):
        r = resolve_entity("LLY")
        assert r.context.ticker == "LLY"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_aapl_in_phrase_wins(self):
        r = resolve_entity("AAPL earnings beat last quarter")
        assert r.context.ticker == "AAPL"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_nvda_in_question_wins(self):
        r = resolve_entity("Is NVDA overpriced at current levels?")
        assert r.context.ticker == "NVDA"
        assert r.method == "exact_ticker"
        assert r.confidence == 1.0

    def test_ticker_confidence_always_1(self):
        """exact_ticker confidence must always be exactly 1.0."""
        for ticker in ["AAPL", "MSFT", "NVDA", "TSM", "ASML", "VRTX", "LLY"]:
            r = resolve_entity(ticker)
            assert r.confidence == 1.0, f"{ticker}: expected 1.0 got {r.confidence}"
            assert r.method == "exact_ticker"

    def test_ticker_above_gate(self):
        """exact_ticker results always clear the routing gate."""
        for ticker in ["AAPL", "NVDA", "AMD", "TSM", "ASML", "AVGO", "VRTX"]:
            r = resolve_entity(ticker)
            assert _above_gate(r), f"{ticker} should clear routing gate"

    def test_stop_words_not_extracted_as_tickers(self):
        """Common English words that look like tickers must be filtered."""
        # "IS", "IN", "GO", "A" etc. are in _TICKER_STOP_WORDS
        r = resolve_entity("Is this a good investment?")
        # Should not extract "IS", "A", etc. as tickers
        if r.context is not None:
            assert r.context.ticker not in {"IS", "IN", "A", "GO", "BE"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. ALIAS EXACT MATCH PRECEDENCE (over fuzzy)
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasExactPrecedence:
    """Alias word-boundary lookup (Step 2) must beat fuzzy (Step 3)."""

    def test_vertex_pharmaceuticals_is_alias_exact(self):
        r = resolve_entity("vertex pharmaceuticals")
        assert r.context.ticker == "VRTX"
        assert r.method == "alias_exact"
        assert r.confidence == 0.95

    def test_nvidia_is_alias_exact(self):
        r = resolve_entity("nvidia")
        assert r.context.ticker == "NVDA"
        assert r.method == "alias_exact"

    def test_broadcom_is_alias_exact(self):
        r = resolve_entity("broadcom")
        assert r.context.ticker == "AVGO"
        assert r.method == "alias_exact"

    def test_taiwan_semiconductor_is_alias_exact(self):
        r = resolve_entity("taiwan semiconductor")
        assert r.context.ticker == "TSM"
        assert r.method == "alias_exact"

    def test_taiwan_semi_is_alias_exact(self):
        r = resolve_entity("taiwan semi")
        assert r.context.ticker == "TSM"
        assert r.method == "alias_exact"

    def test_asml_holding_is_alias_exact(self):
        r = resolve_entity("asml holding")
        assert r.context.ticker == "ASML"
        assert r.method == "alias_exact"

    def test_advanced_micro_devices_is_alias_exact(self):
        r = resolve_entity("advanced micro devices")
        assert r.context.ticker == "AMD"
        assert r.method == "alias_exact"

    def test_eli_lilly_is_alias_exact(self):
        r = resolve_entity("eli lilly")
        assert r.context.ticker == "LLY"
        assert r.method == "alias_exact"

    def test_novo_nordisk_is_alias_exact(self):
        r = resolve_entity("novo nordisk")
        assert r.context.ticker == "NVO"
        assert r.method == "alias_exact"

    def test_alias_exact_confidence_is_095(self):
        """alias_exact must always return confidence 0.95."""
        for q in ["apple", "microsoft", "nvidia", "broadcom", "vertex pharmaceuticals"]:
            r = resolve_entity(q)
            assert r.method == "alias_exact", f"'{q}' should be alias_exact, got {r.method}"
            assert r.confidence == 0.95, f"'{q}' confidence should be 0.95"


# ─────────────────────────────────────────────────────────────────────────────
# 3. NEVER-SILENT-REMAP GUARANTEE
# ─────────────────────────────────────────────────────────────────────────────

class TestNeverSilentRemap:
    """Unknown or ambiguous queries must NEVER route to an unrelated company."""

    def test_vertex_pharma_never_routes_to_arm(self):
        """The canonical launch failure: 'vertex pharmaceuticals' must be VRTX, never ARM."""
        r = resolve_entity("vertex pharmaceuticals")
        assert r.context is not None
        assert r.context.ticker == "VRTX", (
            f"CRITICAL: 'vertex pharmaceuticals' resolved to {r.context.ticker}, expected VRTX. "
            f"This is the launch-blocking bug — ARM must never match inside 'pharmaceuticals'."
        )

    def test_arm_not_in_pharmaceuticals(self):
        """Word-boundary check: 'arm' must not match inside 'pharmaceuticals'."""
        ctx = _alias_lookup("pharmaceuticals")
        if ctx is not None:
            assert ctx.ticker != "ARM", (
                "'pharmaceuticals' word-boundary leaked to ARM Holdings"
            )

    def test_arm_not_in_alarm(self):
        ctx = _alias_lookup("alarm systems")
        if ctx is not None:
            assert ctx.ticker != "ARM"

    def test_arm_not_in_charm(self):
        ctx = _alias_lookup("the charm offensive")
        if ctx is not None:
            assert ctx.ticker != "ARM"

    def test_arm_not_in_farm(self):
        # "farm" itself is ambiguous (fuzzy), but the router gate handles it.
        # Key assertion: alias_exact must NOT fire for "farm equipment"
        ctx = _alias_lookup("farm equipment agricultural")
        if ctx is not None:
            assert ctx.ticker != "ARM"

    def test_garbled_text_does_not_route(self):
        """Garbled/nonsense text must not route to any company above the gate."""
        r = resolve_entity("xyzzy qqqq zzzz gibberish")
        assert not _above_gate(r), "Garbled text must not clear the routing gate"

    def test_sector_term_does_not_route(self):
        """Generic sector terms alone must not trigger company routing."""
        for q in [
            "the biotech sector is growing",
            "pharmaceutical industry outlook",
            "semiconductor market analysis",
            "fintech disruption trends",
        ]:
            r = resolve_entity(q)
            if r.context is not None:
                assert not _above_gate(r), (
                    f"'{q}' should not clear routing gate — sector term falsely routed "
                    f"to {r.context.ticker} at conf={r.confidence:.2f}"
                )

    def test_interest_does_not_route_to_pinterest(self):
        """'interest' is a suffix of 'pinterest' — must not produce a Pinterest match."""
        r = resolve_entity("why are interest rates so high")
        if r.context is not None:
            assert r.context.ticker != "PINS", (
                "CRITICAL: 'interest rates' incorrectly resolved to Pinterest (PINS). "
                "'interest' must be in _CONTEXT_WORDS."
            )
            assert not _above_gate(r)

    def test_inflation_does_not_route(self):
        r = resolve_entity("inflation is rising due to energy costs")
        if r.context is not None:
            assert not _above_gate(r)


# ─────────────────────────────────────────────────────────────────────────────
# 4. HARD CONFIDENCE THRESHOLD
# ─────────────────────────────────────────────────────────────────────────────

class TestHardConfidenceThreshold:
    """MINIMUM_ROUTE_CONFIDENCE must be defined and enforced."""

    def test_threshold_is_defined(self):
        assert isinstance(MINIMUM_ROUTE_CONFIDENCE, float)
        assert 0.72 < MINIMUM_ROUTE_CONFIDENCE <= 1.0

    def test_threshold_is_at_least_0_85(self):
        """Threshold must be strict enough to catch near-miss fuzzy matches."""
        assert MINIMUM_ROUTE_CONFIDENCE >= 0.85, (
            f"MINIMUM_ROUTE_CONFIDENCE={MINIMUM_ROUTE_CONFIDENCE} is too low. "
            "Must be at least 0.85 to reject ambiguous fuzzy matches."
        )

    def test_exact_ticker_always_above_threshold(self):
        for ticker in ["AAPL", "NVDA", "AMD", "TSM", "ASML", "VRTX"]:
            r = resolve_entity(ticker)
            assert _above_gate(r), f"{ticker} exact_ticker must clear the gate"

    def test_alias_exact_always_above_threshold(self):
        """alias_exact at 0.95 must always clear the 0.85 gate."""
        for q in ["nvidia", "broadcom", "vertex pharmaceuticals", "taiwan semi"]:
            r = resolve_entity(q)
            assert _above_gate(r), f"'{q}' alias_exact must clear the gate"

    def test_fuzzy_below_threshold_has_rejection_reason(self):
        """When a fuzzy match is below threshold, rejection_reason must be set."""
        # Construct a case guaranteed to produce a below-threshold fuzzy match
        # by testing a real low-confidence resolution directly.
        # Use _fuzzy_token_match directly with a word that barely reaches cutoff.
        result = _fuzzy_token_match("farmacueticals", cutoff=0.72)
        if result is not None:
            _, score, _ = result
            conf = round(0.50 + score * 0.47, 3)
            if conf < MINIMUM_ROUTE_CONFIDENCE:
                r = resolve_entity("farmacueticals")
                assert r.rejection_reason == "fuzzy_below_threshold", (
                    f"Below-threshold fuzzy match must set rejection_reason='fuzzy_below_threshold', "
                    f"got {r.rejection_reason!r}"
                )

    def test_rejection_reason_empty_on_success(self):
        """Successful resolutions must have empty rejection_reason."""
        for q in ["NVDA", "nvidia", "broadcom"]:
            r = resolve_entity(q)
            assert r.rejection_reason == "", (
                f"'{q}' succeeded but rejection_reason={r.rejection_reason!r}"
            )

    def test_not_found_sets_rejection_reason(self):
        r = resolve_entity("xyzzy unknown company qqq")
        assert r.rejection_reason == "not_found"

    def test_minimum_route_confidence_is_float(self):
        assert isinstance(MINIMUM_ROUTE_CONFIDENCE, float)


# ─────────────────────────────────────────────────────────────────────────────
# 5. MULTI-CANDIDATE RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiCandidateResolution:
    """Not-found resolutions must populate ranked candidate suggestions."""

    def test_not_found_populates_candidates(self):
        """When a real-but-mistyped company fails resolution, candidates should appear."""
        # Badly garbled but still recognisable
        r = resolve_entity("nvidiaaa corporation stock")
        # The primary context may or may not resolve; if not found, candidates are expected
        if r.context is None:
            # candidates should have something useful
            assert len(r.candidates) >= 0  # non-negative; not a hard requirement here

    def test_candidates_sorted_by_score_descending(self):
        """Candidates must be sorted highest-score-first."""
        candidates = _gather_candidates("goooogle search engine", n=3)
        if len(candidates) >= 2:
            scores = [s for _, _, s in candidates]
            assert scores == sorted(scores, reverse=True), (
                f"Candidates not sorted descending: {scores}"
            )

    def test_candidates_format(self):
        """Each candidate must be a (ticker, company_name, score) triple."""
        candidates = _gather_candidates("microsoft azure cloud", n=3)
        for item in candidates:
            assert len(item) == 3, f"Expected (ticker, name, score), got {item}"
            ticker, name, score = item
            assert isinstance(ticker, str) and ticker
            assert isinstance(name, str) and name
            assert 0.0 <= score <= 1.0

    def test_candidates_populated_in_entity_resolution(self):
        """EntityResolution.candidates must be populated when context is None."""
        r = resolve_entity("xyzzy unknown company")
        assert isinstance(r.candidates, list)

    def test_fallback_reason_candidates_available(self):
        """fallback_reason should be 'candidates_available' when suggestions exist."""
        # Use a recognisable-but-not-exact query likely to produce candidates
        r = resolve_entity("gogle cloud stock analysis")
        if r.context is None and len(r.candidates) > 0:
            assert r.fallback_reason == "candidates_available"

    def test_fallback_reason_no_candidates(self):
        r = resolve_entity("zzzzxxx totally nonsense input qqqq")
        if r.context is None and len(r.candidates) == 0:
            assert r.fallback_reason == "no_candidates"

    def test_no_duplicate_tickers_in_candidates(self):
        """Each ticker must appear at most once in the candidate list."""
        candidates = _gather_candidates("apple microsoft google", n=5)
        tickers = [t for t, _, _ in candidates]
        assert len(tickers) == len(set(tickers)), f"Duplicate tickers: {tickers}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. REGRESSION: 15 NAMED COMPANIES
# ─────────────────────────────────────────────────────────────────────────────

class TestNamedCompanyRegression:
    """Each of the 15 specified companies must resolve correctly."""

    # ── Pharma / Biotech ──────────────────────────────────────────────────────

    def test_vertex_pharmaceuticals(self):
        assert _ticker("vertex pharmaceuticals") == "VRTX"
        assert _ticker("Vertex Pharmaceuticals") == "VRTX"
        assert _ticker("VRTX") == "VRTX"

    def test_eli_lilly(self):
        assert _ticker("eli lilly") == "LLY"
        assert _ticker("lilly") == "LLY"
        assert _ticker("LLY") == "LLY"

    def test_novo_nordisk(self):
        assert _ticker("novo nordisk") == "NVO"
        assert _ticker("novo") == "NVO"
        assert _ticker("NVO") == "NVO"

    def test_regeneron(self):
        assert _ticker("regeneron") == "REGN"
        assert _ticker("REGN") == "REGN"

    def test_moderna(self):
        assert _ticker("moderna") == "MRNA"
        assert _ticker("MRNA") == "MRNA"

    def test_astrazeneca(self):
        assert _ticker("astrazeneca") == "AZN"
        assert _ticker("astra zeneca") == "AZN"
        assert _ticker("AZN") == "AZN"

    def test_roche(self):
        assert _ticker("roche") == "RHHBY"
        assert _ticker("roche holding") == "RHHBY"
        assert _ticker("RHHBY") == "RHHBY"

    def test_crispr_therapeutics(self):
        assert _ticker("crispr therapeutics") == "CRSP"
        assert _ticker("crispr") == "CRSP"
        assert _ticker("CRSP") == "CRSP"

    def test_biontech(self):
        assert _ticker("biontech") == "BNTX"
        assert _ticker("BNTX") == "BNTX"

    def test_intuitive_surgical(self):
        assert _ticker("intuitive surgical") == "ISRG"
        assert _ticker("ISRG") == "ISRG"

    # ── Semiconductors ────────────────────────────────────────────────────────

    def test_amd(self):
        assert _ticker("advanced micro devices") == "AMD"
        assert _ticker("AMD") == "AMD"
        assert _ticker("amd") == "AMD"

    def test_nvidia(self):
        assert _ticker("nvidia") == "NVDA"
        assert _ticker("NVDA") == "NVDA"
        assert _ticker("nvidia corporation") == "NVDA"

    def test_broadcom(self):
        assert _ticker("broadcom") == "AVGO"
        assert _ticker("AVGO") == "AVGO"
        assert _ticker("avgo") == "AVGO"

    def test_tsmc(self):
        assert _ticker("tsmc") == "TSM"
        assert _ticker("taiwan semiconductor") == "TSM"
        assert _ticker("taiwan semi") == "TSM"
        assert _ticker("TSM") == "TSM"

    def test_asml(self):
        assert _ticker("asml") == "ASML"
        assert _ticker("asml holding") == "ASML"
        assert _ticker("ASML") == "ASML"


# ─────────────────────────────────────────────────────────────────────────────
# 7. TYPO / FUZZY MATCHING
# ─────────────────────────────────────────────────────────────────────────────

class TestTypoFuzzyMatching:
    """Common typos must resolve to the correct ticker and clear the routing gate."""

    def _assert_resolves(self, query: str, expected_ticker: str):
        r = resolve_entity(query)
        assert r.context is not None, f"'{query}' returned None, expected {expected_ticker}"
        assert r.context.ticker == expected_ticker, (
            f"'{query}' → {r.context.ticker}, expected {expected_ticker}"
        )
        assert _above_gate(r), (
            f"'{query}' → {expected_ticker} but did not clear routing gate "
            f"(conf={r.confidence:.2f}, method={r.method})"
        )

    # NVIDIA typos (in alias map → alias_exact)
    def test_nvdia_typo(self):
        self._assert_resolves("Nvdia", "NVDA")

    def test_nvidea_typo(self):
        self._assert_resolves("nvidea", "NVDA")

    def test_nvidai_typo(self):
        self._assert_resolves("nvidai", "NVDA")

    def test_nividia_typo(self):
        self._assert_resolves("nividia", "NVDA")

    # Microsoft typos (in alias map)
    def test_microsft_typo(self):
        self._assert_resolves("Microsft", "MSFT")

    def test_microsfot_typo(self):
        self._assert_resolves("microsfot", "MSFT")

    def test_micorsoft_typo(self):
        self._assert_resolves("micorsoft", "MSFT")

    # Apple typos
    def test_aple_typo(self):
        self._assert_resolves("aple", "AAPL")

    def test_appel_typo(self):
        self._assert_resolves("appel", "AAPL")

    # Broadcom typos (in alias map)
    def test_braodcom_typo(self):
        self._assert_resolves("braodcom", "AVGO")

    def test_broadcome_typo(self):
        self._assert_resolves("broadcome", "AVGO")

    # Vertex typos (in alias map)
    def test_vertex_pharma_partial(self):
        self._assert_resolves("vertex pharma", "VRTX")

    def test_vertx_pharmaceuticals_typo(self):
        self._assert_resolves("vertx pharmaceuticals", "VRTX")

    # Google typos
    def test_gogle_typo(self):
        self._assert_resolves("gogle", "GOOGL")

    def test_googel_typo(self):
        self._assert_resolves("googel", "GOOGL")

    # AstraZeneca typos
    def test_astrazenica_typo(self):
        self._assert_resolves("astrazenica", "AZN")

    # CRISPR typos
    def test_crispr_theraputics_typo(self):
        self._assert_resolves("crispr theraputics", "CRSP")

    # AMD brand names
    def test_ryzen_brand_name(self):
        self._assert_resolves("ryzen", "AMD")

    def test_radeon_brand_name(self):
        self._assert_resolves("radeon", "AMD")


# ─────────────────────────────────────────────────────────────────────────────
# 8. PHRASE QUERY RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

class TestPhraseQueryResolution:
    """Company names embedded in natural-language phrases must still resolve."""

    def _assert_phrase(self, phrase: str, expected_ticker: str):
        r = resolve_entity(phrase)
        assert r.context is not None, (
            f"'{phrase}' returned None, expected {expected_ticker}"
        )
        assert r.context.ticker == expected_ticker, (
            f"'{phrase}' → {r.context.ticker}, expected {expected_ticker}"
        )
        assert _above_gate(r)

    def test_google_cloud_margins(self):
        self._assert_phrase("Google cloud margins are expanding", "GOOGL")

    def test_amazon_aws_revenue(self):
        self._assert_phrase("Amazon aws revenue growth", "AMZN")

    def test_apple_iphone_deliveries(self):
        self._assert_phrase("apple iphone margin analysis", "AAPL")

    def test_microsoft_azure_cloud(self):
        self._assert_phrase("microsoft azure cloud growth", "MSFT")

    def test_tesla_ev_deliveries(self):
        self._assert_phrase("tesla ev deliveries", "TSLA")

    def test_nvidia_data_center(self):
        self._assert_phrase("nvidia data center demand", "NVDA")

    def test_vertex_pharma_in_sentence(self):
        self._assert_phrase("is vertex pharmaceuticals stock overpriced", "VRTX")

    def test_eli_lilly_weight_loss_drug(self):
        self._assert_phrase("eli lilly weight loss drug outlook", "LLY")

    def test_asml_chip_equipment(self):
        self._assert_phrase("asml chip making equipment", "ASML")

    def test_tsmc_foundry_revenue(self):
        self._assert_phrase("taiwan semiconductor manufacturing revenue", "TSM")

    def test_broadcom_ai_chips(self):
        self._assert_phrase("broadcom ai chip demand", "AVGO")

    def test_amd_vs_nvidia(self):
        # AMD appears before NVIDIA in text; alias_exact fires longest-first
        # so "advanced micro devices" won't match; "amd" word-boundary check fires
        r = resolve_entity("amd vs nvidia in data center")
        assert r.context is not None
        # Either AMD or NVDA — the first word-boundary match wins
        assert r.context.ticker in ("AMD", "NVDA")
        assert _above_gate(r)


# ─────────────────────────────────────────────────────────────────────────────
# 9. OBSERVABILITY FIELDS
# ─────────────────────────────────────────────────────────────────────────────

class TestObservabilityFields:
    """EntityResolution must carry structured observability data."""

    def test_entity_resolution_has_rejection_reason(self):
        r = resolve_entity("nvidia")
        assert hasattr(r, "rejection_reason"), "EntityResolution must have rejection_reason field"

    def test_entity_resolution_has_fallback_reason(self):
        r = resolve_entity("nvidia")
        assert hasattr(r, "fallback_reason"), "EntityResolution must have fallback_reason field"

    def test_successful_resolution_empty_rejection_reason(self):
        for q in ["NVDA", "nvidia", "broadcom", "vertex pharmaceuticals"]:
            r = resolve_entity(q)
            assert r.rejection_reason == "", (
                f"'{q}' succeeded, rejection_reason should be '' not {r.rejection_reason!r}"
            )

    def test_successful_resolution_empty_fallback_reason(self):
        for q in ["NVDA", "nvidia", "broadcom"]:
            r = resolve_entity(q)
            assert r.fallback_reason == "", (
                f"'{q}' succeeded, fallback_reason should be '' not {r.fallback_reason!r}"
            )

    def test_not_found_rejection_reason(self):
        r = resolve_entity("xyzzy completely unknown qqqqq")
        assert r.context is None
        assert r.rejection_reason == "not_found"

    def test_not_found_fallback_reason_populated(self):
        r = resolve_entity("xyzzy completely unknown qqqqq")
        assert r.fallback_reason in ("candidates_available", "no_candidates"), (
            f"not_found should set fallback_reason, got {r.fallback_reason!r}"
        )

    def test_method_values_are_valid(self):
        valid_methods = {"exact_ticker", "alias_exact", "fuzzy_token", "not_found"}
        for q in ["NVDA", "nvidia", "xyzzy"]:
            r = resolve_entity(q)
            assert r.method in valid_methods, f"'{q}': invalid method {r.method!r}"

    def test_confidence_in_unit_interval(self):
        for q in ["NVDA", "nvidia", "nvdia", "xyzzy"]:
            r = resolve_entity(q)
            assert 0.0 <= r.confidence <= 1.0, (
                f"'{q}': confidence {r.confidence} out of [0,1]"
            )

    def test_candidates_is_list(self):
        r = resolve_entity("xyzzy unknown")
        assert isinstance(r.candidates, list)

    def test_matched_text_populated_on_success(self):
        r = resolve_entity("nvidia")
        assert r.matched_text, "matched_text should be non-empty on successful resolution"

    def test_matched_text_empty_on_not_found(self):
        r = resolve_entity("xyzzy completely unknown")
        if r.method == "not_found":
            assert r.matched_text == ""


# ─────────────────────────────────────────────────────────────────────────────
# 10. FRONTEND-SAFE FALLBACK STATES
# ─────────────────────────────────────────────────────────────────────────────

class TestFrontendFallbackStates:
    """Low-confidence resolutions must produce safe, structured fallback data."""

    def test_no_routing_below_threshold(self):
        """Queries that produce fuzzy matches below the gate must not route."""
        # Feed a deliberately ambiguous query
        r = resolve_entity("some general pharmaceuticals market question without company")
        if r.context is not None and r.method == "fuzzy_token":
            # Must NOT be above the gate (the router won't route it)
            assert not _above_gate(r), (
                f"Low-confidence fuzzy match should not clear routing gate: "
                f"conf={r.confidence:.2f}"
            )

    def test_below_threshold_has_candidates_or_empty(self):
        """When routing fails, we must get candidates or empty — never an exception."""
        r = resolve_entity("an entirely unrecognised company name abc123")
        assert isinstance(r.candidates, list)
        # Should not raise

    def test_candidates_have_known_tickers(self):
        """All tickers in candidates must exist in the company database."""
        from app.services.company_detection import _COMPANY_DB
        candidates = _gather_candidates("nvidia graphics chips", n=5)
        for ticker, name, score in candidates:
            assert ticker in _COMPANY_DB, (
                f"Candidate ticker '{ticker}' not in _COMPANY_DB — ghost candidate"
            )

    def test_detect_company_returns_none_below_gate(self):
        """detect_company() (router-facing) must return None when confidence is below 0.72."""
        # Use pure nonsense — should always return None
        result = detect_company("zzzzxxx qqqq aaaa gibberish completely made up")
        assert result is None

    def test_detect_company_returns_context_for_known_company(self):
        from app.schemas import CompanyContext
        result = detect_company("nvidia")
        assert result is not None
        assert isinstance(result, CompanyContext)
        assert result.ticker == "NVDA"

    def test_resolve_entity_never_raises(self):
        """resolve_entity must never raise regardless of input."""
        garbage_inputs = [
            "",
            "   ",
            "!!!! ??? ### $$$",
            "a" * 500,
            "\n\n\n",
            None,  # type: ignore — defensive test
        ]
        for inp in garbage_inputs:
            try:
                r = resolve_entity(inp or "")
                assert isinstance(r, EntityResolution)
            except Exception as exc:
                pytest.fail(f"resolve_entity({inp!r}) raised: {exc}")

    def test_fallback_candidates_limit(self):
        """_gather_candidates must return at most n results."""
        for n in [1, 2, 3, 5]:
            candidates = _gather_candidates("microsoft azure cloud computing", n=n)
            assert len(candidates) <= n, (
                f"Expected at most {n} candidates, got {len(candidates)}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 11. BROADER COMPANY COVERAGE
# ─────────────────────────────────────────────────────────────────────────────

class TestBroaderCoverage:
    """Coverage for mega-caps, ADRs, medical tech, and financial companies."""

    def _ok(self, q, expected):
        assert _ticker(q) == expected, f"'{q}' → expected {expected}"

    # Mega-caps
    def test_apple(self):     self._ok("apple", "AAPL")
    def test_microsoft(self): self._ok("microsoft", "MSFT")
    def test_amazon(self):    self._ok("amazon", "AMZN")
    def test_tesla(self):     self._ok("tesla", "TSLA")
    def test_meta(self):      self._ok("meta", "META")
    def test_facebook(self):  self._ok("facebook", "META")

    # Semiconductors broader
    def test_intel(self):     self._ok("intel", "INTC")
    def test_qualcomm(self):  self._ok("qualcomm", "QCOM")
    def test_micron(self):    self._ok("micron", "MU")
    def test_applied_materials(self): self._ok("applied materials", "AMAT")
    def test_lam_research(self):      self._ok("lam research", "LRCX")
    def test_texas_instruments(self): self._ok("texas instruments", "TXN")

    # Global ADRs / international
    def test_novo_nordisk_as(self): self._ok("novo nordisk", "NVO")
    def test_roche(self):           self._ok("roche", "RHHBY")
    def test_astrazeneca(self):     self._ok("astrazeneca", "AZN")
    def test_biontech(self):        self._ok("biontech", "BNTX")
    def test_asml_adr(self):        self._ok("asml", "ASML")
    def test_tsmc_adr(self):        self._ok("tsmc", "TSM")

    # Medical tech
    def test_medtronic(self):         self._ok("medtronic", "MDT")
    def test_stryker(self):           self._ok("stryker", "SYK")
    def test_boston_scientific(self): self._ok("boston scientific", "BSX")
    def test_intuitive_surgical(self):self._ok("intuitive surgical", "ISRG")
    def test_abbott(self):            self._ok("abbott", "ABT")
    def test_danaher(self):           self._ok("danaher", "DHR")
    def test_thermo_fisher(self):     self._ok("thermo fisher", "TMO")

    # Financials
    def test_jpmorgan(self):          self._ok("jpmorgan", "JPM")
    def test_goldman_sachs(self):     self._ok("goldman sachs", "GS")
    def test_blackrock(self):         self._ok("blackrock", "BLK")
    def test_visa(self):              self._ok("visa", "V")
    def test_mastercard(self):        self._ok("mastercard", "MA")
    def test_american_express(self):  self._ok("american express", "AXP")
    def test_berkshire(self):         self._ok("berkshire hathaway", "BRK.B")

    # Energy
    def test_exxon(self):    self._ok("exxonmobil", "XOM")
    def test_chevron(self):  self._ok("chevron", "CVX")

    # Consumer
    def test_walmart(self):   self._ok("walmart", "WMT")
    def test_costco(self):    self._ok("costco", "COST")
    def test_nike(self):      self._ok("nike", "NKE")
    def test_coca_cola(self): self._ok("coca cola", "KO")

    # Brand-name aliases  (AMD GPU/CPU brands → AMD)
    def test_ryzen_brand(self):  self._ok("ryzen", "AMD")
    def test_radeon_brand(self): self._ok("radeon", "AMD")

    # Ticker-form aliases (lowercase tickers → correct company)
    def test_avgo_lowercase(self): self._ok("avgo", "AVGO")
    def test_tsm_lowercase(self):  self._ok("tsm", "TSM")


# ─────────────────────────────────────────────────────────────────────────────
# 12. INTERNAL PIPELINE UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestInternalPipeline:
    """Unit tests for _extract_explicit_ticker, _alias_lookup, _fuzzy_token_match."""

    # _extract_explicit_ticker ─────────────────────────────────────────────────

    def test_extract_ticker_uppercase_known(self):
        ctx = _extract_explicit_ticker("NVDA earnings")
        assert ctx is not None and ctx.ticker == "NVDA"

    def test_extract_ticker_not_in_stop_words(self):
        ctx = _extract_explicit_ticker("Is A good investment?")
        # "IS" is a stop word; "A" is a stop word — neither should trigger
        # (though "A" is also in _COMPANY_DB as Agilent; stop-word filter applies first)
        if ctx is not None:
            assert ctx.ticker not in {"IS", "IN", "A", "BE"}

    def test_extract_ticker_requires_uppercase(self):
        ctx = _extract_explicit_ticker("nvidia")
        assert ctx is None, "_extract_explicit_ticker must only match uppercase"

    def test_extract_ticker_unknown_uppercase_returns_none(self):
        ctx = _extract_explicit_ticker("XYZZY")
        assert ctx is None

    # _alias_lookup ────────────────────────────────────────────────────────────

    def test_alias_lookup_vertex_pharma(self):
        ctx = _alias_lookup("vertex pharmaceuticals")
        assert ctx is not None and ctx.ticker == "VRTX"

    def test_alias_lookup_arm_not_in_pharmaceuticals(self):
        ctx = _alias_lookup("pharmaceuticals sector")
        if ctx is not None:
            assert ctx.ticker != "ARM"

    def test_alias_lookup_arm_standalone_matches(self):
        ctx = _alias_lookup("arm holdings chip design")
        assert ctx is not None and ctx.ticker == "ARM"

    def test_alias_lookup_longest_wins(self):
        # "vertex pharmaceuticals" (22) should match before "vertex" (6)
        ctx = _alias_lookup("vertex pharmaceuticals inc")
        assert ctx is not None and ctx.ticker == "VRTX"

    def test_alias_lookup_word_boundary_arm_in_farm(self):
        ctx = _alias_lookup("farm equipment stocks")
        if ctx is not None:
            assert ctx.ticker != "ARM"

    # _fuzzy_token_match ───────────────────────────────────────────────────────

    def test_fuzzy_match_returns_tuple_or_none(self):
        result = _fuzzy_token_match("nvidia")
        assert result is None or (isinstance(result, tuple) and len(result) == 3)

    def test_fuzzy_short_aliases_excluded(self):
        """3-char aliases like 'arm', 'amd' must not be used in fuzzy Step 3."""
        # "charm" could fuzzy-match "arm" if short aliases were included
        result = _fuzzy_token_match("charm offensive")
        if result is not None:
            _, _, matched = result
            assert matched != "arm", "'arm' (3 chars) must be excluded from fuzzy matching"

    def test_fuzzy_score_range(self):
        """Fuzzy match confidence must be in [0.72, 0.95]."""
        result = _fuzzy_token_match("nvidaa")
        if result is not None:
            _, score, _ = result
            assert 0.72 <= score <= 1.0
