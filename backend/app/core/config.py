"""Application settings, read from environment variables (see .env.example).

Secrets are optional at this stage: a provider whose key is missing is reported
as "not configured" and its jobs are skipped, never faked.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # MarketOS only simulates trades. There is deliberately no other value.
    trading_mode: Literal["paper"] = "paper"

    database_url: str = "postgresql+psycopg://marketos:marketos@localhost:5432/marketos"
    redis_url: str = "redis://localhost:6379/0"
    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    paper_initial_capital: Decimal = Field(default=Decimal("10000"), gt=0)
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    schedule_heartbeat_seconds: int = Field(default=60, ge=10)
    schedule_stock_daily_seconds: int = Field(default=3600, ge=60)
    schedule_crypto_daily_seconds: int = Field(default=3600, ge=60)
    schedule_crypto_1m_seconds: int = Field(default=60, ge=30)
    schedule_indicators_seconds: int = Field(default=3600, ge=60)
    schedule_news_seconds: int = Field(default=900, ge=60)
    schedule_events_seconds: int = Field(default=600, ge=60)

    # Market data collection
    market_history_days: int = Field(default=400, ge=30, le=3650)
    market_intraday_backfill_hours: int = Field(default=24, ge=1, le=168)
    # Re-fetched days before the newest stored bar, so provider corrections are caught.
    market_overlap_days: int = Field(default=5, ge=1, le=30)
    indicator_store_bars: int = Field(default=30, ge=1, le=1000)
    provider_http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    provider_max_retries: int = Field(default=3, ge=0, le=6)
    # Below Tiingo's published free-tier limit of 50/hour, to absorb window edges.
    # News collection
    news_backfill_days: int = Field(default=3, ge=1, le=90)
    # Articles further apart than this are never treated as duplicates of each other.
    news_dedup_window_hours: int = Field(default=48, ge=1, le=336)
    # An event with no new article for this long is closed; a later story starts a new event.
    event_window_hours: int = Field(default=48, ge=1, le=336)
    tiingo_max_requests_per_hour: int = Field(default=40, ge=1)

    tiingo_api_key: SecretStr | None = None
    alpha_vantage_api_key: SecretStr | None = None
    coingecko_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    sec_user_agent: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("paper_initial_capital", mode="before")
    @classmethod
    def _no_float_capital(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("pass capital as a string or integer, not a float")
        return value

    @field_validator(
        "tiingo_api_key",
        "alpha_vantage_api_key",
        "coingecko_api_key",
        "finnhub_api_key",
        "fred_api_key",
        "anthropic_api_key",
        "sec_user_agent",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("sec_user_agent")
    @classmethod
    def _sec_user_agent_has_contact(cls, value: str | None) -> str | None:
        # SEC fair-access policy requires a name and a contact email.
        if value is not None and "@" not in value:
            raise ValueError("SEC_USER_AGENT must include a contact email, e.g. 'Name you@x.com'")
        return value

    def provider_status(self) -> dict[str, bool]:
        """Which providers have credentials. Never exposes the values."""
        return {
            "tiingo": self.tiingo_api_key is not None,
            "alpha_vantage": self.alpha_vantage_api_key is not None,
            "coinbase": True,  # public market data, no key needed
            "coingecko": self.coingecko_api_key is not None,
            "finnhub": self.finnhub_api_key is not None,
            "fred": self.fred_api_key is not None,
            "sec_edgar": self.sec_user_agent is not None,
            "anthropic": self.anthropic_api_key is not None,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
