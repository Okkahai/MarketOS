"""Builds what the model sees, as of one moment. Nothing later than as_of can get in.

Every value comes from bars, articles and events whose available_at is at or before as_of. Values
that cannot be computed are null, never estimated. The result is plain JSON-able data (numbers
as decimal strings); the caller stores it as the immutable context snapshot.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.build import load_members, state_as_of
from app.market.compute import INTERVAL, PRIMARY_PROVIDER
from app.market.indicators import compute_indicators
from app.market.repository import get_bars
from app.models import Asset, Event, EventSource, NewsArticle

BUILDER_VERSION = "ctx-1"
BARS = 260  # covers the 200-day average
MAX_CANDIDATES = 5
MAX_ARTICLES = 8
MAX_PAST_EVENTS = 3
PAST_MOVE_DAYS = 5
_PLACES = Decimal("1e-6")


def _dec(value: float | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(repr(value)).quantize(_PLACES))


def _last(series: list[float | None]) -> float | None:
    return series[-1] if series else None


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def request_hash(stage: str, model: str, prompt_version: str, payload: dict[str, Any]) -> str:
    """Cache key. as_of is left out: the same facts asked twice give the same answer."""
    body = {k: v for k, v in payload.items() if k != "as_of"}
    return sha256(f"{stage}|{model}|{prompt_version}|{canonical(body)}")


def asset_snapshot(session: Session, asset: Asset, as_of: datetime) -> dict[str, Any] | None:
    """Price context for one asset, or None when it has no usable bar yet."""
    bars = get_bars(session, asset.id, INTERVAL, PRIMARY_PROVIDER[asset.asset_class], as_of, BARS)
    if not bars:
        return None
    closes = [float(b.close) for b in bars]
    ind = compute_indicators(
        [b.ts for b in bars],
        [float(b.high) for b in bars],
        [float(b.low) for b in bars],
        closes,
        [float(b.volume) for b in bars],
    )
    last = bars[-1]
    sma50 = _last(ind["sma_50"])
    return {
        "symbol": asset.symbol,
        "asset_class": asset.asset_class,
        "last_close": format(last.close.normalize(), "f"),
        "last_close_ts": last.ts.isoformat(),
        "last_close_available_at": last.available_at.isoformat(),
        "returns": {
            "1d": _dec(_last(ind["ret_1"])),
            "5d": _dec(_last(ind["ret_5"])),
            "20d": _dec(_last(ind["ret_20"])),
        },
        "indicators": {
            "rsi_14": _dec(_last(ind["rsi_14"])),
            "atr_14_pct": _dec(_last(ind["atr_14_pct"])),
            "sma_50_gap_pct": _dec(closes[-1] / sma50 - 1) if sma50 else None,
        },
        "realized_vol_20d": _dec(_last(ind["vol_20"])),
    }


def _regime(session: Session, as_of: datetime) -> dict[str, Any]:
    spy = session.scalar(select(Asset).where(Asset.symbol == "SPY"))
    above = None
    if spy is not None:
        bars = get_bars(session, spy.id, INTERVAL, PRIMARY_PROVIDER[spy.asset_class], as_of, BARS)
        if len(bars) >= 200:
            sma200 = sum(b.close for b in bars[-200:]) / 200
            above = bars[-1].close > sma200
    return {"spy_above_sma200": above, "vix_proxy": None}


def _event_tickers(session: Session, event_id: uuid.UUID, as_of: datetime) -> set[str]:
    rows = session.scalars(
        select(NewsArticle.tickers)
        .join(EventSource, EventSource.article_id == NewsArticle.id)
        .where(EventSource.event_id == event_id, NewsArticle.available_at <= as_of)
    )
    return {t for tickers in rows for t in tickers}


def _past_events(
    session: Session, event: Event, tickers: list[str], assets: dict[str, Asset], as_of: datetime
) -> list[dict[str, Any]]:
    """Earlier events about the same assets and what the first asset did afterwards, using only
    bars available by as_of. A move that is not yet observable is null."""
    stmt = (
        select(Event)
        .where(
            Event.id != event.id,
            Event.available_at < as_of - timedelta(days=1),
            Event.category == event.category,
        )
        .order_by(Event.first_seen_at.desc())
        .limit(30)
    )
    out: list[dict[str, Any]] = []
    for past in session.scalars(stmt):
        past_tickers = _event_tickers(session, past.id, as_of)
        shared = [t for t in tickers if t in past_tickers]
        if tickers and not shared:
            continue
        move = None
        asset = assets.get(shared[0]) if shared else None
        if asset is not None:
            bars = get_bars(
                session, asset.id, INTERVAL, PRIMARY_PROVIDER[asset.asset_class], as_of, BARS
            )
            start = next(
                (
                    b
                    for b in bars
                    if b.ts >= past.first_seen_at.replace(hour=0, minute=0, second=0, microsecond=0)
                ),
                None,
            )
            if start is not None:
                end_ts = start.ts + timedelta(days=PAST_MOVE_DAYS)
                end = next((b for b in bars if b.ts >= end_ts), None)
                if end is not None and start.close:
                    move = str(((end.close / start.close) - 1).quantize(_PLACES))
        out.append(
            {
                "title": past.title,
                "date": past.first_seen_at.date().isoformat(),
                "asset": shared[0] if shared else None,
                "asset_move_after_5d": move,
            }
        )
        if len(out) == MAX_PAST_EVENTS:
            break
    return out


def build_context(session: Session, event_id: uuid.UUID, as_of: datetime) -> dict[str, Any] | None:
    """The model input for one event, or None when the event did not exist yet at as_of."""
    state = state_as_of(session, event_id, as_of)
    event = session.get(Event, event_id)
    if state is None or event is None:
        return None
    members = sorted(
        load_members(session, [event_id], as_of)[event_id], key=lambda m: m.published_at
    )
    articles = [
        {
            "id": str(m.article_id),
            "source": m.publisher,
            "published_at": m.published_at.isoformat(),
            "available_at": m.available_at.isoformat(),
            "title": m.title,
            "excerpt": m.summary[:600],
            "is_copy": m.is_duplicate,
        }
        for m in members[-MAX_ARTICLES:]
    ]
    assets = {a.symbol: a for a in session.scalars(select(Asset).where(Asset.is_active.is_(True)))}
    linked = [s for s in state.ticker_counts if s in assets]
    linked.sort(key=lambda s: -state.ticker_counts[s])
    if not linked:  # a market-wide event: the benchmarks are the candidates
        linked = sorted(s for s, a in assets.items() if a.is_benchmark)
    candidates = []
    for symbol in linked[:MAX_CANDIDATES]:
        snap = asset_snapshot(session, assets[symbol], as_of)
        if snap is not None:
            candidates.append(snap)
    return {
        "as_of": as_of.isoformat(),
        "event": {
            "id": str(event_id),
            "title": state.title,
            "category": state.category,
            "importance": str(state.importance),
            "confidence": str(state.confidence),
            "first_seen_at": state.first_seen_at.isoformat(),
            "articles": articles,
        },
        "candidate_assets": candidates,
        "portfolio": None,  # arrives with the paper portfolio (Phase 6)
        "related_past_events": _past_events(session, event, linked, assets, as_of),
        "market_regime": _regime(session, as_of),
    }
