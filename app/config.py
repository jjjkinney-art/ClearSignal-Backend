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

    if _CONFIG_DICT is not None:  # type: ignore[name-defined]
        model_config = _CONFIG_DICT  # type: ignore[assignment]
    else:
        class Config:  # type: ignore[no-redef]
            env_file = ".env"
            env_file_encoding = "utf-8"


# Instantiate a single settings object when the module is imported.
settings = Settings()
