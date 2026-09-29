"""Checks on model output beyond its types. A failed check stores the reply and makes no signal."""

from typing import Any

from pydantic import ValidationError

from app.ai.schemas import AnalysisResult, TriageResult

BUYS = ("BUY", "STRONG_BUY")


def parse(model_cls: type, data: dict[str, Any]) -> tuple[Any | None, list[str]]:
    """The validated object, or the type errors in plain words."""
    try:
        return model_cls.model_validate(data), []
    except ValidationError as exc:
        return None, [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:10]


def check_triage(result: TriageResult, context: dict[str, Any]) -> list[str]:
    errors = []
    if result.event_id != context["event"]["id"]:
        errors.append("event_id does not match the event that was analysed")
    known = {a["symbol"] for a in context["candidate_assets"]}
    errors += [f"unknown candidate symbol {s}" for s in result.candidate_symbols if s not in known]
    return errors


def check_analysis(result: AnalysisResult, context: dict[str, Any], max_signals: int) -> list[str]:
    event_id = context["event"]["id"]
    known_assets = {a["symbol"] for a in context["candidate_assets"]}
    known_articles = {a["id"] for a in context["event"]["articles"]}
    errors: list[str] = []
    if result.event_id != event_id:
        errors.append("event_id does not match the event that was analysed")
    if not result.signals and not (result.no_trade_reason or "").strip():
        errors.append("no signals and no no_trade_reason")
    if len(result.signals) > max_signals:
        errors.append(f"{len(result.signals)} signals, at most {max_signals} allowed")
    seen: set[str] = set()
    for i, s in enumerate(result.signals):
        where = f"signals[{i}] ({s.asset})"
        if s.asset not in known_assets:
            errors.append(f"{where}: asset is not a candidate")
        if s.asset in seen:
            errors.append(f"{where}: asset appears twice")
        seen.add(s.asset)
        if any(e != event_id for e in s.supporting_events):
            errors.append(f"{where}: supporting_events cites an unknown event")
        if any(ev.source_article_id not in known_articles for ev in s.evidence):
            errors.append(f"{where}: evidence cites an unknown article")
        if s.action != "HOLD":
            for name in ("thesis", "bear_case"):
                if not getattr(s, name).strip():
                    errors.append(f"{where}: {name} is required for {s.action}")
            if not s.invalidation_conditions:
                errors.append(f"{where}: invalidation_conditions is required for {s.action}")
        if s.action in BUYS and not (s.suggested_stop_loss_pct and s.suggested_stop_loss_pct > 0):
            errors.append(f"{where}: a buy needs suggested_stop_loss_pct above 0")
    return errors
