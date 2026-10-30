"""Layer 1 for claim C3 (live trace runs/ddb78b8eba.json, G01): the analyst wrote "Holding still pays after
storage cost and shrink" although no hold_net_gain_pct row existed. It was following a conditional prompt line
("If a hold_net_gain_pct row exists, say whether holding still pays") whose condition was false. The fix moves
the condition into the handoff: Python states whether the holding gain was calculated, and the prompt never
asks the analyst to decide that for itself."""
import json

from fishmarket.agents import load_prompt
from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import run

G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}


def _analyst_message(cfg, profile):
    llm = fake_llm(cfg)
    res = run(profile, llm=llm, cfg=cfg, save=False)
    msg = json.loads(next(x["user"] for x in llm.log if x["agent"] == "agent2"))
    return res, msg


def test_the_conditional_instruction_is_gone_from_the_prompt():
    prompt = load_prompt("agent2")
    assert "If a hold_net_gain_pct row exists" not in prompt
    assert "hold_economics" in prompt


def test_no_storage_tells_the_analyst_the_gain_was_not_calculated(cfg):
    res, msg = _analyst_message(cfg, G01)
    assert res["analysis"]["direction"] == "hold"
    assert not any(s["kind"] == "hold_net_gain_pct" for s in msg["statistics"])
    assert msg["hold_economics"] == {"status": "not calculated", "reason": "no storage given"}


def test_with_storage_the_analyst_is_pointed_at_the_statistic(cfg):
    res, msg = _analyst_message(cfg, {**G01, "storage": "frozen"})
    row = next(s for s in msg["statistics"] if s["kind"] == "hold_net_gain_pct")
    assert msg["hold_economics"] == {"status": "calculated", "stat_id": row["id"]}


def test_sell_now_says_holding_was_not_assessed(cfg):
    llm = fake_llm(cfg)
    for case in json.loads(cfg.PRESETS_PATH.read_text()):
        res = run(case["profile"], llm=llm, cfg=cfg, save=False) if case["profile"].get("question_type", "sell_or_hold") == "sell_or_hold" else None
        if res and res["status"] == "ok" and res["analysis"]["direction"] == "sell_now":
            msg = json.loads([x["user"] for x in llm.log if x["agent"] == "agent2"][-1])
            assert msg["hold_economics"] == {"status": "not calculated", "reason": "the rule says sell now"}
            return
    raise AssertionError("no sell_or_hold preset gives sell_now; pick another case")


def test_other_question_types_get_no_hold_economics(cfg):
    llm = fake_llm(cfg)
    for case in json.loads(cfg.PRESETS_PATH.read_text()):
        qt = case["profile"].get("question_type", "sell_or_hold")
        if qt != "sell_or_hold":
            res = run(case["profile"], llm=llm, cfg=cfg, save=False)
            if res["status"] == "ok":
                msg = json.loads([x["user"] for x in llm.log if x["agent"] == "agent2"][-1])
                assert "hold_economics" not in msg, qt
                return
    raise AssertionError("no preset with another question type")
