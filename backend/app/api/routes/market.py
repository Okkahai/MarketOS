"""Read-only market data API. Prices are decimal strings; nothing is estimated or filled."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.compute import INTERVAL as INDICATOR_INTERVAL
from app.market.compute import PRIMARY_PROVIDER
from app.market.repository import get_bars
from app.models import Asset, IndicatorValue, MarketPrice

router = APIRouter(prefix="/api/v1", tags=["market"])

Interval = Literal["1m", "5m", "1h", "1d"]


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    asset_class: str
    exchange: str | None
    sector: str | None
    currency: str
    is_benchmark: bool
    is_active: bool


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal | None
    volume: Decimal
    available_at: datetime
    revision: int


class WatchlistRow(BaseModel):
    symbol: str
    name: str
    asset_class: str
    is_benchmark: bool
    provider: str
    last_close: Decimal | None
    last_bar_ts: datetime | None
    last_available_at: datetime | None
    change_pct: Decimal | None  # vs the previous daily bar, percent
    volume: Decimal | None


class IndicatorOut(BaseModel):
    name: str
    ts: datetime
    value: Decimal


def _asset(db: Session, symbol: str) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail=f"unknown asset {symbol}")
    return asset


@router.get("/assets", response_model=list[AssetOut])
def list_assets(db: Annotated[Session, Depends(get_db)]) -> list[Asset]:
    return list(db.scalars(select(Asset).order_by(Asset.asset_class, Asset.symbol)))


@router.get("/assets/{symbol}", response_model=AssetOut)
def get_asset(symbol: str, db: Annotated[Session, Depends(get_db)]) -> Asset:
    return _asset(db, symbol)


@router.get("/assets/{symbol}/intervals", response_model=list[Interval])
def asset_intervals(symbol: str, db: Annotated[Session, Depends(get_db)]) -> list[str]:
    """Intervals that have stored bars, so the UI only offers charts that exist."""
    asset = _asset(db, symbol)
    found = db.scalars(
        select(MarketPrice.interval)
        .where(
            MarketPrice.asset_id == asset.id,
            MarketPrice.provider == PRIMARY_PROVIDER[asset.asset_class],
        )
        .distinct()
    )
    order = ["1m", "5m", "1h", "1d"]
    return sorted(found, key=order.index)


@router.get("/assets/{symbol}/bars", response_model=list[BarOut])
def asset_bars(
    symbol: str,
    db: Annotated[Session, Depends(get_db)],
    interval: Interval = "1d",
    limit: Annotated[int, Query(ge=1, le=1000)] = 300,
    as_of: AwareDatetime | None = None,
) -> list[MarketPrice]:
    """Bars known at as_of (default: now), oldest first. Revised bars show the revision that
    was current at as_of."""
    asset = _asset(db, symbol)
    return get_bars(
        db, asset.id, interval, PRIMARY_PROVIDER[asset.asset_class],
        as_of or datetime.now(UTC), limit,
    )  # fmt: skip


@router.get("/assets/{symbol}/indicators", response_model=list[IndicatorOut])
def asset_indicators(symbol: str, db: Annotated[Session, Depends(get_db)]) -> list[IndicatorValue]:
    """Newest stored value of each indicator (daily bars)."""
    asset = _asset(db, symbol)
    latest_ts = db.scalar(
        select(IndicatorValue.ts)
        .where(IndicatorValue.asset_id == asset.id, IndicatorValue.interval == INDICATOR_INTERVAL)
        .order_by(IndicatorValue.ts.desc())
        .limit(1)
    )
    if latest_ts is None:
        return []
    return list(
        db.scalars(
            select(IndicatorValue)
            .where(
                IndicatorValue.asset_id == asset.id,
                IndicatorValue.interval == INDICATOR_INTERVAL,
                IndicatorValue.ts == latest_ts,
            )
            .order_by(IndicatorValue.name)
        )
    )


@router.get("/market/watchlist", response_model=list[WatchlistRow])
def watchlist(db: Annotated[Session, Depends(get_db)]) -> list[WatchlistRow]:
    now = datetime.now(UTC)
    rows: list[WatchlistRow] = []
    for asset in db.scalars(
        select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.asset_class, Asset.symbol)
    ):
        provider = PRIMARY_PROVIDER[asset.asset_class]
        bars = get_bars(db, asset.id, "1d", provider, now, 2)
        last = bars[-1] if bars else None
        rows.append(
            WatchlistRow(
                symbol=asset.symbol, name=asset.name, asset_class=asset.asset_class,
                is_benchmark=asset.is_benchmark, provider=provider,
                last_close=last.close if last else None,
                last_bar_ts=last.ts if last else None,
                last_available_at=last.available_at if last else None,
                change_pct=_change_pct(bars), volume=last.volume if last else None,
            )
        )  # fmt: skip
    return rows


def _change_pct(bars: list[MarketPrice]) -> Decimal | None:
    """Percent change from the previous bar. Uses adjusted closes when both bars have one, so a
    stock split is not shown as a crash."""
    if len(bars) < 2:
        return None
    prev, last = bars[-2], bars[-1]
    if prev.adj_close is not None and last.adj_close is not None:
        a, b = prev.adj_close, last.adj_close
    else:
        a, b = prev.close, last.close
    return ((b / a - 1) * 100).quantize(Decimal("0.0001"))
