"""Builds provider clients from settings. Returns None when a provider lacks credentials."""

from functools import lru_cache

from app.core.config import Settings
from app.providers import coinbase, tiingo
from app.providers.base import HttpJsonClient, RateLimiter


@lru_cache
def _limiter(name: str, max_calls: int, per_seconds: float, max_wait: float) -> RateLimiter:
    # Cached so the request budget survives across job runs inside one worker process.
    return RateLimiter(max_calls, per_seconds, max_wait_seconds=max_wait)


def build_tiingo(settings: Settings) -> tiingo.TiingoProvider | None:
    if settings.tiingo_api_key is None:
        return None
    http = HttpJsonClient(
        "tiingo",
        tiingo.BASE_URL,
        headers={"Authorization": f"Token {settings.tiingo_api_key.get_secret_value()}"},
        # Do not sleep for an hour: when the budget is spent the run stops and says so.
        limiter=_limiter("tiingo", settings.tiingo_max_requests_per_hour, 3600.0, 0.0),
        timeout=settings.provider_http_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )
    return tiingo.TiingoProvider(http)


def build_coinbase(settings: Settings) -> coinbase.CoinbaseProvider:
    http = HttpJsonClient(
        "coinbase",
        coinbase.BASE_URL,
        headers={"User-Agent": coinbase.USER_AGENT},
        # Published limit is 10 requests/second per IP for public endpoints.
        limiter=_limiter("coinbase", 8, 1.0, 5.0),
        timeout=settings.provider_http_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )
    return coinbase.CoinbaseProvider(http)
