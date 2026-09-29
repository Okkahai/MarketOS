"""The MVP asset universe. Idempotent: existing rows are left as they are.

Run with `python -m app.market.seed` (the compose `migrate` service does this after migrating).
Sector names follow GICS.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models import Asset


def _row(symbol: str, asset_class: str, name: str, exchange: str, provider: str, **kw) -> dict:
    # Every row carries the same keys: SQLAlchemy needs that for a multi-row INSERT.
    return {
        "symbol": symbol, "asset_class": asset_class, "name": name, "exchange": exchange,
        "sector": None, "is_benchmark": False, "provider_symbols": {provider: symbol}, **kw,
    }  # fmt: skip


def _stock(symbol: str, name: str, exchange: str, sector: str) -> dict:
    return _row(symbol, "stock", name, exchange, "tiingo", sector=sector)


def _etf(symbol: str, name: str, exchange: str) -> dict:
    return _row(symbol, "etf", name, exchange, "tiingo", is_benchmark=True)


def _crypto(symbol: str, name: str, *, benchmark: bool = False) -> dict:
    return _row(symbol, "crypto", name, "Coinbase", "coinbase", is_benchmark=benchmark)


UNIVERSE: list[dict] = [
    _stock("AAPL", "Apple Inc.", "NASDAQ", "Information Technology"),
    _stock("MSFT", "Microsoft Corporation", "NASDAQ", "Information Technology"),
    _stock("NVDA", "NVIDIA Corporation", "NASDAQ", "Information Technology"),
    _stock("AMZN", "Amazon.com, Inc.", "NASDAQ", "Consumer Discretionary"),
    _stock("GOOGL", "Alphabet Inc. Class A", "NASDAQ", "Communication Services"),
    _stock("META", "Meta Platforms, Inc.", "NASDAQ", "Communication Services"),
    _stock("TSLA", "Tesla, Inc.", "NASDAQ", "Consumer Discretionary"),
    _stock("JPM", "JPMorgan Chase & Co.", "NYSE", "Financials"),
    _stock("AMD", "Advanced Micro Devices, Inc.", "NASDAQ", "Information Technology"),
    _stock("NFLX", "Netflix, Inc.", "NASDAQ", "Communication Services"),
    _etf("SPY", "SPDR S&P 500 ETF Trust", "NYSE Arca"),
    _etf("QQQ", "Invesco QQQ Trust", "NASDAQ"),
    _crypto("BTC-USD", "Bitcoin", benchmark=True),
    _crypto("ETH-USD", "Ethereum"),
]


def seed_assets(session: Session) -> int:
    inserted = session.execute(
        insert(Asset)
        .values(UNIVERSE)
        .on_conflict_do_nothing(index_elements=["symbol"])
        .returning(Asset.id)
    ).all()
    session.commit()
    return len(inserted)


if __name__ == "__main__":
    with get_session_factory()() as db:
        print(f"seeded {seed_assets(db)} new assets")  # noqa: T201
