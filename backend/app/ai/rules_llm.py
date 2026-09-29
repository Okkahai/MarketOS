"""A free analyst: the same LlmClient interface, answered by fixed rules instead of a model.

It reads the same context a model would (event, headlines, price context, portfolio) and returns
the same structured output, so snapshots, validation, the journal, risk rules and paper trading
work unchanged. Deterministic: the same context always gives the same answer, which also makes
it the only analyst whose recommendations a backtest can reproduce.

It is a crude reader. It counts positive and negative cue words in headlines, then checks them
against price context (overbought, already moved, fighting the trend). It cannot judge
magnitude, surprise or sarcasm, and every recommendation says so in its bear case.
"""

import json
import re
from typing import Any

from app.ai.llm import LlmResult
from app.core.config import RULES_TRIAGE_MODEL as TRIAGE_MODEL  # noqa: E402

POSITIVE = (
    "beats", "beat estimates", "tops estimates", "raises guidance", "raised guidance",
    "raises forecast", "upgrade", "upgraded", "record revenue", "record profit", "record high",
    "surges", "soars", "jumps", "rallies", "strong demand", "buyback", "share repurchase",
    "dividend increase", "raises dividend", "approval", "approved", "wins contract", "partnership",
    "expands", "rate cut", "cuts rates", "cut rates", "eases", "outperform",
)  # fmt: skip
NEGATIVE = (
    "misses", "missed estimates", "falls short", "cuts guidance", "lowers guidance",
    "lowered guidance", "cuts forecast", "downgrade", "downgraded", "plunges", "tumbles",
    "sinks", "slumps", "drops", "lawsuit", "sues", "probe", "investigation", "subpoena",
    "recall", "layoffs", "job cuts", "bankruptcy", "default", "fraud", "resigns", "halts",
    "delays", "warns", "warning", "rate hike", "raises rates", "hikes rates", "tightening",
    "underperform", "ban", "fine",
)  # fmt: skip
SIGNAL_THRESHOLD = 0.34
STRONG_THRESHOLD = 0.67
MAX_CANDIDATES = 3


def _cues(text: str, words: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return [w for w in words if re.search(rf"\b{re.escape(w)}\b", low)]


def read_event(context: dict[str, Any]) -> dict[str, Any]:
    """Tone of the event from its original (non-copy) headlines and excerpts, in [-1, 1]."""
    pos = neg = 0
    hits: list[dict[str, Any]] = []
    for a in context["event"]["articles"]:
        if a.get("is_copy"):
            continue
        text = f"{a['title']}. {a.get('excerpt', '')}"
        p, n = _cues(text, POSITIVE), _cues(text, NEGATIVE)
        pos, neg = pos + len(p), neg + len(n)
        if p or n:
            hits.append({"id": a["id"], "title": a["title"], "pos": p, "neg": n})
    total = pos + neg
    return {"pos": pos, "neg": neg, "score": (pos - neg) / total if total else 0.0, "hits": hits}


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def _held(context: dict[str, Any]) -> set[str]:
    portfolio = context.get("portfolio") or {}
    return {p["symbol"] for p in portfolio.get("positions", [])}


def triage(context: dict[str, Any]) -> dict[str, Any]:
    tone = read_event(context)
    symbols = [a["symbol"] for a in context["candidate_assets"]][:MAX_CANDIDATES]
    relevant = bool(tone["hits"]) and abs(tone["score"]) >= 0.2 and bool(symbols)
    reason = (
        f"{tone['pos']} positive and {tone['neg']} negative cue words in the headlines"
        if relevant
        else "no clear positive or negative wording in the headlines"
    )
    return {
        "event_id": context["event"]["id"], "relevant": relevant, "reason": reason,
        "candidate_symbols": symbols if relevant else [],
    }  # fmt: skip


def _stop_pct(atr_pct: float | None) -> float:
    if atr_pct is None:
        return 8.0
    return round(min(8.0, max(3.0, 2 * atr_pct * 100)), 1)


def _decide(
    score: float, importance: float, asset: dict[str, Any], held: bool
) -> tuple[str, list[str]]:
    """Action plus the reasons a guard changed it. Guards only ever soften a buy."""
    ind = asset.get("indicators") or {}
    rsi, gap = _f(ind.get("rsi_14")), _f(ind.get("sma_50_gap_pct"))
    ret5 = _f((asset.get("returns") or {}).get("5d"))
    if score >= SIGNAL_THRESHOLD:
        notes = []
        if rsi is not None and rsi >= 75:
            notes.append(f"RSI 14 is {rsi:.0f}, overbought, so the news may be priced in")
        if ret5 is not None and ret5 > 0.12:
            notes.append(f"the price already rose {ret5 * 100:.1f}% in 5 days")
        if gap is not None and gap < -0.10:
            notes.append(f"the price is {abs(gap) * 100:.1f}% below its 50-day average")
        if notes:
            return "HOLD", notes
        return ("STRONG_BUY" if score >= STRONG_THRESHOLD and importance >= 0.6 else "BUY"), []
    if score <= -SIGNAL_THRESHOLD:
        if not held:
            return "AVOID", []
        return ("SELL" if score <= -STRONG_THRESHOLD else "REDUCE"), []
    return "HOLD", []


def _confidence(score: float, importance: float, event_conf: float, asset: dict[str, Any]) -> float:
    conf = 0.30 + 0.25 * abs(score) + 0.25 * importance + 0.10 * event_conf
    gap = _f((asset.get("indicators") or {}).get("sma_50_gap_pct"))
    if gap is not None and (gap > 0) == (score > 0):
        conf += 0.05  # price trend agrees with the headline tone
    return round(min(0.85, conf), 3)


def analyse(context: dict[str, Any]) -> dict[str, Any]:
    event = context["event"]
    tone = read_event(context)
    importance, event_conf = float(event["importance"]), float(event["confidence"])
    held = _held(context)
    signals = []
    if tone["hits"] and abs(tone["score"]) >= SIGNAL_THRESHOLD:
        for asset in context["candidate_assets"][:MAX_CANDIDATES]:
            signals.append(_signal(context, tone, asset, importance, event_conf, held))
    summary = f"{event['title']}"[:600]
    relevance = "high" if importance >= 0.6 else "medium" if importance >= 0.4 else "low"
    result: dict[str, Any] = {
        "event_id": event["id"],
        "event_assessment": {
            "summary": summary, "market_relevance": relevance, "expected_horizon": "days",
        },
        "signals": signals,
    }  # fmt: skip
    if not signals:
        result["no_trade_reason"] = (
            "The headlines do not lean clearly positive or negative "
            f"({tone['pos']} positive, {tone['neg']} negative cue words)."
        )
    return result


def _signal(
    context: dict[str, Any], tone: dict[str, Any], asset: dict[str, Any], importance: float,
    event_conf: float, held: bool,
) -> dict[str, Any]:  # fmt: skip
    symbol = asset["symbol"]
    action, notes = _decide(tone["score"], importance, asset, symbol in held)
    ind = asset.get("indicators") or {}
    ret5 = _f((asset.get("returns") or {}).get("5d"))
    facts = []
    if _f(ind.get("rsi_14")) is not None:
        facts.append(f"RSI 14 is {float(ind['rsi_14']):.0f}")
    if _f(ind.get("sma_50_gap_pct")) is not None:
        facts.append(
            f"the price is {float(ind['sma_50_gap_pct']) * 100:+.1f}% versus its 50-day average"
        )
    if ret5 is not None:
        facts.append(f"{ret5 * 100:+.1f}% over 5 days")
    tone_text = (
        f"{tone['pos']} positive and {tone['neg']} negative cue words across "
        f"{len(tone['hits'])} headlines"
    )
    thesis = f"Headline tone for {symbol}: {tone_text}."
    if facts:
        thesis += " Price context: " + ", ".join(facts) + "."
    if notes:
        thesis += " Held back because " + "; ".join(notes) + "."
    stop = _stop_pct(_f(ind.get("atr_14_pct")))
    is_buy = action in ("BUY", "STRONG_BUY")
    return {
        "asset": symbol,
        "action": action,
        "confidence": _confidence(tone["score"], importance, event_conf, asset),
        "time_horizon": "7d",
        "thesis": thesis,
        "bull_case": "Positive news flow could keep attracting buyers over the coming days."
        if tone["score"] > 0 else "",
        "bear_case": (
            "This is a word-count reading of headlines: it cannot judge how large or how "
            "surprising the news is, and the market may already have priced it in."
        ),
        "key_catalysts": [context["event"]["title"][:200]],
        "risks": [
            "Headline wording can mislead",
            "A market-wide move can swamp the stock-specific news",
        ],
        "supporting_events": [context["event"]["id"]],
        "evidence": [
            {"source_article_id": h["id"], "quote_or_fact": h["title"][:500]}
            for h in tone["hits"][:3]
        ],
        "invalidation_conditions": [
            f"The price closes {stop}% or more below the entry",
            "Later reporting contradicts the tone of these headlines",
        ],
        "suggested_position_size_pct": None,
        "suggested_stop_loss_pct": stop if is_buy else None,
        "suggested_take_profit_pct": round(2 * stop, 1) if is_buy else None,
    }  # fmt: skip


class RulesClient:
    """Implements the LlmClient protocol. Costs nothing and makes no network call."""

    def complete(
        self, *, model: str, system: str, user: str, schema: dict, max_tokens: int
    ) -> LlmResult:
        context = json.loads(user.removeprefix("<data>\n").removesuffix("\n</data>"))
        data = triage(context) if model == TRIAGE_MODEL else analyse(context)
        return LlmResult(
            data=json.loads(json.dumps(data)), input_tokens=0, output_tokens=0, latency_ms=0,
            model=model, stop_reason="end_turn",
        )  # fmt: skip
