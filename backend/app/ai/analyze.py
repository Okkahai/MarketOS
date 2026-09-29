"""Scheduled AI analysis: triage with a cheap model, then a full analysis of relevant events.

Cost control, in order: only events above AI_MIN_EVENT_IMPORTANCE, at most AI_MAX_EVENTS_PER_RUN
per run, one analysis per event per AI_REANALYZE_HOURS, identical requests are not repeated, and
nothing is called once today's estimated spend reaches AI_DAILY_BUDGET_USD. A model with no
configured price is never called. Every call is stored, valid or not; a valid analysis also
writes its signals to the journal whether or not anything trades.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai import prompts
from app.ai.context import BUILDER_VERSION, build_context, canonical, request_hash, sha256
from app.ai.llm import LlmClient, cost_usd
from app.ai.schemas import AnalysisResult, TriageResult
from app.ai.validate import check_analysis, check_triage, parse
from app.core.clock import Clock, LiveClock
from app.core.config import Settings
from app.jobs.runner import JobContext, run_job
from app.models import AiAnalysis, Asset, ContextSnapshot, Event, Signal
from app.providers.base import ProviderAuthError, ProviderError, ProviderRateLimited
from app.providers.failures import record_failure
from app.trading.state import portfolio_view

logger = logging.getLogger(__name__)

DIRECTION = {
    "STRONG_BUY": "long", "BUY": "long", "HOLD": "flat", "AVOID": "flat",
    "REDUCE": "exit", "SELL": "exit",
}  # fmt: skip


class StopRun(Exception):
    """Ends the run early with a reason (budget reached, provider refused our key)."""


@dataclass
class Tally:
    events: int = 0
    triaged_out: int = 0
    analysed: int = 0
    signals: int = 0
    cache_hits: int = 0
    invalid: int = 0
    errors: int = 0


def spent_today(session: Session, now: datetime) -> Decimal:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(
        select(func.coalesce(func.sum(AiAnalysis.estimated_cost_usd), 0)).where(
            AiAnalysis.as_of >= start
        )
    )
    return Decimal(total)


def run_ai_analysis(
    session_factory: sessionmaker[Session],
    settings: Settings,
    llm: LlmClient | None,
    *,
    clock: Clock | None = None,
) -> uuid.UUID:
    clock = clock or LiveClock()
    with run_job(session_factory, "ai_analysis", provider="anthropic", clock=clock) as ctx:
        skip = _why_skip(settings, llm)
        if skip:
            ctx.status = "skipped"
            ctx.details = {"reason": skip}
            return ctx.run_id
        assert llm is not None
        tally = Tally()
        stopped: str | None = None
        with session_factory() as session:
            try:
                _run(session, settings, llm, ctx, clock.now(), tally)
            except StopRun as stop:
                stopped = str(stop)
        ctx.items_fetched = tally.events
        ctx.items_written = tally.signals
        ctx.details = {**tally.__dict__}
        if stopped:
            ctx.details["stopped"] = stopped
            ctx.status = "partial"
        elif tally.errors or tally.invalid:
            ctx.status = "partial"
        return ctx.run_id


def _why_skip(settings: Settings, llm: LlmClient | None) -> str | None:
    if llm is None:
        return "ANTHROPIC_API_KEY is not set"
    for model in {settings.ai_triage_model, settings.ai_analysis_model}:
        price = settings.ai_model_prices.get(model)
        if not price or "input" not in price or "output" not in price:
            return f"no price configured for {model}; set AI_MODEL_PRICES so the budget can apply"
    return None


def _run(
    session: Session, settings: Settings, llm: LlmClient, ctx: JobContext, now: datetime, t: Tally
) -> None:
    if spent_today(session, now) >= settings.ai_daily_budget_usd:
        raise StopRun("daily budget reached before any call")
    recent = now - timedelta(hours=settings.ai_reanalyze_hours)
    already = select(AiAnalysis.event_id).where(
        AiAnalysis.stage == "analysis", AiAnalysis.as_of >= recent
    )
    events = session.scalars(
        select(Event)
        .where(
            Event.status == "open",
            Event.available_at <= now,
            Event.importance >= settings.ai_min_event_importance,
            Event.id.not_in(already),
        )
        .order_by(Event.importance.desc(), Event.last_updated_at.desc())
        .limit(settings.ai_max_events_per_run)
    ).all()
    portfolio = portfolio_view(session, settings, now)
    for event in events:
        t.events += 1
        context = build_context(session, event.id, now, portfolio)
        if context is None or not context["candidate_assets"]:
            continue  # nothing priced to recommend: no call, no cost
        _process_event(session, settings, llm, ctx, event.id, context, now, t)


def _process_event(
    session: Session,
    settings: Settings,
    llm: LlmClient,
    ctx: JobContext,
    event_id: uuid.UUID,
    context: dict[str, Any],
    now: datetime,
    t: Tally,
) -> None:
    triage = _call(session, settings, llm, ctx, event_id, context, now, "triage", TriageResult, t)
    if triage is None:
        return
    result, _ = triage
    if not result.relevant:
        t.triaged_out += 1
        return
    if result.candidate_symbols:
        keep = set(result.candidate_symbols)
        context = {
            **context,
            "candidate_assets": [a for a in context["candidate_assets"] if a["symbol"] in keep],
        }
    analysis = _call(
        session, settings, llm, ctx, event_id, context, now, "analysis", AnalysisResult, t
    )
    if analysis is None:
        return
    result, analysis_id = analysis
    t.analysed += 1
    _store_signals(session, analysis_id, result, context, now, t)


def _call(
    session: Session,
    settings: Settings,
    llm: LlmClient,
    ctx: JobContext,
    event_id: uuid.UUID,
    context: dict[str, Any],
    now: datetime,
    stage: str,
    schema_cls: type[BaseModel],
    t: Tally,
) -> tuple[Any, uuid.UUID | None] | None:
    """One model call, stored. Returns (validated result, analysis id) or None on any failure."""
    model = settings.ai_triage_model if stage == "triage" else settings.ai_analysis_model
    key = request_hash(stage, model, prompts.PROMPT_VERSION, context)
    cached = session.scalar(
        select(AiAnalysis)
        .where(AiAnalysis.request_hash == key, AiAnalysis.validation_status == "valid")
        .limit(1)
    )
    if cached is not None:
        t.cache_hits += 1
        if stage == "triage":  # the earlier answer stands; an analysis is never repeated
            return schema_cls.model_validate(cached.parsed_output), cached.id
        return None
    if spent_today(session, now) >= settings.ai_daily_budget_usd:
        raise StopRun("daily budget reached")

    payload_text = canonical(context)
    snapshot = ContextSnapshot(
        as_of=now,
        payload=context,
        payload_sha256=sha256(payload_text),
        builder_version=BUILDER_VERSION,
    )
    session.add(snapshot)
    session.flush()
    row = dict(
        context_snapshot_id=snapshot.id, event_id=event_id, stage=stage, as_of=now, model=model,
        prompt_version=prompts.PROMPT_VERSION, request_hash=key, run_id=ctx.run_id,
    )  # fmt: skip
    system = prompts.TRIAGE_SYSTEM if stage == "triage" else prompts.ANALYSIS_SYSTEM
    user = f"<data>\n{payload_text}\n</data>"
    try:
        reply = llm.complete(
            model=model, system=system, user=user, schema=schema_cls.model_json_schema(),
            max_tokens=settings.ai_max_output_tokens,
        )  # fmt: skip
    except ProviderError as exc:
        t.errors += 1
        session.add(
            AiAnalysis(**row, validation_status="error", validation_errors=[str(exc)[:500]])
        )
        session.commit()
        record_failure(session, ctx.run_id, "anthropic", stage, exc, now)
        if isinstance(exc, ProviderAuthError | ProviderRateLimited):
            raise StopRun(f"stopped after {type(exc).__name__}") from exc
        return None

    cost = cost_usd(settings.ai_model_prices, model, reply.input_tokens, reply.output_tokens)
    metrics = dict(
        model_version=reply.model, input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens, estimated_cost_usd=cost, latency_ms=reply.latency_ms,
    )  # fmt: skip
    status, errors, parsed = "valid", [], None
    if reply.refused:
        status, errors = "refused", ["the model refused to answer"]
    elif reply.data is None:
        status, errors = "invalid", [f"no structured output (stop_reason={reply.stop_reason})"]
    else:
        obj, errors = parse(schema_cls, reply.data)
        if obj is not None:
            errors = (
                check_triage(obj, context)
                if stage == "triage"
                else check_analysis(obj, context, settings.ai_max_signals_per_analysis)
            )
        if errors:
            status = "invalid"
        else:
            parsed = obj
    analysis = AiAnalysis(
        **row, **metrics, raw_output=reply.data, validation_status=status,
        validation_errors=errors or None,
        parsed_output=parsed.model_dump(mode="json") if parsed is not None else None,
    )  # fmt: skip
    session.add(analysis)
    session.commit()
    if status != "valid":
        t.invalid += 1
        return None
    return parsed, analysis.id


def _store_signals(
    session: Session,
    analysis_id: uuid.UUID | None,
    result: AnalysisResult,
    context: dict[str, Any],
    now: datetime,
    t: Tally,
) -> None:
    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    prices = {a["symbol"]: a for a in context["candidate_assets"]}
    for s in result.signals:
        snap = prices[s.asset]
        session.add(
            Signal(
                analysis_id=analysis_id,
                asset_id=assets[s.asset].id,
                generated_at=now,
                action=s.action,
                direction=DIRECTION[s.action],
                confidence=Decimal(str(s.confidence)).quantize(Decimal("0.001")),
                time_horizon=s.time_horizon,
                reference_price=Decimal(snap["last_close"]),
                reference_price_ts=datetime.fromisoformat(snap["last_close_ts"]),
                thesis=s.thesis,
                bull_case=s.bull_case,
                bear_case=s.bear_case,
                key_catalysts=s.key_catalysts,
                risks=s.risks,
                invalidation_conditions=s.invalidation_conditions,
                evidence=[e.model_dump() for e in s.evidence],
                supporting_event_ids=[uuid.UUID(e) for e in s.supporting_events],
                suggested_position_size_pct=s.suggested_position_size_pct,
                suggested_stop_loss_pct=s.suggested_stop_loss_pct,
                suggested_take_profit_pct=s.suggested_take_profit_pct,
                portfolio_context=context["portfolio"],
                mode="live_paper",
            )  # fmt: skip
        )
        t.signals += 1
    session.commit()
