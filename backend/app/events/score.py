"""Turns the articles of an event into its state and score. Pure: same members, same result.

The score is a transparent sum, not a model. Every component is written to score_details so a
reviewer can see why an event scored what it did. Weights are starting judgements; Phase 8
should replace them with measured hit rates.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

METHOD_VERSION = "rules-1"

# What kind of event is usually big, before any corroboration.
CATEGORY_BASE = {
    "central_bank": Decimal("0.60"),
    "earnings": Decimal("0.55"),
    "macro": Decimal("0.50"),
    "geopolitics": Decimal("0.45"),
    "filing": Decimal("0.35"),
    "commodities": Decimal("0.35"),
    "crypto": Decimal("0.35"),
    "company": Decimal("0.30"),
    "other": Decimal("0.10"),
}
# How long an event of this kind is expected to matter.
HORIZON = {
    "central_bank": "weeks",
    "geopolitics": "weeks",
    "earnings": "days",
    "macro": "days",
    "filing": "days",
    "commodities": "days",
    "crypto": "days",
    "company": "days",
    "other": "intraday",
}
PER_EXTRA_PUBLISHER = Decimal("0.10")
MAX_EXTRA_PUBLISHERS = 3
PER_EXTRA_ARTICLE = Decimal("0.05")
MAX_EXTRA_ARTICLES = 3
CONFIDENCE_RELIABILITY = Decimal("0.70")
PER_CORROBORATING_PUBLISHER = Decimal("0.15")
MAX_CORROBORATING = 2
_Q = Decimal("0.001")


@dataclass(frozen=True, slots=True)
class Member:
    """One article of an event, with what clustering and scoring need from it."""

    article_id: uuid.UUID
    title: str
    summary: str
    category: str
    publisher: str  # the outlet when the provider names one, else the source key
    reliability: Decimal
    published_at: datetime
    available_at: datetime
    tickers: frozenset[str]
    countries: frozenset[str]
    tokens: frozenset[str]
    is_duplicate: bool


@dataclass(frozen=True, slots=True)
class EventState:
    title: str
    summary: str
    category: str
    importance: Decimal
    confidence: Decimal
    countries: list[str]
    ticker_counts: dict[str, int]
    horizon: str
    first_seen_at: datetime
    last_updated_at: datetime
    available_at: datetime
    details: dict = field(default_factory=dict)


def _clamp01(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value)).quantize(_Q)


def build_state(members: list[Member]) -> EventState:
    if not members:
        raise ValueError("an event needs at least one article")
    ordered = sorted(members, key=lambda m: (m.published_at, str(m.article_id)))
    lead = next((m for m in ordered if not m.is_duplicate), ordered[0])
    # Most common category wins; a tie goes to the earliest article.
    counts = Counter(m.category for m in ordered)
    top = max(counts.values())
    category = next(m.category for m in ordered if counts[m.category] == top)

    publishers = {m.publisher for m in ordered}
    extra_publishers = min(len(publishers) - 1, MAX_EXTRA_PUBLISHERS)
    extra_articles = min(len(ordered) - 1, MAX_EXTRA_ARTICLES)
    base = CATEGORY_BASE[category]
    importance = _clamp01(
        base + PER_EXTRA_PUBLISHER * extra_publishers + PER_EXTRA_ARTICLE * extra_articles
    )
    max_reliability = max(m.reliability for m in ordered)
    corroboration = min(len(publishers) - 1, MAX_CORROBORATING)
    confidence = _clamp01(
        CONFIDENCE_RELIABILITY * max_reliability + PER_CORROBORATING_PUBLISHER * corroboration
    )
    tickers = Counter(t for m in ordered for t in m.tickers)
    return EventState(
        title=lead.title,
        summary=lead.summary[:1000],
        category=category,
        importance=importance,
        confidence=confidence,
        countries=sorted({c for m in ordered for c in m.countries}),
        ticker_counts=dict(sorted(tickers.items())),
        horizon=HORIZON[category],
        first_seen_at=ordered[0].published_at,
        last_updated_at=max(m.available_at for m in ordered),
        available_at=min(m.available_at for m in ordered),
        details={
            "articles": len(ordered),
            "publishers": sorted(publishers),
            "importance": {
                "category_base": str(base),
                "extra_publishers": extra_publishers,
                "extra_articles": extra_articles,
            },
            "confidence": {
                "max_source_reliability": str(max_reliability),
                "corroborating_publishers": corroboration,
            },
        },
    )
