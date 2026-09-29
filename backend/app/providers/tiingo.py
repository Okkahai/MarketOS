"""Tiingo end-of-day stock prices. https://www.tiingo.com/documentation/end-of-day"""

from datetime import UTC, date, datetime

from app.core.money import to_decimal
from app.market.bars import Bar, FetchResult, RejectedRow, stock_daily_available_at
from app.news.normalize import NewsFetch, RawArticle
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

    def fetch_news(self, tickers: list[str], start: datetime) -> NewsFetch:
        return fetch_news(self._http, tickers, start)


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


def fetch_news(
    http: HttpJsonClient, tickers: list[str], start: datetime, *, page_size: int = 100,
    max_pages: int = 5,
) -> NewsFetch:  # fmt: skip
    """Newest first, only items Tiingo has tagged with one of our tickers."""
    result = NewsFetch()
    for page in range(max_pages):
        payload = http.get_json(
            "/tiingo/news",
            {
                "tickers": ",".join(t.lower() for t in tickers),
                "startDate": start.date().isoformat(),
                "limit": page_size,
                "offset": page * page_size,
                "sortBy": "publishedDate",
                "onlyWithTickers": "true",
            },
        )
        if not isinstance(payload, list):
            raise ProviderDataError("tiingo news returned an unexpected response shape")
        for row in payload:
            try:
                result.articles.append(_parse_news(row))
            except (KeyError, TypeError, ValueError) as exc:
                result.rejected.append(RejectedRow(f"{type(exc).__name__}: {exc}", str(row)[:300]))
        if len(payload) < page_size:
            break
    return result


def _parse_news(row: dict) -> RawArticle:
    published = datetime.fromisoformat(str(row["publishedDate"]).replace("Z", "+00:00"))
    return RawArticle(
        external_id=str(row["id"]),
        url=str(row["url"]),
        title=str(row["title"]),
        summary=str(row.get("description") or ""),
        published_at=published,
        provider_tickers=tuple(str(t) for t in row.get("tickers") or ()),
        raw={k: row.get(k) for k in ("source", "tickers", "tags", "crawlDate", "publishedDate")},
    )
