"""Federal Reserve press releases and speeches, from the public RSS feeds.

https://www.federalreserve.gov/feeds/feeds.htm  Feed text is untrusted: parsed with defusedxml
and cleaned before storage.
"""

from datetime import UTC
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.market.bars import RejectedRow
from app.news.normalize import NewsFetch, RawArticle
from app.providers.base import HttpJsonClient, ProviderDataError, ProviderError

BASE_URL = "https://www.federalreserve.gov"
FEEDS = ("/feeds/press_all.xml", "/feeds/speeches_and_testimony.xml")
USER_AGENT = "MarketOS/0.1 (paper trading research)"


def fetch_feeds(http: HttpJsonClient, feeds: tuple[str, ...] = FEEDS) -> NewsFetch:
    result = NewsFetch()
    for path in feeds:
        try:
            articles, rejected = parse_feed(http.get_text(path))
        except ProviderError as exc:
            exc.endpoint = exc.endpoint or path
            result.errors.append((path, exc))
            continue
        result.articles.extend(articles)
        result.rejected.extend(rejected)
    return result


def parse_feed(xml_text: str) -> tuple[list[RawArticle], list[RejectedRow]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ProviderDataError(f"fed feed is not valid XML: {type(exc).__name__}") from exc
    articles: list[RawArticle] = []
    rejected: list[RejectedRow] = []
    for item in root.iter("item"):
        fields = {child.tag: (child.text or "") for child in item}
        try:
            articles.append(_parse_item(fields))
        except (KeyError, ValueError, TypeError) as exc:
            rejected.append(RejectedRow(f"{type(exc).__name__}: {exc}", str(fields)[:300]))
    return articles, rejected


def _parse_item(f: dict[str, str]) -> RawArticle:
    published = parsedate_to_datetime(f["pubDate"])
    if published.tzinfo is None:
        # RFC 822 "-0000" means the zone is unknown; guessing would shift availability.
        raise ValueError("pubDate has no timezone")
    link = f["link"].strip()
    return RawArticle(
        external_id=(f.get("guid") or link).strip(),
        url=link,
        title=f["title"],
        summary=f.get("description", ""),
        published_at=published.astimezone(UTC),
        raw={k: f.get(k) for k in ("guid", "pubDate", "category")},
    )
