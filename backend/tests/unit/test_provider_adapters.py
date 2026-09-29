import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from app.providers.base import HttpJsonClient, ProviderDataError
from app.providers.coinbase import CoinbaseProvider
from app.providers.tiingo import TiingoProvider

# The payloads below follow the providers' documented response shapes. The numbers are
# synthetic test values, not market data.


def http(handler, headers=None):
    inner = httpx.Client(
        base_url="https://x.test", headers=headers or {}, transport=httpx.MockTransport(handler)
    )
    return HttpJsonClient("p", "https://x.test", client=inner, max_retries=0)


TIINGO_BODY = """[
 {"date":"2026-09-24T00:00:00.000Z","close":101.10,"high":102.5,"low":99.0,"open":100.0,
  "volume":1500000,"adjClose":100.9,"adjHigh":102.3,"adjLow":98.8,"adjOpen":99.8,
  "adjVolume":1500000,"divCash":0.0,"splitFactor":1.0},
 {"date":"2026-09-25T00:00:00.000Z","close":103,"high":104,"low":100.5,"open":101.25,
  "volume":2000000,"adjClose":102.8},
 {"date":"2026-09-26T00:00:00.000Z","close":50,"high":40,"low":45,"open":48,"volume":10}
]"""


def test_tiingo_parses_rows_and_rejects_inconsistent_ones():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, text=TIINGO_BODY)

    provider = TiingoProvider(http(handler, {"Authorization": "Token k3y"}))
    result = provider.fetch_daily("AAPL", date(2026, 9, 24), date(2026, 9, 26))

    assert "/tiingo/daily/AAPL/prices" in seen["url"]
    assert "startDate=2026-09-24" in seen["url"] and "k3y" not in seen["url"]
    assert seen["auth"] == "Token k3y"
    assert len(result.bars) == 2
    first = result.bars[0]
    assert first.ts == datetime(2026, 9, 24, tzinfo=UTC)
    assert (first.open, first.close, first.adj_close) == (D("100.0"), D("101.10"), D("100.9"))
    assert first.volume == D("1500000")
    assert first.available_at == datetime(2026, 9, 25, 0, 0, tzinfo=UTC)  # 8pm EDT
    assert result.bars[1].adj_close == D("102.8")
    assert len(result.rejected) == 1 and "40" in result.rejected[0].raw


def test_tiingo_empty_range_is_not_an_error():
    provider = TiingoProvider(http(lambda r: httpx.Response(200, text="[]")))
    result = provider.fetch_daily("AAPL", date(2026, 9, 26), date(2026, 9, 27))  # a weekend
    assert result.bars == [] and result.rejected == []


def test_tiingo_error_object_is_a_data_error_not_zero_bars():
    body = '{"detail":"Error: You have exceeded your hourly request allocation"}'
    provider = TiingoProvider(http(lambda r: httpx.Response(200, text=body)))
    with pytest.raises(ProviderDataError):
        provider.fetch_daily("AAPL", date(2026, 9, 24), date(2026, 9, 26))


def candle(ts: datetime, low="9.5", high="10.5", open_="10", close="10.2", volume="3.5"):
    return json.loads(
        f"[{int(ts.timestamp())},{low},{high},{open_},{close},{volume}]", parse_float=D
    )


def test_coinbase_orders_ascending_maps_columns_and_does_not_fill_gaps():
    t0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    rows = [candle(t0 + timedelta(minutes=3)), candle(t0), candle(t0 + timedelta(minutes=1))]
    # minute 2 has no trades, so Coinbase publishes no row for it

    def handler(request):
        assert request.url.params["granularity"] == "60"
        return httpx.Response(200, text=json.dumps([[r[0], *map(str, r[1:])] for r in rows]))

    provider = CoinbaseProvider(http(handler))
    result = provider.fetch_candles("BTC-USD", "1m", t0, t0 + timedelta(minutes=4))
    assert [b.ts for b in result.bars] == [t0, t0 + timedelta(minutes=1), t0 + timedelta(minutes=3)]
    bar = result.bars[0]
    # Coinbase order is [time, low, high, open, close, volume]
    assert (bar.low, bar.high, bar.open, bar.close, bar.volume) == (
        D("9.5"), D("10.5"), D("10"), D("10.2"), D("3.5"),
    )  # fmt: skip
    assert bar.available_at == t0 + timedelta(minutes=1, seconds=5)


def test_coinbase_splits_long_ranges_into_300_candle_requests_without_duplicates():
    t0 = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    requests = []

    def handler(request):
        requests.append(request.url.params)
        start = datetime.fromisoformat(request.url.params["start"])
        end = datetime.fromisoformat(request.url.params["end"])
        minutes = int((end - start).total_seconds() // 60) + 1
        assert minutes <= 300
        rows = [candle(start + timedelta(minutes=i)) for i in range(minutes)]
        return httpx.Response(200, text=json.dumps([[r[0], *map(str, r[1:])] for r in rows]))

    provider = CoinbaseProvider(http(handler))
    result = provider.fetch_candles("ETH-USD", "1m", t0, t0 + timedelta(minutes=700))
    assert len(requests) == 3
    times = [b.ts for b in result.bars]
    assert times == sorted(set(times))
    assert times[0] == t0 and times[-1] == t0 + timedelta(minutes=700)  # end is inclusive


def test_coinbase_rejects_bad_rows_and_keeps_the_rest():
    t0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    good = [t0.timestamp(), "9", "11", "10", "10.5", "1"]
    inverted = [t0.timestamp() + 60, "12", "11", "10", "10.5", "1"]  # low above high
    short = [t0.timestamp() + 120, "1"]
    body = json.dumps([[int(good[0]), *good[1:]], [int(inverted[0]), *inverted[1:]], short])
    provider = CoinbaseProvider(http(lambda r: httpx.Response(200, text=body)))
    result = provider.fetch_candles("BTC-USD", "1m", t0, t0 + timedelta(minutes=3))
    assert len(result.bars) == 1 and len(result.rejected) == 2


def test_coinbase_object_payload_is_a_data_error():
    provider = CoinbaseProvider(http(lambda r: httpx.Response(200, text='{"message":"NotFound"}')))
    t0 = datetime(2026, 9, 29, tzinfo=UTC)
    with pytest.raises(ProviderDataError):
        provider.fetch_candles("BTC-USD", "1d", t0, t0 + timedelta(days=1))
