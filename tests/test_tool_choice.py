"""The `final` mix puts the analyst on Claude Sonnet 5.5, which returns a 400 for a forced tool_choice
({"type": "tool"} or {"type": "any"}). Such a model gets tool_choice auto, with thinking turned off through
{"type": "between_tools"} so a thinking block cannot eat the max_tokens budget. Models that accept a forced
tool call (Claude Haiku 5.5) keep it: there, a forced call also skips thinking."""
import json

from fishmarket.agents.agent2 import ANALYSIS_TOOL
from fishmarket.fake_agents import StubAnthropicClient, fake_llm
from fishmarket.llm import LLM, RunCtx
from fishmarket.pipeline import run

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"
G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}


def _request(cfg, model):
    stub = StubAnthropicClient(fake_llm(cfg))
    llm = LLM(cfg, mode="live", client=stub)
    user = json.dumps({"statistics": [], "profile": {"region": "Gulf", "species": ["Gulf shrimp"], "business_type":
                       "wild_catch", "customer_segment": "mainstream", "volume_lb_per_month": 1, "as_of": "2026-10-15",
                       "operation": "x"}, "question_type": "sell_or_hold"})
    try:
        llm.call("agent2", "system", user, ANALYSIS_TOOL, model, 2600, RunCtx())
    except Exception:
        pass                      # the fake analyst may reject this tiny input; only the request matters here
    return stub.requests[0]


def test_sonnet_gets_auto_tool_choice_and_no_thinking(cfg):
    req = _request(cfg, SONNET)
    assert req["tool_choice"] == {"type": "auto"}
    assert req["thinking"] == {"type": "between_tools"}


def test_haiku_keeps_the_forced_tool_call(cfg):
    req = _request(cfg, HAIKU)
    assert req["tool_choice"] == {"type": "tool", "name": "submit_analysis"}
    assert "thinking" not in req


def test_final_mix_runs_end_to_end_without_a_fallback(cfg):
    res = run(G01, llm=LLM(cfg, mode="live", client=StubAnthropicClient(fake_llm(cfg))), cfg=cfg, mix="final",
              save=False)
    assert res["status"] == "ok" and res["paid_calls"] == 3
    assert not {"cautious_answer", "template_summary"} & set(res["flags"])
    assert res["analysis"]["direction"] == "hold"
