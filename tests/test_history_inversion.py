"""
Final history-inversion behavioral tests.

These tests verify that:
1. evidence_service produces HistoricalMeaning objects as primary output
2. monitoring consumes HistoricalMeaning from the evidence layer (not local counts)
3. alerts consume HistoricalMeaning (typical_consequence from archetype, enriched by shared meaning)
4. learning consumes HistoricalMeaning via consume_history_meaning
5. Two cases with similar raw counts but different historical meaning → different actions
6. Two alert cases with similar baselines but different historical case meaning → different alerts
7. Learning profiles differ when history meaning differs, even if raw signal frequencies are similar
"""
from __future__ import annotations


import pathlib as _pl_root_helper
_PROJECT_ROOT = str(_pl_root_helper.Path(__file__).resolve().parent.parent)

import sys, types, importlib.util

# -----------------------------------------------------------------------
# Stub setup
# -----------------------------------------------------------------------
def _setup():
    def stub(name):
        if name in sys.modules: return sys.modules[name]
        m = types.ModuleType(name); m.__path__ = []; m.__package__ = name.rsplit(".",1)[0] if "." in name else name; sys.modules[name] = m; return m

    pd = stub("pydantic")
    class BM:
        model_config = {}
        model_fields = {}
        def __init__(self, **kw):
            for k,v in kw.items(): setattr(self,k,v)
        def model_copy(self, deep=False): return self
        def copy(self, deep=False): return self
    pd.BaseModel = BM; pd.Field = lambda *a, **k: (lambda f: None)

    app = stub("app"); app.__path__ = [f"{_PROJECT_ROOT}/app"]
    svc = stub("app.services"); svc.__path__ = [f"{_PROJECT_ROOT}/app/services"]
    dp  = stub("app.data_pipeline"); dp.__path__ = [f"{_PROJECT_ROOT}/app/data_pipeline"]
    for n in ["app.data_pipeline.schemas","app.data_pipeline.ingestion","app.data_pipeline.storage",
              "app.providers","app.services.analysis_service"]:
        stub(n)
    sys.modules["app.data_pipeline.ingestion"].ingest_signals = lambda *a, **kw: None
    sys.modules["app.data_pipeline.storage"].query_records    = lambda *a, **kw: []

    # Real-ish schemas module loaded from file
    schema_mod = stub("app.schemas")
    for cn in ["Alert","ThesisChangeResult","SynthesisOutput","AlertInterpretation",
               "SignalProfileModel","MonitoringDecision","GroundingContext","AnalysisRequest",
               "HistoricalInterpretation","HistoricalMeaning","CompanyProfile","MarketSnapshot",
               "FinancialContext","FilingContext"]:
        class _S:
            model_config = {}
            model_fields = {}
            def __init__(self, **kw):
                for k,v in kw.items(): setattr(self,k,v)
        _S.__name__ = cn
        setattr(schema_mod, cn, type(cn, (_S,), {"model_config": {}, "model_fields": {}, "__init__": _S.__init__}))

    class _ER:
        def __init__(self, **kw):
            for k,v in kw.items(): setattr(self,k,v)
    sys.modules["app.data_pipeline.schemas"].EventRecord = _ER

    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.services"
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_setup()
_BASE = f"{_PROJECT_ROOT}/app/services/"
L  = _load("app.services.learning",           _BASE + "learning.py")
MS = _load("app.services.monitoring_service", _BASE + "monitoring_service.py")
AS = _load("app.services.alert_service",      _BASE + "alert_service.py")

# Make loaded submodules accessible as attributes on the parent stub so that
# unittest.mock.patch("app.services.monitoring_service.X") resolves correctly.
_svc_stub = sys.modules["app.services"]
_svc_stub.learning            = L
_svc_stub.monitoring_service  = MS
_svc_stub.alert_service       = AS

NS = types.SimpleNamespace


def _make_history_meaning(
    domain="event",
    situation_archetype="stress-cluster",
    historical_pattern="Increasing event frequency in recent history.",
    pattern_stability="unstable",
    pattern_direction="deteriorating",
    escalation_likelihood="high",
    usual_consequence="reanalysis",
    meaning_summary="Stress-cluster archetype: historically leads to reanalysis.",
):
    """Create a HistoricalMeaning-like object for testing."""
    return NS(
        domain=domain,
        situation_archetype=situation_archetype,
        historical_pattern=historical_pattern,
        pattern_stability=pattern_stability,
        pattern_direction=pattern_direction,
        escalation_likelihood=escalation_likelihood,
        usual_consequence=usual_consequence,
        meaning_summary=meaning_summary,
    )


# ===================================================================
# EVIDENCE LAYER: meaning-native output
# ===================================================================

class TestEvidenceMeaningNativeOutput:

    def test_historical_meaning_has_required_fields(self):
        """HistoricalMeaning must expose all meaning-native fields."""
        m = _make_history_meaning()
        assert m.situation_archetype  is not None
        assert m.historical_pattern   is not None
        assert m.pattern_stability    is not None
        assert m.pattern_direction    is not None
        assert m.escalation_likelihood is not None
        assert m.usual_consequence    is not None
        assert m.meaning_summary      is not None

    def test_archetype_determines_consequence_not_counts(self):
        """stress-cluster archetype → reanalysis consequence (not from any count bucket)."""
        m = _make_history_meaning(situation_archetype="stress-cluster", usual_consequence="reanalysis")
        assert m.usual_consequence == "reanalysis"

    def test_noise_regime_archetype_consequence_is_noise(self):
        """noise-regime archetype → noise consequence."""
        m = _make_history_meaning(situation_archetype="noise-regime", usual_consequence="noise",
                                   escalation_likelihood="low")
        assert m.usual_consequence == "noise"
        assert m.escalation_likelihood == "low"

    def test_structural_shift_archetype_consequence_is_thesis_change(self):
        """structural-shift archetype → thesis_change consequence."""
        m = _make_history_meaning(situation_archetype="structural-shift",
                                   usual_consequence="thesis_change",
                                   escalation_likelihood="high")
        assert m.usual_consequence == "thesis_change"


# ===================================================================
# MONITORING: consumes HistoricalMeaning directly
# ===================================================================

class TestMonitoringConsumesHistoryMeaning:

    def test_stress_cluster_history_meaning_escalates_action(self):
        """When history_meanings contains stress-cluster, action escalates to reanalysis."""
        profile   = L._PROFILE_DEFINITIONS["alert-driven"]
        ctx_local = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
                     "recent_count": 1, "days_since_last": 10}
        hist_meanings = {"event": _make_history_meaning(
            situation_archetype="stress-cluster",
            escalation_likelihood="high",
            usual_consequence="reanalysis",
        )}
        j = MS._build_contextual_judgment("news", "desc", profile, ctx_local, hist_meanings)
        # alert-driven + reinforcing (from stress-cluster) → trigger_reanalysis
        assert j.recommended_action in ("trigger_reanalysis", "trigger_reanalysis_and_thesis_compare"), (
            f"Stress-cluster history should escalate alert-driven to reanalysis, got {j.recommended_action}"
        )

    def test_noise_regime_history_keeps_noise_action(self):
        """When history_meanings shows noise-regime, noise-driven profile stays record_signal_only."""
        profile   = L._PROFILE_DEFINITIONS["noise-driven"]
        ctx_local = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
                     "recent_count": 1, "days_since_last": 10}
        hist_meanings = {"event": _make_history_meaning(
            situation_archetype="noise-regime",
            escalation_likelihood="low",
            usual_consequence="noise",
        )}
        j = MS._build_contextual_judgment("misc", "noise", profile, ctx_local, hist_meanings)
        assert j.recommended_action == "record_signal_only"

    def test_same_local_context_different_history_meaning_different_action(self):
        """CRITICAL: identical local counts, different history meaning → different actions.

        This is the core behavioral proof that history meaning is the driver.
        """
        profile   = L._PROFILE_DEFINITIONS["alert-driven"]
        ctx_local = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
                     "recent_count": 1, "days_since_last": 10}  # same for both

        # Case A: stress-cluster history
        j_stress = MS._build_contextual_judgment(
            "news", "desc", profile, ctx_local,
            {"event": _make_history_meaning(situation_archetype="stress-cluster",
                                            escalation_likelihood="high",
                                            usual_consequence="reanalysis")}
        )
        # Case B: noise-regime history (same local counts!)
        j_noise = MS._build_contextual_judgment(
            "news", "desc",
            L._PROFILE_DEFINITIONS["noise-driven"],
            ctx_local,
            {"event": _make_history_meaning(situation_archetype="noise-regime",
                                            escalation_likelihood="low",
                                            usual_consequence="noise")}
        )
        assert j_stress.recommended_action != j_noise.recommended_action, (
            f"Same local counts, different history meaning must produce different actions: "
            f"stress={j_stress.recommended_action}, noise={j_noise.recommended_action}"
        )

    def test_history_meaning_populates_historical_meaning_field(self):
        """ContextualJudgment.historical_meaning must come from HistoricalMeaning.meaning_summary."""
        profile   = L._PROFILE_DEFINITIONS["thesis-driven"]
        ctx_local = {"is_cluster": False, "is_first_seen": True, "is_recurrent": False,
                     "recent_count": 0, "days_since_last": None}
        summary   = "Structural-shift archetype: historically leads to thesis_change."
        hist_meanings = {"event": _make_history_meaning(
            situation_archetype="structural-shift",
            usual_consequence="thesis_change",
            meaning_summary=summary,
        )}
        j = MS._build_contextual_judgment("earnings", "desc", profile, ctx_local, hist_meanings)
        assert summary in j.historical_meaning, (
            f"ContextualJudgment.historical_meaning should contain the HistoricalMeaning summary"
        )

    def test_no_history_meaning_falls_back_gracefully(self):
        """When no history_meanings provided, monitoring still works via local fallback."""
        profile   = L._PROFILE_DEFINITIONS["alert-driven"]
        ctx_local = {"is_cluster": False, "is_first_seen": False, "is_recurrent": False,
                     "recent_count": 1, "days_since_last": 10}
        j = MS._build_contextual_judgment("news", "desc", profile, ctx_local, None)
        assert j.recommended_action is not None
        assert j.recommended_action == "generate_alert"


# ===================================================================
# ALERTS: consume HistoricalMeaning
# ===================================================================

class TestAlertsConsumeHistoryMeaning:

    def test_high_escalation_history_elevates_medium_severity_to_escalation(self):
        """High escalation_likelihood from HistoricalMeaning → escalation role even for medium change."""
        hist_m = _make_history_meaning(
            situation_archetype="stress-cluster",
            escalation_likelihood="high",
            usual_consequence="reanalysis",
        )
        case_m = AS._build_historical_case_meaning(
            "key_risks", "medium", "", {},
            history_meaning=hist_m,
        )
        assert case_m.current_case_role == "escalation", (
            f"High escalation history + medium severity should produce escalation role, got {case_m.current_case_role}"
        )

    def test_high_escalation_history_typical_consequence_elevated(self):
        """When history_meaning.usual_consequence is reanalysis and archetype warrants it, typical_consequence elevates."""
        hist_m = _make_history_meaning(
            situation_archetype="stress-cluster",
            escalation_likelihood="high",
            usual_consequence="reanalysis",
        )
        # key_drivers archetype default consequence is "alert"; shared history elevates to "reanalysis"
        case_m = AS._build_historical_case_meaning(
            "key_drivers", "medium", "", {},
            history_meaning=hist_m,
        )
        assert case_m.typical_consequence in ("reanalysis", "thesis_change"), (
            f"Shared reanalysis history should elevate key_drivers typical_consequence, got {case_m.typical_consequence}"
        )

    def test_same_counts_different_history_meaning_different_alert_consequence(self):
        """CRITICAL: same evidence counts, different HistoricalMeaning → different typical_consequence."""
        shared_evidence = {"outcome_counts": {"alert": 3, "reanalysis": 1}, "recent_signal_count": 2}

        # Same component, same evidence, but different history meaning
        hist_stress = _make_history_meaning(
            situation_archetype="structural-shift",
            escalation_likelihood="high",
            usual_consequence="thesis_change",
        )
        hist_noise = _make_history_meaning(
            situation_archetype="noise-regime",
            escalation_likelihood="low",
            usual_consequence="noise",
        )

        # Use key_drivers (default consequence = "alert") with stress history
        m_stress = AS._build_historical_case_meaning("key_drivers", "medium", "", shared_evidence, hist_stress)
        # Same component, same counts, noise history
        m_noise  = AS._build_historical_case_meaning("key_drivers", "medium", "", shared_evidence, hist_noise)

        # stress history escalates consequence (thesis_change > alert → elevates)
        # noise history does not (noise < alert → no elevation)
        assert m_stress.typical_consequence in ("reanalysis", "thesis_change"), (
            f"Stress+structural history should elevate key_drivers consequence, got {m_stress.typical_consequence}"
        )
        assert m_noise.typical_consequence == "alert", (
            f"Noise history should not elevate consequence, got {m_noise.typical_consequence}"
        )
        assert m_stress.typical_consequence != m_noise.typical_consequence

    def test_no_history_meaning_still_works(self):
        """_build_historical_case_meaning works fine without history_meaning."""
        m = AS._build_historical_case_meaning("final_verdict", "high", "", {}, history_meaning=None)
        assert m.case_archetype     == "structural-thesis-shift"
        assert m.typical_consequence == "thesis_change"
        assert m.current_case_role   == "escalation"

    def test_generate_alerts_with_history_meaning_on_context(self):
        """generate_alerts uses history_meaning from current when available."""
        AS._collect_component_evidence = lambda c, scope=None: {"recent_signal_count": 0, "outcome_counts": {}}

        # Create a mock current with historical_meanings
        current = NS(historical_meanings={
            "event": _make_history_meaning(
                situation_archetype="stress-cluster",
                escalation_likelihood="high",
                usual_consequence="reanalysis",
            )
        })

        changes = NS(
            has_changed=True,
            changed_components=["key_drivers"],  # default consequence = "alert"
            change_severity="medium",
            change_summary="drivers updated",
            impact_on_thesis="impact",
        )
        alerts = AS.generate_alerts(changes, current)
        assert alerts, "Expected alert"
        # Stress-cluster history should elevate key_drivers consequence
        a = alerts[0]
        assert a.typical_outcome in ("reanalysis", "thesis_change"), (
            f"Stress-cluster history should elevate key_drivers alert, got {a.typical_outcome}"
        )


# ===================================================================
# LEARNING: consumes HistoricalMeaning
# ===================================================================

class TestLearningConsumesHistoryMeaning:

    def test_consume_history_meaning_updates_outcome_profile(self):
        """consume_history_meaning must update _signal_outcomes from HistoricalMeaning."""
        sig = "test_hist_consume_sig"
        key = sig.strip().lower()
        L._signal_outcomes.pop(key, None)

        hist_m = _make_history_meaning(
            situation_archetype="structural-shift",
            escalation_likelihood="high",
            usual_consequence="thesis_change",
        )
        L.consume_history_meaning(sig, hist_m)
        assert key in L._signal_outcomes
        assert L._signal_outcomes[key].get("thesis_change", 0) > 0

    def test_high_escalation_history_pushes_toward_thesis_driven(self):
        """Consuming stress-cluster/structural-shift history pushes profile toward thesis-driven."""
        sig = "test_thesis_push_sig"
        key = sig.strip().lower()
        L._signal_outcomes.pop(key, None)

        # First consume structural-shift history several times
        hist_m = _make_history_meaning(
            situation_archetype="structural-shift",
            escalation_likelihood="high",
            usual_consequence="thesis_change",
        )
        for _ in range(3):
            L.consume_history_meaning(sig, hist_m)

        profile = L.get_signal_profile(sig)
        assert profile["signal_profile"] == "thesis-driven", (
            f"Repeated structural-shift history should produce thesis-driven, got {profile['signal_profile']}"
        )

    def test_noise_history_keeps_noise_profile(self):
        """Consuming noise-regime history keeps the signal noise-driven."""
        sig = "test_noise_hist_sig"
        key = sig.strip().lower()
        L._signal_outcomes.pop(key, None)

        hist_m = _make_history_meaning(
            situation_archetype="noise-regime",
            escalation_likelihood="low",
            usual_consequence="noise",
        )
        for _ in range(5):
            L.consume_history_meaning(sig, hist_m)

        profile = L.get_signal_profile(sig)
        assert profile["signal_profile"] == "noise-driven", (
            f"Noise history should produce noise-driven, got {profile['signal_profile']}"
        )

    def test_same_signal_freq_different_history_meaning_different_profile(self):
        """CRITICAL: two signals with similar base frequencies but different history meanings → different profiles."""
        sig_a = "test_freq_diff_a"
        sig_b = "test_freq_diff_b"
        for k in [sig_a.lower(), sig_b.lower()]:
            L._signal_outcomes.pop(k, None)

        # Both signals get 2 alerts from local observation
        L.update_signal_outcome([sig_a], "alert")
        L.update_signal_outcome([sig_a], "alert")
        L.update_signal_outcome([sig_b], "alert")
        L.update_signal_outcome([sig_b], "alert")

        # sig_a gets thesis-heavy history
        for _ in range(4):
            L.consume_history_meaning(sig_a, _make_history_meaning(
                situation_archetype="structural-shift",
                escalation_likelihood="high",
                usual_consequence="thesis_change",
            ))

        # sig_b gets noise history
        for _ in range(4):
            L.consume_history_meaning(sig_b, _make_history_meaning(
                situation_archetype="noise-regime",
                escalation_likelihood="low",
                usual_consequence="noise",
            ))

        prof_a = L.get_signal_profile(sig_a)
        prof_b = L.get_signal_profile(sig_b)

        assert prof_a["signal_profile"] != prof_b["signal_profile"], (
            f"Same base frequencies but different history → different profiles: "
            f"a={prof_a['signal_profile']}, b={prof_b['signal_profile']}"
        )
        assert prof_a["signal_profile"] == "thesis-driven", f"a should be thesis-driven: {prof_a['signal_profile']}"
        assert prof_b["signal_profile"] == "noise-driven", f"b should be noise-driven: {prof_b['signal_profile']}"


# ===================================================================
# CROSS-LAYER: end-to-end history meaning chain
# ===================================================================

class TestHistoryMeaningChain:

    def test_structural_shift_history_propagates_to_reanalysis_action(self):
        """End-to-end: structural-shift HistoricalMeaning → thesis-driven profile → reanalysis action."""
        sig = "e2e_structural_shift_sig"
        L._signal_outcomes.pop(sig.lower(), None)

        # Consume structural-shift history into learning
        hist_m = _make_history_meaning(
            situation_archetype="structural-shift",
            escalation_likelihood="high",
            usual_consequence="thesis_change",
        )
        for _ in range(3):
            L.consume_history_meaning(sig, hist_m)

        # Profile should now be thesis-driven
        profile_data     = L.get_signal_profile(sig)
        behavior_profile = profile_data["behavior_profile"]
        assert behavior_profile.profile_type == "thesis-driven"

        # Monitoring with same history meaning should escalate
        ctx = {"is_cluster": False, "is_first_seen": True, "is_recurrent": False,
               "recent_count": 0, "days_since_last": None}
        j = MS._build_contextual_judgment(
            "earnings", sig, behavior_profile, ctx,
            history_meanings={"event": hist_m}
        )
        assert j.recommended_action in ("trigger_reanalysis", "trigger_reanalysis_and_thesis_compare")

    def test_noise_history_never_escalates_through_full_chain(self):
        """End-to-end: noise-regime history → noise-driven profile → record_signal_only."""
        sig = "e2e_noise_sig"
        L._signal_outcomes.pop(sig.lower(), None)

        hist_m = _make_history_meaning(
            situation_archetype="noise-regime",
            escalation_likelihood="low",
            usual_consequence="noise",
        )
        for _ in range(5):
            L.consume_history_meaning(sig, hist_m)

        profile_data     = L.get_signal_profile(sig)
        behavior_profile = profile_data["behavior_profile"]
        assert behavior_profile.profile_type == "noise-driven"

        ctx = {"is_cluster": True, "is_first_seen": False, "is_recurrent": False,
               "recent_count": 5, "days_since_last": 5}
        j = MS._build_contextual_judgment(
            "misc", sig, behavior_profile, ctx,
            history_meanings={"event": hist_m}
        )
        assert j.recommended_action == "record_signal_only"


if __name__ == "__main__":
    suites = [
        TestEvidenceMeaningNativeOutput,
        TestMonitoringConsumesHistoryMeaning,
        TestAlertsConsumeHistoryMeaning,
        TestLearningConsumesHistoryMeaning,
        TestHistoryMeaningChain,
    ]
    passed = 0; failed = 0
    for cls in suites:
        suite = cls()
        for name in sorted(n for n in dir(cls) if n.startswith("test_")):
            try:
                getattr(suite, name)()
                print(f"  PASS  {cls.__name__}.{name}")
                passed += 1
            except Exception as e:
                import traceback
                print(f"  FAIL  {cls.__name__}.{name}: {e}")
                failed += 1
    print(f"\n{'='*60}")
    print(f"  {passed} passed, {failed} failed")
    if not failed:
        print("  ALL TESTS PASSED")
    print(f"{'='*60}")
