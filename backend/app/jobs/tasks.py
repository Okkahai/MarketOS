import logging

from app.ai.analyze import run_ai_analysis
from app.analytics.evaluate import run_evaluate_signals
from app.core.clock import LiveClock
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.events.build import run_cluster_events
from app.jobs.celery_app import celery_app
from app.jobs.runner import run_job
from app.market.compute import run_compute_indicators
from app.market.ingest import run_ingest
from app.monitor import health_report
from app.news.ingest import run_news_source, tracked_symbols
from app.providers import fed
from app.providers.registry import (
    build_coinbase,
    build_fed,
    build_llm,
    build_sec,
    build_tiingo,
)
from app.trading.engine import run_paper_cycle
from app.trading.reconcile import run_reconcile

logger = logging.getLogger(__name__)


@celery_app.task(name="marketos.heartbeat")
def heartbeat() -> str:
    """Proves the worker, beat, broker and database are wired together."""
    with run_job(get_session_factory(), "heartbeat") as ctx:
        ctx.items_written = 0
        return str(ctx.run_id)


@celery_app.task(name="marketos.ingest_stock_daily")
def ingest_stock_daily() -> str:
    settings = get_settings()
    tiingo = build_tiingo(settings)
    fetcher = (
        (
            lambda asset, start, end: tiingo.fetch_daily(
                asset.provider_symbols["tiingo"], start.date(), end.date()
            )
        )
        if tiingo
        else None
    )
    return str(
        run_ingest(
            get_session_factory(),
            settings,
            job_name="ingest_stock_daily",
            provider="tiingo",
            interval="1d",
            asset_classes=("stock", "etf"),
            fetcher=fetcher,
            missing_credentials_hint="Set TIINGO_API_KEY.",
        )  # fmt: skip
    )


def _crypto(interval: str, job_name: str) -> str:
    settings = get_settings()
    coinbase = build_coinbase(settings)
    return str(
        run_ingest(
            get_session_factory(),
            settings,
            job_name=job_name,
            provider="coinbase",
            interval=interval,
            asset_classes=("crypto",),
            fetcher=lambda asset, start, end: coinbase.fetch_candles(
                asset.provider_symbols["coinbase"], interval, start, end
            ),
        )  # fmt: skip
    )


@celery_app.task(name="marketos.ingest_crypto_daily")
def ingest_crypto_daily() -> str:
    return _crypto("1d", "ingest_crypto_daily")


@celery_app.task(name="marketos.ingest_crypto_1m")
def ingest_crypto_1m() -> str:
    return _crypto("1m", "ingest_crypto_1m")


@celery_app.task(name="marketos.compute_indicators")
def compute_indicators() -> str:
    return str(run_compute_indicators(get_session_factory(), get_settings()))


@celery_app.task(name="marketos.ingest_news_tiingo")
def ingest_news_tiingo() -> str:
    settings = get_settings()
    factory = get_session_factory()
    tiingo = build_tiingo(settings)
    fetcher = None
    if tiingo:
        with factory() as session:
            tickers = tracked_symbols(session, "tiingo", "stock", "etf")
        fetcher = lambda since: tiingo.fetch_news(tickers, since)  # noqa: E731
    return str(
        run_news_source(
            factory,
            settings,
            source_key="tiingo_news",
            fetcher=fetcher,
            missing_credentials_hint="Set TIINGO_API_KEY.",
        )  # fmt: skip
    )


@celery_app.task(name="marketos.ingest_news_sec")
def ingest_news_sec() -> str:
    settings = get_settings()
    factory = get_session_factory()
    provider = build_sec(settings)
    fetcher = None
    if provider:
        with factory() as session:
            symbols = tracked_symbols(session, "tiingo", "stock")
        fetcher = lambda since: provider.fetch_filings(symbols, since)  # noqa: E731
    return str(
        run_news_source(
            factory,
            settings,
            source_key="sec_edgar",
            fetcher=fetcher,
            missing_credentials_hint="Set SEC_USER_AGENT to 'Your Name you@example.com'.",
        )  # fmt: skip
    )


@celery_app.task(name="marketos.ingest_news_fed")
def ingest_news_fed() -> str:
    settings = get_settings()
    http = build_fed(settings)
    return str(
        run_news_source(
            get_session_factory(),
            settings,
            source_key="fed_rss",
            fetcher=lambda since: fed.fetch_feeds(http),
        )  # fmt: skip
    )


@celery_app.task(name="marketos.cluster_events")
def cluster_events() -> str:
    return str(run_cluster_events(get_session_factory(), get_settings()))


@celery_app.task(name="marketos.ai_analysis")
def ai_analysis() -> str:
    settings = get_settings()
    return str(run_ai_analysis(get_session_factory(), settings, build_llm(settings)))


@celery_app.task(name="marketos.paper_cycle")
def paper_cycle() -> str:
    return str(run_paper_cycle(get_session_factory(), get_settings()))


@celery_app.task(name="marketos.reconcile")
def reconcile() -> str:
    return str(run_reconcile(get_session_factory()))


@celery_app.task(name="marketos.evaluate_signals")
def evaluate_signals() -> str:
    return str(run_evaluate_signals(get_session_factory()))


@celery_app.task(name="marketos.health_check")
def health_check() -> str:
    """Logs every open alert at ERROR so log-based alerting has something to match on."""
    settings = get_settings()
    with run_job(get_session_factory(), "health_check") as ctx:
        with get_session_factory()() as session:
            report = health_report(session, settings, LiveClock().now())
        for alert in report["alerts"]:
            logger.error("alert %(code)s %(subject)s: %(message)s", alert)
        ctx.items_written = len(report["alerts"])
        return str(ctx.run_id)
