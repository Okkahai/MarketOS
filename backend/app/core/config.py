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
    # Paper trading rules. Percentages are of total portfolio value unless noted.
    paper_min_confidence: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    paper_strong_buy_min_confidence: Decimal = Field(default=Decimal("0.75"), ge=0, le=1)
    paper_max_position_pct: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    paper_max_sector_pct: Decimal = Field(default=Decimal("30"), gt=0, le=100)
    paper_max_crypto_pct: Decimal = Field(default=Decimal("25"), ge=0, le=100)
    paper_min_cash_pct: Decimal = Field(default=Decimal("10"), ge=0, le=100)
    paper_max_open_positions: int = Field(default=8, ge=1)
    paper_min_trade_usd: Decimal = Field(default=Decimal("50"), ge=0)
    paper_default_position_pct: Decimal = Field(default=Decimal("4"), gt=0, le=100)
    paper_cooldown_hours: int = Field(default=24, ge=0)
    paper_max_trades_per_day: int = Field(default=5, ge=1)
    paper_default_stop_pct: Decimal = Field(default=Decimal("8"), gt=0, le=100)
    paper_max_stop_pct: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    paper_max_take_profit_pct: Decimal = Field(default=Decimal("30"), gt=0)
    paper_drawdown_breaker_pct: Decimal = Field(default=Decimal("20"), gt=0, le=100)
    paper_order_expiry_hours: int = Field(default=72, ge=1)
    # A daily bar is the freshest price the model sees; these ages allow a weekend or holiday.
    paper_max_price_age_hours_stock: int = Field(default=100, ge=1)
    paper_max_price_age_hours_crypto: int = Field(default=36, ge=1)
    paper_slippage_bps_stock: Decimal = Field(default=Decimal("5"), ge=0)
    paper_slippage_bps_crypto: Decimal = Field(default=Decimal("10"), ge=0)
    paper_fee_bps_stock: Decimal = Field(default=Decimal("0"), ge=0)
    paper_fee_bps_crypto: Decimal = Field(default=Decimal("40"), ge=0)
    paper_min_fee: Decimal = Field(default=Decimal("0"), ge=0)
    # Bars that supply crypto fill prices: "1m" live, "1d" for daily backtests.
    paper_crypto_fill_interval: Literal["1m", "1d"] = "1m"
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    schedule_heartbeat_seconds: int = Field(default=60, ge=10)
    schedule_stock_daily_seconds: int = Field(default=3600, ge=60)
    schedule_crypto_daily_seconds: int = Field(default=3600, ge=60)
    schedule_crypto_1m_seconds: int = Field(default=60, ge=30)
    schedule_indicators_seconds: int = Field(default=3600, ge=60)
    schedule_news_seconds: int = Field(default=900, ge=60)
    schedule_events_seconds: int = Field(default=600, ge=60)
    schedule_ai_seconds: int = Field(default=900, ge=60)
    schedule_paper_seconds: int = Field(default=300, ge=60)
    schedule_reconcile_seconds: int = Field(default=3600, ge=60)

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

    # AI analysis. Prices are per million tokens and must be set by the operator for every model
    # in use; a model without a price is never called, so the budget can always be enforced.
    # Example: AI_MODEL_PRICES={"claude-haiku-4-5-20251001":{"input":"1","output":"5"}}
    ai_triage_model: str = "claude-haiku-4-5-20251001"
    ai_analysis_model: str = "claude-sonnet-5-5"
    ai_model_prices: dict[str, dict[str, Decimal]] = Field(default_factory=dict)
    ai_daily_budget_usd: Decimal = Field(default=Decimal("5"), ge=0)
    ai_min_event_importance: Decimal = Field(default=Decimal("0.3"), ge=0, le=1)
    ai_max_events_per_run: int = Field(default=5, ge=1, le=50)
    ai_reanalyze_hours: int = Field(default=6, ge=1, le=168)
    ai_max_signals_per_analysis: int = Field(default=3, ge=1, le=10)
    ai_max_output_tokens: int = Field(default=2000, ge=256, le=8000)
    ai_timeout_seconds: float = Field(default=120.0, ge=5, le=600)

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
