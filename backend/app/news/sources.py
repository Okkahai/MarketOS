"""The news sources MarketOS knows about. Idempotent seed, safe to run on every start."""

from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import NewsSource

# Reliability is a starting judgement about how much weight the AI should give an item from
# this source, not a measured number. Phase 8 replaces it with measured hit rates.
SOURCES: list[dict] = [
    {
        "key": "tiingo_news", "name": "Tiingo News", "kind": "api",
        "base_url": "https://api.tiingo.com/tiingo/news", "reliability_weight": Decimal("0.600"),
        "terms_note": "Aggregated third-party headlines. Free plan is personal, non-commercial "
        "use; check your plan before relying on it.",
    },
    {
        "key": "sec_edgar", "name": "SEC EDGAR", "kind": "filing",
        "base_url": "https://data.sec.gov/submissions", "reliability_weight": Decimal("1.000"),
        "terms_note": "Public US government data. Needs a User-Agent with contact and at most "
        "10 requests per second.",
    },
    {
        "key": "fed_rss", "name": "Federal Reserve", "kind": "macro",
        "base_url": "https://www.federalreserve.gov/feeds", "reliability_weight": Decimal("1.000"),
        "terms_note": "Public US government feeds: press releases and speeches.",
    },
]  # fmt: skip


def ensure_sources(session: Session) -> None:
    stmt = insert(NewsSource).values(SOURCES).on_conflict_do_nothing(index_elements=["key"])
    session.execute(stmt)
    session.commit()
