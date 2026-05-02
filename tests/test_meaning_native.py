"""
Meaning-native inversion behavioral tests.

These tests verify that the INTERNAL DRIVER changed — not just that fields are present.

Key behavioral contracts:
    1. Two signals with similar counts but different outcome PATTERNS → different profiles
    2. Two signals with similar scalar weight but different profile_type → different handling
    3. Alerts differ when the same count pattern maps to different case archetypes
    4. Monitoring action can be derived from ContextualJudgment alone (no counts needed)
    5. Alert severity is driven by change_severity and archetype, not by count magnitude
"""
from __future__ import annotations


import pathlib as _pl_root_helper
_PROJECT_ROOT = str(_pl_root_helper.Path(__file__).resolve().parent.parent)

import types, sys, importlib.util

# -----------------------------------------------------------------------
# Shared package stub setup
# -----------------------------------------------------------------------
def _setup_stubs():
    import types as T

    def stub(name):
        if name in sys.modules:
            return sys.modules[name]
        m = T.ModuleType(name)
        m.__path__ = []
        m.__package__ = name.rsplit(".", 1)[0] if "." in name else name
        sys.modules[name] = m
        return m

    pydantic = stub("pydantic")

    class BaseModel:
        model_config = {}
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    pydantic.BaseModel = BaseModel
    pydantic.Field = lambda *a, **k: None

    app = stub("app"); app.__path__ = [f"{_PROJECT_ROOT}/app"]
    svc = stub("app.services"); svc.__path__ = [f"{_PROJECT_ROOT}/app/services"]
    dp  = stub("app.data_pipeline"); dp.__path__ = [f"{_PROJECT_ROOT}/app/data_pipeline"]

    for n in ["app.data_pipeline.schemas", "app.data_pipeline.ingestion",
              "app.data_pipeline.storage", "app.providers", "app.services.analysis_service"]:
        stub(n)

    schema_mod = stub("app.schemas")
    for cls_name in ["Alert", "ThesisChangeResult", "SynthesisOutput", "AlertInterpretation",
                     "SignalProfileModel", "MonitoringDecision", "GroundingContext", "AnalysisRequest"]:
        def _make(name):
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)
            return type(name, (), {"__init__": __init__, "model_config": {}})
        setattr(schema_mod, cls_name, _make(cls_name))

    sys.modules["app.data_pipeline.ingestion"].ingest_signals = lambda *a, **kw: None
    sys.modules["app.data_pipeline.storage"].query_records    = lambda *a, **kw: []

    def _ev(**kw):
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
        return type("EventRecord", (), {"__init__": __init__})(**kw)

    sys.modules["app.data_pipeline.schemas"].EventRecord = type(
        "EventRecord", (),
        {"__init__": lambda self, **kw: [setattr(self, k, v) for k, v in kw.items()]}
    )

    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.services"
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_setup_stubs()
_BASE = f"{_PROJECT_ROOT}/app/services/"
L  = _load("app.services.learning",           _BASE + "learning.py")
MS = _load("app.services.monitoring_service", _BASE + "monitoring_service.py")
AS = _load("app.services.alert_service",      _BASE + "alert_service.py")

NS = types.SimpleNamespace


# ===================================================================
# LEARNING: PATTERN-BASED PROFILE (not dominant count bucket)
# ===================================================================

class TestLearningPatternProfile:

    def test_same_total_different_pattern_different_profile(self):
        """Two signals with same total count but different patterns → different profiles.

        Signal A: thesis=5, alert=1  → thesis-driven (thesis dominates)
        Signal B: alert=5, thesis=1  → alert-driven  (alert dominates non-noise)

        If profile were still max-bucket, this would also pass.
        The REAL test is the pattern rule: thesis-driven requires thesis >= alert AND thesis >= noise.
        """
        L._signal_outcomes["__pa__"] = {"thesis_change": 5, "alert": 1, "noise": 0}
        L._signal_outcomes["__pb__"] = {"alert": 5, "thesis_change": 1, "noise": 0}
        rA = L.get_signal_profile("__pa__")
        rB = L.get_signal_profile("__pb__")
        assert rA["signal_profile"] == "thesis-driven",  f"A: {rA['signal_profile']}"
        assert rB["signal_profile"] == "alert-driven",   f"B: {rB['signal_profile']}"
        assert rA["signal_profile"] != rB["signal_profile"]

    def test_thesis_with_high_noise_not_thesis_driven(self):
        """If thesis_change exists but noise dominates, pattern → noise-driven not thesis-driven.

        Rule: thesis-driven requires thesis_change >= alert AND thesis_change >= noise.
        If noise > thesis_change, this fails Rule 1 and falls through.
        """
        L._signal_outcomes["__pc__"] = {"thesis_change": 2, "noise": 8, "alert": 1}
        rC = L.get_signal_profile("__pc__")
        # thesis=2 < noise=8, so Rule 1 fails; Rule 2: reanalysis=0 < alert=1 fails;
        # Rule 3: alert=1 > reanalysis=0, alert=1 > noise? No, noise=8. So Rule 3 fails.
        # Rule 4: noise-driven
        assert rC["signal_profile"] == "noise-driven", f"C: {rC['signal_profile']}"

    def test_reanalysis_driven_when_reanalysis_leads(self):
        """Reanalysis-driven when reanalysis > alert, reanalysis > noise, thesis minor."""
        L._signal_outcomes["__pd__"] = {"reanalysis": 7, "alert": 2, "thesis_change": 1, "noise": 0}
        rD = L.get_signal_profile("__pd__")
        # thesis=1, total=10, tc_ratio=0.10 < 0.20 → Rule 1 fails (thesis=1 < alert=2)
        # Rule 2: reanalysis=7 > alert=2 AND reanalysis=7 > noise=0 AND tc_ratio=0.10 < 0.20 → reanalysis-driven
        assert rD["signal_profile"] == "reanalysis-driven", f"D: {rD['signal_profile']}"

    def test_behavior_policy_comes_from_profile_not_count(self):
        """behavior_policy is read from canonical profile definition, not count arithmetic."""
        L._signal_outcomes["__pe__"] = {"thesis_change": 4, "alert": 1}
        rE = L.get_signal_profile("__pe__")
        assert rE["signal_profile"] == "thesis-driven"
        assert "highest priority" in rE["behavior_policy"]
        assert "thesis" in rE["behavior_policy"].lower()

    def test_escalation_tendency_is_profile_field_not_count(self):
        """escalation_tendency must be a field from SignalBehaviorProfile, not derived from counts."""
        L._signal_outcomes["__pf__"] = {"thesis_change": 3}
        rF = L.get_signal_profile("__pf__")
        assert "escalation_tendency" in rF
        assert rF["escalation_tendency"] == "high"   # thesis-driven → high escalation

    def test_suppression_rule_present_and_profile_specific(self):
        """suppression_rule must be present and differ across profiles."""
        L._signal_outcomes["__pg_thesis__"] = {"thesis_change": 5}
        L._signal_outcomes["__pg_noise__"]  = {"noise": 10}
        rT = L.get_signal_profile("__pg_thesis__")
        rN = L.get_signal_profile("__pg_noise__")
        assert "suppression_rule" in rT
        assert "suppression_rule" in rN
        assert rT["suppression_rule"] != rN["suppression_rule"]

    def test_same_scalar_weight_different_profile_different_policy(self):
        """Two signals with similar scalar weights but different profiles → different policies."""
        # Both have count=3, so weight ≈ 1.15 before profile factor.
        # But their outcome patterns are different.
        for sig in ["__wta__", "__wtb__"]:
            L._signal_memory[sig] = 3
        L._signal_outcomes["__wta__"] = {"thesis_change": 6}
        L._signal_outcomes["__wtb__"] = {"noise": 6}
        rA = L.get_signal_profile("__wta__")
        rB = L.get_signal_profile("__wtb__")
        assert rA["signal_profile"] == "thesis-driven"
        assert rB["signal_profile"] == "noise-driven"
        assert rA["behavior_policy"] != rB["behavior_policy"]


# ===================================================================
# MONITORING: CONTEXTUAL JUDGMENT DRIVES ACTION
# ===================================================================

class TestMonitoringContextualJudgment:

    def test_judgment_built_and_action_readable(self):
        """ContextualJudgment must be built and its recommended_action read."""
        profile = L._PROFILE_DEFINITIONS["thesis-driven"]
        ctx = {"is_cluster": True, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 4, "days_since_last": 10}
        j = MS._build_contextual_judgment("earnings", "big miss", profile, ctx)
        assert j.recommended_action is not None
        assert j.judgment_summary != ""
        assert j.situation_assessment != ""
        assert j.why_it_matters_now != ""
        assert j.pattern_role != ""

    def test_same_counts_different_profile_different_action(self):
        """Two events with identical temporal context but different profiles → different actions.

        This is the critical behavioral proof: it's the profile, not the counts.
        """
        ctx = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 1, "days_since_last": 14}

        j_thesis = MS._build_contextual_judgment(
            "earnings", "desc",
            L._PROFILE_DEFINITIONS["thesis-driven"], ctx
        )
        j_noise = MS._build_contextual_judgment(
            "earnings", "desc",
            L._PROFILE_DEFINITIONS["noise-driven"], ctx
        )
        assert j_thesis.recommended_action != j_noise.recommended_action, (
            f"Same counts, different profiles must produce different actions: "
            f"thesis={j_thesis.recommended_action}, noise={j_noise.recommended_action}"
        )
        assert j_noise.recommended_action == "record_signal_only"
        assert j_thesis.recommended_action in (
            "trigger_reanalysis", "trigger_reanalysis_and_thesis_compare"
        )

    def test_cluster_reinforcing_thesis_driven_escalates(self):
        """Cluster + thesis-driven + reinforcing → full reanalysis+thesis compare."""
        ctx = {"is_cluster": True, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 5, "days_since_last": 5}
        j = MS._build_contextual_judgment(
            "filing", "cluster thesis",
            L._PROFILE_DEFINITIONS["thesis-driven"], ctx
        )
        assert j.pattern_role == "reinforcing"
        assert j.recommended_action == "trigger_reanalysis_and_thesis_compare"

    def test_first_seen_thesis_driven_initiating_escalates(self):
        """First-seen + thesis-driven → initiating → trigger_reanalysis_and_thesis_compare."""
        ctx = {"is_cluster": False, "is_first_seen": True, "is_recurrent": False,
               "recent_count": 0, "days_since_last": None}
        j = MS._build_contextual_judgment(
            "macro_event", "novel",
            L._PROFILE_DEFINITIONS["thesis-driven"], ctx
        )
        assert j.pattern_role == "initiating"
        assert j.recommended_action == "trigger_reanalysis_and_thesis_compare"

    def test_noise_driven_always_record_only_regardless_of_context(self):
        """Noise-driven profile → record_signal_only regardless of cluster or novelty."""
        for ctx in [
            {"is_cluster": True,  "is_first_seen": False, "is_recurrent": False,
             "recent_count": 5, "days_since_last": 5},
            {"is_cluster": False, "is_first_seen": True,  "is_recurrent": False,
             "recent_count": 0, "days_since_last": None},
        ]:
            j = MS._build_contextual_judgment(
                "misc", "noise",
                L._PROFILE_DEFINITIONS["noise-driven"], ctx
            )
            assert j.recommended_action == "record_signal_only", (
                f"Noise-driven must always be record_signal_only, got {j.recommended_action}"
            )

    def test_alert_driven_isolated_generates_alert_not_reanalysis(self):
        """Alert-driven isolated (echoing) → generate_alert, not reanalysis."""
        ctx = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 1, "days_since_last": 10}
        j = MS._build_contextual_judgment(
            "news", "alert sig",
            L._PROFILE_DEFINITIONS["alert-driven"], ctx
        )
        assert j.recommended_action == "generate_alert", (
            f"Alert-driven isolated should generate_alert, got {j.recommended_action}"
        )

    def test_reanalysis_cluster_interrupting_escalates(self):
        """Reanalysis-driven + recurrent + cluster → reinforcing → escalate to thesis compare."""
        ctx = {"is_cluster": True, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 4, "days_since_last": 20}
        j = MS._build_contextual_judgment(
            "filing", "cluster reanalysis",
            L._PROFILE_DEFINITIONS["reanalysis-driven"], ctx
        )
        assert j.pattern_role == "reinforcing"
        assert j.recommended_action == "trigger_reanalysis_and_thesis_compare"


# ===================================================================
# ALERTS: HISTORICAL CASE MEANING DRIVES CONTENT
# ===================================================================

class TestAlertHistoricalCaseMeaning:

    def test_case_meaning_built_without_counts(self):
        """HistoricalCaseMeaning must be fully formed with empty supporting_evidence."""
        m = AS._build_historical_case_meaning(
            component        = "final_verdict",
            change_severity  = "high",
            change_summary   = "verdict changed",
            supporting_evidence = {},   # no counts
        )
        assert m.case_archetype     == "structural-thesis-shift"
        assert m.usual_meaning      != ""
        assert m.typical_consequence == "thesis_change"
        assert m.user_relevance     != ""
        assert m.meaning_summary    != ""

    def test_different_archetypes_different_case_meanings(self):
        """final_verdict and key_drivers have different archetypes → different meanings."""
        m_fv = AS._build_historical_case_meaning("final_verdict", "medium", "", {})
        m_kd = AS._build_historical_case_meaning("key_drivers",   "medium", "", {})
        assert m_fv.case_archetype     != m_kd.case_archetype
        assert m_fv.typical_consequence != m_kd.typical_consequence
        assert m_fv.usual_meaning      != m_kd.usual_meaning

    def test_escalation_role_from_high_severity_not_counts(self):
        """change_severity=high → current_case_role=escalation, regardless of outcome counts."""
        # Even with empty outcome_counts, high severity → escalation
        m = AS._build_historical_case_meaning("key_risks", "high", "", {})
        assert m.current_case_role == "escalation"

    def test_stabilization_role_from_low_severity_downside(self):
        """Downside component + low severity → stabilization (downside is easing)."""
        m = AS._build_historical_case_meaning("key_risks", "low", "", {})
        assert m.current_case_role == "stabilization"

    def test_escalation_drives_severity_high_regardless_of_archetype(self):
        """Case role=escalation always produces severity=high."""
        m = AS._build_historical_case_meaning("key_drivers", "high", "", {})
        assert m.current_case_role == "escalation"
        sev = AS._severity_from_case_meaning(m, None, "key_drivers")
        assert sev == "high", f"Escalation must produce high severity, got {sev}"

    def test_stabilization_reduces_severity(self):
        """Case role=stabilization must reduce severity below intrinsic."""
        m = AS._build_historical_case_meaning("key_risks", "low", "", {})
        assert m.current_case_role == "stabilization"
        sev = AS._severity_from_case_meaning(m, None, "key_risks")
        assert sev == "low", f"Stabilization should lower severity, got {sev}"

    def test_final_verdict_always_high_via_archetype(self):
        """final_verdict archetype → intrinsic high; escalation role makes it high too."""
        m = AS._build_historical_case_meaning("final_verdict", "medium", "", {})
        sev = AS._severity_from_case_meaning(m, None, "final_verdict")
        assert sev == "high", f"final_verdict must always be high, got {sev}"

    def test_same_count_different_archetype_different_alert(self):
        """Same outcome_counts, different component → different typical_consequence via archetype.

        This is the critical test: alert content must come from archetype, not from counts.
        """
        shared_evidence = {"outcome_counts": {"alert": 5, "reanalysis": 2}, "recent_signal_count": 3}

        m_fv = AS._build_historical_case_meaning("final_verdict", "medium", "", shared_evidence)
        m_kd = AS._build_historical_case_meaning("key_drivers",   "medium", "", shared_evidence)

        # Despite identical count evidence, archetypes produce different typical_consequences
        assert m_fv.typical_consequence == "thesis_change", f"final_verdict: {m_fv.typical_consequence}"
        assert m_kd.typical_consequence == "alert",         f"key_drivers: {m_kd.typical_consequence}"
        assert m_fv.typical_consequence != m_kd.typical_consequence

    def test_generate_alerts_produces_meaning_fields(self):
        """generate_alerts must populate case-meaning fields on returned alerts."""
        AS._collect_component_evidence = lambda c, scope=None: {"recent_signal_count": 0, "outcome_counts": {}}
        changes = NS(
            has_changed=True, changed_components=["final_verdict", "key_risks"],
            change_severity="medium", change_summary="test", impact_on_thesis="impact"
        )
        alerts = AS.generate_alerts(changes, NS())
        assert len(alerts) == 2

        for a in alerts:
            assert a.typical_outcome    is not None
            assert a.interpretive_summary != ""
            assert a.why_this_matters   is not None
            assert a.pattern_type       is not None   # current_case_role

    def test_high_severity_change_produces_high_alert_even_if_counts_are_zero(self):
        """High change_severity → escalation role → high severity alert, independent of counts."""
        AS._collect_component_evidence = lambda c, scope=None: {"recent_signal_count": 0, "outcome_counts": {}}
        changes = NS(
            has_changed=True, changed_components=["key_risks"],
            change_severity="high", change_summary="", impact_on_thesis=""
        )
        alerts = AS.generate_alerts(changes, NS())
        assert alerts and alerts[0].severity == "high", (
            f"High severity change must produce high severity alert, got {alerts[0].severity if alerts else 'no alerts'}"
        )

    def test_low_severity_downside_produces_low_alert(self):
        """Low severity downside component → stabilization → low severity alert."""
        AS._collect_component_evidence = lambda c, scope=None: {"recent_signal_count": 0, "outcome_counts": {}}
        changes = NS(
            has_changed=True, changed_components=["key_risks"],
            change_severity="low", change_summary="", impact_on_thesis=""
        )
        alerts = AS.generate_alerts(changes, NS())
        assert alerts and alerts[0].severity == "low", (
            f"Low severity downside stabilization must produce low severity, got {alerts[0].severity if alerts else 'no alerts'}"
        )


# ===================================================================
# CROSS-LAYER: END-TO-END MEANING CHAIN
# ===================================================================

class TestMeaningChainEndToEnd:

    def test_thesis_driven_signal_end_to_end_escalates(self):
        """thesis-driven profile → initiating context → reanalysis+thesis compare action."""
        L._signal_outcomes["__e2e_thesis_lc__"] = {"thesis_change": 8, "noise": 1}
        profile_data = L.get_signal_profile("__e2e_thesis_lc__")
        assert profile_data["signal_profile"] == "thesis-driven"

        ctx = {"is_cluster": False, "is_first_seen": True, "is_recurrent": False,
               "recent_count": 0, "days_since_last": None}
        judgment = MS._build_contextual_judgment(
            "earnings", "__e2e_thesis_lc__",
            profile_data["behavior_profile"], ctx
        )
        assert judgment.recommended_action == "trigger_reanalysis_and_thesis_compare"

    def test_noise_driven_never_escalates_regardless_of_alert_count(self):
        """Even if outcome_counts has many alerts, noise pattern → record_signal_only."""
        # This signal has many alert outcomes but noise dominates by pattern rule
        L._signal_outcomes["__e2e_noise_lc__"] = {"noise": 20, "alert": 2}
        profile_data = L.get_signal_profile("__e2e_noise_lc__")
        # noise=20 > alert=2, so Rule 1 fails (thesis=0), Rule 2 fails (reanalysis=0),
        # Rule 3: alert=2 > noise? No. → noise-driven
        assert profile_data["signal_profile"] == "noise-driven"

        ctx = {"is_cluster": True, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 5, "days_since_last": 5}
        judgment = MS._build_contextual_judgment(
            "misc", "__e2e_noise_lc__",
            profile_data["behavior_profile"], ctx
        )
        assert judgment.recommended_action == "record_signal_only"

    def test_alert_and_case_meaning_agree_on_thesis_change_for_final_verdict(self):
        """Alert for final_verdict must show thesis_change as typical_outcome via archetype."""
        m = AS._build_historical_case_meaning("final_verdict", "medium", "", {})
        assert m.typical_consequence == "thesis_change"
        assert m.case_archetype == "structural-thesis-shift"


if __name__ == "__main__":
    # Run inline without pytest
    suites = [
        TestLearningPatternProfile,
        TestMonitoringContextualJudgment,
        TestAlertHistoricalCaseMeaning,
        TestMeaningChainEndToEnd,
    ]
    passed = 0
    failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        for name in [n for n in dir(suite_cls) if n.startswith("test_")]:
            try:
                getattr(suite, name)()
                print(f"  PASS  {suite_cls.__name__}.{name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {suite_cls.__name__}.{name}: {e}")
                failed += 1
    print(f"\n{'='*60}")
    print(f"  {passed} passed, {failed} failed")
    if failed == 0:
        print("  ALL TESTS PASSED")
    print(f"{'='*60}")
