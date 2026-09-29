"""The free rules analyst: tone reading, guards, confidence and output validity."""

from app.ai.rules_llm import RulesClient, analyse, read_event, triage
from app.ai.schemas import AnalysisResult, TriageResult
from app.ai.validate import check_analysis, check_triage

EVENT_ID = "e1"


def context(titles, asset=None, portfolio=None, importance="0.7", conf="0.7"):
    asset = asset or {
        "symbol": "AAPL", "asset_class": "stock", "last_close": "100",
        "returns": {"1d": "0.01", "5d": "0.02", "20d": "0.05"},
        "indicators": {"rsi_14": "55.0", "atr_14_pct": "0.02", "sma_50_gap_pct": "0.03"},
    }  # fmt: skip
    return {
        "event": {
            "id": EVENT_ID, "title": titles[0], "category": "earnings", "importance": importance,
            "confidence": conf,
            "articles": [
                {"id": f"a{i}", "title": t, "excerpt": "", "is_copy": False}
                for i, t in enumerate(titles)
            ],
        },
        "candidate_assets": [asset], "portfolio": portfolio,
    }  # fmt: skip


GOOD = ["Apple beats estimates and raises guidance", "Apple stock surges on strong demand"]
BAD = ["Apple misses estimates and cuts guidance", "Apple shares tumble after probe"]


def test_tone_counts_cues_and_ignores_copies():
    ctx = context(GOOD)
    ctx["event"]["articles"].append(
        {"id": "c", "title": "Apple surges surges", "excerpt": "", "is_copy": True}
    )
    tone = read_event(ctx)
    assert tone["neg"] == 0 and tone["score"] == 1.0 and len(tone["hits"]) == 2
    assert read_event(context(["Apple holds annual meeting"]))["score"] == 0.0


def test_triage_passes_only_clear_events_and_its_output_validates():
    ok = triage(context(GOOD))
    assert ok["relevant"] and ok["candidate_symbols"] == ["AAPL"]
    assert check_triage(TriageResult.model_validate(ok), context(GOOD)) == []
    assert not triage(context(["Apple holds annual meeting"]))["relevant"]


def test_strong_good_news_is_a_confident_buy_with_a_stop_and_valid_output():
    ctx = context(GOOD)
    out = analyse(ctx)
    sig = out["signals"][0]
    assert sig["action"] == "STRONG_BUY" and sig["confidence"] >= 0.75
    assert sig["suggested_stop_loss_pct"] == 4.0  # 2 x ATR 2%, inside 3..8
    assert sig["suggested_take_profit_pct"] == 8.0
    assert sig["evidence"][0]["source_article_id"] == "a0"
    assert check_analysis(AnalysisResult.model_validate(out), ctx, 3) == []


def test_guards_soften_a_buy():
    hot = {"symbol": "AAPL", "asset_class": "stock", "last_close": "100",
           "returns": {"5d": "0.20"}, "indicators": {"rsi_14": "82"}}  # fmt: skip
    sig = analyse(context(GOOD, asset=hot))["signals"][0]
    assert sig["action"] == "HOLD" and "overbought" in sig["thesis"]
    assert sig["suggested_stop_loss_pct"] is None
    down = {"symbol": "AAPL", "asset_class": "stock", "last_close": "100",
            "indicators": {"sma_50_gap_pct": "-0.15"}}  # fmt: skip
    assert analyse(context(GOOD, asset=down))["signals"][0]["action"] == "HOLD"


def test_bad_news_avoids_unless_held_then_reduces_or_sells():
    assert analyse(context(BAD))["signals"][0]["action"] == "AVOID"
    held = {"positions": [{"symbol": "AAPL"}]}
    assert analyse(context(BAD, portfolio=held))["signals"][0]["action"] == "SELL"
    mixed = ["Apple misses estimates", "Apple upgraded by analyst", "Apple sinks on warning"]
    out = analyse(context(mixed, portfolio=held))  # 2 negative words each vs 1 positive
    assert out["signals"][0]["action"] == "REDUCE"


def test_unclear_news_makes_no_signal_and_says_why():
    out = analyse(context(["Apple beats estimates", "Apple faces probe"]))
    assert out["signals"] == [] and "do not lean" in out["no_trade_reason"]


def test_weak_evidence_stays_below_the_trading_confidence():
    weak = analyse(context(["Apple upgraded by one analyst", "Apple faces a small fine"] +
                           ["Apple upgraded again", "Apple upgraded once more"],
                           importance="0.3", conf="0.4"))  # fmt: skip
    conf = weak["signals"][0]["confidence"]
    assert conf < 0.60, conf  # the risk engine will not trade this


def test_client_speaks_the_llm_interface_and_is_deterministic():
    import json

    client = RulesClient()
    user = "<data>\n" + json.dumps(context(GOOD)) + "\n</data>"
    a = client.complete(model="rules-analysis-1", system="", user=user, schema={}, max_tokens=1)
    b = client.complete(model="rules-analysis-1", system="", user=user, schema={}, max_tokens=1)
    assert a.data == b.data and a.input_tokens == 0 and a.data["signals"]
    t = client.complete(model="rules-triage-1", system="", user=user, schema={}, max_tokens=1)
    assert t.data["relevant"] is True
