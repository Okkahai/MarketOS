import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.events.cluster import Bucket, best_bucket, match
from app.events.score import Member, build_state
from app.news.dedup import token_set
from app.news.text import normalize_title

T0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
WINDOW = timedelta(hours=48)


def member(title, *, tickers=("AAPL",), minutes=0, category="company", publisher="wire",
           reliability="0.6", countries=(), dup=False, avail=None) -> Member:  # fmt: skip
    published = T0 + timedelta(minutes=minutes)
    return Member(
        article_id=uuid.uuid4(), title=title, summary="", category=category, publisher=publisher,
        reliability=D(reliability), published_at=published, available_at=avail or published,
        tickers=frozenset(tickers), countries=frozenset(countries),
        tokens=token_set(normalize_title(title)), is_duplicate=dup,
    )  # fmt: skip


def bucket(*members: Member) -> Bucket:
    return Bucket(uuid.uuid4(), list(members))


# --- clustering on fixture headlines ------------------------------------------------------------

APPLE_A = "Apple shares jump after strong iPhone sales in China"
APPLE_B = "Apple stock rises on strong iPhone demand in China"


def test_same_story_different_words_clusters():
    assert match(member(APPLE_B, minutes=30), bucket(member(APPLE_A)), WINDOW) >= 0.3


def test_different_apple_stories_stay_apart():
    other = member("Apple unveils a new iPhone lineup", minutes=30)
    assert match(other, bucket(member(APPLE_A)), WINDOW) is None


def test_same_words_but_different_company_never_cluster():
    msft = member(APPLE_B.replace("Apple", "Microsoft"), tickers=("MSFT",), minutes=30)
    assert match(msft, bucket(member(APPLE_A)), WINDOW) is None


def test_far_apart_in_time_does_not_cluster():
    late = member(APPLE_B, minutes=60 * 60)
    assert match(late, bucket(member(APPLE_A)), WINDOW) is None


def test_shared_ticker_is_enough_when_some_tickers_differ():
    both = member(APPLE_B, tickers=("AAPL", "MSFT"), minutes=30)
    assert match(both, bucket(member(APPLE_A)), WINDOW) is not None


FED_A = "Fed holds interest rates steady as inflation cools"
FED_B = "Federal Reserve holds interest rates steady, inflation cools"


def fed(title=FED_A, *, tickers=(), category="central_bank", country="US", minutes=0):
    return member(title, tickers=tickers, category=category, countries=(country,), minutes=minutes)


def test_tickerless_items_need_same_category_and_country():
    assert match(fed(FED_B, minutes=20), bucket(fed()), WINDOW) is not None
    assert match(fed(FED_B, category="macro", minutes=20), bucket(fed()), WINDOW) is None
    assert match(fed(FED_B, country="JP", minutes=20), bucket(fed()), WINDOW) is None


def test_ticker_and_tickerless_do_not_mix():
    assert match(fed(tickers=("SPY",), minutes=5), bucket(fed()), WINDOW) is None


def test_filings_never_cluster():
    text = "Apple Inc. (AAPL) filed 8-K: other events"
    f1 = member(text, category="filing")
    f2 = member(text, category="filing", minutes=10)
    assert match(f2, bucket(f1), WINDOW) is None
    assert match(member(text, minutes=10), bucket(f1), WINDOW) is None


def test_best_bucket_picks_highest_similarity():
    weak = bucket(member("Apple iPhone sales in China beat"))
    strong = bucket(member(APPLE_A))
    found = best_bucket(member(APPLE_B, minutes=30), [weak, strong], WINDOW)
    assert found and found[0] is strong


# --- scoring ------------------------------------------------------------------------------------


def test_single_article_state():
    s = build_state([member("Fed holds rates", category="central_bank", reliability="1")])
    assert s.importance == D("0.600") and s.confidence == D("0.700")
    assert s.horizon == "weeks" and s.details["articles"] == 1


def test_corroboration_raises_score_with_caps():
    ms = [member(APPLE_A, publisher=f"outlet{i}", minutes=i) for i in range(8)]
    s = build_state(ms)
    # 0.30 base + 3 extra publishers * 0.10 + 3 extra articles * 0.05, both capped
    assert s.importance == D("0.750")
    assert s.confidence == D("0.720")  # 0.7 * 0.6 + 2 * 0.15
    assert len(s.details["publishers"]) == 8


def test_same_publisher_copies_do_not_add_publisher_credit():
    ms = [member(APPLE_A, minutes=i) for i in range(2)]
    assert build_state(ms).importance == D("0.350")  # one extra article only


def test_state_is_order_independent_and_uses_earliest_original_as_lead():
    early = member("First headline about Apple", minutes=0)
    late = member("Second headline about Apple", minutes=30)
    copy = member("Copy headline about Apple", minutes=-5, dup=True)
    a = build_state([late, copy, early])
    b = build_state([early, copy, late])
    assert a == b and a.title == "First headline about Apple"
    assert a.first_seen_at == copy.published_at


def test_availability_follows_articles_not_publication():
    early = member("A", minutes=0, avail=T0 + timedelta(hours=5))
    late = member("B about Apple", minutes=10, avail=T0 + timedelta(hours=6))
    s = build_state([early, late])
    assert s.available_at == T0 + timedelta(hours=5)
    assert s.last_updated_at == T0 + timedelta(hours=6)


def test_category_is_majority_then_earliest():
    ms = [member("x a", category="earnings"), member("x b", category="company", minutes=1),
          member("x c", category="company", minutes=2)]  # fmt: skip
    assert build_state(ms).category == "company"
    tie = [member("x a", category="earnings"), member("x b", category="company", minutes=1)]
    assert build_state(tie).category == "earnings"


def test_empty_event_is_an_error():
    with pytest.raises(ValueError):
        build_state([])
