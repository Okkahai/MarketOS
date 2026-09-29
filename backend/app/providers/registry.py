"""Builds provider clients from settings. Returns None when a provider lacks credentials."""

from functools import lru_cache

from app.ai import llm
from app.ai.llm import AnthropicClient
from app.core.config import Settings
from app.providers import coinbase, fed, sec, tiingo
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


def build_sec(settings: Settings) -> sec.SecProvider | None:
    if settings.sec_user_agent is None:
        return None
    headers = {"User-Agent": settings.sec_user_agent}
    # SEC allows 10 requests/second; stay at half of that. Both hosts count as one client.
    limiter = _limiter("sec_edgar", 5, 1.0, 5.0)
    kwargs = {
        "headers": headers,
        "limiter": limiter,
        "timeout": settings.provider_http_timeout_seconds,
        "max_retries": settings.provider_max_retries,
    }
    return sec.SecProvider(
        HttpJsonClient("sec_edgar", sec.WWW_URL, **kwargs),
        HttpJsonClient("sec_edgar", sec.DATA_URL, **kwargs),
    )


def build_fed(settings: Settings) -> HttpJsonClient:
    return HttpJsonClient(
        "fed_rss",
        fed.BASE_URL,
        headers={"User-Agent": fed.USER_AGENT},
        limiter=_limiter("fed_rss", 2, 1.0, 5.0),
        timeout=settings.provider_http_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )


def build_anthropic(settings: Settings) -> AnthropicClient | None:
    if settings.anthropic_api_key is None:
        return None
    http = HttpJsonClient(
        "anthropic",
        llm.BASE_URL,
        headers={
            "x-api-key": settings.anthropic_api_key.get_secret_value(),
            "anthropic-version": llm.API_VERSION,
        },
        limiter=_limiter("anthropic", 30, 60.0, 0.0),
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.provider_max_retries,
    )
    return llm.AnthropicClient(http)
