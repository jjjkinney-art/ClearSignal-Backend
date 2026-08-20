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

    def test_known_variants_are_pinned(self):
        """Sprint 3B.4 adds risk_struct_a. risk_fast_a is retained as a named
        variant purely so its live failure stays reproducible; it is no longer
        a candidate."""
        from app.investment_agents.risk_variants import RISK_VARIANT_STRUCT_A
        assert KNOWN_RISK_VARIANTS == (
            RISK_VARIANT_CONTROL, RISK_VARIANT_FAST_A, RISK_VARIANT_STRUCT_A,
        )

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

    def test_reads_the_field_production_actually_emits(self):
        """The thesis emits `key_risks`, not `risks`.

        The pre-existing `_risks()` helper reads `risks` and therefore returns
        nothing on every real artifact. The risk layer must not inherit that
        blind spot or the whole gate is dead code.
        """
        from validation.ab_compare import _risk_entries
        assert len(_risk_entries({"key_risks": ["a", "b"]})) == 2
        assert len(_risk_entries({"top_risks": [{"risk": "c"}]})) == 1
        assert len(_risk_entries({"risks": ["d"]})) == 1

    def test_qualified_risk_is_not_flagged_generic(self):
        """A 3B.1A-style false positive must not reappear.

        "Increased competition in AI inference market" names the market and is
        specific; flagging it would reject a good candidate.
        """
        from validation.ab_compare import _generic_hits
        qualified = {"key_risks": [
            "NVDA-specific: Increased competition in AI inference market",
            "Market volatility of 20% in Q3",
        ]}
        assert _generic_hits(qualified, "NVDA") == []

    def test_bare_boilerplate_is_flagged_generic(self):
        from validation.ab_compare import _generic_hits
        bare = {"key_risks": ["Market volatility", "Increased competition"]}
        assert _generic_hits(bare, "NVDA") == [
            "increased competition", "market volatility",
        ]

    def test_generic_already_in_control_is_not_a_reject(self):
        """Only phrasing the candidate *introduces* counts against it."""
        from validation.ab_compare import compare_thesis, verdict
        shared = [{"risk": "Increased competition"}, {"risk": "Market volatility"}]
        c = _thesis_payload(shared)
        k = _thesis_payload(shared, variant="risk_fast_a")
        assert not any("generic risk phrasing" in r
                       for r in verdict(compare_thesis(c, k))[1])

    def test_mechanism_detector_has_signal_on_production_shape(self):
        """key_risks are terse labels; the mechanism lives in bear_thesis.

        Counting mechanisms over risk entries alone reads 0 on every real
        artifact, which would make this gate inert. Verified against saved
        artifacts: median 5 distinct mechanisms, never 0.
        """
        from validation.ab_compare import _mechanism_count
        production_shape = {
            "key_risks": ["MSFT-specific: Decline in Azure growth rate"],
            "bear_thesis": ("A slowdown in Azure's growth below 25% would "
                            "compress the multiple, reducing forward P/E"),
            "conclusion": "", "direct_answer": "",
        }
        assert _mechanism_count(production_shape) >= 2

    def test_mechanism_detector_reports_zero_when_flattened(self):
        from validation.ab_compare import _mechanism_count
        assert _mechanism_count({
            "key_risks": ["Risk"], "bear_thesis": "The outlook is uncertain.",
            "conclusion": "", "direct_answer": "",
        }) == 0

    def test_bare_as_and_if_are_not_mechanisms(self):
        """Substring 'as'/'if' match ordinary prose and would fake a mechanism."""
        from validation.ab_compare import _MECHANISM_MARKERS
        assert "as " not in _MECHANISM_MARKERS
        assert "if " not in _MECHANISM_MARKERS


# ── Regression: existing comparator standards must be untouched ──────────────

class TestExistingVerdictsPreserved:
    """The 3B.3 risk layer must not shift any Sprint 3B.2 verdict.

    Replays the five reported live model-A/B pairs through the modified
    comparator. Artifacts live under validation/runs/, which is gitignored, so
    this skips where they are absent rather than failing a clean checkout.

    NVDA is deliberately excluded from this pin (see
    TestRiskTimeoutGuard.test_nvda_control_timeout_flips_review_to_invalid):
    the m2-control-NVDA artifact hit the 16s risk-agent wall cap, and Sprint
    3B.3.1 exists precisely because scoring that pair as an ordinary "review"
    was the misleading verdict this guard is meant to prevent. Pinning NVDA to
    "review" here would mean asserting the bug back in.
    """

    EXPECTED = {"MSFT": "reject", "JPM": "review",
                "ASML": "review", "TSLA": "keep"}

    @pytest.mark.parametrize("ticker,expected", sorted(EXPECTED.items()))
    def test_reported_3b2_verdict_is_reproduced(self, ticker, expected):
        from pathlib import Path

        from validation.ab_compare import compare_runs

        control = Path(f"validation/runs/m2-control-{ticker}")
        candidate = Path(f"validation/runs/m2-fasta-{ticker}")
        if not (control.is_dir() and candidate.is_dir()):
            pytest.skip("live A/B artifacts not present in this checkout")
        result = compare_runs(control, candidate)
        assert result["pairs"], "no comparable pair found"
        assert result["pairs"][0]["verdict"] == expected

    def test_risk_layer_stays_silent_on_pre_3b3_artifacts(self):
        """Artifacts predating this sprint carry no risk_variant."""
        from pathlib import Path

        from validation.ab_compare import compare_runs

        control = Path("validation/runs/m2-control-MSFT")
        candidate = Path("validation/runs/m2-fasta-MSFT")
        if not (control.is_dir() and candidate.is_dir()):
            pytest.skip("live A/B artifacts not present in this checkout")
        pair = compare_runs(control, candidate)["pairs"][0]
        assert pair["risk"]["risk_variant_candidate"] is None


# ── Risk-agent timeout/failure guard (Sprint 3B.3.1) ─────────────────────────

def _obs(stages):
    return {"_observability": {"stages": stages}}


def _risk_stage(status, **extra):
    return {"stage": "agent.risk", "status": status,
            "duration_ms": 16000.0 if status == "timeout" else 9000.0, **extra}


class TestRiskExecutionStatus:
    def test_ok_status_detected(self):
        from validation.ab_compare import risk_execution_status
        assert risk_execution_status(_obs([_risk_stage("ok")])) == "ok"

    def test_timeout_status_detected_from_recorded_status_not_duration(self):
        """A slow-but-successful call must not be misread as a timeout."""
        from validation.ab_compare import risk_execution_status
        slow_but_ok = _obs([_risk_stage("ok", duration_ms=15900.0)])
        assert risk_execution_status(slow_but_ok) == "ok"
        genuine_timeout = _obs([_risk_stage("timeout", duration_ms=100.0)])
        assert risk_execution_status(genuine_timeout) == "timeout"

    def test_error_status_detected(self):
        from validation.ab_compare import risk_execution_status
        assert risk_execution_status(_obs([_risk_stage("error")])) == "error"

    def test_late_arriving_ok_does_not_override_a_recorded_timeout(self):
        """Mirrors the real NVDA shape: an abandoned thread's late 'ok' entry
        must not erase the fact that production already used the fallback."""
        from validation.ab_compare import risk_execution_status
        both = _obs([_risk_stage("timeout"), _risk_stage("ok")])
        assert risk_execution_status(both) == "timeout"

    def test_no_observability_is_unknown_not_a_failure(self):
        from validation.ab_compare import risk_execution_status
        assert risk_execution_status({}) == "unknown"
        assert risk_execution_status({"_observability": {}}) == "unknown"
        assert risk_execution_status(None) == "unknown"

    def test_observability_without_risk_stage_is_unknown(self):
        from validation.ab_compare import risk_execution_status
        assert risk_execution_status(
            _obs([{"stage": "agent.macro", "status": "ok"}])
        ) == "unknown"


class TestRiskTimeoutGuard:
    def _pair(self, control_status, candidate_status):
        control = {**_thesis_payload(_GOOD_RISKS), **_obs([_risk_stage(control_status)])}
        candidate = {**_thesis_payload(_GOOD_RISKS, variant="risk_fast_a"),
                    **_obs([_risk_stage(candidate_status)])}
        return control, candidate

    def test_control_timeout_is_detected(self):
        from validation.ab_compare import compare_thesis, verdict
        c, k = self._pair("timeout", "ok")
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "invalid"
        assert reasons == ["risk comparison invalid: control risk agent timed out"]

    def test_candidate_timeout_is_detected(self):
        from validation.ab_compare import compare_thesis, verdict
        c, k = self._pair("ok", "timeout")
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "invalid"
        assert reasons == ["risk comparison invalid: candidate risk agent timed out"]

    def test_both_sides_timing_out_reports_both(self):
        from validation.ab_compare import compare_thesis, verdict
        c, k = self._pair("timeout", "timeout")
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "invalid"
        assert len(reasons) == 2

    def test_error_status_also_invalidates(self):
        from validation.ab_compare import compare_thesis, verdict
        c, k = self._pair("error", "ok")
        v, reasons = verdict(compare_thesis(c, k))
        assert v == "invalid"
        assert "errored" in reasons[0]

    def test_fallback_text_is_not_read_as_genuine_content_degradation(self):
        """The literal requirement: a timeout-caused fallback must not be
        scored via the ordinary content checks (which would report a false
        "risk entries fell" / "generic phrasing" reject)."""
        from validation.ab_compare import compare_thesis, verdict
        control = {**_thesis_payload(_GOOD_RISKS), **_obs([_risk_stage("timeout")])}
        # Candidate's risk content genuinely IS the production fallback shape:
        # bare, generic, no company reference — content that would otherwise
        # trip every reject condition in the risk layer.
        candidate = {**_thesis_payload(
            [{"risk": "Risk analysis unavailable."}], variant="risk_fast_a",
        ), **_obs([_risk_stage("ok")])}
        v, reasons = verdict(compare_thesis(control, candidate))
        assert v == "invalid"
        assert not any("generic risk phrasing" in r or "mechanism" in r
                       for r in reasons)

    def test_valid_pair_still_compares_normally(self):
        """The guard must not fire when both sides genuinely succeeded."""
        from validation.ab_compare import compare_thesis, verdict
        c, k = self._pair("ok", "ok")
        v, _ = verdict(compare_thesis(c, k))
        assert v == "keep"

    def test_unknown_status_does_not_invalidate(self):
        """Backward compatibility: artifacts with no observability at all
        (older runs, synthetic fixtures) must keep comparing normally."""
        from validation.ab_compare import compare_thesis, verdict
        c = _thesis_payload(_GOOD_RISKS)
        k = _thesis_payload(_GOOD_RISKS, variant="risk_fast_a")
        v, _ = verdict(compare_thesis(c, k))
        assert v == "keep"

    def test_invalid_never_reported_as_keep(self):
        from validation.ab_compare import risk_ab_validity
        c, k = self._pair("timeout", "ok")
        assert risk_ab_validity(c, k) != []

    def test_reason_wording_matches_the_specified_format(self):
        from validation.ab_compare import risk_ab_validity
        c, k = self._pair("timeout", "ok")
        assert risk_ab_validity(c, k) == [
            "risk comparison invalid: control risk agent timed out"
        ]

    def test_nvda_control_timeout_flips_review_to_invalid(self):
        """The exact real-world case this guard was written for."""
        from pathlib import Path

        from validation.ab_compare import compare_runs

        control = Path("validation/runs/m2-control-NVDA")
        candidate = Path("validation/runs/m2-fasta-NVDA")
        if not (control.is_dir() and candidate.is_dir()):
            pytest.skip("live A/B artifacts not present in this checkout")
        pair = compare_runs(control, candidate)["pairs"][0]
        assert pair["verdict"] == "invalid"
        assert pair["risk"]["risk_status_control"] == "timeout"
        assert "control risk agent timed out" in pair["reasons"][0]


class TestRunnerReportingVisibility:
    def test_tally_includes_invalid_bucket(self):
        """compare_runs' tally dict must pre-seed "invalid", or a real
        invalid pair raises KeyError instead of being counted."""
        import inspect

        from validation.ab_compare import compare_runs
        src = inspect.getsource(compare_runs)
        assert '"invalid": 0' in src or "'invalid': 0" in src

    def test_report_shows_risk_status_without_prompt_text(self):
        from validation.ab_compare import ab_report_md
        result = {
            "control_dir": "c", "candidate_dir": "k", "compared": 1,
            "only_in_control": [], "only_in_candidate": [],
            "tally": {"keep": 0, "review": 0, "reject": 0, "invalid": 1},
            "pairs": [{
                "id": "NVDA-core_thesis", "verdict": "invalid",
                "reasons": ["risk comparison invalid: control risk agent timed out"],
                "prose_ratio": None, "confidence_changed": False,
                "confidence_control": 0.5, "confidence_candidate": 0.5,
                "risk": {"risk_status_control": "timeout",
                        "risk_status_candidate": "ok"},
            }],
        }
        md = ab_report_md(result)
        assert "timeout/ok" in md
        assert "invalid: **1**" in md
        assert "SENTINEL_PROMPT" not in md  # sanity: nothing prompt-shaped leaks

    def test_report_flags_invalid_pairs_with_an_explicit_warning(self):
        from validation.ab_compare import ab_report_md
        result = {
            "control_dir": "c", "candidate_dir": "k", "compared": 1,
            "only_in_control": [], "only_in_candidate": [],
            "tally": {"keep": 0, "review": 0, "reject": 0, "invalid": 1},
            "pairs": [],
        }
        assert "could not be judged" in ab_report_md(result)
