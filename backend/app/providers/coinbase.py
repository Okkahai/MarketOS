"""Coinbase Exchange public candles (no API key).

https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles
Each row is [time, low, high, open, close, volume]; at most 300 candles per request; no row is
published for an interval without trades, and we do not fill those gaps.
"""

from datetime import UTC, datetime

from app.core.money import to_decimal
from app.market.bars import INTERVAL_DELTA, Bar, FetchResult, RejectedRow, crypto_available_at
from app.providers.base import HttpJsonClient, ProviderDataError

BASE_URL = "https://api.exchange.coinbase.com"
GRANULARITY_SECONDS = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}
MAX_CANDLES = 300
USER_AGENT = "MarketOS/0.1 (paper-trading research; +https://github.com/Okkahai/MarketOS)"


class CoinbaseProvider:
    name = "coinbase"

    def __init__(self, http: HttpJsonClient) -> None:
        self._http = http

    def fetch_candles(
        self, product: str, interval: str, start: datetime, end: datetime
    ) -> FetchResult:
        step = INTERVAL_DELTA[interval]
        chunk = step * MAX_CANDLES
        result = FetchResult()
        seen: dict[datetime, Bar] = {}
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + chunk - step, end)
            payload = self._http.get_json(
                f"/products/{product}/candles",
                {
                    "granularity": GRANULARITY_SECONDS[interval],
                    "start": cursor.astimezone(UTC).isoformat(),
                    "end": chunk_end.astimezone(UTC).isoformat(),
                },
            )
            if not isinstance(payload, list):
                raise ProviderDataError("coinbase returned an unexpected response shape")
            for row in payload:
                try:
                    bar = _parse_row(row, interval)
                except (IndexError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
                    result.rejected.append(
                        RejectedRow(f"{type(exc).__name__}: {exc}", str(row)[:300])
                    )
                    continue
                seen[bar.ts] = bar
            cursor = chunk_end + step
        result.bars = [seen[ts] for ts in sorted(seen)]
        return result


def _parse_row(row: list, interval: str) -> Bar:
    ts = datetime.fromtimestamp(int(row[0]), tz=UTC)
    return Bar(
        ts=ts,
        low=to_decimal(row[1]),
        high=to_decimal(row[2]),
        open=to_decimal(row[3]),
        close=to_decimal(row[4]),
        volume=to_decimal(row[5]),
        available_at=crypto_available_at(ts, interval),
    )
