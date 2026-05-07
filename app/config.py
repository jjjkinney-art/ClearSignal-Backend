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
    openai_model: str = "gpt-4o"
    max_tokens: int = 4096
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
