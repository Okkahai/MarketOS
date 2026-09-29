"""What the model must return. The JSON Schema sent to the model is generated from these
classes and its reply is validated against the same classes, so the two cannot drift."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID"]
Horizon = Literal["1d", "3d", "7d", "30d"]
EventHorizon = Literal["intraday", "days", "weeks", "months"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventAssessment(_Strict):
    summary: str = Field(max_length=600)
    market_relevance: Literal["high", "medium", "low", "none"]
    expected_horizon: EventHorizon


class Evidence(_Strict):
    source_article_id: str = Field(max_length=64)
    quote_or_fact: str = Field(max_length=500)


class SignalOut(_Strict):
    asset: str = Field(max_length=32)
    action: Action
    confidence: float = Field(ge=0, le=1)
    time_horizon: Horizon
    thesis: str = Field(default="", max_length=1500)
    bull_case: str = Field(default="", max_length=1000)
    bear_case: str = Field(default="", max_length=1000)
    key_catalysts: list[str] = Field(default_factory=list, max_length=10)
    risks: list[str] = Field(default_factory=list, max_length=10)
    supporting_events: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=10)
    # Advisory. The risk engine applies its own limits whatever these say.
    suggested_position_size_pct: Decimal | None = Field(default=None, ge=0, le=100)
    suggested_stop_loss_pct: Decimal | None = Field(default=None, ge=0, le=100)
    suggested_take_profit_pct: Decimal | None = Field(default=None, ge=0, le=100)


class AnalysisResult(_Strict):
    event_id: str = Field(max_length=64)
    event_assessment: EventAssessment
    signals: list[SignalOut] = Field(default_factory=list, max_length=10)
    no_trade_reason: str | None = Field(default=None, max_length=600)


class TriageResult(_Strict):
    event_id: str = Field(max_length=64)
    relevant: bool
    reason: str = Field(max_length=200)
    candidate_symbols: list[str] = Field(default_factory=list, max_length=10)
