"""
Configuration management for the AI analyst backend.

This module defines a ``Settings`` class using Pydantic's
``BaseSettings`` to load environment variables. It exposes a
singleton ``settings`` instance that can be imported across
the codebase. All configurable values (such as API keys and
model settings) should be defined here.
"""

# Pydantic version 2 moved BaseSettings to the pydantic_settings package. To
# maintain compatibility with both v1 and v2 of Pydantic, attempt to
# import BaseSettings from pydantic_settings first, then fall back to
# pydantic.BaseSettings if pydantic_settings is not available.
try:
    from pydantic_settings import BaseSettings  # type: ignore
except ImportError:  # pragma: no cover - handled in older versions
    from pydantic import BaseSettings  # type: ignore

# Attempt to import ConfigDict for pydantic v2 support.  Declare a
# module‑level _CONFIG_DICT so that it is not interpreted as a model field
# inside the Settings class.  When ConfigDict is unavailable (v1), this
# variable will be None.
try:  # pragma: no cover
    from pydantic import ConfigDict  # type: ignore
    _CONFIG_DICT = ConfigDict(env_file=".env", env_file_encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _CONFIG_DICT = None  # type: ignore[assignment]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes
    ----------
    openai_api_key : str
        Secret API key for authenticating requests to the OpenAI API. This
        field has a default empty string so that the ``Settings`` instance
        can be created without requiring the environment variable during
        testing. In production you should set ``OPENAI_API_KEY`` in a
        ``.env`` file or environment.
    openai_model : str
        Chat model to use when querying OpenAI (defaults to GPT‑3.5 Turbo).
    max_tokens : int
        Maximum number of tokens to request from the model.
    temperature : float
        Temperature parameter controlling randomness of model outputs.
    """

    openai_api_key: str = ""

    # Model used by the investment agents and general chat.
    openai_model: str = "gpt-4o"

    # Model used by the 5 specialist investment agents (valuation, macro, risk,
    # market, quality) + the Q-First question-answerer agent.  Defaults to
    # gpt-4o-mini to keep the 6 parallel agent calls well under the Render
    # free-tier Nginx 61-second proxy_read_timeout ceiling.  Override via
    # AGENT_MODEL in the environment when higher reasoning depth is needed.
    agent_model: str = "gpt-4o-mini"

    # Timeout for individual investment agent calls (seconds).
    # Investment agents receive large evidence-rich prompts but generate compact
    # structured outputs (~200-500 tokens).  gpt-4o-mini at worst-case 30 tok/s
    # takes 7-17s.  A 15s timeout covers 95%+ of agent calls under normal load
    # while ensuring agent wall time never exceeds 15s even in the worst case.
    # When an agent times out, it falls back to its safe default (empty model).
    # Pipeline budget: evidence(10s) + agents(15s) + synthesis(30s) + post(3s) = 58s.
    agent_timeout: float = 15.0

    # Retries for individual investment agent calls.  With agent_timeout=15s,
    # retrying is catastrophic: 3 retries × 15s = 45s per agent.  Set to 1
    # (no retry on timeout).  Agent failures fall back to safe defaults and
    # synthesis continues with the available agent outputs.
    agent_max_retries: int = 1

    # Model used exclusively by the thesis synthesiser.  Defaults to a
    # faster, cheaper model; override via SYNTHESIS_MODEL in the environment
    # or .env file when higher capability is required.
    synthesis_model: str = "gpt-4o-mini"

    max_tokens: int = 4096

    # Maximum output tokens for the thesis synthesis call.  Set lower than
    # max_tokens to keep synthesis output concise and reduce generation time.
    # The full InvestmentThesis JSON requires ~1,100 tokens minimum; 1536 gives
    # a comfortable buffer so all 22+ fields are fully populated at quality.
    # On Render Starter (120s proxy_read_timeout), synthesis_timeout=55s means
    # gpt-4o-mini at 30 tok/s worst case: TTFT(12) + 1536/30 = 63s → fits in 55s
    # budget at typical load (45 tok/s: 8 + 34 = 42s).
    # Override via SYNTHESIS_MAX_TOKENS if richer synthesis is needed.
    synthesis_max_tokens: int = 1536

    temperature: float = 0.0

    # Enable or disable retrieval of external data for grounding.  When
    # enabled, the context enrichment process will call third‑party APIs
    # (e.g., FMP and SEC EDGAR) to obtain real financial metrics and recent
    # filings.  Defaults to False to avoid external calls unless explicitly
    # requested.
    enable_data_retrieval: bool = False

    # Optional API key for Financial Modeling Prep.  When provided and
    # ``enable_data_retrieval`` is True, the backend will include this
    # key when calling FMP to access financial statement data.  Leave
    # empty to perform unauthenticated requests (subject to rate limits).
    fmp_api_key: str = ""

    # Optional API key for the St. Louis Fed FRED API.  When set, the
    # general finance evidence layer (app/services/general_finance_evidence.py)
    # will fetch live macro data (Treasury yields, CPI, Fed funds rate, etc.)
    # and inject it into the LLM prompt as grounding context.  Leave empty
    # to fall back to conceptual reasoning only — /api/ask continues to work
    # without this key.
    fred_api_key: str = ""

    # User agent string for SEC EDGAR requests.  The SEC requires that
    # programmatic requests identify the caller and include a contact
    # email.  Customize this value when enabling data retrieval.
    sec_user_agent: str = ""

    # Optional path to a custom system prompt file.  If provided, this path
    # will be used to load the system prompt instead of the default
    # ``system_prompt.txt`` in the ``app`` directory.  The file should
    # contain plain text.  Leave empty to use the default prompt.
    system_prompt_file: str = ""

    # Model timeout in seconds.  Controls how long to wait for the OpenAI
    # API to respond before giving up.  The model client uses this value.
    model_timeout: float = 30.0

    # Synthesis-specific timeout.  On Render Starter (120s proxy_read_timeout),
    # synthesis can safely run 55s.  With synthesis_max_tokens=1536 and gpt-4o-mini
    # at typical 45 tok/s: TTFT(8) + 1536/45 = 42s — fits cleanly in 55s.
    # At worst-case 30 tok/s load: TTFT(12) + 1536/30 = 63s → synthesis_timeout
    # fires at 55s; fallback returned.  ~95% of requests complete within 55s.
    # Python-side wall cap (_SYNTHESIS_WALL_CAP_S=56) fires 1s after httpx.
    # Pipeline budget: evidence(≤10s) + agents(≤16s) + synthesis(≤56s) + post(≤0.5s) = ≤82.5s
    # Well inside Render Starter's 120s proxy_read_timeout.
    synthesis_timeout: float = 55.0

    # Maximum retries for the synthesis call.  Unlike agent calls (max_retries=3),
    # synthesis retries are catastrophic: a single retry adds 35s and pushes the
    # total pipeline over Render's 61s Nginx ceiling.  Set to 1 (no retry on
    # timeout).  When synthesis is slow and times out, the pipeline returns a
    # fallback thesis immediately rather than retrying and timing out Nginx.
    synthesis_max_retries: int = 1

    # Maximum number of retries for model calls.  Each failed attempt will
    # trigger an exponential backoff before retrying.  This value is
    # consumed by the model client.
    model_max_retries: int = 3

    # Backoff factor used to compute delay between retries: delay =
    # ``backoff_factor * 2 ** (attempt - 1)``.  Tune this to adjust
    # responsiveness versus aggressiveness when encountering API errors.
    model_backoff_factor: float = 0.5

    # Enable or disable enterprise hardening features.  When True, the
    # observability, audit, and provider governance layers are active.
    enterprise_mode: bool = False

    # Audit database path.  Used by AuditStore when enterprise_mode is True.
    # Leave empty to use the default "audit.db" in the working directory.
    audit_db_path: str = ""

    # Provider cache TTL in seconds.  Controls how long provider API responses
    # are cached in the in-process response cache.
    provider_cache_ttl_s: float = 300.0

    # History cache TTL in seconds.
    history_cache_ttl_s: float = 120.0

    # Circuit breaker failure threshold: how many consecutive provider
    # failures before the circuit opens.
    circuit_failure_threshold: int = 5

    # Circuit breaker cooldown in seconds before half-open probe.
    circuit_cooldown_s: float = 60.0

    # ── Phase 10A — Continuous Intelligence Loop ─────────────────────────────
    # Drift gate: when True (default), tick() consults should_run_job() before
    # dispatching any producer.  Jobs are skipped (skipped_stale) if no material
    # substrate change has occurred since the last successful run.
    # Set LOOP_DRIFT_GATE_ENABLED=false to disable (all jobs run every tick).
    loop_drift_gate_enabled: bool = True

    # Force-run override: when True, all jobs bypass the drift gate this tick.
    # Also honoured per-job via payload_json.force_run=true.
    # Intended for admin reruns and tests; never set True in production.
    loop_force_run: bool = False

    # Minimum materiality score required to trigger a job run.
    # Signals below this score are treated as non-material and the job is skipped.
    # Range: 0.0–1.0.  Default 0.4 keeps TickerMemory-only updates (score=0.3)
    # below the bar while passing any DossierRevision or moderate+ ThesisDelta.
    loop_drift_materiality_min: float = 0.4
    # Master gate: when False, loop_scheduler_service.tick() is a no-op and no
    # jobs are claimed, dispatched, or delivered.  Set LOOP_ENABLED=true in the
    # environment to activate (default: off / inert until explicitly enabled).
    loop_enabled: bool = False

    # Shadow mode: when True (default), producers run but no real delivery
    # occurs.  All outputs are written to the delivery ledger with
    # status=delivered_shadow.  Set LOOP_SHADOW=false to activate real delivery
    # (not available until Slice 10+).
    loop_shadow: bool = True

    # Canary rollout percentage (0–95).  Fraction of sessions/users that
    # receive the loop output.  0 = effectively off even when enabled=True.
    # Capped at 95 to preserve the permanent 5% holdout.
    loop_canary_pct: int = 0

    # When True, only users listed in LOOP_INTERNAL_USER_IDS receive loop
    # output regardless of canary_pct.  Allows alpha testing with a named set
    # of internal users before public canary.
    loop_internal_only: bool = True

    # Comma-separated list of user_ids treated as "internal".  These always
    # receive COHORT_INTERNAL regardless of canary_pct.
    loop_internal_user_ids: str = ""

    # Number of due jobs claimed per tick.
    loop_tick_batch_size: int = 10

    # Job lease duration in seconds.  A job's lock expires after this many
    # seconds if the holder crashes mid-execution; the next tick reaps it.
    loop_lock_lease_s: int = 120

    # Seconds before retrying a failed job (base; Slice 5 may add backoff).
    loop_retry_backoff_s: int = 300

    # ── Phase 10A · Slice 8 — Delivery guardrails ────────────────────────────
    # Quiet hours: suppress deliveries between start (inclusive) and end
    # (exclusive) UTC hour.  Default: 22:00–07:00 (overnight).
    delivery_quiet_hours_start: int = 22
    delivery_quiet_hours_end:   int = 7

    # Max deliveries per channel per target_key per UTC calendar day.
    # Rows beyond this count are suppressed (status=suppressed).
    delivery_daily_cap: int = 20

    # Minimum severity for delivery.  Payloads with a severity field below
    # this level are suppressed at enqueue time.
    # Values (ascending): info | warning | alert | critical
    delivery_severity_floor: str = "info"

    # ── Phase 10C · Slice 9 — In-app delivery channel activation ─────────────
    # Master gate for real in-app Notification creation.
    # False (default) = all delivery remains shadow-only; no Notification rows
    # are ever written by the in-app flusher.
    # Set DELIVERY_IN_APP_ENABLED=true to allow Notification creation (still
    # gated by DELIVERY_SHADOW and DELIVERY_INTERNAL_ONLY below).
    delivery_in_app_enabled: bool = False

    # Shadow mode for the in-app channel.  When True (default), flush_in_app()
    # behaves identically to flush_pending_shadow() — ledger rows are marked
    # delivered_shadow and no Notification rows are written.
    # Set DELIVERY_SHADOW=false only after delivery_in_app_enabled=true is
    # confirmed safe in internal validation.
    delivery_shadow: bool = True

    # Restrict real in-app delivery to users listed in loop_internal_user_ids.
    # True (default) = only internal user_ids receive real Notification rows.
    # False = canary rollout via delivery_canary_pct.
    delivery_internal_only: bool = True

    # Canary rollout percentage for real in-app delivery (0–95).
    # Only effective when delivery_internal_only=False.
    # 0 (default) = effectively off even when delivery_in_app_enabled=True.
    delivery_canary_pct: int = 0

    # ── Phase 10B · Slice 2 — Watchlist DB-backed membership ─────────────────
    # When True, the /watchlist read/add/remove endpoints route through the
    # DB-backed async membership path (WatchedTicker + watchlist_repo) instead
    # of the JSON-file index, giving persistence across restarts and horizontal
    # scale.  When False (default), the endpoints use the existing JSON-file
    # path, preserving current single-instance behaviour exactly.  The async
    # path dual-writes the file index and falls back to it when the DB is empty
    # or unavailable, so enabling this is backward-compatible and failure-open.
    watchlist_db_backed: bool = False

    # ── Phase 9A: Persistence layer ───────────────────────────────────────────
    # SQLAlchemy async database URL.  Supports two drivers:
    #   asyncpg  — postgresql+asyncpg://user:pass@host/db    (Render production)
    #   aiosqlite — sqlite+aiosqlite:///./dev.db             (local development)
    #
    # When empty, the persistence layer is disabled via a null-object pattern —
    # all persistence calls become no-ops so the API continues to work without
    # a database configured.  Set DATABASE_URL in your .env or Render environment
    # to enable persistence.
    database_url: str = ""

    # ── Phase 9G · Phase 0 — Company Dossier ─────────────────────────────────
    # Enable post-dispatch dossier extraction.  When True, each successful
    # /ask synthesis triggers a fire-and-forget task that harvests signals from
    # the InvestmentThesis and writes them to the dossier facet tables.
    # Defaults to False — set DOSSIER_EXTRACTION_ENABLED=true in the
    # environment or .env to activate.  Injection remains off until Slice 5.
    dossier_extraction_enabled: bool = False

    # ── Slice 5 — Dossier injection (pre-synthesis read path) ────────────────
    # Slice 5A SHADOW: build + measure the injection block but NEVER attach it
    # to the synthesis prompt (zero output change).  Validates budget / decay /
    # relevance against real production dossiers with no synthesis risk.
    dossier_injection_shadow: bool = False
    # Slice 5B LIVE: attach the block to the synthesis prompt (default off —
    # not used in Slice 5A; declared here so 5B needs no further config change).
    dossier_injection_enabled: bool = False
    # Sticky per-session canary percentage for the 5B live rollout (0 =
    # effectively off even when enabled=True).  Unused in 5A.
    dossier_injection_canary_pct: int = 0
    # Whether the demoted prior_state line is included (re-review Decision 1 —
    # staging A/B toggles this).  Default demote/include.
    dossier_injection_include_prior_state: bool = True

    # ── Phase 17 · Slice 3 — Stripe & Checkout ───────────────────────────────
    # Master Stripe toggle.  When False (default throughout all Phase 17 build
    # slices), no outbound Stripe API calls are made and the checkout route
    # returns a safe disabled response.  Flip to True only after all Stripe
    # config values are set in the Render environment.
    stripe_enabled: bool = False

    # Stripe secret key — set via Render env or .env (NEVER commit).
    # Only read when stripe_enabled=True.
    stripe_secret_key: str = ""

    # Stripe Price IDs — must be configured before stripe_enabled=True.
    stripe_price_signal_monthly: str = ""    # Signal (pro) monthly price
    stripe_price_signal_yearly: str = ""     # Signal (pro) annual price
    stripe_price_syndicate_monthly: str = "" # Syndicate (teams) monthly price

    # Checkout redirect URLs.  Required when stripe_enabled=True.
    # Example: "https://app.clearsignal.io/billing/success"
    stripe_success_url: str = ""
    stripe_cancel_url: str = ""

    # Stripe webhook signing secret — set via Render env (whsec_...).
    # Required when stripe_enabled=True and the webhook endpoint is live.
    # NEVER commit this value.
    stripe_webhook_secret: str = ""

    # Stripe billing portal return URL — where the portal sends users back.
    # Example: "https://app.clearsignal.io/billing"
    stripe_portal_return_url: str = ""

    # ── Phase 17 · Slice 6 — Entitlement Enforcement ─────────────────────────
    # Master enforcement toggle.  When False (default throughout all Phase 17
    # build slices), every entitlement check is a no-op — zero behavior change.
    # Flip to True only after billing is live and the subscription table is
    # populated via Stripe webhooks.
    entitlements_enforced: bool = False

    # ── Phase 16 · Slice 3 — Accounts & Auth ─────────────────────────────────
    # Master enforcement toggle.  When False (default throughout all Phase 16
    # build slices), every request resolves to the system user identity and
    # no JWT is ever validated — the bypass that keeps all pre-16 flows
    # working while the identity stack is built.  Flip to True only in the
    # staged rollout sequence described in docs/PHASE_16_ACCOUNTS_ROLLOUT.md.
    auth_enabled: bool = False

    # Supabase project URL.  Used to derive the JWKS endpoint when RS256
    # verification is enabled.  Leave empty to use HS256 with supabase_jwt_secret.
    # Example: "https://xyzabcde.supabase.co"
    supabase_project_url: str = ""

    # Supabase JWT secret (HS256 verification).  Found in your Supabase project
    # dashboard under Project Settings → API → JWT Settings.
    # Never commit this value; set via Render env or .env (git-ignored).
    supabase_jwt_secret: str = ""

    # Expected JWT audience claim.  Supabase issues "authenticated" for signed-in
    # users and "anon" for the anon key.  Only "authenticated" tokens carry a
    # valid user identity.
    supabase_audience: str = "authenticated"

    # The system user UUID that the bypass injects as request.state.user_id.
    # Must match SYSTEM_DEFAULT_USER_ID in system_user_service / account_repo.
    # Override only in tests.
    auth_bypass_user_id: str = "00000000-0000-0000-0000-000000000001"

    # ── Phase 11 — Similarity Engine ─────────────────────────────────────────
    # Master gate for similarity feature-vector / edge construction. When
    # False (default through Slice 5), invalidation/rebuild functions are
    # still callable directly (for tests and manual ops) but no automatic
    # loop producer or scheduled job builds similarity artifacts.
    similarity_build_enabled: bool = False

    # Master gate for similarity scoring (edge generation). When False
    # (default), no automatic scoring pass runs. Independent of
    # similarity_build_enabled so feature vectors can be built without
    # edges being generated.
    similarity_scoring_enabled: bool = False

    # Comma-separated list of active similarity target_types (e.g.
    # "failure_mode,company,thesis"). Empty (default) = no target is
    # considered enabled for automatic rebuild, even if the other flags
    # above are True.
    similarity_targets_enabled: str = ""

    # Shadow mode: when True (default), similarity artifacts may be built/
    # rebuilt but are never surfaced to any user-visible path. Mirrors the
    # loop_shadow / delivery_shadow convention — flip only after Slice 9+
    # delivery work (out of scope through Slice 5).
    similarity_shadow: bool = True

    # ── Phase 12 — Forecasting Engine ────────────────────────────────────────
    # Master gate for automatic feature-vector builds. When False (default),
    # no automatic loop producer or scheduled job builds forecast artifacts.
    # The builders are still directly callable for tests and manual ops.
    forecast_build_enabled: bool = False

    # Master gate for automatic probability scoring. When False (default),
    # no automatic scoring pass runs. Independent of forecast_build_enabled
    # so feature vectors can be built without edges being generated.
    forecast_scoring_enabled: bool = False

    # Master gate for live delivery of forecast transitions. When False
    # (default throughout all Phase 12 build slices), no live Notification
    # rows are ever written for forecast events. Never set True in Phase 12.
    forecast_delivery_enabled: bool = False

    # Shadow mode for forecast delivery. When True (default), transition
    # events are journaled into delivery_ledger(channel="forecast_shadow")
    # only — no flush pipeline drains that channel, no Notification is
    # ever created.  All three of forecast_build_enabled,
    # forecast_scoring_enabled, and forecast_shadow must be True for
    # shadow journaling to activate.
    forecast_shadow: bool = True

    # Comma-separated allowlist of entity_types considered "active" for
    # future automatic rebuild scheduling. Empty (default) means no target
    # is automatically active even if other flags are True.
    forecast_targets_enabled: str = ""

    # Master gate for calibration outcome logging and Brier-score computation.
    # When False (default), detect_outcomes() is a no-op and no
    # forecast_calibration_log rows are written.
    forecast_calibration_enabled: bool = False

    # ── Phase 13 — Decision Intelligence ─────────────────────────────────────
    # Decision Intelligence PRIORITIZES information; it never recommends a buy,
    # sell, position size, trade, or target price (spec §0). All six flags
    # default inert: with build/scoring off and delivery off (shadow true),
    # no priority is ever built and no surface is ever reordered.

    # Master gate for assembling attention candidates and building priorities.
    # When False (default), no automatic producer builds decision_priority rows.
    decision_build_enabled: bool = False

    # Master gate for computing component & composite ranking scores. When False
    # (default), no automatic scoring pass runs.
    decision_scoring_enabled: bool = False

    # Master gate for allowing rankings to reorder/promote real delivery
    # surfaces (inbox, alerts, briefings, watchlists, portfolio). When False
    # (default throughout the Phase 13 build phase), no user-visible surface is
    # ever reordered. Never set True before the post-build Stage 4 sign-off.
    decision_delivery_enabled: bool = False

    # Shadow mode for decision ranking. When True (default), rankings are
    # journaled to decision_ranking_log only — no surface reads them, no
    # Notification is created. decision_scoring_enabled and decision_shadow must
    # both be True for shadow journaling to activate (Phase 13 Slice 8).
    decision_shadow: bool = True

    # Comma-separated allowlist of entity_types eligible for automatic priority
    # builds. Empty (default) means no candidate is eligible even if other flags
    # are True.
    decision_targets_enabled: str = ""

    # Master gate for ranking-outcome logging and drift metrics (rank-order
    # agreement, churn, false prominence, missed importance). When False
    # (default), no decision_ranking_log outcome rows are written (Phase 13
    # Slice 9).
    decision_calibration_enabled: bool = False

    # ── Phase 14 — Scenario Engine ────────────────────────────────────────────
    # The Scenario Engine answers "What happens if X changes?" — it produces
    # conditional analyses, NOT predictions and NOT recommendations (spec §0 /
    # SP-6). All six flags default inert: with build/scoring off and delivery off
    # (shadow true), no scenario is ever built and no surface is ever changed.

    # Master gate for assembling scenario seeds and building snapshots.
    # When False (default), no automatic producer builds scenario_snapshot rows.
    scenario_build_enabled: bool = False

    # Master gate for running transmission/impact evaluation. When False
    # (default), no automatic evaluation pass runs. Independent of
    # scenario_build_enabled so seeds can be built without triggering evaluation.
    scenario_scoring_enabled: bool = False

    # Master gate for allowing scenarios to surface on real delivery surfaces.
    # When False (default throughout the Phase 14 build phase), no user-visible
    # surface is ever changed. Never set True before the post-build Stage 4
    # sign-off.
    scenario_delivery_enabled: bool = False

    # Shadow mode for scenario surfacing. When True (default), surfaced sets are
    # journaled to scenario_run_log only — no surface reads them, no Notification
    # is created. scenario_scoring_enabled and scenario_shadow must both be True
    # for shadow journaling to activate (Phase 14 Slice 8).
    scenario_shadow: bool = True

    # Comma-separated allowlist of entity_types eligible for automatic scenario
    # builds. Empty (default) means no seed is eligible even if other flags are
    # True.
    scenario_targets_enabled: str = ""

    # Master gate for scenario-realization outcome logging and drift metrics
    # (realization agreement, transmission accuracy, invalidator hit-rate, churn).
    # When False (default), no scenario_run_log calibration rows are written
    # (Phase 14 Slice 9).
    scenario_calibration_enabled: bool = False

    # -------------------------------------------------------------------------
    # Phase 15 — User Learning & Personalization flags
    # All six default inert: with capture/inference/relevance off and shadow on,
    # no event is stored, no preference is learned, and no surface is changed.
    # User Learning learns relevance only — it never rewrites truth (SP-7).
    # -------------------------------------------------------------------------

    # Master gate for appending user_signal_event rows.
    # When False (default), no behavioral event is persisted.
    learning_capture_enabled: bool = False

    # Master gate for running the periodic learning pass that produces
    # learned_preference and preference_evidence rows.
    # When False (default), no inference pass runs.
    learning_inference_enabled: bool = False

    # Master gate for computing relevance adjustments over a truth-fixed result set.
    # When False (default), relevance layer is idle.
    learning_relevance_enabled: bool = False

    # Shadow mode for relevance surfacing. When True (default), adjustments are
    # journaled to relevance_adjustment_log only — no surface ordering changes.
    # Never set False before Stage 5 sign-off.
    learning_shadow: bool = True

    # Comma-separated allowlist of entity_types eligible for learning targets.
    # Empty (default) means no entity_type is targeted even if other flags are True.
    learning_targets_enabled: str = ""

    # Master gate for preference calibration metrics (accuracy, drift,
    # false-preference detection). When False (default), no calibration pass runs.
    learning_calibration_enabled: bool = False

    # -------------------------------------------------------------------------
    # Phase 18 — Personal Experience Layer
    #
    # Phase 18 orchestrates intelligence — it never creates it.
    # It reads from every upstream phase but writes only to its own three tables:
    # personal_experience_cursor, personal_experience_event, personal_brief_snapshot.
    # No truth table is ever written, updated, or deleted by any Phase 18 service.
    # -------------------------------------------------------------------------

    # Master gate for the change detection engine that detects what changed
    # for a user since their last visit and writes view cursors.
    # When False (default), no changes are detected, no cursors are written.
    experience_change_detection_enabled: bool = False

    # Master gate for the attention scoring pipeline that computes 7-dimension
    # scores for candidate items. When False (default), all scores return 0.0.
    experience_attention_enabled: bool = False

    # Master gate for the experience composer that orchestrates all sub-services
    # into a ranked, explained experience payload.
    # When False (default), compose returns empty.
    experience_composer_enabled: bool = False

    # Master gate for the personal memory context service that provides
    # session continuity (research resumption, thesis continuation).
    # When False (default), memory context returns empty.
    experience_memory_enabled: bool = False

    # Shadow mode for experience surfacing. When True (default), all output goes
    # to the event log only — no user-visible personalization.
    # Never set False before Stage 5 sign-off.
    experience_shadow: bool = True

    # Master gate for the personal brief builder that generates daily briefs.
    # When False (default), no briefs are generated.
    experience_brief_enabled: bool = False

    # ── Phase 19 — Visual Intelligence flags ────────────────────────────────

    # Gate for Tier 1 structured JSON visual spec generation.
    # When False (default), no JSON visual specs are produced.
    visual_json_enabled: bool = False

    # Gate for Tier 2 server-side SVG visual rendering.
    # When False (default), no SVG visuals are rendered.
    visual_svg_enabled: bool = False

    # Gate for Tier 3 AI-generated visual explanations.
    # When False (default), all AI generation returns fallback specs.
    visual_ai_enabled: bool = False

    # Gate for visual specification caching.
    # When False (default), no cache reads or writes occur.
    visual_cache_enabled: bool = False

    # Shadow mode for visual generation. When True (default), all output goes
    # to the event log only — no user-visible visuals served.
    # Never set False before Stage 5 sign-off.
    visual_shadow: bool = True

    # Gate for visual calibration metrics computation.
    # When False (default), calibration returns empty metrics.
    visual_calibration_enabled: bool = False

    if _CONFIG_DICT is not None:  # type: ignore[name-defined]
        model_config = _CONFIG_DICT  # type: ignore[assignment]
    else:
        class Config:  # type: ignore[no-redef]
            env_file = ".env"
            env_file_encoding = "utf-8"


# Instantiate a single settings object when the module is imported.
settings = Settings()
