"""Shared HTTP behaviour for data providers: rate limiting, retries, typed errors.

Providers raise ProviderError subclasses; callers record them in provider_failures.
Nothing here returns made-up data: a failed call raises.
"""

import json
import logging
import random
import time
from collections import deque
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# A Retry-After longer than this is treated as "come back next run", not waited out.
MAX_RETRY_AFTER_SECONDS = 30.0


class ProviderError(Exception):
    def __init__(
        self, message: str, *, http_status: int | None = None, retry_count: int = 0
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retry_count = retry_count
        self.endpoint: str | None = None  # request path, never the query string


class ProviderAuthError(ProviderError):
    """401/403: the key is missing, wrong or not entitled. Retrying will not help."""


class ProviderNotFound(ProviderError):
    """404: the provider does not know this symbol."""


class ProviderRateLimited(ProviderError):
    """The provider (or our own request budget) says stop for now."""


class ProviderUnavailable(ProviderError):
    """5xx or network trouble that outlasted the retries."""


class ProviderDataError(ProviderError):
    """The response arrived but is not in the documented shape."""


class RateLimiter:
    """Sliding-window limiter. In-process only.

    ponytail: per-process. If several workers ever call the same provider, share the window
    through Redis.
    """

    def __init__(
        self,
        max_calls: int,
        per_seconds: float,
        *,
        max_wait_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.max_wait_seconds = max_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = self._clock()
        while self._calls and now - self._calls[0] >= self.per_seconds:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            wait = self.per_seconds - (now - self._calls[0])
            if wait > self.max_wait_seconds:
                raise ProviderRateLimited(
                    f"local request budget used up ({self.max_calls} per {self.per_seconds:g}s)"
                )
            self._sleep(wait)
            return self.acquire()
        self._calls.append(now)


class HttpJsonClient:
    def __init__(
        self,
        provider: str,
        base_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries
        self._limiter = limiter
        self._sleep = sleep
        self._client = client or httpx.Client(
            base_url=base_url, headers=dict(headers or {}), timeout=timeout
        )

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """GET and parse JSON. Floats become Decimal so prices never pass through binary floats."""
        try:
            response, attempt = self._request(path, params)
            return _parse(response, self.provider, attempt)
        except ProviderError as exc:
            exc.endpoint = exc.endpoint or _endpoint(path)
            raise

    def post_json(self, path: str, body: Mapping[str, Any]) -> Any:
        """POST a JSON body, parse the JSON reply. Same retries and typed errors as get_json."""
        try:
            response, attempt = self._request(path, None, body)
            return _parse(response, self.provider, attempt)
        except ProviderError as exc:
            exc.endpoint = exc.endpoint or _endpoint(path)
            raise

    def get_text(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        """GET a text body (RSS/XML). Same retries and errors as get_json."""
        try:
            return self._request(path, params)[0].text
        except ProviderError as exc:
            exc.endpoint = exc.endpoint or _endpoint(path)
            raise

    def _request(
        self, path: str, params: Mapping[str, Any] | None, body: Mapping[str, Any] | None = None
    ) -> tuple[httpx.Response, int]:
        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            if self._limiter:
                self._limiter.acquire()
            try:
                response = (
                    self._client.get(path, params=params)
                    if body is None
                    else self._client.post(path, json=body)
                )
            except httpx.HTTPError as exc:
                last_error = ProviderUnavailable(
                    f"{type(exc).__name__} calling {self.provider}", retry_count=attempt
                )
                self._backoff(attempt)
                continue

            status = response.status_code
            if status == 200:
                return response, attempt
            if status in (401, 403):
                raise ProviderAuthError(
                    f"{self.provider} rejected the credentials",
                    http_status=status,
                    retry_count=attempt,
                )
            if status == 404:
                raise ProviderNotFound(
                    f"{self.provider} has no data for this request",
                    http_status=404,
                    retry_count=attempt,
                )
            if status == 429:
                wait = _retry_after(response)
                if wait is None or wait > MAX_RETRY_AFTER_SECONDS:
                    raise ProviderRateLimited(
                        f"{self.provider} rate limit hit", http_status=429, retry_count=attempt
                    )
                last_error = ProviderRateLimited(
                    f"{self.provider} rate limit hit", http_status=429, retry_count=attempt
                )
                self._sleep(wait)
                continue
            if status >= 500:
                last_error = ProviderUnavailable(
                    f"{self.provider} returned HTTP {status}",
                    http_status=status,
                    retry_count=attempt,
                )
                self._backoff(attempt)
                continue
            raise ProviderError(
                f"{self.provider} returned HTTP {status}", http_status=status, retry_count=attempt
            )
        assert last_error is not None
        last_error.retry_count = self.max_retries
        raise last_error

    def _backoff(self, attempt: int) -> None:
        if attempt < self.max_retries:
            self._sleep(0.5 * 2**attempt + random.uniform(0, 0.25))  # noqa: S311

    def close(self) -> None:
        self._client.close()


def _endpoint(path: str) -> str:
    """Path without query string or fragment, so keys in URLs can never reach the failure log."""
    return path.split("?", 1)[0].split("#", 1)[0][:300]


def _parse(response: httpx.Response, provider: str, attempt: int) -> Any:
    try:
        return json.loads(response.text, parse_float=Decimal)
    except ValueError as exc:
        raise ProviderDataError(
            f"{provider} returned invalid JSON", http_status=200, retry_count=attempt
        ) from exc


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
