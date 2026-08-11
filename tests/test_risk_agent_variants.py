"""Sprint 3B.3 — risk-agent output-shape variant tests.

The sprint's claim is narrow and these tests are shaped to hold it to that
claim: `risk_fast_a` changes the risk agent's *generated output shape* and
nothing else. Production must be byte-identical, unreachable without internal
authorization, and every other stage — synthesis prompt, synthesis model, the
other five agents, retrieval, downstream integrity — must be untouched.
"""
from __future__ import annotations

import inspect

import pytest

from app.investment_agents import risk_agent
from app.investment_agents.risk_variants import (
    BOUNDED_FIELDS,
    KNOWN_RISK_VARIANTS,
    RISK_VARIANT_CONTROL,
    RISK_VARIANT_FAST_A,
    UNTOUCHED_FIELDS,
    apply_risk_variant,
    describe_risk_variant,
    estimate_tokens,
    resolve_risk_variant,
)
from app.schemas import CompanyContext, RetrievedEvidence, RiskProfile


def _company() -> CompanyContext:
    return CompanyContext(
        ticker="MSFT", company_name="Microsoft Corporation",
        sector="Technology", industry="Software", aliases=["Microsoft"],
    )


def _evidence(n: int = 5) -> list:
    return [
        RetrievedEvidence(
            title=f"MSFT 10-K Risk Factors item {i}", source="sec_edgar",
            summary="Leverage and concentration detail. " * 12,
            timestamp="2026-01-15T00:00:00Z",
        )
        for i in range(n)
    ]


def _control_prompt(**kw) -> str:
    return risk_agent._build_prompt(_company(), _evidence(), None, **kw)


# ── Control must be untouched ────────────────────────────────────────────────

class TestControlUnchanged:
    def test_control_is_byte_identical(self):
        p = _control_prompt()
        assert apply_risk_variant(p, RISK_VARIANT_CONTROL) == p

    @pytest.mark.parametrize("intent", [
        None, "risk_assessment", "competitive_position",
        "valuation_stance", "macro_sensitivity",
    ])
    def test_control_identical_for_every_intent(self, intent):
        p = _control_prompt(question_intent=intent, question="What are the risks?")
        assert apply_risk_variant(p, RISK_VARIANT_CONTROL) == p

    def test_unknown_variant_falls_back_to_control_prompt(self):
        p = _control_prompt()
        for bogus in ("", "fast_a", "risk_fast_b", "control", "RISK_FAST_A ", None):
            assert apply_risk_variant(p, bogus) == p

    def test_default_contextvar_is_risk_control(self):
        from app.observability import current_risk_variant, set_risk_variant
        set_risk_variant(RISK_VARIANT_CONTROL)
        assert current_risk_variant() == RISK_VARIANT_CONTROL

    def test_empty_variant_resets_to_control(self):
        from app.observability import current_risk_variant, set_risk_variant
        set_risk_variant("")
        assert current_risk_variant() == RISK_VARIANT_CONTROL


# ── Authorization: fails closed ──────────────────────────────────────────────

class TestAuthorization:
    def test_unauthorized_never_gets_a_variant(self):
        for req in ("risk_fast_a", "risk_control", "bogus", "", None):
            assert resolve_risk_variant(req, authorized=False) == RISK_VARIANT_CONTROL

    def test_authorized_can_select_fast_a(self):
        assert resolve_risk_variant("risk_fast_a", authorized=True) == RISK_VARIANT_FAST_A

    def test_authorized_unknown_name_falls_closed(self):
        for req in ("bogus", "fast_a", "risk_fast_b", "", None, "  "):
            assert resolve_risk_variant(req, authorized=True) == RISK_VARIANT_CONTROL

    def test_case_and_whitespace_normalised(self):
        assert resolve_risk_variant("  RISK_FAST_A  ", authorized=True) == RISK_VARIANT_FAST_A

    def test_known_variants_are_exactly_two(self):
        assert KNOWN_RISK_VARIANTS == (RISK_VARIANT_CONTROL, RISK_VARIANT_FAST_A)

    def test_risk_header_is_distinct_from_synthesis_headers(self):
        from app.observability import (
            MODEL_VARIANT_HEADER, PROMPT_VARIANT_HEADER, RISK_VARIANT_HEADER,
        )
        assert len({RISK_VARIANT_HEADER, MODEL_VARIANT_HEADER, PROMPT_VARIANT_HEADER}) == 3


# ── One-variable isolation ───────────────────────────────────────────────────

class TestOneVariableIsolation:
    def test_fast_a_changes_the_prompt(self):
        p = _control_prompt()
        assert apply_risk_variant(p, RISK_VARIANT_FAST_A) != p

    def test_fast_a_is_a_pure_suffix_of_control(self):
        """The control prompt must survive verbatim inside the variant.

        This is what makes the experiment one-variable: the variant adds a
        constraint, it never rewrites or drops any control instruction.
        """
        p = _control_prompt()
        fa = apply_risk_variant(p, RISK_VARIANT_FAST_A)
        body = p[: -len("\n\nJSON:")]
        assert body in fa
        assert fa.endswith("JSON:")

    def test_variant_names_every_bounded_field(self):
        fa = apply_risk_variant(_control_prompt(), RISK_VARIANT_FAST_A)
        for fld in BOUNDED_FIELDS:
            assert fld in fa

    def test_bounded_set_has_not_drifted(self):
        assert BOUNDED_FIELDS == (
            "debt_risk", "competitive_risk", "regulatory_risk", "concentration_risk",
        )

    def test_untouched_fields_are_explicitly_protected(self):
        """The always-consumed fields must be named as *not* to be shortened."""
        fa = apply_risk_variant(_control_prompt(), RISK_VARIANT_FAST_A)
        for fld in ("key_risks", "overall", "signals"):
            assert fld in fa
        assert "Do NOT shorten key_risks, overall or signals" in fa

    def test_untouched_set_has_not_drifted(self):
        assert UNTOUCHED_FIELDS == ("key_risks", "overall", "confidence", "signals")

    def test_variant_mandates_anchor_retention(self):
        """The 3B.2 failure mode was a lost quantitative threshold.

        The variant must carry an explicit retention mandate, or it is just
        prose compression of the kind that already failed.
        """
        fa = apply_risk_variant(_control_prompt(), RISK_VARIANT_FAST_A)
        low = fa.lower()
        for token in ("numeric figure", "threshold", "competitor",
                      "citation", "mechanism"):
            assert token in low

    def test_variant_forbids_dropping_a_field(self):
        fa = apply_risk_variant(_control_prompt(), RISK_VARIANT_FAST_A)
        assert "Do NOT drop a field" in fa


# ── Nothing else may change ──────────────────────────────────────────────────

class TestNoOtherBehaviorChange:
    def test_no_extra_model_call_is_introduced(self):
        """`run_risk_agent` must still make exactly one structured call."""
        src = inspect.getsource(risk_agent.run_risk_agent)
        assert src.count("get_structured_response(") == 1

    def test_variant_does_not_touch_the_model_client(self):
        """Risk keeps the production agent client — this sprint is not a model A/B."""
        src = inspect.getsource(risk_agent)
        assert "synthesis_client" not in src
        assert "ModelClient(" not in src

    def test_risk_variant_module_does_not_import_synthesis(self):
        from app.investment_agents import risk_variants
        src = inspect.getsource(risk_variants)
        assert "thesis_synthesizer" not in src
        assert "synthesis_prompt_variants" not in src
        assert "synthesis_model_variants" not in src

    def test_other_agents_have_no_variant_hook(self):
        for mod in ("macro_agent", "market_agent", "quality_agent", "valuation_agent"):
            m = __import__(f"app.investment_agents.{mod}", fromlist=[mod])
            assert "apply_risk_variant" not in inspect.getsource(m)

    def test_evidence_filter_is_unchanged_by_variant(self):
        """Retrieval payload into risk must not depend on the variant."""
        from app.observability import set_risk_variant
        ev = _evidence()
        set_risk_variant(RISK_VARIANT_FAST_A)
        a = risk_agent._filter_evidence(ev, _company())
        set_risk_variant(RISK_VARIANT_CONTROL)
        b = risk_agent._filter_evidence(ev, _company())
        assert [e.title for e in a] == [e.title for e in b]

    def test_riskprofile_schema_fields_unchanged(self):
        """The output contract must be identical across variants."""
        fields = set(RiskProfile.model_fields)
        assert {"debt_risk", "competitive_risk", "regulatory_risk",
                "concentration_risk", "key_risks", "overall", "confidence",
                "signals", "evidence_used", "quantitative_claims"} <= fields


# ── Observability ────────────────────────────────────────────────────────────

class TestObservability:
    def test_describe_reports_variant_and_model(self):
        d = describe_risk_variant(RISK_VARIANT_FAST_A)
        assert d["risk_variant"] == RISK_VARIANT_FAST_A
        assert d["risk_provider"] == "openai"
        assert d["risk_model"]

    def test_describe_reports_sizes_when_given(self):
        d = describe_risk_variant(RISK_VARIANT_CONTROL, prompt="abcd" * 25,
                                  evidence_count=4)
        assert d["risk_input_chars"] == 100
        assert d["risk_input_tokens_est"] == 25
        assert d["risk_item_count"] == 4

    def test_describe_never_returns_prompt_text(self):
        marker = "SENTINEL_PROMPT_BODY_XYZ"
        d = describe_risk_variant(RISK_VARIANT_FAST_A, prompt=marker * 10,
                                  evidence_count=1)
        assert marker not in repr(d)

    def test_agent_meta_scrubs_prompt_text(self):
        from app.observability import RequestTrace
        t = RequestTrace("r1")
        t.note_agent_meta(risk_variant="risk_fast_a", risk_input_chars=1234,
                          profile_token="SHOULD_NOT_APPEAR")
        assert t.agent_meta["risk_variant"] == "risk_fast_a"
        assert t.agent_meta["risk_input_chars"] == 1234
        assert "profile_token" not in t.agent_meta

    def test_scrubber_still_rejects_prompt_named_keys(self):
        """The 3A redaction rule must not have been widened to admit sizes."""
        from app.observability import RequestTrace
        t = RequestTrace("r3")
        t.note_agent_meta(risk_prompt_chars=99, risk_evidence_items=3,
                          risk_input_chars=99)
        assert "risk_prompt_chars" not in t.agent_meta
        assert "risk_evidence_items" not in t.agent_meta
        assert t.agent_meta["risk_input_chars"] == 99

    def test_agent_meta_is_detail_gated(self):
        from app.observability import RequestTrace
        t = RequestTrace("r2")
        t.note_agent_meta(risk_variant="risk_fast_a")
        assert "agent_meta" not in t.to_dict(include_stages=False)
        assert t.to_dict(include_stages=True)["agent_meta"]["risk_variant"] == "risk_fast_a"

    def test_estimate_tokens_is_length_based(self):
        assert estimate_tokens("x" * 400) == 100
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0


# ── Executor propagation ─────────────────────────────────────────────────────

class TestExecutorPropagation:
    def test_bind_carries_risk_variant_into_a_worker_thread(self):
        """The risk agent runs in a ThreadPoolExecutor.

        Without propagation the variant would silently never apply, and an A/B
        run would compare control against control while reporting otherwise.
        """
        from concurrent.futures import ThreadPoolExecutor

        from app.observability import bind, current_risk_variant, set_risk_variant

        set_risk_variant(RISK_VARIANT_FAST_A)
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen = pool.submit(bind(current_risk_variant)).result()
        set_risk_variant(RISK_VARIANT_CONTROL)
        assert seen == RISK_VARIANT_FAST_A

    def test_bind_still_carries_the_other_two_variants(self):
        from concurrent.futures import ThreadPoolExecutor

        from app.observability import (
            bind, current_model_variant, current_prompt_variant,
            set_model_variant, set_prompt_variant,
        )

        set_prompt_variant("compact_a")
        set_model_variant("fast_a")
        with ThreadPoolExecutor(max_workers=1) as pool:
            got = pool.submit(bind(lambda: (current_prompt_variant(),
                                            current_model_variant()))).result()
        set_prompt_variant("control")
        set_model_variant("control")
        assert got == ("compact_a", "fast_a")


# ── Runner plumbing ──────────────────────────────────────────────────────────

class TestRunnerPlumbing:
    def test_risk_header_requires_a_profile_token(self):
        from validation.runner import RISK_VARIANT_HEADER, build_ask_headers
        h = build_ask_headers(None, None, None, None, "risk_fast_a")
        assert RISK_VARIANT_HEADER not in h

    def test_risk_header_sent_with_a_profile_token(self):
        from validation.runner import RISK_VARIANT_HEADER, build_ask_headers
        h = build_ask_headers(None, "tok", None, None, "risk_fast_a")
        assert h[RISK_VARIANT_HEADER] == "risk_fast_a"

    def test_risk_variant_is_independent_of_synthesis_variants(self):
        from validation.runner import (
            RISK_VARIANT_HEADER, SYNTHESIS_MODEL_VARIANT_HEADER,
            SYNTHESIS_VARIANT_HEADER, build_ask_headers,
        )
        h = build_ask_headers(None, "tok", None, None, "risk_fast_a")
        assert RISK_VARIANT_HEADER in h
        assert SYNTHESIS_VARIANT_HEADER not in h
        assert SYNTHESIS_MODEL_VARIANT_HEADER not in h

    def test_cli_exposes_risk_variant_flag(self):
        from validation.runner import build_arg_parser
        args = build_arg_parser().parse_args(["--risk-variant", "risk_fast_a"])
        assert args.risk_variant == "risk_fast_a"

    def test_cli_risk_variant_defaults_empty(self):
        from validation.runner import build_arg_parser
        assert build_arg_parser().parse_args([]).risk_variant == ""


# ── Risk-specific comparator (Sprint 3B.3) ───────────────────────────────────

def _thesis_payload(risks, *, variant=None, company="MSFT"):
    payload = {
        "company": company,
        "answer": {"investment_thesis": {
            "direct_answer": "MSFT faces FCF risk.",
            "bull_thesis": "b",
            "bear_thesis": "Azure decelerates because capex rises.",
            "valuation_view": "v", "conclusion": "c", "confidence": 0.7,
            "risks": risks, "catalysts": ["x"],
            "decision_thresholds": [], "quantitative_claims": [],
            "_integrity": {"ok": True, "status": "clean"},
        }},
    }
    if variant is not None:
        payload["_observability"] = {"risk_variant": variant}
    return payload


_GOOD_RISKS = [
    {"risk": "MSFT Azure margin compresses because capex intensity rises"},
    {"risk": "MSFT faces OpenAI concentration due to funding exposure"},
]
_BAD_RISKS = [{"risk": "Market volatility"}, {"risk": "Increased competition"}]


class TestRiskComparator:
    def test_equivalent_risk_ab_pair_keeps(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_GOOD_RISKS, variant="risk_fast_a")
        assert verdict(compare_thesis(c, k))[0] == "keep"

    def test_lost_mechanism_is_a_reject(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_BAD_RISKS, variant="risk_fast_a")
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "reject"
        assert any("mechanism" in r for r in reasons)

    def test_generic_phrasing_is_a_reject(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_BAD_RISKS, variant="risk_fast_a")
        assert any("generic risk phrasing" in r
                   for r in verdict(compare_thesis(c, k))[1])

    def test_losing_company_specificity_is_a_reject(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_BAD_RISKS, variant="risk_fast_a")
        assert any("no longer names the company" in r
                   for r in verdict(compare_thesis(c, k))[1])

    def test_dropped_risk_entry_is_a_reject(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_GOOD_RISKS[:1], variant="risk_fast_a")
        assert any("risk entries fell" in r
                   for r in verdict(compare_thesis(c, k))[1])

    def test_risk_layer_is_silent_without_a_risk_variant(self):
        """Existing synthesis A/B verdicts must be bit-for-bit unchanged."""
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_BAD_RISKS)          # no _observability at all
        v, reasons = verdict(compare_thesis(c, k))
        assert not any("mechanism" in r or "generic risk" in r for r in reasons)

    def test_risk_layer_is_silent_for_control_variant(self):
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_BAD_RISKS, variant="risk_control")
        assert not any("mechanism" in r
                       for r in verdict(compare_thesis(c, k))[1])

    def test_risk_block_is_always_present_in_the_artifact(self):
        from validation.ab_compare import compare_thesis
        cmp_ = compare_thesis(_thesis_payload(_GOOD_RISKS),
                              _thesis_payload(_GOOD_RISKS))
        assert "risk" in cmp_
        assert cmp_["risk"]["risk_entries_control"] == 2

    def test_risk_reasons_empty_for_missing_variant(self):
        from validation.ab_compare import risk_reasons
        assert risk_reasons({}) == []
        assert risk_reasons({"risk_variant_candidate": None}) == []
