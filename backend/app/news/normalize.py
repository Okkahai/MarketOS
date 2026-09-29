"""One common article shape for every source. Adapters produce RawArticle; this validates it."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.market.bars import RejectedRow
from app.news.classify import classify
from app.news.entities import extract_companies, extract_countries, extract_tickers
from app.news.text import (
    canonicalize_url,
    clean_text,
    content_hash,
    normalize_title,
    scrub_json,
)
from app.providers.base import ProviderError

# A source claiming publication more than this far ahead of our clock is wrong, not early.
MAX_FUTURE_SKEW = timedelta(minutes=10)


class ArticleRejected(ValueError):
    """The item is unusable. It is recorded in provider_failures and never stored."""


@dataclass(frozen=True, slots=True)
class RawArticle:
    external_id: str
    url: str
    title: str
    published_at: datetime
    summary: str = ""
    provider_tickers: tuple[str, ...] = ()
    fixed_category: str | None = None  # set by sources whose items are always one kind (filings)
    text_dedup: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsFetch:
    """What a source adapter returns. Errors are kept so one bad company does not hide the rest."""

    articles: list[RawArticle] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    errors: list[tuple[str | None, ProviderError]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NormalizedArticle:
    external_id: str
    url: str
    canonical_url: str
    title: str
    title_norm: str
    summary: str
    published_at: datetime
    collected_at: datetime
    available_at: datetime
    category: str
    countries: list[str]
    companies: list[str]
    tickers: list[str]
    content_hash: str
    text_dedup: bool
    raw_payload: dict[str, Any]


def normalize(raw: RawArticle, collected_at: datetime) -> NormalizedArticle:
    """Cleans text, resolves entities and sets the timestamps.

    available_at is the later of published_at and collected_at: a decision made at time T may
    use the article only if we had it by T, and never before the source says it was out.
    """
    title = clean_text(raw.title, 500)
    if not title:
        raise ArticleRejected("empty title")
    external_id = clean_text(raw.external_id, 200)
    if not external_id:
        raise ArticleRejected("missing external id")
    if raw.published_at.tzinfo is None or raw.published_at.utcoffset() is None:
        raise ArticleRejected("published_at has no timezone")
    if raw.published_at > collected_at + MAX_FUTURE_SKEW:
        raise ArticleRejected(f"published_at {raw.published_at.isoformat()} is in the future")
    try:
        canonical = canonicalize_url(raw.url)
    except ValueError as exc:
        raise ArticleRejected(f"bad url: {exc}") from exc

    summary = clean_text(raw.summary, 2000)
    text = f"{title} {summary}"
    tickers = extract_tickers(text, raw.provider_tickers)
    companies = extract_companies(text)
    title_norm = normalize_title(title)
    if not title_norm:
        raise ArticleRejected("title has no words")
    return NormalizedArticle(
        external_id=external_id,
        url=raw.url.strip(),
        canonical_url=canonical,
        title=title,
        title_norm=title_norm[:500],
        summary=summary,
        published_at=raw.published_at,
        collected_at=collected_at,
        available_at=max(raw.published_at, collected_at),
        category=raw.fixed_category or classify(text, has_company=bool(tickers or companies)),
        countries=extract_countries(text),
        companies=companies,
        tickers=tickers,
        content_hash=content_hash(title_norm),
        text_dedup=raw.text_dedup,
        raw_payload=scrub_json(raw.raw),
    )


def normalize_all(
    raws: list[RawArticle], collected_at: datetime
) -> tuple[list[NormalizedArticle], list[RejectedRow]]:
    good: list[NormalizedArticle] = []
    rejected: list[RejectedRow] = []
    for raw in raws:
        try:
            good.append(normalize(raw, collected_at))
        except ArticleRejected as exc:
            rejected.append(RejectedRow(str(exc), str(raw.raw or raw.title)[:300]))
    return good, rejected
