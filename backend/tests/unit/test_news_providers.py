import json
from datetime import UTC, datetime

import httpx
import pytest

from app.news.normalize import normalize
from app.providers import fed
from app.providers.base import HttpJsonClient, ProviderAuthError, ProviderDataError
from app.providers.sec import SecProvider, parse_submissions
from app.providers.tiingo import fetch_news

# Payloads follow the documented response shapes; the text is synthetic.

SINCE = datetime(2026, 9, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def http(handler, base="https://x.test"):
    inner = httpx.Client(base_url=base, transport=httpx.MockTransport(handler))
    return HttpJsonClient("p", base, client=inner, max_retries=0)


# --- Tiingo -------------------------------------------------------------------------------


def test_tiingo_news_parses_and_paginates():
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        if request.url.params["offset"] == "0":
            rows = [
                {"id": i, "title": f"Story {i}", "url": f"https://n.test/{i}",
                 "description": "d", "publishedDate": "2026-09-28T10:00:00Z",
                 "tickers": ["aapl", "btcusd"], "source": "n.test", "tags": []}
                for i in range(2)
            ]  # fmt: skip
        else:
            rows = [{"id": 9, "title": "no date", "url": "https://n.test/9"}]
        return httpx.Response(200, json=rows)

    result = fetch_news(http(handler), ["AAPL", "BTCUSD"], SINCE, page_size=2)
    assert [a.external_id for a in result.articles] == ["0", "1"]
    assert len(result.rejected) == 1 and "publishedDate" in result.rejected[0].reason
    assert calls[0]["tickers"] == "aapl,btcusd" and calls[0]["onlyWithTickers"] == "true"
    assert len(calls) == 2
    assert normalize(result.articles[0], NOW).tickers == ["AAPL", "BTC-USD"]


def test_tiingo_news_error_object_is_a_data_error():
    with pytest.raises(ProviderDataError):
        fetch_news(http(lambda r: httpx.Response(200, json={"detail": "nope"})), ["AAPL"], SINCE)


def test_tiingo_news_auth_error_propagates_with_endpoint():
    with pytest.raises(ProviderAuthError) as info:
        fetch_news(http(lambda r: httpx.Response(401, json={"detail": "bad"})), ["AAPL"], SINCE)
    assert info.value.endpoint == "/tiingo/news"


# --- Fed ----------------------------------------------------------------------------------

FED_XML = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Federal Reserve issues FOMC statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</link>
<guid>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm</guid>
<pubDate>Wed, 16 Sep 2026 18:00:00 GMT</pubDate>
<description>&lt;p&gt;Rates unchanged.&lt;/p&gt;</description></item>
<item><title>No zone</title><link>https://x.test/1</link>
<pubDate>Wed, 16 Sep 2026 18:00:00 -0000</pubDate></item>
<item><title>No date</title><link>https://x.test/2</link></item>
</channel></rss>"""


def test_fed_feed_parses_items_and_rejects_bad_ones():
    articles, rejected = fed.parse_feed(FED_XML)
    assert len(articles) == 1 and len(rejected) == 2
    n = normalize(articles[0], NOW)
    assert n.published_at == datetime(2026, 9, 16, 18, tzinfo=UTC)
    assert n.category == "central_bank" and n.countries == ["US"]
    assert "<p>" not in n.summary


def test_fed_feed_refuses_xml_entity_bombs():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss>&b;</rss>'
    )
    with pytest.raises(ProviderDataError):
        fed.parse_feed(bomb)


def test_fed_feed_failure_is_recorded_not_raised():
    result = fed.fetch_feeds(http(lambda r: httpx.Response(500)), ("/feeds/a.xml",))
    assert result.articles == [] and result.errors[0][0] == "/feeds/a.xml"
    assert result.errors[0][1].endpoint == "/feeds/a.xml"


# --- SEC ----------------------------------------------------------------------------------

TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
SUBMISSIONS = {
    "filings": {"recent": {
        "accessionNumber": ["0000320193-26-000010", "0000320193-26-000009", "0000320193-26-000008"],
        "acceptanceDateTime": ["2026-09-25T20:15:30.000Z", "2026-09-25T20:00:00.000Z",
                               "2026-01-02T20:00:00.000Z"],
        "form": ["8-K", "4", "10-Q"],
        "primaryDocument": ["a8k.htm", "f4.xml", "a10q.htm"],
        "items": ["2.02,9.01", "", ""],
        "primaryDocDescription": ["8-K", "4", "10-Q"],
    }}
}  # fmt: skip


def test_sec_submissions_keep_only_recent_relevant_forms():
    articles, rejected = parse_submissions(SUBMISSIONS, "AAPL", "Apple Inc.", 320193, SINCE)
    assert rejected == [] and len(articles) == 1  # Form 4 skipped, 10-Q older than `since`
    a = articles[0]
    assert a.url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/a8k.htm"
    assert a.title == (
        "Apple Inc. (AAPL) filed 8-K: results of operations, financial statements and exhibits"
    )
    assert a.published_at == datetime(2026, 9, 25, 20, 15, 30, tzinfo=UTC)
    n = normalize(a, NOW)
    assert n.category == "filing" and n.tickers == ["AAPL"] and n.text_dedup is False


def test_sec_unexpected_shape_is_a_data_error():
    with pytest.raises(ProviderDataError):
        parse_submissions({"nope": 1}, "AAPL", "Apple", 1, SINCE)


def test_sec_provider_reports_unknown_symbol_and_continues():
    def www(request):
        return httpx.Response(200, json=TICKERS)

    def data(request):
        assert request.url.path == "/submissions/CIK0000320193.json"
        return httpx.Response(200, content=json.dumps(SUBMISSIONS))

    provider = SecProvider(http(www, "https://www.sec.gov"), http(data, "https://data.sec.gov"))
    result = provider.fetch_filings(["ZZZZ", "AAPL"], SINCE)
    assert len(result.articles) == 1
    assert result.errors[0][0] == "ZZZZ" and "not in SEC" in str(result.errors[0][1])


def test_sec_auth_error_stops_the_run():
    def data(request):
        return httpx.Response(403)

    provider = SecProvider(
        http(lambda r: httpx.Response(200, json=TICKERS), "https://www.sec.gov"),
        http(data, "https://data.sec.gov"),
    )
    provider._tickers = {"AAPL": (1, "A"), "MSFT": (2, "M")}
    provider._tickers_at = 1e18
    result = provider.fetch_filings(["AAPL", "MSFT"], SINCE)
    assert len(result.errors) == 1 and isinstance(result.errors[0][1], ProviderAuthError)
