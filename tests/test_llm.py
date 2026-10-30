import json
from dataclasses import replace

import pytest

from fishmarket.config import DEFAULT
from fishmarket.agents.agent1 import PLAN_TOOL
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import LLM, BudgetExceeded, LLMError, ReplayMiss, RunCtx, compute_cost, load_pricing

HAIKU = "claude-haiku-5-5"
SYS, USER = "system prompt", json.dumps({"request_brief": {"species": "Gulf shrimp", "region": "Gulf"}})


def make(cfg, mode="auto", **kw):
    stub = StubAnthropicClient(fake_llm(cfg), **kw)
    return LLM(cfg, mode=mode, client=stub), stub


def other(tag):
    return json.dumps({"request_brief": {"species": "Cod", "region": "Northeast", "tag": tag}})


def call(llm, ctx=None, user=USER, max_tokens=600):
    return llm.call("agent1", SYS, user, PLAN_TOOL, HAIKU, max_tokens, ctx or RunCtx())


def test_cost_comes_from_usage_and_pricing(cfg):
    llm, _ = make(cfg)
    r = call(llm)
    assert r["cache"] == "miss"
    assert r["cost_usd"] == pytest.approx((1500 * 0.10 + 300 * 0.50) / 1e6)


def test_cache_hit_costs_zero_and_makes_no_request(cfg):
    llm, stub = make(cfg)
    first = call(llm)
    second = call(llm)
    assert second["cache"] == "hit" and second["cost_usd"] == 0.0
    assert second["tool_input"] == first["tool_input"]
    assert len(stub.requests) == 1
    rows = [json.loads(x) for x in cfg.LEDGER_PATH.read_text().splitlines()]
    assert [r["cache"] for r in rows] == ["miss", "hit"] and rows[1]["cost_usd"] == 0


def test_replay_raises_friendly_error_on_miss(cfg):
    llm, stub = make(cfg, mode="replay")
    with pytest.raises(ReplayMiss) as e:
        call(llm)
    assert "Replay mode" in str(e.value) and not stub.requests


def test_replay_serves_from_the_cache(cfg):
    llm, _ = make(cfg, mode="auto")
    call(llm)
    replay = LLM(cfg, mode="replay", client=None)
    assert call(replay)["cache"] == "hit"


def test_approved_folder_is_searched(cfg):
    llm, _ = make(cfg)
    call(llm)
    f = next(p for p in cfg.CACHE_DIR.glob("*.json"))
    (cfg.CACHE_DIR / "approved").mkdir()
    f.rename(cfg.CACHE_DIR / "approved" / f.name)
    assert call(LLM(cfg, mode="replay"))["cache"] == "hit"


def test_live_mode_always_calls(cfg):
    llm, stub = make(cfg, mode="live")
    call(llm); call(llm)
    assert len(stub.requests) == 2


def test_per_run_limit_blocks_the_call_that_would_pass_it(cfg):
    from dataclasses import replace
    tight = replace(cfg, PER_RUN_LIMIT_USD=0.0002)
    llm, stub = make(tight)
    with pytest.raises(BudgetExceeded):
        call(llm)
    assert not stub.requests


def test_global_stop_uses_the_ledger_total(cfg):
    cfg.LEDGER_PATH.write_text(json.dumps({"cost_usd": 33.9999}) + "\n")
    llm, stub = make(cfg)
    with pytest.raises(BudgetExceeded) as e:
        call(llm)
    assert "stop" in str(e.value) and not stub.requests


def test_spend_guard_counts_what_the_run_already_spent(cfg):
    from dataclasses import replace
    c2 = replace(cfg, PER_RUN_LIMIT_USD=0.0035)
    llm, _ = make(c2)
    ctx = RunCtx()
    call(llm, ctx, user=other("a"))                 # worst case ~0.0002 + spent 0.0003: fine
    ctx.spent_usd = 0.0034
    with pytest.raises(BudgetExceeded):
        call(llm, ctx, user=other("b"))


def test_no_secret_is_written_anywhere(cfg, monkeypatch, tmp_path):
    secret = "sk-ant-api03-SECRETSECRETSECRET123"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    llm, _ = make(cfg)
    call(llm)

    class Boom:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError(f"401 invalid x-api-key {secret}")
    bad = LLM(cfg, mode="live", client=Boom())
    with pytest.raises(LLMError) as e:
        call(bad, user=other("diff"))
    assert secret not in str(e.value)
    for p in list(cfg.CACHE_DIR.rglob("*")) + [cfg.LEDGER_PATH]:
        if p.is_file():
            assert secret not in p.read_text()


def test_missing_key_gives_a_friendly_error(cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError) as e:
        call(LLM(cfg, mode="auto"))
    assert "ANTHROPIC_API_KEY" in str(e.value)


def test_no_sampling_parameters_are_sent_by_default(cfg):
    """Claude Haiku 5.5 and later reject non-default temperature/top_p/top_k with a 400."""
    assert DEFAULT.TEMPERATURE is None
    llm, stub = make(replace(cfg, TEMPERATURE=DEFAULT.TEMPERATURE))
    call(llm)
    assert len(stub.requests) == 1
    assert not {"temperature", "top_p", "top_k"} & set(stub.requests[0])


def test_temperature_rejection_is_handled_once(cfg):
    llm, stub = make(replace(cfg, TEMPERATURE=0.0), reject_temperature=True)
    r = call(llm)
    assert r["cache"] == "miss" and len(stub.requests) == 2 and "temperature" not in stub.requests[1]
    call(llm, user=other("x"))
    assert "temperature" not in stub.requests[-1] and len(stub.requests) == 3


def test_forced_tool_choice(cfg):
    llm, stub = make(cfg)
    call(llm)
    assert stub.requests[0]["tool_choice"] == {"type": "tool", "name": "submit_plan"}


def test_long_prompt_multiplier_for_haiku():
    p = load_pricing(__import__("fishmarket.config", fromlist=["DEFAULT"]).DEFAULT)
    small = compute_cost(p, HAIKU, {"input_tokens": 1000, "output_tokens": 0})
    big = compute_cost(p, HAIKU, {"input_tokens": 200_000, "output_tokens": 0})
    assert big == pytest.approx(200_000 * 0.10 / 1e6 * 5) and small == pytest.approx(1000 * 0.10 / 1e6)
