"""Replaying history through the same code that runs live.

A ReplayClock walks the window step by step. At each step the analyst sees only what existed
then (articles and bars filtered on available_at <= the clock), its signals go into an isolated
portfolio, and the paper engine runs exactly as it does live: exits, risk verdicts, fills at the
first bar after the decision, snapshot. Nothing is called on the network.

Claude is refused: a hosted model has read the future, so its replayed calls would be
hindsight. The rules analyst is deterministic and sees only the context it is given.
"""

import json
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.analyze import Replay, StopRun, Tally, _process_event
from app.ai.context import build_context
from app.ai.rules_llm import RulesClient
from app.analytics import metrics
from app.analytics.portfolio import performance
from app.core.clock import FixedClock, LiveClock, ensure_utc
from app.core.config import Settings
from app.core.money import quantize_money
from app.events.build import load_members
from app.events.score import build_state
from app.jobs.runner import run_job
from app.models import (
    BacktestRun,
    CashLedger,
    Event,
    Order,
    Portfolio,
    PortfolioSnapshot,
    Position,
    RiskDecision,
    Signal,
    Trade,
)
from app.trading.engine import Tally as TradeTally
from app.trading.engine import paper_step
from app.trading.rules import RiskConfig
from app.trading.state import portfolio_view

logger = logging.getLogger(__name__)


class BacktestError(Exception):
    pass


def _events_to_analyse(
    session: Session,
    settings: Settings,
    t: datetime,
    since: datetime,
    analysed: dict[uuid.UUID, datetime],
) -> list[uuid.UUID]:
    """Events that gained a visible article since the previous step, judged as they were at t."""
    window = timedelta(hours=settings.event_window_hours)
    ids = session.scalars(
        select(Event.id).where(Event.available_at <= t, Event.available_at > t - window)
    ).all()
    members = load_members(session, list(ids), t)  # only articles available at t
    ranked = []
    for event_id in ids:
        found = members.get(event_id)
        if not found or max(m.available_at for m in found) <= since:
            continue  # nothing new became visible since the previous step
        state = build_state(found)
        if state.importance < settings.ai_min_event_importance:
            continue
        last = analysed.get(event_id)
        if last is not None and t - last < timedelta(hours=settings.ai_reanalyze_hours):
            continue
        ranked.append((state.importance, str(event_id), event_id))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return [r[2] for r in ranked[: settings.ai_max_events_per_run]]


def run_backtest(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    start: datetime,
    end: datetime,
    step_hours: int = 24,
    name: str | None = None,
) -> uuid.UUID:
    start, end = ensure_utc(start), ensure_utc(end)
    if settings.ai_provider != "rules":
        raise BacktestError(
            "backtests need AI_PROVIDER=rules: a hosted model has seen the future, so replaying "
            "it would be hindsight"
        )
    if not start < end <= LiveClock().now():
        raise BacktestError("the window must end in the past and start before it ends")
    if step_hours < 1:
        raise BacktestError("step_hours must be at least 1")

    cfg = replace(RiskConfig.from_settings(settings), crypto_fill_interval="1d")
    capital = quantize_money(Decimal(settings.paper_initial_capital))
    with session_factory() as session:
        run = BacktestRun(
            name=name or f"{start.date()} to {end.date()}", start_at=start, end_at=end,
            step_hours=step_hours, initial_capital=capital,
            params={"risk": cfg.snapshot(), "analyst": settings.ai_analysis_model},
        )  # fmt: skip
        session.add(run)
        session.flush()
        portfolio = Portfolio(
            name=f"backtest-{run.id}", mode="backtest", starting_capital=capital, cash=capital,
            backtest_run_id=run.id, created_at=start,
        )  # fmt: skip
        session.add(portfolio)
        session.flush()
        session.add(
            CashLedger(
                portfolio_id=portfolio.id, kind="deposit", amount=capital, balance_after=capital
            )
        )
        session.commit()
        run_id, portfolio_id = run.id, portfolio.id

    try:
        with run_job(session_factory, "backtest", clock=LiveClock()) as job:
            with session_factory() as session:
                portfolio = session.get(Portfolio, portfolio_id)
                assert portfolio is not None
                counts = _replay(
                    session, settings, cfg, portfolio, run_id, job, start, end, step_hours
                )
                summary = _summarise(session, portfolio, counts)
            job.details = {"backtest_run_id": str(run_id), **counts}
    except Exception as exc:
        with session_factory() as session:
            r = session.get(BacktestRun, run_id)
            assert r is not None
            r.status, r.error, r.finished_at = "failed", str(exc)[:2000], func.now()
            session.commit()
        raise
    with session_factory() as session:
        r = session.get(BacktestRun, run_id)
        assert r is not None
        r.status, r.summary, r.finished_at = "succeeded", summary, func.now()
        session.commit()
    return run_id


def _replay(
    session: Session,
    settings: Settings,
    cfg: RiskConfig,
    portfolio: Portfolio,
    run_id: uuid.UUID,
    job: Any,
    start: datetime,
    end: datetime,
    step_hours: int,
) -> dict[str, int]:
    clock = FixedClock(start)
    step = timedelta(hours=step_hours)
    replay, analyst = Replay(run_id), RulesClient()
    analysed: dict[uuid.UUID, datetime] = {}
    ai, trading = Tally(), TradeTally()
    steps = 0
    t, since = start, start - step
    while t <= end:
        clock.advance_to(t)
        now = clock.now()
        view = portfolio_view(session, settings, now, portfolio, cfg)
        for event_id in _events_to_analyse(session, settings, now, since, analysed):
            context = build_context(session, event_id, now, view)
            if context is None or not context["candidate_assets"]:
                continue
            analysed[event_id] = now
            ai.events += 1
            try:
                _process_event(session, settings, analyst, job, event_id, context, now, ai, replay)
            except StopRun as stop:  # nothing in the rules analyst can raise this
                logger.warning("replay analysis stopped: %s", stop)
        paper_step(session, portfolio, cfg, now, trading, snapshot_every=timedelta(0))
        since, t, steps = now, t + step, steps + 1
    return {"steps": steps, "events_analysed": ai.events, "signals": ai.signals,
            "invalid_analyses": ai.invalid}  # fmt: skip


def _summarise(session: Session, portfolio: Portfolio, counts: dict[str, int]) -> dict[str, Any]:
    snaps = list(
        session.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.portfolio_id == portfolio.id)
            .order_by(PortfolioSnapshot.as_of)
        )
    )
    perf, benchmarks = performance(session, snaps)
    closed = session.scalars(
        select(Position.realized_pnl).where(
            Position.portfolio_id == portfolio.id, Position.closed_at.is_not(None)
        )
    ).all()

    def count(model: Any, *where: Any) -> int:
        return session.scalar(select(func.count()).select_from(model).where(*where)) or 0

    pid = portfolio.id
    decisions = dict(
        session.execute(
            select(RiskDecision.decision, func.count())
            .where(RiskDecision.portfolio_id == pid)
            .group_by(RiskDecision.decision)
        ).all()
    )
    summary = {
        **counts,
        "portfolio": perf,
        "benchmarks": benchmarks,
        "trades": metrics.trade_stats([float(p) for p in closed]),
        "decisions": decisions,
        "orders_filled": count(Order, Order.portfolio_id == pid, Order.status == "filled"),
        "orders_expired": count(Order, Order.portfolio_id == pid, Order.status == "expired"),
        "trade_count": count(Trade, Trade.portfolio_id == pid),
        "signals_journalled": count(Signal, Signal.backtest_run_id == portfolio.backtest_run_id),
        "final_cash": str(portfolio.cash),
        "notes": (
            "Replayed with the rules analyst on the news and prices stored in this database. "
            "Coverage is limited to the articles that were collected then; a window with little "
            "news produces few signals. Past results do not predict future ones."
        ),
    }
    return json.loads(json.dumps(summary, default=str))  # datetimes to ISO text for JSONB
