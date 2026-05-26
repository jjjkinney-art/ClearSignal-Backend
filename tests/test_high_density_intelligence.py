"""
High-Density Intelligence Tests
=================================

Part 6 of the High-Density Intelligence phase.

Tests:
  1. Stance mapping — expanded vocabulary fires correctly (Aggressive Buy, Accumulate, Tactical)
  2. Evidence category richness — _build_analysis_foundation returns extended categories
  3. Historical context detection — QoQ, YoY, revision, tone shift keywords detected
  4. Thesis evolution schema — thesis_evolution field present and correct type
  5. Section contract markers — signal diversity requirements present in synthesis source
  6. Cross-signal interaction — bear_thesis prompt requirements present
  7. Stance schema — directional_stance description includes new stances
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_dims(
    *,
    final_score: float,
    frag: float = 0.30,
    asym: float = 0.25,
    ta:   float = 0.70,
    vc:   float = 0.55,
):
    """Build a minimal ConvictionDimensions-like object for stance tests."""
    from app.services.conviction_modeler import ConvictionDimensions
    return ConvictionDimensions(
        evidence_quality     = 0.75,
        evidence_freshness   = 0.70,
        thesis_alignment     = ta,
        macro_uncertainty    = 0.40,
        valuation_certainty  = vc,
        estimate_dispersion  = 0.60,
        governance_risk      = 0.05,
        expectation_fragility = frag,
        expectation_asymmetry = asym,
    )


def _run_stance(final_score, frag=0.30, asym=0.25, ta=0.70, vc=0.55):
    from app.services.conviction_modeler import _compute_directional_stance
    from app.schemas import CompanyContext
    dims = _make_dims(final_score=final_score, frag=frag, asym=asym, ta=ta, vc=vc)
    company = CompanyContext(ticker="TEST", company_name="Test Corp")
    return _compute_directional_stance(final_score, dims, "actionable thesis", company)


def _make_evidence_with_text(text: str, title: str = ""):
    from app.schemas import RetrievedEvidence
    return RetrievedEvidence(
        title=title or text[:60],
        source="Test Source",
        summary=text,
        timestamp="2026-05-10",
        relevance_score=0.85,
    )


def _run_af(evidence_list, dims=None):
    from app.services.conviction_modeler import _build_analysis_foundation
    from app.schemas import CompanyContext
    if dims is None:
        class _FakeDims:
            evidence_quality  = 0.65
            evidence_freshness = 0.60
        dims = _FakeDims()
    company = CompanyContext(ticker="TEST", company_name="Test Corp")
    return _build_analysis_foundation(evidence_list, dims, company)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Stance mapping — expanded vocabulary
# ─────────────────────────────────────────────────────────────────────────────

class TestStanceMapping:
    """_compute_directional_stance must return the expanded stance vocabulary."""

    _ALL_STANCES = {
        "Aggressive Buy", "Buy", "Accumulate", "Hold", "Tactical", "Avoid", "Sell"
    }

    def test_aggressive_buy_fires_at_very_high_conviction(self):
        """Very high score + very low fragility + high alignment → Aggressive Buy."""
        stance, reasoning = _run_stance(final_score=0.82, frag=0.28, ta=0.75)
        assert stance == "Aggressive Buy", (
            f"Expected 'Aggressive Buy' at final_score=0.82, frag=0.28, ta=0.75; got {stance!r}.\n"
            f"Check _compute_directional_stance() threshold: final_score >= 0.78, frag < 0.35, ta > 0.68."
        )

    def test_aggressive_buy_reasoning_is_non_generic(self):
        """Aggressive Buy reasoning must reference expectation understatement."""
        _, reasoning = _run_stance(final_score=0.82, frag=0.28, ta=0.75)
        assert "expectation" in reasoning.lower() or "consensus" in reasoning.lower() or "upside" in reasoning.lower(), (
            f"Aggressive Buy reasoning does not reference expectations/upside: {reasoning!r}"
        )

    def test_accumulate_fires_for_quality_at_full_valuation(self):
        """Moderate score + mid-range fragility (0.40-0.62) → Accumulate."""
        stance, _ = _run_stance(final_score=0.62, frag=0.50, ta=0.65)
        assert stance == "Accumulate", (
            f"Expected 'Accumulate' at final_score=0.62, frag=0.50; got {stance!r}.\n"
            f"Accumulate fires for durable quality at full valuation — frag 0.40-0.62."
        )

    def test_accumulate_reasoning_mentions_dips_or_entry(self):
        """Accumulate reasoning must mention entry/weakness/dips framing."""
        _, reasoning = _run_stance(final_score=0.62, frag=0.50, ta=0.65)
        assert any(kw in reasoning.lower() for kw in ("dip", "weakness", "entry", "add on")), (
            f"Accumulate reasoning must reference entry framing. Got: {reasoning!r}"
        )

    def test_tactical_fires_for_high_fragility_asymmetry_play(self):
        """Moderate score + high fragility + low asymmetry → Tactical."""
        stance, _ = _run_stance(final_score=0.54, frag=0.60, asym=0.40)
        assert stance == "Tactical", (
            f"Expected 'Tactical' at final_score=0.54, frag=0.60, asym=0.40; got {stance!r}.\n"
            f"Tactical = near-term asymmetry without full structural conviction."
        )

    def test_tactical_not_fired_when_asym_high(self):
        """When asymmetry is high (binary setup), should NOT produce Tactical."""
        stance, _ = _run_stance(final_score=0.54, frag=0.60, asym=0.65)
        # High asymmetry means execution binary — should land in Hold or Avoid, not Tactical
        assert stance != "Tactical", (
            f"Tactical should not fire when asym={0.65} (binary execution risk)."
        )

    def test_buy_fires_at_solid_conviction_low_fragility(self):
        """Solid conviction (0.68+), low fragility, high alignment → Buy."""
        stance, _ = _run_stance(final_score=0.70, frag=0.35, ta=0.68)
        assert stance == "Buy", (
            f"Expected 'Buy' at final_score=0.70, frag=0.35, ta=0.68; got {stance!r}."
        )

    def test_hold_fires_at_elevated_fragility(self):
        """Moderate score below Tactical threshold but elevated fragility → Hold."""
        # score=0.47 is below the Tactical floor (0.52), so Tactical cannot fire.
        # With frag=0.65 >= 0.58, the Hold (demanding) branch fires instead.
        stance, _ = _run_stance(final_score=0.47, frag=0.65)
        assert stance == "Hold", (
            f"Expected 'Hold' at score=0.47, frag=0.65; got {stance!r}."
        )

    def test_avoid_fires_at_low_score(self):
        """Low conviction score → Avoid."""
        stance, _ = _run_stance(final_score=0.32, frag=0.40)
        assert stance == "Avoid", (
            f"Expected 'Avoid' at final_score=0.32; got {stance!r}."
        )

    def test_sell_fires_at_very_low_score(self):
        """Very low conviction → Sell."""
        stance, _ = _run_stance(final_score=0.18, frag=0.75)
        assert stance == "Sell", (
            f"Expected 'Sell' at final_score=0.18; got {stance!r}."
        )

    def test_all_stance_outputs_are_valid_vocabulary(self):
        """Every possible stance output must be in the known vocabulary."""
        test_cases = [
            (0.85, 0.25, 0.20, 0.75),  # Aggressive Buy territory
            (0.72, 0.32, 0.22, 0.68),  # Buy territory
            (0.63, 0.50, 0.30, 0.62),  # Accumulate territory
            (0.68, 0.36, 0.22, 0.66),  # Buy (broad)
            (0.55, 0.58, 0.40, 0.55),  # Tactical
            (0.52, 0.65, 0.45, 0.50),  # Hold demanding
            (0.54, 0.35, 0.30, 0.55),  # Hold balanced
            (0.35, 0.40, 0.35, 0.40),  # Avoid
            (0.15, 0.80, 0.60, 0.30),  # Sell
        ]
        for final_score, frag, asym, ta in test_cases:
            stance, reasoning = _run_stance(final_score, frag=frag, asym=asym, ta=ta)
            assert stance in self._ALL_STANCES, (
                f"_compute_directional_stance returned unknown stance {stance!r} "
                f"(final_score={final_score}, frag={frag}, asym={asym}, ta={ta}). "
                f"Valid stances: {sorted(self._ALL_STANCES)}"
            )
            assert isinstance(reasoning, str) and len(reasoning) > 20, (
                f"Stance reasoning is empty or too short for stance={stance!r}."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Evidence category richness
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceCategoryRichness:
    """_build_analysis_foundation must detect extended Part 1 categories."""

    def test_balance_sheet_detection(self):
        """Balance sheet keywords → 'balance sheet and capital structure'."""
        ev = [_make_evidence_with_text(
            "Net cash position of $30B with active buyback — FCF yield supports capital returns.",
            title="Balance Sheet Analysis net cash buyback FCF"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("balance sheet" in item.lower() or "capital" in item.lower() for item in ev_used), (
            f"Balance sheet evidence not detected. ev_used={ev_used!r}"
        )

    def test_demand_detection(self):
        """Demand/unit volume keywords → 'demand trend and volume indicators'."""
        ev = [_make_evidence_with_text(
            "iPhone unit volume declined 8% QoQ as channel inventory normalised.",
            title="iPhone unit volume shipment demand trend"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("demand" in item.lower() or "volume" in item.lower() for item in ev_used), (
            f"Demand evidence not detected. ev_used={ev_used!r}"
        )

    def test_regulatory_detection(self):
        """Regulatory/FDA keywords → 'regulatory and compliance context'."""
        ev = [_make_evidence_with_text(
            "DOJ antitrust investigation into app store fee structure expands.",
            title="regulatory DOJ antitrust investigation compliance"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("regulatory" in item.lower() or "compliance" in item.lower() for item in ev_used), (
            f"Regulatory evidence not detected. ev_used={ev_used!r}"
        )

    def test_sentiment_detection(self):
        """Analyst upgrade/downgrade keywords → 'analyst sentiment shift'."""
        ev = [_make_evidence_with_text(
            "Goldman Sachs upgrade from Neutral to Buy; consensus positioning shifts bullish.",
            title="upgrade downgrade analyst sentiment positioning"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("sentiment" in item.lower() or "analyst" in item.lower() for item in ev_used), (
            f"Sentiment evidence not detected. ev_used={ev_used!r}"
        )

    def test_execution_detection(self):
        """Earnings beat/miss keywords → 'execution vs expectations'."""
        ev = [_make_evidence_with_text(
            "Revenue beat consensus by 4%; EPS came in above estimate for the third consecutive quarter.",
            title="earnings beat consensus estimate above execution"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("execution" in item.lower() for item in ev_used), (
            f"Execution evidence not detected. ev_used={ev_used!r}"
        )

    def test_estimate_revision_detection(self):
        """Estimate revision keywords → 'estimate revision trend'."""
        ev = [_make_evidence_with_text(
            "Street raised FY26 EPS estimate by 7% following upward revision to revenue guidance.",
            title="estimate revision raised estimate upward revision"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("revision" in item.lower() for item in ev_used), (
            f"Estimate revision not detected. ev_used={ev_used!r}"
        )

    def test_qoq_detection(self):
        """QoQ/sequential keywords → 'sequential quarter comparison'."""
        ev = [_make_evidence_with_text(
            "Gross margin expanded 80bps quarter-over-quarter as fixed costs absorbed higher volume.",
            title="quarter-over-quarter QoQ sequential margin"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("sequential" in item.lower() or "quarter" in item.lower() for item in ev_used), (
            f"QoQ detection not found. ev_used={ev_used!r}"
        )

    def test_yoy_detection(self):
        """YoY keywords → 'year-over-year trajectory'."""
        ev = [_make_evidence_with_text(
            "Services revenue grew 14% year-over-year, accelerating from 11% in the prior year.",
            title="year-over-year YoY annual comparison trajectory"
        )]
        ev_used, _, _ = _run_af(ev)
        assert any("year-over-year" in item.lower() or "trajectory" in item.lower() for item in ev_used), (
            f"YoY detection not found. ev_used={ev_used!r}"
        )

    def test_rich_diverse_evidence_produces_many_categories(self):
        """A diverse evidence pool should produce ≥ 5 distinct domain strings."""
        evidence = [
            _make_evidence_with_text("Net cash $30B; buyback of $5B authorized.", "balance sheet buyback"),
            _make_evidence_with_text("Unit volumes fell 8% quarter-over-quarter.", "unit volume QoQ"),
            _make_evidence_with_text("Analyst upgrade; consensus estimate raised.", "upgrade revision consensus"),
            _make_evidence_with_text("EPS beat consensus by 6%.", "earnings beat estimate"),
            _make_evidence_with_text("Rate sensitivity for long-duration FCF.", "rate macro yield"),
        ]
        ev_used, _, _ = _run_af(evidence)
        assert len(ev_used) >= 5, (
            f"Rich diverse evidence produced only {len(ev_used)} categories: {ev_used!r}.\n"
            f"Expected ≥ 5 distinct domain strings for a 5-piece diverse evidence pool."
        )

    def test_no_raw_count_strings_in_ev_used(self):
        """ev_used must never contain raw count strings like '3 evidence items'."""
        import re
        evidence = [_make_evidence_with_text("Some basic market commentary.") for _ in range(5)]
        ev_used, _, _ = _run_af(evidence)
        for item in ev_used:
            assert not re.search(r"\d+\s+evidence\s+item", item, re.IGNORECASE), (
                f"Raw count pattern found in ev_used: {item!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Thesis evolution schema
# ─────────────────────────────────────────────────────────────────────────────

class TestThesisEvolutionSchema:
    """InvestmentThesis.thesis_evolution must be present, default empty, and a string."""

    def test_thesis_evolution_field_exists(self):
        """InvestmentThesis must have a thesis_evolution field."""
        from app.schemas import InvestmentThesis
        assert hasattr(InvestmentThesis, "model_fields") or hasattr(InvestmentThesis, "__fields__"), (
            "InvestmentThesis is not a Pydantic model."
        )
        # Access via model_fields (pydantic v2) or __fields__ (v1)
        try:
            fields = InvestmentThesis.model_fields
        except AttributeError:
            fields = InvestmentThesis.__fields__
        assert "thesis_evolution" in fields, (
            "InvestmentThesis.thesis_evolution field is missing. "
            "Add it to schemas.py: thesis_evolution: str = Field(default='', ...)"
        )

    def test_thesis_evolution_default_is_empty_string(self):
        """thesis_evolution must default to '' (not None)."""
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(ticker="TEST", company_name="Test Corp")
        assert t.thesis_evolution == "", (
            f"thesis_evolution default is {t.thesis_evolution!r} — expected ''."
        )

    def test_thesis_evolution_accepts_string(self):
        """thesis_evolution must accept a non-empty string value."""
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(
            ticker="TEST",
            company_name="Test Corp",
            thesis_evolution=(
                "The debate shifted from demand durability toward margin sustainability "
                "after Q2 gross margin disappointed by 120bps. "
                "Consensus expectations contracted materially post-earnings."
            ),
        )
        assert "margin" in t.thesis_evolution.lower(), (
            "thesis_evolution did not preserve the supplied string."
        )

    def test_thesis_evolution_survives_model_dump(self):
        """thesis_evolution must be serialized in model_dump()."""
        from app.schemas import InvestmentThesis
        t = InvestmentThesis(
            ticker="TEST",
            company_name="Test Corp",
            thesis_evolution="Operating story unchanged — repricing came from rates, not fundamentals.",
        )
        try:
            d = t.model_dump()
        except Exception:
            d = t.dict()
        assert "thesis_evolution" in d, (
            "thesis_evolution is missing from model_dump() output. "
            "It must be serialized to the API response."
        )
        assert d["thesis_evolution"] != "", (
            "thesis_evolution was cleared during model_dump()."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Synthesis prompt — signal diversity and cross-signal interaction
# ─────────────────────────────────────────────────────────────────────────────

class TestSynthesisPromptSignalDiversity:
    """Verify signal diversity requirements and cross-signal interaction in synthesizer."""

    def _read_synthesizer_source(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "app", "services", "thesis_synthesizer.py",
        )
        with open(path) as fh:
            return fh.read()

    def test_signal_diversity_block_present(self):
        """SIGNAL DIVERSITY REQUIREMENTS block must be in the synthesis prompt."""
        source = self._read_synthesizer_source()
        assert "SIGNAL DIVERSITY REQUIREMENTS" in source, (
            "SIGNAL DIVERSITY REQUIREMENTS block missing from thesis_synthesizer.py. "
            "The prompt must enforce category spread across key_drivers and key_risks."
        )

    def test_signal_category_spread_listed(self):
        """The signal diversity block must list specific categories."""
        source = self._read_synthesizer_source()
        assert "operating leverage" in source and "capital allocation" in source, (
            "Signal diversity categories (operating leverage, capital allocation) "
            "are missing from thesis_synthesizer.py."
        )
        assert "pricing power" in source or "ASP" in source, (
            "Pricing power / ASP signal category missing from diversity requirements."
        )

    def test_cross_signal_interaction_block_present(self):
        """CROSS-SIGNAL INTERACTION block must be in the synthesis prompt."""
        source = self._read_synthesizer_source()
        assert "CROSS-SIGNAL INTERACTION" in source, (
            "CROSS-SIGNAL INTERACTION block missing from thesis_synthesizer.py. "
            "The prompt must require compound risk naming in bear_thesis."
        )

    def test_cross_signal_examples_present(self):
        """Cross-signal examples (compound interactions) must be in the prompt."""
        source = self._read_synthesizer_source()
        assert "higher rates" in source.lower() and "multiple compression" in source.lower(), (
            "Cross-signal compound examples are missing from thesis_synthesizer.py."
        )

    def test_signal_repetition_rule_present(self):
        """SIGNAL REPETITION — FORBIDDEN rule must be in the prompt."""
        source = self._read_synthesizer_source()
        assert "SIGNAL REPETITION" in source, (
            "SIGNAL REPETITION rule missing from thesis_synthesizer.py."
        )

    def test_thesis_evolution_field_in_schema_description(self):
        """thesis_evolution must be listed in _THESIS_SCHEMA_DESCRIPTION."""
        source = self._read_synthesizer_source()
        assert "thesis_evolution" in source, (
            "thesis_evolution field is not mentioned in thesis_synthesizer.py. "
            "Add it to _THESIS_SCHEMA_DESCRIPTION and the TASK section."
        )

    def test_thesis_evolution_what_changed_framing_in_prompt(self):
        """The synthesis prompt must describe thesis_evolution as 'What Changed?'."""
        source = self._read_synthesizer_source()
        assert "What Changed" in source or "what changed" in source.lower(), (
            "The thesis_evolution synthesis block must include 'What Changed?' framing."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Stance schema description
# ─────────────────────────────────────────────────────────────────────────────

def test_stance_schema_includes_accumulate():
    """InvestmentThesis.directional_stance description must mention 'Accumulate'."""
    from app.schemas import InvestmentThesis
    try:
        field_info = InvestmentThesis.model_fields["directional_stance"]
        description = field_info.description or ""
    except (AttributeError, KeyError):
        field_info = InvestmentThesis.__fields__["directional_stance"]
        description = field_info.field_info.description or ""
    assert "Accumulate" in description, (
        "InvestmentThesis.directional_stance field description does not mention 'Accumulate'. "
        "Update the Field() description in schemas.py."
    )


def test_stance_schema_includes_tactical():
    """InvestmentThesis.directional_stance description must mention 'Tactical'."""
    from app.schemas import InvestmentThesis
    try:
        field_info = InvestmentThesis.model_fields["directional_stance"]
        description = field_info.description or ""
    except (AttributeError, KeyError):
        field_info = InvestmentThesis.__fields__["directional_stance"]
        description = field_info.field_info.description or ""
    assert "Tactical" in description, (
        "InvestmentThesis.directional_stance field description does not mention 'Tactical'. "
        "Update the Field() description in schemas.py."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Accumulate vs Buy boundary — ensuring the right stance fires
# ─────────────────────────────────────────────────────────────────────────────

class TestAccumulateVsBuyBoundary:
    """Accumulate must fire in a clearly defined zone separate from Buy."""

    def test_accumulate_not_fired_when_fragility_very_low(self):
        """When fragility is very low (< 0.40), should be Buy not Accumulate."""
        stance, _ = _run_stance(final_score=0.65, frag=0.30, ta=0.68)
        assert stance in {"Buy", "Aggressive Buy"}, (
            f"Expected Buy/Aggressive Buy at very low fragility (0.30); got {stance!r}. "
            f"Accumulate is for mid-range fragility (0.40-0.62)."
        )

    def test_accumulate_not_fired_when_fragility_very_high(self):
        """When fragility is very high (> 0.62), should be Hold or Avoid, not Accumulate."""
        stance, _ = _run_stance(final_score=0.60, frag=0.70, ta=0.55)
        assert stance not in {"Accumulate", "Buy", "Aggressive Buy"}, (
            f"Expected Hold/Tactical/Avoid at fragility=0.70; got {stance!r}."
        )

    def test_accumulate_description_mentions_entry_context(self):
        """Accumulate reasoning must explain the 'add on dips' entry context."""
        _, reasoning = _run_stance(final_score=0.62, frag=0.50)
        assert any(kw in reasoning.lower() for kw in (
            "dip", "weakness", "add on", "entry", "pricing"
        )), (
            f"Accumulate reasoning must reference entry/dip context. Got: {reasoning!r}"
        )
