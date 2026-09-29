"""Rule-based grouping of articles into events.

An article joins an open event when they concern the same thing and are close in time:
  * they share a ticker (or, with no tickers on either side, the same category and a country),
  * and their titles share at least two words and overlap by 30% or more (Jaccard).
The best match wins. Filings never join or accept other articles: each filing is its own event,
because two 8-Ks from one company are two different events even when their titles match.

This is deliberately simple and explainable. Embeddings or an LLM can replace it later, and
`events.method` records which one made a given event.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.events.score import Member
from app.news.dedup import jaccard

SIMILARITY_THRESHOLD = 0.3
MIN_SHARED_WORDS = 2


@dataclass
class Bucket:
    """An open event during a clustering pass."""

    event_id: UUID
    members: list[Member] = field(default_factory=list)

    @property
    def is_filing(self) -> bool:
        return self.members[0].category == "filing"

    @property
    def tickers(self) -> set[str]:
        return {t for m in self.members for t in m.tickers}

    @property
    def countries(self) -> set[str]:
        return {c for m in self.members for c in m.countries}

    @property
    def last_published(self):
        return max(m.published_at for m in self.members)


def match(member: Member, bucket: Bucket, window: timedelta) -> float | None:
    """Similarity if the article belongs in the bucket, else None."""
    if member.category == "filing" or bucket.is_filing:
        return None
    if abs(member.published_at - bucket.last_published) > window:
        return None
    tickers = bucket.tickers
    if member.tickers or tickers:
        if not member.tickers & tickers:
            return None
    elif not (
        member.countries & bucket.countries and member.category == bucket.members[0].category
    ):
        return None
    best = 0.0
    for other in bucket.members:
        if len(member.tokens & other.tokens) >= MIN_SHARED_WORDS:
            best = max(best, jaccard(member.tokens, other.tokens))
    return best if best >= SIMILARITY_THRESHOLD else None


def best_bucket(
    member: Member, buckets: Iterable[Bucket], window: timedelta
) -> tuple[Bucket, float] | None:
    found: tuple[Bucket, float] | None = None
    for bucket in buckets:
        score = match(member, bucket, window)
        if score is not None and (found is None or score > found[1]):
            found = (bucket, score)
    return found
