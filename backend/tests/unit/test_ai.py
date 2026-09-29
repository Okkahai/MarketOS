import json
from decimal import Decimal as D

import httpx
import pytest

from app.ai import prompts
from app.ai.context import request_hash
from app.ai.llm import TOOL_NAME, AnthropicClient, cost_usd
from app.ai.schemas import AnalysisResult, TriageResult
from app.ai.validate import check_analysis, check_triage, parse
from app.providers.base import HttpJsonClient, ProviderAuthError, ProviderRateLimited

EVENT = "11111111-1111-1111-1111-111111111111"
ART = "22222222-2222-2222-2222-222222222222"
CONTEXT = {
    "as_of": "2026-09-29T12:00:00+00:00",
    "event": {"id": EVENT, "articles": [{"id": ART, "title": "t"}]},
    "candidate_assets": [{"symbol": "AAPL"}, {"symbol": "MSFT"}],
}


def signal(**kw):
    base = dict(
        asset="AAPL", action="BUY", confidence=0.7, time_horizon="7d", thesis="Because.",
        bear_case="Could fall.", invalidation_conditions=["Closes below 100"],
        supporting_events=[EVENT], evidence=[{"source_article_id": ART, "quote_or_fact": "f"}],
        suggested_stop_loss_pct=5, suggested_position_size_pct=4,
    )  # fmt: skip
    return {**base, **kw}


def result(*signals, **kw):
    base = dict(
        event_id=EVENT,
        event_assessment={"summary": "s", "market_relevance": "high", "expected_horizon": "days"},
        signals=list(signals), no_trade_reason=None,
    )  # fmt: skip
    return {**base, **kw}


def check(data, max_signals=3):
    obj, errors = parse(AnalysisResult, data)
    assert obj is not None, errors
    return check_analysis(obj, CONTEXT, max_signals)


# --- schema and validation ------------------------------------------------------------------


def test_valid_analysis_passes():
    assert check(result(signal())) == []


def test_no_trade_is_valid_only_with_a_reason():
    assert check(result(no_trade_reason="Already priced in.")) == []
    assert "no no_trade_reason" in check(result())[0]


@pytest.mark.parametrize(
    "bad,expected",
    [
        (signal(asset="TSLA"), "not a candidate"),
        (signal(supporting_events=["33333333-3333-3333-3333-333333333333"]), "unknown event"),
        (signal(evidence=[{"source_article_id": "x", "quote_or_fact": "f"}]), "unknown article"),
        (signal(thesis=""), "thesis is required"),
        (signal(bear_case=" "), "bear_case is required"),
        (signal(invalidation_conditions=[]), "invalidation_conditions is required"),
        (signal(suggested_stop_loss_pct=None), "needs suggested_stop_loss_pct"),
        (signal(suggested_stop_loss_pct=0), "needs suggested_stop_loss_pct"),
    ],
)
def test_business_rules(bad, expected):
    assert expected in " ".join(check(result(bad)))


def test_hold_needs_no_thesis_or_stop():
    hold = signal(action="HOLD", thesis="", bear_case="", invalidation_conditions=[],
                  suggested_stop_loss_pct=None)  # fmt: skip
    assert check(result(hold)) == []


def test_duplicate_asset_and_too_many_signals_and_wrong_event():
    assert "appears twice" in " ".join(check(result(signal(), signal())))
    two = result(signal(), signal(asset="MSFT"))
    assert "at most 1 allowed" in " ".join(check(two, max_signals=1))
    assert "event_id does not match" in " ".join(check(result(signal(), event_id="other")))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["signals"][0].update(confidence=1.5),
        lambda d: d["signals"][0].update(action="YOLO"),
        lambda d: d["signals"][0].update(suggested_position_size_pct=150),
        lambda d: d["signals"][0].update(extra_field=1),
        lambda d: d.pop("event_assessment"),
    ],
)
def test_type_errors_are_reported_in_words(mutate):
    data = result(signal())
    mutate(data)
    obj, errors = parse(AnalysisResult, data)
    assert obj is None and errors


def test_triage_checks():
    ok, _ = parse(TriageResult, {"event_id": EVENT, "relevant": True, "reason": "r",
                                 "candidate_symbols": ["AAPL"]})  # fmt: skip
    assert check_triage(ok, CONTEXT) == []
    bad, _ = parse(TriageResult, {"event_id": EVENT, "relevant": True, "reason": "r",
                                  "candidate_symbols": ["ZZZ"]})  # fmt: skip
    assert "unknown candidate" in check_triage(bad, CONTEXT)[0]


def test_json_schema_is_generated_from_the_models():
    schema = AnalysisResult.model_json_schema()
    assert schema["additionalProperties"] is False and "signals" in schema["properties"]


# --- cost and cache key ---------------------------------------------------------------------


def test_cost_from_configured_prices():
    prices = {"m": {"input": D("3"), "output": D("15")}}
    assert cost_usd(prices, "m", 1000, 500) == D("0.010500")
    with pytest.raises(KeyError):
        cost_usd(prices, "other", 1, 1)


def test_request_hash_ignores_as_of_but_not_facts_or_model():
    a = request_hash("analysis", "m", "v1", CONTEXT)
    assert a == request_hash("analysis", "m", "v1", {**CONTEXT, "as_of": "later"})
    assert a != request_hash("analysis", "m2", "v1", CONTEXT)
    assert a != request_hash("triage", "m", "v1", CONTEXT)
    assert a != request_hash("analysis", "m", "v1", {**CONTEXT, "candidate_assets": []})


def test_prompts_treat_data_as_untrusted():
    for text in (prompts.TRIAGE_SYSTEM, prompts.ANALYSIS_SYSTEM):
        assert "untrusted" in text and "<data>" in text and "paper-trading" in text


# --- the Anthropic client -------------------------------------------------------------------


def client(handler):
    inner = httpx.Client(
        base_url="https://x.test", transport=httpx.MockTransport(handler),
        headers={"x-api-key": "k"},
    )  # fmt: skip
    return AnthropicClient(
        HttpJsonClient("anthropic", "https://x.test", client=inner, max_retries=0)
    )


def call(c):
    return c.complete(model="m", system="s", user="u", schema={"type": "object"}, max_tokens=100)


def test_forced_tool_call_is_sent_and_parsed():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["path"] = request.url.path
        return httpx.Response(200, text=json.dumps({
            "model": "m-2026", "stop_reason": "tool_use",
            "usage": {"input_tokens": 120, "output_tokens": 40},
            "content": [{"type": "text", "text": "ignored"},
                        {"type": "tool_use", "name": TOOL_NAME, "input": {"confidence": 0.72}}],
        }))  # fmt: skip

    reply = call(client(handler))
    assert seen["path"] == "/v1/messages"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert seen["body"]["messages"] == [{"role": "user", "content": "u"}]
    assert reply.data == {"confidence": 0.72} and isinstance(reply.data["confidence"], float)
    assert (reply.input_tokens, reply.output_tokens, reply.model) == (120, 40, "m-2026")


@pytest.mark.parametrize("stop", ["max_tokens", "refusal", "end_turn"])
def test_truncated_refused_or_missing_output_gives_no_data(stop):
    def handler(request):
        content = [{"type": "tool_use", "name": TOOL_NAME, "input": {"a": 1}}]
        if stop == "end_turn":  # finished, but never called the tool
            content = [{"type": "text", "text": "no tool"}]
        return httpx.Response(200, json={"stop_reason": stop, "usage": {}, "content": content})

    reply = call(client(handler))
    assert reply.data is None and reply.refused == (stop == "refusal")


def test_auth_and_rate_limit_errors_are_typed():
    with pytest.raises(ProviderAuthError):
        call(client(lambda r: httpx.Response(401, json={})))
    with pytest.raises(ProviderRateLimited):
        call(client(lambda r: httpx.Response(429, json={})))
