from decimal import Decimal

import httpx
import pytest

from app.providers.base import (
    HttpJsonClient,
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFound,
    ProviderRateLimited,
    ProviderUnavailable,
    RateLimiter,
)


def client(handler, *, retries=3, limiter=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    http = httpx.Client(base_url="https://x.test", transport=httpx.MockTransport(handler))
    return HttpJsonClient(
        "testprov", "https://x.test", client=http, max_retries=retries, limiter=limiter,
        sleep=sleeps.append,
    ), sleeps  # fmt: skip


def test_success_parses_floats_as_exact_decimals():
    c, _ = client(lambda r: httpx.Response(200, text='{"p": 0.1, "q": 185.20, "n": 3}'))
    data = c.get_json("/a")
    assert data == {"p": Decimal("0.1"), "q": Decimal("185.20"), "n": 3}
    assert isinstance(data["p"], Decimal)


def test_retries_server_errors_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=[1])

    c, sleeps = client(handler)
    assert c.get_json("/a") == [1]
    assert len(calls) == 3 and len(sleeps) == 2


def test_gives_up_after_max_retries_and_reports_the_count():
    calls = []
    c, _ = client(lambda r: (calls.append(1), httpx.Response(500))[1], retries=2)
    with pytest.raises(ProviderUnavailable) as err:
        c.get_json("/prices")
    assert len(calls) == 3
    assert err.value.http_status == 500 and err.value.retry_count == 2
    assert err.value.endpoint == "/prices"


def test_network_errors_are_retried_and_reported_without_the_message():
    def handler(request):
        raise httpx.ConnectError("secret-host:5432 refused")

    c, _ = client(handler, retries=1)
    with pytest.raises(ProviderUnavailable) as err:
        c.get_json("/a")
    assert "secret-host" not in str(err.value)


def test_short_retry_after_is_waited_out():
    calls = []

    def handler(request):
        calls.append(1)
        return (
            httpx.Response(429, headers={"retry-after": "2"})
            if len(calls) == 1
            else (httpx.Response(200, json={"ok": True}))
        )

    c, sleeps = client(handler)
    assert c.get_json("/a") == {"ok": True}
    assert sleeps == [2.0]


@pytest.mark.parametrize("headers", [{"retry-after": "3600"}, {}])
def test_long_or_missing_retry_after_stops_immediately(headers):
    calls = []
    c, sleeps = client(lambda r: (calls.append(1), httpx.Response(429, headers=headers))[1])
    with pytest.raises(ProviderRateLimited):
        c.get_json("/a")
    assert len(calls) == 1 and sleeps == []


@pytest.mark.parametrize(
    ("status", "exc"),
    [(401, ProviderAuthError), (403, ProviderAuthError), (404, ProviderNotFound),
     (400, ProviderError)],
)  # fmt: skip
def test_client_errors_are_not_retried(status, exc):
    calls = []
    c, _ = client(lambda r: (calls.append(1), httpx.Response(status))[1])
    with pytest.raises(exc) as err:
        c.get_json("/a")
    assert len(calls) == 1 and err.value.http_status == status


def test_invalid_json_is_a_data_error():
    c, _ = client(lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ProviderDataError):
        c.get_json("/a")


def test_each_attempt_uses_the_rate_limit_budget():
    now = [0.0]
    limiter = RateLimiter(2, 60.0, clock=lambda: now[0])
    c, _ = client(lambda r: httpx.Response(500), retries=5, limiter=limiter)
    with pytest.raises(ProviderRateLimited):
        c.get_json("/a")


def test_limiter_sliding_window():
    now = [0.0]
    limiter = RateLimiter(2, 10.0, clock=lambda: now[0])
    limiter.acquire()
    now[0] = 5.0
    limiter.acquire()
    with pytest.raises(ProviderRateLimited):
        limiter.acquire()
    now[0] = 10.0  # the first call has left the window
    limiter.acquire()
    with pytest.raises(ProviderRateLimited):
        limiter.acquire()


def test_limiter_sleeps_when_the_wait_is_short_enough():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(1, 1.0, max_wait_seconds=2.0, clock=lambda: now[0], sleep=sleep)
    limiter.acquire()
    limiter.acquire()
    assert slept == [pytest.approx(1.0)]
