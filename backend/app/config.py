"""Runtime settings, read from environment variables or a local .env file (never committed)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # --- LLM provider -----------------------------------------------------
    # "anthropic" for real use, "fake" for offline development and tests.
    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "low"  # low keeps latency well under the 30 s target
    # USD per 1M tokens, used only for the cost estimate in logs/metrics.
    llm_price_input_per_mtok: float = 4.0
    llm_price_output_per_mtok: float = 20.0

    # --- Storage ------------------------------------------------------------
    corpus_db_path: Path = REPO_ROOT / "var" / "corpus.db"
    audit_db_path: Path = REPO_ROOT / "var" / "audit.db"
    sources_catalog_path: Path = REPO_ROOT / "corpus" / "sources.csv"
    retention_days: int = 30

    # --- Verification behaviour ----------------------------------------------
    max_input_chars: int = 5000
    max_fetched_chars: int = 12000
    max_claims: int = 5
    passages_per_claim: int = 8
    archival_after_days: int = 365

    # --- Abuse protection --------------------------------------------------
    rate_limit_per_minute: int = 10
    admin_token: str | None = None  # required for /api/logs and /api/metrics

    # --- Channels ------------------------------------------------------------
    public_base_url: str = "http://localhost:5173"  # where result links point
    api_base_url: str = "http://localhost:8000"  # used by the Discord bot
    discord_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
