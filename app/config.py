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
    # The full InvestmentThesis JSON minimum is ~1,100 tokens.  1200 gives a
    # ~9% buffer over the minimum while keeping generation time to:
    #   1200 tokens × 54 tok/s (worst typical load) = 22s  ← fits in 27s budget
    #   1200 tokens × 30 tok/s (extreme load) = 40s        ← synthesis times out,
    #                                                         fallback thesis returned
    # Override via SYNTHESIS_MAX_TOKENS if richer synthesis is needed.
    synthesis_max_tokens: int = 1200

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

    # Synthesis-specific timeout.  With synthesis_max_tokens=1200, gpt-4o-mini
    # generates at most 1200 output tokens.  Observed synthesis latency on Render:
    # 26-38s depending on OpenAI load and evidence density.  37s catches ~95%+.
    # Python-side wall cap (_SYNTHESIS_WALL_CAP_S=38) fires 1s after httpx.
    # Pipeline budget: evidence(≤8s) + agents(≤14s) + synthesis(≤38s) + post(≤0.5s) = ≤60.5s
    # 0.5s margin inside Render's 61s Nginx proxy_read_timeout.
    # Evidence cap reduced to 8s (from 10s) to free 2s for synthesis headroom.
    # Agent wall cap reduced to 14s (from 16s) to free 2s for synthesis headroom.
    synthesis_timeout: float = 37.0

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
    if _CONFIG_DICT is not None:  # type: ignore[name-defined]
        model_config = _CONFIG_DICT  # type: ignore[assignment]
    else:
        class Config:  # type: ignore[no-redef]
            env_file = ".env"
            env_file_encoding = "utf-8"


# Instantiate a single settings object when the module is imported.
settings = Settings()
