"""Found in the first live trace (runs/ddb78b8eba.json, G01): the analyst left timing_window empty, so the
Python recommendation sentence came out as "Hold your Gulf shrimp and plan to sell later, ." The window is
deterministic, so Python must supply it whenever the analyst does not, and say so in the trace."""
from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import run
from fishmarket.templates import recommendation_sentence

G01 = {"region": "Gulf", "species": ["Gulf shrimp"], "customer_segment": "mainstream", "volume_lb_per_month": 40000,
       "as_of": "2026-10-15", "operation_type": "wild_catch", "question_type": "sell_or_hold"}


def _analyst_window(cfg, window):
    fake = fake_llm(cfg)
    honest = fake.handlers["agent2"]

    def analyst(system, user, schema, attempt):
        out = honest(system, user, schema, attempt)
        out["timing_window"] = window
        return out

    fake.handlers["agent2"] = analyst
    return fake


def test_recommendation_sentence_never_dangles_without_a_window():
    s = recommendation_sentence("hold", "sell_or_hold", "Gulf shrimp", "", [])
    assert ", ." not in s and not s.endswith(" .") and s.endswith(".")


def test_empty_timing_window_from_the_analyst_is_filled_by_python(cfg):
    res = run(G01, llm=_analyst_window(cfg, ""), cfg=cfg, save=False)
    rep = res["report"]
    assert res["analysis"]["direction"] == "hold"
    assert rep["timing_window"] == "through January"
    assert "Hold your Gulf shrimp and plan to sell later, through January." in rep["summary_md"]
    assert ", ." not in rep["summary_md"]
    assert "template_summary" not in res["flags"]
    grounding = [e for e in res["events"] if e["step"] == "grounding" and e["status"] == "done"]
    assert grounding and "timing_window_filled" in grounding[-1]["detail"].get("python_notes", [])


def test_analyst_window_is_kept_when_given(cfg):
    res = run(G01, llm=_analyst_window(cfg, "through December"), cfg=cfg, save=False)
    assert res["report"]["timing_window"] == "through December"
    assert not any("timing_window_filled" in e["detail"].get("python_notes", []) for e in res["events"])
