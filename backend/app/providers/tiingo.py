"""Tiingo end-of-day stock prices. https://www.tiingo.com/documentation/end-of-day"""

from datetime import UTC, date, datetime

from app.core.money import to_decimal
from app.market.bars import Bar, FetchResult, RejectedRow, stock_daily_available_at
from app.providers.base import HttpJsonClient, ProviderDataError

BASE_URL = "https://api.tiingo.com"


class TiingoProvider:
    name = "tiingo"

    def __init__(self, http: HttpJsonClient) -> None:
        self._http = http

    def fetch_daily(self, symbol: str, start: date, end: date) -> FetchResult:
        path = f"/tiingo/daily/{symbol}/prices"
        payload = self._http.get_json(
            path, {"startDate": start.isoformat(), "endDate": end.isoformat()}
        )
        # Errors can arrive as a JSON object with a "detail" message instead of a list.
        if not isinstance(payload, list):
            raise ProviderDataError("tiingo returned an unexpected response shape")
        result = FetchResult()
        for row in payload:
            try:
                result.bars.append(_parse_row(row))
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                result.rejected.append(RejectedRow(f"{type(exc).__name__}: {exc}", str(row)[:300]))
        return result


def _parse_row(row: dict) -> Bar:
    stamp = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00"))
    trading_date = stamp.date()
    adj = row.get("adjClose")
    return Bar(
        ts=datetime(trading_date.year, trading_date.month, trading_date.day, tzinfo=UTC),
        open=to_decimal(row["open"]),
        high=to_decimal(row["high"]),
        low=to_decimal(row["low"]),
        close=to_decimal(row["close"]),
        volume=to_decimal(row["volume"]),
        adj_close=to_decimal(adj) if adj is not None else None,
        available_at=stock_daily_available_at(trading_date),
    )
