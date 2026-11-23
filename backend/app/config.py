"""Application settings, loaded from environment variables (12-factor style).

Every value has a safe default for local development. Production deployments
must set APP_ENV=production, which turns on the strict checks in `validate()`.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Quarry"
    log_level: str = "INFO"

    # Persistence
    database_url: str = "sqlite:///./data/quarry.db"
    redis_url: str | None = None  # when unset, in-process fallbacks are used
    storage_dir: str = "./data/blobs"

    # Secrets. Dev defaults are deliberately obvious so they are never mistaken for real ones.
    jwt_secret: str = "dev-only-change-me-dev-only-change-me"
    # Comma separated Fernet keys; the first encrypts, all of them decrypt (key rotation).
    data_encryption_keys: str = "ZGV2LW9ubHkta2V5LWRvLW5vdC11c2UtaW4tcHJvZCE="

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173"

    # Abuse limits
    max_upload_mb: int = 25
    max_rows_per_file: int = 1_000_000
    max_columns: int = 300
    max_files_per_user: int = 20
    uploads_per_user_per_hour: int = 20
    register_per_ip_per_hour: int = 5
    login_per_ip_per_minute: int = 20
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    rate_limit_per_minute: int = 120
    chat_rate_limit_per_minute: int = 20
    daily_llm_calls_per_user: int = 300

    # Query engine
    query_timeout_seconds: float = 10.0
    query_row_limit: int = 5_000
    query_memory_limit: str = "512MB"
    result_cache_ttl_seconds: int = 600

    # LLM
    llm_provider: Literal["anthropic", "openai", "fake"] = "fake"
    llm_model: str = "claude-sonnet-5-5"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_max_tool_steps: int = 6
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    history_messages: int = Field(default=12, description="Prior turns sent to the model")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def encryption_key_list(self) -> list[str]:
        return [k.strip() for k in self.data_encryption_keys.split(",") if k.strip()]

    def validate_for_production(self) -> None:
        """Refuse to boot in production with development secrets or insecure cookies."""
        if self.app_env != "production":
            return
        problems = []
        if "dev-only" in self.jwt_secret or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a random value of at least 32 characters")
        if "ZGV2LW9ubHkta2V5" in self.data_encryption_keys:
            problems.append("DATA_ENCRYPTION_KEYS must be replaced with a generated Fernet key")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true behind HTTPS")
        if self.llm_provider == "fake":
            problems.append("LLM_PROVIDER=fake is for tests only")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
