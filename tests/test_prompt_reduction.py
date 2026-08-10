"""Sprint 3B.1 — synthesis prompt variants, section instrumentation, A/B.

Grounded in the sprint3b-verify production profile: synthesis is the slowest
stage on 34/36 queries, and the sole finding was NVDA-structural_risk writing
"FY26" with no calendar anchor. Fully offline.
"""
from __future__ import annotations

import json

import pytest

from app import observability as obs
from app.services.synthesis_prompt_variants import (
    KNOWN_VARIANTS, VARIANT_COMPACT_A, VARIANT_COMPACT_B, VARIANT_CONTROL,
    apply_variant, estimate_tokens, measure_sections, resolve_variant,
)
from app.services.thesis_polisher import _expand_fiscal_year
from validation.ab_compare import compare_thesis, verdict
from validation.runner import (
    SYNTHESIS_VARIANT_HEADER, build_ask_headers,
)

SECRET = "profiling-secret"

# A prompt shaped like the real one: the style/density blocks compact_a
# consolidates, plus analytic blocks it must never touch.
SAMPLE_PROMPT = "\n\n".join([
    "You are a senior investment analyst producing an institutional thesis.",
    "Required JSON fields (all must be present):\n" + "\n".join(
        f'  "field_{i}" : string — description of field {i}' for i in range(40)),
    "WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:\n" + ("- vary it\n" * 30),
    "NATURALNESS — MANDATORY:\n" + ("- sound human\n" * 20),
    "STRUCTURAL VARIETY — MANDATORY:\n" + ("- rotate openings\n" * 15),
    "SECTION ASYMMETRY — MANDATORY:\n" + ("- vary length\n" * 15),
    "PM-GRADE LANGUAGE — MANDATORY:\n" + ("- PM register\n" * 10),
    "INSTITUTIONAL TONE — MANDATORY:\n- institutional",
    "MARKET-NATIVE COMPRESSION — MANDATORY:\n- compress",
    "IMPLICATION_COMPRESSION — MANDATORY:\n" + ("- state implication\n" * 25),
    "TERMINAL DENSITY — MANDATORY:\n" + ("- end dense\n" * 15),
    "SELECTIVE INCOMPLETENESS — MANDATORY:\n" + ("- leave inference\n" * 25),
    "MECHANISM_PRIORITY — MANDATORY:\n- mechanism over correlation",
    "PRICED_IN_REASONING — MANDATORY:\n- what is priced in",
    "CONFIDENCE LANGUAGE ALIGNMENT — MANDATORY:\n- align confidence",
    "EVIDENCE PROVENANCE — MANDATORY:\n- cite provenance",
    "EXPECTATION DELTA — MANDATORY:\n- delta vs consensus",
    "CORE MARKET DEBATE — MANDATORY:\n- the central debate",
    "CROSS-SIGNAL INTERACTION — MANDATORY for bear_thesis:\n- interaction",
    '"threshold_zones" : array of 2-3 objects',
    "SPECIALIST AGENT OUTPUTS:\nVALUATION: prose here",
    "SUPPORTING EVIDENCE:\n[1] evidence",
])

# Analytic mandates that must survive every variant.
PROTECTED = (
    "MECHANISM_PRIORITY", "PRICED_IN_REASONING", "CONFIDENCE LANGUAGE ALIGNMENT",
    "EVIDENCE PROVENANCE", "EXPECTATION DELTA", "CORE MARKET DEBATE",
    "CROSS-SIGNAL INTERACTION", "threshold_zones", "Required JSON fields",
    "SPECIALIST AGENT OUTPUTS", "SUPPORTING EVIDENCE",
)


@pytest.fixture(autouse=True)
def _clean():
    obs.set_trace(None)
    obs.set_prompt_variant(VARIANT_CONTROL)
    yield
    obs.set_trace(None)
    obs.set_prompt_variant(VARIANT_CONTROL)


# ── Section instrumentation ──────────────────────────────────────────────────

class TestSectionMeasurement:
    def test_totals_reconcile_with_prompt_length(self):
        m = measure_sections(SAMPLE_PROMPT)
        assert m["total_chars"] == len(SAMPLE_PROMPT)
        assert sum(s["chars"] for s in m["sections"]) == len(SAMPLE_PROMPT)

    def test_no_prompt_text_is_returned(self):
        # Section NAMES legitimately contain words like "evidence", so the
        # check is on actual prompt body text, which must never appear.
        serialized = json.dumps(measure_sections(SAMPLE_PROMPT))
        for fragment in ("You are a senior", "vary it", "sound human",
                         "mechanism over correlation", "what is priced in",
                         "MANDATORY", "[1] evidence"):
            assert fragment not in serialized, fragment

    def test_sections_carry_only_counts(self):
        for s in measure_sections(SAMPLE_PROMPT)["sections"]:
            assert set(s) == {"section", "chars", "est_tokens"}
            assert isinstance(s["chars"], int)

    def test_known_groups_are_identified(self):
        names = {s["section"] for s in measure_sections(SAMPLE_PROMPT)["sections"]}
        assert "output_schema" in names
        assert "style_formatting_rules" in names

    def test_unclassified_blocks_land_in_other_not_dropped(self):
        prompt = "Totally unknown block header\nbody text"
        m = measure_sections(prompt)
        assert sum(s["chars"] for s in m["sections"]) == len(prompt)
        assert m["sections"][0]["section"] == "other"

    def test_empty_prompt(self):
        assert measure_sections("")["total_chars"] == 0

    def test_token_estimate_is_monotonic(self):
        assert estimate_tokens("x" * 400) > estimate_tokens("x" * 100)


# ── Variant transform ────────────────────────────────────────────────────────

class TestVariantTransform:
    def test_control_is_byte_identical(self):
        # 118 existing assertions depend on the production prompt; control
        # must never differ from it.
        assert apply_variant(SAMPLE_PROMPT, VARIANT_CONTROL) == SAMPLE_PROMPT

    def test_unknown_variant_falls_back_to_control(self):
        assert apply_variant(SAMPLE_PROMPT, "experimental_xyz") == SAMPLE_PROMPT
        assert apply_variant(SAMPLE_PROMPT, "") == SAMPLE_PROMPT

    def test_compact_a_reduces_size(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert len(out) < len(SAMPLE_PROMPT)

    def test_compact_a_is_deterministic(self):
        a = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        b = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert a == b

    @pytest.mark.parametrize("marker", PROTECTED)
    def test_analytic_mandates_survive_compact_a(self, marker):
        assert marker in apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)

    @pytest.mark.parametrize("marker", PROTECTED)
    def test_analytic_mandates_survive_compact_b(self, marker):
        assert marker in apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_B)

    def test_consolidated_style_requirements_are_still_stated(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert "PROSE STYLE — MANDATORY:" in out
        for concept in ("portfolio manager", "Vary sentence length",
                        "Vary section length", "institutional"):
            assert concept.lower() in out.lower(), concept

    def test_consolidated_density_requirements_are_still_stated(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert "ANALYTICAL DENSITY — MANDATORY:" in out
        for concept in ("implication", "consequence", "inference"):
            assert concept.lower() in out.lower(), concept

    def test_superseded_style_blocks_are_gone(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        for header in ("WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:",
                       "NATURALNESS — MANDATORY:", "SECTION ASYMMETRY — MANDATORY:"):
            assert header not in out

    def test_block_ordering_is_preserved(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert out.index("Required JSON fields") < out.index("PROSE STYLE")
        assert out.index("PROSE STYLE") < out.index("SUPPORTING EVIDENCE")

    def test_compact_b_does_not_stack_unverified_reductions(self):
        # compact_b must not go further until compact_a has live evidence.
        assert apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_B) == \
               apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)

    def test_empty_prompt_is_safe(self):
        assert apply_variant("", VARIANT_COMPACT_A) == ""


# ── Variant authorization ────────────────────────────────────────────────────

class TestVariantAuthorization:
    def test_unauthorized_caller_always_gets_control(self):
        for requested in ("compact_a", "compact_b", "control", None, "garbage"):
            assert resolve_variant(requested, authorized=False) == VARIANT_CONTROL

    def test_authorized_caller_can_select_a_known_variant(self):
        assert resolve_variant("compact_a", authorized=True) == VARIANT_COMPACT_A
        assert resolve_variant("compact_b", authorized=True) == VARIANT_COMPACT_B

    def test_authorized_unknown_variant_falls_back_to_control(self):
        assert resolve_variant("compact_z", authorized=True) == VARIANT_CONTROL
        assert resolve_variant("", authorized=True) == VARIANT_CONTROL

    def test_variant_names_are_case_insensitive(self):
        assert resolve_variant("COMPACT_A", authorized=True) == VARIANT_COMPACT_A

    def test_all_known_variants_resolve(self):
        for v in KNOWN_VARIANTS:
            assert resolve_variant(v, authorized=True) == v

    def test_variant_propagates_across_a_thread(self):
        from concurrent.futures import ThreadPoolExecutor
        obs.set_prompt_variant(VARIANT_COMPACT_A)
        seen = {}

        def _worker():
            seen["v"] = obs.current_prompt_variant()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obs.bind(_worker)).result()
        assert seen["v"] == VARIANT_COMPACT_A

    def test_default_variant_is_control(self):
        obs.set_prompt_variant("")
        assert obs.current_prompt_variant() == VARIANT_CONTROL


class TestRunnerVariantHeaders:
    def test_ordinary_run_sends_no_variant_header(self):
        assert SYNTHESIS_VARIANT_HEADER not in build_ask_headers()

    def test_variant_requires_the_profiling_token(self):
        headers = build_ask_headers(synthesis_variant="compact_a")
        assert SYNTHESIS_VARIANT_HEADER not in headers

    def test_variant_sent_with_token(self):
        headers = build_ask_headers(profile_token=SECRET, synthesis_variant="compact_a")
        assert headers[SYNTHESIS_VARIANT_HEADER] == "compact_a"

    def test_header_name_matches_backend(self):
        assert SYNTHESIS_VARIANT_HEADER == obs.PROMPT_VARIANT_HEADER

    def test_cli_flag_defaults_empty(self):
        from validation.runner import build_arg_parser
        assert build_arg_parser().parse_args([]).synthesis_variant == ""
        assert build_arg_parser().parse_args(
            ["--synthesis-variant", "compact_a"]).synthesis_variant == "compact_a"


# ── NVDA fiscal-year fix ─────────────────────────────────────────────────────

class TestFiscalYearDisambiguation:
    def test_exact_nvda_production_sentence(self):
        text = ("Confirmation would come from hyperscaler CapEx guidance "
                "exceeding $200B for FY26.")
        out = _expand_fiscal_year(text)
        assert "fiscal 2026" in out
        assert "FY26" not in out

    def test_validator_no_longer_flags_the_fixed_text(self):
        from validation.checks.presentation import _FISCAL_YEAR_RE
        fixed = _expand_fiscal_year("guidance exceeding $200B for FY26.")
        assert not _FISCAL_YEAR_RE.search(fixed)

    @pytest.mark.parametrize("raw,expected", [
        ("FY26", "fiscal 2026"), ("FY 26", "fiscal 2026"),
        ("FY2026", "fiscal 2026"), ("FY25", "fiscal 2025"),
    ])
    def test_abbreviation_forms(self, raw, expected):
        assert _expand_fiscal_year(raw) == expected

    def test_multiple_references_all_expanded(self):
        assert _expand_fiscal_year("Revenue in FY25 and FY26") == \
               "Revenue in fiscal 2025 and fiscal 2026"

    def test_no_calendar_anchor_is_invented(self):
        # "fiscal 2026" states the fiscal label only — it must not assert a
        # calendar equivalence the model never established.
        out = _expand_fiscal_year("for FY26.")
        assert "calendar" not in out.lower()
        assert out == "for fiscal 2026."

    def test_text_without_fiscal_refs_is_untouched(self):
        for text in ("No fiscal references here.", "Revenue grew 14% in 2026.", ""):
            assert _expand_fiscal_year(text) == text

    def test_already_expanded_text_is_stable(self):
        assert _expand_fiscal_year("fiscal 2026 guidance") == "fiscal 2026 guidance"

    def test_polisher_applies_it_across_prose_fields(self):
        from app.services.thesis_polisher import disambiguate_fiscal_years

        class T:
            direct_answer = "Guidance for FY26 is key."
            bull_thesis = "Upside if FY27 accelerates."
            conclusion = "No refs."

            def model_copy(self, update):
                for k, v in update.items():
                    setattr(self, k, v)
                return self

        out = disambiguate_fiscal_years(T())
        assert "fiscal 2026" in out.direct_answer
        assert "fiscal 2027" in out.bull_thesis
        assert out.conclusion == "No refs."

    def test_polisher_never_raises(self):
        from app.services.thesis_polisher import disambiguate_fiscal_years
        assert disambiguate_fiscal_years(object()) is not None


# ── A/B comparison framework ─────────────────────────────────────────────────

def _resp(direct="Azure grows 31% supporting the multiple.",
          bull="Bull case rests on 25% growth.", bear="Bear if below 15%.",
          risks=None, thresholds=None, confidence="medium",
          integrity=None, variant="control"):
    return {"answer": {"investment_thesis": {
        "direct_answer": direct, "bull_thesis": bull, "bear_thesis": bear,
        "valuation_view": "At 30x the stock is fully priced.",
        "conclusion": "Constructive.", "confidence": confidence,
        "risks": risks if risks is not None else [{"risk": "Azure deceleration"}],
        "catalysts": ["Q3 earnings"],
        "decision_thresholds": thresholds if thresholds is not None
            else [{"metric": "Azure Growth"}],
        "quantitative_claims": [], "_integrity": integrity or {"ok": True,
                                                               "status": "qualified"},
    }}, "_observability": {"synthesis_variant": variant}}


class TestABComparison:
    def test_identical_responses_are_kept(self):
        c = compare_thesis(_resp(), _resp(variant="compact_a"))
        assert verdict(c)[0] == "keep"
        assert c["structural_ok"]

    def test_missing_required_field_is_rejected(self):
        cand = _resp(variant="compact_a")
        cand["answer"]["investment_thesis"]["bear_thesis"] = ""
        v, reasons = verdict(compare_thesis(_resp(), cand))
        assert v == "reject"
        assert any("missing required fields" in r for r in reasons)

    def test_lost_threshold_metric_is_rejected(self):
        cand = _resp(thresholds=[], variant="compact_a")
        v, reasons = verdict(compare_thesis(_resp(), cand))
        assert v == "reject"
        assert any("threshold metrics lost" in r for r in reasons)

    def test_flattening_into_a_generic_summary_is_rejected(self):
        cand = _resp(direct="Good.", bull="Up.", bear="Down.", variant="compact_a")
        cmp_ = compare_thesis(_resp(), cand)
        assert cmp_["flattening_suspected"] is True
        assert verdict(cmp_)[0] == "reject"

    def test_integrity_regression_is_rejected(self):
        cand = _resp(integrity={"ok": False, "status": "blocked"}, variant="compact_a")
        v, reasons = verdict(compare_thesis(_resp(), cand))
        assert v == "reject"
        assert any("integrity ok regressed" in r for r in reasons)

    def test_lost_figure_triggers_review_not_silent_pass(self):
        cand = _resp(bull="Bull case rests on continued growth.", variant="compact_a")
        v, reasons = verdict(compare_thesis(_resp(), cand))
        assert v == "review"
        assert any("figures no longer cited" in r for r in reasons)

    def test_lost_risk_triggers_review(self):
        # One of two risks dropped: the field is still populated, so this is a
        # semantic concern to review, not a structural reject.
        control = _resp(risks=[{"risk": "Azure deceleration"},
                               {"risk": "Capex intensity rising"}])
        cand = _resp(risks=[{"risk": "Azure deceleration"}], variant="compact_a")
        v, reasons = verdict(compare_thesis(control, cand))
        assert v == "review"
        assert any("risks no longer named" in r for r in reasons)

    def test_emptying_a_required_list_is_a_structural_reject(self):
        cand = _resp(risks=[], variant="compact_a")
        assert verdict(compare_thesis(_resp(), cand))[0] == "reject"

    def test_confidence_change_triggers_review(self):
        cand = _resp(confidence="high", variant="compact_a")
        v, reasons = verdict(compare_thesis(_resp(), cand))
        assert v == "review"
        assert any("confidence" in r for r in reasons)

    def test_variant_is_recorded_for_attribution(self):
        c = compare_thesis(_resp(), _resp(variant="compact_a"))
        assert c["variant_candidate"] == "compact_a"

    def test_comparison_is_not_character_similarity(self):
        """Reworded but equivalent prose must not be rejected just for
        differing textually."""
        cand = _resp(
            direct="Supporting the multiple, Azure grows 31%.",
            bull="Resting on 25% growth, the bull case holds.",
            bear="Below 15%, the bear case activates.",
            variant="compact_a")
        assert verdict(compare_thesis(_resp(), cand))[0] == "keep"

    def test_malformed_responses_do_not_crash(self):
        for bad in ({}, None, {"answer": None}, "string"):
            assert isinstance(compare_thesis(_resp(), bad), dict)


# ── Sprint 3B.1A — A/B failure forensics ─────────────────────────────────────

from app.services.synthesis_prompt_variants import VARIANT_COMPACT_A2
from validation.ab_compare import normalize_metric, _figures, _unavailable_thresholds


class TestFigureExtractionFixes:
    """Two objective comparator flaws found by the live A/B, each of which
    manufactured phantom 'lost figures'."""

    def test_ranges_are_one_figure_not_two(self):
        # NVDA reported losing '~25', '30x', '~5', '8x' — actually two ranges.
        t = {"bull_thesis": "compression to ~25-30x P/E and by ~5-8x on rates"}
        figs = _figures(t)
        assert "~25-30x" in figs and "~5-8x" in figs
        assert "~25" not in figs and "30x" not in figs

    def test_product_identifier_is_not_a_figure(self):
        # MSFT reported losing '365' — from "Microsoft 365".
        assert not any("365" in f for f in
                       _figures({"bull_thesis": "integration with Microsoft 365 drives lock-in"}))

    def test_genuine_figures_still_extracted(self):
        figs = _figures({"bull_thesis": "Azure growth of 25% and a 20% decline risk"})
        assert "25%" in figs and "20%" in figs

    def test_identifier_exclusion_keeps_neighbouring_figures(self):
        figs = _figures({"bull_thesis": "Microsoft 365 seats grew 14% last year"})
        assert "14%" in figs
        assert not any(f.startswith("365") for f in figs)


class TestMetricNormalization:
    """Renames that mean the same metric must not read as a loss; renames that
    mean a DIFFERENT metric must still be reported."""

    @pytest.mark.parametrize("a,b", [
        ("Credit Card Net Charge-Off Rate", "Net Charge-Off Rate"),   # JPM
        ("EUV System Shipments", "EUV System Shipments per Quarter"),  # ASML
        ("Net Interest Margin (NIM)", "NIM"),
        ("Return on Tangible Common Equity (ROTCE)", "ROTCE"),
        ("Forward P/E Ratio", "P/E"),
        ("Gross Margin Percentage", "Gross Margin"),
    ])
    def test_equivalent_names_normalize_together(self, a, b):
        assert normalize_metric(a) == normalize_metric(b)

    @pytest.mark.parametrize("a,b", [
        ("Net Interest Margin (NIM)", "Net Interest Income Growth"),   # JPM real loss
        ("Return on Tangible Common Equity", "Tangible Book Value Multiple"),
        ("Service Revenue Growth", "Order Backlog Value"),             # ASML real loss
        ("Forward P/E Ratio", "Gross Margin Percentage"),
    ])
    def test_materially_different_metrics_stay_distinct(self, a, b):
        assert normalize_metric(a) != normalize_metric(b)


class TestThresholdDegradationSignal:
    def test_unavailable_thresholds_counted(self):
        t = {"decision_thresholds": [
            {"metric": "A", "unavailable": True},
            {"metric": "B", "unavailable": False},
            {"metric": "C", "unavailable": True},
        ]}
        assert _unavailable_thresholds(t) == 2

    def test_degradation_rejects_even_when_names_match(self):
        """The sharpest signal: a metric that survives by name but arrives
        unusable is still a regression."""
        base = {"answer": {"investment_thesis": {
            "direct_answer": "d", "bull_thesis": "b", "bear_thesis": "r",
            "valuation_view": "v", "conclusion": "c", "confidence": "medium",
            "risks": [{"risk": "x"}], "catalysts": ["y"],
            "quantitative_claims": [], "_integrity": {"ok": True},
        }}}
        import copy
        control = copy.deepcopy(base)
        control["answer"]["investment_thesis"]["decision_thresholds"] = [
            {"metric": "EUV System Shipments", "unavailable": False}]
        cand = copy.deepcopy(base)
        cand["answer"]["investment_thesis"]["decision_thresholds"] = [
            {"metric": "EUV System Shipments per Quarter", "unavailable": True}]
        cmp_ = compare_thesis(control, cand)
        assert cmp_["threshold_metrics_lost"] == []      # rename recognised
        assert cmp_["thresholds_degraded"] == 1          # but still degraded
        v, reasons = verdict(cmp_)
        assert v == "reject"
        assert any("became unavailable" in r for r in reasons)


class TestCompactA2:
    """compact_a2 restores the specificity guidance compact_a dropped."""

    def test_restores_magnitude_requirements(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)
        assert "MAGNITUDE" in out

    def test_restores_bear_thesis_specificity(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)
        assert "MOST SPECIFIC" in out

    def test_restores_specific_mechanism_over_category(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)
        assert "specific mechanism" in out.lower()

    def test_forbids_symmetric_hedging(self):
        out = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)
        assert "symmetric balancing" in out.lower()

    def test_compact_a_lacks_what_a2_restores(self):
        a = apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A)
        assert "MAGNITUDE" not in a and "MOST SPECIFIC" not in a

    @pytest.mark.parametrize("marker", PROTECTED)
    def test_analytic_mandates_and_schema_survive_a2(self, marker):
        assert marker in apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)

    def test_a2_is_deterministic(self):
        assert apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2) == \
               apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)

    def test_a2_still_reduces_versus_control(self):
        assert len(apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)) < len(SAMPLE_PROMPT)

    def test_a2_is_more_conservative_than_a(self):
        # A safe smaller reduction is the whole point of the revision.
        assert len(apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A2)) > \
               len(apply_variant(SAMPLE_PROMPT, VARIANT_COMPACT_A))

    def test_a2_requires_authorization(self):
        assert resolve_variant("compact_a2", authorized=False) == VARIANT_CONTROL
        assert resolve_variant("compact_a2", authorized=True) == VARIANT_COMPACT_A2

    def test_control_still_byte_identical_with_a2_registered(self):
        assert apply_variant(SAMPLE_PROMPT, VARIANT_CONTROL) == SAMPLE_PROMPT


# ── Sprint 3B.1B — output-schema compression ─────────────────────────────────

import re as _re
from app.services.synthesis_prompt_variants import VARIANT_COMPACT_SCHEMA_A

SCHEMA_PROMPT = "\n\n".join([
    "You are a senior investment analyst.",
    'Required JSON fields (all must be present):\n'
    '"ticker"                  : string — the company ticker symbol\n'
    '"direct_answer"           : string — EXACTLY 4 sentences answering the question\n'
    '"bull_thesis"             : string — 3-4 sentence institutional bull case\n'
    '"bear_thesis"             : string — 3-4 sentence institutional bear case\n'
    '"valuation_view"          : string — state the SPECIFIC current multiple (e.g. "~28x")\n'
    '"threshold_zones"         : array of 3 objects — MANDATORY, never empty\n'
    '"confidence_score"        : number between 0.0 and 1.0\n'
    '"confidence_reasoning"    : string — 2-3 sentences of honest uncertainty\n'
    '"key_risks"               : array of 4 strings\n'
    'CONFIDENCE LANGUAGE ALIGNMENT — MANDATORY:\n'
    'confidence_score >= 0.82 -> you MAY use: "constructive"\n'
    'NEVER use regardless of score: "high conviction"',
    "MECHANISM_PRIORITY — MANDATORY:\n- mechanism over correlation",
    "WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:\n- vary it",
    "SPECIALIST AGENT OUTPUTS:\nVALUATION: prose",
])


def _schema_block(prompt):
    return [b for b in prompt.split("\n\n")
            if b.strip().startswith("Required JSON fields")][0]


class TestCompactSchemaA:
    def test_control_still_byte_identical(self):
        assert apply_variant(SCHEMA_PROMPT, VARIANT_CONTROL) == SCHEMA_PROMPT

    def test_deterministic(self):
        a = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)
        b = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)
        assert a == b

    def test_reduces_size(self):
        out = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)
        assert len(out) < len(SCHEMA_PROMPT)

    def test_schema_semantics_are_byte_identical_ignoring_whitespace(self):
        """The strongest guarantee available: nothing but spaces changed."""
        before = _schema_block(SCHEMA_PROMPT)
        after = _schema_block(apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A))
        assert _re.sub(r"\s+", "", before) == _re.sub(r"\s+", "", after)

    def test_every_field_name_survives(self):
        before = _re.findall(r'"([a-z_]+)"\s*:', _schema_block(SCHEMA_PROMPT))
        after = _re.findall(r'"([a-z_]+)"\s*:',
                            _schema_block(apply_variant(SCHEMA_PROMPT,
                                                        VARIANT_COMPACT_SCHEMA_A)))
        assert before == after and before

    @pytest.mark.parametrize("field", [
        "ticker", "direct_answer", "bull_thesis", "bear_thesis",
        "valuation_view", "threshold_zones", "confidence_score",
        "confidence_reasoning", "key_risks",
    ])
    def test_named_fields_present(self, field):
        assert f'"{field}"' in apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)

    @pytest.mark.parametrize("requirement", [
        "EXACTLY 4 sentences",          # direct_answer contract
        "SPECIFIC current multiple",    # valuation numeric anchor
        "MANDATORY, never empty",       # threshold_zones completeness
        "array of 3 objects",           # threshold count
        "number between 0.0 and 1.0",   # confidence type/range
        "3-4 sentence",                 # bull/bear length
        "array of 4 strings",           # key_risks
    ])
    def test_requirements_and_types_survive(self, requirement):
        assert requirement in apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)

    @pytest.mark.parametrize("enum_text", [
        "CONFIDENCE LANGUAGE ALIGNMENT — MANDATORY:",
        'confidence_score >= 0.82 -> you MAY use: "constructive"',
        'NEVER use regardless of score: "high conviction"',
    ])
    def test_embedded_confidence_mandate_survives(self, enum_text):
        # This is an analytic rule that merely lives inside the schema block.
        assert enum_text in apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)

    def test_style_and_analytic_blocks_untouched(self):
        out = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)
        # Explicitly does NOT reuse compact_a/compact_a2 reductions.
        assert "WRITING RHYTHM AND CADENCE VARIATION — MANDATORY:" in out
        assert "MECHANISM_PRIORITY — MANDATORY:" in out
        assert "SPECIALIST AGENT OUTPUTS:" in out

    def test_only_the_schema_block_changes(self):
        before = SCHEMA_PROMPT.split("\n\n")
        after = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A).split("\n\n")
        differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert len(differing) == 1
        assert before[differing[0]].strip().startswith("Required JSON fields")

    def test_requires_authorization(self):
        assert resolve_variant("compact_schema_a", authorized=False) == VARIANT_CONTROL
        assert resolve_variant("compact_schema_a", authorized=True) == \
               VARIANT_COMPACT_SCHEMA_A

    def test_does_not_reuse_compact_a_reductions(self):
        out = apply_variant(SCHEMA_PROMPT, VARIANT_COMPACT_SCHEMA_A)
        assert "PROSE STYLE — MANDATORY:" not in out
        assert "ANALYTICAL DENSITY — MANDATORY:" not in out

    def test_no_model_call_in_transform(self):
        import inspect
        from app.services import synthesis_prompt_variants as spv
        src = inspect.getsource(spv._compress_schema_whitespace)
        for forbidden in ("ModelClient", "chat.completions", "openai", ".call("):
            assert forbidden not in src


class TestThresholdQualityComparator:
    """Sprint 3B.1B strengthening — every live failure so far was a threshold
    failure, so each mode is detected explicitly."""

    @staticmethod
    def _pair(control_th, cand_th):
        base = {"direct_answer": "d", "bull_thesis": "b", "bear_thesis": "r",
                "valuation_view": "v", "conclusion": "c", "confidence": "medium",
                "risks": [{"risk": "x"}], "catalysts": ["y"],
                "quantitative_claims": [], "_integrity": {"ok": True}}
        return ({"answer": {"investment_thesis": {**base,
                                                  "decision_thresholds": control_th}}},
                {"answer": {"investment_thesis": {**base,
                                                  "decision_thresholds": cand_th}}})

    def test_available_count_drop_rejects(self):
        c, k = self._pair(
            [{"metric": "A", "unavailable": False}, {"metric": "B", "unavailable": False}],
            [{"metric": "A", "unavailable": False}])
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "reject"
        assert any("available thresholds fell" in r for r in reasons)

    def test_unavailable_substitution_rejects(self):
        c, k = self._pair(
            [{"metric": "EUV System Shipments", "unavailable": False}],
            [{"metric": "EUV System Shipments per Quarter", "unavailable": True}])
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "reject"
        assert any("no longer available" in r for r in reasons)

    def test_materially_different_replacement_rejects(self):
        c, k = self._pair(
            [{"metric": "Net Interest Margin", "unavailable": False}],
            [{"metric": "Net Interest Income Growth", "unavailable": False}])
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "reject"

    def test_lost_numeric_anchor_rejects(self):
        c, k = self._pair(
            [{"metric": "Azure Growth", "unavailable": False,
              "bull_boundary": 25.0, "bear_boundary": 15.0}],
            [{"metric": "Azure Growth", "unavailable": False,
              "bull_boundary": None, "bear_boundary": None}])
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "reject"
        assert any("numeric anchors lost" in r for r in reasons)

    def test_equivalent_rename_still_available_is_not_a_reject(self):
        c, k = self._pair(
            [{"metric": "Credit Card Net Charge-Off Rate", "unavailable": False,
              "bull_boundary": 3.0, "bear_boundary": 5.0}],
            [{"metric": "Net Charge-Off Rate", "unavailable": False,
              "bull_boundary": 3.0, "bear_boundary": 5.0}])
        assert verdict(compare_thesis(c, k))[0] == "keep"

    def test_standards_not_lowered_all_known_failures_still_reject(self):
        """Regression guard: the strengthening must not let a known-bad
        candidate through."""
        import json as _json
        import os as _os
        for T, expect in (("JPM", "reject"), ("ASML", "reject")):
            cp = f"validation/runs/ab-control-{T}/raw_responses/{T}-core_thesis.json"
            kp = f"validation/runs/ab-compacta-{T}/raw_responses/{T}-core_thesis.json"
            if not (_os.path.exists(cp) and _os.path.exists(kp)):
                pytest.skip("A/B artifacts not present in this checkout")
            v, _ = verdict(compare_thesis(_json.load(open(cp)), _json.load(open(kp))))
            assert v == expect, f"{T} should still {expect}"
