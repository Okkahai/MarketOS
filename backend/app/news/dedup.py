"""Duplicate detection across sources.

Two articles are duplicates when they share a canonical URL, have the same normalised title,
or (for titles of at least five words) their word sets overlap by 80% or more. Paraphrases of
the same event are not duplicates: grouping those is the event layer's job.

Filings are compared by URL only. Two 8-Ks from the same company can have identical titles and
still be different filings.
"""

import uuid
from dataclasses import dataclass

from app.news.text import content_hash

_STOPWORDS = frozenset(
    "the a an of to in on for and at as by with from is are was were be it its this that".split()
)
MIN_TOKENS_FOR_SIMILARITY = 5
MIN_TOKENS_FOR_SAME_TITLE = 3
SIMILARITY_THRESHOLD = 0.8


@dataclass(frozen=True, slots=True)
class Candidate:
    id: uuid.UUID
    canonical_url: str
    title_norm: str
    text_dedup: bool  # False for filings

    @property
    def tokens(self) -> frozenset[str]:
        return token_set(self.title_norm)


def token_set(title_norm: str) -> frozenset[str]:
    return frozenset(t for t in title_norm.split() if t not in _STOPWORDS)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def find_duplicate(
    *, canonical_url: str, title_norm: str, text_dedup: bool, pool: list[Candidate]
) -> tuple[uuid.UUID, str] | None:
    """The first (earliest) pool entry this article duplicates, and why. Pool is oldest first."""
    for other in pool:
        if other.canonical_url == canonical_url:
            return other.id, "same_url"
    if not text_dedup:
        return None
    tokens = token_set(title_norm)
    same_title_ok = len(title_norm.split()) >= MIN_TOKENS_FOR_SAME_TITLE
    my_hash = content_hash(title_norm)
    for other in pool:
        if not other.text_dedup:
            continue
        if same_title_ok and content_hash(other.title_norm) == my_hash:
            return other.id, "same_title"
        if (
            len(tokens) >= MIN_TOKENS_FOR_SIMILARITY
            and len(other.tokens) >= MIN_TOKENS_FOR_SIMILARITY
            and jaccard(tokens, other.tokens) >= SIMILARITY_THRESHOLD
        ):
            return other.id, "similar_title"
    return None
