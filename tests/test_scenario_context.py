import pytest

from fishmarket import real_data, scenario_context as sc
from fishmarket.config import DEFAULT
from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import run
from fishmarket.registry import load_catalog

pytestmark = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


def test_every_scenario_species_and_region_is_mapped_explicitly():
    cat = load_catalog(DEFAULT)
    assert set(cat.index) <= set(sc.mapping())                       # no scenario species falls back to guessing
    regions = {r for rl in cat["region_list"] for r in rl}
    assert regions <= set(sc.regions())


def test_words_only_strips_every_number():
    t = "Per the 2021 assessment, both stocks are overfished and subject to overfishing. Rebuilding target dates are 2033 and 2026."
    w = sc.words_only(t)
    assert not any(ch.isdigit() for ch in w) and "overfished" in w and "Rebuilding" not in w


def test_context_items_for_a_region_dependent_species():
    items = sc.build(("Cod",), "Northeast")
    texts = " ".join(i["text"] for i in items)
    assert "Atlantic cod in New England" in texts and "Pacific cod" not in texts
    assert all(not any(ch.isdigit() for ch in i["agent_text"]) for i in items)   # agents never get a real number


def test_unmapped_species_gets_an_honest_note():
    items = sc.build(("Walleye",), "Great Lakes")
    assert len(items) == 1 and "not in the NOAA marine landings file" in items[0]["text"]


def test_pipeline_shows_real_data_separately_and_agents_get_words_only(cfg):
    seen = {}
    base = fake_llm(cfg)
    orig = base.call

    def spy(agent, system, user, *a, **k):
        seen[agent] = user
        return orig(agent, system, user, *a, **k)
    base.call = spy
    p = {"operation_type": "wild_catch", "region": "Northeast", "species": ["Cod"], "customer_segment": "mainstream", "volume_lb_per_month": 40000}
    res = run(p, llm=base, cfg=cfg, save=False)
    rw = res["report"]["real_world"]
    assert any("Atlantic cod in New England" in i["text"] for i in rw)
    assert "real_world_context" in seen["agent2"] and "Real U.S. data" in seen["agent2"]
    import json
    ctx = json.loads(seen["agent2"])["real_world_context"]
    assert all(not any(ch.isdigit() for ch in line) for line in ctx)
    off = run(p, llm=fake_llm(cfg), cfg=cfg.__class__(**{**cfg.__dict__, "SCENARIO_REAL_CONTEXT": False}), save=False)
    assert "real_world" not in off["report"]
    assert res["analysis"]["direction"] == off["analysis"]["direction"]          # real data never changes the fictional result
