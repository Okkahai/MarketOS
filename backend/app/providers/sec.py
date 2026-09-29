"""SEC EDGAR filings for the tracked companies. https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Free, no key, but the fair-access policy requires a User-Agent with a contact and at most 10
requests per second. The filing's acceptanceDateTime is when it became public, so that is the
published_at.
"""

import time
from datetime import UTC, datetime

from app.market.bars import RejectedRow
from app.news.normalize import NewsFetch, RawArticle
from app.providers.base import (
    HttpJsonClient,
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderRateLimited,
)

WWW_URL = "https://www.sec.gov"
DATA_URL = "https://data.sec.gov"
FORMS = frozenset({"8-K", "10-K", "10-Q"})
TICKER_CACHE_SECONDS = 24 * 3600

# The 8-K items people actually care about; anything else is shown by its number.
ITEM_LABELS = {
    "1.01": "material agreement",
    "1.02": "termination of material agreement",
    "1.03": "bankruptcy",
    "2.01": "acquisition or disposal",
    "2.02": "results of operations",
    "2.03": "new financial obligation",
    "2.05": "exit or restructuring costs",
    "2.06": "material impairment",
    "3.01": "delisting notice",
    "4.01": "change of auditor",
    "4.02": "non-reliance on past financials",
    "5.01": "change of control",
    "5.02": "officer or director change",
    "5.07": "shareholder vote",
    "7.01": "Regulation FD disclosure",
    "8.01": "other events",
    "9.01": "financial statements and exhibits",
}


class SecProvider:
    name = "sec_edgar"

    def __init__(self, www: HttpJsonClient, data: HttpJsonClient) -> None:
        self._www = www
        self._data = data
        self._tickers: dict[str, tuple[int, str]] = {}
        self._tickers_at = 0.0

    def company_index(self) -> dict[str, tuple[int, str]]:
        """ticker -> (CIK, company name). Cached for a day."""
        if self._tickers and time.monotonic() - self._tickers_at < TICKER_CACHE_SECONDS:
            return self._tickers
        payload = self._www.get_json("/files/company_tickers.json")
        if not isinstance(payload, dict):
            raise ProviderDataError("sec company_tickers.json has an unexpected shape")
        index: dict[str, tuple[int, str]] = {}
        for row in payload.values():
            try:
                index[str(row["ticker"]).upper()] = (int(row["cik_str"]), str(row["title"]))
            except (KeyError, TypeError, ValueError):
                continue
        if not index:
            raise ProviderDataError("sec company_tickers.json contained no usable rows")
        self._tickers, self._tickers_at = index, time.monotonic()
        return index

    def fetch_filings(self, symbols: list[str], since: datetime) -> NewsFetch:
        result = NewsFetch()
        try:
            index = self.company_index()
        except ProviderError as exc:
            result.errors.append(("company_tickers", exc))
            return result
        for symbol in symbols:
            entry = index.get(symbol.upper())
            if entry is None:
                result.errors.append(
                    (symbol, ProviderDataError(f"{symbol} is not in SEC company_tickers.json"))
                )
                continue
            cik, company = entry
            try:
                payload = self._data.get_json(f"/submissions/CIK{cik:010d}.json")
                articles, rejected = parse_submissions(payload, symbol, company, cik, since)
            except ProviderError as exc:
                result.errors.append((symbol, exc))
                if isinstance(exc, ProviderAuthError | ProviderRateLimited):
                    break
                continue
            result.articles.extend(articles)
            result.rejected.extend(rejected)
        return result


def parse_submissions(
    payload: object, symbol: str, company: str, cik: int, since: datetime
) -> tuple[list[RawArticle], list[RejectedRow]]:
    try:
        recent = payload["filings"]["recent"]  # type: ignore[index]
        columns = {
            k: recent[k]
            for k in ("accessionNumber", "acceptanceDateTime", "form", "primaryDocument")
        }
    except (KeyError, TypeError) as exc:
        raise ProviderDataError(f"sec submissions for {symbol} has an unexpected shape") from exc
    items = recent.get("items") or []
    descriptions = recent.get("primaryDocDescription") or []
    articles: list[RawArticle] = []
    rejected: list[RejectedRow] = []
    for i, accession in enumerate(columns["accessionNumber"]):
        form = columns["form"][i]
        if form not in FORMS:
            continue
        try:
            accepted = datetime.fromisoformat(
                str(columns["acceptanceDateTime"][i]).replace("Z", "+00:00")
            )
            if accepted.tzinfo is None:
                accepted = accepted.replace(tzinfo=UTC)
            if accepted < since:
                continue
            item_codes = [c.strip() for c in (items[i] if i < len(items) else "").split(",")]
            what = ", ".join(ITEM_LABELS.get(c, f"item {c}") for c in item_codes if c)
            doc = columns["primaryDocument"][i]
            folder = str(accession).replace("-", "")
            articles.append(
                RawArticle(
                    external_id=str(accession),
                    url=f"{WWW_URL}/Archives/edgar/data/{cik}/{folder}/{doc}",
                    title=f"{company} ({symbol}) filed {form}" + (f": {what}" if what else ""),
                    summary=str(descriptions[i]) if i < len(descriptions) else "",
                    published_at=accepted.astimezone(UTC),
                    provider_tickers=(symbol,),
                    fixed_category="filing",
                    text_dedup=False,
                    raw={"form": form, "items": item_codes, "accession": accession},
                )
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            rejected.append(RejectedRow(f"{type(exc).__name__}: {exc}", f"{symbol} {accession}"))
    return articles, rejected
