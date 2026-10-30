"""Lot 3 of the reliability audit: error handling in the LLM wrapper. Every paid call is counted, no
damaged answer is trusted or cached, and nothing retries or waits without saying so."""
import json
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fishmarket.agents.agent1 import PLAN_TOOL
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import LLM, BudgetExceeded, LLMError, RunCtx
from fishmarket.pipeline import run

HAIKU = "claude-haiku-5-5"
SYS, USER = "system prompt", json.dumps({"request_brief": {"species": "Gulf shrimp", "region": "Gulf"}})
G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}


class Client:
    """Answers every request with one fixed response."""

    def __init__(self, content, stop_reason="tool_use", tin=2000, tout=500):
        self.messages = self
        self.requests = []
        self.resp = SimpleNamespace(content=content, stop_reason=stop_reason,
                                    usage=SimpleNamespace(input_tokens=tin, output_tokens=tout))

    def create(self, **kw):
        self.requests.append(kw)
        return self.resp


def call(llm, ctx=None):
    return llm.call("agent1", SYS, USER, PLAN_TOOL, HAIKU, 600, ctx or RunCtx())


def ledger(cfg):
    return [json.loads(x) for x in cfg.LEDGER_PATH.read_text().splitlines()] if cfg.LEDGER_PATH.exists() else []


# ---- 10. a paid answer that is unusable is still counted ------------------------------------------

def test_paid_answer_without_a_tool_call_is_counted(cfg):
    llm = LLM(cfg, mode="live", client=Client([SimpleNamespace(type="text", text="hello")], stop_reason="end_turn"))
    ctx = RunCtx()
    with pytest.raises(LLMError) as e:
        call(llm, ctx)
    rows = ledger(cfg)
    assert len(rows) == 1 and rows[0]["cost_usd"] > 0 and rows[0]["outcome"] == "no_tool_call"
    assert ctx.spent_usd == pytest.approx(rows[0]["cost_usd"]) and ctx.paid_calls == 1
    assert e.value.call["cost_usd"] == pytest.approx(rows[0]["cost_usd"])
    assert not list(cfg.CACHE_DIR.glob("*.json"))


# ---- 9. a truncated answer is not trusted or cached ----------------------------------------------

def test_truncated_answer_is_rejected_counted_and_not_cached(cfg):
    block = SimpleNamespace(type="tool_use", input={"sources": ["SRC-GOV-01"]})
    llm = LLM(cfg, mode="live", client=Client([block], stop_reason="max_tokens", tout=600))
    with pytest.raises(LLMError) as e:
        call(llm)
    assert "cut off" in str(e.value)
    rows = ledger(cfg)
    assert len(rows) == 1 and rows[0]["outcome"] == "truncated" and rows[0]["cost_usd"] > 0
    assert not list(cfg.CACHE_DIR.glob("*.json"))


def test_failed_paid_call_shows_its_cost_in_the_trace(cfg):
    fake = fake_llm(cfg)
    stub = StubAnthropicClient(fake)

    class TruncateAnalyst:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            resp = stub.create(**kw)
            if kw["tool_choice"]["name"] == "submit_analysis":
                resp.stop_reason = "max_tokens"
            return resp

    res = run(G01, llm=LLM(cfg, mode="live", client=TruncateAnalyst()), cfg=cfg, save=False)
    failed = [e for e in res["events"] if e["step"] == "agent2" and e["status"] == "failed"]
    assert failed and failed[0]["cost_usd"] > 0 and "cut off" in failed[0]["headline"]
    assert "cautious_answer" in res["flags"]
    assert res["report"]["cost"]["total_usd"] == pytest.approx(sum(r["cost_usd"] for r in ledger(cfg)))


# ---- 11. a corrupt saved answer is reported, set aside, and never crashes the run ------------------

def _fill_cache(cfg):
    run(G01, llm=LLM(cfg, mode="auto", client=StubAnthropicClient(fake_llm(cfg))), cfg=cfg, save=False)
    files = list(cfg.CACHE_DIR.glob("*.json"))
    assert len(files) == 3
    return files


def test_corrupt_cache_file_raises_a_clear_error_and_is_quarantined(cfg):
    files = _fill_cache(cfg)
    for p in files:
        p.write_text("{not json")
    res = run(G01, llm=LLM(cfg, mode="replay"), cfg=cfg, save=False)
    assert res["status"] == "ok"
    errors = [e for e in res["events"] if e["status"] == "failed" and "unreadable" in e["headline"]]
    assert {e["step"] for e in errors} == {"agent1", "agent2"}
    assert "template_summary" in res["flags"] and "cautious_answer" in res["flags"]
    # each damaged file that was read is set aside; the summary's request changed after the analyst's
    # fallback, so its (also damaged) entry was never read, never served, and stays where it was
    assert len(list(cfg.CACHE_DIR.glob("*.corrupt"))) == len(errors) == 2


def test_cache_entry_missing_fields_is_treated_as_corrupt(cfg):
    files = _fill_cache(cfg)
    for p in files:
        p.write_text(json.dumps({"tool_input": {}}))
    res = run(G01, llm=LLM(cfg, mode="replay"), cfg=cfg, save=False)
    assert res["status"] == "ok"
    assert any("unreadable" in e["headline"] for e in res["events"])


# ---- 12. an unreadable ledger blocks spending instead of under-counting ---------------------------

def test_unreadable_ledger_line_blocks_live_calls(cfg):
    cfg.LEDGER_PATH.write_text('{"cost_usd": 1.0}\n{"cost_usd": 3.9, "broken\n')
    llm = LLM(cfg, mode="live", client=StubAnthropicClient(fake_llm(cfg)))
    with pytest.raises(BudgetExceeded) as e:
        call(llm)
    assert "unreadable" in str(e.value)
    assert llm.ledger.bad_lines() == 1
    assert llm.remaining_budget() == 0.0


def test_unreadable_ledger_does_not_block_cache_hits(cfg):
    llm = LLM(cfg, mode="auto", client=StubAnthropicClient(fake_llm(cfg)))
    call(llm)
    with cfg.LEDGER_PATH.open("a") as f:
        f.write("garbage\n")
    assert call(llm)["cache"] == "hit"


# ---- 13. no hidden SDK retries, bounded wait --------------------------------------------------------

def test_sdk_client_has_no_hidden_retries_and_a_timeout(cfg, monkeypatch):
    seen = {}
    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = lambda **kw: seen.update(kw) or SimpleNamespace(messages=None)
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    LLM(cfg, mode="live")._get_client()
    assert seen["max_retries"] == 0
    assert 0 < seen["timeout"] <= cfg.LLM_TIMEOUT_S


def test_unknown_model_is_a_clean_llm_error(cfg):
    llm = LLM(cfg, mode="live", client=StubAnthropicClient(fake_llm(cfg)))
    with pytest.raises(LLMError):
        llm.call("agent1", SYS, USER, PLAN_TOOL, "claude-unknown-model", 600, RunCtx())


# ---- 16. the temperature fallback is visible -------------------------------------------------------

def test_dropped_temperature_is_reported_in_the_call_and_trace(cfg):
    cfg = replace(cfg, TEMPERATURE=0.0)      # the default sends none; this covers a config that still does
    stub = StubAnthropicClient(fake_llm(cfg), reject_temperature=True)
    llm = LLM(cfg, mode="live", client=stub)
    assert "temperature_dropped" in call(llm)["notes"]
    res = run(G01, llm=LLM(cfg, mode="live", client=StubAnthropicClient(fake_llm(cfg), reject_temperature=True)),
              cfg=cfg, save=False)
    first_ai = next(e for e in res["events"] if e["step"] == "agent1")
    assert "temperature_dropped" in first_ai["detail"].get("llm_notes", [])
