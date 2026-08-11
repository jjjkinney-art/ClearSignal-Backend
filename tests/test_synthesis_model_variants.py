"""Sprint 3B.2 — synthesis-model A/B variants.

Prompt reduction is closed (compact_a and compact_a2 failed the live quality
gate; compact_schema_a reached only 0.27%). This sprint isolates MODEL CHOICE
and nothing else. Fully offline: no network, no LLM.
"""
from __future__ import annotations

import pytest

from app import observability as obs
from app.model_client import synthesis_client
from app.services.synthesis_model_variants import (
    KNOWN_MODEL_VARIANTS, MODEL_VARIANT_CONTROL, MODEL_VARIANT_FAST_A,
    client_for_variant, configured_model_for_variant, describe_variant,
    resolve_model_variant,
)
from app.services.synthesis_prompt_variants import (
    VARIANT_CONTROL, apply_variant, resolve_variant,
)
from app.services.thesis_synthesizer import _synthesis_client_for_request
from validation.runner import (
    SYNTHESIS_MODEL_VARIANT_HEADER, SYNTHESIS_VARIANT_HEADER,
    build_arg_parser, build_ask_headers,
)

CANDIDATE = "gpt-4o-mini-candidate-for-test"


@pytest.fixture(autouse=True)
def _clean():
    obs.set_trace(None)
    obs.set_prompt_variant(VARIANT_CONTROL)
    obs.set_model_variant(MODEL_VARIANT_CONTROL)
    yield
    obs.set_trace(None)
    obs.set_prompt_variant(VARIANT_CONTROL)
    obs.set_model_variant(MODEL_VARIANT_CONTROL)


@pytest.fixture
def configured(monkeypatch):
    """A deployment that has named a fast_a candidate model."""
    from app.config import settings
    monkeypatch.setattr(settings, "synthesis_model_fast_a", CANDIDATE,
                        raising=False)
    import app.services.synthesis_model_variants as smv
    monkeypatch.setattr(smv, "_CLIENT_CACHE", {}, raising=False)
    return CANDIDATE


@pytest.fixture
def unconfigured(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "synthesis_model_fast_a", "", raising=False)


# ── Control must be provably unchanged ───────────────────────────────────────

class TestControlUnchanged:
    def test_control_returns_the_production_client_object(self):
        # Identity, not equality: the default path is literally the current
        # production object, so it cannot have drifted.
        assert client_for_variant(MODEL_VARIANT_CONTROL) is synthesis_client

    def test_request_path_defaults_to_production_client(self):
        assert _synthesis_client_for_request() is synthesis_client

    def test_control_reports_the_production_model(self):
        assert configured_model_for_variant(MODEL_VARIANT_CONTROL) == \
               synthesis_client.model

    def test_unknown_variant_returns_production_client(self):
        for name in ("nonsense", "", None, "fast_z"):
            assert client_for_variant(name) is synthesis_client


# ── Only the model changes ───────────────────────────────────────────────────

class TestOnlyModelChanges:
    def test_fast_a_uses_the_configured_model(self, configured):
        client = client_for_variant(MODEL_VARIANT_FAST_A)
        assert client.model == CANDIDATE
        assert client is not synthesis_client

    @pytest.mark.parametrize("attr", [
        "temperature", "max_tokens", "timeout", "max_retries", "backoff_factor",
    ])
    def test_every_other_setting_matches_production(self, configured, attr):
        """The experiment must isolate model capability, not also change the
        token budget, timeout or retry behavior."""
        candidate = client_for_variant(MODEL_VARIANT_FAST_A)
        assert getattr(candidate, attr) == getattr(synthesis_client, attr)

    def test_client_is_cached_per_variant(self, configured):
        assert client_for_variant(MODEL_VARIANT_FAST_A) is \
               client_for_variant(MODEL_VARIANT_FAST_A)

    def test_prompt_is_byte_identical_across_model_variants(self):
        """A model variant must never touch the prompt."""
        prompt = "Required JSON fields:\n\nMANDATORY block\n\nEVIDENCE"
        obs.set_model_variant(MODEL_VARIANT_CONTROL)
        a = apply_variant(prompt, obs.current_prompt_variant())
        obs.set_model_variant(MODEL_VARIANT_FAST_A)
        b = apply_variant(prompt, obs.current_prompt_variant())
        assert a == b == prompt

    def test_model_variant_does_not_change_prompt_variant(self):
        obs.set_model_variant(MODEL_VARIANT_FAST_A)
        assert obs.current_prompt_variant() == VARIANT_CONTROL

    def test_prompt_variant_does_not_change_model_variant(self):
        obs.set_prompt_variant("compact_a")
        assert obs.current_model_variant() == MODEL_VARIANT_CONTROL


# ── Authorization ────────────────────────────────────────────────────────────

class TestAuthorization:
    def test_unauthorized_always_gets_control(self, configured):
        for requested in ("fast_a", "control", "garbage", None):
            assert resolve_model_variant(requested, authorized=False) == \
                   MODEL_VARIANT_CONTROL

    def test_authorized_can_select_fast_a(self, configured):
        assert resolve_model_variant("fast_a", authorized=True) == \
               MODEL_VARIANT_FAST_A

    def test_case_insensitive(self, configured):
        assert resolve_model_variant("FAST_A", authorized=True) == \
               MODEL_VARIANT_FAST_A

    def test_unknown_name_falls_back_to_control(self, configured):
        assert resolve_model_variant("fast_z", authorized=True) == \
               MODEL_VARIANT_CONTROL

    def test_unconfigured_deployment_refuses_the_variant(self, unconfigured):
        """No model configured => the variant cannot be selected at all, even
        by an authorized caller."""
        assert resolve_model_variant("fast_a", authorized=True) == \
               MODEL_VARIANT_CONTROL

    def test_unconfigured_variant_still_serves_production_model(self, unconfigured):
        obs.set_model_variant(MODEL_VARIANT_FAST_A)
        assert _synthesis_client_for_request() is synthesis_client

    def test_all_known_variants_resolve(self, configured):
        for v in KNOWN_MODEL_VARIANTS:
            assert resolve_model_variant(v, authorized=True) == v

    def test_variant_propagates_across_a_thread(self, configured):
        from concurrent.futures import ThreadPoolExecutor
        obs.set_model_variant(MODEL_VARIANT_FAST_A)
        seen = {}

        def _worker():
            seen["v"] = obs.current_model_variant()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(obs.bind(_worker)).result()
        assert seen["v"] == MODEL_VARIANT_FAST_A


# ── Observability ────────────────────────────────────────────────────────────

class TestObservability:
    def test_control_description(self):
        d = describe_variant(MODEL_VARIANT_CONTROL)
        assert d["synthesis_model_variant"] == "control"
        assert d["synthesis_model"] == synthesis_client.model
        assert d["synthesis_provider"] == "openai"

    def test_fast_a_description_reports_candidate_model(self, configured):
        d = describe_variant(MODEL_VARIANT_FAST_A)
        assert d["synthesis_model_variant"] == "fast_a"
        assert d["synthesis_model"] == CANDIDATE

    def test_description_carries_no_prompt_text(self, configured):
        import json
        serialized = json.dumps(describe_variant(MODEL_VARIANT_FAST_A))
        for fragment in ("MANDATORY", "Required JSON fields", "You are a"):
            assert fragment not in serialized

    def test_header_name_matches_backend(self):
        assert SYNTHESIS_MODEL_VARIANT_HEADER == obs.MODEL_VARIANT_HEADER

    def test_model_call_records_the_variant_model(self):
        """Token/duration accounting flows through the existing Sprint 3A
        model-call recorder, which reports whichever model actually ran.

        Uses a keyless client so the assertion is made entirely offline — a
        test must never reach the provider.
        """
        from app.model_client import ModelClient
        trace = obs.start_trace("req12345")
        keyless = ModelClient(api_key="", model=CANDIDATE, temperature=0.0,
                              max_tokens=16)
        with pytest.raises(RuntimeError):     # keyless => fails before any call
            keyless.call("prompt", stage="synthesis")
        assert trace.model_calls
        assert trace.model_calls[0]["model"] == CANDIDATE
        assert trace.model_calls[0]["stage"] == "synthesis"


# ── Runner plumbing ──────────────────────────────────────────────────────────

class TestRunnerPlumbing:
    def test_ordinary_run_sends_no_model_variant_header(self):
        assert SYNTHESIS_MODEL_VARIANT_HEADER not in build_ask_headers()

    def test_model_variant_requires_the_profiling_token(self):
        headers = build_ask_headers(synthesis_model_variant="fast_a")
        assert SYNTHESIS_MODEL_VARIANT_HEADER not in headers

    def test_model_variant_sent_with_token(self):
        headers = build_ask_headers(profile_token="S",
                                    synthesis_model_variant="fast_a")
        assert headers[SYNTHESIS_MODEL_VARIANT_HEADER] == "fast_a"

    def test_model_variant_is_independent_of_prompt_variant(self):
        """A model experiment must not implicitly send a prompt variant."""
        headers = build_ask_headers(profile_token="S",
                                    synthesis_model_variant="fast_a")
        assert SYNTHESIS_VARIANT_HEADER not in headers

    def test_both_variants_can_be_sent_independently(self):
        headers = build_ask_headers(profile_token="S",
                                    synthesis_variant="control",
                                    synthesis_model_variant="fast_a")
        assert headers[SYNTHESIS_VARIANT_HEADER] == "control"
        assert headers[SYNTHESIS_MODEL_VARIANT_HEADER] == "fast_a"

    def test_cli_flag_defaults_empty(self):
        assert build_arg_parser().parse_args([]).synthesis_model_variant == ""

    def test_cli_flag_accepts_variant(self):
        args = build_arg_parser().parse_args(["--synthesis-model-variant", "fast_a"])
        assert args.synthesis_model_variant == "fast_a"

    def test_cli_flags_are_separate(self):
        args = build_arg_parser().parse_args([
            "--synthesis-variant", "control",
            "--synthesis-model-variant", "fast_a",
        ])
        assert args.synthesis_variant == "control"
        assert args.synthesis_model_variant == "fast_a"


# ── No behavior change elsewhere ─────────────────────────────────────────────

class TestNoOtherBehaviorChange:
    def test_no_extra_model_call_introduced(self):
        import inspect
        import app.services.synthesis_model_variants as smv
        src = inspect.getsource(smv)
        # The module builds clients; it must never itself invoke one.
        assert ".call(" not in src
        assert "chat.completions" not in src

    def test_resolution_is_deterministic(self, configured):
        results = {resolve_model_variant("fast_a", authorized=True)
                   for _ in range(10)}
        assert len(results) == 1

    def test_agent_model_is_untouched(self, configured):
        """The shared agent client must keep its own model even while a
        synthesis model variant is active."""
        from app.config import settings
        from app.model_client import model_client as agent_client
        assert agent_client.model == settings.agent_model
        assert agent_client is not client_for_variant(MODEL_VARIANT_FAST_A)

    def test_prompt_variants_still_work(self):
        prompt = "A\n\nWRITING RHYTHM AND CADENCE VARIATION — MANDATORY:\n- x\n\nB"
        assert apply_variant(prompt, "control") == prompt
        assert resolve_variant("compact_a", authorized=False) == VARIANT_CONTROL

    def test_client_builder_never_raises(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "synthesis_model_fast_a", CANDIDATE,
                            raising=False)
        import app.services.synthesis_model_variants as smv
        monkeypatch.setattr(smv, "_CLIENT_CACHE", {}, raising=False)

        def _boom(*a, **k):
            raise RuntimeError("cannot build")

        monkeypatch.setattr("app.model_client.ModelClient", _boom)
        assert client_for_variant(MODEL_VARIANT_FAST_A) is synthesis_client


# ── Sprint 3B.2 (verified candidate) ─────────────────────────────────────────

VERIFIED_FAST_A = "gpt-4.1-nano-2025-04-14"


class TestVerifiedCandidate:
    """The candidate was chosen by enumerating this API project's models and
    probing parameter compatibility, not by reading the repository."""

    def test_default_fast_a_is_the_verified_candidate(self):
        from app.config import settings
        assert settings.synthesis_model_fast_a == VERIFIED_FAST_A

    def test_fast_a_resolves_to_the_verified_model(self):
        assert configured_model_for_variant(MODEL_VARIANT_FAST_A) == VERIFIED_FAST_A

    def test_fast_a_client_uses_the_verified_model(self):
        assert client_for_variant(MODEL_VARIANT_FAST_A).model == VERIFIED_FAST_A

    def test_candidate_is_pinned_to_a_dated_snapshot(self):
        # A floating alias would make an A/B result unreproducible once the
        # alias moves.
        import re
        assert re.search(r"-\d{4}-\d{2}-\d{2}$", VERIFIED_FAST_A)

    def test_candidate_is_not_a_reasoning_model(self):
        """gpt-5 tiers reject max_tokens and need max_completion_tokens, which
        would stop the experiment isolating model choice."""
        assert not VERIFIED_FAST_A.startswith("gpt-5")
        assert not VERIFIED_FAST_A.startswith(("o1", "o3", "o4"))

    def test_control_is_still_gpt_4o_mini(self):
        from app.config import settings
        assert settings.synthesis_model == "gpt-4o-mini"
        assert synthesis_client.model == "gpt-4o-mini"

    def test_control_and_candidate_are_different_models(self):
        assert configured_model_for_variant(MODEL_VARIANT_CONTROL) != \
               configured_model_for_variant(MODEL_VARIANT_FAST_A)

    def test_candidate_shares_every_non_model_setting(self):
        candidate = client_for_variant(MODEL_VARIANT_FAST_A)
        for attr in ("temperature", "max_tokens", "timeout", "max_retries",
                     "backoff_factor"):
            assert getattr(candidate, attr) == getattr(synthesis_client, attr)

    def test_public_traffic_still_gets_control(self):
        assert resolve_model_variant("fast_a", authorized=False) == \
               MODEL_VARIANT_CONTROL

    def test_operator_can_still_disable_the_variant(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "synthesis_model_fast_a", "", raising=False)
        assert resolve_model_variant("fast_a", authorized=True) == \
               MODEL_VARIANT_CONTROL

    def test_operator_override_is_honoured(self, monkeypatch):
        from app.config import settings
        import app.services.synthesis_model_variants as smv
        monkeypatch.setattr(settings, "synthesis_model_fast_a", "gpt-4.1-mini",
                            raising=False)
        monkeypatch.setattr(smv, "_CLIENT_CACHE", {}, raising=False)
        assert configured_model_for_variant(MODEL_VARIANT_FAST_A) == "gpt-4.1-mini"

    def test_observability_reports_the_verified_model(self):
        d = describe_variant(MODEL_VARIANT_FAST_A)
        assert d["synthesis_model"] == VERIFIED_FAST_A
        assert d["synthesis_model_variant"] == "fast_a"
