"""Sprint 3B.4 — structured risk output and its projection to RiskProfile.

Sprint 3B.3's `risk_fast_a` failed live with 0 keeps across 15 observations:
bounding prose destroyed the thresholds, numeric anchors and mechanisms that
prose was carrying. `risk_struct_a` changes the REPRESENTATION instead — each
risk fact is stated once as a structured item, and the existing RiskProfile
contract is rebuilt from those items in Python.

These tests hold that claim to its narrow form: the projection must reconstruct
a full-weight RiskProfile with every load-bearing element intact, production
must be untouched, and a failed parse must degrade rather than ship a hollow
profile.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.investment_agents import risk_agent
from app.investment_agents.risk_structured import (
    CATEGORY_TO_FIELD,
    PROSE_FIELDS,
    RiskItem,
    RiskStructured,
    project_to_risk_profile,
    projection_is_viable,
    render_item,
)
from app.investment_agents.risk_variants import (
    RISK_VARIANT_CONTROL,
    RISK_VARIANT_FAST_A,
    RISK_VARIANT_STRUCT_A,
    STRUCTURED_RISK_VARIANTS,
    apply_risk_variant,
    resolve_risk_variant,
)
from app.schemas import CompanyContext, RetrievedEvidence, RiskProfile, Signal


def _company():
    return CompanyContext(ticker="MSFT", company_name="Microsoft Corporation",
                          sector="Technology", industry="Software",
                          aliases=["Microsoft"])


def _evidence(n=5):
    return [RetrievedEvidence(title=f"MSFT 10-K item {i}", source="sec_edgar",
                              summary="Leverage detail. " * 12,
                              timestamp="2026-01-15T00:00:00Z")
            for i in range(n)]


def _control_prompt(**kw):
    return risk_agent._build_prompt(_company(), _evidence(), None, **kw)


def _full_item(**over):
    base = dict(
        category="competitive",
        mechanism="Azure growth below 25% compresses the forward multiple",
        metric="Azure YoY growth", current_value="~29%",
        warning_threshold="25%", bear_threshold="20%",
        entities=["AWS", "Google Cloud"], citations=[2], impact=0.85,
        horizon="medium_term",
    )
    base.update(over)
    return RiskItem(**base)


def _structured():
    return RiskStructured(
        overall="MSFT risk is AI capex execution, not leverage. Net cash $28.5B [1].",
        confidence=0.72,
        risk_items=[
            _full_item(),
            _full_item(category="debt", mechanism="AI capex reduces FCF conversion",
                       metric="quarterly capex", current_value="$22.6B",
                       warning_threshold="$25B", bear_threshold="$30B",
                       entities=["Nvidia"], citations=[3], impact=0.70,
                       horizon="short_term"),
            _full_item(category="regulatory",
                       mechanism="EU Teams unbundling sets a Copilot precedent",
                       metric="remedy scope", current_value="Teams unbundled",
                       warning_threshold="Copilot review", bear_threshold="forced unbundling",
                       entities=["European Commission"], citations=[5], impact=0.60,
                       horizon="long_term"),
            _full_item(category="concentration",
                       mechanism="Nvidia supplies substantially all AI silicon",
                       metric="supplier concentration", current_value="<2% per customer",
                       warning_threshold="", bear_threshold="",
                       entities=["Nvidia", "OpenAI"], citations=[1], impact=0.45,
                       horizon="long_term"),
        ],
    )


def _project(structured=None):
    return project_to_risk_profile(
        structured or _structured(), ticker="MSFT",
        risk_profile_cls=RiskProfile, signal_cls=Signal,
    )


# ── Schema ───────────────────────────────────────────────────────────────────

class TestSchema:
    def test_only_mechanism_carries_meaning_without_defaults(self):
        item = RiskItem(mechanism="m")
        assert item.category == "other"
        assert item.metric == "" and item.warning_threshold == ""
        assert item.entities == [] and item.citations == []

    def test_impact_is_bounded(self):
        with pytest.raises(Exception):
            RiskItem(mechanism="m", impact=1.5)

    def test_citations_accept_int_and_string_forms(self):
        item = RiskItem(mechanism="m", citations=[1, "2", "[3]"])
        assert len(item.citations) == 3

    def test_structured_defaults_are_empty_not_fabricated(self):
        s = RiskStructured()
        assert s.overall == "" and s.risk_items == [] and s.confidence == 0.0

    def test_every_category_maps_to_a_real_riskprofile_field(self):
        for field in set(CATEGORY_TO_FIELD.values()):
            assert field in PROSE_FIELDS
            assert field in RiskProfile.model_fields


# ── Projection preserves the quality contract ────────────────────────────────

class TestProjectionQualityContract:
    def test_returns_a_real_riskprofile(self):
        assert isinstance(_project(), RiskProfile)

    def test_key_risks_present_and_company_specific(self):
        r = _project()
        assert len(r.key_risks) == 4
        assert all("MSFT" in k for k in r.key_risks)

    def test_every_numeric_anchor_survives(self):
        r = _project()
        blob = " ".join([r.debt_risk, r.competitive_risk, r.regulatory_risk,
                         r.concentration_risk, r.overall, " ".join(r.key_risks)])
        for figure in ("25%", "~29%", "20%", "$22.6B", "$25B", "$30B", "$28.5B"):
            assert figure in blob, figure

    def test_every_threshold_survives(self):
        r = _project()
        blob = r.debt_risk + r.competitive_risk + r.regulatory_risk
        assert "warning at 25%" in blob
        assert "bear case at 20%" in blob
        assert "warning at $25B" in blob

    def test_every_named_entity_survives(self):
        r = _project()
        blob = " ".join([r.debt_risk, r.competitive_risk, r.regulatory_risk,
                         r.concentration_risk])
        for entity in ("AWS", "Google Cloud", "Nvidia", "European Commission",
                       "OpenAI"):
            assert entity in blob, entity

    def test_every_citation_marker_survives(self):
        r = _project()
        blob = " ".join([r.debt_risk, r.competitive_risk, r.regulatory_risk,
                         r.concentration_risk])
        for marker in ("[2]", "[3]", "[5]", "[1]"):
            assert marker in blob, marker

    def test_causal_mechanism_survives(self):
        r = _project()
        assert "compresses the forward multiple" in r.competitive_risk
        assert "reduces FCF conversion" in r.debt_risk

    def test_confidence_is_carried_through(self):
        assert _project().confidence == 0.72

    def test_overall_is_carried_through_verbatim(self):
        assert _project().overall == _structured().overall

    def test_no_prose_field_is_an_empty_substitute(self):
        """Every category present in the items must yield non-empty prose."""
        r = _project()
        for field in PROSE_FIELDS:
            assert getattr(r, field).strip(), field

    def test_signals_are_bearish_risk_typed_and_capped(self):
        r = _project()
        assert len(r.signals) == 3          # control prompt asks for 2-3
        assert all(s.direction == "bearish" for s in r.signals)
        assert all(s.signal_type == "risk" for s in r.signals)
        assert all(s.source_agent == "risk" for s in r.signals)

    def test_signals_are_ordered_by_model_impact(self):
        scores = [s.impact_score for s in _project().signals]
        assert scores == sorted(scores, reverse=True)

    def test_claim_extraction_still_finds_anchors(self):
        """attach_agent_claims reads overall/debt_risk/concentration_risk plus
        signal text — the projection must leave figures in those fields."""
        from app.integrity.claim_extraction import attach_agent_claims
        r = _project()
        attach_agent_claims(r, ticker="MSFT", dimension="filing", metric="risk",
                            text_fields=("overall", "debt_risk",
                                         "concentration_risk"))
        assert r.quantitative_claims
        assert any(c.get("metric") == "risk" for c in r.quantitative_claims)

    def test_unmapped_category_still_reaches_key_risks(self):
        """An 'other' item has no prose field but must not vanish."""
        s = RiskStructured(overall="o", confidence=0.5, risk_items=[
            RiskItem(category="other", mechanism="Litigation outcome is binary"),
        ])
        r = _project(s)
        assert len(r.key_risks) == 1
        assert "Litigation outcome is binary" in r.key_risks[0]

    def test_item_without_metric_is_still_rendered(self):
        text = render_item(RiskItem(mechanism="Binary legal outcome"))
        assert "Binary legal outcome" in text

    def test_missing_threshold_is_not_fabricated(self):
        text = render_item(RiskItem(mechanism="m", metric="x", current_value="1%"))
        assert "warning at" not in text
        assert "bear case at" not in text


# ── Viability / fail-closed ──────────────────────────────────────────────────

class TestViability:
    def test_none_is_not_viable(self):
        assert projection_is_viable(None) is False

    def test_no_items_is_not_viable(self):
        assert projection_is_viable(
            RiskStructured(overall="o", confidence=0.5)) is False

    def test_items_without_mechanism_are_not_viable(self):
        assert projection_is_viable(RiskStructured(
            overall="o", confidence=0.5,
            risk_items=[RiskItem(category="debt", metric="x")])) is False

    def test_missing_overall_is_not_viable(self):
        assert projection_is_viable(RiskStructured(
            overall="", confidence=0.5,
            risk_items=[RiskItem(mechanism="m")])) is False

    def test_minimal_valid_structure_is_viable(self):
        assert projection_is_viable(RiskStructured(
            overall="o", confidence=0.5,
            risk_items=[RiskItem(mechanism="m")])) is True


# ── Prompt transform / one-variable isolation ────────────────────────────────

class TestPromptIsolation:
    def test_control_prompt_is_byte_identical(self):
        p = _control_prompt()
        assert apply_risk_variant(p, RISK_VARIANT_CONTROL) == p

    def test_struct_a_preserves_everything_before_the_output_section(self):
        """Framing, evidence and the analytical questions must be untouched —
        that is what makes this a representation experiment."""
        p = _control_prompt(question_intent="risk_assessment", question="Risks?")
        st = apply_risk_variant(p, RISK_VARIANT_STRUCT_A)
        head = p[:p.find("Produce a JSON object matching the RiskProfile schema")]
        assert st.startswith(head)
        assert "MSFT 10-K item 3" in st            # evidence block intact
        assert "leverage profile" in st            # analytical questions intact
        assert "QUESTION FOCUS" in st              # intent emphasis intact

    def test_struct_a_replaces_the_output_schema(self):
        st = apply_risk_variant(_control_prompt(), RISK_VARIANT_STRUCT_A)
        assert "risk_items" in st
        assert "matching the RiskProfile schema" not in st

    def test_struct_a_ends_on_the_same_json_cue(self):
        assert apply_risk_variant(_control_prompt(),
                                  RISK_VARIANT_STRUCT_A).endswith("JSON:")

    def test_struct_a_interpolates_the_ticker(self):
        st = apply_risk_variant(_control_prompt(), RISK_VARIANT_STRUCT_A)
        assert "MSFT revenue line" in st
        assert "{ticker}" not in st

    def test_struct_a_forbids_inventing_figures(self):
        st = apply_risk_variant(_control_prompt(), RISK_VARIANT_STRUCT_A)
        assert "Never invent a figure" in st

    def test_struct_a_requires_mechanism(self):
        st = apply_risk_variant(_control_prompt(), RISK_VARIANT_STRUCT_A)
        assert "mechanism" in st and "Required" in st

    def test_struct_a_requires_each_risk_stated_once(self):
        st = apply_risk_variant(_control_prompt(), RISK_VARIANT_STRUCT_A)
        assert "EXACTLY ONCE" in st

    def test_missing_marker_falls_back_to_control(self):
        """A restructured control prompt must not yield two output schemas."""
        assert apply_risk_variant("no marker here", RISK_VARIANT_STRUCT_A) == \
            "no marker here"

    def test_struct_a_is_registered_as_structured(self):
        assert RISK_VARIANT_STRUCT_A in STRUCTURED_RISK_VARIANTS
        assert RISK_VARIANT_CONTROL not in STRUCTURED_RISK_VARIANTS
        assert RISK_VARIANT_FAST_A not in STRUCTURED_RISK_VARIANTS


# ── Authorization ────────────────────────────────────────────────────────────

class TestAuthorization:
    def test_unauthorized_cannot_reach_struct_a(self):
        assert resolve_risk_variant("risk_struct_a", authorized=False) == \
            RISK_VARIANT_CONTROL

    def test_authorized_can_select_struct_a(self):
        assert resolve_risk_variant("risk_struct_a", authorized=True) == \
            RISK_VARIANT_STRUCT_A


# ── Agent integration ────────────────────────────────────────────────────────

def _run(payload, variant, ticker="MSFT"):
    """Run the agent against a stubbed client, returning (profile, calls, meta)."""
    from app.observability import set_risk_variant, start_trace

    class _Client:
        model = "gpt-4o-mini"
        calls = 0

        def call(self, prompt, **kw):
            _Client.calls += 1
            return payload

    original = risk_agent.model_client
    risk_agent.model_client = _Client()
    trace = start_trace("t")
    set_risk_variant(variant)
    try:
        profile = risk_agent.run_risk_agent(
            CompanyContext(ticker=ticker, company_name="Microsoft Corporation",
                           sector="T", industry="S", aliases=["Microsoft"]),
            _evidence(),
        )
    finally:
        set_risk_variant(RISK_VARIANT_CONTROL)
        risk_agent.model_client = original
    return profile, _Client.calls, trace.agent_meta


_STRUCT_PAYLOAD = json.dumps({
    "overall": "MSFT risk is capex execution [1].", "confidence": 0.72,
    "risk_items": [
        {"category": "competitive", "mechanism": "Azure below 25% compresses the multiple",
         "metric": "Azure growth", "current_value": "29%", "warning_threshold": "25%",
         "bear_threshold": "20%", "entities": ["AWS"], "citations": [2],
         "impact": 0.85, "horizon": "medium_term"},
        {"category": "debt", "mechanism": "capex cuts FCF conversion",
         "metric": "capex", "current_value": "$22.6B", "warning_threshold": "$25B",
         "bear_threshold": "", "entities": ["Nvidia"], "citations": [3],
         "impact": 0.70, "horizon": "short_term"},
    ],
})

_CONTROL_PAYLOAD = json.dumps({
    "debt_risk": "d", "competitive_risk": "c", "regulatory_risk": "r",
    "concentration_risk": "k", "key_risks": ["a", "b"], "overall": "o",
    "confidence": 0.7, "signals": [],
})


class TestAgentIntegration:
    def test_structured_path_makes_exactly_one_model_call(self):
        _, calls, _ = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        assert calls == 1

    def test_control_path_makes_exactly_one_model_call(self):
        _, calls, _ = _run(_CONTROL_PAYLOAD, RISK_VARIANT_CONTROL)
        assert calls == 1

    def test_control_path_is_unchanged_by_this_sprint(self):
        profile, _, meta = _run(_CONTROL_PAYLOAD, RISK_VARIANT_CONTROL)
        assert profile.debt_risk == "d" and profile.overall == "o"
        assert profile.key_risks == ["a", "b"]
        assert "risk_parse_ok" not in meta      # no structured flag on control

    def test_control_prompt_never_mentions_risk_items(self):
        """Proof the control call still asks for the RiskProfile schema."""
        seen = {}

        class _Client:
            model = "gpt-4o-mini"

            def call(self, prompt, **kw):
                seen["prompt"] = prompt
                return _CONTROL_PAYLOAD

        from app.observability import set_risk_variant
        original = risk_agent.model_client
        risk_agent.model_client = _Client()
        set_risk_variant(RISK_VARIANT_CONTROL)
        try:
            risk_agent.run_risk_agent(_company(), _evidence())
        finally:
            risk_agent.model_client = original
        assert "risk_items" not in seen["prompt"]
        assert "matching the RiskProfile schema" in seen["prompt"]

    def test_structured_output_is_projected_into_riskprofile(self):
        profile, _, _ = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        assert isinstance(profile, RiskProfile)
        assert profile.confidence == 0.72
        assert len(profile.key_risks) == 2
        assert "warning at 25%" in profile.competitive_risk
        assert "[3]" in profile.debt_risk

    def test_evidence_used_is_populated_on_the_structured_path(self):
        profile, _, _ = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        assert profile.evidence_used

    def test_claims_are_extracted_on_the_structured_path(self):
        profile, _, _ = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        assert profile.quantitative_claims

    @pytest.mark.parametrize("payload,label", [
        (json.dumps({"overall": "o", "confidence": 0.5, "risk_items": []}), "no items"),
        (json.dumps({"overall": "", "confidence": 0.5,
                     "risk_items": [{"mechanism": "m"}]}), "no overall"),
        (json.dumps({"overall": "o", "confidence": 0.5,
                     "risk_items": [{"category": "debt", "metric": "x"}]}), "no mechanism"),
        ("not json at all", "unparseable"),
    ])
    def test_unusable_output_degrades_rather_than_shipping_a_hollow_profile(
            self, payload, label):
        profile, calls, meta = _run(payload, RISK_VARIANT_STRUCT_A)
        assert calls == 1, "must not retry with a second call"
        assert profile.confidence == 0.0
        assert "Insufficient evidence" in profile.overall
        assert not profile.key_risks
        assert meta.get("risk_parse_ok") is False

    def test_parse_failure_never_fabricates_fields(self):
        profile, _, _ = _run("not json", RISK_VARIANT_STRUCT_A)
        for field in PROSE_FIELDS:
            assert getattr(profile, field) == ""


# ── Observability ────────────────────────────────────────────────────────────

class TestObservability:
    def test_structured_run_records_parse_and_sizes(self):
        _, _, meta = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        assert meta["risk_variant"] == RISK_VARIANT_STRUCT_A
        assert meta["risk_parse_ok"] is True
        assert meta["risk_item_total"] == 2
        assert meta["risk_projected_chars"] > 0
        assert meta["risk_projected_signals"] == 2
        assert meta["risk_projected_risk_lines"] == 2

    def test_no_prompt_text_in_observability(self):
        _, _, meta = _run(_STRUCT_PAYLOAD, RISK_VARIANT_STRUCT_A)
        blob = repr(meta)
        assert "risk_items" not in blob
        assert "Produce a JSON object" not in blob
        assert "EVIDENCE" not in blob

    def test_scrubber_still_rejects_key_named_metadata(self):
        """`risk_projected_key_risks` would be dropped ("key" is an unsafe
        marker); the count is exposed under a safe name instead."""
        from app.observability import RequestTrace
        t = RequestTrace("r")
        t.note_agent_meta(risk_projected_key_risks=3, risk_projected_risk_lines=3)
        assert "risk_projected_key_risks" not in t.agent_meta
        assert t.agent_meta["risk_projected_risk_lines"] == 3


# ── Comparator: parse failure invalidates ────────────────────────────────────

def _payload(risks, *, parse_ok=None, status="ok", variant="risk_struct_a"):
    obs = {"stages": [{"stage": "agent.risk", "status": status,
                       "duration_ms": 9000.0}],
           "risk_variant": variant}
    if parse_ok is not None:
        obs["agent_meta"] = {"risk_parse_ok": parse_ok}
    return {
        "company": "MSFT",
        "answer": {"investment_thesis": {
            "direct_answer": "a", "bull_thesis": "b",
            "bear_thesis": "Azure falls because capex rises",
            "valuation_view": "v", "conclusion": "c", "confidence": 0.7,
            "key_risks": risks, "catalysts": ["x"], "decision_thresholds": [],
            "quantitative_claims": [], "_integrity": {"ok": True, "status": "clean"},
        }},
        "_observability": obs,
    }


_GOOD = [{"risk": "MSFT Azure margin compresses because capex rises"}]


class TestComparatorParseGuard:
    def test_candidate_parse_failure_invalidates(self):
        from validation.ab_compare import compare_thesis, verdict
        v, reasons = verdict(compare_thesis(
            _payload(_GOOD, variant="risk_control"),
            _payload(_GOOD, parse_ok=False)))
        assert v == "invalid"
        assert any("failed to parse" in r for r in reasons)

    def test_control_parse_failure_invalidates(self):
        from validation.ab_compare import compare_thesis, verdict
        v, reasons = verdict(compare_thesis(
            _payload(_GOOD, parse_ok=False),
            _payload(_GOOD, parse_ok=True)))
        assert v == "invalid"
        assert any("control structured risk" in r for r in reasons)

    def test_successful_parse_compares_normally(self):
        from validation.ab_compare import compare_thesis, verdict
        v, _ = verdict(compare_thesis(
            _payload(_GOOD, variant="risk_control"),
            _payload(_GOOD, parse_ok=True)))
        assert v == "keep"

    def test_absent_parse_flag_is_not_a_failure(self):
        """Control runs and every pre-3B.4 artifact carry no flag."""
        from validation.ab_compare import risk_parse_ok
        assert risk_parse_ok(_payload(_GOOD, variant="risk_control")) is None
        assert risk_parse_ok({}) is None

    def test_parse_status_surfaces_in_the_report(self):
        from validation.ab_compare import ab_report_md
        md = ab_report_md({
            "control_dir": "c", "candidate_dir": "k", "compared": 1,
            "only_in_control": [], "only_in_candidate": [],
            "tally": {"keep": 0, "review": 0, "reject": 0, "invalid": 1},
            "pairs": [{"id": "MSFT-core_thesis", "verdict": "invalid",
                       "reasons": ["risk comparison invalid: candidate structured "
                                   "risk output failed to parse"],
                       "prose_ratio": None, "confidence_changed": False,
                       "confidence_control": 0.5, "confidence_candidate": 0.5,
                       "risk": {"risk_status_control": "ok",
                                "risk_status_candidate": "ok",
                                "risk_parse_ok_candidate": False}}],
        })
        assert "parse-fail" in md

    def test_timeout_guard_still_fires(self):
        """Sprint 3B.3.1 behaviour must survive this sprint."""
        from validation.ab_compare import compare_thesis, verdict
        v, reasons = verdict(compare_thesis(
            _payload(_GOOD, status="timeout", variant="risk_control"),
            _payload(_GOOD, parse_ok=True)))
        assert v == "invalid"
        assert any("timed out" in r for r in reasons)


# ── Regression locks ─────────────────────────────────────────────────────────

class TestRegressionLocks:
    EXPECTED = {"MSFT": "reject", "JPM": "review", "ASML": "review",
                "TSLA": "keep"}

    @pytest.mark.parametrize("ticker,expected", sorted(EXPECTED.items()))
    def test_sprint_3b2_verdicts_unchanged(self, ticker, expected):
        from pathlib import Path

        from validation.ab_compare import compare_runs
        control = Path(f"validation/runs/m2-control-{ticker}")
        candidate = Path(f"validation/runs/m2-fasta-{ticker}")
        if not (control.is_dir() and candidate.is_dir()):
            pytest.skip("live A/B artifacts not present in this checkout")
        assert compare_runs(control, candidate)["pairs"][0]["verdict"] == expected

    def test_nvda_remains_invalid_from_the_timeout_guard(self):
        from pathlib import Path

        from validation.ab_compare import compare_runs
        control = Path("validation/runs/m2-control-NVDA")
        candidate = Path("validation/runs/m2-fasta-NVDA")
        if not (control.is_dir() and candidate.is_dir()):
            pytest.skip("live A/B artifacts not present in this checkout")
        assert compare_runs(control, candidate)["pairs"][0]["verdict"] == "invalid"

    def test_other_agents_have_no_structured_hook(self):
        for mod in ("macro_agent", "market_agent", "quality_agent",
                    "valuation_agent"):
            m = __import__(f"app.investment_agents.{mod}", fromlist=[mod])
            src = inspect.getsource(m)
            assert "risk_structured" not in src
            assert "RiskStructured" not in src

    def test_structured_module_does_not_touch_synthesis_or_scoring(self):
        from app.investment_agents import risk_structured
        src = inspect.getsource(risk_structured)
        for forbidden in ("thesis_synthesizer", "conviction_modeler",
                          "signal_ranker", "synthesis_model_variants"):
            assert forbidden not in src

    def test_structured_path_uses_the_production_agent_client(self):
        """No model change: this sprint isolates representation only."""
        src = inspect.getsource(risk_agent)
        assert "ModelClient(" not in src
        assert "synthesis_client" not in src

    def test_riskprofile_contract_is_unchanged(self):
        assert {"debt_risk", "competitive_risk", "regulatory_risk",
                "concentration_risk", "key_risks", "overall", "confidence",
                "signals", "evidence_used", "quantitative_claims"} <= set(
                    RiskProfile.model_fields)
