"""The model client. One narrow interface so tests and the job never touch HTTP details."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from app.providers.base import HttpJsonClient

BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
TOOL_NAME = "record_result"


@dataclass(frozen=True, slots=True)
class LlmResult:
    data: dict[str, Any] | None  # the tool arguments; None when the model gave no usable output
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str | None  # as reported by the API
    stop_reason: str | None
    refused: bool = False


class LlmClient(Protocol):
    def complete(
        self, *, model: str, system: str, user: str, schema: dict, max_tokens: int
    ) -> LlmResult: ...


class AnthropicClient:
    """Messages API with a forced tool call, so the reply is JSON that matches the schema."""

    def __init__(self, http: HttpJsonClient, clock: Callable[[], float] = time.monotonic) -> None:
        self._http = http
        self._clock = clock

    def complete(
        self, *, model: str, system: str, user: str, schema: dict, max_tokens: int
    ) -> LlmResult:
        started = self._clock()
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": "Record the result in the required structure.",
                    "input_schema": schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        reply = self._http.post_json("/v1/messages", body)
        latency_ms = int((self._clock() - started) * 1000)
        usage = reply.get("usage") or {}
        stop = reply.get("stop_reason")
        data = None
        if stop not in ("refusal", "max_tokens"):  # a truncated tool call is not trustworthy
            for block in reply.get("content") or []:
                if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                    data = _plain(block.get("input"))
                    break
        return LlmResult(
            data=data if isinstance(data, dict) else None,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            latency_ms=latency_ms,
            model=reply.get("model"),
            stop_reason=stop,
            refused=stop == "refusal",
        )


def _plain(value: Any) -> Any:
    """JSON parsing yields Decimal for numbers (see HttpJsonClient); the model's output is not
    money, so store it as ordinary JSON numbers."""
    return json.loads(json.dumps(value, default=float))


def cost_usd(
    prices: dict[str, dict[str, Decimal]], model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    """Estimated cost from the configured per-million-token prices. Raises if unpriced."""
    price = prices[model]
    total = (Decimal(input_tokens) * price["input"] + Decimal(output_tokens) * price["output"]) / (
        Decimal(1_000_000)
    )
    return total.quantize(Decimal("0.000001"))
